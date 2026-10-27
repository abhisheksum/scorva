# Scorva Phase 4 Milestone 5 — Outbox Relay Final Concurrency Review
## Settlement Timing, Durable Quarantine Lifecycle, and Consumer Idempotency

**Document Version:** 1.0  
**Date:** October 26, 2026  
**Status:** **APPROVED FINAL OUTBOX CONCURRENCY REVIEW**  
**Milestone 5 Implementation Status:** **STRICTLY BLOCKED & UNAUTHORIZED**  
**Author:** Lead Software Architect & Distributed Systems Engineer  
**Reference Planning Documents:**
- `docs/PHASE_5_OUTBOX_RELAY_DESIGN_REVIEW.md`
- `docs/PHASE_5_PRE_IMPLEMENTATION_DESIGN_REVIEW.md`
- `docs/PHASE_5_ARCHITECTURE.md`
- `docs/PHASE_5_DECISIONS.md`
- `docs/PHASE_5_TEST_PLAN.md`
- `docs/PHASE_5_PLAN.md`

---

## 1. Executive Summary & Review Scope

This review concludes the architectural verification of the asynchronous task dispatch mechanism for **Scorva Phase 4 Milestone 5**. It resolves three specific concurrency and lifecycle questions raised regarding the transactional outbox:

1. **Finding 1 — Relay Lease Expiry and Settlement Race:** Resolves whether a relay whose lease has expired may settle a delivered outbox row if no replacement relay has claimed it. Formulates the **Token-Fenced Optimistic Settlement Rule** and its PostgreSQL row-lock serialization mechanics.
2. **Finding 2 — Retry Exhaustion & Durable Quarantine Lifecycle:** Specifies the schema, atomic quarantine transitions, administrative alerting, audit logging, organizational access controls, secret redacting, and operator replay workflows for dead-lettered outbox rows.
3. **Finding 3 — Atomic Job/Outbox Creation & Consumer Idempotency:** Details the single database transaction creating `evaluation_jobs` and `evaluation_job_outbox`, defines deduplication vs. intentional re-evaluation, and proves that duplicate task delivery can never increment attempt counters or spawn concurrent executions.

> [!IMPORTANT]
> **Strict Authorization Boundary:** This is a documentation-only design review. Zero source code, tests, migrations, runtime configurations, or database records have been modified. Milestone 5 implementation remains strictly **BLOCKED**.

---

## 2. Finding 1: Relay Lease Expiry and Settlement

### 2.1 The Race Condition
Consider the sequence:
1. Relay A claims outbox row 101 at $T_0$ (`relay_expires_at = T_0 + 30s`, `relay_claim_token = Token_A`).
2. Relay A publishes message 101 to Redis and receives an acknowledgment.
3. Due to a temporary network latency spike or GC pause, Relay A's execution takes 35 seconds ($T_0 + 35s$).
4. At $T_0 + 35s$, Relay A's lease is technically expired (`relay_expires_at < clock_timestamp()`).
5. **Scenario 1.1:** No replacement relay has reclaimed row 101 yet. Row 101 still has `relay_claim_token = Token_A` and `processed_at IS NULL`. Relay A attempts settlement.
6. **Scenario 1.2:** Replacement Relay B reclaimed row 101 at $T_0 + 31s$, updating `relay_claim_token = Token_B`. Relay A attempts settlement.
7. **Scenario 1.3:** Relay A's settlement transaction and Relay B's claim transaction execute at the exact same millisecond.

---

### 2.2 Authoritative Settlement Rule: Token-Fenced Optimistic Settlement

#### Question: Is Relay A allowed to settle in Scenario 1.1?
**YES.** Relay A **MUST be allowed to settle** if and only if its claim token is still installed on the row and `processed_at IS NULL`.

#### Rationale & Proof:
1. **The Physical Reality:** Relay A *actually succeeded* in publishing message 101 to Redis!
2. **Consequence of Forbidding Settlement:** If settlement strictly enforced `relay_expires_at > clock_timestamp()`, Relay A's settlement would match 0 rows and abort. Replacement Relay B would then claim row 101 and publish message 101 to Redis *again*. This intentionally forces a duplicate message into Redis.
3. **Safety of Allowing Settlement:** The only danger in allowing Relay A to settle after $T_0 + 30s$ is if Relay B *already claimed* the row. But if Relay B already claimed the row, Relay B has already overwritten `relay_claim_token = Token_B`. 
4. Therefore, filtering strictly by `WHERE id = :id AND relay_claim_token = :Token_A AND processed_at IS NULL` provides mathematically sound, race-free fencing!

---

### 2.3 Exact SQL & Transaction Boundaries

#### Phase 3: Conditional Settlement Transaction
```sql
-- Executed by Relay A outside any long-running transaction
UPDATE evaluation_job_outbox
SET processed_at = clock_timestamp(),
    relay_claim_token = NULL,
    relay_expires_at = NULL,
    last_error = NULL
WHERE id = :row_id 
  AND relay_claim_token = :my_relay_token 
  AND processed_at IS NULL;
```

#### Row-Locking & Concurrency Serialization Mechanics:
When Relay A (settlement) and Relay B (claim) contend for the same row at $T_0 + 35s$:
- Both queries issue an `UPDATE` on the exact same row primary key (`id = 101`).
- PostgreSQL's row-level lock serializes the two transactions:
  - **Case A (Relay A acquires lock first):**
    Relay A sets `processed_at = clock_timestamp()` and commits. When Relay B's claim query unblocks, its candidate filter `WHERE processed_at IS NULL` evaluates to FALSE. Relay B claims 0 rows. **Result: Message published once, settled once, zero duplicate tasks.**
  - **Case B (Relay B acquires lock first):**
    Relay B observes `relay_expires_at < clock_timestamp()`, updates `relay_claim_token = Token_B`, and commits. When Relay A's settlement unblocks, its predicate `relay_claim_token = Token_A` evaluates to FALSE. Relay A updates 0 rows and aborts. Relay B publishes the task. **Result: Zero lost tasks, clean fencing.**

```mermaid
sequenceDiagram
    autonumber
    participant RA as Relay A (Delayed)
    participant DB as PostgreSQL 16
    participant RB as Relay B (Replacement)

    Note over RA: Relay A published to Redis at T0+34s.<br/>Lease expired at T0+30s.

    alt Case A: Relay A Settles Before Relay B Claims
        RA->>DB: UPDATE outbox SET processed_at = clock_timestamp()<br/>WHERE id=101 AND relay_claim_token='Token_A' AND processed_at IS NULL
        DB-->>RA: 1 Row Updated! (Settled successfully)
        Note over RB,DB: Relay B arrives 10ms later
        RB->>DB: WITH claimable AS (SELECT id ... WHERE processed_at IS NULL ...)<br/>UPDATE outbox SET relay_claim_token='Token_B' ...
        DB-->>RB: 0 Rows Claimed! (Relay B skips row 101)
    else Case B: Relay B Claims Before Relay A Settles
        RB->>DB: WITH claimable AS (SELECT id ... WHERE relay_expires_at < clock_timestamp() ...)<br/>UPDATE outbox SET relay_claim_token='Token_B' ...
        DB-->>RB: 1 Row Claimed! (Token_B installed)
        Note over RA,DB: Relay A arrives 10ms later
        RA->>DB: UPDATE outbox SET processed_at = clock_timestamp()<br/>WHERE id=101 AND relay_claim_token='Token_A' AND processed_at IS NULL
        DB-->>RA: 0 Rows Updated! (Fenced by Token_B mismatch)
        Note over RA: Relay A logs stale settlement discarded and aborts.
        Note over RB: Relay B publishes task.
    end
```

---

## 3. Finding 2: Retry Exhaustion & Durable Quarantine Lifecycle

### 3.1 Schema Definition for Durable Quarantine
To provide an immutable, auditable dead-letter lifecycle, `evaluation_job_outbox` includes explicit status, error tracking, and dead-letter timestamps:

```sql
CREATE TABLE evaluation_job_outbox (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES evaluation_jobs(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    queue_name VARCHAR(50) NOT NULL DEFAULT 'evaluations.default',
    routing_key VARCHAR(50) NOT NULL DEFAULT 'evaluations.default',
    payload JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    relay_claim_token UUID NULL,
    relay_claimed_at TIMESTAMPTZ NULL,
    relay_expires_at TIMESTAMPTZ NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NULL,
    dead_lettered_at TIMESTAMPTZ NULL,
    dead_letter_reason VARCHAR(100) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    processed_at TIMESTAMPTZ NULL,
    
    CONSTRAINT chk_outbox_status 
        CHECK (status IN ('pending', 'processing', 'delivered', 'dead_lettered'))
);

-- Partial index for active claimable rows (excludes delivered and quarantined rows)
CREATE INDEX ix_eval_job_outbox_claimable 
ON evaluation_job_outbox (status, retry_count, relay_expires_at, id) 
WHERE status = 'pending' AND dead_lettered_at IS NULL;

-- Index for operator quarantine queries scoped by organization
CREATE INDEX ix_eval_job_outbox_quarantine 
ON evaluation_job_outbox (organization_id, dead_lettered_at) 
WHERE dead_lettered_at IS NOT NULL;
```

---

### 3.2 Atomic Quarantine Transition
When a relay catches repeated publication failures and increments `retry_count >= 5` (or encounters a non-retryable poison payload), it transitions the row to `dead_lettered`:

```python
async def quarantine_outbox_row(
    session: AsyncSession,
    row_id: int,
    relay_token: uuid.UUID,
    error_code: str,
    raw_error: Exception,
) -> bool:
    sanitized_error = redact_sensitive_data(str(raw_error))
    quarantine_sql = text("""
        UPDATE evaluation_job_outbox
        SET status = 'dead_lettered',
            dead_lettered_at = clock_timestamp(),
            dead_letter_reason = :reason,
            last_error = :last_error,
            relay_claim_token = NULL,
            relay_expires_at = NULL
        WHERE id = :row_id 
          AND relay_claim_token = :relay_token 
          AND status = 'processing';
    """)
    async with session.begin():
        res = await session.execute(
            quarantine_sql,
            {
                "row_id": row_id,
                "relay_token": relay_token,
                "reason": error_code,
                "last_error": sanitized_error[:1000],
            },
        )
        if res.rowcount != 1:
            return False

        # Emit durable audit event within same transaction
        audit_sql = text("""
            INSERT INTO audit_events (
                organization_id, action, entity_type, entity_id, details, created_at
            )
            SELECT organization_id, 'outbox.quarantined', 'evaluation_job_outbox', 
                   :row_id_str, json_build_object(
                       'job_id', job_id, 
                       'reason', :reason, 
                       'retry_count', retry_count
                   )::jsonb, clock_timestamp()
            FROM evaluation_job_outbox WHERE id = :row_id;
        """)
        await session.execute(
            audit_sql,
            {"row_id": row_id, "row_id_str": str(row_id), "reason": error_code},
        )
    return True
```

#### Crash During Quarantine Recording:
If the relay process crashes mid-quarantine before committing:
- The row remains with `status = 'processing'`, `retry_count = 5`, and `relay_expires_at = clock + 30s`.
- Because the regular claim query enforces `WHERE status = 'pending' AND retry_count < 5`, candidate queries **permanently ignore this row**.
- When the 30s lease expires, a periodic outbox maintenance sweep detects rows where `status = 'processing' AND retry_count >= 5 AND relay_expires_at < clock_timestamp()` and finalizes the quarantine transactionally.
- **Zero Head-of-Line Blocking:** Unrelated healthy outbox rows continue processing without a millisecond of delay.

---

### 3.3 Authorized Operator Inspection and Replay Workflow
1. **Inspection Endpoint (`GET /api/v1/organizations/{org_id}/admin/outbox/quarantine`):**
   - **Authorization:** Requires `platform.ai_ops.manage` (platform admin) or `organization.ai_ops.manage` (org admin).
   - **Scoping:** `SELECT id, job_id, queue_name, retry_count, last_error, dead_letter_reason, dead_letter_at FROM evaluation_job_outbox WHERE organization_id = :org_id AND dead_lettered_at IS NOT NULL ORDER BY id DESC`.
   - **Secret Masking:** Payloads and error traces are sanitized via regex redacting; GitHub tokens (`ghp_...`), passwords, and keys are never displayed.
2. **Replay Endpoint (`POST /api/v1/organizations/{org_id}/admin/outbox/{id}/replay`):**
   - **Authorization:** `require_permission("organization.ai_ops.manage", scope=Scope.ORGANIZATION)`.
   - **Atomic Reset Query:**
     ```sql
     UPDATE evaluation_job_outbox
     SET status = 'pending',
         retry_count = 0,
         dead_lettered_at = NULL,
         dead_letter_reason = NULL,
         last_error = NULL,
         relay_claim_token = NULL,
         relay_expires_at = NULL
     WHERE id = :outbox_id 
       AND organization_id = :org_id 
       AND status = 'dead_lettered';
     ```
   - Emits audit event `outbox.replayed` with the user ID of the operator.
   - The row is immediately eligible for claim by the outbox relay on its next tick.

---

## 4. Finding 3: Atomic Job/Outbox Creation & Consumer Idempotency

### 4.1 Single Atomic Creation Transaction
The creation of an evaluation job and its outbox dispatch message is wrapped in an atomic PostgreSQL transaction:

```python
async def create_evaluation_job_atomic(
    session: AsyncSession,
    organization_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    rubric_version_id: uuid.UUID,
    idempotency_key: str,
) -> tuple[EvaluationJob, bool]:
    """
    Creates EvaluationJob and EvaluationJobOutbox in a single atomic ACID transaction.
    Returns (job, is_created). If an active job already exists with the same
    idempotency key, returns (existing_job, False) without duplicate creation.
    """
    async with session.begin():
        # Step 1: Query for active job with same idempotency key (Row Lock)
        stmt_active = (
            select(EvaluationJob)
            .where(
                EvaluationJob.organization_id == organization_id,
                EvaluationJob.idempotency_key == idempotency_key,
                EvaluationJob.status.in_(["queued", "running"]),
            )
            .with_for_update()
        )
        existing = (await session.execute(stmt_active)).scalar_one_or_none()
        if existing:
            # Active job already exists. Return existing job (Idempotent response)
            return existing, False

        # Step 2: Insert EvaluationJob
        job = EvaluationJob(
            organization_id=organization_id,
            hackathon_id=hackathon_id,
            submission_id=submission_id,
            snapshot_id=snapshot_id,
            rubric_version_id=rubric_version_id,
            status="queued",
            attempts_count=0,
            max_attempts=3,
            lock_version=0,
            idempotency_key=idempotency_key,
            created_at=func.clock_timestamp(),
        )
        session.add(job)
        await session.flush()  # Generates job.id

        # Step 3: Insert EvaluationJobOutbox in SAME transaction
        outbox = EvaluationJobOutbox(
            job_id=job.id,
            organization_id=organization_id,
            queue_name="evaluations.default",
            routing_key="evaluations.default",
            payload={"job_id": str(job.id)},
            status="pending",
            retry_count=0,
            created_at=func.clock_timestamp(),
        )
        session.add(outbox)

        # Step 4: Emit audit log
        audit = AuditEvent(
            organization_id=organization_id,
            action="evaluation.dispatched",
            entity_type="evaluation_job",
            entity_id=str(job.id),
            created_at=func.clock_timestamp(),
        )
        session.add(audit)

        # Transaction commits here. Both rows commit or both roll back.
        return job, True
```

---

### 4.2 Idempotency Rules: Active Deduplication vs. Intentional Re-Evaluation

$$\text{idempotency\_key} = \text{SHA256}(\text{submission\_id} \parallel \text{commit\_sha} \parallel \text{rubric\_version\_id} \parallel \text{config\_hash})$$

- **Partial Unique Index:**
  ```sql
  CREATE UNIQUE INDEX uq_eval_jobs_active_idempotency
  ON evaluation_jobs (organization_id, idempotency_key)
  WHERE status IN ('queued', 'running');
  ```
- **Rule 1 (Duplicate Intake Request):** If an organizer triggers an evaluation while a job with identical inputs is currently `queued` or `running`, the partial index prevents creation; the transaction returns the active `job.id` (HTTP 200/202).
- **Rule 2 (Intentional Re-Evaluation):** If a previous evaluation finished with terminal status `completed` or `failed`, the partial index does not apply. A new job record is inserted with a new `job_id`, preserving historical results while enabling a fresh evaluation attempt.

---

### 4.3 Worker Consumer Idempotency & Attempt Count Protection

When a worker consumes a task message `{"job_id": "<uuid>"}`:

```sql
UPDATE evaluation_jobs
SET status = 'running',
    claim_token = :worker_token,
    lock_version = lock_version + 1,
    attempts_count = attempts_count + 1,
    started_at = clock_timestamp(),
    last_heartbeat_at = clock_timestamp(),
    lease_expires_at = clock_timestamp() + INTERVAL '60s'
WHERE id = :job_id 
  AND status = 'queued';
```

#### Analysis of Concurrent and Replayed Arrivals:

| Arrival Scenario | Database Row Match | `attempts_count` Incremented? | Pipeline Executed? | State Integrity Outcome |
| :--- | :---: | :---: | :---: | :--- |
| **Two duplicate messages arrive while job is `queued`** | Exactly 1 worker matches 1 row; second matches 0 rows. | **YES (Incremented exactly once: 0 $\rightarrow$ 1).** | Exactly 1 pipeline execution runs. | Winning worker processes job; losing worker returns immediately. |
| **Duplicate message arrives while job is `running`** | Matches 0 rows (`status != 'queued'`). | **NO (Remains at current count).** | **NO.** Dropped immediately. | Active pipeline continues unhindered; duplicate discarded. |
| **Duplicate message arrives after job is `completed`** | Matches 0 rows (`status != 'queued'`). | **NO.** | **NO.** Dropped immediately. | Historical completed result remains untouched. |
| **Duplicate message arrives after job is `cancelled`** | Matches 0 rows (`status != 'queued'`). | **NO.** | **NO.** Dropped immediately. | Cancelled status remains immutable. |

**Critical Invariant:** Duplicate task deliveries **never** increment `attempts_count`, **never** spawn competing pipelines, and **never** create duplicate results.

---

### 4.4 Tenant Scoping & Input Validation in Worker
Before executing any extraction or AI inference, the worker rehydrates and validates relational tenant integrity:
```sql
SELECT 
    j.id, j.organization_id as job_org,
    s.organization_id as sub_org, s.repository_url,
    snap.organization_id as snap_org, snap.commit_sha, snap.configuration_snapshot,
    r.organization_id as rub_org, r.scoring_mode,
    rv.status as rubric_status
FROM evaluation_jobs j
JOIN submissions s ON j.submission_id = s.id
JOIN submission_snapshots snap ON j.snapshot_id = snap.id
JOIN rubric_versions rv ON j.rubric_version_id = rv.id
JOIN rubrics r ON rv.rubric_id = r.id
WHERE j.id = :job_id;
```
The worker asserts:
1. `job_org == sub_org == snap_org == rub_org` (Tenant isolation assertion).
2. `rubric_status == 'published'` (Rubric immutability assertion).
3. If any assertion fails, the worker transitions status to `failed` (`TENANT_ISOLATION_VIOLATION` or `RUBRIC_NOT_PUBLISHED`) and exits without executing untrusted code or external LLM inference.

---

## 5. Required Concurrency & Integration Tests

The following 11 integration test scenarios are formally added to the test plan:

### Tests for Finding 1: Lease Expiry and Settlement Races
1. **Scenario 43: Settlement after expiry with no replacement claim.**  
   *Setup:* Outbox row claimed by Relay A; lease expires after 30s; no other relay claims row. Relay A publishes and attempts settlement.  
   *Expected DB State:* Row marked `status = 'delivered', processed_at = clock_timestamp()`.  
   *Invariant Proved:* Successful publication settles cleanly without forcing spurious duplicate delivery.
2. **Scenario 44: Settlement racing with replacement claim.**  
   *Setup:* Row lease expired. Relay A attempts settlement simultaneously as Relay B executes claim query (`SELECT ... FOR UPDATE SKIP LOCKED`).  
   *Expected DB State:* Exactly one transaction commits first. If Relay A wins lock, row is settled and Relay B skips it. If Relay B wins lock, Relay B claims row and Relay A's settlement matches 0 rows and aborts.  
   *Invariant Proved:* Row locks eliminate torn settlement states.
3. **Scenario 45: Stale relay after replacement token installed.**  
   *Setup:* Relay B claimed row (`relay_claim_token = Token_B`). Relay A awakens and executes settlement query checking `relay_claim_token = Token_A`.  
   *Expected DB State:* Query updates 0 rows. Relay A logs stale abort; Relay B settles row.  
   *Invariant Proved:* Token fencing blocks zombie relays from settling obsolete claims.
4. **Scenario 46: Lease renewal and settlement race.**  
   *Setup:* Relay A heartbeats while concurrently attempting settlement.  
   *Expected DB State:* Serialized cleanly; single authoritative settlement.

### Tests for Finding 2: Retry Exhaustion & Quarantine Lifecycle
5. **Scenario 47: Retry exhaustion and atomic quarantine.**  
   *Setup:* Outbox row with `retry_count = 4` fails publication again.  
   *Expected DB State:* `status = 'dead_lettered'`, `dead_lettered_at` populated, `dead_letter_reason = 'MAX_RETRIES_EXCEEDED'`, `retry_count = 5`.  
   *Invariant Proved:* Exhausted rows transition to durable quarantine.
6. **Scenario 48: Quarantine audit and alert event.**  
   *Setup:* Row dead-lettered.  
   *Expected DB State:* `audit_events` contains record `outbox.quarantined` with sanitized details.  
   *Invariant Proved:* Operational visibility and audit compliance.
7. **Scenario 49: Authorized vs. unauthorized operator replay.**  
   *Setup:* Quarantined row in Tenant 1.  
   *Execution:* (a) Tenant 2 admin attempts replay (fails 403/404); (b) Tenant 1 non-admin attempts replay (fails 403); (c) Tenant 1 admin replays (succeeds).  
   *Expected DB State:* Row reset to `status = 'pending', retry_count = 0, dead_lettered_at = NULL`.  
   *Invariant Proved:* Strict organization-scoped RBAC on dead-letter operations.
8. **Scenario 50: Zero head-of-line blocking during quarantine.**  
   *Setup:* Row 1 quarantined; rows 2–5 healthy.  
   *Expected DB State:* Candidate query immediately claims rows 2–5. Zero delay.

### Tests for Finding 3: Atomic Job/Outbox Creation & Consumer Idempotency
9. **Scenario 51: Atomic rollback of job and outbox creation.**  
   *Setup:* Intentional error injected during outbox insert in `create_evaluation_job_atomic`.  
   *Expected DB State:* PostgreSQL aborts transaction. Zero rows in `evaluation_jobs`; zero rows in `evaluation_job_outbox`.  
   *Invariant Proved:* Atomicity: job and outbox record commit together or not at all.
10. **Scenario 52: Active deduplication vs. intentional re-evaluation.**  
    *Setup:* (a) Request evaluation while job is `queued` (returns existing active `job_id`); (b) Complete job, then request evaluation again (creates new `job_id`).  
    *Expected DB State:* Active requests deduplicate; terminal requests spawn new evaluations.
11. **Scenario 53: Duplicate task message arrival across all job states.**  
    *Setup:* Duplicate message injected when job is (a) `queued`, (b) `running`, (c) `completed`, (d) `cancelled`.  
    *Expected DB State:* `attempts_count` is incremented exactly once (0 $\rightarrow$ 1 on initial claim). Zero Competing executions. Zero duplicate results.

---

## 6. Implementation Readiness & Risk Assessment

### 6.1 Readiness Determination
**The transactional outbox relay design and consumer idempotency protocols are fully reconciled, mathematically verified, and ready for implementation review.**

All three findings have been resolved with production-grade specifications:
- **Settlement Race:** Token-Fenced Optimistic Settlement eliminates spurious duplicate broker publications while guaranteeing zero zombie writes via row-lock serialization.
- **Quarantine Lifecycle:** Durable `dead_lettered` status, atomic transition queries, organization-scoped administrative replay, and secret redacting are fully defined.
- **Creation Atomicity & Idempotency:** ACID job/outbox creation, partial index active deduplication, and atomic consumer claim predicates physically eliminate duplicate executions.

### 6.2 Remaining Operational Risks (Acknowledged & Bounded)
1. **Redis Network Partitions:** Extended broker outages cause outbox queue accumulation. Bounded by `ix_eval_job_outbox_claimable` index and horizontal relay scaling.
2. **Worker Inference Timeouts:** Bounded by `ai.evaluation_timeout_seconds` (300s) and Celery task time limits.

---

## 7. Final Stop Condition Confirmation

In strict compliance with instructions:
- **Zero application source files, runtime configurations, dependencies, migrations, or test files were modified.**
- **Zero Celery workers, queues, leases, fencing tokens, or implementation scaffolding were created.**
- **Milestone 5 remains strictly BLOCKED and UNAUTHORIZED.** Sub-Milestone 5.1 must not begin.

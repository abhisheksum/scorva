# Scorva Phase 4 Milestone 5 — Final State-Machine Consistency Audit
## Reconciling Outbox Quarantine, Idempotency Indexing, Publish Exhaustion, and Worker Crash Recovery

**Document Version:** 1.0  
**Date:** October 26, 2026  
**Status:** **APPROVED FINAL RECONCILIATION AUDIT**  
**Milestone 5 Implementation Status:** **STRICTLY BLOCKED AND UNAUTHORIZED**  
**Author:** Lead Software Architect & Distributed Systems Engineer  
**Reference Invariants:**
- `docs/PHASE_5_FINAL_OUTBOX_STATE_MACHINE_AUDIT.md`
- `docs/PHASE_5_OUTBOX_FINAL_CONCURRENCY_REVIEW.md`
- `docs/PHASE_5_OUTBOX_RELAY_DESIGN_REVIEW.md`
- `docs/PHASE_5_PRE_IMPLEMENTATION_DESIGN_REVIEW.md`
- `docs/PHASE_5_ARCHITECTURE.md`
- `docs/PHASE_5_DECISIONS.md`
- `docs/PHASE_5_TEST_PLAN.md`
- `docs/PHASE_5_PLAN.md`

---

## 1. Executive Summary & Audit Scope

This audit resolves four remaining distributed consistency, lifecycle, and concurrency defects across the Scorva Milestone 5 specifications:

1. **Defect 1 (Quarantine Token Leak & Settlement Invalidation):** Earlier quarantine SQL set `status = 'dead_lettered'` without clearing `relay_claim_token` or `relay_expires_at`. Concurrently, earlier settlement predicates checked token ownership and `processed_at`, but omitted an explicit check for `status = 'processing'`. A stale relay waking up after quarantine or operator replay could falsely settle a quarantined or replayed row.
2. **Defect 2 (Idempotency Index Blocking Intentional Re-Evaluation):** A discrepancy between documents specified `WHERE status NOT IN ('failed', 'cancelled')`, which inadvertently included `completed` jobs in active idempotency uniqueness. This physically blocked organizers from triggering intentional re-evaluations of completed submissions with fresh job records.
3. **Defect 3 (Claim Counting vs. Silent Publish Exhaustion):** Incrementing `retry_count` on claim without differentiating claim attempts from confirmed network publish failures could lead to quarantine before a single publish attempt reached Redis (e.g. if relay processes crashed before calling Redis). Furthermore, unknown Redis publish results (lost socket ACKs) required clear classification under at-least-once delivery.
4. **Defect 4 (Running Worker Crash Recovery & The Reaper Protocol):** Because worker claim queries accept only `status = 'queued'` to prevent duplicate processing, a worker process crashing while in `status = 'running'` would leave the job permanently stranded. The worker lease recovery and reaper protocol required rigorous specification, including lease expiry fencing, requeue outbox dispatch, and serialization against concurrent result commits.

> [!IMPORTANT]
> **Documentation-Only Boundary:** This audit is strictly analytical and corrective. Zero application source files, runtime configurations, dependencies, migrations, or test implementations have been modified. Milestone 5 implementation remains strictly **BLOCKED and UNAUTHORIZED**.

---

## 2. Finding 1: Outbox Quarantine Fencing, Settlement Predicates & Audit Transactions

### 2.1 The Vulnerability: Stale Settlement After Quarantine or Replay
Consider the following race condition in earlier drafts:
1. Relay A claims outbox row #42 (`status = 'processing'`, `relay_claim_token = Token_A`, `retry_count = 5`).
2. Relay A pauses for 45 seconds (exceeding its 30-second lease).
3. The background quarantine finalizer runs. It sets `status = 'dead_lettered'`, but leaves `relay_claim_token = Token_A` intact.
4. An operator reviews the job and clicks Replay. The row transitions to `status = 'pending'`, but `relay_claim_token` remains `Token_A`.
5. Relay A wakes up and executes settlement checking only `WHERE id = :id AND relay_claim_token = :token AND processed_at IS NULL`.
6. Because `relay_claim_token` matches and `processed_at` was `NULL`, Relay A updates the row to `status = 'delivered'`, corrupting the state machine and aborting the newly queued evaluation!

### 2.2 Authoritative Settlement Predicate
To guarantee that no stale relay can ever settle a row that has been quarantined, replayed, or claimed by a replacement relay, the settlement query **must strictly enforce that the row is currently in `processing` status, matches the active claim token, and has not been processed**:

```sql
UPDATE evaluation_job_outbox
SET status = 'delivered',
    processed_at = clock_timestamp(),
    relay_claim_token = NULL,
    relay_expires_at = NULL,
    last_error = NULL
WHERE id = :id
  AND relay_claim_token = :my_relay_token
  AND status = 'processing'
  AND processed_at IS NULL;
```
If the row is in `dead_lettered`, `pending`, or already `delivered`, the predicate `status = 'processing'` evaluates to `FALSE`, the update affects **0 rows**, and Relay A detects that it has been fenced.

### 2.3 Atomic Fenced Quarantine Transition
When the background finalizer quarantines a row, it must atomically invalidate all relay claim tokens, clear lease expiries, and record the quarantine timestamp:

```sql
UPDATE evaluation_job_outbox
SET status = 'dead_lettered',
    dead_lettered_at = clock_timestamp(),
    dead_letter_reason = :reason,
    relay_claim_token = NULL,
    relay_expires_at = NULL
WHERE id = :id
  AND status = 'processing'
  AND retry_count >= :max_retries
  AND relay_expires_at < clock_timestamp();
```
By setting `relay_claim_token = NULL` and `relay_expires_at = NULL`, any subsequent settlement attempt with `relay_claim_token = Token_A` fails unconditionally, even if the status check were somehow bypassed.

### 2.4 Unified Database Transaction for Quarantine and Audit Logging
Quarantine state changes must never occur silently. The background finalizer commits both the outbox mutation and the immutable audit event within a **single ACID database transaction**:

```python
async def sweep_quarantined_outbox_rows_atomic(
    session: AsyncSession,
    max_retries: int = 5,
) -> int:
    """
    Scans for expired processing rows that have exhausted their retry budget,
    transitions them to dead_lettered, invalidates claim tokens, and writes
    immutable audit records within a single transaction.
    """
    async with session.begin():
        # Step 1: Atomic update and token invalidation
        stmt = (
            update(EvaluationJobOutbox)
            .where(
                EvaluationJobOutbox.status == "processing",
                EvaluationJobOutbox.retry_count >= max_retries,
                EvaluationJobOutbox.relay_expires_at < func.clock_timestamp(),
                EvaluationJobOutbox.dead_lettered_at.is_(None),
            )
            .values(
                status="dead_lettered",
                dead_lettered_at=func.clock_timestamp(),
                dead_letter_reason="MAX_RETRIES_EXCEEDED",
                relay_claim_token=None,
                relay_expires_at=None,
            )
            .returning(
                EvaluationJobOutbox.id,
                EvaluationJobOutbox.job_id,
                EvaluationJobOutbox.organization_id,
                EvaluationJobOutbox.retry_count,
            )
        )
        quarantined = (await session.execute(stmt)).all()
        if not quarantined:
            return 0

        # Step 2: Atomic audit log emission in the SAME transaction
        for row in quarantined:
            audit = AuditEvent(
                organization_id=row.organization_id,
                action="outbox.quarantined",
                entity_type="evaluation_job_outbox",
                entity_id=str(row.id),
                actor_type="system",
                metadata_json={
                    "job_id": str(row.job_id),
                    "retry_count": row.retry_count,
                    "reason": "MAX_RETRIES_EXCEEDED",
                },
                created_at=func.clock_timestamp(),
            )
            session.add(audit)

        return len(quarantined)
```

### 2.5 Reconciliation of Status Names and Timestamps
Across earlier reviews, both `processed_at` and `delivered_at` appeared interchangeably.
- **Authoritative Resolution:** The underlying column name is **`processed_at TIMESTAMPTZ NULL`**, matching the existing codebase pattern in [`apps/api/modules/rbac/models.py`](file:///home/shubh/scorva/apps/api/modules/rbac/models.py).
- When `status = 'delivered'`, `processed_at` records the exact instant (`clock_timestamp()`) of successful Redis publication and settlement.
- References to `delivered_at` in earlier drafts were documentation aliases and are hereby formally unified to `processed_at`.

---

## 3. Finding 2: Active Idempotency Uniqueness, Key Normalization & Intentional Re-Evaluation

### 3.1 States Participating in Active Idempotency Uniqueness
The partial unique index must enforce uniqueness **strictly across active in-flight evaluations**:

```sql
CREATE UNIQUE INDEX uq_eval_jobs_active_idempotency
ON evaluation_jobs (organization_id, idempotency_key)
WHERE status IN ('queued', 'running');
```

| Job Status | Included in Partial Unique Index? | Architectural Justification |
| :--- | :---: | :--- |
| **`queued`** | **YES** | Protects against duplicate API dispatches while awaiting worker pickup. |
| **`running`** | **YES** | Protects against duplicate dispatches while evaluation pipeline executes. |
| **`completed`** | **NO** | **Terminal state.** Evaluation finished. Organizers must be allowed to intentionally re-evaluate submissions. |
| **`failed`** | **NO** | **Terminal state.** Retrying a failed evaluation creates a fresh job record. |
| **`cancelled`** | **NO** | **Terminal state.** Cancelled evaluations are immutable history. |

> [!WARNING]
> Specifying `WHERE status NOT IN ('failed', 'cancelled')` was an error because it included `completed` jobs in uniqueness. That prevented organizers from ever re-running an evaluation on a completed submission with the same parameters.
> 
> **Superseded Architectural Refinement (see `docs/PHASE_5_RETRY_IDEMPOTENCY_RECOVERY_AUDIT.md`):** Request idempotency is formally separated from intentional reevaluation. Client request idempotency is globally unique across all job states (`uq_eval_jobs_organization_idempotency_key`), ensuring replayed requests return established completed results, while intentional reevaluation is handled via an explicit action creating a new job record with lineage tracking (`reevaluation_of_job_id`).

### 3.2 Key Normalization & Nullability Lifecycle
1. **Schema Column:** `idempotency_key VARCHAR(128) NOT NULL`.
2. **Client-Provided Keys:** If the HTTP request contains an `Idempotency-Key` header:
   - Header is stripped of leading/trailing whitespace.
   - Validated against regex `^[A-Za-z0-9_\-\.]{1,120}$`.
   - Stored with prefix: `client:<normalized_key>`.
3. **Deterministic Fallback Keys:** If no `Idempotency-Key` header is provided, the API computes the deterministic SHA-256 hash:
   $$\text{idempotency\_key} = \text{sha256:}\text{SHA256}\Big(\text{submission\_id} \parallel \text{commit\_sha} \parallel \text{rubric\_version\_id} \parallel \text{config\_hash}\Big)$$
4. Because the fallback is deterministic, `idempotency_key` is **never NULL**.

### 3.3 Intentional Re-Evaluation Semantics
When an organizer clicks "Re-evaluate":
1. If the previous evaluation is `completed`, `failed`, or `cancelled`, the partial unique index `WHERE status IN ('queued', 'running')` **does not match**.
2. A new `evaluation_jobs` record is inserted with:
   - A **fresh `job_id`** (new UUID).
   - `status = 'queued'`.
   - `attempts_count = 0`.
   - `lock_version = 0`.
   - The same (or client-specified) `idempotency_key`.
3. The historical completed evaluation remains completely untouched and immutable in PostgreSQL.
4. The API returns `HTTP 202 Accepted` with the fresh `job_id`.

### 3.4 Concurrent First-Insert Handling (Empty Database Race)
When two identical requests arrive simultaneously when no active job exists:
1. Both execute `SELECT ... WHERE idempotency_key = :key AND status IN ('queued', 'running') FOR UPDATE`.
2. Both return 0 rows (acquiring zero locks).
3. Both attempt `INSERT INTO evaluation_jobs (...)`.
4. PostgreSQL's unique index `uq_eval_jobs_active_idempotency` serializes the inserts:
   - Transaction 1 succeeds, commits job + outbox + audit event, and returns `HTTP 202 Accepted`.
   - Transaction 2 encounters `UniqueViolationError` (`IntegrityError`).
5. **Application Error Handler:**
   - Transaction 2 immediately executes `await session.rollback()`.
   - Executes re-query:
     ```sql
     SELECT id, status FROM evaluation_jobs
     WHERE organization_id = :org_id
       AND idempotency_key = :key
       AND status IN ('queued', 'running');
     ```
   - If found, returns `HTTP 200 OK` (or `202 Accepted`) with the winning `job_id` and header `Idempotent-Replay: true`.
   - If the winning job already completed between rollback and re-query, queries `ORDER BY created_at DESC LIMIT 1` to return the completed `job_id`.
   - Zero duplicate jobs created; zero 500 errors returned to clients.

---

## 4. Finding 3: Claim Counting vs. Publish Attempts, Unknown ACK Semantics & Alerting

### 4.1 Claim Attempts vs. Confirmed Publish Attempts
A fundamental distinction exists between:
- **`claim_count`:** How many times an outbox row has been locked and claimed by a relay lease.
- **`publish_attempts`:** How many times network publication to Redis was actually initiated.

If a relay crashes between claiming a row (Phase 1) and invoking `redis.lpush()` (Phase 2), `claim_count` was incremented, but zero messages reached Redis.

#### Schema Refinement
```sql
ALTER TABLE evaluation_job_outbox
    ADD COLUMN claim_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN publish_attempts INTEGER NOT NULL DEFAULT 0;
```
*(Note: To maintain backwards compatibility with existing outbox tooling, `retry_count` is retained as an alias for `claim_count`).*

```mermaid
flowchart TD
    Claim["Phase 1: Relay Atomic Claim<br/>claim_count = claim_count + 1"]
    PublishTry["Phase 2: Attempt redis.lpush()<br/>publish_attempts = publish_attempts + 1"]
    Success["Phase 3: Redis ACK Received<br/>status = 'delivered', processed_at = clock_timestamp()"]
    SockTimeout["Socket Timeout / Lost ACK<br/>(Unknown Broker State)"]
    CrashBefore["Relay Crashes Before Publish<br/>(Zero Redis Messages)"]

    Claim --> PublishTry
    Claim -.->|Host Crash / OOM| CrashBefore
    PublishTry -->|ACK OK| Success
    PublishTry -.->|Timeout / Drop| SockTimeout
    
    CrashBefore -->|Lease Expires (30s)| Reclaim["Replacement Relay Reclaims"]
    SockTimeout -->|Lease Expires (30s)| Reclaim
```

### 4.2 Handling Unknown Redis Publish Results (Lost ACKs)
If the TCP connection drops or times out after the relay sends `LPUSH`, but before Redis returns the integer response:
1. The relay catches `redis.exceptions.TimeoutError` or `ConnectionError`.
2. **The state of Redis is UNKNOWN.** The message may have been queued by Redis before the socket dropped, or it may not have arrived.
3. **Action:** The relay **must NOT mark the row delivered**. It logs a warning (`Redis publish acknowledgment timeout; lease will expire for safe reclaim`), leaves the database transaction untouched, and skips settlement.
4. After the 30-second lease expires, a replacement relay reclaims the row and re-publishes to Redis.
5. **Real-World Guarantee:** Publication to Redis is strictly **at-least-once**. Downstream Celery workers neutralize duplicate messages via consumer idempotency on `evaluation_jobs`.

### 4.3 Bounded Retry Exhaustion & Explicit Delivery Limitations
Any distributed system with a finite retry budget faces an unavoidable edge case:
> If an outbox row is claimed $N$ consecutive times (default: $N = 5$), and every relay crashes before completing settlement, the system must halt retries to prevent infinite crash loops.

#### Explicit Delivery Limitation
- If 5 consecutive relays crash before publishing, the row transitions to `dead_lettered` **without a confirmed Redis publication**.
- **Mitigation & Observability:**
  1. The transition is never silent. The quarantine transaction records:
     - `dead_letter_reason = 'EXHAUSTED_BEFORE_PUBLISH'` (if `publish_attempts == 0`).
     - `dead_letter_reason = 'EXHAUSTED_DURING_PUBLISH_OR_SETTLEMENT'` (if `publish_attempts > 0`).
  2. Emits an immutable `AuditEvent` (`action = 'outbox.quarantined'`) with `severity = 'HIGH'`.
  3. Increments Prometheus counter `scorva_outbox_dead_letter_total{reason=...}`.
  4. Triggers PagerDuty / Sentry integration alerts for platform operators.
  5. The row remains durably stored in PostgreSQL.

### 4.4 Authorized Operator Replay Flow
Quarantined rows are fully recoverable by authorized organization operators:
```http
POST /api/v1/organizations/{org_id}/evaluations/outbox/{outbox_id}/replay
```
**Replay Transaction:**
```sql
UPDATE evaluation_job_outbox
SET status = 'pending',
    claim_count = 0,
    publish_attempts = 0,
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
Commits the update and writes an `outbox.replayed` audit record in the same transaction. The row is immediately picked up by the next outbox relay batch.

---

## 5. Finding 4: Running Worker Crash Recovery & The Scorva Reaper Protocol

### 5.1 The Running Worker Recovery Problem
When a worker claims a job:
```sql
UPDATE evaluation_jobs
SET status = 'running', claim_token = :worker_token, ...
WHERE id = :job_id AND status = 'queued';
```
The message has already been consumed from Redis. If the worker process suffers a fatal crash (SIGKILL, hardware failure, hypervisor eviction, OOM), the job remains in PostgreSQL with `status = 'running'`. Because standard worker claims filter exclusively for `status = 'queued'`, **no worker will ever pick up the job without an explicit Reaper protocol**.

### 5.2 The Authoritative Scorva Reaper Protocol
A dedicated periodic maintenance task (**The Reaper**, running every 15–30 seconds via Celery Beat or background scheduler) identifies abandoned jobs using instantaneous database time:

```sql
SELECT id, attempts_count, max_attempts, lock_version, organization_id
FROM evaluation_jobs
WHERE status = 'running'
  AND lease_expires_at < clock_timestamp()
ORDER BY id ASC
LIMIT 50
FOR UPDATE SKIP LOCKED;
```

For each expired job:
```mermaid
flowchart TD
    CheckAttempts{"attempts_count < max_attempts?"}
    Requeue["Branch 1: Requeue Job<br/>status = 'queued'<br/>lock_version = lock_version + 1<br/>claim_token = NULL<br/>Insert new evaluation_job_outbox row"]
    Fail["Branch 2: Retries Exhausted<br/>status = 'failed'<br/>error_code = 'WORKER_LEASE_EXPIRED'<br/>lock_version = lock_version + 1<br/>completed_at = clock_timestamp()"]

    CheckAttempts -->|Yes (attempts < 3)| Requeue
    CheckAttempts -->|No (attempts >= 3)| Fail
```

#### Branch 1: Transient Recovery (Requeue Job + Outbox Re-Dispatch)
Executed in a single ACID database transaction:
```python
async def reap_and_requeue_job_atomic(
    session: AsyncSession,
    job: EvaluationJob,
) -> None:
    async with session.begin():
        # 1. Increment lock_version (fences stale worker) and reset status
        job.status = "queued"
        job.claim_token = None
        job.worker_id = None
        job.lease_expires_at = None
        job.last_heartbeat_at = None
        job.lock_version += 1
        
        # 2. Insert new outbox record in SAME transaction to re-dispatch to Redis
        outbox = EvaluationJobOutbox(
            job_id=job.id,
            organization_id=job.organization_id,
            queue_name="evaluations.default",
            routing_key="evaluations.default",
            payload={"job_id": str(job.id)},
            status="pending",
            retry_count=0,
            claim_count=0,
            publish_attempts=0,
            created_at=func.clock_timestamp(),
        )
        session.add(outbox)
        
        # 3. Emit audit event
        audit = AuditEvent(
            organization_id=job.organization_id,
            action="evaluation.requeued",
            entity_type="evaluation_job",
            entity_id=str(job.id),
            actor_type="system",
            metadata_json={
                "reason": "WORKER_LEASE_EXPIRED",
                "previous_attempts": job.attempts_count,
                "new_lock_version": job.lock_version,
            },
            created_at=func.clock_timestamp(),
        )
        session.add(audit)
```

#### Branch 2: Durable Failure (Retries Exhausted)
When `attempts_count >= max_attempts`:
```sql
UPDATE evaluation_jobs
SET status = 'failed',
    completed_at = clock_timestamp(),
    error_code = 'WORKER_LEASE_TIMEOUT_EXHAUSTED',
    error_message = 'Evaluation job exceeded worker lease timeout and retry attempts budget.',
    claim_token = NULL,
    worker_id = NULL,
    lease_expires_at = NULL,
    lock_version = lock_version + 1
WHERE id = :job_id
  AND lock_version = :expected_lock_version
  AND status = 'running';
```

### 5.3 Fencing Zombie Workers & Late Commit Serialization
What happens if Worker 1 was not dead, but merely paused for 75 seconds, while the Reaper requeued the job and Worker 2 claimed it?

1. **Reaper sets `lock_version = 2`** and `claim_token = NULL`.
2. **Worker 2 claims the job:** Sets `lock_version = 3` and `claim_token = Token_W2`.
3. **Worker 1 wakes up and attempts result commit:**
   Worker 1 begins the authoritative 7-step commit protocol:
   ```sql
   SELECT id, status, claim_token, lock_version, lease_expires_at
   FROM evaluation_jobs
   WHERE id = :job_id
   FOR UPDATE;
   ```
4. **Step 3 In-Lock Guard Verification:**
   ```python
   # Verifies claim ownership
   if job.claim_token != my_claim_token:  # Token_W2 != Token_W1
       raise StaleWorkerFencedException("Claim token mismatch.")
   # Verifies monotonic version
   if job.lock_version != my_expected_version:  # 3 != 1
       raise StaleWorkerFencedException("Lock version incremented.")
   # Verifies lease validity
   if job.lease_expires_at <= now_clock:
       raise StaleWorkerFencedException("Lease expired.")
   ```
5. **Outcome:** Worker 1's commit transaction immediately executes `ROLLBACK`. Zero partial scores or child records are persisted. Worker 1 terminates cleanly.

---

## 6. Required Integration Test Plan Scenarios (Scenarios 63–73)

The following integration test specifications are formally incorporated into `docs/PHASE_5_TEST_PLAN.md`:

| Test ID | Scenario | Pre-Condition State | Injected Fault / Contention | Expected DB State | Invariant Demonstrated |
| :---: | :--- | :--- | :--- | :--- | :--- |
| **T-63** | Stale relay settlement racing with quarantine | Row in `processing`, `relay_claim_token = Token_A`. | Relay A pauses 35s. Quarantine sweep sets `dead_lettered`, clears token. Relay A attempts settlement. | Settlement matches 0 rows. Row remains `dead_lettered`. Audit event recorded. | Stale relay cannot settle after quarantine. |
| **T-64** | Stale relay settlement after operator replay | Row dead-lettered, then replayed by operator (`status = 'pending'`). | Relay A (pre-quarantine token) attempts settlement. | Settlement matches 0 rows (`status != 'processing'`). Row remains `pending`. | Pre-quarantine relay cannot settle replayed row. |
| **T-65** | Completed job intentional re-evaluation | Prior job finished with `status = 'completed'`. | Operator submits re-evaluation request with identical inputs. | New job record created with new `job_id`, `status = 'queued'`. Historical job untouched. | Completed evaluations do not block intentional re-runs. |
| **T-66** | Idempotency key normalization & missing headers | Request without `Idempotency-Key` header. | Client sends request. | Job created with `idempotency_key = sha256:...` (64 chars). `NOT NULL` constraint satisfied. | Deterministic fallback prevents NULL keys. |
| **T-67** | Relay crash before Redis publish | Row claimed (`claim_count = 1`, `publish_attempts = 0`). | Relay process SIGKILL before `redis.lpush()`. | Lease expires (30s). Relay B reclaims, sets `claim_count = 2`, publishes to Redis. | Pre-publish crash recovers cleanly without lost work. |
| **T-68** | Unknown Redis publish acknowledgment | Row claimed (`publish_attempts = 1`). | Socket timeout on Redis LPUSH response. | Relay skips settlement. Replacement relay re-publishes. Celery receives duplicate. | At-least-once delivery survives network timeouts. |
| **T-69** | Publish retry exhaustion alerting | Row fails claim/publish 5 consecutive times. | All 5 attempts fail. | Row set to `dead_lettered`, `dead_letter_reason = 'EXHAUSTED_BEFORE_PUBLISH'`, audit event emitted. | Exhaustion terminates cleanly with operator alert. |
| **T-70** | Operator replay of dead-lettered row | Row in `dead_lettered` (`claim_count = 5`). | Operator triggers replay API endpoint. | Row reset to `status = 'pending'`, counters reset to 0, token cleared. Re-dispatched to Redis. | Dead-lettered work is 100% recoverable by operators. |
| **T-71** | Running worker crash recovery by Reaper | Worker claims job (`running`), then crashes. | Worker heartbeat stops; 60s lease elapses. | Reaper detects expiry, sets `status = 'queued'`, increments `lock_version`, inserts outbox row. | Abandoned running jobs are automatically re-queued. |
| **T-72** | Result commit racing with worker lease expiry | Worker finishes inference at $T+61s$. | Lease expired at $T+60s$. Reaper has not run yet. | Worker's in-lock check `lease_expires_at <= now_clock` aborts commit with rollback. | Stale workers never commit results after lease expires. |
| **T-73** | Stale worker commit after replacement claim | Worker 1 pauses 75s. Reaper requeues. Worker 2 claims (`lock_version = 3`). | Worker 1 awakens and attempts commit with `lock_version = 1`. | Worker 1 lock check fails; rollback executed; Worker 2 result preserved. | Storage fencing guarantees single authoritative result. |

---

## 7. Honest Risk Assessment & Residual Uncertainties

1. **Broker Backlog Spikes During Redis Outages:** If Redis is partitioned for hours, PostgreSQL buffers outbox rows. When Redis recovers, relays burst accumulated tasks. While tenant semaphores protect workers from memory exhaustion, message queues will experience temporary high queue lag.
2. **Reaper Polling Interval Granularity:** The Reaper runs on a periodic interval (e.g. 15–30s). A crashed worker's job will experience a recovery latency equal to `lease_duration (60s) + reaper_interval (15-30s) = 75-90s` before re-execution begins. This is an intentional tradeoff to avoid high-frequency database polling.
3. **Operator Vigilance for Dead-Letter Queues:** While poison rows are quarantined without head-of-line blocking and audit alerts are fired, if organization operators ignore dead-letter alerts, evaluations will remain un-evaluated until operator intervention.
4. **Table Retention Pruning:** Over months of production operations, `evaluation_job_outbox` rows with `status = 'delivered'` will accumulate. A retention cleanup policy (purging delivered rows older than 30 days) is required for Milestone 7.

---

## 8. Inventory of Modified Documents

- [`docs/PHASE_5_FINAL_STATE_MACHINE_CONSISTENCY_AUDIT.md`](file:///home/shubh/scorva/docs/PHASE_5_FINAL_STATE_MACHINE_CONSISTENCY_AUDIT.md) — Created authoritative reconciliation audit document.
- [`docs/PHASE_5_ARCHITECTURE.md`](file:///home/shubh/scorva/docs/PHASE_5_ARCHITECTURE.md) — Reconciled outbox settlement predicates, table schema (`claim_count`, `publish_attempts`, `processed_at`), active idempotency index (`WHERE status IN ('queued', 'running')`), and Reaper requeue outbox insertion.
- [`docs/PHASE_5_DECISIONS.md`](file:///home/shubh/scorva/docs/PHASE_5_DECISIONS.md) — Updated ADR-11, ADR-12, and ADR-15 to match the 4-state machine, quarantine fencing, and Reaper recovery protocol.
- [`docs/PHASE_5_PLAN.md`](file:///home/shubh/scorva/docs/PHASE_5_PLAN.md) — Updated Sub-Milestones 5.1 and 5.4 with the authoritative settlement predicate and Reaper requeue specifications.
- [`docs/PHASE_5_TEST_PLAN.md`](file:///home/shubh/scorva/docs/PHASE_5_TEST_PLAN.md) — Appended integration test specifications (Scenarios 63–73).
- [`docs/PHASE_5_FINAL_OUTBOX_STATE_MACHINE_AUDIT.md`](file:///home/shubh/scorva/docs/PHASE_5_FINAL_OUTBOX_STATE_MACHINE_AUDIT.md) — Synchronized timestamp column naming (`processed_at`), idempotency index definition, and quarantine fencing SQL.

### Confirmation of Invariants:
- Zero application code, runtime configuration, dependencies, migrations, test implementation files, or database records were modified.
- Zero Celery workers, queues, leases, fencing tokens, or scaffolding were created.

---

## 9. Final Stop Condition

```
M5 IMPLEMENTATION STATUS: STRICTLY BLOCKED AND UNAUTHORIZED.
```
Do not start implementation or treat documentation completion as implementation approval.

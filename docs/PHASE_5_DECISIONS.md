# Scorva Phase 4 Milestone 5 — Architecture Decision Records (ADRs)
## Celery Evaluation Orchestrator, Worker Leases & Distributed Fault Tolerance

**Document Version:** 1.0  
**Date:** October 26, 2026  
**Status:** **PROPOSED ARCHITECTURE DECISION LOG (M5 PLANNING)**  
**Milestone 5 Implementation Status:** **BLOCKED & UNAUTHORIZED**  
**Author:** Lead Software Architect & Distributed Systems Engineer  
**Reference Invariants:** `docs/PHASE_4_DECISIONS.md`, `docs/PHASE_4_M4_POST_REMEDIATION_READ_ONLY_AUDIT.md`

---

## ADR-11: Transactional Outbox Pattern & Two-Phase Persisted Relay Lease Protocol (4-State Machine)

### Status: **PROPOSED (M5 — REVISED IN OUTBOX FINAL AUDIT)**

### Context
When an API client triggers an evaluation, the platform must perform two actions:
1. Insert an `evaluation_jobs` record in PostgreSQL.
2. Publish an evaluation task message to the Redis task queue for Celery.

If the application attempts to perform these two actions sequentially:
- Committing to PostgreSQL first and publishing to Redis second risks an API process crash or network timeout between the two operations, leaving a permanently stuck, un-dispatched job.
- Publishing to Redis first and committing to PostgreSQL second risks an uncommitted job being picked up by a worker, failing because the row does not exist in the database.

Furthermore, a naive outbox relay that holds a PostgreSQL transaction and row lock open while calling Redis (`redis.lpush()`) risks database connection pool exhaustion and table bloat if Redis experiences latency spikes or network timeouts.

Finally, an outbox model with only `processed_at IS NULL` or a candidate query selecting only `status = 'pending'` risks permanently orphaning expired `processing` rows if a relay crashes after claiming them.

### Decision
1. Implement the **Transactional Outbox Pattern** with a formal **4-State Machine** (`pending`, `processing`, `delivered`, `dead_lettered`) and the **Two-Phase Persisted Relay Lease Protocol**:
   - The FastAPI router inserts both the `evaluation_jobs` row and the `evaluation_job_outbox` row (status `'pending'`, `retry_count = 0`) within the same initial ACID transaction.
   - **Phase 1 (Atomic Batch Claim with Expired Recovery):** The background relay executes an instantaneous, sub-millisecond database transaction that claims both new `pending` rows and crashed/expired `processing` rows whose lease has lapsed:
     ```sql
     WITH claimable AS (
         SELECT id FROM evaluation_job_outbox
         WHERE (
             status = 'pending'
             OR (status = 'processing' AND relay_expires_at < clock_timestamp())
         )
         AND claim_count < :max_claims
         AND dead_lettered_at IS NULL
         ORDER BY id ASC LIMIT :batch_size
         FOR UPDATE SKIP LOCKED
     )
     UPDATE evaluation_job_outbox o
     SET status = 'processing',
         relay_claim_token = :my_relay_token,
         relay_claimed_at = clock_timestamp(),
         relay_expires_at = clock_timestamp() + (:lease_seconds || ' seconds')::INTERVAL,
         claim_count = claim_count + 1
     FROM claimable WHERE o.id = claimable.id
     RETURNING o.id, o.job_id, o.organization_id, o.queue_name, o.payload, o.claim_count;
     ```
     This claims the batch, increments `claim_count` on claim (tracking claim/lease attempts), and commits immediately. **Zero database connections or row locks are held during network operations.**
   - **Phase 2 (Out-of-Transaction Publish):** The relay publishes messages to Redis with a strict 2.0-second socket timeout outside any database transaction.
   - **Phase 3 (Conditional Settlement):** Upon confirmed Redis acknowledgment, the relay marks the row delivered in a fast update checking the claim token and processing state:
     ```sql
     UPDATE evaluation_job_outbox
     SET status = 'delivered',
         processed_at = clock_timestamp(),
         publish_attempts = publish_attempts + 1,
         relay_expires_at = NULL,
         last_error = NULL
     WHERE id = :id
       AND relay_claim_token = :my_relay_token
       AND status = 'processing'
       AND processed_at IS NULL;
     ```
   - **Quarantine Recovery Sweep:** A periodic background finalizer quarantines expired rows that reached maximum claim attempts, clearing relay claims and emitting audit logs atomically:
     ```sql
     UPDATE evaluation_job_outbox
     SET status = 'dead_lettered',
         dead_lettered_at = clock_timestamp(),
         dead_letter_reason = CASE
             WHEN publish_attempts = 0 THEN 'EXHAUSTED_BEFORE_PUBLISH'
             ELSE 'EXHAUSTED_DURING_PUBLISH_OR_SETTLEMENT'
         END,
         relay_claim_token = NULL,
         relay_expires_at = NULL
     WHERE status = 'processing'
       AND claim_count >= :max_claims
       AND relay_expires_at < clock_timestamp();
     ```
2. **Delivery Guarantee Realism & Consumer Idempotency:**
   - Broker publication is realistically **at-least-once**. Duplicate Redis deliveries can occur if a relay's lease expires while publishing to Redis or if Redis ACKs drop.
   - Task consumer execution on Celery workers is strictly **idempotent**: workers claim jobs using `UPDATE evaluation_jobs SET status = 'running', claim_token = :token, lock_version = lock_version + 1, attempts_count = attempts_count + 1 WHERE id = :job_id AND status = 'queued'`. Duplicate messages arriving for `running`, `completed`, `failed`, or `cancelled` jobs match 0 rows and are safely discarded without re-running or incrementing attempt counts.

### Alternatives Considered & Superseded
- **Approach 1 (Publish While Holding DB Row Lock):** Superseded. Holding database transactions during network calls risks pool exhaustion and deadlocks when Redis experiences latency.
- **Direct Celery Dispatch inside FastAPI Route (`task.delay()`):** Rejected because broker network partitions or API worker crashes cause lost jobs.
- **Filtering only `status = 'pending'` in Outbox Query:** Rejected in final audit because it permanently leaves crashed `processing` rows orphaned.
- **Assuming Exactly-Once Delivery at the Broker:** Rejected as physically impossible in distributed network architectures without downstream storage fencing.

### Consequences & Trade-Offs
- **Pros:** 100% immune to broker outages during job intake; zero database connection pool starvation during slow network calls; automatic lease recovery after relay process crashes; zero poison row head-of-line blocking; completely safe under duplicate broker messages.
- **Cons:** Requires persistent lease columns (`relay_claim_token`, `relay_expires_at`, `status`, `dead_lettered_at`, `dead_letter_reason`) on `evaluation_job_outbox`.

---

## ADR-12: Storage-Enforced Monotonic Fencing Tokens vs. Pure Distributed Locks

### Status: **PROPOSED (M5)**

### Context
In distributed asynchronous systems, worker nodes can experience unexpected process pauses (long garbage collection cycles, swapping, hypervisor CPU throttling, or network partitions). 

If mutual exclusion is enforced solely by an ephemeral distributed lock (e.g. Redis key TTL):
1. Worker 1 acquires the lock for Job A.
2. Worker 1 experiences a 70-second process pause. The 60-second lock expires.
3. Worker 2 acquires the lock for Job A and begins processing.
4. Worker 1 awakens and writes results to PostgreSQL, overwriting Worker 2's authoritative output (Martin Kleppmann's "Zombie Worker" anomaly).

### Decision
1. Scorva adopts **Storage-Enforced Monotonic Fencing Tokens** (`lock_version INTEGER NOT NULL DEFAULT 0`) on `evaluation_jobs`.
2. Every state mutation, heartbeat renewal, and result commit must execute within a row-locked transaction (`SELECT ... FOR UPDATE`) verifying `lock_version = :expected_version` and incrementing `lock_version + 1`.
3. If a replacement worker or the Reaper task reclaims a job, it increments `lock_version`.
4. When a stale worker resumes, its lock-check or CAS update detects the incremented version. The worker detects that it has been fenced, rolls back its transaction, and terminates cleanly.
5. All lease deadlines and expiry comparisons are calculated using **database-authoritative instantaneous clock** (`clock_timestamp()`), completely eliminating worker clock skew and avoiding frozen transaction-start timestamps caused by `CURRENT_TIMESTAMP`.

### Alternatives Considered
- **Pure Redis Redlock:** Rejected. Redlock does not solve process pauses or clock skew and cannot prevent stale storage writes without downstream storage fencing.
- **Pessimistic Long-Held Database Transactions (`FOR UPDATE` held open for 60 seconds):** Rejected. Holding database transactions open during long AI inference (30–60s) exhausts database connection pools and causes transaction ID wraparound issues.
- **Blind CAS Update vs. Explicit Row Lock on Commit:** Evaluated in pre-implementation review. Selected explicit row locking (`SELECT ... FOR UPDATE`) inside the commit transaction to serialize cleanly against concurrent Reaper or cancellation transactions.

### Consequences & Trade-Offs
- **Pros:** Physically guarantees that zombie workers can never corrupt database state; mathematically provable linearizability; completely immune to NTP clock drift and transaction-start clock freezing.
- **Cons:** Requires checking query row counts and in-lock guards on every database update.

---

## ADR-13: Lean Task Payloads (Job IDs Only) & Authoritative Database Rehydration

### Status: **PROPOSED (M5)**

### Context
Celery task messages could theoretically serialize the entire evaluation context: repository URL, commit SHA, rubric criteria, weights, and configuration settings.

However, placing full payloads in message queues introduces critical security and consistency risks:
1. Serializing repository tokens or credentials into Redis exposes secrets to anyone with broker read access.
2. If an organizer updates a draft rubric or configuration before a queued job runs, the queue message contains stale data.
3. An attacker with Redis write access could inject forged tasks with arbitrary URLs or altered criteria.

### Decision
1. Task messages are strictly **lean**: they contain only `{"job_id": "<uuid>"}`.
2. Workers treat task payloads as untrusted notifications.
3. Upon task receipt, the worker connects to PostgreSQL and rehydrates authoritative state directly from immutable database entities:
   - `submission_snapshots` (frozen commit SHA and repository URL).
   - `rubric_versions` (frozen criteria, weights, and score bounds).
   - `configuration_snapshot` (frozen runtime settings).
4. Credentials for private repositories are retrieved from the encrypted vault (`organization_integrations`) at runtime and never placed in queues.

### Consequences & Trade-Offs
- **Pros:** Eliminates secret exposure in message brokers; eliminates stale task state; blocks message forgery attacks.
- **Cons:** Requires a database read query at the start of every worker task (negligible overhead for an evaluation taking 15–60s).

---

## ADR-14: Two-Tier Retry Hierarchy (In-Worker Schema Retries vs. Task Orchestration Retries)

### Status: **PROPOSED (M5)**

### Context
Failures during an evaluation job stem from fundamentally different sources:
1. **Model Output Formatting Failure:** The LLM output omitted a required JSON field or generated minor formatting flaws.
2. **Infrastructure / Timeout Failure:** Ollama took 35 seconds to respond and timed out, or a network socket dropped.
3. **Security Policy Violation:** The repository tarball contained a directory traversal attempt or SSRF redirect.

Conflating these failure modes into a single retry counter leads to either retrying unrecoverable security attacks or exhausting task retry budgets on minor LLM formatting corrections.

### Decision
1. Implement a **Two-Tier Retry Hierarchy**:
   - **Tier 1 (Ephemeral In-Worker Model Retry — M4):** Managed by [`output_validator.py#execute_evaluation_with_retry`](file:///home/shubh/scorva/apps/api/modules/evaluations/output_validator.py). Strictly bounded to 1 retry. Only recoverable `AIProviderFormatError` triggers a prompt correction. It does **not** consume a task-level retry attempt.
   - **Tier 2 (Durable Task-Level Retry — M5):** Managed by Celery task orchestrator. Handles transient infrastructure timeouts (`AIProviderTimeoutError`, `AIProviderConnectionError`). Bounded to `eval.max_retries` (default: 3) with exponential backoff and full jitter.
2. **Zero-Retry Policy for Security Violations:**
   - Security exceptions (`SSRFViolationError`, `ArchiveExtractionViolation`, `AIProviderConfigError`, `AIProviderResponseSizeError`) are strictly non-retryable. They transition the job immediately to terminal `failed` status.

### Consequences & Trade-Offs
- **Pros:** Prevents wasted compute on malicious or unrecoverable tasks; gives LLMs a second chance to fix JSON syntax without triggering heavy task restarts.
- **Cons:** Requires clear exception hierarchy differentiation established in M4.

---

## ADR-15: Evaluation Job State Machine Expansion & Migration Compatibility

### Status: **PROPOSED (M5)**

### Context
In Milestone 2, the `evaluation_jobs` table was created with the check constraint:
```sql
CheckConstraint("status IN ('queued', 'running', 'completed', 'failed', 'cancelled')", name="chk_evaluation_jobs_status")
```
Milestone 5 introduces cooperative cancellation (`cancel_requested`) and explicit lease expiration tracking (`lease_expires_at TIMESTAMPTZ`).

### Decision
1. **State Constraint Strategy:**
   - Rather than expanding the status column with intermediate transient states like `cancel_requested` or `retry_wait` (which would require breaking database enum/check constraints and complicate UI state mapping), Scorva **preserves the existing 5 core statuses**:
     `'queued'`, `'running'`, `'completed'`, `'failed'`, `'cancelled'`.
   - Cooperative cancellation is tracked by a dedicated boolean column `cancellation_requested BOOLEAN NOT NULL DEFAULT FALSE`. This avoids breaking existing queries, index filters, or API contracts.
2. **New Columns Required for M5:**
   - `lease_expires_at TIMESTAMPTZ NULL`: Explicit DB-authoritative lease deadline.
   - `idempotency_key VARCHAR(128) NULL`: Normalized client key or unique server token.
   - `reevaluation_of_job_id UUID NULL REFERENCES evaluation_jobs(id) ON DELETE SET NULL`: Link to parent historical job for intentional re-evaluations.
   - `dispatch_generation INTEGER NOT NULL DEFAULT 1`: Monotonic dispatch attempt generation.
   - `cancellation_requested BOOLEAN NOT NULL DEFAULT FALSE`: Cooperative cancel flag.
   - Global unique index `uq_eval_jobs_organization_idempotency_key` ON `evaluation_jobs (organization_id, idempotency_key) WHERE idempotency_key IS NOT NULL`.
3. **Migration Compatibility:**
   - Migration will add these columns with safe defaults, ensuring zero disruption to existing rows.

### Consequences & Trade-Offs
- **Pros:** 100% backward-compatible with existing schema and UI status expectations; avoids complex check constraint rewrites; properly decouples request idempotency from intentional re-evaluation.
- **Cons:** Requires checking `cancellation_requested` flag alongside `status`.

---

## ADR-17: Decoupling Request Idempotency from Intentional Re-Evaluation

### Status: **PROPOSED (M5)**

### Context
Conflating HTTP request idempotency with intentional submission re-evaluation causes either:
1. Replayed requests after job completion to spawn unwanted duplicate evaluations (if index is active-only); or
2. Organizers being blocked from re-running evaluations on completed submissions (if index covers completed jobs).

### Decision
1. **Global Request Idempotency Scope:**
   `uq_eval_jobs_organization_idempotency_key` enforces global uniqueness across all job statuses for non-null keys. Replaying a request with the same `Idempotency-Key` returns the established job outcome (even after completion) with `Idempotent-Replay: true`.
2. **Dedicated Re-Evaluation Mechanism:**
   Intentional re-evaluation is an explicit operation (`POST .../submissions/{id}/reevaluate`) that generates a fresh `job_id`, assigns a new unique idempotency key, sets `reevaluation_of_job_id = Job_1.id`, and preserves Job 1's historical results untouched.

### Consequences & Trade-Offs
- **Pros:** 100% standards-compliant HTTP request idempotency; allows unlimited intentional re-evaluations with full lineage tracking.
- **Cons:** Requires explicit re-evaluate endpoint or parameter distinct from raw evaluation intake.

---

## ADR-16: Atomic Multi-Table Fenced Commit Transaction via Pessimistic Row Locking

### Status: **PROPOSED (M5 — REVISED IN PRE-IMPLEMENTATION REVIEW)**

### Context
When an evaluation completes, the worker must persist:
1. Parent row in `evaluation_results`.
2. $N$ child rows in `evaluation_criterion_scores`.
3. $M$ grandchild rows in `evidence_references`.
4. Update `evaluation_jobs` status to `completed` and link `current_result_id`.
5. Insert audit log event in `audit_events`.

If these writes occur across separate transactions, a worker crash or fencing collision could leave orphan result rows or inconsistent scores. Furthermore, relying on a blind trailing CAS update allows child rows to be inserted optimistically before the worker verifies whether it has been fenced or its lease has expired.

### Decision
1. Execute all persistence operations in a **single atomic PostgreSQL transaction** (`async with session.begin():`).
2. The very first statement in the transaction is the **Pessimistic Row Lock (`SELECT ... FOR UPDATE`)**:
   ```sql
   SELECT id, status, claim_token, lock_version, attempts_count, lease_expires_at, cancellation_requested
   FROM evaluation_jobs
   WHERE id = :job_id
   FOR UPDATE;
   ```
3. Inside the exclusive row lock, the worker evaluates five mandatory guards:
   - `status == 'running'`
   - `claim_token == :my_claim_token`
   - `lock_version == :my_expected_lock_version`
   - `cancellation_requested == FALSE`
   - `lease_expires_at > clock_timestamp()`
4. If any guard fails, the transaction immediately raises an exception and rolls back. Zero child rows are inserted.
5. If all guards pass, parent and child rows are inserted, `attempts_count` is assigned as `attempt_number`, `evaluation_jobs` status is updated to `completed`, and `lock_version` is incremented.
6. The transaction commits atomically. Any concurrent Reaper or cancellation transaction blocked on the row lock unblocks, reads `status = 'completed'`, and takes zero action.

### Alternatives Considered
- **Option A (Blind CAS UPDATE first or last):** Rejected. Blind updates do not hold the row lock during child insertions, and if executed last, child rows are inserted optimistically before verifying ownership.
- **Option B (Pessimistic Row Lock Protocol):** Selected. Eliminates all race conditions with concurrent Reapers and cancellation requests.

### Consequences & Trade-Offs
- **Pros:** Eliminates partial result records; guarantees that fenced or expired workers can never persist any partial evaluation data; cleanly serializes against Reaper and cancellation.
- **Cons:** Holds a brief row lock during result insertion (typically <50ms for relational inserts).

---

## ADR-17: Tenant-Level Concurrency Throttling via Redis Distributed Semaphores

### Status: **PROPOSED (M5 — CLARIFIED IN PRE-IMPLEMENTATION REVIEW)**

### Context
In a multi-tenant hackathon platform, an organizer might submit 500 team submissions for evaluation simultaneously. If unconstrained, this tenant could saturate all worker processes, starving other tenants of evaluation resources.

### Decision
1. Enforce a configurable tenant concurrency limit (`eval.tenant_max_concurrent_jobs`, default: 3).
2. Use a Redis distributed sliding window semaphore key: `eval:concurrent:{organization_id}` as an **Advisory Throughput and Fairness Governor**.
3. Before a worker claims a job from `queued`, it checks if the tenant has available capacity.
4. If the tenant is at capacity, the task message is pushed back or delayed, allowing tasks from other tenants to proceed.
5. When a job reaches a terminal state (`completed`, `failed`, `cancelled`), the semaphore slot is released.
6. **Correctness & Security Isolation Guarantee:**
   - Correctness, tenant isolation, and data integrity **never** depend on Redis.
   - Even if Redis fails, keys expire, or semaphores become desynchronized, tenant isolation is physically enforced by PostgreSQL foreign keys and mandatory query filters (`WHERE organization_id = :org_id`).
   - Concurrency semaphores govern only scheduling throughput, not authorization boundaries.

### Consequences & Trade-Offs
- **Pros:** Fair-share resource allocation across tenants; protects Ollama / GPU resources from saturation; safe failure modes if Redis experiences transient issues.
- **Cons:** Requires maintaining active semaphore counts in Redis.

---

## ADR-18: Worker Engine Strategy: Dedicated Synchronous SQLAlchemy vs Asyncpg in Celery

### Status: **PROPOSED (M5)**

### Context
FastAPI runs on `asyncio` using `asyncpg`. However, Celery workers typically run using the `prefork` or `solo` concurrency pool, where tasks execute synchronously. Running `asyncio.run()` inside each Celery prefork task to execute `asyncpg` queries causes frequent event loop conflicts, unclosed connection pool warnings, and greenlet threading issues.

### Decision
1. Create a dedicated **synchronous SQLAlchemy 2.0 engine** for worker processes:
   `apps/api/workers/database.py` using `postgresql+psycopg2://` (or `NullPool` synchronous session).
2. The worker engine uses `NullPool` to ensure connection creation and teardown do not leak across forked worker child processes.
3. FastAPI web processes continue using the high-performance asyncpg connection pool.

### Consequences & Trade-Offs
- **Pros:** Complete elimination of event loop and greenlet conflicts in Celery worker processes; rock-solid connection lifecycle.
- **Cons:** Requires `psycopg2-binary` dependency alongside `asyncpg`.

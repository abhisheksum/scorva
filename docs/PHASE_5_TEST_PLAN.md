# Scorva Phase 4 Milestone 5 — Quality Assurance & Test Plan
## Celery Evaluation Orchestrator, Worker Leases & Fault Tolerance

**Document Version:** 1.0  
**Date:** October 26, 2026  
**Status:** **PLANNING ONLY — STRICTLY AUTHORIZED FOR PLANNING & THREAT MODELING**  
**Milestone 5 Implementation Status:** **BLOCKED & UNAUTHORIZED**  
**Author:** Lead QA & Verification Engineer, Distributed Systems Architect  
**Reference Invariants:** `docs/PHASE_4_TEST_PLAN.md`, `docs/PHASE_4_M4_POST_REMEDIATION_READ_ONLY_AUDIT.md`

---

## 1. Testing Philosophy & Verification Strategy

Asynchronous background execution and distributed worker coordination introduce failure modes that cannot be detected by conventional unit testing alone. Race conditions, network partitions, worker crashes, and lease expirations must be verified under **realistic multi-process concurrency** and **deliberate fault injection**.

### 1.1 Testing Pyramid for Milestone 5

```
              [ Chaos & Worker Crash Injection Tests ]
            [ Multi-Process Concurrency & Fencing Tests ]
          [ End-to-End Task Pipeline Integration Tests ]
        [ Real PostgreSQL & Redis Dual-Engine Tests ]
      [ Deterministic In-Worker Unit & Mock Provider Tests ]
```

### 1.2 Mandatory Environment Distinctions: Live Storage vs Mocks

> [!IMPORTANT]
> **Strict Verification Requirement:**  
> Critical distributed guarantees—specifically atomic job claims, CAS fencing tokens, lease expiration, outbox relay consistency, and multi-table result persistence—**MUST NOT** be certified solely on the basis of mocked in-memory unit tests.  
> They **REQUIRE** execution against real **PostgreSQL 16** (testing row-level locks, `FOR UPDATE SKIP LOCKED`, and multi-table transactions) and real **Redis 7** (testing Celery task routing, atomic semaphores, and Pub/Sub).

- **Tier 1 (Offline Unit Tests):** Mock AI providers, in-memory state models, pure Pydantic schema validation. Fast, zero-network, run on any developer machine.
- **Tier 2 (Storage Integration Tests):** Real local PostgreSQL 16 container (`scorva` DB) and real Redis 7 container (`localhost:6379`). Verifies transactions, constraints, and outbox relay.
- **Tier 3 (Multi-Process Concurrency & Chaos Tests):** Spawns distinct Python worker processes (`multiprocessing` / sub-processes) executing against PostgreSQL and Redis to inject SIGKILL, artificial process pauses, and simultaneous claim races.

---

## 2. Exhaustive 24-Scenario Verification Matrix

Below is the exhaustive test specification covering every critical concurrency, failure, and security scenario required for Milestone 5:

---

### Scenario 01: Duplicate Task Delivery
- **Setup:** A valid `evaluation_jobs` record exists in `queued` status.
- **Injected Failure:** Celery redelivers the exact same task message (`job_id`) twice to two separate worker threads/processes simultaneously.
- **Expected Database State:** Exactly one worker successfully transitions status to `running` with `attempts_count = 1`. The second worker receives 0 updated rows and returns immediately. Exactly one `evaluation_results` row is produced.
- **Expected Audit Events:** Exactly 1 `evaluation.claimed` event; exactly 1 `evaluation.completed` event.
- **Invariant Proved:** At-least-once message delivery produces strictly idempotent execution.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 02: Two Workers Attempting to Claim One Job Concurrently
- **Setup:** Job A is in `queued` status.
- **Injected Failure:** Worker 1 and Worker 2 simultaneously issue `UPDATE evaluation_jobs SET status = 'running', claim_token = :token, lock_version = lock_version + 1 WHERE id = :job_id AND status = 'queued' RETURNING lock_version`.
- **Expected Database State:** PostgreSQL row-level locking serializes the updates. Exactly one worker updates 1 row and receives `lock_version = 1`. The competing worker updates 0 rows and aborts claim.
- **Expected Audit Events:** 1 `evaluation.claimed` event emitted by the winning worker.
- **Invariant Proved:** Atomic CAS claim eliminates duplicate in-flight workers.
- **Infrastructure Requirement:** Real PostgreSQL 16 (Multi-connection concurrency test).

---

### Scenario 03: Lease Expiry While Original Worker Continues Running
- **Setup:** Worker 1 claims Job A (`lock_version = 1`). Lease TTL is configured to 5 seconds.
- **Injected Failure:** Worker 1's heartbeat thread is artificially killed, but Worker 1 continues performing compute for 15 seconds.
- **Expected Database State:** PostgreSQL records `lease_expires_at < NOW()`. Reaper task runs, detects expired lease, and updates status to `queued` with `lock_version = 2`.
- **Expected Audit Events:** `evaluation.lease_expired` emitted with `reaped_by = "reaper_daemon"`.
- **Invariant Proved:** Unresponsive or frozen workers forfeit their lease autonomously.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Celery Beat Reaper.

---

### Scenario 04: Replacement Worker Receiving a Higher Fencing Token
- **Setup:** Job A had an expired lease from Worker 1 (`lock_version = 1`). Reaper requeued Job A (`lock_version = 2`).
- **Injected Failure:** Worker 2 claims Job A while Worker 1 is still processing in the background.
- **Expected Database State:** Worker 2 successfully updates Job A: `status = 'running'`, `claim_token = W2_UUID`, `lock_version = 3`.
- **Expected Audit Events:** `evaluation.claimed` with `worker_id = W2_UUID, lock_version = 3`.
- **Invariant Proved:** Monotonically increasing fencing tokens order successive claim generations.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 05: Old Worker Attempting to Heartbeat After Expiry
- **Setup:** Worker 1 was previously expired; Worker 2 claimed the job with `lock_version = 3`.
- **Injected Failure:** Worker 1 awakens and attempts to issue a lease renewal heartbeat:
  `UPDATE evaluation_jobs SET last_heartbeat_at = NOW(), lease_expires_at = NOW() + INTERVAL '60s' WHERE id = :job_id AND claim_token = 'W1_UUID' AND lock_version = 1`.
- **Expected Database State:** Update matches 0 rows. Worker 1 detects renewal failure and raises `StaleWorkerFencedException`.
- **Expected Audit Events:** `evaluation.heartbeat_rejected` with reason `"FENCING_GENERATION_MISMATCH"`.
- **Invariant Proved:** Expired workers cannot extend dead leases or alter active job state.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 06: Old Worker Attempting to Persist a Result After Replacement Claim
- **Setup:** Worker 2 has claimed Job A and is actively running. Worker 1 finishes its stale computation and initiates result persistence.
- **Injected Failure:** Worker 1 attempts to execute the atomic result persistence transaction with `expected_lock_version = 1`.
- **Expected Database State:** CAS check on `evaluation_jobs` updates 0 rows. Entire transaction is rolled back. Zero rows written to `evaluation_results`, `evaluation_criterion_scores`, or `evidence_references`. Worker 2 subsequently completes and writes authoritative result.
- **Expected Audit Events:** `evaluation.commit_fenced` emitted for Worker 1; `evaluation.completed` emitted for Worker 2.
- **Invariant Proved:** **Critical System Invariant:** Possession of an old lease or completion of old computation is never sufficient to commit state after a newer fencing token is issued.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 07: Worker Crash Before and After Provider Inference
- **Setup:** Two separate tests: (a) Crash before `generate_evaluation` call, (b) Crash immediately after receiving inference response before database persistence.
- **Injected Failure:** Worker process is terminated abruptly via `os.kill(os.getpid(), signal.SIGKILL)`.
- **Expected Database State:** In both cases, scratch files are abandoned; no partial result rows exist in DB. After lease expiration (60s), Reaper task detects stale heartbeat and resets status to `queued` (or `failed` if attempts exhausted). Next attempt restarts cleanly.
- **Expected Audit Events:** `evaluation.reaped` on lease timeout; `evaluation.claimed` on replacement retry.
- **Invariant Proved:** Sudden process death leaves zero corrupted state and triggers automatic recovery.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Multi-process runner.

---

### Scenario 08: Database Commit Succeeds but Broker Publication Fails
- **Setup:** API handles `POST /evaluations`.
- **Injected Failure:** Redis broker is forcefully shut down or network connection drops immediately before Celery task dispatch.
- **Expected Database State:** Because the API writes both `evaluation_jobs` and `evaluation_job_outbox` in the same PostgreSQL transaction, both records commit successfully. API returns `HTTP 202 Accepted`. Redis is down, but when Redis reconnects, the background outbox relay tails `evaluation_job_outbox` and successfully publishes the task to Celery.
- **Expected Audit Events:** `evaluation.outbox_created`; delayed `evaluation.outbox_relayed`.
- **Invariant Proved:** Transactional Outbox pattern completely eliminates lost evaluations caused by broker outages.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis restart simulation.

---

### Scenario 09: Broker Publication Succeeds but Publisher Acknowledgment is Lost
- **Setup:** Outbox relay publishes task message to Redis.
- **Injected Failure:** Redis receives message and places on queue, but TCP acknowledgment packet to relay worker is dropped.
- **Expected Database State:** Relay worker catches network timeout and does not update `processed_at`. On next polling tick, relay worker re-reads outbox row and publishes message again (at-least-once delivery). Worker consumes first message, claims job; second message updates 0 rows and is safely discarded.
- **Expected Audit Events:** 1 `evaluation.claimed` event; 1 `evaluation.completed` event.
- **Invariant Proved:** Publisher redelivery cleanly absorbed by idempotent worker claim.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7.

---

### Scenario 10: Database Transaction Rollback During Result Persistence
- **Setup:** Worker pipeline successfully finishes model evaluation and score calculation.
- **Injected Failure:** During `persist_evaluation_result_atomic`, an intentional database error is injected (e.g., foreign key violation or connection severance before `COMMIT`).
- **Expected Database State:** PostgreSQL transaction aborts completely. `evaluation_jobs.status` remains `running` (reverted). Zero orphaned rows in `evaluation_results` or child tables. Worker raises exception and re-queues attempt.
- **Expected Audit Events:** Zero `evaluation.completed` events.
- **Invariant Proved:** Atomicity: all-or-nothing persistence across all 4 result entities.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 11: Crash During Multi-Table Result Persistence
- **Setup:** Persistence function inserts into `evaluation_results`, child scores, and is mid-way through inserting `evidence_references`.
- **Injected Failure:** Process receives `SIGKILL` mid-transaction before executing `COMMIT`.
- **Expected Database State:** PostgreSQL automatically rolls back uncommitted transaction. `evaluation_results` table contains 0 rows for this attempt.
- **Expected Audit Events:** Zero result events.
- **Invariant Proved:** Relational integrity guaranteed under sudden worker crash mid-write.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 12: Duplicate Result-Commit Attempts
- **Setup:** Worker 1 successfully commits evaluation results for Job A (attempt 1).
- **Injected Failure:** Due to a logic error or retry loop, Worker 1 executes the exact same commit transaction a second time.
- **Expected Database State:** Second attempt fails with unique constraint violation `uq_evaluation_results_job_attempt (job_id, attempt_number)` or CAS `status = 'running'` mismatch.
- **Expected Audit Events:** Exactly 1 `evaluation.completed` event.
- **Invariant Proved:** Database constraints physically prevent duplicate completed results.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 13: Cancellation Racing with Result Commitment
- **Setup:** Worker 1 is in `persistence` stage.
- **Injected Failure:** User clicks "Cancel" simultaneously with worker committing results.
- **Expected Database State:** 
  - Case A (Cancel commits first): `evaluation_jobs.status` becomes `cancelled`. Worker 1's CAS update `WHERE status = 'running'` matches 0 rows; worker aborts and rolls back results.
  - Case B (Worker commits first): Worker 1 sets `status = 'completed'` and commits results. User's cancel query matches 0 rows (since job is no longer `running` or `queued`).
  In neither case does a job end up in a torn state.
- **Expected Audit Events:** Exactly 1 terminal event (`evaluation.cancelled` OR `evaluation.completed`).
- **Invariant Proved:** Mutual exclusion between cancellation and successful completion.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 14: Lease Renewal Transaction Succeeds but Response is Lost
- **Setup:** Worker heartbeat sends `UPDATE ... SET lease_expires_at = NOW() + INTERVAL '60s'`.
- **Injected Failure:** PostgreSQL successfully updates row and commits, but connection drops before worker receives acknowledgment.
- **Expected Database State:** Database reflects extended lease deadline (`NOW() + 60s`). Worker encounters connection error on heartbeat, logs warning, and retries heartbeat on next 15s interval. Since lease has not expired on the DB side, subsequent heartbeat succeeds.
- **Expected Audit Events:** 1 transient heartbeat warning; zero spurious job requeues.
- **Invariant Proved:** Heartbeat retry tolerance over transient network blips.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 15: Clock Skew Between Workers
- **Setup:** Worker A host clock is skewed +15 minutes fast; Worker B host clock is skewed -15 minutes slow.
- **Injected Failure:** Worker A and B execute evaluations simultaneously and renew leases.
- **Expected Database State:** Both workers use `lease_expires_at = clock_timestamp() + INTERVAL '60s'`. PostgreSQL's instantaneous server clock determines all expiration evaluations. Neither Worker A nor Worker B suffers premature lease expiration or lock extension based on local clock drift.
- **Expected Audit Events:** Normal lifecycle events.
- **Invariant Proved:** Complete immunity to NTP drift and host clock skew.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 16: Transient Provider Failure and Retry Exhaustion
- **Setup:** Ollama server is unreachable (`ConnectionRefusedError`).
- **Injected Failure:** Worker encounters connection drops on attempt 1, attempt 2, and attempt 3.
- **Expected Database State:**
  - Attempt 1: Fails with `AIProviderConnectionError`. Requeued with exponential backoff (15s + jitter). `attempts_count = 1`.
  - Attempt 2: Fails. Requeued (30s + jitter). `attempts_count = 2`.
  - Attempt 3: Fails. `attempts_count = 3` reaches `max_attempts` (3). Status transitions to terminal `failed` with `error_code = 'PROVIDER_UNAVAILABLE'`.
- **Expected Audit Events:** 2 `evaluation.retried` events; 1 `evaluation.failed` event.
- **Invariant Proved:** Predictable bounded retry exhaustion without infinite retry storms.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Mock failure client.

---

### Scenario 17: Configuration Errors and SSRF Violations are Not Retried
- **Setup:** Evaluation configured with an invalid model provider (`ai_provider = "invalid"`) or attempting to access forbidden internal port (`http://localhost:5432`).
- **Injected Failure:** Worker encounters `AIProviderConfigError` or `SSRFViolationError`.
- **Expected Database State:** Task immediately transitions to terminal `failed` with `error_code = 'SSRF_VIOLATION'` on attempt 1. `attempts_count = 1`. Zero retries scheduled.
- **Expected Audit Events:** Exactly 1 `evaluation.failed` event; zero retry events.
- **Invariant Proved:** Security violations and unrecoverable errors fail closed immediately.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 18: Schema-Correction Retry Budget is Separate from Task Budget
- **Setup:** LLM returns malformed JSON on initial inference.
- **Injected Failure:** Model generates invalid output on first call, but valid output on second call within the same worker task invocation.
- **Expected Database State:** In-worker retry loop (M4 `execute_evaluation_with_retry`) executes second call with schema-correction prompt. Output passes validation. Job completes successfully on `attempts_count = 1`. Task-level retry budget is NOT consumed.
- **Expected Audit Events:** 1 `evaluation.completed` event.
- **Invariant Proved:** Separation between ephemeral model self-correction and durable task-level orchestration retries.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Mock AI Provider.

---

### Scenario 19: Cross-Tenant Job-ID Substitution
- **Setup:** Job A belongs to Tenant 1. Attacker is authenticated under Tenant 2.
- **Injected Failure:** Attacker attempts to cancel, retry, or query Job A.
- **Expected Database State:** API query `WHERE id = :job_id AND organization_id = :tenant_2_id` returns 0 rows. API responds with `HTTP 404 Not Found` (or `403 Forbidden`). Job A remains untouched in Tenant 1.
- **Expected Audit Events:** `security.cross_tenant_access_denied`.
- **Invariant Proved:** Strict tenant boundary enforcement across job lifecycles.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 20: Unauthorized Administrative Recovery
- **Setup:** An unprivileged user attempts to trigger the crash recovery reaper task manually via an administrative endpoint.
- **Injected Failure:** User lacks `platform.ai_ops.manage` permission.
- **Expected Database State:** API rejects request with `HTTP 403 Forbidden`. Reaper task does not execute out-of-band.
- **Expected Audit Events:** `authz.permission_denied`.
- **Invariant Proved:** Platform maintenance operations are restricted to platform administrators.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 21: Queue Flooding and Retry Storms
- **Setup:** 500 evaluation jobs submitted concurrently for Tenant 1.
- **Injected Failure:** Simultaneous burst of evaluations during high traffic.
- **Expected Database State:** Tenant concurrency semaphore limits active running jobs for Tenant 1 to `eval.tenant_max_concurrent_jobs` (3). Exactly 3 jobs transition to `running`; 497 remain in `queued`. As running jobs complete, queued jobs are claimed sequentially without exhausting database connections or worker memory.
- **Expected Audit Events:** Normal rate-limited progress logs.
- **Invariant Proved:** Protection against tenant queue starvation and system collapse.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7.

---

### Scenario 22: Graceful Worker Shutdown and Task Redelivery
- **Setup:** Celery worker is actively evaluating Job A.
- **Injected Failure:** Worker process receives `SIGTERM` from Docker/Kubernetes.
- **Expected Database State:** Celery warm shutdown allows active task to finish within `soft_time_limit` (300s). If completed, results commit normally. If task exceeds time limit, Celery terminates task; lease expires on DB after 60s, and Reaper safely requeues task.
- **Expected Audit Events:** 1 `evaluation.completed` (if completed in time) OR 1 `evaluation.reaped` (if terminated).
- **Invariant Proved:** Clean container restart and zero-data-loss deployments.
- **Infrastructure Requirement:** Multi-process Celery worker + SIGTERM injection.

---

### Scenario 23: Recovery of Stuck or Unpublished Jobs
- **Setup:** Job A was committed to `evaluation_jobs`, but outbox relay process crashed before publishing to Redis.
- **Injected Failure:** Relay worker restarts after 5 minutes of downtime.
- **Expected Database State:** Upon startup, outbox relay executes `SELECT ... FROM evaluation_job_outbox WHERE processed_at IS NULL ORDER BY id LIMIT 50 FOR UPDATE SKIP LOCKED`. It finds Job A, publishes to Redis, and marks `processed_at = clock_timestamp()`. Worker claims Job A and completes evaluation.
- **Expected Audit Events:** `evaluation.outbox_relayed_after_recovery`.
- **Invariant Proved:** Durable self-healing of unpublished jobs following service restarts.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7.

---

### Scenario 24: Full Regression of Milestone 1–4 Boundaries
- **Setup:** Complete end-to-end evaluation run executing through Celery worker.
- **Injected Failure:** Execution of all previous security test suites under worker context.
- **Expected Database State:**
  - M1: Dynamic RBAC policy and organization scoping verified.
  - M2: Scoring math identical to `scoring_calculator.py` with `ROUND_HALF_UP` and zero `float` drift.
  - M3: Safe archive extraction verified (no symlinks, no path traversal, zero code execution).
  - M4: Profile B SSRF guard active (redirects rejected, pinned IP socket); output schema validation verified.
- **Expected Audit Events:** Full audit history for each milestone verified.
- **Invariant Proved:** Zero architectural regression across all previously completed Phase 4 milestones.
- **Infrastructure Requirement:** Full backend test suite execution ($>310$ tests passing).

---

## 3. Pre-Implementation Review: 10 Critical PostgreSQL-Backed Concurrency & Fault-Injection Tests (Scenarios 25–34)

The following tests require **real PostgreSQL 16** (and real Redis 7 where indicated) to verify storage-level locking, fencing, and fault tolerance:

### Scenario 25: Lease Expiry During a Long-Running Result Transaction
- **Setup:** Job A in `running` status with 2 seconds remaining on lease deadline (`lease_expires_at = clock_timestamp() + INTERVAL '2s'`).
- **Injected Failure:** Worker process acquires pessimistic row lock (`SELECT ... FOR UPDATE`), but artificially sleeps for 5 seconds inside the transaction before evaluating guards.
- **Expected Database State:** Worker evaluates `job.lease_expires_at <= clock_timestamp()`. Guard check fails. Transaction executes `ROLLBACK`. Zero rows inserted into `evaluation_results`. Job remains eligible for Reaper recovery.
- **Expected Audit Events:** `evaluation.commit_aborted` with `reason = 'LEASE_EXPIRED'`.
- **Invariant Proved:** Locks acquired before lease expiry cannot commit state if the lease deadline elapses before the final guard evaluation.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 26: Reaper vs. Heartbeat Contention
- **Setup:** Job A in `running` status with lease expired 1 second ago.
- **Injected Failure:** Heartbeat thread sends lease renewal `UPDATE ... FOR UPDATE` at the exact millisecond the Reaper scans for expired jobs using `SELECT ... FOR UPDATE SKIP LOCKED`.
- **Expected Database State:** One transaction wins row lock first.
  - Case A (Heartbeat wins): Lease extended 60s; Reaper subsequently skips row.
  - Case B (Reaper wins): Reaper updates `status = 'queued', lock_version = lock_version + 1`. Heartbeat unblocks, detects incremented `lock_version`, and raises `StaleWorkerFencedException`.
- **Expected Audit Events:** Either `evaluation.lease_renewed` OR `evaluation.reaped` (never torn or corrupt).
- **Invariant Proved:** Row-level locks eliminate torn lease states between Reaper and worker heartbeats.
- **Infrastructure Requirement:** Real PostgreSQL 16 (Multi-connection test).

---

### Scenario 27: Cancellation Versus Result Commit
- **Setup:** Worker is in `persistence` stage.
- **Injected Failure:** Organizer clicks Cancel (`POST /evaluations/{id}/cancel`) simultaneously with worker executing `persist_evaluation_result_atomic`. Both execute `SELECT ... FOR UPDATE` on `evaluation_jobs`.
- **Expected Database State:**
  - Case A (Cancel wins lock): `cancellation_requested = TRUE, status = 'cancelled'`. Worker unblocks, Step 3 in-lock guard detects `status != 'running'`, worker rolls back results.
  - Case B (Worker wins lock): Worker commits results, updates `status = 'completed'`. Cancel unblocks, sees terminal `completed` status, returns HTTP 409 Conflict.
- **Expected Audit Events:** Exactly 1 terminal event (`evaluation.cancelled` OR `evaluation.completed`).
- **Invariant Proved:** Mutual exclusion between cancellation and successful result commitment.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 28: Old Worker Commit After Replacement Worker Claim
- **Setup:** Worker 1 had lease expired at `lock_version = 1`. Reaper requeued job (`lock_version = 2`). Worker 2 claimed job (`lock_version = 3`).
- **Injected Failure:** Worker 1 finishes stale inference and executes `persist_evaluation_result_atomic` with `expected_lock_version = 1`.
- **Expected Database State:** Worker 1 acquires row lock. Step 3 detects `job.lock_version (3) != expected_lock_version (1)`. Worker 1 immediately rolls back. Zero child rows inserted. Worker 2 proceeds to finish and commit authoritative results.
- **Expected Audit Events:** 1 `evaluation.commit_fenced` for Worker 1; 1 `evaluation.completed` for Worker 2.
- **Invariant Proved:** Monotonic fencing tokens strictly prevent stale worker generations from committing results.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 29: Two Workers Attempting Final Persistence Concurrently
- **Setup:** Artificial anomaly: Two workers hold valid claim tokens for Job A.
- **Injected Failure:** Both workers invoke `persist_evaluation_result_atomic` concurrently.
- **Expected Database State:** PostgreSQL row lock serializes the workers. Worker 1 acquires lock, increments `lock_version` to 4, sets `status = 'completed'`, commits. Worker 2 unblocks, reads `status = 'completed'` and `lock_version = 4`, guard fails, Worker 2 rolls back.
- **Expected Audit Events:** 1 `evaluation.completed` event.
- **Invariant Proved:** Physical impossibility of concurrent duplicate result persistence.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 30: Lost Heartbeat Response After Successful Database Commit
- **Setup:** Job A `running`. Heartbeat renewal sends `UPDATE ... lease_expires_at = clock_timestamp() + INTERVAL '60s'`.
- **Injected Failure:** PostgreSQL commits update, but TCP connection drops before client receives packet.
- **Expected Database State:** Database reflects extended lease deadline (`NOW() + 60s`). Worker heartbeat thread logs network error and retries on next 15s interval. Since DB lease was extended, subsequent heartbeat finds valid lease and succeeds.
- **Expected Audit Events:** 1 transient heartbeat warning; zero spurious job requeues.
- **Invariant Proved:** Heartbeat retry tolerance over transient network disconnects.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 31: Outbox Publication Acknowledgment Loss & Duplicate Delivery
- **Setup:** Outbox relay publishes task to Redis.
- **Injected Failure:** Redis receives message and queues it, but TCP acknowledgment packet to relay drops.
- **Expected Database State:** Relay marks row failed and retries next tick, publishing duplicate message. Worker 1 consumes first message, claims job (`queued -> running`). Worker 2 consumes second message, queries DB, detects `status != 'queued'`, drops message immediately with zero state change.
- **Expected Audit Events:** 1 `evaluation.claimed` event; 1 `evaluation.completed` event.
- **Invariant Proved:** At-least-once task delivery converted to strictly idempotent consumer execution.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7.

---

### Scenario 32: Worker Crash During Multi-Table Result Persistence
- **Setup:** Worker persistence function inserts parent `evaluation_results` and child scores.
- **Injected Failure:** Worker process receives `SIGKILL` mid-transaction before executing `COMMIT`.
- **Expected Database State:** PostgreSQL automatically rolls back uncommitted transaction. `evaluation_results` table contains 0 rows for this attempt. Lease expires after 60s; Reaper requeues job.
- **Expected Audit Events:** Zero result events; 1 `evaluation.reaped` event.
- **Invariant Proved:** Atomicity: all-or-nothing persistence across multi-table result hierarchy.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Multi-process runner.

---

### Scenario 33: Idempotent Duplicate Task Execution
- **Setup:** Job A is already in `running` or `completed` status.
- **Injected Failure:** Replayed task message arrives on Celery queue for Job A.
- **Expected Database State:** Worker consumes task, queries `SELECT status FROM evaluation_jobs WHERE id = :job_id`. Sees `status != 'queued'`. Worker logs duplicate discarded and returns immediately without acquiring lease or modifying timestamps.
- **Expected Audit Events:** `evaluation.duplicate_task_discarded`.
- **Invariant Proved:** Complete consumer idempotency against replayed broker messages.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7.

---

### Scenario 34: Redis Concurrency Semaphore Expiry / Outage
- **Setup:** Tenant A has 3 active running evaluations (`eval.tenant_max_concurrent_jobs = 3`).
- **Injected Failure:** Redis server is stopped or keys expire prematurely mid-evaluation.
- **Expected Database State:** Active evaluations continue executing unhindered. Database queries strictly enforce `WHERE organization_id = :org_id`. Foreign key constraints enforce relational integrity. Concurrency semaphore is bypassed or degraded, but zero tenant data leakage occurs.
- **Expected Audit Events:** System operational warning `throttling.redis_unavailable_degraded_mode`.
- **Invariant Proved:** Tenant isolation and database correctness operate completely independently of Redis availability.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis restart injection.

---

## 4. Outbox Relay Final Design Check: 8 Critical Concurrency & Broker Failure Tests (Scenarios 35–42)

The following integration tests explicitly verify the **Two-Phase Persisted Relay Lease Protocol (Approach 2)** across crash recovery, network acknowledgment loss, poison message isolation, and broker outages:

### Scenario 35: Relay Crashes After Claiming but Before Publishing
- **Setup:** Job A in `queued` status. Outbox row claimed by Relay 1 (`relay_claim_token = R1_UUID`, `relay_expires_at = clock_timestamp() + INTERVAL '5s'`).
- **Injected Failure:** Relay 1 process is terminated abruptly via `SIGKILL` before making any network call to Redis.
- **Expected Database State:** Outbox row remains with `processed_at IS NULL`. After 5 seconds, Relay 2 executes claim query; detects `relay_expires_at < clock_timestamp()`; claims row with `relay_claim_token = R2_UUID`; publishes to Redis; marks `processed_at = clock_timestamp()`.
- **Expected Job State:** Job transitions from `queued` to `running` upon worker consumption.
- **Expected Audit Events:** `outbox.lease_recovered`, `evaluation.claimed`.
- **Invariant Proved:** Un-dispatched outbox claims autonomously expire and recover without manual intervention or lost tasks.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Multi-process relay runner.

---

### Scenario 36: Relay Crashes After Publishing but Before Marking Delivered
- **Setup:** Outbox row claimed by Relay 1. Message successfully pushed to Redis (`LPUSH`).
- **Injected Failure:** Relay 1 receives `SIGKILL` immediately after Redis returns acknowledgment, before executing the settlement update `UPDATE ... SET processed_at = clock_timestamp()`.
- **Expected Database State:** Task message exists in Redis queue. Outbox row remains with `processed_at IS NULL`. After 5 seconds, Relay 2 claims row and publishes duplicate message to Redis (at-least-once delivery). Relay 2 marks `processed_at = clock_timestamp()`.
- **Expected Job State:** Worker 1 consumes first message, claims job (`queued -> running`). Worker 2 consumes second message, queries DB, detects `status != 'queued'`, drops message with 0 rows updated.
- **Expected Audit Events:** 1 `evaluation.claimed`, 1 `evaluation.completed`, 1 `evaluation.duplicate_task_discarded`.
- **Invariant Proved:** At-least-once task delivery survives relay crashes without losing jobs, and worker idempotency cleanly neutralizes duplicate messages.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7.

---

### Scenario 37: Redis Accepts Message but Acknowledgment is Lost
- **Setup:** Outbox row claimed by Relay 1.
- **Injected Failure:** A test TCP proxy between relay and Redis queues the `LPUSH` message in Redis, then abruptly closes the TCP socket without sending the acknowledgment integer back to the relay client.
- **Expected Database State:** Relay client raises `aioredis.ConnectionError` or `TimeoutError`. Settlement query is skipped. Outbox row remains with `processed_at IS NULL`. After lease expiry, row is re-claimed and re-published.
- **Expected Job State:** Celery worker processes first task. Duplicate task is dropped.
- **Expected Audit Events:** `outbox.dispatch_timeout_retried`, `evaluation.completed`.
- **Invariant Proved:** Loss of broker publication acknowledgments never causes lost evaluations.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7 + Proxy socket drop fixture.

---

### Scenario 38: Two Relay Processes Claim Rows Concurrently
- **Setup:** 10 pending outbox rows exist in `evaluation_job_outbox`.
- **Injected Failure:** Relay 1 and Relay 2 execute the atomic claim query (`SELECT ... FOR UPDATE SKIP LOCKED`) at the exact same millisecond.
- **Expected Database State:** Relay 1 claims rows 1–5 (`relay_claim_token = R1_UUID`); Relay 2 claims rows 6–10 (`relay_claim_token = R2_UUID`). Zero row contention, zero lock wait timeouts, zero overlapping claims. Both batches published and settled.
- **Expected Job State:** All 10 jobs transition to `running` / `completed`.
- **Expected Audit Events:** 10 `outbox.relayed` events across the two relay instances.
- **Invariant Proved:** `SKIP LOCKED` provides lock-free, horizontally scalable outbox claiming.
- **Infrastructure Requirement:** Real PostgreSQL 16 (Multi-connection concurrency test).

---

### Scenario 39: Stale Relay Attempts Settlement After Lease Expiry and Replacement
- **Setup:** Relay 1 claims outbox row with 2-second lease (`relay_expires_at = clock_timestamp() + INTERVAL '2s'`).
- **Injected Failure:** Relay 1 experiences an artificial 5-second process pause. During the pause, Relay 2 re-claims the row (`relay_claim_token = R2_UUID`), publishes to Redis, and marks it settled. Relay 1 awakens and executes:
  `UPDATE evaluation_job_outbox SET processed_at = clock_timestamp() WHERE id = :id AND relay_claim_token = 'R1_UUID' AND processed_at IS NULL`.
- **Expected Database State:** Relay 1 update matches 0 rows (claim token mismatch and `processed_at` already populated). Relay 1 detects 0 rows updated and logs stale claim abort.
- **Expected Job State:** Job processed normally by the publication from Relay 2.
- **Expected Audit Events:** 1 `outbox.stale_settlement_rejected`.
- **Invariant Proved:** Token-fenced settlement updates prevent zombie relays from corrupting outbox state.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 40: One Poison Row Does Not Starve Unrelated Outbox Rows
- **Setup:** Outbox row 1 contains an invalid queue name or payload that triggers a non-recoverable error. Rows 2–10 contain valid jobs.
- **Injected Failure:** Relay attempts to process row 1; raises exception.
- **Expected Database State:** Row 1 increments `retry_count` on each attempt. After 5 attempts, `retry_count = 5` permanently excludes row 1 from candidate queries (`WHERE retry_count < 5`). Rows 2–10 are claimed and published within 200ms without head-of-line blocking. Row 1 is flagged as quarantined.
- **Expected Job State:** Jobs 2–10 execute and complete. Job 1 remains `queued` and alerts administrator.
- **Expected Audit Events:** `outbox.poison_row_quarantined` with `outbox_id = 1, attempts = 5`.
- **Invariant Proved:** Defective or poison outbox rows are quarantined without degrading queue throughput for healthy jobs.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 41: Redis Remains Unavailable Across Multiple Retry Intervals
- **Setup:** 5 evaluation jobs created in `queued` status; 5 outbox rows pending.
- **Injected Failure:** Redis server is stopped (`docker pause scorva-redis` or simulated connection refusal) for 60 seconds across multiple relay polling cycles.
- **Expected Database State:** During outage, claims fail publication, leases expire, and rows are re-evaluated on subsequent ticks. `retry_count` increments up to the backoff threshold. Zero rows are lost or corrupted. When Redis resumes, all 5 rows are successfully published and marked `processed_at = clock_timestamp()`.
- **Expected Job State:** All 5 jobs remain safely stored in PostgreSQL; none are lost; all execute when Redis recovers.
- **Expected Audit Events:** `outbox.broker_offline_warning`, followed by 5 `outbox.relayed` events.
- **Invariant Proved:** Durable store-and-forward persistence survives extended message broker downtime.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis pause simulation.

---

### Scenario 42: Duplicate Task Delivery Cannot Create Duplicate Successful Evaluations
- **Setup:** A valid `evaluation_jobs` row in `queued` status.
- **Injected Failure:** Two identical task messages containing `{"job_id": "<uuid>"}` are injected directly into the Celery Redis queue. Two worker processes consume the tasks simultaneously.
- **Expected Database State:** Worker 1 executes `UPDATE evaluation_jobs SET status = 'running' WHERE id = :job_id AND status = 'queued'` (1 row updated). Worker 2 executes the same query (0 rows updated). Worker 2 drops task immediately. Worker 1 executes full pipeline and commits single result.
- **Expected Job State:** Job status `completed`. Exactly one `evaluation_results` row created.
- **Expected Audit Events:** Exactly 1 `evaluation.claimed`, exactly 1 `evaluation.completed`.
- **Invariant Proved:** End-to-end execution idempotency: at-least-once task delivery never produces duplicate evaluations.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7 + Multi-process worker test.

---

## 5. Outbox Final Concurrency Review: 11 Critical Scenarios (Scenarios 43–53)

The following integration test specifications verify settlement timing, lease expiry recovery, durable quarantine lifecycles, and atomic job/outbox creation:

### Scenario 43: Settlement After Expiry with No Replacement Claim
- **Setup:** Outbox row claimed by Relay A (`relay_expires_at = clock_timestamp() + INTERVAL '5s'`).
- **Injected Failure:** Relay A sleeps 7 seconds before attempting settlement. No other relay has claimed the row.
- **Expected Database State:** Relay A's settlement query checks `WHERE id = :id AND relay_claim_token = 'Token_A' AND processed_at IS NULL`. Row is successfully updated to `status = 'delivered', processed_at = clock_timestamp()`.
- **Expected Audit Events:** 1 `outbox.settled_after_lease_expiry`.
- **Invariant Proved:** Token-fenced optimistic settlement avoids unnecessary duplicate message dispatch when publication succeeded and no competitor claimed the row.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 44: Settlement Racing with Replacement Claim
- **Setup:** Row lease expired. Relay A attempts settlement at the exact millisecond Relay B attempts claim (`SELECT ... FOR UPDATE SKIP LOCKED`).
- **Injected Failure:** Concurrent execution of settlement and claim queries.
- **Expected Database State:** Row lock serializes the transactions.
  - If Relay A acquires lock first: Row marked `status = 'delivered'`. Relay B unblocks, candidate filter `WHERE processed_at IS NULL` drops row. Relay B claims 0 rows.
  - If Relay B acquires lock first: Relay B installs `relay_claim_token = Token_B`. Relay A unblocks, token check fails (0 rows updated), Relay A aborts. Relay B publishes task.
- **Expected Audit Events:** Exactly 1 settlement event. Zero torn outbox states.
- **Invariant Proved:** Row-level locks eliminate race conditions between expired relay settlement and replacement relay claims.
- **Infrastructure Requirement:** Real PostgreSQL 16 (Multi-connection test).

---

### Scenario 45: Stale Relay After Replacement Token Installed
- **Setup:** Relay B claimed row (`relay_claim_token = Token_B`).
- **Injected Failure:** Relay A awakens from long pause and executes settlement with `relay_claim_token = Token_A`.
- **Expected Database State:** Relay A update matches 0 rows. Relay A logs stale abort; Relay B publishes task and settles row.
- **Expected Audit Events:** 1 `outbox.stale_settlement_rejected`.
- **Invariant Proved:** Token fencing prevents zombie relays from modifying outbox state after a replacement has claimed the row.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 46: Lease Renewal and Settlement Race
- **Setup:** Relay A heartbeats while concurrently attempting settlement.
- **Injected Failure:** Multi-threaded race inside Relay A between background heartbeat thread and main settlement task.
- **Expected Database State:** Serialized cleanly via PostgreSQL row lock. Single authoritative settlement.
- **Expected Audit Events:** 1 `outbox.settled`.
- **Invariant Proved:** Thread-safe coordination between heartbeats and settlement.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 47: Retry Exhaustion and Atomic Quarantine
- **Setup:** Outbox row with `retry_count = 4` fails publication again due to broker failure.
- **Injected Failure:** Relay catches 5th failure.
- **Expected Database State:** Row updated to `status = 'dead_lettered', dead_lettered_at = clock_timestamp(), dead_letter_reason = 'MAX_RETRIES_EXCEEDED', retry_count = 5`. Partial index excludes row from active claim queries.
- **Expected Audit Events:** `outbox.quarantined` with `job_id, retry_count = 5`.
- **Invariant Proved:** Atomic transition to durable dead-letter state upon retry exhaustion.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 48: Quarantine Audit and Alert Event Emission
- **Setup:** Poison row dead-lettered.
- **Injected Failure:** Corrupted payload or non-recoverable error.
- **Expected Database State:** `audit_events` contains record with `action = 'outbox.quarantined'` and sanitized payload details (zero leaked secrets).
- **Expected Audit Events:** 1 `outbox.quarantined` event.
- **Invariant Proved:** Complete audit trail and secret-sanitized logging on quarantine.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 49: Authorized vs. Unauthorized Operator Replay
- **Setup:** Quarantined outbox row in Organization 1.
- **Injected Failure:**
  - Case A: Org 2 admin attempts replay (returns HTTP 404 / 403).
  - Case B: Org 1 non-admin attempts replay (returns HTTP 403 Forbidden).
  - Case C: Org 1 admin with `organization.ai_ops.manage` replays (returns HTTP 200 OK).
- **Expected Database State:** Row reset to `status = 'pending', retry_count = 0, dead_lettered_at = NULL`. Eligible for claim on next tick.
- **Expected Audit Events:** 1 `outbox.replayed` with actor user ID.
- **Invariant Proved:** Strict organization-scoped RBAC governs dead-letter recovery.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 50: Zero Head-of-Line Blocking During Quarantine
- **Setup:** Row 1 fails and is quarantined; rows 2–10 are valid.
- **Injected Failure:** Row 1 repeatedly raises exceptions.
- **Expected Database State:** Relay immediately skips row 1 via `FOR UPDATE SKIP LOCKED`. Rows 2–10 are claimed and published within 200ms.
- **Expected Job State:** Jobs 2–10 execute normally.
- **Expected Audit Events:** 1 `outbox.quarantined`; 9 `outbox.relayed`.
- **Invariant Proved:** Poison rows cannot cause head-of-line blocking for healthy queue traffic.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 51: Atomic Rollback of Job and Outbox Creation
- **Setup:** Evaluation job dispatch initiated.
- **Injected Failure:** Simulated error injected during outbox insert in `create_evaluation_job_atomic` (e.g. database foreign key violation or connection drop before commit).
- **Expected Database State:** Transaction aborts completely. Zero rows in `evaluation_jobs`; zero rows in `evaluation_job_outbox`.
- **Expected Audit Events:** Zero dispatch events.
- **Invariant Proved:** Atomicity: job and outbox record commit together or not at all.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 52: Active Deduplication vs. Intentional Re-Evaluation
- **Setup:** Submission snapshot S1 evaluated with rubric R1.
- **Injected Failure:**
  - Case A: Dispatch while job is `queued` or `running` (returns existing active `job_id`, 0 rows inserted).
  - Case B: Complete job to `completed`, then dispatch again (creates new `job_id`, inserts new outbox row).
- **Expected Database State:** Partial unique index prevents duplicate active jobs, but allows sequential re-evaluations after completion.
- **Expected Audit Events:** 1 `evaluation.dispatched` on initial run; 1 `evaluation.dispatched` on re-evaluation.
- **Invariant Proved:** Predictable idempotency: active duplicate suppression paired with intentional re-evaluation auditability.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 53: Duplicate Task Message Arrival Across All Job States
- **Setup:** Replayed task message injected into Redis when job is (a) `queued`, (b) `running`, (c) `completed`, (d) `cancelled`.
- **Injected Failure:** Worker consumes duplicate message in each state.
- **Expected Database State:**
  - `queued`: Exactly 1 worker updates row (`attempts_count = 1`); duplicate updates 0 rows and returns.
  - `running`: Updates 0 rows (`status != 'queued'`); duplicate returns immediately. `attempts_count` remains 1.
  - `completed`: Updates 0 rows; duplicate returns immediately. Completed results untouched.
  - `cancelled`: Updates 0 rows; duplicate returns immediately.
- **Expected Audit Events:** 1 `evaluation.claimed`; duplicate dropped without state change.
- **Invariant Proved:** Duplicate broker deliveries can never increment attempt counters or spawn competing pipelines.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7.

---

## 6. Final State-Machine & Delivery-Guarantee Audit: 9 Integration Scenarios (Scenarios 54–62)

The following integration test specifications formally verify the reclamation of expired `processing` rows, at-least-once delivery realism, concurrent idempotency creation, and consumer idempotency across all job states:

### Scenario 54: Reclamation of Expired `processing` Outbox Row
- **Setup:** Row 1 in `processing` status, `relay_claim_token = Token_A`, `relay_expires_at = clock_timestamp() - INTERVAL '1s'` (Relay A crashed).
- **Injected Failure:** Relay B executes unified claim query (`WHERE status = 'pending' OR (status = 'processing' AND relay_expires_at < clock_timestamp())`).
- **Expected Database State:** Relay B reclaims Row 1: sets `status = 'processing'`, `relay_claim_token = Token_B`, `relay_expires_at = clock_timestamp() + INTERVAL '30s'`, `retry_count = 2`.
- **Expected Publication Behavior:** Relay B successfully publishes task to Redis and marks `status = 'delivered', processed_at = clock_timestamp()`.
- **Invariant Proved:** Expired `processing` rows are never orphaned and are safely reclaimed by surviving relay instances.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7.

---

### Scenario 55: Concurrent Reclamation of Expired Row by Two Relays
- **Setup:** Row 1 in `processing` status with expired lease.
- **Injected Failure:** Relay 1 and Relay 2 execute the unified claim query at the exact same millisecond.
- **Expected Database State:** PostgreSQL row-level lock serializes the updates. Exactly 1 relay claims Row 1 (`retry_count = 2`). The competing relay skips Row 1 via `FOR UPDATE SKIP LOCKED`.
- **Expected Publication Behavior:** Exactly 1 task published by winning relay.
- **Invariant Proved:** `FOR UPDATE SKIP LOCKED` eliminates duplicate claims and race conditions on expired `processing` rows.
- **Infrastructure Requirement:** Real PostgreSQL 16 (Multi-connection test).

---

### Scenario 56: Redis Publish Succeeds but TCP Acknowledgment is Lost
- **Setup:** Row 1 in `processing` status.
- **Injected Failure:** Relay pushes task to Redis, but socket connection drops before reading response.
- **Expected Database State:** Relay skips settlement. Row 1 remains `processing`. After 30s, lease expires. Relay 2 reclaims Row 1 (`retry_count = 2`) and re-publishes to Redis. Relay 2 settles row (`status = 'delivered'`).
- **Expected Publication Behavior:** Two identical task messages exist in Redis (at-least-once delivery).
- **Worker Execution Outcome:** Worker 1 claims job (`queued -> running`). Worker 2 claims 0 rows and drops duplicate message cleanly. Exactly 1 `evaluation_results` row produced.
- **Invariant Proved:** At-least-once broker delivery survives acknowledgment loss without lost jobs or duplicate executions.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7 + Proxy socket drop fixture.

---

### Scenario 57: Duplicate Redis Messages Generated by Lease-Expiry Race
- **Setup:** Relay A claims Row 1.
- **Injected Failure:** Relay A publishes to Redis, but is paused for 35 seconds before settlement. Relay B reclaims Row 1 (lease expired at 30s) and also publishes to Redis. Both publish successfully.
- **Expected Database State:** Two task messages exist in Redis. Relay B executes settlement and marks Row 1 `status = 'delivered'`. When Relay A attempts settlement, its update checks `WHERE relay_claim_token = Token_A`; matches 0 rows and aborts cleanly.
- **Worker Execution Outcome:** First worker claims job (`attempts_count = 1`). Second worker sees `status = 'running'`, matches 0 rows, drops message without incrementing `attempts_count`.
- **Invariant Proved:** Token fencing prevents stale relay settlement, while consumer worker idempotency neutralizes duplicate broker messages.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7.

---

### Scenario 58: Stale Relay Settlement Attempt After Replacement Token Installed
- **Setup:** Relay B has reclaimed Row 1 and installed `relay_claim_token = Token_B`.
- **Injected Failure:** Relay A resumes from pause and executes:
  `UPDATE evaluation_job_outbox SET status = 'delivered', processed_at = clock_timestamp() WHERE id = 1 AND relay_claim_token = 'Token_A' AND status = 'processing'`.
- **Expected Database State:** Query updates 0 rows (claim token mismatch). Relay A logs stale abort; Relay B settles row.
- **Invariant Proved:** Monotonic token fencing prevents zombie relays from modifying state after replacement claim.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 59: Crash During Retry Exhaustion Finalization
- **Setup:** Row 1 at `retry_count = 5`, `status = 'processing'`.
- **Injected Failure:** Relay fails publication and process receives `SIGKILL` before executing in-line quarantine update.
- **Expected Database State:** Row 1 remains in DB. Lease expires after 30s. Candidate query excludes row (`WHERE retry_count < 5`). Periodic background quarantine sweep query executes:
  `UPDATE evaluation_job_outbox SET status = 'dead_lettered', dead_lettered_at = clock_timestamp(), dead_letter_reason = 'MAX_RETRIES_EXCEEDED' WHERE status = 'processing' AND retry_count >= 5 AND relay_expires_at < clock_timestamp()`.
  Row 1 transitions cleanly to `dead_lettered`.
- **Expected Publication Behavior:** Zero head-of-line blocking for healthy rows. Admin audit alert emitted.
- **Invariant Proved:** Crash during retry exhaustion is safely finalized to durable quarantine by background sweep.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 60: Concurrent Idempotency-Key Requests with Empty Database
- **Setup:** Zero evaluation jobs exist for submission S1.
- **Injected Failure:** Client sends 2 simultaneous HTTP requests with identical idempotency key.
- **Expected Database State:** Both requests find 0 rows on `SELECT ... FOR UPDATE`. Both attempt `INSERT INTO evaluation_jobs`. First transaction inserts job and outbox record. Second transaction hits partial unique index `uq_eval_jobs_active_idempotency`, catches `IntegrityError`, rolls back, re-queries, and returns winning `job_id`.
- **Expected Publication Behavior:** Exactly 1 job and exactly 1 outbox record created.
- **Invariant Proved:** Partial unique index resolves concurrent creation without phantom reads or duplicates.
- **Infrastructure Requirement:** Real PostgreSQL 16 (Multi-connection test).

---

### Scenario 61: Duplicate Worker Delivery Across All Job States
- **Setup:** Test evaluates task delivery across all 5 job states: `queued`, `running`, `completed`, `failed`, `cancelled`.
- **Injected Failure:** Worker receives duplicate message in each state.
- **Expected Database State:**
  - `queued`: Atomic claim updates 1 row; `attempts_count` increments from 0 to 1; pipeline runs.
  - `running`: Atomic claim updates 0 rows (`status != 'queued'`); message dropped; `attempts_count` remains 1.
  - `completed`: Updates 0 rows; message dropped; historical results untouched.
  - `failed`: Updates 0 rows; message dropped; failed status untouched.
  - `cancelled`: Updates 0 rows; message dropped; cancelled status untouched.
- **Invariant Proved:** Worker claim update is strictly idempotent; duplicate deliveries can never increment attempt counters or spawn competing pipelines.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Celery worker runner.

---

### Scenario 62: Replay Racing with Background Quarantine Sweep
- **Setup:** Row 1 at `status = 'processing'`, `retry_count = 5`, lease expired.
- **Injected Failure:** Operator clicks "Replay" at the exact millisecond the background quarantine finalizer runs.
- **Expected Database State:**
  - Case A (Finalizer commits first): Row transitions to `dead_lettered`. Operator replay executes `UPDATE ... SET status = 'pending' WHERE id = 1 AND status = 'dead_lettered'`; succeeds. Row is reset to `pending` and eligible for claim.
  - Case B (Replay attempts first): Replay checks `WHERE status = 'dead_lettered'`; matches 0 rows (row is still `processing`). API returns `HTTP 409 Conflict: Row is not dead-lettered`. Finalizer then transitions row to `dead_lettered`.
- **Invariant Proved:** Mutual exclusion: replay operates strictly on dead-lettered rows, eliminating torn states.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

## 7. Final State-Machine Consistency Review: 11 Critical Scenarios (Scenarios 63–73)

The following integration test specifications formally verify outbox quarantine fencing, active idempotency uniqueness, publish failure recovery, and worker crash recovery via the Reaper protocol:

---

### Scenario 63: Stale Relay Settlement Racing with Background Quarantine
- **Setup:** Outbox Row 1 is in `processing` status with `relay_claim_token = Token_A` and `retry_count = 5`.
- **Injected Failure:** Relay A experiences a 40-second process pause. While paused, the 30-second lease expires. The background quarantine finalizer runs, sets `status = 'dead_lettered'`, sets `relay_claim_token = NULL`, sets `relay_expires_at = NULL`, and commits an `outbox.quarantined` audit event. Relay A awakens and attempts settlement:
  ```sql
  UPDATE evaluation_job_outbox
  SET status = 'delivered', processed_at = clock_timestamp()
  WHERE id = 1 AND relay_claim_token = 'Token_A' AND status = 'processing' AND processed_at IS NULL;
  ```
- **Expected Database State:** Update matches 0 rows (both `relay_claim_token` is NULL and `status` is `'dead_lettered'`). Relay A logs stale abort. Row 1 remains `dead_lettered`.
- **Expected Audit Events:** Exactly 1 `outbox.quarantined` event. Zero settlement events.
- **Invariant Proved:** Atomic quarantine clears claim tokens and fences off stale relay settlement updates unconditionally.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 64: Stale Relay Settlement After Operator Replay
- **Setup:** Row 1 was quarantined to `dead_lettered` after Relay A's lease expired (`Token_A`). An authorized operator then invokes the Replay API, which transitions Row 1 to `status = 'pending'`, resets counters, and emits an `outbox.replayed` audit event.
- **Injected Failure:** Stale Relay A (unaware that it was quarantined and replayed) awakens and executes its delayed settlement query with `relay_claim_token = Token_A`.
- **Expected Database State:** Settlement query matches 0 rows because `status = 'pending'` (predicate requires `status = 'processing'`) and `relay_claim_token` is NULL (does not match `Token_A`). Row 1 remains `pending` and unaffected.
- **Expected Audit Events:** 1 `outbox.replayed` event; zero settlement events from Relay A.
- **Invariant Proved:** Settlement predicate `status = 'processing'` prevents pre-quarantine relays from settling replayed outbox rows.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 65: Intentional Re-Evaluation of Completed Job
- **Setup:** Evaluation Job 1 for submission S1 completed successfully (`status = 'completed'`, `idempotency_key = K1`).
- **Injected Failure:** An organizer triggers an intentional re-evaluation of submission S1 with identical inputs (same rubric, same commit SHA).
- **Expected Database State:**
  - Partial unique index `uq_eval_jobs_active_idempotency` ON `(organization_id, idempotency_key) WHERE status IN ('queued', 'running')` is evaluated. Because Job 1 has `status = 'completed'`, it is **excluded from the index**.
  - A new `evaluation_jobs` record (Job 2) is successfully inserted with a **fresh `job_id`**, `status = 'queued'`, `attempts_count = 0`, `lock_version = 0`, and `idempotency_key = K1`.
  - A new `evaluation_job_outbox` record is inserted in the same transaction.
  - Job 1 remains completely untouched with its full historical scores.
- **Expected API Response:** `HTTP 202 Accepted` returning the fresh `job_id` of Job 2.
- **Invariant Proved:** Active-only idempotency index allows intentional re-evaluation of completed work while preserving immutable historical evaluations.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 66: Idempotency Key Normalization and Deterministic Fallback
- **Setup:** An API client triggers evaluation without providing an `Idempotency-Key` HTTP header.
- **Injected Failure:** Two identical requests arrive with missing headers.
- **Expected Database State:**
  - The API computes the deterministic hash:
    `idempotency_key = sha256:SHA256(submission_id || commit_sha || rubric_version_id || config_hash)`.
  - The column constraint `idempotency_key VARCHAR(128) NOT NULL` is verified.
  - Request 1 creates Job 1 (`status = 'queued'`).
  - Request 2 arrives while Job 1 is still in-flight (`queued`). The partial index detects conflict; Transaction 2 catches `IntegrityError`, rolls back, re-queries, and returns `job_id` of Job 1 with `HTTP 200 OK` and header `Idempotent-Replay: true`.
- **Invariant Proved:** Fallback key generation guarantees non-null keys, and in-flight deduplication functions identically with or without client-provided headers.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 67: Relay Process Crash Before Redis Publication
- **Setup:** Outbox Row 1 is claimed by Relay 1 (`claim_count = 1`, `publish_attempts = 0`, `relay_claim_token = Token_1`, `status = 'processing'`).
- **Injected Failure:** Relay 1 process is killed via `SIGKILL` immediately after committing the Phase 1 claim transaction, **before** executing `redis.lpush()`.
- **Expected Database State:** Zero messages are published to Redis. After 30 seconds, Relay 1's lease expires. On the next tick, Relay 2's unified claim query reclaims Row 1 (`status = 'processing'`, `claim_count = 2`, `relay_claim_token = Token_2`). Relay 2 executes `redis.lpush()` and completes settlement (`status = 'delivered', processed_at = clock_timestamp()`).
- **Expected Publication Behavior:** Exactly 1 task message delivered to Redis.
- **Invariant Proved:** Process crashes prior to publication recover automatically without lost work or orphaned jobs.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7 + Process termination fixture.

---

### Scenario 68: Unknown Redis Publish Acknowledgment Due to Socket Timeout
- **Setup:** Row 1 claimed by Relay 1 (`claim_count = 1`).
- **Injected Failure:** Relay 1 calls `redis.lpush()`. Redis commits the message to the queue, but the network socket drops before Redis returns the response. Relay 1 catches `redis.exceptions.TimeoutError`.
- **Expected Database State:** Relay 1 skips database settlement and logs a warning. Row 1 remains `processing`. After 30 seconds, Relay 2 reclaims Row 1 (`claim_count = 2`), publishes to Redis, and completes settlement (`status = 'delivered'`).
- **Worker Execution Outcome:** Redis now contains two task messages for Job 1.
  - Worker A consumes Message 1: Executes atomic claim (`queued -> running`, `attempts_count = 1`), runs evaluation, and commits results (`status = 'completed'`).
  - Worker B consumes Message 2: Executes atomic claim (`WHERE status = 'queued'`). Matches 0 rows because Job 1 is already `running` or `completed`. Worker B logs `Duplicate task ignored` and discards message cleanly.
- **Invariant Proved:** At-least-once broker delivery combined with worker consumer idempotency survives network ACK loss without duplicate evaluation runs.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7 + Socket timeout proxy.

---

### Scenario 69: Outbox Retry Exhaustion Alerting and Audit Event Emission
- **Setup:** Outbox Row 1 contains a malformed configuration that causes network publication to fail repeatedly.
- **Injected Failure:** Row 1 fails claim and publication across 5 consecutive attempts (`claim_count = 5`).
- **Expected Database State:**
  - After attempt 5, the row is excluded from the candidate claim query (`WHERE retry_count < 5`).
  - Lease expires at 30s. The background quarantine finalizer runs:
    Transitions Row 1 to `status = 'dead_lettered'`, `dead_lettered_at = clock_timestamp()`, `dead_letter_reason = 'EXHAUSTED_BEFORE_PUBLISH'`, `relay_claim_token = NULL`, `relay_expires_at = NULL`.
  - In the **same database transaction**, an `AuditEvent` (`action = 'outbox.quarantined'`, `severity = 'HIGH'`) is committed.
  - Prometheus counter `scorva_outbox_dead_letter_total` increments.
- **Invariant Proved:** Exhausted outbox rows are quarantined durably without head-of-line blocking, and fire explicit operational audit alerts.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 70: Authorized Operator Replay Flow of Quarantined Row
- **Setup:** Row 1 is in `status = 'dead_lettered'` in Organization Org_A.
- **Injected Failure:**
  - Test 1 (Unauthorized): Operator from Org_B attempts to replay Row 1. API returns `HTTP 404 Not Found` (tenant isolation).
  - Test 2 (Authorized): Operator with `evaluations:manage` in Org_A invokes `POST /api/v1/organizations/Org_A/evaluations/outbox/1/replay`.
- **Expected Database State:**
  - Replay transaction updates Row 1: `status = 'pending'`, `claim_count = 0`, `publish_attempts = 0`, `retry_count = 0`, `dead_lettered_at = NULL`, `dead_letter_reason = NULL`.
  - Commits `outbox.replayed` audit event.
  - On next relay tick, Row 1 is claimed, published to Redis, and settled to `delivered`.
- **Invariant Proved:** Quarantined rows are completely recoverable via authorized, organization-scoped operator workflows.
- **Infrastructure Requirement:** Real PostgreSQL 16 + FastAPI test client.

---

### Scenario 71: Running Worker Crash Recovery by Scheduled Reaper
- **Setup:** Job 1 is claimed by Worker 1: `status = 'running'`, `claim_token = Token_W1`, `lock_version = 1`, `lease_expires_at = clock_timestamp() + INTERVAL '60s'`, `attempts_count = 1`.
- **Injected Failure:** Worker 1 process suffers a fatal crash (SIGKILL or host OOM). Heartbeat ceases. 60 seconds elapse.
- **Expected Database State:**
  - The Celery Beat Reaper task runs: `SELECT ... WHERE status = 'running' AND lease_expires_at < clock_timestamp() FOR UPDATE SKIP LOCKED`.
  - Identifies Job 1 as expired. Because `attempts_count (1) < max_attempts (3)`:
    - Updates Job 1: `status = 'queued'`, `claim_token = NULL`, `worker_id = NULL`, `lease_expires_at = NULL`, `lock_version = 2`.
    - Inserts a new `evaluation_job_outbox` row for Job 1 (`status = 'pending'`) in the **same transaction**.
    - Emits `evaluation.requeued` audit event.
  - Outbox relay dispatches new task to Redis.
  - Worker 2 consumes task, claims Job 1 (`status = 'running'`, `claim_token = Token_W2`, `lock_version = 3`, `attempts_count = 2`), and finishes evaluation.
- **Invariant Proved:** Abandoned running jobs are automatically recovered, requeued, and re-dispatched with incremented fencing tokens.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7 + Celery worker runner.

---

### Scenario 72: Result Commit Racing with Worker Lease Expiry
- **Setup:** Worker 1 claims Job 1 with a 60-second lease expiring at $T+60$s.
- **Injected Failure:** Worker 1's inference takes 61 seconds due to local model delay. Worker 1 finishes inference at $T+61$s and begins Step 1 of the 7-step commit protocol (`SELECT ... FOR UPDATE`). The Reaper has not run yet.
- **Expected Database State:**
  - Worker 1 acquires row lock on `evaluation_jobs`.
  - Step 3 In-Lock Guard executes:
    `now_clock = SELECT clock_timestamp()`.
    `if job.lease_expires_at <= now_clock:` raises `WorkerLeaseExpiredException`.
  - Worker 1 executes `ROLLBACK`.
  - Zero rows inserted into `evaluation_results` or child tables.
  - Job 1 remains in PostgreSQL with its lease expired. When Reaper runs, it requeues Job 1 for clean re-execution.
- **Invariant Proved:** In-lock lease validation against instantaneous database time prevents expired workers from persisting late results.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 73: Stale Worker Commit Attempt After Replacement Worker Claims Job
- **Setup:** Job 1 was claimed by Worker 1 (`lock_version = 1`, `claim_token = Token_W1`).
- **Injected Failure:** Worker 1 pauses for 75 seconds. Reaper runs at $T+60$s and requeues Job 1 (`lock_version = 2`). Worker 2 claims Job 1 (`lock_version = 3`, `claim_token = Token_W2`), executes evaluation, and commits results (`status = 'completed'`, `lock_version = 4`). Worker 1 awakens and attempts its 7-step commit protocol with its cached `expected_lock_version = 1` and `claim_token = Token_W1`.
- **Expected Database State:**
  - Worker 1 acquires row lock: `SELECT status, claim_token, lock_version FROM evaluation_jobs WHERE id = Job_1 FOR UPDATE`.
  - In-lock guards inspect row: finds `status = 'completed'` (not `'running'`), `claim_token = Token_W2` (not `Token_W1`), and `lock_version = 4` (not 1).
  - Worker 1 raises `StaleWorkerFencedException` and executes `ROLLBACK`.
  - Worker 2's authoritative result and scores remain 100% intact and uncorrupted.
- **Invariant Proved:** Monotonic storage fencing completely eliminates Martin Kleppmann's Zombie Worker anomaly across process pauses.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

## 8. Retry, Idempotency, Cancellation and Recovery Review: 14 Critical Scenarios (Scenarios 74–87)

The following integration test specifications formally verify outbox counter mechanics, network publish outcomes, request idempotency lifecycle, cancellation transaction serialization, and multi-record recovery generations:

---

### Scenario 74: Relay Process Crash Before Redis Publication
- **Setup:** Outbox Row 1 claimed by Relay 1 (`claim_count = 1`, `publish_attempts = 0`, `status = 'processing'`).
- **Injected Failure:** Relay 1 process killed via `SIGKILL` immediately after committing the Phase 1 claim transaction, before initiating any network socket connection to Redis.
- **Expected Database State:** Zero messages delivered to Redis. Lease expires at 30s. Relay 2 reclaims Row 1 (`claim_count = 2`, `status = 'processing'`), completes Redis publish, and executes Phase 3 settlement (`status = 'delivered', processed_at = clock_timestamp(), publish_attempts = 1`).
- **Invariant Proved:** Pre-publish relay crashes increment `claim_count` without false publish credit, and recover automatically without lost work.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Process termination fixture.

---

### Scenario 75: Relay Process Crash During Network Socket Call
- **Setup:** Outbox Row 1 claimed by Relay 1 (`claim_count = 1`).
- **Injected Failure:** Relay 1 initiates `redis.lpush()`. Network proxy abruptly terminates TCP socket mid-packet transmission. Relay 1 catches `ConnectionError` or times out.
- **Expected Database State:** Relay 1 does not execute settlement. Row 1 remains `status = 'processing'`. After 30s lease expiry, Relay 2 reclaims Row 1 (`claim_count = 2`), publishes to Redis, and completes settlement.
- **Invariant Proved:** Unconfirmed publish attempts recover safely via at-least-once re-claim protocol.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7 + Proxy socket drop fixture.

---

### Scenario 76: Relay Process Crash After Redis Publication but Before Settlement
- **Setup:** Row 1 claimed by Relay 1 (`claim_count = 1`).
- **Injected Failure:** Relay 1 successfully calls `redis.lpush()`. Redis confirms receipt with integer queue length $\ge 1$. Relay 1 process receives `SIGKILL` before executing Phase 3 settlement transaction.
- **Expected Database State:** Task message exists in Redis. Database row remains `status = 'processing'`. After 30s lease expiry, Relay 2 reclaims Row 1 (`claim_count = 2`) and publishes a duplicate message to Redis.
- **Worker Execution Outcome:** Two identical messages exist in Redis.
  - Worker A consumes Message 1: Claims job (`status = 'running'`, `attempts_count = 1`) and executes evaluation.
  - Worker B consumes Message 2: Executes atomic claim `WHERE status = 'queued'`; matches 0 rows (job is already `running` or `completed`); drops duplicate message cleanly.
- **Invariant Proved:** At-least-once delivery survives post-publish relay crashes; downstream consumer idempotency neutralizes duplicate broker messages.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7 + Process termination fixture.

---

### Scenario 77: Bounded Outbox Retry Exhaustion & High-Severity Alerting
- **Setup:** Outbox Row 1 experiences persistent network failure across 5 consecutive relay claim attempts.
- **Injected Failure:** `claim_count` reaches 5 (`publish_attempts = 0`). 30-second lease expires.
- **Expected Database State:**
  - Candidate claim query excludes row (`WHERE claim_count < 5`).
  - Background quarantine sweep executes: sets `status = 'dead_lettered'`, `dead_lettered_at = clock_timestamp()`, `dead_letter_reason = 'EXHAUSTED_BEFORE_PUBLISH'`, `relay_claim_token = NULL`, `relay_expires_at = NULL`.
  - In the **same transaction**, an `AuditEvent` (`action = 'outbox.quarantined'`, `severity = 'HIGH'`) is committed.
  - Prometheus counter `scorva_outbox_dead_letter_total` increments.
- **Invariant Proved:** Bounded retries terminate cleanly into durable quarantine with operational alerting; zero silent data loss.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 78: Request Idempotency In-Flight Replay
- **Setup:** Job 1 is currently `running` with `idempotency_key = 'client:req-001'`.
- **Injected Failure:** Client retries identical HTTP request `POST /api/v1/evaluations` with `Idempotency-Key: req-001` while Job 1 is running.
- **Expected API Response:** API queries `WHERE idempotency_key = 'client:req-001'`, finds Job 1. Returns `HTTP 200 OK` (or `202 Accepted`) with Job 1's `job_id`, `status: "running"`, and header `Idempotent-Replay: true`.
- **Expected Database State:** Zero new rows inserted in `evaluation_jobs` or `evaluation_job_outbox`.
- **Invariant Proved:** In-flight request idempotency deduplicates cleanly and returns the active job representation.
- **Infrastructure Requirement:** Real PostgreSQL 16 + FastAPI test client.

---

### Scenario 79: Request Idempotency Replay After Job Completion
- **Setup:** Job 1 has finished with `status = 'completed'` and `idempotency_key = 'client:req-001'`.
- **Injected Failure:** Client retries identical HTTP request `POST /api/v1/evaluations` with `Idempotency-Key: req-001` 2 hours after completion.
- **Expected API Response:** Global unique index `uq_eval_jobs_organization_idempotency_key` resolves Job 1. API returns `HTTP 200 OK` with Job 1's `job_id`, `status: "completed"`, final scores, and header `Idempotent-Replay: true`.
- **Expected Database State:** Zero new rows inserted. Job 1 scores remain intact.
- **Invariant Proved:** Retrying a request after completion returns established terminal results and never spawns duplicate evaluations.
- **Infrastructure Requirement:** Real PostgreSQL 16 + FastAPI test client.

---

### Scenario 80: Explicit Intentional Re-Evaluation
- **Setup:** Job 1 for submission S1 is `completed` with `idempotency_key = 'client:req-001'`.
- **Injected Failure:** Operator invokes explicit re-evaluation endpoint `POST /api/v1/.../submissions/S1/reevaluate` with `Idempotency-Key: req-002`.
- **Expected Database State:**
  - Job 2 is created with a **fresh `job_id`**, `status = 'queued'`, `attempts_count = 0`, `idempotency_key = 'client:req-002'`, and `reevaluation_of_job_id = Job_1.id`.
  - Outbox row for Job 2 inserted with `status = 'pending'`.
  - Job 1 remains completely untouched with historical scores.
- **Expected API Response:** `HTTP 202 Accepted` returning Job 2 `job_id`.
- **Invariant Proved:** Intentional re-evaluation creates a distinct job with explicit lineage while preserving immutable historical evaluations.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 81: Concurrent Identical Requests on Empty Database
- **Setup:** Zero evaluation jobs exist for submission S1.
- **Injected Failure:** Client sends 2 simultaneous HTTP requests with identical `Idempotency-Key: req-001`.
- **Expected Database State:** Both requests find 0 rows on initial query. Both attempt `INSERT INTO evaluation_jobs`. PostgreSQL unique index `uq_eval_jobs_organization_idempotency_key` serializes inserts:
  - Transaction 1 commits Job 1 + outbox record.
  - Transaction 2 encounters `UniqueViolationError` (`IntegrityError`), rolls back, re-queries, and returns Job 1 with `HTTP 200/202` and `Idempotent-Replay: true`.
- **Invariant Proved:** Partial unique index resolves concurrent creation without phantom jobs or 500 errors.
- **Infrastructure Requirement:** Real PostgreSQL 16 (Multi-connection concurrency test).

---

### Scenario 82: Cancellation Wins Race Against Reaper Recovery
- **Setup:** Job 1 is `running`, worker crashed, lease expired at $T+60$s.
- **Injected Failure:** Operator invokes cancellation API at $T+61$s. Cancellation transaction acquires exclusive row lock before Reaper.
- **Expected Database State:** Cancellation sets `status = 'cancelled'`, `cancellation_requested = TRUE`, `lock_version = 2`, `completed_at = clock_timestamp()`. When Reaper locks row, in-lock guard finds `status != 'running'`. Reaper skips row. Job 1 is never requeued.
- **Invariant Proved:** Cancellation winning the row lock prevents subsequent reaper requeue or task dispatch.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 83: Reaper Recovery Wins Race Against Cancellation
- **Setup:** Job 1 is `running`, worker crashed, lease expired at $T+60$s.
- **Injected Failure:** Reaper acquires row lock before Cancellation API.
- **Expected Database State:**
  - Reaper updates Job 1: `status = 'queued'`, `lock_version = 2`, `claim_token = NULL`, inserts outbox row #2. Commits.
  - Cancellation then locks row, finds `status = 'queued'`. Updates Job 1: `status = 'cancelled'`, `completed_at = clock_timestamp()`, `lock_version = 3`. Commits.
  - When worker consumes outbox row #2 from Redis, atomic claim checks `WHERE status = 'queued'`; matches 0 rows; drops message.
- **Invariant Proved:** Serialized locking ensures cancellation applied after reaper requeue safely neutralizes the pending task.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 84: Cancellation Wins Race Against Worker Result Commit
- **Setup:** Worker 1 finishes evaluation inference at $T+50$s.
- **Injected Failure:** Operator cancellation request acquires row lock on `evaluation_jobs` at exact instant Worker 1 begins Step 1 of the 7-step commit protocol.
- **Expected Database State:**
  - Cancellation transaction updates: `status = 'cancelled'`, `cancellation_requested = TRUE`, `lock_version = 2`. Commits.
  - Worker 1 commit transaction acquires lock. Step 3 In-Lock Guard finds `status == 'cancelled'`, `cancellation_requested == TRUE`, and `lock_version == 2` (expected 1). Worker raises `EvaluationCancelledException` and executes `ROLLBACK`.
  - Zero rows inserted into `evaluation_results` or child tables.
- **Invariant Proved:** In-lock guards halt in-flight result persistence when cancellation commits first.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 85: Worker Result Commit Wins Race Against Cancellation
- **Setup:** Worker 1 completes inference and begins 7-step commit protocol.
- **Injected Failure:** Operator cancellation request arrives while Worker 1 holds row lock.
- **Expected Database State:**
  - Worker 1 verifies guards, inserts child result rows, updates `status = 'completed'`, `lock_version = 2`. Commits.
  - Cancellation transaction acquires row lock, inspects row: finds `status == 'completed'`.
  - Cancellation rejected with `HTTP 409 Conflict: Evaluation already completed`. Completed scores remain 100% intact.
- **Invariant Proved:** Completed evaluations cannot be retroactively cancelled or corrupted.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 86: Multiple Outbox Rows Across Sequential Reaper Recoveries
- **Setup:** Job 1 experiences two consecutive worker crashes.
- **Injected Failure:** Reaper recovers Job 1 at $T+60$s, and again at $T+130$s.
- **Expected Database State:**
  - Outbox row #1: `status = 'delivered'`, `dispatch_generation = 1`.
  - Outbox row #2: `status = 'delivered'`, `dispatch_generation = 2`.
  - Outbox row #3: `status = 'pending'`, `dispatch_generation = 3`.
  - Partial unique index `uq_eval_job_outbox_active_dispatch` allows insertion of Row #3 because Rows #1 and #2 are in `delivered` status.
- **Invariant Proved:** Multi-record outbox schema safely tracks sequential recovery generations without constraint collisions.
- **Infrastructure Requirement:** Real PostgreSQL 16.

---

### Scenario 87: Duplicate Delivery Across Recovery Generations
- **Setup:** Job 1 was requeued by Reaper to Generation 2 (`lock_version = 3`).
- **Injected Failure:** A delayed task message from Generation 1 is delivered to Worker A while Worker B is processing Generation 2.
- **Expected Database State:**
  - Worker B holds lease with `lock_version = 3`. Job 1 is `status = 'running'`.
  - Worker A receives delayed Generation 1 task, executes atomic claim:
    `UPDATE evaluation_jobs SET status = 'running' ... WHERE id = :job_id AND status = 'queued'`.
  - Matches 0 rows because Job 1 is already `running`. Worker A drops message. `attempts_count` is not incremented.
- **Invariant Proved:** Consumer idempotency isolates recovery generations cleanly, preventing stale broker messages from disrupting active workers.
- **Infrastructure Requirement:** Real PostgreSQL 16 + Redis 7 + Celery multi-worker fixture.

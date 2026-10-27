# Scorva Phase 4 Milestone 5 — Sub-Milestone 5.2 Completion Report

**Document Version:** 1.0  
**Date:** October 26, 2026  
**Status:** **SUB-MILESTONE 5.2 IMPLEMENTED, TESTED & VERIFIED**  
**Milestone 5 Implementation Scope:** Sub-Milestone 5.2 (Celery Worker Engine, Worker Database Connection Pool, and Lease/Fencing Protocol)  
**Post-5.2 Implementation Status:** **Sub-Milestones 5.3–5.5 STRICTLY BLOCKED & PENDING EXPLICIT AUTHORIZATION**  
**Database Verification Target:** PostgreSQL 16 on `:5432` (`scorva` database)  
**Test Suite Verification:** 12/12 M5.2 tests passing; 20/20 M5.1 tests passing; 297/297 across full project regression suite (0 failures, 0 errors)

---

## 1. Executive Summary & Authorization Context

Pursuant to explicit user authorization for **Phase 4, Sub-Milestone 5.2: Celery Worker Engine, Worker Database Connection Pool, and Lease/Fencing Protocol**, the background worker execution runtime has been implemented and verified.

The core deliverable of Sub-Milestone 5.2 is the industrial-grade, fault-tolerant worker execution substrate:
1. **Celery 5.6 Application Integration:** Broker configuration (`settings.REDIS_URL`), task routing to `evaluations.default`, late ACKs, and prefetch limits.
2. **Dedicated Worker Database Connection Pool:** Synchronous SQLAlchemy 2.0 engine using `psycopg2` with bounded `QueuePool`, fork safety via Celery signals, and task-scoped sessions ensuring zero database transactions are held during non-database operations.
3. **Atomic PostgreSQL Worker Claim Protocol:** Atomic transition of `queued` $\rightarrow$ `running`, monotonic incrementing of fencing version (`lock_version`) and attempt counter (`attempts_count`), unique claim token installation, and authoritative lease establishment via PostgreSQL server clock (`clock_timestamp()`).
4. **Renewable Lease & Monotonic Fencing Protocol:** Lease renewal / heartbeat validation enforcing row locking, current `status = 'running'`, claim token matching, fencing token matching, and strict rejection of late heartbeats on expired leases. Cooperative cancellation detection is integrated into the heartbeat response.
5. **Two Focused M5.1 Verifications & Hardening:**
   - Outbox quarantine cannot quarantine actively publishing relays prior to lease expiry, and invalidates stale tokens.
   - Missing `Idempotency-Key` headers are deterministically fingerprinted and deduplicated against active in-flight jobs.

---

## 2. Initial Focused M5.1 Checks & Corrections

### Check 1: Outbox Quarantine Pre-Expiry Immunity & Stale Token Invalidation
- **Code Inspection:** Verified that `quarantine_exhausted_outbox_rows` in [`apps/api/modules/evaluations/outbox.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/outbox.py#L161-L168) explicitly requires `EvaluationJobOutbox.relay_expires_at < func.clock_timestamp()`. An actively publishing relay whose lease has not expired is completely immune from quarantine sweeps, even if `claim_count >= 5`.
- **Token Invalidation:** On quarantine, the row is updated with `relay_claim_token = None` and `relay_expires_at = None`. Any subsequent settlement attempt by a stale relay with the old token matches 0 rows and aborts safely.
- **Regression Verification:** Added `test_outbox_quarantine_does_not_quarantine_unexpired_relay_and_invalidates_token` to [`apps/api/tests/test_evaluation_outbox_m5_1.py`](file:///home/shubh/scorva/apps/api/tests/test_evaluation_outbox_m5_1.py).

### Check 2: Missing Idempotency-Key Behavior & Duplicate Handling
- **Code Inspection & Correction:** In [`apps/api/modules/evaluations/service.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/service.py#L457-L466), when `idempotency_key` is `None`:
  1. `request_fingerprint` is always computed deterministically via canonical JSON SHA-256 hash.
  2. If an evaluation job for the same submission with identical `request_fingerprint` is currently in-flight (`status IN ('queued', 'running')`), the request deduplicates to the active job without spawning duplicate worker jobs or outbox records.
  3. Once the active job reaches a terminal state (`completed`, `failed`), a subsequent request without an `Idempotency-Key` creates a fresh evaluation job.
- **Regression Verification:** Added `test_missing_idempotency_key_deduplicates_in_flight_and_allows_post_completion` to [`apps/api/tests/test_evaluation_outbox_m5_1.py`](file:///home/shubh/scorva/apps/api/tests/test_evaluation_outbox_m5_1.py).

---

## 3. Implemented Celery & Worker Engine Architecture

### 3.1 Celery Application ([`apps/api/workers/celery_app.py`](file:///home/shubh/scorva/apps/api/workers/celery_app.py))
- **Broker:** Redis 7 via `settings.REDIS_URL`.
- **Serializers:** JSON for tasks and results; strict JSON content acceptance.
- **Timezone:** UTC-enforced.
- **Reliability:**
  - `task_acks_late = True`: Tasks are acknowledged only after processing completes, enabling automatic crash recovery.
  - `task_reject_on_worker_lost = True`: Requeues tasks if a child worker process is abruptly killed.
  - `worker_prefetch_multiplier = 1`: Prevents worker starvation and guarantees fair queue distribution.
- **Queue & Routing:** Routes `apps.api.workers.tasks.evaluate_submission` to queue `evaluations.default`.

### 3.2 Worker Database Engine ([`apps/api/workers/database.py`](file:///home/shubh/scorva/apps/api/workers/database.py))
- **Dialect & Driver:** Synchronous SQLAlchemy 2.0 with `psycopg2-binary`.
- **Connection Pool:** `QueuePool` with bounded concurrency:
  - `pool_size = 5`
  - `max_overflow = 10`
  - `pool_timeout = 30.0`
  - `pool_recycle = 1800`
  - `pool_pre_ping = True` (healthcheck before checkout)
- **Fork Safety:** Celery `worker_process_init` signal disconnects and disposes of any inherited parent process pool, ensuring worker processes never share socket file descriptors across OS forks.
- **Task Session Scope:**
  ```python
  @contextmanager
  def worker_session_scope() -> Generator[Session, None, None]:
      factory = get_worker_session_factory()
      session: Session = factory()
      try:
          yield session
          session.commit()
      except Exception:
          session.rollback()
          raise
      finally:
          session.close()
  ```
- **Transaction Invariant:** Database sessions are strictly short-lived (claim and heartbeat ticks). Zero database connections, transactions, or row locks are held during repository fetching, extraction, or model inference.

### 3.3 Atomic Job Claim Protocol ([`apps/api/workers/lease_manager.py`](file:///home/shubh/scorva/apps/api/workers/lease_manager.py))
Atomically claims eligible queued jobs using PostgreSQL server time:
```sql
UPDATE evaluation_jobs
SET status = 'running',
    claim_token = :claim_token,
    lock_version = lock_version + 1,
    attempts_count = attempts_count + 1,
    started_at = clock_timestamp(),
    last_heartbeat_at = clock_timestamp(),
    lease_expires_at = clock_timestamp() + (:lease_seconds || ' seconds')::interval
WHERE id = :job_id
  AND status = 'queued'
  AND cancellation_requested = false
  AND attempts_count < max_attempts
RETURNING id, organization_id, hackathon_id, submission_id, snapshot_id,
          rubric_version_id, status, lock_version, claim_token,
          attempts_count, max_attempts, lease_expires_at, cancellation_requested;
```
- **Duplicate Harmlessness:** Any message arriving for a `running`, `completed`, `failed`, `cancelled`, or nonexistent job matches 0 rows. It returns `None` and discards harmlessly without incrementing counters or altering state.
- **Monotonic Fencing:** Increments `lock_version` and installs a unique `claim_token` tied to the worker identity.

### 3.4 Lease Renewal & Fencing Protocol ([`apps/api/workers/lease_manager.py`](file:///home/shubh/scorva/apps/api/workers/lease_manager.py))
Atomic heartbeat query enforcing storage-fenced execution:
```sql
UPDATE evaluation_jobs
SET last_heartbeat_at = clock_timestamp(),
    lease_expires_at = clock_timestamp() + (:lease_seconds || ' seconds')::interval
WHERE id = :job_id
  AND status = 'running'
  AND claim_token = :claim_token
  AND lock_version = :lock_version
  AND lease_expires_at > clock_timestamp()
RETURNING id, lock_version, lease_expires_at, cancellation_requested;
```
- **Late Heartbeat Rejection:** If `lease_expires_at <= clock_timestamp()`, the lease has already lapsed. The query updates 0 rows, diagnosing `LEASE_EXPIRED`. The lease is never revived.
- **Fencing Protection:** If `lock_version` or `claim_token` does not match (e.g. job was reclaimed by a replacement worker or reaper), 0 rows are updated, protecting replacement workers.
- **Cooperative Cancellation:** Returns `cancellation_requested`. If `True`, the worker cleanly aborts execution.
- **Background Thread (`HeartbeatController`):** Manages periodic renewal in a background daemon thread, executing short-lived transactions and exposing `check_health()`.

### 3.5 Evaluation Task Consumer ([`apps/api/workers/tasks.py`](file:///home/shubh/scorva/apps/api/workers/tasks.py))
- **Minimal Payload:** Accepts only `job_id: str`. Zero repository contents, credentials, or transient payloads.
- **Safe Claim:** Calls `WorkerLeaseManager.claim_job_sync(...)`.
- **Harmless Discard:** Non-claimable jobs return `{"status": "discarded", "reason": "NOT_CLAIMABLE"}`.

---

## 4. Inventory of Modified & Created Files

| File | Status | Description |
| :--- | :---: | :--- |
| [`apps/api/workers/__init__.py`](file:///home/shubh/scorva/apps/api/workers/__init__.py) | Created | Worker package initialization |
| [`apps/api/workers/database.py`](file:///home/shubh/scorva/apps/api/workers/database.py) | Created | Synchronous worker database engine, connection pool, and `worker_session_scope` |
| [`apps/api/workers/lease_manager.py`](file:///home/shubh/scorva/apps/api/workers/lease_manager.py) | Created | `WorkerLeaseManager` (atomic claim, heartbeat renewal, fencing) and `HeartbeatController` |
| [`apps/api/workers/celery_app.py`](file:///home/shubh/scorva/apps/api/workers/celery_app.py) | Created | Celery application bootstrap, Redis broker config, task routing |
| [`apps/api/workers/tasks.py`](file:///home/shubh/scorva/apps/api/workers/tasks.py) | Created | Celery evaluation task consumer `evaluate_submission` |
| [`apps/api/modules/evaluations/service.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/service.py) | Modified | In-flight deduplication for requests without `Idempotency-Key` |
| [`apps/api/pyproject.toml`](file:///home/shubh/scorva/apps/api/pyproject.toml) | Modified | Added `celery>=5.4.0` and `psycopg2-binary>=2.9.0` dependencies |
| [`apps/api/tests/test_evaluation_outbox_m5_1.py`](file:///home/shubh/scorva/apps/api/tests/test_evaluation_outbox_m5_1.py) | Modified | Added focused M5.1 regression tests (quarantine unexpired immunity, missing key handling) |
| [`apps/api/tests/test_worker_engine_m5_2.py`](file:///home/shubh/scorva/apps/api/tests/test_worker_engine_m5_2.py) | Created | 12 dedicated automated M5.2 tests on PostgreSQL 16 |
| [`docs/PHASE_5_PLAN.md`](file:///home/shubh/scorva/docs/PHASE_5_PLAN.md) | Modified | Updated Sub-Milestone 5.2 to Completed & Verified |

---

## 5. Automated Test Execution Evidence

### 5.1 M5.2 Test Suite (`test_worker_engine_m5_2.py`)
```bash
.venv/bin/pytest apps/api/tests/test_worker_engine_m5_2.py -v
```
```
============================= test session starts ==============================
collected 12 items

apps/api/tests/test_worker_engine_m5_2.py::test_successful_worker_claim PASSED [  8%]
apps/api/tests/test_worker_engine_m5_2.py::test_duplicate_message_while_job_running_discarded PASSED [ 16%]
apps/api/tests/test_worker_engine_m5_2.py::test_terminal_and_cancelled_jobs_claim_rejected PASSED [ 25%]
apps/api/tests/test_worker_engine_m5_2.py::test_concurrent_worker_claims PASSED [ 33%]
apps/api/tests/test_worker_engine_m5_2.py::test_valid_heartbeat_renewal PASSED [ 41%]
apps/api/tests/test_worker_engine_m5_2.py::test_expired_lease_renewal_rejected PASSED [ 50%]
apps/api/tests/test_worker_engine_m5_2.py::test_stale_claim_token_rejection PASSED [ 58%]
apps/api/tests/test_worker_engine_m5_2.py::test_lock_version_mismatch_rejection PASSED [ 66%]
apps/api/tests/test_worker_engine_m5_2.py::test_cancellation_racing_with_heartbeat_renewal PASSED [ 75%]
apps/api/tests/test_worker_engine_m5_2.py::test_worker_session_cleanup_and_transaction_rollback PASSED [ 83%]
apps/api/tests/test_worker_engine_m5_2.py::test_celery_task_evaluate_submission_minimal_payload_and_idempotence PASSED [ 91%]
apps/api/tests/test_worker_engine_m5_2.py::test_heartbeat_controller_background_thread_and_cancellation PASSED [100%]

============================== 12 passed in 3.90s ==============================
```

### 5.2 Combined M5.1 & M5.2 Suites
```bash
.venv/bin/pytest apps/api/tests/test_evaluation_outbox_m5_1.py apps/api/tests/test_worker_engine_m5_2.py -v
```
```
======================= 32 passed, 10 warnings in 12.11s =======================
```

### 5.3 Full System Regression Suite
```bash
.venv/bin/pytest apps/api/tests/ -k "not test_github_client and not test_integrations_service"
```
```
297 passed, 14 deselected, 186 warnings in 138.17s (0:02:18)
```
**Zero regressions across the entire project.**

---

## 6. Known Scope Boundaries & Next Sub-Milestone Readiness

### 6.1 Known Boundaries (Strictly Preserved)
- **Sub-Milestone 5.3 (Pipeline Execution & Fenced Atomic Persistence):** Full multi-stage pipeline orchestration (`repo_acquisition`, `safe_extraction`, `evidence_indexing`, `model_evaluation`, `output_validation`, `score_calculation`, `persistence`) and CAS atomic result transactions remain un-scaffolded.
- **Sub-Milestone 5.4 (Reaper Daemon & Fault Recovery):** Celery Beat periodic reaper daemon for sweeping expired claims and requeuing retryable jobs remains un-scaffolded.
- **Sub-Milestone 5.5 (Tenant Concurrency Throttling & Hardening):** Redis distributed semaphore for org concurrency bounding remains un-scaffolded.

### 6.2 Readiness for Sub-Milestone 5.3
Sub-Milestone 5.2 establishes the worker runtime, thread-safe database pooling, task-scoped transactions, and lease/fencing manager. The system is ready for Sub-Milestone 5.3 whenever authorized.

---

## 7. Final Acceptance Verdict

### **Verdict: PASS (SUB-MILESTONE 5.2 COMPLETE & VERIFIED)**

- **M5.1 Checks & Hardening:** PASS (Quarantine pre-expiry immunity and missing key deduplication verified)
- **Celery Integration:** PASS (Minimal payload, late ACKs, JSON serialization, prefetch 1)
- **Worker Database Lifecycle:** PASS (Dedicated `QueuePool`, fork safety, short-lived sessions, zero locks during compute)
- **Atomic Job Claim:** PASS (PostgreSQL server time, `queued` $\rightarrow$ `running`, token install, monotonic fencing)
- **Lease Renewal & Fencing:** PASS (Storage-fenced renewal, late heartbeat rejection, cancellation detection)
- **Automated Tests:** PASS (12/12 M5.2 tests passing; 297/297 full regression suite passing)
- **Scope Discipline:** PASS (Sub-Milestones 5.3–5.5 remain strictly blocked)

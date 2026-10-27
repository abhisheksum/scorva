# Scorva Phase 4 Milestone 5 — Sub-Milestone 5.4 Completion Report

**Document Version:** 1.0  
**Date:** October 26, 2026  
**Status:** **SUB-MILESTONE 5.4 IMPLEMENTED, TESTED & VERIFIED (PASS)**  
**Milestone 5 Implementation Scope:** Sub-Milestone 5.4 (Crash Recovery, Retry Scheduling & Cooperative Cancellation)  
**Post-5.4 Implementation Status:** **Sub-Milestone 5.5 (Concurrency Throttling, Observability & Hardening) STRICTLY BLOCKED & PENDING EXPLICIT AUTHORIZATION**  
**Database Verification Target:** PostgreSQL 16 on `:5432` (`scorva` database)  
**Test Suite Verification:**
- `apps/api/tests/test_reaper_m5_4.py`: **18/18 passed** (100%)
- Combined M5.1, M5.2, M5.3, M5.4 suites: **61/61 passed** (100%)
- Full project regression suite: **326 passed**, 0 failed, 14 deselected (zero regressions)

---

## 1. Executive Summary & Authorization Context

Pursuant to explicit user authorization for **Phase 4, Sub-Milestone 5.4: Crash Recovery, Retry Scheduling & Cooperative Cancellation**, the background crash recovery engine, exponential backoff retry scheduler, fencing token invalidator, and cooperative cancellation lifecycle have been implemented and verified against PostgreSQL 16.

Sub-Milestone 5.4 completes the automated self-healing and lifecycle management layer of the Scorva distributed evaluation architecture. It guarantees that:
1. **No Worker Zombie Leases:** Expired worker leases are detected and reclaimed automatically without human intervention.
2. **Deterministic Fencing Invalidation:** Any recovery action monotonically advances the job's `lock_version` and clears its `claim_token`, permanently fencing out zombie or late-arriving workers.
3. **No Hot-Loop Retries:** Exponential backoff with proportional jitter prevents thundering herds and retry storms against the worker pool and AI providers.
4. **Clean Cooperative Cancellation:** In-flight cancellation is respected cooperatively during worker heartbeats and pipeline stage boundaries, and definitively in-lock prior to any persistence. Stalled cancelled jobs are finalized upon lease expiry without retry.
5. **No Race Hazards:** Cancellation vs completion races serialize deterministically under PostgreSQL row locks; if completion locks first, cancellation returns HTTP 409 `CANNOT_CANCEL_COMPLETED`.

---

## 2. Implemented Architecture & Protocol Details

### 2.1 Expired-Job Reaper Engine ([`apps/api/workers/reaper.py`](file:///home/shubh/scorva/apps/api/workers/reaper.py))

The reaper engine operates periodically (every 15s via Celery Beat) or synchronously via `reap_stalled_evaluation_jobs_sync` / `reap_stalled_evaluation_jobs_async`:

```
                           [Reaper Sweep Trigger]
                                      │
                                      ▼
             SELECT ... FOR UPDATE SKIP LOCKED
             WHERE status = 'running' AND lease_expires_at < clock_timestamp()
                                      │
               ┌──────────────────────┼──────────────────────┐
               ▼                      ▼                      ▼
    [cancellation_requested]    [attempts >= max]     [attempts < max]
               │                      │                      │
       status = 'cancelled'    status = 'failed'      status = 'queued'
       claim_token = NULL     claim_token = NULL     claim_token = NULL
       lock_version + 1       lock_version + 1       lease_expires_at = now + backoff
       dead-letter outbox     dead-letter outbox     lock_version + 1
       audit cancelled        audit exhausted        dispatch_generation + 1
                                                     supersede active outbox
                                                     insert retry outbox
                                                     audit reaped_retry
```

#### Key Guarantees:
- **`SELECT ... FOR UPDATE SKIP LOCKED`**: Competing reaper workers sweep disjoint batches of expired jobs simultaneously without deadlocking or duplicate processing.
- **Clock Synchronization**: All lease validity checks evaluate strictly against PostgreSQL `clock_timestamp()`. Worker system clocks are never trusted.
- **Audit Logging**: Every transition emits an immutable `AuditEvent` (`actor_role='system'`, outcome=SUCCESS/FAILURE) recording reason and version bump.

---

### 2.2 Exponential Backoff Retry Scheduling with Proportional Jitter

Retry backoff is computed via `calculate_exponential_backoff`:

$$\text{delay} = \min\left(\text{max\_seconds}, \text{base\_seconds} \times 2^{\text{attempts} - 1}\right) + \text{jitter}$$

- **Zero-Migration Scheduling**: When a job is reaped for retry, the reaper stores the scheduled retry timestamp in the existing `evaluation_jobs.lease_expires_at` column while setting `status = 'queued'`.
- **Worker Claim Guard**: In [`apps/api/workers/lease_manager.py`](file:///home/shubh/scorva/apps/api/workers/lease_manager.py), both sync and async worker claim queries enforce:
  ```sql
  WHERE id = :job_id
    AND status = 'queued'
    AND cancellation_requested = false
    AND attempts_count < max_attempts
    AND (lease_expires_at IS NULL OR lease_expires_at <= clock_timestamp())
  ```
  Workers are physically barred from claiming the job until the backoff window elapses.
- **Outbox Relay Staging**: The new `evaluation_job_outbox` row is created with `status = 'processing'` and `relay_expires_at = clock_timestamp() + interval(backoff)`, ensuring the outbox relay also defers dispatch until the backoff expires.

---

### 2.3 Fence Invalidation Across Recovery

Whenever the reaper recovers a job:
1. `claim_token` is cleared (`NULL`).
2. `lock_version` is incremented (`lock_version = lock_version + 1`).
3. If the zombie worker wakes up and attempts a heartbeat, `WorkerLeaseManager.renew_lease` checks `lock_version == :expected_lock_version` and `claim_token == :expected_token`, which fail with `LOCK_VERSION_MISMATCH` or `CLAIM_TOKEN_MISMATCH`.
4. If the zombie worker attempts a fenced result commit, `commit_evaluation_result_fenced` acquires the exclusive row lock, inspects `lock_version` and `claim_token`, and immediately aborts the transaction with zero writes.
5. Prior active outbox dispatches are marked `dead_lettered` (`SUPERSEDED_BY_RETRY`) before inserting the new outbox row, preserving the partial unique index `uq_eval_job_outbox_active_dispatch`.

---

### 2.4 Cooperative Cancellation System

The cancellation lifecycle coordinates four distinct states:

| Scenario | Job State | Action Taken | Guarantee |
| :--- | :--- | :--- | :--- |
| **Queued Cancellation** | `status = 'queued'` | Atomically transitions `status = 'cancelled'`, `cancellation_requested = true`, increments `lock_version`, dead-letters active outbox records. | No worker ever claims or executes the job. |
| **Running Cooperative** | `status = 'running'` | Atomically sets `cancellation_requested = true`. Worker heartbeat and stage checks detect flag, raising `JobCancelledError`. Fenced commit in-lock check transitions job to `cancelled` with zero writes. | Zero partial results committed to `evaluation_results`. |
| **Abandoned Cancellation** | `status = 'running'`, worker died | Worker dies before aborting. Lease expires. Reaper detects `cancellation_requested == true` and finalizes directly to `status = 'cancelled'` with `error_code='CANCELLED_AFTER_LEASE_EXPIRY'`. | Job does not get requeued. |
| **Completion Race** | Worker committing vs User cancelling | Synchronized under pessimistic PostgreSQL row lock (`SELECT ... FOR UPDATE`). If completion locks first, cancellation returns HTTP 409 `CANNOT_CANCEL_COMPLETED`. | Strict serialization; no ambiguous hybrid state. |

---

## 3. Files Created & Modified

| File | Purpose / Modifications |
| :--- | :--- |
| [`apps/api/workers/reaper.py`](file:///home/shubh/scorva/apps/api/workers/reaper.py) | **[Created]** Complete Expired-Job Reaper Engine (`calculate_exponential_backoff`, `ReapedJobResult`, `ReaperBatchReport`, `reap_stalled_evaluation_jobs_sync`, `reap_stalled_evaluation_jobs_async`, `reap_stalled_evaluation_jobs_task`). |
| [`apps/api/workers/lease_manager.py`](file:///home/shubh/scorva/apps/api/workers/lease_manager.py) | **[Modified]** Added backoff guard `AND (lease_expires_at IS NULL OR lease_expires_at <= clock_timestamp())` to `claim_job_sync` and `claim_job_async`. Replaced string concatenation with `* interval '1 second'` for driver compatibility. |
| [`apps/api/modules/evaluations/service.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/service.py) | **[Modified]** Implemented `CancellationResult`, `cancel_evaluation_job_atomic`, and `cancel_evaluation_job_atomic_sync`. Added `execution_options(populate_existing=True)` and safe fallback metadata for audit events. |
| [`apps/api/modules/evaluations/router.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/router.py) | **[Modified]** Added authenticated, tenant-scoped `POST /organizations/{org_id}/evaluations/{job_id}/cancel` endpoint. |
| [`apps/api/workers/pipeline.py`](file:///home/shubh/scorva/apps/api/workers/pipeline.py) | **[Modified]** Integrated cancellation check in fenced result commit to mark job `cancelled` and abort with zero writes. Updated `run_evaluation_pipeline` return code. |
| [`apps/api/workers/celery_app.py`](file:///home/shubh/scorva/apps/api/workers/celery_app.py) | **[Modified]** Configured Celery Beat periodic schedule for `reap-stalled-evaluation-jobs` running every 15s. |
| [`apps/api/tests/test_reaper_m5_4.py`](file:///home/shubh/scorva/apps/api/tests/test_reaper_m5_4.py) | **[Created]** 18 comprehensive automated integration tests verifying all reaper and cancellation scenarios against PostgreSQL 16. |
| [`docs/PHASE_5_PLAN.md`](file:///home/shubh/scorva/docs/PHASE_5_PLAN.md) | **[Modified]** Updated Sub-Milestone 5.4 status to `[COMPLETED & VERIFIED]`. |

---

## 4. Automated Verification Results

### 4.1 Sub-Milestone 5.4 Test Suite (`test_reaper_m5_4.py`)
All 18 scenarios passed cleanly against PostgreSQL 16:
1. `test_expired_running_job_is_recovered_and_receives_durable_outbox_dispatch` (PASS)
2. `test_unexpired_running_job_is_not_reclaimed` (PASS)
3. `test_completed_failed_cancelled_jobs_are_not_reclaimed` (PASS)
4. `test_exhausted_job_transitions_to_terminal_failure_state` (PASS)
5. `test_retryable_jobs_respect_max_attempts` (PASS)
6. `test_backoff_prevents_immediate_repeated_retries` (PASS)
7. `test_backoff_calculation_and_jitter_bounds` (PASS)
8. `test_concurrent_reapers_safely_process_disjoint_rows_with_skip_locked` (PASS)
9. `test_stale_worker_cannot_heartbeat_after_recovery` (PASS)
10. `test_stale_worker_cannot_commit_results_after_recovery` (PASS)
11. `test_heartbeat_versus_reaper_race_handled_safely` (PASS)
12. `test_result_commit_versus_reaper_race_handled_safely` (PASS)
13. `test_queued_cancellation_prevents_worker_execution` (PASS)
14. `test_running_cancellation_prevents_result_commitment` (PASS)
15. `test_abandoned_cancellation_finalized_after_lease_expiry` (PASS)
16. `test_repeated_cancellation_requests_are_idempotent` (PASS)
17. `test_outbox_publication_failure_preserves_durable_recovery_state` (PASS)
18. `test_cancel_evaluation_job_endpoint_http_contract` (PASS)

### 4.2 Combined Milestone 5 Suites
```
apps/api/tests/test_evaluation_outbox_m5_1.py ....................       [ 32%]
apps/api/tests/test_worker_engine_m5_2.py ............                   [ 52%]
apps/api/tests/test_pipeline_m5_3.py ...........                         [ 70%]
apps/api/tests/test_reaper_m5_4.py ..................                    [100%]
======================= 61 passed, 10 warnings in 21.04s =======================
```

### 4.3 Full Backend Regression Suite
```
326 passed, 14 deselected, 186 warnings in 150.67s (0:02:30)
```
**Regressions: ZERO.**

---

## 5. Implementation Status & Next Steps

Sub-Milestone 5.4 is **100% complete and verified**.

### Operating Mode Constraint:
- **Sub-Milestone 5.5: Concurrency Throttling, Observability & Hardening remains STRICTLY BLOCKED and UNAUTHORIZED.**
- No code or infrastructure for Sub-Milestone 5.5 will be modified or created until explicit user authorization is received.

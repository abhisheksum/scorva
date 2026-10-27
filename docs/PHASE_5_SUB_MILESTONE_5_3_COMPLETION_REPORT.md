# Scorva Phase 4 Milestone 5 — Sub-Milestone 5.3 Completion Report

**Document Version:** 1.0  
**Date:** October 26, 2026  
**Status:** **SUB-MILESTONE 5.3 IMPLEMENTED, TESTED & VERIFIED**  
**Milestone 5 Implementation Scope:** Sub-Milestone 5.3 (Pipeline Orchestration & Fenced Atomic Result Persistence)  
**Post-5.3 Implementation Status:** **Sub-Milestones 5.4–5.5 STRICTLY BLOCKED & PENDING EXPLICIT AUTHORIZATION**  
**Database Verification Target:** PostgreSQL 16 on `:5432` (`scorva` database)  
**Test Suite Verification:**
- `apps/api/tests/test_pipeline_m5_3.py`: **11/11 passed** (100%)
- Combined M5.1, M5.2, M5.3 suites: **43/43 passed** (100%)
- Full project regression suite: **308 passed**, 0 failed, 14 deselected (zero regressions)

---

## 1. Executive Summary & Authorization Context

Pursuant to explicit user authorization for **Phase 4, Sub-Milestone 5.3: Pipeline Orchestration & Fenced Atomic Result Persistence**, the end-to-end evaluation execution pipeline and in-database pessimistic fencing protocol have been implemented and verified.

The core deliverable of Sub-Milestone 5.3 enforces the central distributed system guarantee:

> **A stale worker must never overwrite a newer worker's result, and evaluation results must never be partially committed.**

### Sub-Milestone 5.3 Key Achievements:
1. **End-to-End Evaluation Pipeline (`apps/api/workers/pipeline.py`):**
   - Atomically claims the queued job via M5.2 `WorkerLeaseManager`.
   - Spawns background `HeartbeatController` thread renewing the lease with PostgreSQL server time (`clock_timestamp()`).
   - Rehydrates and verifies tenant-isolated evaluation context (`EvaluationJob`, `Submission`, `SubmissionSnapshot`, `RubricVersion`, `RubricCriterion`).
   - Builds `EvidenceIndex` from frozen submission snapshot manifest.
   - Compiles rubric prompt using M4 `compile_evaluation_prompt` and grammar schema via `get_evaluation_json_schema()`.
   - Executes AI model inference via `AIProviderClient` / `execute_evaluation_with_retry` using `_safe_run_async` (preventing thread pool and event loop blocking across Celery worker forks).
   - Computes raw and normalized scores deterministically via M2 `calculate_evaluation_scores`.
   - Executes atomic fenced result persistence under PostgreSQL pessimistic row lock.
2. **Atomic Fenced Result Commitment Protocol (Approach 2 with Pessimistic Row Locking):**
   - Single PostgreSQL transaction coordinates both guard verification and all result insertions.
   - Acquires row lock via `SELECT ... FOR UPDATE` on `evaluation_jobs`.
   - Enforces in-lock guards:
     - `status == 'running'`
     - `claim_token == claim.claim_token`
     - `lock_version == claim.lock_version`
     - `lease_expires_at > clock_timestamp()`
     - `cancellation_requested == false`
   - Atomically inserts `EvaluationResult`, `EvaluationCriterionScore`, `EvidenceReference`, and `AuditEvent`.
   - Atomically updates `EvaluationJob` to `status = 'completed'` with incremented `lock_version`.
   - Guaranteed rollback on any guard failure or unexpected exception: 0 orphaned rows or partial writes.
3. **Task Consumer Wiring (`apps/api/workers/tasks.py`):**
   - Celery `evaluate_submission` task delegates execution to `run_evaluation_pipeline`.
   - Safe duplicate delivery handling: non-claimable jobs return `discarded` without side effects.

---

## 2. Implemented Architecture & Protocol Details

### 2.1 Pipeline Orchestrator ([`apps/api/workers/pipeline.py`](file:///home/shubh/scorva/apps/api/workers/pipeline.py))

The evaluation pipeline coordinates the 8 sequential stages in worker memory with short-lived database transactions:

```
[Celery Message: job_id]
         │
         ▼
[Stage 1: Short-Lived Claim] ──► Atomic UPDATE 'queued' -> 'running' (lock_version + 1)
         │
         ▼
[Heartbeat Thread Started]   ──► Periodic UPDATE lease_expires_at = clock_timestamp() + TTL
         │
         ▼
[Stage 2: Context Rehydration] ──► Tenant Scoping: Job, Submission, Snapshot, Rubric, Criteria
         │
         ▼
[Stage 3: Evidence Indexing]   ──► EvidenceIndex built from snapshot metadata manifest
         │
         ▼
[Stage 4: Prompt Compilation]  ──► compile_evaluation_prompt() + JSON Schema Grammar
         │
         ▼
[Stage 5: AI Model Inference]  ──► execute_evaluation_with_retry() via _safe_run_async()
         │
         ▼
[Stage 6: Score Calculation]   ──► calculate_evaluation_scores() (Raw & Normalized)
         │
         ▼
[Stage 7: Fenced Commit]       ──► Pessimistic SELECT ... FOR UPDATE + In-Lock Guards
                                   + INSERT EvaluationResult, CriterionScores, EvReferences, Audit
                                   + UPDATE EvaluationJob status='completed', lock_version + 1
                                   COMMIT (All-or-Nothing)
```

### 2.2 Fenced Atomic Result Persistence Protocol

The persistence protocol implemented in `commit_evaluation_result_fenced_sync` and `commit_evaluation_result_fenced_async` operates within a single PostgreSQL transaction:

```sql
-- Step 1: Acquire exclusive row lock and evaluate guards against authoritative server time
SELECT id, status, claim_token, lock_version, lease_expires_at, cancellation_requested,
       (lease_expires_at > clock_timestamp()) AS is_lease_valid
FROM evaluation_jobs
WHERE id = :job_id
FOR UPDATE;

-- Step 2: In-lock assertions evaluated by application:
-- If status != 'running'                  -> ROLLBACK (JOB_NOT_RUNNING)
-- If claim_token != claim.claim_token     -> ROLLBACK (CLAIM_TOKEN_MISMATCH)
-- If lock_version != claim.lock_version   -> ROLLBACK (FENCING_TOKEN_MISMATCH)
-- If NOT is_lease_valid                   -> ROLLBACK (LEASE_EXPIRED)
-- If cancellation_requested               -> ROLLBACK (CANCELLATION_REQUESTED)

-- Step 3: Insert Authoritative Result
INSERT INTO evaluation_results (
    id, organization_id, hackathon_id, submission_id, rubric_version_id,
    job_id, snapshot_id, attempt_number, model_provider, model_name,
    prompt_version, raw_score, normalized_score, summary_assessment,
    has_insufficient_evidence, created_at
) VALUES (:id, :org_id, :hack_id, :sub_id, :rv_id, :job_id, :snap_id,
          :attempt_number, :provider, :model, :prompt_ver, :raw_score,
          :norm_score, :summary, :insufficient_ev, clock_timestamp());

-- Step 4: Insert Criterion Scores & Evidence References
INSERT INTO evaluation_criterion_scores (...);
INSERT INTO evidence_references (...);

-- Step 5: Insert Immutable Audit Event
INSERT INTO audit_events (...);

-- Step 6: Atomically transition job to completed with monotonic fencing increment
UPDATE evaluation_jobs
SET status = 'completed',
    current_result_id = :result_id,
    completed_at = clock_timestamp(),
    lock_version = lock_version + 1,
    current_stage = 'persistence'
WHERE id = :job_id
  AND lock_version = :lock_version
  AND claim_token = :claim_token;

-- Step 7: Commit transaction
COMMIT;
```

---

## 3. Automated Test Suite & Concurrency Verification

All automated tests in [`apps/api/tests/test_pipeline_m5_3.py`](file:///home/shubh/scorva/apps/api/tests/test_pipeline_m5_3.py) run directly against **PostgreSQL 16** on `:5432`.

### Test Results Breakdown:

| Test Identifier | Tested Invariant / Concurrency Condition | Result |
| :--- | :--- | :---: |
| `test_successful_end_to_end_pipeline_evaluation_and_atomic_commit` | Claims job, compiles prompt, runs mock inference, validates rubric scores, calculates weights, persists results & audit log, marks job `completed`. | **PASS** |
| `test_invalid_provider_output_rejected_without_partial_result_writes` | Malformed or out-of-bounds provider score is rejected; transaction rolls back; 0 rows written to `evaluation_results`; job fails. | **PASS** |
| `test_missing_or_invalid_inputs_handled_safely` | Cross-tenant snapshot mismatch detected; pipeline safely marks job `failed` with `INPUT_NOT_FOUND` without crashing. | **PASS** |
| `test_duplicate_delivery_does_not_create_duplicate_evaluation_results` | Redelivered Celery message for already-claimed job returns `discarded`; exactly 1 `EvaluationResult` exists. | **PASS** |
| `test_stale_claim_token_cannot_commit_results` | Worker with stale claim token attempts persistence; row lock guard rejects with `CLAIM_TOKEN_MISMATCH`; 0 rows written. | **PASS** |
| `test_lock_version_mismatch_cannot_commit_results` | Worker with superseded `lock_version` attempts persistence; guard rejects with `FENCING_TOKEN_MISMATCH`; 0 rows written. | **PASS** |
| `test_expired_lease_cannot_commit_results` | Worker whose lease expired before commit attempts persistence; `clock_timestamp()` guard rejects with `LEASE_EXPIRED`; 0 rows written. | **PASS** |
| `test_lease_loss_during_inference_prevents_result_commitment` | Heartbeat detects lease stolen/expired mid-inference; pipeline aborts before attempting result commitment. | **PASS** |
| `test_cancellation_before_commitment_prevents_result_commitment` | Cancellation flag set mid-flight; guard rejects commitment with `CANCELLATION_REQUESTED`; 0 rows written. | **PASS** |
| `test_database_failure_during_result_persistence_rolls_back_all_writes` | Injected database error during criterion insertion rolls back entire transaction; 0 partial rows in database. | **PASS** |
| `test_job_completion_and_evaluation_results_are_committed_atomically` | Verifies atomic commitment invariant: `EvaluationJob.status == 'completed'` and `EvaluationResult` exist together, never in isolation. | **PASS** |

---

## 4. Full Regression Verification

Following M5.3 implementation, the full suite of automated tests was executed across all platform subsystems:

```
============================== test session starts ==============================
platform linux -- Python 3.14.8, pytest-9.1.1, pluggy-1.7.0
rootdir: /home/shubh/scorva/apps/api
configfile: pyproject.toml
plugins: anyio-4.15.1, asyncio-1.4.0

308 passed, 14 deselected, 186 warnings in 149.58s (0:02:29)
```

- **M5.1 Outbox & Idempotency:** 20/20 passed
- **M5.2 Worker Engine & Lease Manager:** 12/12 passed
- **M5.3 Pipeline Orchestrator & Persistence:** 11/11 passed
- **Total Milestone 5 Automated Tests:** 43/43 passed
- **Subsystem Regressions:** **0 regressions across 308 platform tests**

---

## 5. Strict Authorization Boundary & Next Steps

Sub-Milestone 5.3 is **COMPLETED and FULLY VERIFIED**.

In strict accordance with project governance:
- **Sub-Milestone 5.4: Crash Reaper, Retries & Cooperative Cancellation** remains **BLOCKED AND UNAUTHORIZED**.
- **Sub-Milestone 5.5: Concurrency Throttling, Observability & Hardening** remains **BLOCKED AND UNAUTHORIZED**.
- No implementation, code generation, or migrations for Sub-Milestones 5.4 or 5.5 will proceed without explicit user authorization.

**Acceptance Verdict: PASS**

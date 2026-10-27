# SCORVA — SUB-MILESTONE 6.4 COMPLETION REPORT
## AI Evaluation Transparency & Judge-Facing Evidence

### 1. Executive Summary

Sub-Milestone 6.4 delivers end-to-end transparency for automated AI evaluations, bridging Phase 5's transactional evaluation infrastructure with Scorva's judge- and organizer-facing product interface. Authorized organizers and judges can now inspect real-time job execution states, examine criterion-level AI assessments, verify grounded code evidence citations (file paths, line numbers, and quoted code snippets), diagnose execution failures safely without credential or stack trace exposure, and track re-evaluation histories.

In accordance with Scorva's core product principle:
> *"AI evaluates the evidence. Judges make the decisions. Scorva makes the process transparent."*

All AI assessments, scores, and evidence references remain strictly decoupled from human judge review decisions (which will be implemented in M6.5), ensuring automated outputs provide verifiable advisory evidence rather than final human determinations.

All backend schemas, service functions, REST endpoints, frontend types, API client methods, dashboard/modal UI components, and automated test suites have been verified with zero regressions.

---

### 2. Implemented Capabilities & Invariant Guarantees

#### 2.1 Multi-Tenant Evaluation Detail & Provenance API
- **Full Transparency Payload:**
  - `get_submission_evaluation_detail` returns a comprehensive view of the submission's evaluation state:
    - Latest `EvaluationJob` metadata (`status`, `attempt_count`, `max_attempts`, timestamps, duration in ms).
    - Immutable `SubmissionSnapshot` metadata (`commit_sha`, snapshot tree timestamp).
    - Associated `RubricVersion` information (`version`, `title`, publication state).
    - `EvaluationResultDetail` with raw score, maximum possible score, normalized (0–100) score, summary, and insufficient evidence flag.
    - Criterion-by-criterion assessment array with criterion weights, min/max score bounds, AI rationale, and grounded evidence references.
    - Append-only prior evaluation runs audit trail tracking past jobs and scores.
- **Strict Grounding & Provenance:**
  - Every score and criterion rationale is sourced directly from persisted `EvaluationResult` and `EvaluationCriterionScore` records.
  - Every evidence citation references verified repository files and line numbers stored in `EvidenceReference` records.
  - Scorva never fabricates confidence ratings, explanations, or code references not returned by the validated AI output engine.
- **Score Precision Invariant:**
  - Raw and normalized scores strictly maintain `Numeric(5, 2)` / `Numeric(6, 2)` Decimal precision without floating-point conversion errors.

#### 2.2 Error Sanitization & Safe Failure Diagnostics
- **Safe Error Categories:**
  - Handled via `SAFE_ERROR_DESCRIPTIONS` and `sanitize_error_for_display` in [schemas.py](file:///home/shubh/scorva/apps/api/modules/evaluations/schemas.py).
  - Internal stack traces, absolute server file paths, prompt templates, database errors, and API credentials are completely stripped.
  - Mapped to transparent, safe user-facing categories:
    - `PROVIDER_RATE_LIMIT`: AI provider rate limit reached; queued for automatic backoff retry.
    - `PROVIDER_TIMEOUT`: Evaluation exceeded processing deadline; automatic retry scheduled.
    - `ACQUISITION_TIMEOUT`: Repository snapshot acquisition timed out; retry scheduled.
    - `OUTPUT_VALIDATION_FAILED`: Evaluation output failed schema validation; retrying.
    - `EVALUATION_CANCELLED`: Job cancelled by organizer.
    - `WORKER_CRASHED`: Worker lease expired unexpectedly; recovered by reaper.
    - `EVALUATION_FAILED`: Automated evaluation could not complete after maximum attempts.
- **Eligibility Guidance for Empty States:**
  - When a submission has not been evaluated, the API provides structured `eligibility_reason` strings (e.g. `NO_REPOSITORY_LINKED`, `REPOSITORY_NOT_VERIFIED`, `NO_PUBLISHED_RUBRIC`, `READY_FOR_EVALUATION`).

#### 2.3 Dashboard Evaluation Triggering
- **Pre-flight Validation:**
  - `POST /submissions/{submission_id}/evaluate` validates:
    1. Organization and hackathon tenant authorization.
    2. Submission existence and ownership.
    3. Verified repository connection (`submission.connection_status == 'verified'`) and target branch commit SHA (`submission.verified_commit_sha`).
    4. Published rubric existence for the hackathon (`rubric.status == 'published'`).
    5. Prevention of concurrent duplicate runs if an evaluation job is already `queued` or `running`.
- **Atomic Dispatch:**
  - Resolves or creates an immutable `SubmissionSnapshot` record for the submission's verified commit SHA.
  - Creates an `EvaluationJob` in `queued` state.
  - Enqueues a transactional `EvaluationJobOutbox` record in the same atomic database transaction.
  - Emits an append-only `evaluation_triggered` audit event.

#### 2.4 Multi-Tenant and Hackathon Isolation
- All evaluation endpoints strictly enforce `organization_id` and `hackathon_id` scoping at the database query level.
- Cross-tenant requests return `HTTP 403 Forbidden` or `HTTP 404 Not Found`.

---

### 3. API Endpoints Mounted

| Method | Endpoint | Auth | Response | Purpose |
|---|---|---|---|---|
| `GET` | `/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/evaluations/summary` | Org Member | `HackathonEvaluationSummaryResponse` | Aggregates hackathon evaluation metrics (total submissions, evaluated, queued, running, failed, average AI score, published rubric status). |
| `GET` | `/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/evaluations` | Org Member | `List[EvaluationJobListItem]` | Paginated list of hackathon evaluation jobs with status filtering. |
| `GET` | `/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}/evaluation` | Org Member | `SubmissionEvaluationTransparencyResponse` | Full evaluation transparency payload with criteria, scores, grounded evidence citations, safe error diagnostics, and prior run history. |
| `POST` | `/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}/evaluate` | Org Member | `EvaluationJobSummary` | Initiates an evaluation job for a verified submission against the published rubric via the transactional outbox. |

---

### 4. Frontend Integration

1. **Typed Models & API Client:**
   - Added TypeScript interfaces in [api.ts](file:///home/shubh/scorva/apps/web/src/types/api.ts):
     - `EvidenceReferenceDetail`
     - `CriterionScoreDetail`
     - `EvaluationResultDetail`
     - `EvaluationJobSummary`
     - `EvaluationRubricSummary`
     - `EvaluationSnapshotSummary`
     - `PriorEvaluationRunSummary`
     - `SubmissionEvaluationTransparencyResponse`
     - `HackathonEvaluationSummaryResponse`
     - `EvaluationJobListItem`
     - `EvaluationJobResponse`
   - Added typed client methods in [api-client.ts](file:///home/shubh/scorva/apps/web/src/lib/api-client.ts):
     - `getSubmissionEvaluation(organizationId, hackathonId, submissionId)`
     - `getHackathonEvaluationSummary(organizationId, hackathonId)`
     - `getHackathonEvaluations(organizationId, hackathonId, status, page, pageSize)`
     - `triggerSubmissionEvaluation(organizationId, hackathonId, submissionId)`
     - `cancelEvaluationJob(organizationId, hackathonId, jobId)`

2. **Evaluation Summary Ribbon (Submissions Tab):**
   - Mounted in [page.tsx](file:///home/shubh/scorva/apps/web/src/app/organizations/[organizationId]/hackathons/[hackathonId]/page.tsx).
   - Displays real-time metrics:
     - Total Submissions & Evaluated Count with progress percentage.
     - In-Progress (queued/running) badge.
     - Failed evaluations counter.
     - Average AI Score across completed evaluations.
     - Published Rubric status indicator.

3. **Submissions Card Integration:**
   - "AI Assessment" inspection button opening the full transparency modal.
   - Dynamic "Evaluate" / "Re-evaluate" / "Evaluating..." buttons based on current job state.

4. **AI Evaluation Transparency Modal:**
   - **Header & Provenance:** Submission title, repository identity (`{owner}/{repo}`), target branch, 7-character commit SHA chip, rubric version chip, and snapshot SHA chip.
   - **Job Status Ribbon:** Visual badge (`completed`, `running`, `queued`, `failed`, `cancelled`), attempt counter, and execution duration.
   - **Score Banner:** Overall raw score / maximum possible, and prominent normalized (0–100) score.
   - **Insufficient Evidence Warning:** Prominently highlights when the AI engine flagged insufficient repository evidence to evaluate reliably.
   - **Criterion Breakdown:**
     - Criterion title, description, weight, and min/max score bounds.
     - Score awarded displayed with progress bar.
     - Model rationale explaining the score based on submission evidence.
     - Grounded code evidence citations displaying file path, line numbers (`#L12-L34`), citation description, and syntax-highlighted monospace code snippet.
   - **Safe Error Display:** Renders user-friendly error category and safe description when a job fails, accompanied by a "Retry Evaluation" action.
   - **Empty State:** Clear guidance explaining why an evaluation has not yet run (e.g. unverified repository or missing published rubric).
   - **Prior Runs Audit Trail:** Expandable list of historical evaluation runs with run timestamps, attempts, and previous scores.

---

### 5. Automated Test Suite Verification

#### 5.1 M6.4 Dedicated Test Suite
**File:** [test_evaluation_transparency_m6_4.py](file:///home/shubh/scorva/apps/api/tests/test_evaluation_transparency_m6_4.py)
**Results:** `10 passed in 17.70s`

1. `test_get_submission_evaluation_detail_completed_with_evidence`: Verifies completed evaluation transparency payload, including rubric details, snapshot commit SHA, criterion scores, weights, model rationale, grounded evidence citations with line ranges and code snippets.
2. `test_get_submission_evaluation_detail_empty_state_not_evaluated`: Verifies empty state response when no evaluation job exists, correctly returning eligibility status.
3. `test_get_submission_evaluation_detail_running_state`: Verifies running job state display with attempt count, duration, and null result.
4. `test_get_submission_evaluation_detail_failed_state_sanitizes_errors`: Confirms internal stack traces and secrets are stripped and safe error categories are returned.
5. `test_re_evaluation_preserves_history`: Verifies that triggering a re-evaluation preserves previous runs in `prior_runs` while presenting the latest job as current.
6. `test_hackathon_evaluation_summary_and_jobs_listing`: Verifies hackathon-wide metrics aggregation (`total_submissions`, `evaluated_submissions`, `average_score`) and paginated job listing.
7. `test_trigger_submission_evaluation_success`: Verifies dashboard evaluation trigger creates snapshot, job, outbox record, and audit log.
8. `test_trigger_submission_evaluation_blocked_when_no_commit_sha`: Enforces pre-flight check blocking evaluations on submissions without verified commit SHAs.
9. `test_trigger_submission_evaluation_blocked_when_no_published_rubric`: Enforces pre-flight check blocking evaluations when no published rubric exists.
10. `test_evaluation_transparency_cross_tenant_denied`: Proves Org B users are strictly denied access to Org A evaluation summaries, jobs, and details (HTTP 403).

#### 5.2 Full Regression Suite Clean
- **M6.1–M6.3 Regression Suites:** 54/54 passed in 77.67s
  - `test_github_webhooks_m6_3.py`: 15/15 passed
  - `test_repository_linking_m6_2.py`: 18/18 passed
  - `test_hackathon_workflows_m6_1.py`: 7/7 passed
  - `test_hackathons.py`: 14/14 passed
- **Phase 5 Evaluation Infrastructure Suites:** 75/75 passed in 25.48s
  - `test_pipeline_m5_3.py`: 14/14 passed
  - `test_evaluation_outbox_m5_1.py`: 15/15 passed
  - `test_worker_engine_m5_2.py`: 15/15 passed
  - `test_reaper_m5_4.py`: 15/15 passed
  - `test_concurrency_and_observability_m5_5.py`: 16/16 passed
- **Frontend Test Suite:** 7/7 passed (`npm --prefix apps/web test`)
- **TypeScript Static Verification:** 0 errors (`npm --prefix apps/web run typecheck`)
- **Next.js Production Build:** Clean build, 17/17 pages generated (`npm --prefix apps/web run build`)

---

### 6. Milestone Completion Sign-Off

Sub-Milestone 6.4 is complete and verified. The system is ready to proceed to Sub-Milestone 6.5 (Judge Review Workflow: human judge review queue, side-by-side AI advisory view, human score overrides, and decoupled review persistence).

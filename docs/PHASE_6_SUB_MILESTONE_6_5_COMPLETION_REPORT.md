# SCORVA — SUB-MILESTONE 6.5 COMPLETION REPORT
## Judge Review Workflow & Independent Human Decisions

### 1. Executive Summary

Sub-Milestone 6.5 builds the complete judge-facing evaluation workflow for reviewing university hackathon project submissions, scoring them against the published rubric, recording detailed qualitative feedback, and recording independent human evaluation decisions.

In direct alignment with Scorva's core product principle:
> *"AI evaluates the evidence. Judges make the decisions. Scorva makes the process transparent."*

Human judge scores, notes, feedback, and decisions remain strictly decoupled from automated AI evaluation results. The system prevents AI findings from ever masquerading as human decisions, while also preventing human scores from mutating underlying AI runs or evaluation snapshots.

All database schema evolutions, backend services, REST API endpoints, optimistic concurrency controls, draft privacy mechanisms, RBAC/assignment checks, frontend types, API client methods, dedicated Judge Workspace UI (`/judge`), Hackathon Detail Page review modals, and automated test suites have been implemented and verified with zero regressions.

---

### 2. Implemented Capabilities & Invariant Guarantees

#### 2.1 Decoupled Human Review Data Model & Migration
- **Alembic Migration:** `c3d4e5f6a1b2_m6_5_judge_review_workflow.py` evolved the pre-existing `judge_reviews` and `judge_criterion_scores` tables into independent evaluation entities.
- **`judge_reviews` Table Evolution:**
  - Added direct foreign keys: `hackathon_id` (FK `hackathons.id`, CASCADE), `submission_id` (FK `submissions.id`, CASCADE), `rubric_version_id` (FK `rubric_versions.id`, RESTRICT).
  - Loosened coupling: `evaluation_result_id` is now nullable, ensuring reviews can exist and be submitted whether or not an AI evaluation has executed.
  - Added review status: `status VARCHAR(20) NOT NULL DEFAULT 'draft'` with check constraint `status IN ('draft', 'submitted')`.
  - Added aggregate score: `score NUMERIC(5, 2) NULL` storing the canonical human weighted evaluation score.
  - Added timestamp: `submitted_at TIMESTAMPTZ NULL` recording the exact final submission moment.
  - Concurrency control: `version INT NOT NULL DEFAULT 1` enabling optimistic concurrency detection.
  - Unique constraint: `uq_judge_reviews_submission_judge` on `(submission_id, judge_user_id)` preventing duplicate reviews per judge on any given submission.
- **`judge_criterion_scores` Table Evolution:**
  - Added direct `score NUMERIC(5, 2) NULL` column.
  - Retained historical fields `original_awarded_score`, `adjusted_awarded_score`, `judge_notes` as nullable.
  - Unique constraint: `uq_judge_criterion_scores_review_criterion` on `(judge_review_id, criterion_id)`.

#### 2.2 Strict Multi-Tenant Isolation & Judge Assignment Verification
- **Explicit Assignment Guard:**
  - A user cannot view the judge queue, access the judge review workspace, save drafts, or submit scores without an active `HackathonJudge` assignment record (`hackathon_judges`).
  - Being an organization member (`ORGANIZER` or `ORG_ADMIN`) alone does NOT confer judge permissions (`FORBIDDEN_NOT_ASSIGNED_JUDGE`).
  - If a judge assignment is revoked, all future review operations by that user are immediately blocked.
- **Multi-Tenant Scoping:**
  - Every endpoint enforces tenant checks verifying that `organization_id`, `hackathon_id`, and `submission_id` belong to the same organizational tenancy boundary. Cross-tenant queries return 403 or 404.

#### 2.3 Draft Privacy & Optimistic Concurrency Control
- **Draft Privacy Invariant:**
  - An assigned judge's draft review (`status == 'draft'`) is strictly private to that judge.
  - Even hackathon organizers or other assigned judges are forbidden from viewing another judge's draft review (`FORBIDDEN_PRIVATE_REVIEW`).
  - Only upon explicit final submission (`status == 'submitted'`) does the review become visible to organizers in the aggregate progress and audit views.
- **Optimistic Concurrency Control (`version`):**
  - Draft saves and submissions accept an optional `version` parameter.
  - If the client's submitted `version` does not match the database `version`, the request is aborted with `HTTP 409 Conflict` (`CONCURRENT_MODIFICATION_DETECTED`), protecting judges from accidentally overwriting concurrent edits from other tabs or devices.

#### 2.4 Rubric Integrity & Scoring Mathematics
- **Published Rubric Enforcement:**
  - Reviews must evaluate against the published rubric version for the hackathon (`rubric_version.status == 'published'`).
- **Score Bounds Validation:**
  - Each criterion score must satisfy $min\_score \le score \le max\_score$. Submitting an out-of-range score is rejected with `HTTP 400 Bad Request` (`SCORE_OUT_OF_BOUNDS`).
- **Rubric Whitelist Validation:**
  - Any score submitted for a criterion not present in the published rubric version is rejected (`UNKNOWN_CRITERION_ID`).
- **Completeness Enforcement on Submission:**
  - While draft reviews allow partial criterion scoring, final review submission strictly requires all criteria defined in the published rubric version to have a valid score (`CRITERIA_INCOMPLETE`).
- **Weighted Aggregate Calculation:**
  - Canonical score is calculated using exact `Decimal` arithmetic with round-half-up:
    $$Aggregate = \frac{\sum_{i=1}^n (Score_i \times Weight_i)}{\sum_{i=1}^n Weight_i}$$
  - Zero floating-point arithmetic is used; values are stored in `Numeric(5, 2)`.

#### 2.5 Review Immutability & Decoupling from AI
- **Immutability of Submitted Reviews:**
  - Once submitted (`status == 'submitted'`), a review cannot be modified or re-submitted (`REVIEW_ALREADY_SUBMITTED`).
- **Strict Decoupling from AI Results:**
  - Saving or submitting a judge review does not alter `EvaluationJob` (its `status`, `attempt_count`, or lease) or `EvaluationResult` (its `raw_score`, `normalized_score`, or `rationale`).
  - Both human and AI scores remain independently queryable side-by-side.

#### 2.6 Append-Only Auditing
- Review mutations emit structured audit events to `audit_events`:
  - `judge_review_draft_saved`: Emitted when an assigned judge saves a partial or complete draft.
  - `judge_review_submitted`: Emitted when an assigned judge records a final, immutable score decision.

---

### 3. API Endpoints Mounted

| Method | Endpoint | Authorization | Response Schema | Purpose |
|---|---|---|---|---|
| `GET` | `/api/v1/judge/assignments` | Authenticated Judge | `List[JudgeAssignmentItem]` | Lists all hackathons where the authenticated user is an active assigned judge, with submission counters and review completion progress. |
| `GET` | `/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/judge/queue` | Assigned Judge | `List[JudgeQueueItem]` | Submission review queue for the judge, indicating which submissions are unreviewed, in draft, or submitted. |
| `GET` | `/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}/review` | Assigned Judge / Organizer | `JudgeSubmissionReviewResponse` | Side-by-side review interface payload including published rubric criteria, advisory AI findings, and the judge's current draft review. |
| `POST` | `/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}/review` | Assigned Judge | `JudgeReviewDetail` | Saves or updates a draft judge review with optimistic concurrency control. |
| `PUT` | `/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}/review` | Assigned Judge | `JudgeReviewDetail` | Alias for draft save/update. |
| `POST` | `/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}/review/submit` | Assigned Judge | `JudgeReviewDetail` | Validates completeness, validates score bounds, computes weighted score, transitions review to `submitted`, and records audit event. |
| `GET` | `/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/reviews/progress` | Org Staff | `OrganizerReviewProgressResponse` | Organizer review progress overview: metrics summary, judge completion breakdown, and per-submission judge coverage. |
| `GET` | `/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}/reviews` | Assigned Judge / Org Staff | `SubmissionReviewsResponse` | Scoped list of reviews: assigned judges see only their own review; organizers see all submitted reviews. |

---

### 4. Frontend Integration

1. **TypeScript Definitions & API Client:**
   - In [`apps/web/src/types/api.ts`](file:///home/shubh/scorva/apps/web/src/types/api.ts):
     - `JudgeCriterionScoreInput`, `SaveJudgeReviewRequest`, `SubmitJudgeReviewRequest`
     - `JudgeCriterionScoreDetail`, `JudgeReviewDetail`, `JudgeSubmissionReviewResponse`
     - `JudgeQueueItem`, `JudgeAssignmentItem`, `JudgeProgressItem`, `SubmissionCoverageItem`
     - `OrganizerReviewProgressResponse`, `SubmissionReviewsResponse`
   - In [`apps/web/src/lib/api-client.ts`](file:///home/shubh/scorva/apps/web/src/lib/api-client.ts):
     - `getJudgeAssignments()`
     - `getJudgeQueue(orgId, hackathonId)`
     - `getSubmissionReview(orgId, hackathonId, submissionId)`
     - `saveSubmissionReviewDraft(orgId, hackathonId, submissionId, data)`
     - `submitSubmissionReview(orgId, hackathonId, submissionId, data)`
     - `getHackathonReviewProgress(orgId, hackathonId)`
     - `getSubmissionAllReviews(orgId, hackathonId, submissionId)`

2. **Dedicated Judge Workspace (`/judge`):**
   - Implemented in [`apps/web/src/app/judge/page.tsx`](file:///home/shubh/scorva/apps/web/src/app/judge/page.tsx).
   - Displays all active hackathons assigned to the logged-in judge.
   - Shows progress meters (e.g. "3 of 5 submissions reviewed"), submission counters, organization tags, and direct jump-links to hackathon review queues.
   - Handles empty states for judges who have not yet been assigned to any hackathons.

3. **Hackathon Detail Page — Reviews Tab & Review Modal:**
   - Implemented in [`apps/web/src/app/organizations/[organizationId]/hackathons/[hackathonId]/page.tsx`](file:///home/shubh/scorva/apps/web/src/app/organizations/[organizationId]/hackathons/[hackathonId]/page.tsx).
   - **Reviews Tab for Organizers:**
     - High-level metric cards: Total Assigned Judges, Total Submissions, Total Reviews Completed, Submissions with ≥1 Review.
     - Judge Progress table: Judge name, email, submissions reviewed count, progress percentage bar.
     - Submission Coverage table: Team name, title, number of submitted reviews, average human judge score.
   - **Submission Cards:** Added "Judge Review" button opening the review modal.
   - **Interactive Judge Review Modal:**
     - **Advisory AI Assessment (Left Panel):** Displays AI overall score, assessment rationale, criterion-by-criterion breakdown with grounded code snippet citations (file path, line ranges, and quoted code). Prominently tagged with an "AI Advisory Assessment — AI evaluates evidence; Judges make decisions" badge.
     - **Independent Human Scoring (Right Panel):** Form containing rubric criteria cards, weight indicators, score bounds inputs `[min, max]`, criterion-specific judge notes, overall qualitative feedback textarea, final decision selector (`accepted`, `adjusted`, `rejected`), "Save Draft" button with version tracking, and "Submit Final Review" button with confirmation dialog.
     - **Read-Only Submitted State:** If a review is already submitted, the modal displays the immutable scores, aggregate weighted score, feedback, and submission timestamp without editable inputs.

---

### 5. Automated Test Suite & Verification Results

A dedicated automated test suite was created in [`apps/api/tests/test_judge_review_m6_5.py`](file:///home/shubh/scorva/apps/api/tests/test_judge_review_m6_5.py), comprising 14 comprehensive tests covering all 20 required points from Prompt Section 10:

| # | Test Function | Verified Behavior | Status |
|---|---|---|---|
| 1 & 2 | `test_assigned_judge_can_access_and_unassigned_denied` | Assigned judge accesses review interface; unassigned user (participant or unassigned staff) is denied with 403 `FORBIDDEN_NOT_ASSIGNED_JUDGE`. | **PASS** |
| 3 | `test_cross_tenant_access_denied` | Cross-tenant access to judge queue and review endpoint strictly blocked with 403. | **PASS** |
| 4 | `test_judge_can_save_and_retrieve_draft` | Judge saves draft with partial criteria; retrieves it later; updates draft with remaining criteria; version increments. | **PASS** |
| 5 | `test_judge_concurrency_protection_on_draft_update` | Submitting a stale version returns 409 `CONCURRENT_MODIFICATION_DETECTED`. | **PASS** |
| 6 & 7 | `test_final_review_submission_enforces_criteria_and_computes_score` | Submitting incomplete criteria is rejected with 400 `CRITERIA_INCOMPLETE`; full submission calculates correct weighted aggregate score ($\frac{0.4 \times 8.0 + 0.6 \times 9.0}{1.0} = 8.60$). | **PASS** |
| 8 & 9 | `test_submitted_review_immutable_and_duplicate_submit_blocked` | Attempting to update or re-submit a submitted review returns 400 `REVIEW_ALREADY_SUBMITTED`. | **PASS** |
| 10 | `test_score_bounds_and_unknown_criteria_enforced` | Score out of bounds returns 400 `SCORE_OUT_OF_BOUNDS`; unknown criterion ID returns 400 `UNKNOWN_CRITERION_ID`. | **PASS** |
| 11 | `test_multiple_independent_judges_per_submission` | Dave and Charlie independently review the same submission with different scores; neither overwrites the other. | **PASS** |
| 12 | `test_judge_assignments_and_queue_listings` | `GET /api/v1/judge/assignments` and `GET /judge/queue` return correct hackathon and submission statuses (`unreviewed`, `draft`, `submitted`). | **PASS** |
| 13 | `test_removing_judge_blocks_future_review_operations` | When judge assignment is deleted from `hackathon_judges`, future review access is blocked with 403. | **PASS** |
| 14 & 15 | `test_ai_scores_and_human_scores_strictly_decoupled` | Human review submission does not alter `EvaluationResult` or `EvaluationJob`; human and AI scores remain independently queryable. | **PASS** |
| 16 | `test_judge_review_without_ai_evaluation` | Judge can review and submit scores for a submission that has never had an AI evaluation job run. | **PASS** |
| 17 | `test_audit_events_recorded_for_judge_reviews` | `judge_review_draft_saved` and `judge_review_submitted` events are recorded in `audit_events`. | **PASS** |
| 18 | `test_organizer_review_progress_dashboard` | `GET /reviews/progress` returns accurate counts for assigned judges, completed reviews, and per-submission coverage. | **PASS** |
| 19 & 20 | `test_private_drafts_visible_only_to_authorized_users` | Dave's unsubmitted draft is private to Dave (403 for other judges/organizers); once submitted, it is visible to organizers and Dave, but hidden from Charlie. | **PASS** |

#### Summary of Test Runs:
- **M6.5 Dedicated Test Suite:** `14 passed in 72.51s` (`apps/api/tests/test_judge_review_m6_5.py`)
- **M6.1–M6.4 Regression Test Suite:** `64 passed in 262.19s` (`apps/api/tests/test_evaluation_transparency_m6_4.py`, `test_github_webhooks_m6_3.py`, `test_repository_linking_m6_2.py`, `test_hackathon_workflows_m6_1.py`, `test_hackathons.py`)
- **Phase 5 Infrastructure Test Suite:** `75 passed in 53.82s` (`apps/api/tests/test_pipeline_m5_3.py`, `test_evaluation_outbox_m5_1.py`, `test_worker_engine_m5_2.py`, `test_reaper_m5_4.py`, `test_concurrency_and_observability_m5_5.py`)
- **Frontend Unit Tests & Typecheck:** `7 passed, 0 failed` and `tsc --noEmit` clean with 0 errors.
- **Frontend Production Build:** `npm --prefix apps/web run build` completed cleanly, prerendering 18 static/dynamic routes including `/judge`.

---

### 6. Deliverable Inventory

#### Backend:
- Database Migration: [`apps/api/alembic/versions/c3d4e5f6a1b2_m6_5_judge_review_workflow.py`](file:///home/shubh/scorva/apps/api/alembic/versions/c3d4e5f6a1b2_m6_5_judge_review_workflow.py)
- Models: [`apps/api/modules/evaluations/models.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/models.py) (`JudgeReview`, `JudgeCriterionScore`, `Submission.judge_reviews`)
- Schemas: [`apps/api/modules/evaluations/schemas.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/schemas.py)
- Service Layer: [`apps/api/modules/evaluations/judge_service.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/judge_service.py)
- Global Judge Router: [`apps/api/modules/evaluations/judge_router.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/judge_router.py) (mounted in [`apps/api/main.py`](file:///home/shubh/scorva/apps/api/main.py) at `/api/v1/judge`)
- Hackathon Scoped Subresources Router: [`apps/api/modules/hackathons/subresources_router.py`](file:///home/shubh/scorva/apps/api/modules/hackathons/subresources_router.py)
- Test Suite: [`apps/api/tests/test_judge_review_m6_5.py`](file:///home/shubh/scorva/apps/api/tests/test_judge_review_m6_5.py)

#### Frontend:
- TypeScript Models: [`apps/web/src/types/api.ts`](file:///home/shubh/scorva/apps/web/src/types/api.ts)
- API Client: [`apps/web/src/lib/api-client.ts`](file:///home/shubh/scorva/apps/web/src/lib/api-client.ts)
- Dedicated Judge Portal: [`apps/web/src/app/judge/page.tsx`](file:///home/shubh/scorva/apps/web/src/app/judge/page.tsx)
- Hackathon Detail Page: [`apps/web/src/app/organizations/[organizationId]/hackathons/[hackathonId]/page.tsx`](file:///home/shubh/scorva/apps/web/src/app/organizations/[organizationId]/hackathons/[hackathonId]/page.tsx) (Reviews tab, judge review modal, AI advisory view, progress dashboard)

#### Documentation:
- Updated Master Plan: [`docs/PHASE_6_PLAN.md`](file:///home/shubh/scorva/docs/PHASE_6_PLAN.md)
- Completion Report: [`docs/PHASE_6_SUB_MILESTONE_6_5_COMPLETION_REPORT.md`](file:///home/shubh/scorva/docs/PHASE_6_SUB_MILESTONE_6_5_COMPLETION_REPORT.md)

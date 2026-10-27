# SCORVA — PHASE 6 IMPLEMENTATION PLAN
## Judge-Facing Hackathon Evaluation Platform

### 1. Mission and Core Product Principle

**Mission:** Build an end-to-end, multi-tenant university hackathon evaluation platform connecting organizers, team submissions, repository evidence, automated AI assessments, and human judge decisions.

**Core Product Principle:**
> *"AI evaluates the evidence. Judges make the decisions. Scorva makes the process transparent."*

Human judge scores, adjustments, and feedback remain strictly decoupled from AI evaluations. AI provides evidence-backed assessments, but human judges retain ultimate authority.

---

### 2. Architectural Invariants and Safety Guarantees

1. **Strict Multi-Tenant Isolation:** Every query, route, mutation, and worker task must enforce `organization_id` and `hackathon_id` scoping at the database level. Never trust client-supplied IDs without server-side verification.
2. **Server-Side RBAC:** Enforce explicit roles (`org_owner`, `org_admin`, `organizer`, `judge`, `participant`). Client UI visibility never replaces backend authorization.
3. **Immutability of Evaluation Snapshots & Rubrics:**
   - Rubric criteria cannot be modified once a rubric version is published (`status = 'published'`).
   - Repository code and evidence are captured into immutable snapshots before evaluation.
4. **Fenced Worker Persistence:** Evaluation jobs run asynchronously through the transactional outbox and Celery worker engine with token-fenced row commits.
5. **Decimal-Based Scoring:** All scores use `Numeric(5, 2)` or `Numeric(6, 2)` precision with strict min/max and weight validation; floats are forbidden in scoring logic.
6. **Append-Only Audit Logging:** All consequential actions (status changes, judge overrides, re-evaluations, cancellations) emit structured `audit_events`.
7. **SSRF & Credential Protection:** All repository cloning and webhook handling adhere to Profile B network isolation, URL validation, and secret masking.

---

### 3. Implementation Sequence: Sub-Milestones M6.1 – M6.7

```
M6.1: Product Foundation & API Integration (Completed)
  │
  ▼
M6.2: Team Registration & Repository Linking (Completed)
  │
  ▼
M6.3: GitHub Events & Project Activity (Completed)
  │
  ▼
M6.4: AI Evaluation Transparency (Completed)
  │
  ▼
M6.5: Judge Review Workflow (Completed)
  │
  ▼
M6.6: Organizer Evaluation Dashboard & Rankings (Next Milestone)
  │
  ▼
M6.7: End-to-End Hardening & Multi-Tenant Verification
```

---

### 4. Milestone Breakdown

#### Milestone 6.1: Product Foundation & API Integration (Completed)
- **Inventory & Route Setup:**
  - Route inventory of hackathons, teams, submissions, judges, rubrics, and evaluations.
  - Complete backend endpoints for team listing, team creation, team joining (`join_code`).
  - Complete backend endpoints for submissions listing and submission detail.
  - Complete backend endpoints for hackathon judges listing, assignment, and removal.
  - Complete backend endpoints for rubric retrieval, creation, criteria configuration, and publishing.
  - Complete hackathon overview / metrics summary endpoint (`total_teams`, `total_submissions`, `evaluations_status`).
- **Frontend Wiring:**
  - Extended `apps/web/src/lib/api-client.ts` with typed methods for teams, submissions, judges, rubrics, and hackathon overview.
  - Enhanced Hackathon Detail view (`apps/web/src/app/organizations/[organizationId]/hackathons/[hackathonId]/page.tsx`) with real tabs/views: Overview, Teams, Submissions, Judges, and Rubric.
- **Verification:**
  - Automated integration test suite (`apps/api/tests/test_hackathon_workflows_m6_1.py`): 7/7 passed.
  - Full hackathon test suite (`apps/api/tests/test_hackathons.py`): 14/14 passed.

#### Milestone 6.2: Team Registration & Repository Linking (Completed)
- **Schema & Database Migrations:**
  - Alembic migration `a1b2c3d4e5f6_m6_2_submission_repository_linking.py` added 8 columns to `submissions`:
    `repository_owner`, `repository_name`, `default_branch`, `verified_commit_sha`, `connection_status` (default `'unverified'`), `verified_at`, `verification_diagnostic`, `verification_error`.
  - Mapped in `apps/api/modules/evaluations/models.py`.
- **Profile A SSRF Defense & URL Hardening:**
  - Hardened `parse_github_url` rejecting credentials (`CREDENTIALS_IN_URL_FORBIDDEN`), nonstandard ports (`UNSUPPORTED_GIT_PORT`), URL query/fragment components (`INVALID_URL_COMPONENTS`), and non-GitHub providers (`UNSUPPORTED_GIT_PROVIDER`).
  - Strict host validation and Profile A IP pinning ensuring all resolved addresses are public unicast IPs.
- **Repository Verification & Management Workflows:**
  - Added `verify_repository_access(owner, repo, target_branch)` in `GitHubIngestionClient` verifying repo accessibility, default branch, target branch, visibility, and resolving head commit SHA.
  - Safe verification service `validate_github_repository` distinguishing verified ownership via installed organization integration app tokens from unauthenticated public access.
  - Implemented 5 dedicated API endpoints mounted on `subresources_router.py`:
    - `POST /{hackathon_id}/repositories/validate`: Safe pre-submission connection test.
    - `POST /{hackathon_id}/submissions/{submission_id}/link-repository`: Links or replaces repository with failsafe rollback.
    - `PATCH /{hackathon_id}/submissions/{submission_id}/branch`: Updates target branch after confirming branch existence on GitHub.
    - `POST /{hackathon_id}/submissions/{submission_id}/verify`: Refreshes repository status and tracks latest commit SHA.
    - `POST /{hackathon_id}/submissions/{submission_id}/unlink-repository`: Unlinks repository; strictly blocked if active/completed evaluations exist.
- **Audit & Invariants:**
  - Emits append-only audit records: `repository_linked`, `submission_branch_updated`, `submission_verification_refreshed`, `repository_unlinked`.
  - Duplicate repository prevention per hackathon (`REPOSITORY_ALREADY_SUBMITTED`).
  - Failsafe invariant: Verification errors leave existing valid links unchanged.
  - Submission deadline enforcement blocking repo modifications after hackathon closes.
- **Frontend Integration:**
  - Typed methods in `apps/web/src/lib/api-client.ts` and models in `apps/web/src/types/api.ts`.
  - UI in `apps/web/src/app/organizations/[organizationId]/hackathons/[hackathonId]/page.tsx` with connection status pills, commit SHA chips, real-time "Test Connection" validation, and dedicated modals for updating branch and relinking repositories.
- **Automated Verification:**
  - 18/18 tests passing in `apps/api/tests/test_repository_linking_m6_2.py`.
  - Full suite clean: 21/21 hackathon/M6.1 tests, 75/75 Phase 5 tests, 7/7 web tests, 0 TypeScript errors.

#### Milestone 6.3: GitHub Events & Project Activity (Completed)
- **Database Schema & Migrations:**
  - Alembic migration `b2c3d4e5f6a1_m6_3_github_events_ingestion.py` created the `github_events` table with unique delivery constraints, foreign keys to `organizations`, `hackathons`, and `submissions`, and composite indexes for timeline retrieval.
  - Mapped in `apps/api/modules/evaluations/models.py` (`GitHubEvent`).
- **Cryptographic Security & Verification:**
  - HMAC-SHA256 signature verification (`X-Hub-Signature-256`) via constant-time comparison in `verify_github_webhook_signature`.
  - Configured `GITHUB_WEBHOOK_SECRET` and body size limit `GITHUB_WEBHOOK_MAX_BYTES` (5MB).
  - Malformed payload, missing header, and invalid signature rejections before processing.
- **Defensive Event Normalization & Ingestion:**
  - Normalized event ingestion for `push`, `pull_request`, `ping`, `create`, `delete`, and `repository`.
  - Idempotent deduplication via unique `X-GitHub-Delivery` constraint.
  - Correlated to registered submissions using canonical repository identity (`{owner}/{repo}`).
  - Pushes on target branch before submission deadline update `submission.verified_commit_sha`.
  - Pushes after deadline are preserved for timeline evidence with diagnostic `DEADLINE_PASSED` without mutating verified submission commit.
  - Invariant: incoming webhooks never mutate published evaluation snapshots, jobs, scores, or judge reviews.
- **Timeline API & Frontend:**
  - Added `GET /{hackathon_id}/submissions/{submission_id}/activity` and `GET /{hackathon_id}/activity` endpoints with tenant isolation.
  - Frontend API client methods `getSubmissionActivity` and `getHackathonActivity`.
  - "Activity" modal in hackathon submissions dashboard rendering real-time push and PR timeline events.
- **Automated Verification:**
  - 15/15 tests passing in `apps/api/tests/test_github_webhooks_m6_3.py`.
  - Full suite clean: 18/18 M6.2 tests, 21/21 M6.1 & Hackathons tests, 75/75 Phase 5 tests, 7/7 web tests, 0 TypeScript errors.

#### Milestone 6.4: AI Evaluation Transparency (Completed)
- **Evaluation Transparency & Detail Endpoints:**
  - `GET /organizations/{org_id}/hackathons/{hackathon_id}/evaluations/summary`: hackathon evaluation metrics aggregating total submissions, evaluated count, queued/running/completed/failed/cancelled status breakdown, average AI score, and published rubric availability.
  - `GET /organizations/{org_id}/hackathons/{hackathon_id}/evaluations`: hackathon-scoped evaluation jobs listing with status filtering and pagination.
  - `GET /organizations/{org_id}/hackathons/{hackathon_id}/submissions/{submission_id}/evaluation`: full evaluation transparency payload containing latest evaluation job status, duration, attempts, rubric version metadata, snapshot commit SHA, raw & normalized scores, criterion-by-criterion assessments (weights, bounds, AI rationale), grounded evidence citations (file paths, line ranges, quoted code snippets), sanitized error categories, and prior runs audit trail.
  - `POST /organizations/{org_id}/hackathons/{hackathon_id}/submissions/{submission_id}/evaluate`: dashboard evaluation trigger ensuring hackathon status, published rubric, verified commit SHA, immutable snapshot resolution, and transactional outbox dispatch.
- **Safety, Isolation & Grounding Invariants:**
  - Multi-tenant and hackathon scoping strictly enforced across all evaluation endpoints; cross-tenant access returns 403/404.
  - Strict preservation of `Numeric(5, 2)` / `Numeric(6, 2)` score precision with zero floating-point arithmetic.
  - Model rationale and evidence citations are grounded strictly in persisted evaluation results without fabrication.
  - Error sanitization strips credentials, local system paths, prompt templates, and stack traces into safe user-facing categories (`SAFE_ERROR_DESCRIPTIONS`).
  - Evaluations never overwrite human judge decisions or modify immutable snapshots.
- **Frontend Transparency UI:**
  - Real-time Evaluation Summary status bar in hackathon submissions dashboard.
  - Submissions card "AI Assessment" modal with status ribbon, score banner (raw and normalized), rubric criteria cards, grounded code snippets with line numbers, safe failure diagnostics, and prior evaluation run history.
  - "Evaluate" / "Re-evaluate" action buttons with real-time feedback.
- **Automated Verification:**
  - 10/10 passed in `apps/api/tests/test_evaluation_transparency_m6_4.py`.
  - Full regression clean: 54/54 M6.1–M6.3 tests, 75/75 Phase 5 tests, 7/7 web tests, 0 TypeScript errors, clean Next.js production build.

#### Milestone 6.5: Judge Review Workflow & Independent Human Decisions (Completed)
- **Database Schema Evolution & Alembic Migration:**
  - Alembic migration `c3d4e5f6a1b2_m6_5_judge_review_workflow.py` evolved `judge_reviews` and `judge_criterion_scores` into independent human evaluation entities.
  - Added columns to `judge_reviews`: `hackathon_id`, `submission_id`, `rubric_version_id`, `status` (`'draft'`, `'submitted'`), `score`, `submitted_at`, and optimistic concurrency `version` (int, default 1).
  - Loosened historical references: `evaluation_result_id` is nullable, preventing tight coupling to AI evaluation runs.
  - Added columns to `judge_criterion_scores`: independent `score` (`Numeric(5, 2)`), while preserving nullable override fields.
  - Enforced unique constraints: `uq_judge_reviews_submission_judge` on `(submission_id, judge_user_id)` and `uq_judge_criterion_scores_review_criterion` on `(judge_review_id, criterion_id)`.
- **Backend Service Layer & API Endpoints:**
  - `GET /api/v1/judge/assignments`: Lists assigned hackathons with submission counts and review progress.
  - `GET /organizations/{org_id}/hackathons/{hackathon_id}/judge/queue`: Submission queue for assigned judges with individual review statuses.
  - `GET /organizations/{org_id}/hackathons/{hackathon_id}/submissions/{submission_id}/review`: Side-by-side review workspace with published rubric, advisory AI assessments, and judge draft state.
  - `POST / PUT /organizations/{org_id}/hackathons/{hackathon_id}/submissions/{submission_id}/review`: Draft review saving with optimistic concurrency control (`version`).
  - `POST /organizations/{org_id}/hackathons/{hackathon_id}/submissions/{submission_id}/review/submit`: Final immutable review submission enforcing all criteria scored within range, computing weighted aggregate score, and transitioning status to `'submitted'`.
  - `GET /organizations/{org_id}/hackathons/{hackathon_id}/reviews/progress`: Organizer review progress dashboard aggregating assigned judges, completed reviews, and per-submission coverage.
  - `GET /organizations/{org_id}/hackathons/{hackathon_id}/submissions/{submission_id}/reviews`: Scoped reviews listing (judges see only their own; organizers see all submitted).
- **Core Security, Isolation & Invariant Guarantees:**
  - Strict multi-tenant and hackathon scoping on every review operation.
  - Explicit judge assignment check: Unassigned users (even organizers/admins) are denied judge review operations (`FORBIDDEN_NOT_ASSIGNED_JUDGE`).
  - Draft privacy: Unsubmitted drafts are strictly private to the creating judge (`FORBIDDEN_PRIVATE_REVIEW`).
  - Score integrity: Scores strictly constrained to rubric criterion `[min_score, max_score]`. Unknown criteria rejected (`UNKNOWN_CRITERION_ID`).
  - AI decoupling: Human reviews never mutate `EvaluationJob` or `EvaluationResult`.
  - Immutability: Submitted reviews cannot be modified or re-submitted (`REVIEW_ALREADY_SUBMITTED`).
  - Append-only auditing: Emits `judge_review_draft_saved` and `judge_review_submitted` events.
- **Frontend Integration:**
  - Created dedicated Judge Workspace at `/judge` (`apps/web/src/app/judge/page.tsx`) with assigned hackathon cards, progress meters, and submission links.
  - Extended Hackathon Detail page with "Reviews" tab and "Judge Review" button on submission cards.
  - Implemented interactive Judge Review Modal featuring side-by-side advisory AI assessments (scores, quotes, line references) and independent human scoring form (criterion notes, feedback, draft saving, and confirmation modal for final submission).
  - Added Organizer Review Progress dashboard summarizing judge completion rates and submission coverage.
- **Automated Verification:**
  - Dedicated test suite `apps/api/tests/test_judge_review_m6_5.py` passed with 14/14 tests covering all 20 required points.
  - Full regression test suites clean: 64/64 M6.1–M6.4 tests, 75/75 Phase 5 tests, 7/7 frontend unit tests, 0 TypeScript errors, clean Next.js build.

#### Milestone 6.6: Organizer Evaluation Dashboard & Rankings
- Real-time submission leaderboard and evaluation progress dashboard.
- Explicit ranking policies and tie-breaking algorithms based on human judge scores or normalized scores.
- Export audit trail and final decision reports.

#### Milestone 6.7: End-to-End Hardening
- Comprehensive cross-tenant regression testing.
- UI responsive design, empty states, and accessibility compliance.
- Final security verification and operational readiness sign-off.

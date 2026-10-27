# SCORVA — SUB-MILESTONE 6.3 COMPLETION REPORT
## GitHub Webhooks, Event Ingestion & Repository Activity Timeline

### 1. Executive Summary

Sub-Milestone 6.3 delivers secure, idempotent GitHub webhook ingestion and traceable project activity timelines for Scorva. Ingested events provide trustworthy project evidence, capture push and pull request activities, update target branch commit SHAs while respecting hackathon deadlines, and present real-time timeline feeds in the hackathon dashboard.

All database schema migrations, cryptographic signature checks, defensive payload normalizations, API endpoints, frontend integration, and automated test suites have been verified with zero regressions.

---

### 2. Implemented Capabilities & Invariant Guarantees

#### 2.1 Cryptographic Webhook Security
- **HMAC-SHA256 Constant-Time Verification:**
  - `verify_github_webhook_signature` validates `X-Hub-Signature-256` using constant-time comparison (`hmac.compare_digest`), preventing timing side-channel attacks.
  - Missing signatures or non-prefixed headers (`sha256=`) are rejected with HTTP 401 (`WEBHOOK_SIGNATURE_MISSING`, `WEBHOOK_SIGNATURE_INVALID_FORMAT`).
  - Signature mismatches are rejected with HTTP 403 (`WEBHOOK_SIGNATURE_MISMATCH`).
  - Secrets and full payload byte contents are never logged.
- **Configured Webhook Secrets:**
  - Distinct `GITHUB_WEBHOOK_SECRET` setting decoupled from user or API access tokens.
- **Body Size Limit:**
  - Enforced via `GITHUB_WEBHOOK_MAX_BYTES` (5 MB limit), returning HTTP 413 (`PAYLOAD_TOO_LARGE`) if exceeded.

#### 2.2 Defensive Normalization & Idempotent Ingestion
- **Durable Deduplication:**
  - Webhooks enforce a unique constraint on `delivery_id` (`X-GitHub-Delivery`).
  - Repeated deliveries return HTTP 200 with status `"duplicate"` without duplicate records.
- **Normalized Event Evidence Store:**
  - Normalizes `push`, `pull_request`, `ping`, `create`, `delete`, and `repository` events into the `github_events` table.
  - Preserves essential evidence metadata (`ref`, `commit_sha`, `pr_number`, `pr_title`, `pr_url`, `pr_merged`, `sender_login`, `summary`) while discarding sensitive or unvetted payload components.
- **Canonical Repository Matching:**
  - Correlates incoming webhooks by canonical repository identity (`{owner}/{repo}`) against registered active hackathon submissions.
  - Automatically binds events to the corresponding `organization_id`, `hackathon_id`, and `submission_id`.

#### 2.3 Deadline Guards & Evaluation Immutability
- **Target Branch Commit Resolution:**
  - Push events matching a submission's `target_branch` update `submission.verified_commit_sha`, `submission.verified_at`, and `submission.connection_status = 'verified'`.
  - Pushes on unrelated branches do not alter the submission's target commit SHA.
- **Deadline Protection:**
  - Push events received after `hackathon.submission_deadline` do NOT mutate the submission's verified commit SHA. The event is recorded in the activity timeline with diagnostic category `DEADLINE_PASSED`.
- **Evaluation Immutability Invariant:**
  - Incoming webhooks never mutate existing `EvaluationJob` statuses, `SubmissionSnapshot` commit SHAs, evaluation scores, or `JudgeReview` records.

---

### 3. Database Migration & Schema

#### 3.1 Migration Revision: `b2c3d4e5f6a1`
- **File:** [b2c3d4e5f6a1_m6_3_github_events_ingestion.py](file:///home/shubh/scorva/apps/api/alembic/versions/b2c3d4e5f6a1_m6_3_github_events_ingestion.py)
- **Down Revision:** `a1b2c3d4e5f6` (M6.2 Submission Repository Linking)
- **Table Created:** `github_events`
  - `id`: `UUID`, Primary Key
  - `delivery_id`: `VARCHAR(100)`, Unique, Index
  - `event_type`: `VARCHAR(50)`, Index
  - `action`: `VARCHAR(50)`, Nullable
  - `organization_id`: `UUID`, FK (`organizations.id`, ondelete `SET NULL`)
  - `hackathon_id`: `UUID`, FK (`hackathons.id`, ondelete `SET NULL`)
  - `submission_id`: `UUID`, FK (`submissions.id`, ondelete `SET NULL`)
  - `repository_owner`: `VARCHAR(150)`
  - `repository_name`: `VARCHAR(150)`
  - `canonical_repo_id`: `VARCHAR(300)`, Index
  - `ref`: `VARCHAR(255)`, Nullable
  - `commit_sha`: `VARCHAR(40)`, Nullable
  - `sender_login`: `VARCHAR(100)`, Nullable
  - `summary`: `VARCHAR(500)`, Nullable
  - `details`: `JSONB`, Server Default `{}`
  - `status`: `VARCHAR(20)`, Default `'received'` (`received`, `processed`, `ignored`, `failed`)
  - `diagnostic_code`: `VARCHAR(100)`, Nullable
  - `error_message`: `TEXT`, Nullable
  - `event_timestamp`: `DateTime(timezone=True)`, Index
  - `created_at`: `DateTime(timezone=True)`, Server Default `now()`
  - `processed_at`: `DateTime(timezone=True)`, Nullable
- **Indexes:**
  - `ix_github_events_delivery_id` (Unique)
  - `ix_github_events_canonical_repo_id`
  - `ix_github_events_event_timestamp`
  - `ix_github_events_org_hack_sub` on `(organization_id, hackathon_id, submission_id)`
  - `ix_github_events_repo_timestamp` on `(canonical_repo_id, event_timestamp)`

---

### 4. API Endpoints

| Method | Endpoint | Auth | Response | Purpose |
|---|---|---|---|---|
| `POST` | `/api/v1/integrations/github/webhook` | `X-Hub-Signature-256` | `WebhookIngestResponse` | Receives, verifies, and normalizes incoming GitHub webhook deliveries. |
| `POST` | `/api/v1/webhooks/github` | `X-Hub-Signature-256` | `WebhookIngestResponse` | Alias receiver endpoint. |
| `GET` | `/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}/activity` | Org Member | `List[RepositoryActivityItem]` | Retrieves chronological repository activity timeline for a submission. |
| `GET` | `/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/activity` | Org Member | `List[RepositoryActivityItem]` | Retrieves hackathon-wide repository activity timeline. |

---

### 5. Append-Only Audit Logging

Ingested webhook events emit audit events recorded in `audit_events`:
- `github_webhook_ingested`: Emitted when an event is durably ingested and matched to an organization.
- `submission_commit_received`: Emitted when a target branch push updates the submission's verified commit SHA.

---

### 6. Frontend Integration

1. **Typed Models & API Client:**
   - Added `WebhookIngestResponse` and `RepositoryActivityItem` to [api.ts](file:///home/shubh/scorva/apps/web/src/types/api.ts).
   - Added `getSubmissionActivity` and `getHackathonActivity` methods to [api-client.ts](file:///home/shubh/scorva/apps/web/src/lib/api-client.ts).
2. **Activity Timeline Modal:**
   - In [page.tsx](file:///home/shubh/scorva/apps/web/src/app/organizations/[organizationId]/hackathons/[hackathonId]/page.tsx), added an "Activity" button to each submission card.
   - Opens a dedicated Activity Timeline modal rendering:
     - Event badges for `push`, `pull_request`, and branch events.
     - Head commit messages and PR titles.
     - Author handle (`@sender`), target branch, and 7-character commit SHA chip.
     - Exact timestamp and event processing status (`processed`, `ignored`, `failed`).

---

### 7. Automated Test Suite Verification

#### 7.1 M6.3 Dedicated Test Suite
**File:** [test_github_webhooks_m6_3.py](file:///home/shubh/scorva/apps/api/tests/test_github_webhooks_m6_3.py)
**Results:** `15 passed in 19.91s`

1. `test_webhook_missing_signature_rejected`: Rejects missing `X-Hub-Signature-256` (401).
2. `test_webhook_invalid_signature_format_rejected`: Rejects signatures without `sha256=` (401).
3. `test_webhook_signature_mismatch_rejected`: Rejects tampered payloads / incorrect secret (403).
4. `test_webhook_missing_delivery_header_rejected`: Rejects payloads without `X-GitHub-Delivery` (400).
5. `test_webhook_malformed_json_rejected`: Rejects malformed JSON bodies (400).
6. `test_webhook_payload_too_large_rejected`: Rejects payloads exceeding 5MB limit (413).
7. `test_webhook_ping_event_accepted`: Correctly processes GitHub ping events.
8. `test_webhook_duplicate_delivery_idempotency`: Verifies repeated deliveries return `duplicate` without second insertion.
9. `test_webhook_push_to_target_branch_updates_commit_sha`: Updates `verified_commit_sha` on target branch pushes.
10. `test_webhook_push_to_other_branch_does_not_update_target_commit`: Protects target branch commit from non-target pushes.
11. `test_webhook_pull_request_event_normalized`: Correctly normalizes pull request actions, PR numbers, and URLs.
12. `test_webhook_push_after_deadline_does_not_mutate_commit_sha`: Preserves deadline cutoff with `DEADLINE_PASSED` diagnostic.
13. `test_webhook_does_not_mutate_evaluation_results`: Proves published snapshots and jobs remain immutable on new pushes.
14. `test_get_submission_activity_timeline`: Verifies timeline API returns chronological events for the submission.
15. `test_activity_timeline_cross_tenant_denied`: Proves Org B users cannot view Org A activity streams (403).

#### 7.2 Full Regression Suite Clean
- **M6.2 Test Suite:** 18/18 passed in 24.65s ([`test_repository_linking_m6_2.py`](file:///home/shubh/scorva/apps/api/tests/test_repository_linking_m6_2.py)).
- **M6.1 & Hackathons Suite:** 21/21 passed in 41.79s ([`test_hackathon_workflows_m6_1.py`](file:///home/shubh/scorva/apps/api/tests/test_hackathon_workflows_m6_1.py), [`test_hackathons.py`](file:///home/shubh/scorva/apps/api/tests/test_hackathons.py)).
- **Phase 5 Suite:** 75/75 passed in 25.95s.
- **Frontend Test Suite:** 7/7 passed (`npm --prefix apps/web test`).
- **TypeScript Static Check:** 0 errors (`npm --prefix apps/web run typecheck`).

---

### 8. Milestone Completion Sign-Off

Sub-Milestone 6.3 is complete and ready for Sub-Milestone 6.4 (AI Evaluation Transparency).

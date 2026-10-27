# SCORVA — SUB-MILESTONE 6.2 COMPLETION REPORT
## Team Registration & GitHub Repository Linking

### 1. Executive Summary

Sub-Milestone 6.2 delivers the secure, resilient workflow for linking GitHub repositories to hackathon submissions. This enables participating teams to bind their remote GitHub repositories to Scorva submissions, verifies repository accessibility and requested branches, resolves HEAD commit SHAs, protects the internal network via Profile A SSRF defense, and renders rich connection diagnostics in the organizer and team frontend.

All implementation code, database migrations, security controls, frontend integration, and automated tests are fully implemented and verified.

---

### 2. Implemented Capabilities & Invariant Guarantees

#### 2.1 Profile A SSRF Defense & URL Hardening
- **Strict Grammar & Component Filtering:**
  - `parse_github_url` in [github_client.py](file:///home/shubh/scorva/apps/api/modules/evaluations/github_client.py) explicitly rejects URLs containing credentials or user-info with error code `CREDENTIALS_IN_URL_FORBIDDEN`.
  - Rejects non-standard ports (strictly allowing only 80, 443, or none) with error code `UNSUPPORTED_GIT_PORT`.
  - Rejects query strings and URL fragments with error code `INVALID_URL_COMPONENTS`.
  - Strictly restricts git provider domains to `github.com` with error code `UNSUPPORTED_GIT_PROVIDER`.
- **DNS Pinning & Egress Isolation:**
  - Enforces Profile A HTTP transport using `PinnedAsyncHTTPTransport` with pre-resolved public unicast IP addresses.
  - Resolves hostnames against public DNS and validates with `resolve_and_validate_hostname`, preventing DNS rebinding and loopback, link-local (169.254.169.254), or RFC 1918 private subnet egress.
  - Intercepts redirects and re-validates redirect destinations before issuing outbound requests.

#### 2.2 Ownership Verification vs. Public Accessibility
- **Distinction Between Ownership and Accessibility:**
  - If a team links a public repository without organization credentials, Scorva accesses it unauthenticated and flags `ownership_verified=False` with the diagnostic note: *"Public repository access verified. Verified organization ownership requires configuring a GitHub integration token."*
  - If an organization integration exists with an active GitHub App installation token, Scorva accesses the repository with authenticated credentials and flags `ownership_verified=True`.
- **Canonical Repository Identity:**
  - Tracks `canonical_repo_id` (format: `"{owner}/{repo}"`) alongside `repository_owner` and `repository_name`.

#### 2.3 Failsafe Update Invariant
- **Non-Destructive Failures:**
  - If a developer attempts to update the target branch or link a new repository URL and verification fails (e.g. branch does not exist on GitHub, repository is private and unauthorized, or GitHub rate limits the client), the backend rejects the request with HTTP 400 and **guarantees that existing valid submission data, repository URL, target branch, and verified commit SHA remain completely unmodified**.

#### 2.4 Lifecycle & Hackathon Deadline Enforcement
- **Submission Deadline Guard:**
  - Linking repositories or changing branches is strictly rejected if `now_utc > hackathon.submission_deadline` (`SUBMISSION_DEADLINE_PASSED`).
- **Completed/Archived Guard:**
  - Rejects repository mutations if the hackathon is `completed` or `archived`.
- **Team Membership RBAC:**
  - Only team members of the registered team or organization administrators/owners (`org_admin`, `org_owner`) can link, update branch, or unlink repositories (`NOT_A_TEAM_MEMBER`).
- **Duplicate Repository Prevention:**
  - Enforces that no two teams in the same hackathon can register or link the same active repository URL (`REPOSITORY_ALREADY_SUBMITTED`).
- **Unlink Protection for Evaluated Submissions:**
  - Unlinking a repository from a submission is blocked with HTTP 400 (`CANNOT_UNLINK_EVALUATED_SUBMISSION`) if active (`queued`, `running`) or `completed` evaluation jobs exist for that submission.

---

### 3. Database Migration & Schema

#### 3.1 Migration Revision: `a1b2c3d4e5f6`
- **File:** [a1b2c3d4e5f6_m6_2_submission_repository_linking.py](file:///home/shubh/scorva/apps/api/alembic/versions/a1b2c3d4e5f6_m6_2_submission_repository_linking.py)
- **Down Revision:** `9e37b1c1921d` (M5.1 Evaluation Outbox)
- **Added Columns to `submissions`:**
  - `repository_owner`: `VARCHAR(150)`, nullable
  - `repository_name`: `VARCHAR(150)`, nullable
  - `default_branch`: `VARCHAR(100)`, nullable
  - `verified_commit_sha`: `VARCHAR(40)`, nullable
  - `connection_status`: `VARCHAR(20)`, nullable, default `'unverified'`
  - `verified_at`: `DateTime(timezone=True)`, nullable
  - `verification_diagnostic`: `VARCHAR(100)`, nullable
  - `verification_error`: `TEXT`, nullable
- **Indexes Created:**
  - `ix_submissions_repo_owner_name` on `(repository_owner, repository_name)`
  - `ix_submissions_connection_status` on `(connection_status)`

---

### 4. API Endpoints

Mounted on [subresources_router.py](file:///home/shubh/scorva/apps/api/modules/hackathons/subresources_router.py) with prefix `/api/v1/organizations/{org_id}/hackathons/{hackathon_id}`:

| Method | Endpoint | Request Body | Response Model | Description |
|---|---|---|---|---|
| `POST` | `/repositories/validate` | `ValidateRepositoryRequest` | `RepositoryValidationResult` | Live connection test verifying URL syntax, host, accessibility, branch existence, and commit SHA without modifying submission state. |
| `POST` | `/submissions/{sub_id}/link-repository` | `LinkRepositoryRequest` | `SubmissionDetailResponse` | Verifies and links a repository to an existing submission. Safe rollback on failure. |
| `PATCH` | `/submissions/{sub_id}/branch` | `UpdateBranchRequest` | `SubmissionDetailResponse` | Verifies branch existence on GitHub, resolves latest commit SHA, and updates target branch. |
| `POST` | `/submissions/{sub_id}/verify` | None | `SubmissionDetailResponse` | Refreshes repository accessibility, updates commit SHA if new commits were pushed, and records diagnostic notes. |
| `POST` | `/submissions/{sub_id}/unlink-repository` | None | `SubmissionDetailResponse` | Unlinks repository and clears commit SHA. Blocked if evaluations have run. |

---

### 5. Append-Only Audit Logging

All repository operations generate immutable audit events recorded in `audit_events`:

1. `repository_linked`: Emitted when a repository is successfully verified and bound to a submission.
2. `submission_branch_updated`: Emitted when target branch is updated with its newly resolved commit SHA.
3. `submission_verification_refreshed`: Emitted when verification is re-tested and latest commit SHA updated.
4. `repository_unlinked`: Emitted when a repository is detached from a submission.

---

### 6. Frontend Integration

1. **API Client & Type Definitions:**
   - Extended [api.ts](file:///home/shubh/scorva/apps/web/src/types/api.ts) with `RepositoryConnectionStatus`, `ValidateRepositoryRequest`, `RepositoryValidationResult`, `LinkRepositoryRequest`, `UpdateBranchRequest`, and verified submission fields.
   - Added matching asynchronous methods in [api-client.ts](file:///home/shubh/scorva/apps/web/src/lib/api-client.ts).
2. **Submissions Tab UI:**
   - Enhanced [page.tsx](file:///home/shubh/scorva/apps/web/src/app/organizations/[organizationId]/hackathons/[hackathonId]/page.tsx):
     - **Connection Status Badges:** Visual indicators for `verified` (green check), `unverified` (amber clock), `failed` (red alert with diagnostic code tooltip), and `unlinked` (gray badge).
     - **Git Details:** Shows target branch, default branch, resolved commit SHA chip (`GitCommit` icon with 7-character hash), and last verified timestamp.
     - **Action Toolbar:**
       - **Verify Button:** Triggers `refreshSubmissionVerification` with loading spinner.
       - **Branch Button:** Opens "Update Target Branch" modal.
       - **Relink Button:** Opens "Link / Relink Repository" modal.
       - **Unlink Button:** Prompts and calls `unlinkSubmissionRepository`.
     - **Pre-submission Testing in Submit Modal:** "Test Connection" button invokes `validateRepository` before submission and renders live status (branch, commit SHA, app authorization status, or exact error diagnostic).

---

### 7. Automated Test Suite Verification

#### 7.1 M6.2 Dedicated Test Suite
**File:** [test_repository_linking_m6_2.py](file:///home/shubh/scorva/apps/api/tests/test_repository_linking_m6_2.py)
**Results:** `18 passed in 23.15s`

1. `test_url_parser_rejects_credentials`: Rejects embedded username/password (`CREDENTIALS_IN_URL_FORBIDDEN`).
2. `test_url_parser_rejects_nonstandard_ports`: Rejects ports like 8443 (`UNSUPPORTED_GIT_PORT`).
3. `test_url_parser_rejects_query_and_fragment`: Rejects query parameters and `#` fragments (`INVALID_URL_COMPONENTS`).
4. `test_url_parser_rejects_unsupported_providers`: Rejects GitLab, Bitbucket (`UNSUPPORTED_GIT_PROVIDER`).
5. `test_url_parser_accepts_clean_github_urls`: Normalizes HTTPS `.git` and trailing slash URLs.
6. `test_ssrf_egress_protection_blocks_private_ips`: Blocks `127.0.0.1`, `169.254.169.254`, `10.0.0.1`, `192.168.1.1`.
7. `test_api_validate_repository_success`: Validates repository, branch, and commit SHA via API.
8. `test_api_validate_repository_branch_not_found`: Correctly returns `BRANCH_NOT_FOUND` on missing branch.
9. `test_api_validate_repository_rate_limited`: Truthfully surfaces `GITHUB_RATE_LIMITED`.
10. `test_api_create_submission_with_verified_repo`: Auto-populates verified commit and branch on creation.
11. `test_api_duplicate_repository_rejected`: Rejects duplicate active repo URL in same hackathon (409).
12. `test_api_link_repository_success_and_audit`: Verifies linking, commit resolution, and audit record.
13. `test_failsafe_invariant_failed_link_preserves_existing_data`: Proves failed verification leaves valid link intact.
14. `test_api_update_target_branch_and_audit`: Updates target branch, commit SHA, and audit trail.
15. `test_api_refresh_verification`: Resolves new HEAD commit SHA on refresh.
16. `test_api_unlink_repository_and_evaluation_guard`: Blocks unlinking if evaluation job exists; succeeds otherwise.
17. `test_api_non_team_member_cannot_modify_submission`: Enforces team membership authorization (403).
18. `test_api_cross_tenant_isolation_denied`: Proves Org B cannot touch Org A submission (403).

#### 7.2 Regression Suite Clean Execution
- **M6.1 & Hackathons Suite:** 21/21 passed in 43.71s (`test_hackathon_workflows_m6_1.py`, `test_hackathons.py`).
- **Phase 5 Suite:** 75/75 passed in 25.67s (`test_evaluation_outbox_m5_1.py`, `test_worker_engine_m5_2.py`, `test_pipeline_m5_3.py`, `test_reaper_m5_4.py`, `test_concurrency_and_observability_m5_5.py`).
- **Frontend Test Suite:** 7/7 unit & race tests passed (`npm --prefix apps/web test`).
- **TypeScript Static Check:** 0 errors (`npm --prefix apps/web run typecheck`).

---

### 8. Milestone Completion Sign-Off

Sub-Milestone 6.2 meets all technical and security criteria specified in the Phase 6 master plan. The repository linking subsystem is stable, failsafe, tenant-isolated, and ready for Sub-Milestone 6.3 (GitHub Events & Project Activity).

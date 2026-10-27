# Scorva — Phase 4 Quality Assurance & Testing Plan
## AI-Powered Hackathon Evaluation Engine

**Document Version:** 1.0  
**Date:** October 26, 2026  
**Status:** **APPROVED TEST SPECIFICATION**  
**Author:** Lead QA & Verification Engineer, Backend Architect  

---

## 1. Testing Philosophy & Quality Strategy

Phase 4 testing requires verifying multi-tenant isolation, asynchronous worker pipelines, third-party network failure handling, adversarial untrusted repository archives, prompt injection resistance, and deterministic score computation.

The testing pyramid is organized into 5 distinct layers:

```
          [ End-to-End Acceptance Tests ]
        [ Component & Worker Simulation Tests ]
      [ Adversarial Security & Injection Fixtures ]
    [ Multi-Tenant Integration & API Contract Tests ]
  [ Deterministic Unit & Mathematical Scoring Tests ]
```

---

## 2. Layered Test Catalog

### Layer 1: Configuration, RBAC & Mathematical Verification Tests

- **`test_configuration_service.py`:**
  - **Schema & Bounds Validation:**
    - Verifies typed Pydantic models for all categories (`judge.*`, `eval.*`, `extract.*`, `ai.*`, `platform.*`).
    - Asserts that out-of-bounds values (e.g., `extract.max_compressed_bytes = 500MB`, `judge.rationale_min_length = 5`) are rejected with `HTTP 422 Unprocessable Entity`.
    - Asserts that Tier 1 settings can only be set at Platform scope and Tier 5 invariants cannot be altered at any scope.
  - **Cascading Precedence Resolution (Path A):**
    - Setup: Platform default (`eval.default_scoring_mode = 'offset_normalized'`), Org override (`raw_proportional`), Hackathon override (`offset_normalized`).
    - Verifies resolution order: Hackathon override takes precedence over Org, Org takes precedence over Platform, Platform takes precedence over Safe Default.
    - Snapshot binding: Verifies that evaluation job uses frozen `configuration_snapshot` from `submission_snapshots`, completely immune to subsequent Org or Hackathon edits.
  - **Two-Phase Limit Validation:**
    - Phase 1 (Config-Update Time): Verifies Pydantic schema validation rejects out-of-bounds inputs (e.g. `extract.max_compressed_bytes = 500MB` -> `HTTP 422`). Asserts Tier 5 keys unconditionally return `HTTP 403 Forbidden` (`SECURITY_INVARIANT_IMMUTABLE`).
    - Phase 2 (Runtime Ingestion Time): Asserts extractor enforces hardcoded constants (`ABSOLUTE_MAX_COMPRESSED_BYTES = 100MB`, `ABSOLUTE_MAX_UNCOMPRESSED_BYTES = 500MB`) regardless of database values. Verifies path containment, symlink rejection, and zero-code execution have no toggle flags.
  - **Super Admin Delegation Enclosure:**
    - Asserts that Organization Admins can only override settings where `allow_org_override = TRUE` and within platform `[min_value, max_value]`.
    - Asserts that attempts by tenant admins to override Tier 1, Tier 2, or Tier 5 settings raise `HTTP 403 Forbidden`.
  - **Correct Rollback Semantics:**
    - Restoring a prior configuration creates a **NEW** version `v4` and appends to `configuration_history` with `restored_from_version = 1`.
    - Restored value is re-validated against current schema rules (fails with `HTTP 422` if current bounds reject historical value).
    - Optimistic concurrency: Stale `current_version` fails with `HTTP 409 Conflict`.
    - Asserts that past `submission_snapshots.configuration_snapshot` values are 100% immutable and unchanged by rollbacks.

- **`test_dynamic_rbac_service.py`:**
  - **Dual-Path Isolation (Path B vs. Path A):**
    - Asserts that an evaluation snapshot NEVER grants permissions or bypasses live authorization checks.
    - Test mid-job revocation: Judge submits score adjustment after judge assignment is revoked -> returns `HTTP 403 Forbidden` (`JUDGE_ASSIGNMENT_REVOKED`).
    - Test diagnostic exposure: User without `evaluation.view_raw_model` denied access even if they triggered the historical job.
  - **Participant Permissions & Team Privacy:**
    - Verifies participant role capabilities: `participant.register`, `participant.team.create/join`, `participant.submission.create/update/withdraw`.
    - Hard deadline enforcement: Submission update after `hackathon.submission_deadline` fails with `HTTP 400 Bad Request` (`SUBMISSION_DEADLINE_PASSED`).
    - Team isolation: Participant in Team 1 attempts to query or read Team 2's submission -> returns `HTTP 404 / 403`.
    - Feedback gating: Participant attempts to view evaluation report before `eval.participant_view_scores = TRUE` and hackathon completion -> returns `HTTP 403 Forbidden`.
  - **Delegation Boundary Enforcement:**
    - Asserts that an administrator cannot create a role or grant a permission that they themselves do not possess.
    - Asserts that Org Admins cannot grant Platform-level permissions or modify platform configuration (`is_delegable = FALSE`).
  - **Serialized Last Platform Owner Lockout Protection:**
    - Spawns two concurrent threads attempting to demote/delete the remaining two Platform Owners simultaneously.
    - Asserts that transaction serialization (`pg_advisory_xact_lock` + `SELECT id FROM roles WHERE name = 'platform_owner' FOR UPDATE`) allows exactly one transaction to succeed and forces the other to fail with `LAST_PLATFORM_OWNER_LOCKOUT` (`HTTP 400 Bad Request`).
    - Asserts that user deactivation in `users` also verifies surviving platform owners $\ge 1$.
  - **Revocation vs. In-Progress Protected Write Race:**
    - Simulates sensitive write (judge score override) concurrent with role revocation.
    - Asserts that commit-phase authorization check serializes cleanly: if revocation commits first, write aborts with `HTTP 403 Forbidden`; zero torn authorization states.
  - **Durable Versioning & Outbox Recovery:**
    - Asserts committed role/permission changes write to `authz_policy_versions` and insert an event into `authz_invalidation_outbox` in the same transaction.
    - Tests relay worker recovering from simulated Redis connection failure without losing invalidation events.
  - **Fail-Closed Outage Semantics & Staleness Bounds:**
    - Simulates authorization service outage during sensitive operation: asserts immediate fail-closed rejection with `HTTP 503` or `HTTP 403` (`AUTHZ_SERVICE_UNAVAILABLE`).
    - Simulates total Redis Pub/Sub packet loss: asserts that monotonic `user_perms_version:{user_id}` check and 30-second L1 memory TTL prevent stale authorization beyond 30 seconds.
    - Strict Auth Mode: High-risk operations (score overrides, rubric publishing, job dispatch) bypass L1 memory cache and verify directly against Redis/PostgreSQL.

- **`test_scoring_calculator.py`:**
  - Configurable scoring formula verification:
    - Mode A (`offset_normalized`): $\text{Normalized} = \frac{S_i - \text{min}}{\text{max} - \text{min}}$ awarding $0\%$ for minimum score and $100\%$ for maximum score.
    - Mode B (`raw_proportional`): $\text{Proportional} = \frac{S_i}{\text{max}}$ awarding proportional credit.
  - Precision and rounding: verifying `ROUND_HALF_UP` behavior on fractional boundaries (e.g., `85.455 -> 85.46`, `85.454 -> 85.45`).
  - Strict prohibition of IEEE-754 binary floating-point calculations (`float`); asserts all intermediate and final scoring math uses Python `decimal.Decimal`.
  - Rubric weight sum validation: passes when $|\sum w_i - 1.0000| \le 0.0001$; fails when sum is $0.9990$ or $1.0010$.
  - Score bounds clamping: rejects scores $< \text{min\_score}$ or $> \text{max\_score}$.
- **`test_rubric_validation.py`:**
  - Criteria definition validation: asserts titles, descriptions, and non-empty evidence requirements.
  - Frozen version immutability: asserts that once `status == 'published'`, criteria cannot be added, removed, or modified.

### Layer 2: Database Constraints & Migration Tests

- **`test_phase4_migrations.py`:**
  - **Migration Branching from `de1a35a5cc94` (Milestone 1):**
    - Clean `upgrade` against Postgres: verifies Subsystem A (tables 1-3: `configuration_settings`, `configuration_overrides`, `configuration_history`) and Subsystem B (tables 4-7: `permissions`, `roles`, `role_permissions`, `user_role_assignments` + `authz_policy_versions` + `authz_invalidation_outbox`) are created with unique constraints and foreign keys.
    - Explicitly verifies `down_revision = 'de1a35a5cc94'` (the verified database head).
    - Seeds default granular permissions and system roles (`platform_owner`, `platform_admin`, `org_owner`, `org_admin`, `organizer`, `judge`, `mentor`, `participant`).
    - Uses string-backed columns with check constraints for dynamic roles/permissions to ensure atomic transaction rollback compatibility across all PostgreSQL versions.
    - Clean `downgrade -1` returning schema cleanly to `de1a35a5cc94`.
  - **Migration `c053567b0586` / `create_phase4_evaluation_schema` (Milestone 2):**
    - Clean `upgrade` from Milestone 1 migration: creates Subsystem C (tables 8-22: `teams`, `team_members`, `submissions`, `submission_snapshots`, `rubrics`, `rubric_versions`, `rubric_criteria`, `organization_integrations`, `evaluation_jobs`, `evaluation_results`, `evaluation_criterion_scores`, `evidence_references`, `judge_reviews`, `judge_criterion_scores`, `hackathon_judges`).
    - Verifies JSONB column `configuration_snapshot` on `submission_snapshots`.
    - Clean `downgrade -1` dropping evaluation schema back to Milestone 1 head.
  - **Migration `d630cee07d82` / `remedy_m2_evaluation_schema_constraints` (Milestone 2 Remediation):**
    - Enforces PostgreSQL foreign key constraint `fk_evaluation_jobs_current_result_id` with `ON DELETE SET NULL`.
    - Installs lifecycle triggers `trg_rubric_versions_protect` (blocks deletion/unpublishing of published rubrics) and `trg_submission_snapshots_immutable` (freezes snapshot configuration and identity).
    - Updates `check_rubric_version_immutability()` to prevent reparenting criteria between published and draft versions.
    - Verified via disposable test database in `test_evaluation_migrations.py` across full upgrade, downgrade, and re-upgrade cycle.
  - **`test_m2_integrity_remediation.py`:**
    - Real PostgreSQL integration tests verifying all 4 integrity findings.
    - Tests direct SQL mutations, reparenting vectors, snapshot freezes, and FK `ON DELETE SET NULL`.
    - Concurrency tests: separate database sessions verify that `publish_rubric_version` with `SELECT ... FOR UPDATE` strictly serializes against concurrent `add_rubric_criterion` and parallel publication attempts.
  - Idempotency and repeatability of multiple upgrade/downgrade test cycles.
- **`test_audit_trail_durability.py`:**
  - Verifies that every role grant, permission update, role revocation, and configuration rollback inserts an immutable row into `audit_events` or `configuration_history` within the same transaction.
  - Asserts that all records contain actor ID, email, role, IP address, user agent, action, resource, before/after diff payload, and correlation ID.
  - Asserts that `UPDATE` or `DELETE` on `audit_events` is blocked by PostgreSQL trigger `trg_audit_events_immutable`.
- **`test_evaluation_db_constraints.py`:**
  - Unique constraint `uq_config_key_scope (key, scope_type, scope_id)`.
  - Unique constraint `uq_role_name_scope (name, scope_type, scope_id)`.
  - Unique constraint `uq_user_role_assignment (user_id, role_id, scope_type, scope_id)`.
  - Unique constraint `uq_hackathon_rubric_name (hackathon_id, name)`.
  - Unique constraint `uq_rubric_version (rubric_id, version_number)`.
  - Unique constraint `uq_submission_snapshot_commit (submission_id, commit_sha)`.
  - Unique constraint `uq_eval_result_attempt (job_id, attempt_number)`.
  - Foreign key `ON DELETE RESTRICT` on organizations, hackathons, and submissions (preventing accidental cascade deletion of evaluation history).
  - Immutability trigger test: PostgreSQL trigger blocks any INSERT, UPDATE, or DELETE on `rubric_criteria` when parent `rubric_versions.status == 'published'`.

### Layer 3: Safe Extraction & Adversarial Fixture Tests (Milestone 3 — 18 Tests)

- **`test_safe_extraction.py` (18/18 passing):**
  - **Legitimate Archives:** Valid tar.gz and zip archive extraction verifying files, directories, nested structures, and content integrity.
  - **Zip Bomb & Uncompressed Size Fixture:** Archive expanding to >250MB. Asserts extraction aborts immediately when cumulative uncompressed bytes exceed $262,144,000$ (250MB) with `QuotaExceededError`.
  - **Compressed Stream Size Fixture:** Archive stream exceeding $52,428,800$ (50MB). Asserts immediate abort with `QuotaExceededError`.
  - **Single File Size Fixture:** Archive containing an 11MB file. Asserts immediate rejection upon breaching $10,485,760$ (10MB) with `QuotaExceededError`.
  - **File Count Fixture:** Archive containing $> 2000$ files. Asserts rejection with `QuotaExceededError`.
  - **Nesting Depth Fixture:** Archive with directory depth $> 10$. Asserts rejection with `QuotaExceededError`.
  - **Path Length Fixture:** Archive with file path length $> 255$ characters. Asserts rejection with `QuotaExceededError`.
  - **Path Traversal Fixtures (ZipSlip):** 6 adversarial fixtures covering `../../../../etc/passwd`, `..\..\Windows\System32`, hidden double dots, and absolute paths. Asserts immediate rejection via `Path.is_relative_to` with `SecurityViolationError`.
  - **Symlink & Hardlink Fixtures:** Archives containing symlinks (`issym()`) and hardlinks (`islnk()`). Asserts immediate rejection with `SecurityViolationError`.
  - **Special Device Fixtures:** Archives containing FIFOs (`isfifo()`), block devices (`isblk()`), and character devices (`ischr()`). Asserts rejection.
  - **Ephemeral Sandbox Cleanup:** Context manager `ephemeral_extracted_repository` guarantees deletion of temporary `/tmp/scorva/eval_*` scratch directory even on errors.

### Layer 4: SSRF Defense, Credential Security & Ingestion Tests (Milestone 3 — 19 Tests)

- **`test_ssrf_guard.py` (4/4 passing):**
  - **Profile A (Public Web Egress — GitHub Downloads):**
    - Blocks private IPv4 subnets: `10.0.0.1`, `172.16.0.1`, `192.168.1.1`, `127.0.0.1`.
    - Blocks AWS / Cloud metadata endpoint: `169.254.169.254`.
    - Blocks IPv6 loopback (`::1`), unique local (`fc00::`), and link-local (`fe80::`).
    - Blocks carrier-grade NAT: `100.64.0.1`.
    - Enforces host allowlist strictly (`api.github.com`, `codeload.github.com`).
    - Pinned transport connects directly to pre-resolved public IP, eliminating DNS rebinding TOCTOU windows.
  - **Profile B (Internal Inference Egress — Ollama):**
    - Permits configured `ALLOWED_INTERNAL_AI_HOSTS` (`ollama`, `localhost`, `127.0.0.1`).
    - Disallows arbitrary user-supplied provider URLs.
    - Rejects redirects: Asserts `follow_redirects=False` rejects HTTP redirects.
- **`test_integrations_service.py` (5/5 passing):**
  - AES-256-GCM encryption and decryption of GitHub PATs in `organization_integrations`.
  - Masked preview generation (`ghp_****1234`).
  - Prohibits storing raw credentials in `organizations.settings` JSON via `assert_settings_does_not_contain_credentials`.
  - Token rotation and revocation zero out plaintext and record audit events (`INTEGRATION_CONFIGURED`, `INTEGRATION_TOKEN_ROTATED`, `INTEGRATION_REVOKED`).
  - Strict tenant isolation: Tenant A cannot retrieve or rotate Tenant B's credentials.
- **`test_secret_redaction.py` (4/4 passing):**
  - Regex secret masking redacts GitHub tokens (`ghp_...`), AWS keys (`AKIA...`), OpenAI keys (`sk-...`), JWTs (`eyJ...`), and passwords from code snippets.
  - Sensitive file exclusion: `.env*`, `*.pem`, `*.key`, `id_rsa*`, `credentials.json`, `.git/`, `node_modules/`, `venv/`.
  - File taxonomy categorization (`documentation`, `build_config`, `test_suites`, `source_code`).
  - Structural XML context framing (`<UNTRUSTED_REPOSITORY_EVIDENCE>`).
- **`test_github_client.py` (6/6 passing):**
  - GitHub URL parsing and validation.
  - Commit SHA resolution via `GET /repos/{owner}/{repo}/commits/HEAD`.
  - Streaming download with 302 redirect tracking to `codeload.github.com` and `Authorization` header stripping across hosts.
  - SSRF redirect rejection when redirect target points to non-allowlisted host or private IP.
  - Redirect loop protection (max 3 redirects).
  - End-to-end ingestion pipeline (resolve SHA $\rightarrow$ download $\rightarrow$ extract $\rightarrow$ index evidence).

### Layer 5: AI Provider Abstraction & Output Validation Tests (Milestone 4 — Remediated & Verified: 52/52 Passing)

- **`test_ssrf_guard.py` (6/6 passing):**
  - Public unicast IP validation matrix (blocking RFC 1918, loopbacks, link-local, carrier-grade NAT, cloud metadata 169.254.169.254).
  - Profile A URL validation and port 443 bounding.
  - Profile B internal AI endpoint validation (`ALLOWED_INTERNAL_AI_HOSTS`, allowed ports, port scanning prevention for ports 5432, 6379, 22, 8000).
  - Live TCP integration test with `ProfileBAsyncHTTPTransport` verifying immediate rejection of HTTP 302 redirects with `AI_PROVIDER_REDIRECT_DISALLOWED`.
  - Live TCP loopback communication over pinned IP socket.
- **`test_ai_provider.py` (22/22 passing):**
  - `AIProviderClient` protocol runtime adherence for `MockAIProviderClient` and `OllamaProviderClient`.
  - Deterministic offline mock execution with zero network and zero credentials.
  - Live TCP integration tests for Ollama /api/chat request formatting, stream closure, response parsing, and error encapsulation.
  - SEC-M4-01 Incremental chunk streaming and real-time response size bounding:
    - Multi-chunk streaming within byte limits.
    - Multi-chunk streaming exceeding limit aborts immediately (`AIProviderResponseSizeError`).
    - Responses without `Content-Length` headers bounded cumulatively.
    - Early rejection on oversized `Content-Length` headers.
  - SEC-M4-02 Production mock guard:
    - Factory raises `AIProviderConfigError` when `ai_default_provider = "mock"` and `SCORVA_ENV == "production"`.
    - Normal operation in development/test environments.
  - SEC-M4-03 ElementTree XML attribute escaping in `<METADATA>` and `<INVENTORY>`.
  - SEC-M4-05 Decoupled timeout and network error handling:
    - `AIProviderTimeoutError` immediately raises without retrying or sending schema prompts (1 call, 0 retries).
    - `AIProviderConnectionError` immediately raises without schema retries (1 call, 0 retries).
    - `AIProviderFormatError` retries at most once for recoverable parse errors.
- **`test_prompt_injection_resilience.py` (24/24 passing):**
  - 20 distinct adversarial prompt injection vectors: delimiter breakout, instruction override, fake system messages, jailbreak, roleplay, base64, hex, rot13, secret probes, markdown breakout, XML CDATA, criterion hallucination, numerical score bounds, duplicate criteria, criterion omission, RBAC escalation, tool call injection, system prefix spoofing, fabricated citations, missing evidence score inflation.
  - SEC-M4-04 Downstream output validation assertions on vectors 04 through 10:
    - Vector 04: Unconstrained score 100 rejected with `SCORE_OUT_OF_BOUNDS`.
    - Vector 05: Extra conversational fields (`bedtime_story`) rejected with `SCHEMA_VALIDATION_ERROR`.
    - Vector 06: Decoded base64 criterion injection rejected with `UNKNOWN_CRITERIA_DETECTED`.
    - Vector 07: Fabricated hex-named file citation rejected with `FABRICATED_CITATION_FILE`.
    - Vector 08: Missing evidence rule violation rejected with `MISSING_EVIDENCE_SCORE_MISMATCH`.
    - Vector 09: Secret extraction extra fields rejected with `SCHEMA_VALIDATION_ERROR`.
    - Vector 10: Truncated breakout JSON missing criteria rejected with `SCHEMA_VALIDATION_ERROR`.
  - Structural schema and numerical edge cases: rejection of NaN, Infinity, -Infinity, inverted line ranges (`start_line > end_line`), line range overflows, and extra unapproved JSON fields (`extra="forbid"`).

### Layer 6: Worker Orchestration, Fencing & Fault-Tolerance Tests (Milestone 5 — Planned)

- **`test_worker_leases.py`:**
  - Renewable lease acquisition: worker acquires lock with unique UUID claim token.
  - Heartbeat renewal: background thread extends TTL every 15s.
  - CAS Generation Fencing: Worker 1 loses lease due to network pause; Worker 2 claims job (increments `lock_version`); Worker 1 resumes and attempts to commit; Worker 1 CAS check fails (0 rows updated) and worker aborts cleanly without committing results.
- **`test_reaper_task.py`:**
  - Simulated worker crash: job remains in `running` status with stale heartbeat (>3 minutes).
  - Reaper task runs: resets status to `queued` if attempts remain, or marks `failed` with `WORKER_HEARTBEAT_TIMEOUT`.
- **`test_job_idempotency.py`:**
  - Multiple evaluation dispatches with the same `Idempotency-Key` return identical `202 Accepted` response with the existing `job_id`.
  - Duplicate Celery task deliveries execute once without creating duplicate evaluation records.

### Layer 6: Multi-Tenant API & RBAC Tests

- **`test_evaluation_tenant_isolation.py`:**
  - Setup 2 distinct organizations (`Org A`, `Org B`) and 2 hackathons (`Hackathon A`, `Hackathon B`).
  - Tenant A organizer attempts to create submission or evaluation in Tenant B hackathon -> HTTP 404/403.
  - Tenant A organizer attempts to read Tenant B's evaluation job or results -> HTTP 404/403.
  - Tenant A organizer attempts to cancel Tenant B's evaluation job -> HTTP 404/403.
  - Tenant A judge attempts to submit review for Tenant B's evaluation -> HTTP 404/403.
  - Super Admin with `AI_OPS_ADMIN` role can inspect cross-tenant job diagnostics via `/api/v1/admin/ai/jobs`.
- **`test_judge_permissions.py`:**
  - Judge attempts to create rubric draft -> HTTP 403 Forbidden.
  - Judge attempts to publish rubric version -> HTTP 403 Forbidden.
  - Judge attempts to trigger evaluation job -> HTTP 403 Forbidden.
  - Judge attempts to manage GitHub integration credentials -> HTTP 403 Forbidden.
  - Judge attempts to invite organization members -> HTTP 403 Forbidden.
  - Judge successfully views evaluation results and citations -> HTTP 200 OK.
  - Judge submits review with score adjustments:
    - With valid justification ($\ge 20$ chars) -> HTTP 201 Created.
    - With empty or short justification ($< 20$ chars) -> HTTP 422 Unprocessable Entity.
  - Raw AI scores are permanently preserved alongside adjusted scores.
  - Transactional audit log emitted with `action = "judge_review.submitted"`.

### Layer 7: Frontend Unit & Behavioral Race Tests

- **`test_ai_operations_ui.mjs`:**
  - Typecheck and build verification for `/admin/ai-operations`.
  - Real-time job polling, stage progress bar rendering, error diagnosis display.
- **`test_tenant_evaluation_race.mjs`:**
  - Switching between submissions or organizations while evaluation status requests are pending immediately cancels prior requests via `AbortController`.
  - Stale responses cannot overwrite newly selected submission view.

---

## 3. Measurable Acceptance Criteria & Quality Gates

| Test Suite / Metric | Target Threshold | Measurable Gate Condition |
|---|:---:|---|
| **Backend Test Suite Pass Rate** | **100%** (All existing 125 tests + all new Phase 4 tests) | Zero failures, zero unexpected skips across full regression suite. |
| **Deterministic Score Calculator** | Absolute error $= 0.00$ compared to manual decimal calculations | Python `Decimal` with `ROUND_HALF_UP` matches pre-calculated fixture tables across both scoring modes. |
| **Safe Extraction Path Traversal** | 100% of traversal fixtures rejected | 25 distinct directory traversal archive fixtures rejected immediately with `SecurityViolationError`. |
| **Archive Quota Enforcement** | 100% of oversized fixtures rejected | Streaming extraction aborts when cumulative bytes $> 250$MB, single file $> 10$MB, files $> 2000$, or depth $> 10$. |
| **Public SSRF Defense (Profile A)** | 100% of forbidden destination attempts blocked | Rejects all private IP connections, cloud metadata (`169.254.169.254`), and unauthorized redirects. |
| **Internal AI Egress (Profile B)** | 100% of non-allowlisted hosts and redirects blocked | Restricts connections to `ALLOWED_INTERNAL_AI_HOSTS`; rejects all HTTP redirects. |
| **Model Output Validation Failure** | 0 malformed scores accepted | Malformed JSON or out-of-bounds scores trigger retry with temp 0.0, then fail closed to `FAILED` status. |
| **Cross-Tenant Evaluation Isolation** | 0 cross-tenant leaks | 100% of cross-tenant evaluation queries and mutation attempts return HTTP 404 or 403. |
| **Role Authorization Boundary** | 100% of unauthorized judge operations blocked | Judge role strictly prevented from rubric creation, rubric publishing, job dispatch, and credential management. |
| **Configuration Bounds Enforcement** | 100% of out-of-bounds or Tier 5 mutation attempts rejected | Pydantic validation rejects illegal ranges; authorization rejects non-Platform edits to Tier 1 and all edits to Tier 5. |
| **Two-Phase Limit Enforcement** | Hardcoded runtime ceilings strictly enforced | Extractor enforces hardcoded caps (100MB/500MB) regardless of DB; zero toggle flags for algorithmic safeguards. |
| **Dual-Path Authorization Separation**| 0 snapshot authorization bypasses | Evaluation snapshots strictly isolated to scoring mechanics; 100% of live access revocations take effect immediately. |
| **Participant Team Isolation** | 0 cross-team leaks | 100% of attempts by participants to read/edit other teams' submissions or unreleased feedback return HTTP 403/404. |
| **Rollback Immutability & Concurrency**| 100% history preservation | Rollbacks generate new version `v_new`, re-validate against current bounds, require matching `version`, and never alter historical snapshots. |
| **Bounded Permission Staleness** | $\le 30$s staleness on total Pub/Sub failure | Strict 30s L1 memory TTL + monotonic version check; sensitive operations bypass L1 cache completely. |
| **Fail-Closed Authorization Outages** | 100% fail-closed rejection on authz outage | Rejects sensitive operations with HTTP 503 or 403 if PostgreSQL or authorization service is unreachable. |
| **Dynamic RBAC Delegation Boundary** | 0 privilege escalation leaks | Administrators strictly prevented from creating roles or granting permissions they do not possess. |
| **Serialized Platform Owner Lockout** | 100% of concurrent lockout attempts blocked | Serialization via advisory lock + row lock allows exactly one removal under concurrent race, strictly preserving $\ge 1$ owner. |
| **Durable Invalidation Outbox** | 0 lost invalidation events | Committed mutations write to `authz_invalidation_outbox`; relay worker retries with exponential backoff on Redis failure. |
| **Attributable Audit Trail Durability**| 100% transactional audit emission | Every grant, revoke, and rollback inserts immutable row into `audit_events` with actor, IP, diff payload, and correlation ID. |
| **Alembic Migration Verification** | Clean upgrade from `de1a35a5cc94`; clean downgrade | Verified against real database head `de1a35a5cc94` without schema remnants. |
| **Frontend TypeScript Typecheck** | **0 errors** (`npm run typecheck --prefix apps/web`) | Full TypeScript compilation with `'judge'` restored in `OrgRole` and all configuration/RBAC types. |
| **Next.js Production Build** | **100% clean compilation** (`npm run build --prefix apps/web`) | All static and dynamic routes compile cleanly. |
| **Stale Worker Fencing** | 0 duplicate official evaluations under simulated crash | Monotonic CAS counter blocks fenced worker commits with 0 rows updated. |

---

## 4. Test Environment Setup & CI Execution Matrix

```bash
# 1. Run Configuration & RBAC Service Tests
.venv/bin/pytest apps/api/tests/test_configuration_service.py apps/api/tests/test_dynamic_rbac_service.py -v

# 2. Run Database Migration & Constraint Tests (Migrations 0003 & 0004)
.venv/bin/pytest apps/api/tests/test_phase4_migrations.py apps/api/tests/test_evaluation_db_constraints.py -v

# 3. Run Unit, Calculator & Rubric Validation Tests
.venv/bin/pytest apps/api/tests/test_scoring_calculator.py apps/api/tests/test_rubric_validation.py -v

# 4. Run Security & Adversarial Fixture Tests
.venv/bin/pytest apps/api/tests/test_safe_extraction.py apps/api/tests/test_ssrf_guard.py apps/api/tests/test_prompt_injection_resilience.py apps/api/tests/test_secret_redaction.py -v

# 5. Run Worker Leases, Fencing & Reaper Tests
.venv/bin/pytest apps/api/tests/test_worker_leases.py apps/api/tests/test_reaper_task.py apps/api/tests/test_job_idempotency.py -v

# 6. Run Multi-Tenant API & Judge Review Tests
.venv/bin/pytest apps/api/tests/test_evaluation_tenant_isolation.py apps/api/tests/test_judge_reviews.py -v

# 7. Run Full Platform Pytest Suite
.venv/bin/pytest apps/api/tests -v

# 8. Run Frontend Typecheck & Behavioral Tests
npm test --prefix apps/web
npm run build --prefix apps/web
```

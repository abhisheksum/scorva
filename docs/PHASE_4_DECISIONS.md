# Scorva — Phase 4 Architecture Decision Records (ADRs)
## AI-Powered Hackathon Evaluation Engine

**Document Version:** 1.0  
**Date:** October 26, 2026  
**Status:** **APPROVED DECISION LOG**  
**Author:** Lead Software Architect & Systems Engineer  

---

## ADR-01: Zero Code Execution vs. Dynamic Sandboxed Execution in Phase 4

### Status: **ACCEPTED**

### Context
Hackathon submissions consist of arbitrary source code written by external participants. Evaluating the code could theoretically include:
1. Compiling and running the application (e.g. `npm install && npm start`, `cargo run`).
2. Executing automated test suites (`pytest`, `npm test`).
3. Running static analysis (AST parsing, file classification, documentation parsing, token metrics, secret masking, and LLM code evaluation).

Executing untrusted code introduces severe security risks: container escapes, cryptomining, network scanning, kernel vulnerabilities, and persistence attacks. Safe execution requires complex virtualization infrastructure (e.g., Firecracker microVMs or gVisor runtimes).

### Decision
For Phase 4, Scorva adopts a strict **Zero-Code-Execution (Static Analysis Only)** policy:
- Archives are extracted into temporary directories without executing any build, install, or run commands.
- Analysis is performed exclusively via static file tree classification, AST generation, documentation reading, test suite inspection (verifying test files exist and reading their code), secret redaction, and generative AI review.
- Dynamic sandbox execution is explicitly deferred to Phase 5+.

### Consequences & Trade-Offs
- **Pros:** Completely eliminates arbitrary code execution (RCE) vulnerabilities; prevents infinite build loops, dependency bomb attacks, and malicious binary execution; minimizes infrastructure complexity in Phase 4.
- **Cons:** Scorva cannot dynamically verify whether the code actually compiles or passes its unit tests in this phase. The evaluation evaluates the static implementation, architectural structure, and code quality rather than live runtime execution.

---

## ADR-02: Celery Worker Architecture & Dual SQLAlchemy Engine Management

### Status: **ACCEPTED**

### Context
Evaluation jobs involve downloading archives, static parsing, and invoking LLM models (which can take 15 to 60+ seconds per evaluation). Running this work in the FastAPI event loop (`BackgroundTasks`) would block asynchronous worker threads, exhaust memory in web containers, and provide no job recovery if an API process restarts.

Celery 5.4 with Redis is Scorva's target task queue. However, FastAPI uses async SQLAlchemy 2.0 with `asyncpg`, whereas Celery worker tasks execute synchronously in prefork or solo worker processes.

### Decision
1. Deploy Celery 5.4 with Redis (`redis://localhost:6379/1`) as the dedicated task queue broker.
2. In worker processes (`apps/api/workers/`), instantiate a dedicated **synchronous SQLAlchemy 2.0 engine** (`postgresql+psycopg2://` or `postgresql+asyncpg` run via sync session or `NullPool`) to avoid event loop conflicts and prevent connection pooling leaks across Celery worker forks.
3. Web API dispatches task messages (`job_id`, `organization_id`, `hackathon_id`) to Redis, returning `HTTP 202 Accepted` immediately.

### Consequences & Trade-Offs
- **Pros:** Complete isolation of long-running evaluations from the web request loop; reliable job queuing and retry semantics; horizontal scalability of worker nodes independent of API servers.
- **Cons:** Requires running a separate Celery worker process and Celery Beat daemon; requires managing dual database driver configurations (async for web API, sync for workers).

---

## ADR-03: Provider-Neutral AI Abstraction vs. Vendor Lock-In

### Status: **ACCEPTED**

### Context
Scorva is designed to run in diverse deployment environments: fully on-premise (e.g. enterprise hackathons using local Ollama instances) and cloud deployments (using hosted LLM APIs like Anthropic Claude or OpenAI). Hardcoding direct Ollama HTTP calls would couple evaluation logic to one model provider.

### Decision
1. Define a strict Python `Protocol`:
   ```python
   class AIProviderClient(typing.Protocol):
       async def generate_evaluation(
           self, 
           prompt: str, 
           schema: dict[str, Any], 
           model_name: str, 
           timeout_seconds: float
       ) -> dict[str, Any]: ...
   ```
2. Implement `OllamaProviderClient` as the initial local/on-premise adapter, leveraging Ollama's `/api/chat` endpoint with JSON Schema format enforcement.
3. Implement `MockAIProviderClient` returning deterministic, fixture-based evaluation responses for automated CI/CD testing without requiring a GPU or network access.
4. Enforce multi-layer SSRF validation and IP pinning on all configured provider base URLs.

### Consequences & Trade-Offs
- **Pros:** Seamless switching between Ollama, Mock, and future cloud model providers; zero-cost, deterministic automated testing; vendor independence.
- **Cons:** Schema capabilities are limited to the intersection of structured output capabilities supported across target providers (Ollama JSON Schema grammar constraint).

---

## ADR-04: Configurable Score Normalization & Financial-Grade Rounding

### Status: **ACCEPTED (Configurable Scoring Modes with Recommended Default)**

### Context
Rubric criteria frequently define score ranges where the minimum score is non-zero (e.g. $[1.0, 5.0]$ on a Likert scale or $[5.0, 10.0]$). Standard proportional scaling ($\frac{S}{max}$) produces counter-intuitive normalized scores when the minimum score is $>0$: awarding $1.0$ on a $1\text{--}5$ scale awards $20\%$ rather than $0\%$, meaning a project that failed every criterion would receive a baseline total score of $20/100$.

Conversely, zero-offset scaling ($\frac{S - min}{max - min}$) maps the minimum possible score ($S = min$) to $0.00\%$ and the maximum possible score ($S = max$) to $100.00\%$. However, if an organizer expects a raw point-accumulation model where 1 point out of 5 is simply 1 point, zero-offset scaling changes the scoring scale.

Furthermore, standard binary floating-point arithmetic (`float`) causes IEEE-754 precision drift (e.g. `0.1 + 0.2 = 0.30000000000000004`), which can cause total scores to vary across platforms or fail weight sum checks.

### Decision
1. Scorva implements two explicit mathematical scoring modes configurable per rubric:
   - **Mode A (`offset_normalized` — Recommended Default):**
     $$\text{Normalized Score}_i = \frac{S_i - \text{min\_score}_i}{\text{max\_score}_i - \text{min\_score}_i}$$
     $$\text{Weighted Score}_i = \text{Normalized Score}_i \times \text{Weight}_i \times 100$$
     $$\text{Total Score} = \text{round}\left(\sum_{i=1}^N \text{Weighted Score}_i, 2\right)$$
   - **Mode B (`raw_proportional`):**
     $$\text{Proportional Score}_i = \frac{S_i}{\text{max\_score}_i}$$
     $$\text{Weighted Score}_i = \text{Proportional Score}_i \times \text{Weight}_i \times 100$$
     $$\text{Total Score} = \text{round}\left(\sum_{i=1}^N \text{Weighted Score}_i, 2\right)$$
2. When all criteria have $\text{min\_score}_i = 0.00$, Mode A and Mode B produce mathematically identical results ($\frac{S_i - 0}{max_i - 0} = \frac{S_i}{max_i}$).
3. Prohibit IEEE-754 floating-point math in scoring computations; compute all weights, products, sums, and percentages using Python `decimal.Decimal` with explicit rounding mode `ROUND_HALF_UP` to 2 decimal places ($0.00$ to $100.00$).
4. Enforce strict rubric weight validation: $|\sum_{i=1}^N \text{Weight}_i - 1.0000| \le 0.0001$.

### Consequences & Trade-Offs
- **Pros:** Exact mathematical predictability; gives organizers the choice between scale-normalized and raw proportional scoring; eliminates float representation discrepancies.
- **Cons:** Requires storing `scoring_mode` on `rubrics` and converting Pydantic floats to `Decimal` in scoring functions.

---

## ADR-05: Rubric Versioning & Evaluation Snapshot Immutability

### Status: **ACCEPTED**

### Context
Hackathon organizers frequently tweak rubrics before an event. If rubrics were mutable entities and evaluations directly linked to a rubric ID, an organizer updating criteria or weights midway through judging would silently alter the calculations and historical rankings of already-evaluated submissions.

### Decision
1. Separate `rubrics` (parent metadata container) from `rubric_versions` (immutable snapshots of criteria, weights, and score ranges).
2. A rubric version starts in `draft` status.
3. Publishing a rubric version asserts $|\sum w_i - 1.0000| \le 0.0001$ and sets status to `published`. Once published, the version and its `rubric_criteria` are **strictly immutable**. Any subsequent changes require creating a new draft version ($V2, V3$).
4. Every `evaluation_job` and `evaluation_result` references `rubric_version_id`.
5. Every `submission` snapshot captures the exact frozen `commit_sha` being evaluated.

### Consequences & Trade-Offs
- **Pros:** Complete auditability; historical evaluation scores can never be silently corrupted by rubric adjustments; organizers can iterate on drafts safely.
- **Cons:** Slightly more complex relational model requiring a version table.

---

## ADR-06: Distributed Worker Lease Fencing & Crash Recovery

### Status: **ACCEPTED**

### Context
In distributed asynchronous systems, worker crashes, network partitions, and garbage-collection pauses can cause a worker to lose its distributed lock. If another worker takes over the job while the first worker resumes, both workers could write competing results to the database.

### Decision
1. Implement **Renewable Redis Leases**: The claiming worker acquires a 60-second lease with a unique UUID claim token. A background thread sends heartbeats renewing the lease every 15 seconds.
2. Implement **Database CAS Fencing**: The `evaluation_jobs` table includes `claim_token` and `lock_version` (an integer incremented on every status change). Before writing stage checkpoints or final scores, the worker executes a CAS update:
   ```sql
   UPDATE evaluation_jobs
   SET status = 'completed', lock_version = lock_version + 1
   WHERE id = :job_id AND claim_token = :my_claim_token AND lock_version = :my_lock_version;
   ```
   If 0 rows are updated, the worker has been fenced. It aborts immediately and discards its results.
3. Implement a **Celery Beat Reaper Task**: Scans every 60s for jobs in `running` status whose `last_heartbeat_at` is older than 3 minutes. Requeues the job if attempts remain, or marks `failed` with `WORKER_HEARTBEAT_TIMEOUT`.

### Consequences & Trade-Offs
- **Pros:** Eliminates duplicate evaluation persistence; guarantees recovery from worker crashes; prevents zombie workers from corrupting state.
- **Cons:** Requires Redis key TTL management and periodic background heartbeat threads in worker tasks.

---

## ADR-07: Human Judge Oversight & Auditable Adjustments

### Status: **ACCEPTED**

### Context
Scorva's core principle is: *"AI evaluates the evidence. Judges make the decisions."* If the platform automatically published AI scores as final competition rankings, organizers could face legal, ethical, and participant trust issues arising from hallucinations or biased models.

### Decision
1. Evaluation results produced by AI are classified as **Recommendations**, not final competition decisions.
2. Human judges inspect the AI assessment, along with cited evidence snippets and explanations.
3. Judges can submit a `judge_reviews` record:
   - Accept the AI score as-is.
   - Adjust individual criterion scores up or down with mandatory written rationale ($\ge 20$ characters).
   - Reject the evaluation and trigger an authorized retry.
4. The database stores both the original AI scores (`evaluation_results`) and the judge's adjusted scores (`judge_reviews` / `judge_criterion_scores`). Raw AI output is **never overwritten**.
5. Every judge adjustment transactionally writes an immutable audit record to `audit_events`.

### Consequences & Trade-Offs
- **Pros:** Guarantees human-in-the-loop accountability; preserves complete evidentiary trail; protects platform from algorithmic decision liability.
- **Cons:** Requires building judge review tables and UI review drawers.

---

## ADR-08: Prompt Injection Mitigation Strategy

### Status: **ACCEPTED**

### Context
Hackathon repositories contain untrusted user content (README, comments, commit messages) that may contain prompt injection attacks attempting to override rubric rules or force a 100/100 score.

### Decision
1. Treat all repository text strictly as untrusted data inputs.
2. Wrap evidence inside explicit structural boundary delimiters (`<UNTRUSTED_REPOSITORY_EVIDENCE>`).
3. Enforce model output strictly through Ollama JSON Schema grammar constraints (the model cannot output conversational text).
4. Enforce post-generation deterministic schema validation:
   - The model can only return scores for criteria IDs present in the frozen rubric.
   - Awarded scores outside $[min, max]$ are rejected or clamped.
   - The model has no access to final weights or total calculations.
5. Explicitly acknowledge that prompt engineering alone is not an absolute security boundary. Final authority rests with deterministic backend validators and human judges.

---

## ADR-09: Dedicated Encrypted Credential Entity vs. Ordinary Settings JSON

### Status: **ACCEPTED**

### Context
Storing organizer-supplied GitHub tokens inside `organizations.settings` JSONB introduces severe security vulnerabilities:
1. `organizations.settings` is returned in general administrative and tenant profile API responses, risking accidental token leakage to frontend clients.
2. PostgreSQL JSONB columns lack native field-level cryptographic protection at rest.
3. JSONB settings cannot enforce audit logging specific to credential rotation or lifecycle changes.
4. Mixing credentials with general tenant settings violates the principle of least privilege.

### Decision
1. **Strictly reject** storing raw credentials in `organizations.settings` JSON.
2. Introduce a dedicated table `organization_integrations` with columns:
   - `id`, `organization_id`, `provider` ('github'), `credential_type` ('pat' or 'github_app').
   - `encrypted_token`: BYTEA storing AES-256-GCM ciphertext encrypted using `ENCRYPTION_MASTER_KEY` via `apps.api.core.security.encrypt_value`.
   - `key_id`: Key version identifier ('master_v1') for cryptographic agility.
   - `token_preview`: Safe masked preview string (`ghp_****1234`).
   - `scopes`: JSONB array validating minimum fine-grained read permissions (`["contents:read", "metadata:read"]`).
   - `revoked_at`, `expires_at`, `last_used_at`.
3. Restrict management endpoints (`POST /integrations/github`, `DELETE /integrations/github/{id}`) strictly to `org_owner` and `org_admin`.
4. Emit transactional audit events: `INTEGRATION_CONFIGURED`, `INTEGRATION_TOKEN_ROTATED`, `INTEGRATION_REVOKED`.
5. Public repositories are ingested via platform-level anonymous/pooled rate-limited clients without requiring organizer tokens.

### Consequences & Trade-Offs
- **Pros:** Strong encryption at rest; zero accidental token exposure in settings endpoints; audit trail for credential rotation; clear separation of privilege.
- **Cons:** Requires a dedicated database table and credential encryption management service.

---

## ADR-10: Introduction of `judge` Role in Milestone 1 Migration & Event-Scoped ACL

### Status: **ACCEPTED**

### Context
In Phase 3 Milestone 4, `judge` was temporarily removed from frontend types because the backend `OrgRole` PostgreSQL enum only contained `('org_owner', 'org_admin', 'organizer')`. Phase 4 introduces judge review workflows, creating an architectural need for a consistent role and permission model.

### Decision
1. In Milestone 1 migration `0003_phase4_schema`, execute:
   ```sql
   ALTER TYPE org_role_enum ADD VALUE 'judge';
   ```
2. Update backend models (`apps/api/modules/organizations/models.py`) with `OrgRole.JUDGE = "judge"`.
3. Introduce an event-scoped mapping table `hackathon_judges (hackathon_id, user_id, assigned_by_user_id, created_at)` to allow scoping judges to specific hackathons within the tenant.
4. Establish separate FastAPI dependencies:
   - `require_org_organizer`: Accepts `org_owner`, `org_admin`, `organizer`. Used for submissions ingestion, evaluation dispatch, and rubric drafting.
   - `require_org_admin`: Accepts `org_owner`, `org_admin`. Used for rubric publishing and GitHub credential management.
   - `require_org_judge`: Accepts `org_owner`, `org_admin`, `organizer`, and `judge`. Used for viewing results and submitting human reviews.
5. In Milestone 6, restore `'judge'` to the frontend `OrgRole` type in `apps/web/src/types/api.ts`.

### Consequences & Trade-Offs
- **Pros:** Resolves the Phase 3 role inconsistency cleanly; enables least-privilege access for hackathon judges; prevents judges from modifying rubrics or triggering expensive jobs.
- **Cons:** Requires an Alembic enum migration and test updates for role authorization.

---

## ADR-11: Segmented Egress SSRF Policies (Public Web Egress vs. Configured Internal AI)

### Status: **ACCEPTED**

### Context
A global SSRF defense that blanket-blocks private IP ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`) breaks Ollama connectivity when Ollama runs on a local machine (`http://localhost:11434`) or on an internal Docker network bridge (`http://ollama:11434`). However, disabling private-address protection globally would allow attackers to submit repository URLs that target internal services or cloud metadata (`169.254.169.254`).

### Decision
Segment outbound network egress into two strictly isolated security profiles:
1. **Profile A: External Web Egress (GitHub Tarball Downloads):**
   - Untrusted input: repository URLs provided by users/organizers.
   - Destination allowlist: ONLY `api.github.com` and `codeload.github.com`.
   - DNS Pre-Resolution: Resolves hostname and asserts every IP is a public routable IP. Rejects RFC 1918, loopbacks, link-local, and cloud metadata (`169.254.169.254`).
   - Redirect handling: Maximum 3 redirects. Every redirect target MUST be `https://`, have a host matching `codeload.github.com`, and its resolved IP must be verified public before connection.
   - IP Pinning: Socket connects to pre-validated IP to eliminate DNS rebinding TOCTOU windows.
2. **Profile B: Internal Inference Egress (AI Providers / Ollama):**
   - Trusted configuration: Endpoint configured strictly via server environment variables (`settings.OLLAMA_BASE_URL`).
   - Destination allowlist: Host must match `ALLOWED_INTERNAL_AI_HOSTS = {"ollama", "localhost", "127.0.0.1"}`.
   - Zero Redirect Policy: Client sets `follow_redirects=False`. If an AI provider returns an HTTP redirect, it is aborted immediately.
   - Network isolation: Internal Docker bridge network without public ingress.
3. **Profile C: Default Deny:** All other outbound network requests are prohibited.

### Consequences & Trade-Offs
- **Pros:** Allows Ollama to run on private/Docker networks safely while maintaining impenetrable SSRF defenses against malicious repository downloads and external redirects.
- **Cons:** Requires maintaining two distinct HTTP client transport configurations in `ssrf_guard.py`.

---

## ADR-12: Preserving Historical Evaluation Attempts and Immutable Evidence Citations

### Status: **ACCEPTED**

### Context
When evaluation jobs fail or are retried by organizers, overwriting the previous evaluation record destroys diagnostic logs, timing history, and auditable proof of prior attempts. Furthermore, if LLM evidence citations are not verified against the actual repository tree, hallucinations could award credit for non-existent files.

### Decision
1. Retries do not delete historical attempts. `evaluation_results` includes `attempt_number` and is keyed by `(job_id, attempt_number)`.
2. `evaluation_jobs.current_result_id` tracks the authoritative active evaluation result.
3. Every citation in `evidence_references` is validated against the evaluated commit snapshot manifest:
   - Verifies `file_path` exists in the extracted repository.
   - Verifies `start_line <= end_line <= total_lines(file_path)`.
   - If a citation is invalid, it is marked `is_verified_in_repo = False` with `verification_failure_reason`.
4. Missing Evidence: If a project lacks code for a criterion, the system explicitly records `evidence_status = 'missing'`, clamps the score to `min_score`, and records `rationale = "NO_VERIFIABLE_EVIDENCE: Repository contains no automated tests or test configurations."` The system never fabricates scores.

### Consequences & Trade-Offs
- **Pros:** Full evidentiary and diagnostic audit trail; eliminates hallucinated citation credit; ensures fair scoring when evidence is absent.
- **Cons:** Slightly higher storage footprint due to retaining failed attempt records.

---

## ADR-13: Centralized Typed Configuration Service with Cascading Precedence and Point-in-Time Snapshots

### Status: **ACCEPTED**

### Context
Scorva previously relied on arbitrary JSON settings (`organizations.settings`) and hardcoded constants for platform behavior. This approach risked:
1. Undocumented, unvalidated keys causing runtime errors.
2. Silent corruption or tampering with critical security policies (e.g. archive limits, SSRF controls).
3. Ambiguous inheritance rules between platform defaults and tenant preferences.
4. Historical evaluation invalidation: if an organizer or Super Admin altered rubric scoring parameters or prompt templates after an event completed, recalculations or audits would yield inconsistent results.

### Decision
1. **Centralized Typed Service:** All platform configuration is managed via a strongly typed `ConfigurationService` using Pydantic schemas, explicit tier boundaries (Tiers 1 to 5), and strictly validated ranges.
2. **Dual-Path Resolution Separation:**
   - **Path A (Evaluation Configuration Mechanics):**
     $$\text{Queued Evaluation Config} = \text{Hackathon Override} \succ \text{Organization Override} \succ \text{Platform Setting} \succ \text{Safe Default}$$
     Overrides are restricted: Tier 1 (Super Admin only), Tier 2 (bounded Super Admin), Tier 3 (bounded tenant), Tier 4 (infrastructure env vars), Tier 5 (immutable security invariants).
   - **Path B (Live Authorization & Security):** Real-time permission evaluation based on active user roles, event assignments, and Tier 5 invariants. **Evaluation snapshots NEVER grant permissions or override access denials.**
3. **Point-in-Time Snapshotting:** When an evaluation job is queued, the resolved effective configuration is serialized into `submission_snapshots.configuration_snapshot` (JSONB). Historical evaluations evaluate against this snapshot forever, guaranteeing 100% reproducible scoring.
4. **Append-Only Rollback Semantics:**
   - Restoring a prior configuration creates a **NEW** version in `configuration_settings` and appends to `configuration_history` with `restored_from_version`.
   - Restored value is strictly re-validated against current schema bounds.
   - Enforces optimistic concurrency (`version` match) and never mutates historical evaluation snapshots.
5. **Optimistic Concurrency & Audit:** Settings updates require `version` matching (`HTTP 409 Conflict` on mismatch) and append every change to `configuration_history` with full diff and user attribution.
6. **Multi-Layer Cache Invalidation:** Updates publish to Redis channel `config:invalidated`, clearing L1 in-memory caches and L2 Redis caches across all nodes without downtime.

### Consequences & Trade-Offs
- **Pros:** 100% deterministic evaluation reproducibility; prevents silent security invariant weakening; provides complete auditability and instant rollback.
- **Cons:** Requires explicit schema definitions for all new configuration settings; slightly larger database storage per evaluation snapshot (~2KB JSONB).

---

## ADR-14: Granular Declarative RBAC Architecture vs. Hardcoded Role Strings

### Status: **ACCEPTED**

### Context
Phase 3 used hardcoded role strings (`require_platform_role("platform_owner")`, `require_org_role("org_admin")`). As Scorva expands to include evaluation pipelines, judge score adjustments, GitHub integrations, and participant self-service, hardcoded role checks become brittle, inflexible, and difficult to audit. Furthermore, tenant organizations require the ability to create customized roles (e.g. "Senior Judge", "Technical Lead") without deploying code changes.

### Decision
1. **Declarative Permission Matrix:** Replace hardcoded role checks with fine-grained permissions structured as `domain.action` (e.g., `evaluation.trigger`, `judge.override`, `participant.submission.create`, `rubric.publish`).
2. **Explicit Participant Support:** Include complete participant role, team association, and resource scoping (`ScopeType.RESOURCE`). Enforce team submission privacy and hard deadline enforcement (`now <= submission_deadline`).
3. **Dynamic Roles & Scoping:**
   - Roles are dynamic collections of permissions, assigned to users with an explicit scope (`platform`, `organization`, `hackathon`, or `resource`).
   - Default system roles (`platform_owner`, `platform_admin`, `org_owner`, `org_admin`, `organizer`, `judge`, `mentor`, `participant`) are seeded but permissions are evaluated dynamically.
4. **Least-Privilege Delegation Boundaries:**
   - An administrator cannot create a role or grant permissions that exceed their own effective permissions within that scope (`is_delegable = True` check).
   - Org Admins cannot grant Platform-level permissions or alter platform-wide roles.
5. **Lockout Protection:**
   - The system strictly blocks revocation, deletion, or deactivation of the last remaining Platform Owner user with `LAST_PLATFORM_OWNER_LOCKOUT` (`HTTP 400 Bad Request`) via atomic row-locked query.
6. **Multi-Layer Cache Invalidation & Bounded Staleness:**
   - 30-second upper-bound L1 memory cache TTL; 300-second L2 Redis cache TTL. Maximum staleness capped at 30 seconds even on total Pub/Sub failure.
   - Monotonic `user_perms_version:{user_id}` counter in Redis and PostgreSQL; auto-eviction on version mismatch.
   - Disconnected worker recovery (L1 flushed on reconnect); WebSocket per-frame re-verification.
   - Strict Auth Mode for sensitive operations (bypasses L1 cache).

### Consequences & Trade-Offs
- **Pros:** Maximum authorization flexibility for tenants; clean separation of privileges; self-documenting permission boundaries; protects against administrator lockout.
- **Cons:** Requires a join across permission tables or Redis permission cache lookups on authorized requests; slightly higher initial schema complexity (tables 4-7).

---

## ADR-15: 7-Milestone Phase 4 Roadmap with Dedicated Configuration & RBAC Foundation

### Status: **ACCEPTED**

### Context
Phase 4 encompasses complex systems: configuration services, dynamic RBAC, rubric authoring, GitHub ingestion, AI provider abstraction, Celery distributed execution, and frontend management dashboards. Attempting to build evaluation models before the configuration and permission systems are established would lead to schema churn, unvalidated mock configurations, and brittle role authorization retrofitting.

### Decision
Structure Phase 4 into 7 sequentially reviewable, test-verified milestones:
1. **Milestone 1:** Centralized Configuration & Dynamic RBAC Foundation (Schema Subsystems A & B: 7 streamlined tables, typed Pydantic models, cache invalidation, lockout protection).
2. **Milestone 2:** Domain Evaluation Data Foundation & Scoring Arithmetic (Schema Subsystem C: 15 tables including participant teams, Alembic migration 0004, deterministic `Decimal` calculator, rubric versioning).
3. **Milestone 3:** Safe GitHub Ingestion & Multi-Tenant Credential Store (SSRF Profile A, streaming extraction quota guards, AST tree classification, AES-256-GCM tokens).
4. **Milestone 4:** Provider-Neutral AI Engine & Structured Evidence Generation (SSRF Profile B, Ollama/Mock adapters, structural XML fencing, JSON Schema enforcement, prompt injection defense).
5. **Milestone 5:** Celery Worker Orchestration, Fencing & Asynchronous Pipeline (Renewable Redis leases, CAS monotonic version fencing, heartbeat reaper, retry backoff).
6. **Milestone 6:** Tenant Lifecycle APIs, Granular Authorization & Judge Overrides (Participant APIs, judge score adjustment contracts with $\ge 20$ char justification, evaluation audit events).
7. **Milestone 7:** Frontend Integration, Super Admin Dashboards & Judge Workspace (Next.js admin interfaces for Configuration, Dynamic Roles, AI Operations, and Judge Evaluation review).

### Consequences & Trade-Offs
- **Pros:** Each milestone is self-contained, reviewable, and fully covered by unit/integration tests before downstream features depend on it; decouples security mechanics from scoring logic.
- **Cons:** Requires strict milestone discipline and verification gates before proceeding between phases.

---

## ADR-16: IP Pinning Network Transport and Streaming Quota Sandboxing for Repository Ingestion

### Status: **ACCEPTED**

### Context
SSRF protections that only validate IP addresses at the DNS resolution stage are vulnerable to DNS Rebinding TOCTOU (Time-of-Check to Time-of-Use) attacks, where a malicious DNS server returns a legitimate public IP during validation but subsequently returns a local/metadata IP (e.g., `169.254.169.254` or `127.0.0.1`) during the actual HTTP connection. Furthermore, handling untrusted archives presents severe risks of decompression bombs (zip bombs), path traversal (ZipSlip), and special file escapes (symlinks/FIFOs).

### Decision
1. **IP Pinning Transport (`PinnedAsyncHTTPTransport`):**
   - Implemented a custom `AsyncNetworkBackend` for `httpcore` that binds socket connections directly to the pre-validated public IP address (`anyio.connect_tcp(pinned_ip, port)`).
   - Completely closes the DNS rebinding TOCTOU window while preserving standard TLS SNI host verification for `*.github.com`.
2. **Deterministic Six-Fold Quota Guards:**
   - Implemented strict streaming decompression caps: 50MB compressed, 250MB uncompressed, 10MB single file, 2,000 files, directory depth 10, path length 255 characters.
   - Any breach immediately aborts decompression with `QuotaExceededError`.
3. **Anti-ZipSlip & Special File Defense:**
   - Evaluates `member_path.is_relative_to(target_directory)` for every entry.
   - Strictly rejects all symlinks, hardlinks, character/block devices, and FIFOs.
4. **Static Evidence Indexing & Secret Masking:**
   - Performs zero code execution during extraction and analysis.
   - Categorizes files into taxonomies (`documentation`, `build_config`, `test_suites`, `source_code`).
   - Automatically excludes secret files (`.env*`, `*.pem`, `id_rsa*`, `credentials.json`, `.git/`, `node_modules/`, `venv/`).
   - Redacts high-entropy secrets (GitHub tokens, AWS keys, API keys, JWTs, passwords) from code snippets and wraps evidence in structural XML delimiters (`<UNTRUSTED_REPOSITORY_EVIDENCE>`).

### Consequences & Trade-Offs
- **Pros:** Impregnable SSRF protection against DNS rebinding; provably safe sandbox isolation against malicious archives; complete secret hygiene prior to prompt assembly.
- **Cons:** Custom transport overrides internal connection logic in `httpcore`.

---

## 5. Architectural Decisions Made vs. Decisions Requiring Product Approval

### 5.1 Architectural Decisions Made (Technical Foundation Established)

| Decision | Selected Architecture | Justification |
|---|---|---|
| **Code Execution Model** | Zero-Code-Execution (Static analysis only) | Completely eliminates RCE risk; microVM sandboxing deferred to Phase 5. |
| **Dual-Path Resolution** | Path A (Evaluation Config Snapshot) vs. Path B (Live Authorization) | Prevents evaluation snapshots from granting permissions or overriding live security revocations. |
| **Streamlined Database Design** | 9 tables in Milestone 1 (3 Config, 6 RBAC/Outbox); 15 tables in Milestone 2 | Eliminates `user_effective_permissions` table (prevents drift); eliminates duplicate rollback/lock tables. |
| **Delegation Policy** | Super Admin controls `is_delegable` and setting override envelopes | Enforces least-privilege ceiling; prevents vertical escalation by tenant admins. |
| **Two-Phase Safeguards** | Config-update validation + hardcoded absolute runtime ceilings | Prevents Super Admin from weakening traversal, unsafe-file, or zero-code protections. |
| **Rollback Semantics** | Append-only new version `v_new` with re-validation and optimistic concurrency | Preserves full audit history; prevents race conditions; leaves past snapshots untouched. |
| **Cache Invalidation & Durability** | Transactional outbox + 30s L1 TTL + monotonic DB version + Strict Auth Mode | Guarantees bounded staleness ($\le 30$s) even if Pub/Sub dropped; authoritative check for sensitive ops. |
| **Lockout Protection Serialization** | `pg_advisory_xact_lock` + `roles WHERE name = 'platform_owner' FOR UPDATE` | Strictly serializes concurrent demotion/deletion transactions; eliminates invalid aggregate FOR UPDATE. |
| **Rubric & Snapshot Immutability Triggers** | `d630cee07d82`: `trg_rubric_criteria_immutable`, `trg_rubric_versions_protect`, `trg_submission_snapshots_immutable` | Eliminates reparenting, unpublishing, cascade deletion, and snapshot mutation vectors at the database level. |
| **Foreign Key Constraint Enforcement** | `fk_evaluation_jobs_current_result_id` (ON DELETE SET NULL) | Enforces database-level referential integrity between evaluation jobs and results. |
| **Publication Concurrency Serialization** | `SELECT ... FOR UPDATE` on `RubricVersion` and criteria + `FOR SHARE` in DB trigger | Eliminates publication weight-sum race condition without deadlocks. |
| **Migration Strategy** | Real Alembic branch from verified head `de1a35a5cc94` with DDL string constraints | Preserves 100% reversible migrations without PostgreSQL enum transaction lock issues. |
| **Durable Audit Trail** | Transactional emission to immutable `audit_events` with diff payloads | Guaranteed accountability protected by `trg_audit_events_immutable` trigger. |
| **Worker Architecture** | Celery 5.4 with Redis & Sync SQLAlchemy engine | Isolates heavy workloads; prevents event-loop conflicts. |
| **Credential Storage** | Dedicated `organization_integrations` with AES-256-GCM | Rejects raw tokens in settings JSON; provides field encryption and auditability. |
| **Role Architecture** | `judge` and `participant` roles with granular permission mappings | Resolves enum gap; explicitly models judging and participant team lifecycles. |
| **SSRF Policy** | Segmented Profile A (Public GitHub) & Profile B (Internal Ollama) | Safely connects to local Ollama while blocking SSRF/metadata access on downloads. |
| **Worker Leases & Fencing** | 60s Redis lease + CAS `lock_version` check | Prevents zombie workers from writing stale results or duplicate evaluations. |

### 5.2 Decisions Still Requiring Product Owner Approval

The following specific design decisions require product owner confirmation before implementation:

1. **Default Rubric Scoring Mode:**
   - *Option A (Recommended):* `offset_normalized` ($\sum w_i \times \frac{s_i - min_i}{max_i - min_i} \times 100$). Ensures minimum score awards $0\%$ and maximum awards $100\%$.
   - *Option B:* `raw_proportional` ($\sum w_i \times \frac{s_i}{max_i} \times 100$). Awards proportional points regardless of minimum score.
   - *Recommendation:* Support both on the Rubric model, defaulting to Option A whenever $min_i > 0$. **Requires Product Owner Signoff.**

2. **GitHub App Organization Installation vs. Personal Access Tokens (PAT):**
   - *Phase 4 Proposal:* Smallest viable secure design implements Fine-Grained Personal Access Tokens (PATs) stored in `organization_integrations`. Full GitHub App manifest installation flow deferred to Phase 5.
   - *Recommendation:* Confirm that organizer-supplied fine-grained PATs (`contents:read`, `metadata:read`) satisfy Phase 4 pilot requirements. **Requires Product Owner Signoff.**

3. **Minimum Rationale Character Threshold for Judge Overrides:**
   - *Proposal:* Require judges to provide at least 20 characters of written explanation when altering an AI criterion score.
   - *Recommendation:* 20 characters prevents accidental single-character overrides while remaining fast for judges. **Requires Product Owner Signoff.**

4. **Tenant Concurrency Limits:**
   - *Proposal:* Default concurrency cap of 3 active evaluation jobs per organization.
   - *Recommendation:* Prevents queue monopolization while allowing rapid evaluation of small batches. **Requires Product Owner Signoff.**

5. **Dynamic Role Deletion Policy:**
   - *Option A (Recommended):* Prohibit deletion (`RESTRICT`) of any role that currently has active user assignments; administrator must reassign users first.
   - *Option B:* Cascade deletion of role assignments with immediate cache eviction.
   - *Recommendation:* Option A prevents accidental loss of user access. **Requires Product Owner Signoff.**

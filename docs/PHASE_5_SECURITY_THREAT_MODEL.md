# Scorva Phase 4 Milestone 5 — Security Threat Model & Defense In Depth
## Celery Evaluation Orchestrator, Worker Leases & Distributed Fault Tolerance

**Document Version:** 1.0  
**Date:** October 26, 2026  
**Status:** **PLANNING ONLY — STRICTLY AUTHORIZED FOR PLANNING & THREAT MODELING**  
**Milestone 5 Implementation Status:** **BLOCKED & UNAUTHORIZED**  
**Author:** Lead Application Security Architect & Distributed Systems Reviewer  
**Reference Invariants:** `docs/PHASE_4_SECURITY_THREAT_MODEL.md`, `docs/PHASE_4_M4_POST_REMEDIATION_READ_ONLY_AUDIT.md`

---

## 1. Executive Summary & Security Posture

Milestone 5 introduces asynchronous worker processes, message queues, distributed leases, and background task execution into Scorva. While asynchronous execution isolates the Web API from heavy computational workloads, it introduces new attack surfaces:
- **Broker and Queue Tampering:** Risks of forged task messages, message replay, and queue poisoning.
- **Distributed Concurrency Vulnerabilities:** Risks of zombie workers, race conditions, torn writes, and stale results.
- **Tenant Context Pollution:** Risks of cross-tenant job substitution or worker process contamination.
- **Denial of Service (DoS):** Queue flooding, retry storms, and resource exhaustion across CPU, memory, and LLM inference.

The foundational security doctrine for Milestone 5 is:
> **The message broker is a transport channel, not a security boundary. Workers must never trust task messages as authoritative state. Storage-enforced monotonic fencing tokens and atomic transactions govern state mutations, not ephemeral distributed locks.**

---

## 2. Asset Registry & Trust Boundaries

### 2.1 Critical Asset Registry (Milestone 5 Focus)

| Asset ID | Asset Description | Confidentiality | Integrity | Availability |
|---|---|:---:|:---:|:---:|
| **A-01** | **Evaluation Result Legitimacy** (Official scores and ranks awarded to submissions) | High | Critical | High |
| **A-02** | **Multi-Tenant State Isolation** (Submissions, Rubrics, Jobs across organizations) | Critical | Critical | High |
| **A-03** | **Encrypted Credential Vault** (GitHub PATs, App tokens, DB connection strings) | Critical | Critical | Critical |
| **A-04** | **Worker Computational Capacity** (Worker CPU, RAM, scratch disk storage) | Low | High | Critical |
| **A-05** | **AI Inference Resource Quotas** (Ollama GPU compute, concurrency bounds) | Low | High | Critical |
| **A-06** | **Authoritative State Machine** (`evaluation_jobs` status, attempts, audit trail) | Medium | Critical | High |

### 2.2 Extended Trust Boundaries

```
[ UNTRUSTED EXTERNAL ZONE ]
   • Public / Private GitHub Repositories (Code, README, Tarballs)
   • Untrusted LLM Provider Completions
---------------------------------------------------------------------- [ Boundary 1: API Gateway & Auth ]
[ WEB APPLICATION PLANE ]
   • FastAPI Monolith & Scoped User Session Context
   • Dynamic RBAC Authorization Layer (`require_permission`)
---------------------------------------------------------------------- [ Boundary 2: Outbox & Persistence ]
[ STORAGE & BROKER TIER ]
   • PostgreSQL 16 Primary DB (ACID Transactions & Foreign Keys)
   • Redis 7 Instance (Celery Message Queues & Semaphores)
---------------------------------------------------------------------- [ Boundary 3: Worker Task Dispatch ]
[ ASYNCHRONOUS WORKER PLANE ]
   • Celery Worker Processes (Sandboxed Static Execution)
   • Local Scratch Filesystem (`/tmp/scorva/eval_xxxx`)
---------------------------------------------------------------------- [ Boundary 4: Egress Control ]
[ EGRESS CONTROL PLANE ]
   • Profile A Public SSRF Guard (GitHub API & Codeload only)
   • Profile B Internal SSRF Guard (Pinned Ollama Host & Port only)
```

---

## 3. STRIDE Threat Analysis Matrix

| Threat Category | Specific Threat in Milestone 5 | Severity | Primary Mitigation |
| :--- | :--- | :---: | :--- |
| **Spoofing** | Forged Celery task injected into Redis queue | High | Lean task payloads; worker rehydrates authoritative DB state; DB-level tenant verification. |
| **Tampering** | Stale worker overwriting newer evaluation results | Critical | Storage-enforced monotonic fencing tokens (`lock_version`) in atomic commit transaction. |
| **Repudiation** | Untracked job cancellation, retry, or worker claim | Medium | Immutable append-only audit log records (`audit_events`) committed with every state change. |
| **Information Disclosure** | Sensitive credentials or code leaked in worker logs or exceptions | Critical | Automated regex secret masking, exception message sanitization, and suppression of raw prompt logging. |
| **Denial of Service** | Queue flooding, runaway inference, or retry storms | High | Tenant concurrency throttling (Redis semaphores), max attempts ceiling, and bounded task time limits. |
| **Elevation of Privilege** | Cross-tenant job-ID manipulation | Critical | Mandatory organization scoping on all SQL queries (`WHERE organization_id = :org_id`). |

---

## 4. Deep Threat Analysis: The 12 Milestone 5 Threats

### Threat 01: Cross-Tenant Job-ID Substitution
- **Attack Preconditions:** Attacker has an authenticated account in Tenant A. Attacker obtains or guesses an `evaluation_job_id` belonging to Tenant B.
- **Attack Vector:** Attacker sends a request (or crafts a task message) attempting to trigger, cancel, retry, or inspect Tenant B's job using Tenant A's session.
- **Blast Radius / Impact:** Unauthorized viewing, cancellation, or tampering with another organization's hackathon evaluation.
- **Technical Mitigations:**
  1. All database queries for evaluation jobs include mandatory tenant scoping:
     ```sql
     SELECT * FROM evaluation_jobs 
     WHERE id = :job_id AND organization_id = :authenticated_org_id;
     ```
  2. Workers verify that `submission.organization_id == snapshot.organization_id == rubric_version.organization_id == job.organization_id`. Mismatches abort with `TENANT_ISOLATION_VIOLATION`.
- **Residual Risk:** Negligible. Enforced at SQL query level and relational foreign keys.
- **Verification Test Reference:** `test_evaluation_tenant_isolation.py::test_cross_tenant_job_id_substitution_rejected`.

---

### Threat 02: Forged or Replayed Celery Task Messages
- **Attack Preconditions:** An attacker gains access to the Redis broker port or exploits a Redis injection vulnerability to insert arbitrary messages into Celery's task queue (`LPUSH celery:evaluations.default`).
- **Attack Vector:** Attacker crafts a message with a fabricated `job_id`, fake repository URL, or altered rubric criteria to trick the worker into executing malicious instructions.
- **Blast Radius / Impact:** Evaluation of unauthorized repositories or execution of arbitrary configuration.
- **Technical Mitigations:**
  1. **Zero-Trust Task Payloads:** Celery task messages carry ONLY `job_id`. They contain no URLs, tokens, code, or configuration.
  2. **Authoritative Database Validation:** Upon receiving `job_id`, the worker executes `SELECT ... FROM evaluation_jobs WHERE id = :job_id`. If the ID does not exist in PostgreSQL or is not in `queued` status, the message is immediately dropped and an audit alert is triggered.
  3. **No Dynamic Execution:** Worker performs static analysis only; no code execution is ever permitted.
- **Residual Risk:** Low. An attacker with full Redis write access can trigger processing of already-queued legitimate jobs, but cannot alter the job parameters or inject unauthorized payloads.
- **Verification Test Reference:** `test_evaluation_orchestration.py::test_forged_celery_task_payload_ignored`.

---

### Threat 03: Unauthorized Task Dispatch
- **Attack Preconditions:** Non-administrative user (e.g. participant or unprivileged judge) attempts to trigger evaluation jobs.
- **Attack Vector:** Attacker calls `POST /api/v1/organizations/{id}/evaluations` without proper role assignment.
- **Blast Radius / Impact:** Resource exhaustion, premature evaluation before submission finalization.
- **Technical Mitigations:**
  1. API endpoint strictly guarded by dynamic RBAC: `require_permission("evaluation.dispatch", scope=Scope.HACKATHON)`.
  2. Participants are explicitly denied `evaluation.dispatch`.
  3. Pre-flight check verifies hackathon submission deadline has passed before batch dispatch.
- **Residual Risk:** None. Enforced by live RBAC dynamic engine verified in M1.
- **Verification Test Reference:** `test_judge_permissions.py::test_participant_and_judge_cannot_dispatch_evaluations`.

---

### Threat 04: Stale Workers Attempting Result Writes (Zombie Worker Problem)
- **Attack Preconditions:** Worker 1 claims Job A, enters a prolonged GC/network pause exceeding its lease TTL (60s). Reaper resets Job A to `queued`. Worker 2 claims Job A, executes, and commits result. Worker 1 resumes.
- **Attack Vector:** Worker 1 attempts to write its obsolete evaluation result to `evaluation_results` and mark Job A `completed`.
- **Blast Radius / Impact:** Result corruption, race conditions, overwritten scores, non-deterministic evaluation outcomes.
- **Technical Mitigations:**
  1. **Storage-Enforced Monotonic Fencing Tokens:** Every job has `lock_version INTEGER NOT NULL DEFAULT 0`.
  2. When Worker 2 claims the job, `lock_version` increments from 1 to 2.
  3. Worker 1's commit transaction executes:
     ```sql
     UPDATE evaluation_jobs 
     SET status = 'completed', lock_version = lock_version + 1
     WHERE id = :job_id AND claim_token = :w1_token AND lock_version = 1;
     ```
  4. The query updates 0 rows. Worker 1 detects `rowcount == 0`, immediately rolls back its transaction, and terminates cleanly without persisting child rows.
- **Residual Risk:** Zero. Guaranteed by PostgreSQL row-level locks and ACID transaction semantics.
- **Verification Test Reference:** `test_worker_leases.py::test_stale_worker_fenced_from_committing_results`.

---

### Threat 05: Duplicate Task Execution
- **Attack Preconditions:** Network timeout during broker acknowledgment (`task_acks_late = True`) causes Redis to redeliver a task message after a worker has already started or completed processing.
- **Attack Vector:** Multiple workers attempt to process the exact same job concurrently.
- **Blast Radius / Impact:** Duplicate compute expenditure, duplicate rows in `evaluation_results`, duplicate scoring.
- **Technical Mitigations:**
  1. **Atomic SQL Claim:** Worker must transition status from `queued` to `running`:
     ```sql
     UPDATE evaluation_jobs 
     SET status = 'running', claim_token = :token, lock_version = lock_version + 1
     WHERE id = :job_id AND status = 'queued';
     ```
     Only the first worker updates 1 row; all duplicate deliveries update 0 rows and immediately exit (`return`).
  2. **Database Constraint:** `evaluation_results` has `UNIQUE (job_id, attempt_number)`, physically preventing duplicate result records for the same attempt.
- **Residual Risk:** Negligible. At-least-once delivery is safely converted to idempotent execution.
- **Verification Test Reference:** `test_evaluation_orchestration.py::test_duplicate_task_delivery_idempotency`.

---

### Threat 06: Poisoned or Malicious Repository Evidence
- **Attack Preconditions:** Malicious hackathon participant includes path traversal filenames (`../../etc/shadow`), symlinks to host devices, 50GB zip bombs, or XML delimiter injection strings in their repository code or README.
- **Attack Vector:** Exploits worker file extraction, evidence indexing, or prompt assembly to compromise the worker environment.
- **Blast Radius / Impact:** Host filesystem overwrite, arbitrary file disclosure, memory exhaustion, or model jailbreak.
- **Technical Mitigations:**
  1. **M3 Static Extractor Boundaries:** Zero code execution, `Path.is_relative_to` path containment, hard limits (1000 files, 50MB compressed / 250MB uncompressed), zero symlinks/FIFOs.
  2. **M3 XML Evidence Indexer:** Snippets and paths sanitized with XML 1.0 illegal control character stripping and attribute escaping.
  3. **M4 Prompt Containment:** System prompt instructions strictly isolated from evidence XML containers.
  4. **M4 Downstream Output Validator:** Compelled Pydantic schema validation, bounds checks, and line citation verification block compromised outputs.
- **Residual Risk:** Residual LLM compliance variance handled by deterministic downstream validation and human judge oversight (ADR-07, ADR-08).
- **Verification Test Reference:** `test_prompt_injection_resilience.py` (24 vectors passing) + `test_github_client.py` (archive security).

---

### Threat 07: SSRF-Policy Bypass Through Alternate Provider Paths
- **Attack Preconditions:** An attacker tampers with worker runtime configuration or attempts to supply an arbitrary provider URL (`http://169.254.169.254/latest/meta-data` or `http://localhost:5432`).
- **Attack Vector:** Worker attempts to reach internal databases or cloud metadata services during model evaluation.
- **Blast Radius / Impact:** Exfiltration of AWS IAM role credentials, database credential probing, internal network scanning.
- **Technical Mitigations:**
  1. Workers instantiate `OllamaProviderClient` exclusively through the approved factory [`get_ai_provider_client`](file:///home/shubh/scorva/apps/api/modules/evaluations/ai_provider.py).
  2. **Profile B SSRF Guard:** Hostname allowlist (`ALLOWED_INTERNAL_AI_HOSTS`), port bounding (`ALLOWED_INTERNAL_AI_PORTS = {11434, 443}`), forbidden internal ports (5432, 6379, 22), socket-level redirect rejection (`follow_redirects=False`), and IP pinning via `PinnedAsyncNetworkBackend`.
  3. No custom provider URLs are accepted from request bodies or repository evidence.
- **Residual Risk:** Zero. Verified against live TCP sockets in Milestone 4 audit.
- **Verification Test Reference:** `test_ssrf_guard.py::test_profile_b_internal_ai_endpoint_validation`.

---

### Threat 08: Secret Leakage in Exception Messages, Task Payloads, or Logs
- **Attack Preconditions:** Pipeline fails due to an invalid token, GitHub connection drop, or database constraint violation.
- **Attack Vector:** Sensitive tokens (GitHub PATs, database passwords, API secrets) are printed in plaintext traceback logs, Celery task failure payloads, or error response strings.
- **Blast Radius / Impact:** Secret exposure to centralized log aggregators (Elasticsearch, Datadog) or developers.
- **Technical Mitigations:**
  1. **Hierarchical Exception Masking:** [`AIProviderError`](file:///home/shubh/scorva/apps/api/modules/evaluations/ai_provider.py#L33-L82) subclasses sanitize messages; raw internal URLs and auth headers are stripped before raising.
  2. **Regex Log Filter:** Custom logging filter redacts patterns matching `ghp_[A-Za-z0-9_]{36}`, `sk-[A-Za-z0-9_]{48}`, `postgresql://.*@`, and bearer tokens.
  3. Task failure payloads stored in `evaluation_jobs.error_message` contain standardized error codes, not raw stack traces.
- **Residual Risk:** Low. Automated redacting active across all worker logs.
- **Verification Test Reference:** `test_ai_provider.py::test_secret_masking_in_error_payloads`.

---

### Threat 09: Broker Compromise or Unauthorized Message Publication
- **Attack Preconditions:** Network compromise allows unauthorized clients to connect to Redis port 6379.
- **Attack Vector:** Attacker reads task messages from Redis or writes rogue messages.
- **Blast Radius / Impact:** Queue disruption, snooping on job IDs.
- **Technical Mitigations:**
  1. Redis requires strong password authentication (`REDIS_URL` in `.env`).
  2. In production, Redis binds exclusively to internal Docker / VPC network interfaces (`127.0.0.1` or private subnet), never exposed to public internet.
  3. As established in Threat 02, task messages contain only `job_id`; snooping Redis reveals no repository code, credentials, or evaluation results.
- **Residual Risk:** Low. Protected by network perimeter and zero-trust payload design.
- **Verification Test Reference:** `test_evaluation_orchestration.py::test_redis_broker_network_isolation`.

---

### Threat 10: Denial of Service via Queue Flooding, Retries, or Runaway Inference
- **Attack Preconditions:** Malicious tenant submits 10,000 evaluation requests simultaneously or crafts a repository that causes LLM inference to hang indefinitely.
- **Attack Vector:** Worker pool exhaustion, starving other tenants of evaluation resources.
- **Blast Radius / Impact:** Platform-wide outage, hackathon judging delays.
- **Technical Mitigations:**
  1. **Tenant Concurrency Semaphore:** Redis distributed semaphore limits each tenant to `eval.tenant_max_concurrent_jobs` (default: 3 active evaluations). Excess jobs remain in `queued` status.
  2. **Task Timeouts:** Hard timeout enforced by Celery (`time_limit = 360s`, `soft_time_limit = 300s`).
  3. **Inference Timeouts:** HTTP requests to Ollama bounded by `ai.evaluation_timeout_seconds` (default: 300s).
  4. **Retry Bounding:** Maximum 3 attempts per job; exponential backoff with full jitter prevents retry storms.
- **Residual Risk:** Medium. Bounded by worker concurrency capacity; autoscale worker instances if queue depth spikes.
- **Verification Test Reference:** `test_worker_concurrency_throttling.py::test_tenant_concurrency_limit_enforced`.

---

### Threat 11: Unauthorized Administrative Cancellation or Retry
- **Attack Preconditions:** Attacker attempts to cancel or retry an ongoing evaluation job without possessing organizational permissions.
- **Attack Vector:** Direct invocation of cancellation API.
- **Blast Radius / Impact:** Disruption of legitimate evaluation runs.
- **Technical Mitigations:**
  1. Guarded by dynamic RBAC: `require_permission("evaluation.cancel", scope=Scope.HACKATHON)`.
  2. Only Organization Owner, Admin, or Organizer can cancel jobs.
  3. Transactional audit log emitted (`action = "evaluation.cancelled"`).
- **Residual Risk:** None. Enforced by dynamic RBAC.
- **Verification Test Reference:** `test_evaluation_tenant_isolation.py::test_unauthorized_cancellation_rejected`.

---

### Threat 12: Worker and Database Privilege Boundaries
- **Attack Preconditions:** Attacker compromises a worker container or process through a zero-day dependency vulnerability.
- **Attack Vector:** Attacker attempts to leverage the worker's database connection to alter platform roles, drop tables, or access user passwords.
- **Blast Radius / Impact:** Database compromise, privilege escalation.
- **Technical Mitigations:**
  1. **Principle of Least Privilege:** Worker database role (`scorva_worker`) is granted `SELECT`, `INSERT`, `UPDATE` strictly on evaluation-related tables (`evaluation_jobs`, `evaluation_results`, `evaluation_criterion_scores`, `evidence_references`, `submissions`, `submission_snapshots`, `rubric_versions`, `rubric_criteria`, `audit_events`).
  2. Worker database user has `NO ACCESS` to `users.hashed_password`, `mfa_pending_tokens`, `roles`, or `permissions` tables.
  3. Database DDL permissions (schema migrations) are strictly restricted to the deployment pipeline, never granted to worker runtimes.
- **Residual Risk:** Low. Enforced by PostgreSQL role grants.
- **Verification Test Reference:** `test_worker_privilege_boundaries.py::test_worker_db_user_least_privilege`.

---

## 5. Security Invariant Verification Matrix

| Invariant | Enforcement Mechanism | Failure Mode | Verification Test Reference |
| :--- | :--- | :--- | :--- |
| **Monotonic Fencing** | `UPDATE ... WHERE lock_version = :ver` | 0 rows updated $\rightarrow$ Abort & Rollback | `test_worker_leases.py` |
| **Atomic Commit** | Single PostgreSQL ACID transaction | DB rollback $\rightarrow$ 0 partial results | `test_evaluation_orchestration.py` |
| **No Code Execution** | Static extractor only; no subshells | Immediate job failure | `test_github_client.py` |
| **Profile B SSRF** | Pinned transport & host allowlist | `SSRFViolationError` (Terminal) | `test_ssrf_guard.py` |
| **Deterministic Math** | Python `Decimal(ROUND_HALF_UP)` | Rejects non-finite & weight drift | `test_scoring_calculator.py` |
| **Tenant Scoping** | `WHERE organization_id = :org_id` | HTTP 404 / 403 / Query empty | `test_evaluation_tenant_isolation.py` |

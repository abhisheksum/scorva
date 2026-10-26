# Scorva — Phase 2 Security Review & Verification Gate

**Document Version:** 2.0 (Final Security Closure)  
**Date:** October 25, 2026  
**Status:** **APPROVED FOR PHASE 3 READINESS**  
**Scope:** Phase 2 (Authentication, Sessions, MFA, Platform RBAC, Audit Logging, and Multi-Worker Outage Resilience)

---

## 1. Executive Summary & Security Gate Decision

A comprehensive, adversarial security review and closure analysis was performed on the Phase 2 implementation of the Scorva Super Admin platform. All reported claims were independently reproduced and verified against the actual running PostgreSQL database, Redis broker, FastAPI backend API, and Next.js frontend web application.

### Gate Decision: **PASSED (ALL CRITERIA SATISFIED)**

- **57 Backend Automated Tests:** 100% PASSING (including 14 dedicated security gate, multi-worker simulation, and outage resilience tests).
- **Clean Database Migration:** Verified clean schema upgrade, table/trigger verification, and complete downgrade cycle against an entirely fresh PostgreSQL instance.
- **Frontend Verification:** TypeScript compiler checks (`tsc --noEmit`) and optimized production build (`next build`, 17 static pages) pass with 0 errors.
- **Production Guardrails:** Insecure development default keys, weak secrets, debug mode, and unencrypted cookies are systematically rejected at startup when `SCORVA_ENV=production`.
- **Multi-Worker Redis Outage Resilience:** Replaced process-local memory fallback with a globally consistent, durable PostgreSQL fallback mechanism for rate limiting, TOTP replay protection, and MFA ephemeral challenge tokens. Verified with simulated multi-worker concurrency tests.

---

## 2. Investigation of Redis Outage Behavior & Multi-Worker Architecture

### 2.1 The Vulnerability of Process-Local In-Memory Fallbacks

An in-depth architectural audit of fallback mechanisms during a Redis outage identified a critical security limitation with process-local stores (`dict` / `_memory_store`):

1. **Process Isolation in Multi-Worker Deployments:**
   - In production, FastAPI runs across multiple worker processes (e.g., Uvicorn workers behind Gunicorn, or multiple container replicas behind a load balancer).
   - An in-memory fallback dictionary resides exclusively in the private heap memory of an individual OS process.
2. **Rate Limit Multiplier Exploit:**
   - If an API cluster runs $N$ worker processes with a process-local fallback, an attacker distributing brute-force authentication requests across workers can execute up to $N \times \text{max\_attempts}$ before being throttled.
3. **TOTP Replay Window Exploit:**
   - If Worker 1 verifies and accepts a 6-digit TOTP code and marks it in its local memory, Worker 2 remains completely unaware of that event.
   - An attacker intercepting or replaying the valid TOTP code within its 90-second validity window could authenticate against Worker 2 without being detected.
4. **MFA Challenge Token Dropping:**
   - A multi-step login flow (Step 1: password check issuing challenge token; Step 2: TOTP check consuming challenge token) fails if Step 1 and Step 2 hit different workers, causing legitimate users to be rejected with `SESSION_NOT_FOUND`.

### 2.2 Solution: Durable, Cross-Worker PostgreSQL Fallback

To ensure state remains globally consistent across all workers and instances even when Redis is down, durable database fallback tables were introduced via Alembic migration `89e5bd9e37a3_add_security_fallback_tables`:

- **`totp_replay_prevention`**: Stores `(user_id, code, expires_at)` with composite primary key `(user_id, code)`.
  - Enforced via atomic `INSERT ... ON CONFLICT (user_id, code) DO NOTHING`.
  - If `rowcount == 0`, the code has already been consumed by any worker, immediately rejecting replays across the entire fleet.
- **`rate_limit_buckets`**: Stores `(key, attempts, window_start, expires_at)`.
  - Enforced via atomic `INSERT ... ON CONFLICT (key) DO UPDATE` returning current aggregated attempts and remaining TTL.
  - Guarantees brute-force limits are globally synchronized across all worker processes.
- **`mfa_pending_tokens`**: Stores `(token, token_type, user_id, data, expires_at)`.
  - Enables temporary challenge and enrollment tokens to be shared across workers, ensuring seamless multi-step authentication under Redis outages.

### 2.3 Safe Failure Policy & Availability-versus-Security Trade-Off

When designing resilient authentication systems, a deliberate choice must be made between **availability** and **security** during catastrophic double-outages:

| Outage Scenario | System Behavior | Security Posture | Availability Posture |
|---|---|---|---|
| **Normal Operations** (Redis + PostgreSQL Healthy) | Fast-path Redis caching (<1ms) for sessions, rate limits, and TOTP replay protection. PostgreSQL serves as system of record. | Maximum | Maximum |
| **Redis Outage** (PostgreSQL Healthy) | Circuit-breaker falls back to PostgreSQL atomic fallback tables (`rate_limit_buckets`, `totp_replay_prevention`, `mfa_pending_tokens`). | **Maximum (Guaranteed globally consistent across all workers)** | High (Minimal latency increase from indexed DB transactions) |
| **Total Storage Outage** (Redis Down + PostgreSQL Down) | **Fail-Closed Policy:** Rate limiter rejects requests (`allowed=False, remaining=0`). TOTP verification aborts with `HTTP 503 Service Unavailable`. | **Maximum (Prevents unthrottled brute-force attacks and token replay)** | Degraded (Protected actions fail until database health recovers) |

> [!IMPORTANT]
> **Availability-versus-Security Decision:**
> Scorva strictly chooses **security over fail-open availability**. In the event of a catastrophic double partition where both Redis and PostgreSQL are unreachable, the platform intentionally refuses authentication requests (503 Service Unavailable) rather than allowing unthrottled credential stuffing or unverified TOTP logins.

---

## 3. Security Review Findings and Resolved Defects

| ID | Finding Description | Severity | Status | Resolution Summary |
|---|---|---|---|---|
| **SEC-01** | **Startup Script Allowed Continuation on Migration Failure:** `scripts/start.sh` used `|| log_warn` when running Alembic migrations, allowing the backend to start up against an unmigrated or corrupted database schema. | **HIGH** | **RESOLVED** | Modified [`scripts/start.sh`](file:///home/shubh/scorva/scripts/start.sh) to strictly check exit code and abort startup (`exit 1`) if Alembic migrations fail. |
| **SEC-02** | **Production Startup Did Not Reject Development Defaults:** Default development values for `SECRET_KEY`, `ENCRYPTION_MASTER_KEY`, `DATABASE_URL`, and `SESSION_COOKIE_SECURE=False` were not validated on startup. | **HIGH** | **RESOLVED** | Added `@model_validator(mode="after")` in [`apps/api/config.py`](file:///home/shubh/scorva/apps/api/config.py) strictly enforcing length, non-default strings, `SESSION_COOKIE_SECURE=True`, and `DEBUG=False` when `SCORVA_ENV=production`. |
| **SEC-03** | **Hardcoded Passwords & Shared Static TOTP Secrets in Seeding:** `apps/api/scripts/seed_admin.py` used static passwords (`Password123!`) and shared the identical static TOTP secret (`JBSWY3DPEHPK3PXP`) across multiple accounts. | **HIGH** | **RESOLVED** | Refactored [`apps/api/scripts/seed_admin.py`](file:///home/shubh/scorva/apps/api/scripts/seed_admin.py): `--dev-defaults` is strictly forbidden in production; production requires explicit environment variables or generates random CSPRNG passwords and unique random TOTP secrets per account. |
| **SEC-04** | **Proactive Session Cache Invalidation on Revocation:** While PostgreSQL correctly revoked sessions, Redis keys were only evicted lazily on subsequent requests. | **MEDIUM** | **RESOLVED** | Updated [`apps/api/modules/users/router.py`](file:///home/shubh/scorva/apps/api/modules/users/router.py) to proactively query and delete all active session hashes from Redis immediately upon role change, account suspension, or session revocation. |
| **SEC-05** | **Alembic env.py Overwrote Dynamic Database URLs:** `apps/api/alembic/env.py` unconditionally overwrote `config.set_main_option("sqlalchemy.url")`, preventing programmatic migration testing against clean test databases. | **LOW** | **RESOLVED** | Updated [`apps/api/alembic/env.py`](file:///home/shubh/scorva/apps/api/alembic/env.py) to respect explicit database URL overrides while falling back to `settings.DATABASE_URL` by default. |
| **SEC-06** | **Process-Local Memory Fallback in Multi-Worker Setup:** Rate limiting and TOTP replay protection used in-memory dictionary during Redis outages, allowing quota multiplication and TOTP replay across different worker processes. | **HIGH** | **RESOLVED** | Created fallback tables `totp_replay_prevention`, `rate_limit_buckets`, and `mfa_pending_tokens` via migration `89e5bd9e37a3`. Updated [`apps/api/core/redis.py`](file:///home/shubh/scorva/apps/api/core/redis.py) with atomic database UPSERT fallbacks and fail-closed error handling. |

---

## 4. Security Verification Results

All tests executed with complete isolation and passing status:

| Security Check / Requirement | Status | Verification Method |
|---|---|---|
| **Production Configuration Validation** | **PASS** | [`test_production_settings_rejects_insecure_defaults`](file:///home/shubh/scorva/apps/api/tests/test_security_gate.py#L52-L109) |
| **Valid Production Configuration Acceptance** | **PASS** | [`test_production_settings_valid_configuration_succeeds`](file:///home/shubh/scorva/apps/api/tests/test_security_gate.py#L110-L125) |
| **Production Seeding Guardrails** | **PASS** | [`test_seed_development_presets_forbidden_in_production`](file:///home/shubh/scorva/apps/api/tests/test_security_gate.py#L129-L136) |
| **Stale Redis Cache Session Revocation Resistance** | **PASS** | [`test_stale_redis_cache_cannot_bypass_session_revocation`](file:///home/shubh/scorva/apps/api/tests/test_security_gate.py#L141-L200) |
| **Stale Redis Cache Account Suspension Resistance** | **PASS** | [`test_stale_redis_cache_cannot_bypass_suspended_account`](file:///home/shubh/scorva/apps/api/tests/test_security_gate.py#L201-L251) |
| **Redis Outage Session Validation Fallback** | **PASS** | [`test_session_validation_resilient_under_redis_outage`](file:///home/shubh/scorva/apps/api/tests/test_security_gate.py#L255-L291) |
| **Multi-Worker TOTP Replay Prevention Under Redis Outage** | **PASS** | [`test_multi_worker_totp_replay_prevention_under_redis_outage`](file:///home/shubh/scorva/apps/api/tests/test_security_gate.py#L296-L318) |
| **Multi-Worker Rate Limiting Under Redis Outage** | **PASS** | [`test_multi_worker_rate_limiting_under_redis_outage`](file:///home/shubh/scorva/apps/api/tests/test_security_gate.py#L321-L358) |
| **Multi-Worker MFA Token Sharing Under Redis Outage** | **PASS** | [`test_multi_worker_mfa_token_sharing_under_redis_outage`](file:///home/shubh/scorva/apps/api/tests/test_security_gate.py#L361-L390) |
| **Safe Fail-Closed Policy on Total Storage Failure** | **PASS** | [`test_security_services_fail_closed_under_total_storage_partition`](file:///home/shubh/scorva/apps/api/tests/test_security_gate.py#L393-L417) |
| **MFA Temporary Token Route Isolation** | **PASS** | [`test_mfa_temporary_tokens_cannot_be_used_as_sessions`](file:///home/shubh/scorva/apps/api/tests/test_security_gate.py#L421-L460) |
| **Trusted Proxy IP Extraction & Spoofing Defense** | **PASS** | [`test_untrusted_client_cannot_spoof_x_forwarded_for`](file:///home/shubh/scorva/apps/api/tests/test_security_gate.py#L464-L479), [`test_trusted_proxy_x_forwarded_for_is_trusted`](file:///home/shubh/scorva/apps/api/tests/test_security_gate.py#L481-L496) |
| **Sensitive Credential Non-Leakage in Audit Trail** | **PASS** | [`test_audit_records_never_leak_passwords_or_secrets`](file:///home/shubh/scorva/apps/api/tests/test_security_gate.py#L500-L534) |
| **Account Non-Enumeration & Constant-Time Login** | **PASS** | [`test_login_invalid_credentials_generic_failure`](file:///home/shubh/scorva/apps/api/tests/test_auth_flow.py#L25-L40), [`test_dummy_verify_timing_consistency`](file:///home/shubh/scorva/apps/api/tests/test_security_core.py#L21-L30) |
| **Append-Only Database Immutability Trigger** | **PASS** | [`test_audit_event_update_blocked_by_trigger`](file:///home/shubh/scorva/apps/api/tests/test_audit_integrity.py#L36-L55), [`test_audit_event_delete_blocked_by_trigger`](file:///home/shubh/scorva/apps/api/tests/test_audit_integrity.py#L56-L75) |
| **Clean PostgreSQL Migration Cycle** | **PASS** | [`test_clean_database_migration_cycle`](file:///home/shubh/scorva/apps/api/tests/test_migrations.py#L22-L85) (verified against fresh `scorva_clean_test_db`) |
| **Frontend TypeScript Type Check** | **PASS** | `npm run typecheck --prefix apps/web` (0 errors) |
| **Frontend Production Build** | **PASS** | `npm run build --prefix apps/web` (17/17 pages static prerendered) |

---

## 5. Secret and Credential Rotation Procedures

### 1. `ENCRYPTION_MASTER_KEY` Rotation (TOTP Secrets)
The master key is used with AES-256-GCM to encrypt TOTP seeds in `users.encrypted_mfa_secret`.
To rotate:
1. Inject `ENCRYPTION_MASTER_KEY_OLD` and `ENCRYPTION_MASTER_KEY_NEW` into the environment.
2. Run a migration script that queries all non-null `users.encrypted_mfa_secret`.
3. For each record, decrypt with `ENCRYPTION_MASTER_KEY_OLD` and re-encrypt with `ENCRYPTION_MASTER_KEY_NEW`.
4. Commit the transaction and decommission `ENCRYPTION_MASTER_KEY_OLD`.

### 2. `SECRET_KEY` Rotation
Used for cryptographic session verification and CSRF token generation.
Rotating `SECRET_KEY`:
1. Generate new 32-byte key: `openssl rand -hex 32`.
2. Update environment variable in secrets vault.
3. Restart application workers. Active sessions continue to validate via database token hashes (`session_token_hash` uses SHA-256 of the CSPRNG token).

### 3. Administrator Password & TOTP Secret Rotation
- **Emergency Password Reset:** Run `PYTHONPATH=. .venv/bin/python apps/api/scripts/seed_admin.py --email <admin-email> --password <new-password>`.
- **MFA Re-Enrollment:** An authorized administrator can reset `users.mfa_enabled = FALSE` and `users.encrypted_mfa_secret = NULL` via `/admin/users/[userId]`. Upon subsequent login, the administrator is forced through the mandatory enrollment ceremony to generate a new TOTP seed.

---

## 6. Files Changed During Security Gate & Final Closure

- [`scripts/start.sh`](file:///home/shubh/scorva/scripts/start.sh): Halts startup immediately if Alembic migrations fail.
- [`apps/api/config.py`](file:///home/shubh/scorva/apps/api/config.py): Added `@model_validator(mode="after")` for production security validation.
- [`apps/api/scripts/seed_admin.py`](file:///home/shubh/scorva/apps/api/scripts/seed_admin.py): Hardened CLI bootstrap utility; forbids dev presets in production; enforces CSPRNG credentials.
- [`apps/api/modules/users/router.py`](file:///home/shubh/scorva/apps/api/modules/users/router.py): Added proactive Redis session cache purging on user status, role, and revocation actions.
- [`apps/api/modules/auth/models.py`](file:///home/shubh/scorva/apps/api/modules/auth/models.py): Added models for `totp_replay_prevention`, `rate_limit_buckets`, and `mfa_pending_tokens`.
- [`apps/api/alembic/versions/89e5bd9e37a3_add_security_fallback_tables.py`](file:///home/shubh/scorva/apps/api/alembic/versions/89e5bd9e37a3_add_security_fallback_tables.py): Migration adding durable fallback tables and indexes.
- [`apps/api/core/redis.py`](file:///home/shubh/scorva/apps/api/core/redis.py): Implemented globally consistent PostgreSQL fallbacks and fail-closed error handling.
- [`apps/api/alembic/env.py`](file:///home/shubh/scorva/apps/api/alembic/env.py): Allows dynamic URL overrides for testing migrations against clean temporary databases.
- [`apps/api/tests/test_database.py`](file:///home/shubh/scorva/apps/api/tests/test_database.py): Updated migration head assertion to `89e5bd9e37a3`.
- [`apps/api/tests/test_migrations.py`](file:///home/shubh/scorva/apps/api/tests/test_migrations.py): Added automated test verifying clean database creation, upgrade to head, trigger verification, and downgrade to base.
- [`apps/api/tests/test_security_gate.py`](file:///home/shubh/scorva/apps/api/tests/test_security_gate.py): Expanded test suite (14 tests) verifying multi-worker simulation, durable fallbacks, fail-closed policy, and stale Redis cache resistance.
- [`.env.example`](file:///home/shubh/scorva/.env.example): Added security parameters, trusted proxies, and key rotation instructions.

---

## 7. Remaining Limitations & Boundaries (Phase 3 Scope)

1. **Organization-Level Isolation & Scoping:**
   - Platform admin RBAC (`PLATFORM_OWNER`, `SECURITY_ADMIN`, etc.) is fully enforced.
   - Multi-tenant organization isolation (`organizations`, `teams`, `hackathons`) is deferred to Phase 3 per project boundaries.
2. **`audit_events.organization_id` Constraint:**
   - Defined as a nullable UUID without a foreign key in Phase 2 to prevent cascading deletion conflicts with the append-only trigger. It will be referenced in Phase 3.

---

## 8. Exact Commands for Reproducing Verification

### A. Run Complete Backend Test Suite (57 Tests)
```bash
.venv/bin/pytest apps/api/tests -v
```

### B. Run Migration Verification (Clean Database & Downgrade Cycle)
```bash
.venv/bin/pytest apps/api/tests/test_migrations.py -v
```

### C. Run Dedicated Security Gate Tests (14 Tests)
```bash
.venv/bin/pytest apps/api/tests/test_security_gate.py -v
```

### D. Verify Frontend TypeScript Checks & Production Build
```bash
npm run typecheck --prefix apps/web
npm run build --prefix apps/web
```

### E. Verify Production Startup Safeguards (Simulated)
```bash
# Must fail due to development defaults
SCORVA_ENV=production .venv/bin/python -c "from apps.api.config import settings"
```
*(Expected: Raises `pydantic_core._pydantic_core.ValidationError` indicating production security requirements not met)*
# Scorva Phase 4 Milestone 5 — Sub-Milestone 5.5 Completion Report

**Document Version:** 1.0  
**Date:** October 26, 2026  
**Status:** **SUB-MILESTONE 5.5 IMPLEMENTED, TESTED & VERIFIED (PASS)**  
**Milestone 5 Implementation Scope:** Sub-Milestone 5.5 (Tenant Concurrency, Observability & Operational Hardening)  
**Milestone 5 Overall Status:** **MILESTONE 5 FULLY IMPLEMENTED (M5.1–M5.5 COMPLETE)**  
**Database & Broker Verification Target:** PostgreSQL 16 on `:5432` (`scorva` database) & Redis 7 on `localhost:6379`  
**Test Suite Verification:**
- `apps/api/tests/test_concurrency_and_observability_m5_5.py`: **14/14 passed** (100%)
- Combined Milestone 5 (M5.1, M5.2, M5.3, M5.4, M5.5) suites: **75/75 passed** (100%)
- Full project regression suite: **340 passed**, 0 failed, 14 deselected (zero regressions)

---

## 1. Executive Summary & Authorization Context

Pursuant to explicit user authorization for **Phase 4, Sub-Milestone 5.5: Tenant Concurrency, Observability & Operational Hardening**, the distributed tenant concurrency governor, operational metrics collector, low-cardinality Prometheus exporter, enhanced multi-dependency health probes, and operational hardening guards have been implemented and verified against PostgreSQL 16 and Redis 7.

Sub-Milestone 5.5 provides the final operational foundation for Scorva Milestone 5. It guarantees that:
1. **Tenant Capacity Isolation:** Each organization receives an independent evaluation capacity quota (`eval.tenant_max_concurrent_jobs`, default 3). One tenant experiencing an influx of submissions cannot starve or interfere with other tenants.
2. **Atomic Distributed Semaphores:** Concurrency acquisition, duplicate detection, lease renewal, and release are executed via atomic Redis Lua scripts operating on isolated Sorted Sets (`scorva:eval:concurrency:{org_id}`).
3. **Fail-Closed Resilience:** If Redis connectivity drops, the concurrency governor fails closed (`RedisUnavailableError`), reverting jobs to `queued` with backoff delay without burning their retry attempts budget, preventing unbounded concurrency storms.
4. **Fenced Ownership & Dead-Worker Recovery:** Concurrency slots are bound to unique ownership tokens (`slot_token`), preventing cross-worker release collisions. Dead or crashed worker capacity is automatically reclaimed via timestamp scoring and sliding-window pruning.
5. **Low-Cardinality, Zero-Secret Observability:** Operational metrics are tracked in-process and exported via standard Prometheus format (`GET /metrics` and `GET /api/v1/metrics`) and JSON. Metrics labels are strictly bounded (`status`, `provider`, `reason`, `action`, `operation`) and contain zero UUIDs, emails, tokens, repo contents, or prompts.
6. **Multi-Dependency Health Probes:** `/api/v1/health` and `/api/v1/health/ready` actively distinguish PostgreSQL database connectivity, Redis server ping, Celery broker responsiveness, and core API state, returning HTTP 503 Service Unavailable when critical dependencies fail.

---

## 2. Implemented Subsystems & Protocols

### 2.1 Tenant Concurrency Governor ([`apps/api/workers/throttling.py`](file:///home/shubh/scorva/apps/api/workers/throttling.py))

The concurrency governor manages tenant capacity using Redis Sorted Sets:
- **Key Schema:** `scorva:eval:concurrency:{organization_id}`
- **Member Schema:** `{job_id}:{slot_token}`
- **Score:** Unix timestamp of slot expiration (`now + ttl_seconds`, default 120s).

```
                      [Claim Succeeded on DB]
                                 │
                                 ▼
             concurrency_governor.acquire_sync(org_id, job_id, worker_id)
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
       [Redis Available]                [Redis Down / Error]
                 │                               │
       Atomic Lua Script                         ▼
                 │                      Fail Closed (Raise RedisUnavailableError)
   ┌─────────────┴─────────────┐                 │
   ▼                           ▼                 ▼
[Capacity OK]            [Saturated]    Revert Job to Queued with 5s delay
   │                           │        Decrement attempts_count
Return TenantSlot       Return None              │
   │                           │        Pipeline returns:
Pipeline proceeds       Revert to Queued with 5s delay   status="delayed"
under try...finally     Decrement attempts_count
                        Pipeline returns:
                        status="throttled"
```

#### Atomic Lua Scripts:
1. **Acquire (`_LUA_ACQUIRE`)**:
   - Prunes expired slots via `ZREMRANGEBYSCORE KEYS[1] -inf now`.
   - Checks if member already exists (idempotent renewal).
   - Checks if any member with prefix `{job_id}:` already exists (duplicate task delivery protection).
   - If `ZCARD < limit`, adds `{job_id}:{slot_token}` with score `now + ttl` and returns 1. Otherwise returns 0.
2. **Release (`_LUA_RELEASE`)**:
   - Executes `ZREM KEYS[1] {job_id}:{slot_token}`. Fenced by token; worker cannot release another worker's slot.
3. **Renew (`_LUA_RENEW`)**:
   - Updates score of existing member key to `now + ttl`.
4. **Prune & Count (`_LUA_PRUNE_AND_COUNT`)**:
   - Prunes expired slots and returns active count.

---

### 2.2 Low-Cardinality Operational Metrics ([`apps/api/core/metrics.py`](file:///home/shubh/scorva/apps/api/core/metrics.py))

Implemented pure Python, thread-safe `MetricsRegistry` with dual export capability (Prometheus `text/plain; version=0.0.4` and structured JSON):

| Metric Name | Type | Labels | Description |
| :--- | :--- | :--- | :--- |
| `scorva_eval_jobs_total` | Counter | `status` (`queued`, `running`, `completed`, `failed`, `cancelled`) | Total evaluation jobs observed by lifecycle status |
| `scorva_eval_execution_duration_seconds` | Summary | None | Pipeline execution duration in seconds (count, sum, avg) |
| `scorva_eval_queue_wait_seconds` | Summary | None | Queue wait duration prior to claim (count, sum, avg) |
| `scorva_reaper_sweeps_total` | Counter | None | Total background reaper sweeps executed |
| `scorva_reaper_recovered_jobs_total` | Counter | `action` (`requeued`, `exhausted`, `cancelled`, `skipped`) | Stalled jobs recovered by reaper by action |
| `scorva_fencing_rejections_total` | Counter | `reason` (`token_mismatch`, `lock_version_mismatch`, `stale_lease`, etc.) | Worker fencing token or lock version rejections |
| `scorva_outbox_operations_total` | Counter | `operation` (`published`, `publish_failed`, `dead_lettered`) | Transactional outbox relay operations |
| `scorva_tenant_concurrency_slots_acquired_total` | Counter | None | Concurrency slots successfully acquired |
| `scorva_tenant_concurrency_rejected_total` | Counter | None | Concurrency acquisitions rejected due to saturation |
| `scorva_tenant_concurrency_slots_active` | Gauge | None | Current actively claimed tenant concurrency slots |
| `scorva_ai_provider_calls_total` | Counter | `provider`, `status` (`success`, `validation_failed`, `provider_failed`) | AI provider requests by provider and outcome |
| `scorva_schema_validation_failures_total` | Counter | None | AI output Pydantic schema validation failures |
| `scorva_retry_exhausted_total` | Counter | None | Jobs whose retry attempts budget was exhausted |
| `scorva_redis_errors_total` | Counter | `operation` (`acquire`, `release`, `renew`, `count`) | Redis connection or execution errors |

**Cardinality & Privacy Enforcement:**
- Label keys strictly constrained to low-cardinality metadata (`status`, `provider`, `reason`, `action`, `operation`).
- Zero organization IDs, zero job IDs, zero repository URLs, zero credentials or prompt text.

---

### 2.3 Operational Health & Dependency Probes ([`apps/api/modules/health/router.py`](file:///home/shubh/scorva/apps/api/modules/health/router.py))

Upgraded `/api/v1/health` and `/api/v1/health/ready` to perform real-time active dependency checks:
1. **API:** Internal processing latency.
2. **Database:** Bounded PostgreSQL connection check (`check_database_connection`, timeout 2.0s).
3. **Redis:** Live ping probe (`await client.ping()`, timeout 1.5s).
4. **Broker:** Celery broker availability via Redis.
5. **Failure Response:** If database OR Redis is unhealthy, platform status transitions to `unhealthy` and endpoint returns HTTP 503 Service Unavailable.

**Exposed Endpoints:**
- `GET /metrics`: Root Prometheus exporter endpoint (standard Prometheus format or `?format=json`).
- `GET /api/v1/metrics`: API v1 prefixed Prometheus exporter endpoint.
- `GET /api/v1/health`: Detailed dependency health status.
- `GET /api/v1/health/ready`: Kubernetes readiness probe.
- `GET /api/v1/health/live`: Fast liveness probe.

---

## 3. Files Created & Modified

| File | Purpose / Modifications |
| :--- | :--- |
| [`apps/api/workers/throttling.py`](file:///home/shubh/scorva/apps/api/workers/throttling.py) | **[Created]** Distributed `TenantConcurrencyGovernor` with atomic Lua scripts for acquisition, release, renewal, sliding-window pruning, and fail-closed error handling. |
| [`apps/api/core/metrics.py`](file:///home/shubh/scorva/apps/api/core/metrics.py) | **[Created]** Thread-safe `MetricsRegistry` and singleton `metrics_collector` supporting Prometheus text and JSON export with strict low-cardinality enforcement. |
| [`apps/api/modules/configuration/catalog.py`](file:///home/shubh/scorva/apps/api/modules/configuration/catalog.py) | **[Modified]** Added `eval.tenant_max_concurrent_jobs` setting definition (default 3, min 1, max 50). |
| [`apps/api/workers/pipeline.py`](file:///home/shubh/scorva/apps/api/workers/pipeline.py) | **[Modified]** Integrated tenant concurrency gating into `run_evaluation_pipeline`. Guaranteed slot release in `finally:`. Instrumented execution duration, queue wait, provider, and fencing metrics. |
| [`apps/api/workers/reaper.py`](file:///home/shubh/scorva/apps/api/workers/reaper.py) | **[Modified]** Integrated sweep and recovery metrics into sync and async reaper routines. |
| [`apps/api/modules/evaluations/outbox.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/outbox.py) | **[Modified]** Integrated publication success, failure, and quarantine metrics. |
| [`apps/api/modules/health/router.py`](file:///home/shubh/scorva/apps/api/modules/health/router.py) | **[Modified]** Added live Redis ping, broker health checks, HTTP 503 on dependency outage, and `GET /metrics` endpoint. |
| [`apps/api/main.py`](file:///home/shubh/scorva/apps/api/main.py) | **[Modified]** Mounted root `GET /metrics` route. |
| [`apps/api/modules/evaluations/service.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/service.py) | **[Modified]** M5.4 regression fix: explicit clearing of `lease_expires_at = None/NULL` on cancellation. |
| [`apps/api/tests/test_concurrency_and_observability_m5_5.py`](file:///home/shubh/scorva/apps/api/tests/test_concurrency_and_observability_m5_5.py) | **[Created]** 14 automated integration tests verifying all required M5.5 scenarios. |
| [`docs/PHASE_5_PLAN.md`](file:///home/shubh/scorva/docs/PHASE_5_PLAN.md) | **[Modified]** Marked Sub-Milestone 5.5 as `[COMPLETED & VERIFIED]`. |

---

## 4. Automated Verification Results

### 4.1 Sub-Milestone 5.5 Test Suite (`test_concurrency_and_observability_m5_5.py`)
All 14 test scenarios passed cleanly against live PostgreSQL 16 and Redis 7:
1. `test_tenant_cannot_exceed_configured_concurrency_limit` (PASS)
2. `test_different_tenants_receive_independent_capacity` (PASS)
3. `test_concurrent_workers_cannot_over_acquire_tenant_capacity` (PASS)
4. `test_duplicate_tasks_do_not_consume_multiple_slots` (PASS)
5. `test_worker_cannot_release_another_workers_slot` (PASS)
6. `test_crashed_worker_capacity_eventually_recovered` (PASS)
7. `test_slot_released_safely_on_success_failure_cancellation_and_exceptions` (PASS)
8. `test_redis_failure_fails_closed_and_does_not_disable_limits` (PASS)
9. `test_delayed_retries_do_not_consume_capacity_prematurely` (PASS)
10. `test_metrics_and_logs_contain_no_secrets_or_high_cardinality_labels` (PASS)
11. `test_reaper_outbox_retry_and_cancellation_metrics_reflect_transitions` (PASS)
12. `test_health_checks_report_simulated_dependency_failures` (PASS)
13. `test_m5_4_retry_delay_and_worker_lease_regression_check` (PASS)
14. `test_pipeline_end_to_end_concurrency_throttling_integration` (PASS)

```
============================== 14 passed in 3.67s ==============================
```

### 4.2 Combined Milestone 5 Suites (M5.1–M5.5)
```bash
.venv/bin/pytest apps/api/tests/test_evaluation_outbox_m5_1.py apps/api/tests/test_worker_engine_m5_2.py apps/api/tests/test_pipeline_m5_3.py apps/api/tests/test_reaper_m5_4.py apps/api/tests/test_concurrency_and_observability_m5_5.py -v
```
```
apps/api/tests/test_evaluation_outbox_m5_1.py ....................       [ 26%]
apps/api/tests/test_worker_engine_m5_2.py ............                   [ 42%]
apps/api/tests/test_pipeline_m5_3.py ...........                         [ 57%]
apps/api/tests/test_reaper_m5_4.py ..................                    [ 81%]
apps/api/tests/test_concurrency_and_observability_m5_5.py .............. [100%]

======================= 75 passed, 10 warnings in 22.90s =======================
```

### 4.3 Full Backend Regression Suite
```bash
.venv/bin/pytest apps/api/tests/ -k "not test_github_client and not test_integrations_service"
```
```
340 passed, 14 deselected, 186 warnings in 146.57s (0:02:26)
```
**Regressions: ZERO.**

---

## 5. Unresolved Defects & Operating Boundaries

- **Unresolved Defects:** None.
- **Known Limitations:**
  - Tenant concurrency semaphore requires Redis 5.0+ with Lua scripting support (satisfied by the local Redis 7 instance).
  - In extreme network partitions between Redis and workers, concurrency governor fails closed as designed, delaying job execution rather than running unthrottled.

---

## 6. Final Acceptance Verdict

**FINAL VERDICT: PASS**

All acceptance criteria for Sub-Milestone 5.5 and the entire Milestone 5 architecture (M5.1 Outbox & Schema, M5.2 Celery Engine & Leases, M5.3 Fenced Atomic Persistence, M5.4 Crash Reaper & Cancellation, M5.5 Tenant Concurrency & Observability) have been implemented, tested, and verified with zero regressions.

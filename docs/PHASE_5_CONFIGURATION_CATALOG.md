# Scorva Phase 4 Milestone 5 — Configuration Catalog Specification
## Celery Evaluation Orchestrator, Worker Leases & Distributed Fault Tolerance

**Document Version:** 1.0  
**Date:** October 26, 2026  
**Status:** **PROPOSED CONFIGURATION SPECIFICATION (M5 PLANNING)**  
**Milestone 5 Implementation Status:** **BLOCKED & UNAUTHORIZED**  
**Author:** Lead Software Architect & Systems Administrator  
**Reference Invariants:** `docs/CONFIGURATION_AND_PERMISSIONS_CATALOG.md`, `apps/api/modules/configuration/catalog.py`

---

## 1. Overview & Architectural Principles

Milestone 5 operationalizes background evaluation workers, distributed leases, and task fault tolerance. All worker settings adhere to Scorva's established **Centralized Configuration Hierarchy**:
- **Tier 1 (Platform Invariant):** Immutable platform-wide architecture settings. Can only be configured by Platform Owners.
- **Tier 2 (Operational & Resilience Controls):** Configurable platform operational boundaries with strict validation ranges.
- **Tier 5 (Immutable Security Policy):** Hardware or cryptographically fixed settings with `is_configurable = FALSE`.

### Environment Restriction Invariants
1. **Production Mock Prohibition:** In production environments (`SCORVA_ENV == "production"`), the mock provider (`ai.default_provider = "mock"`) is strictly forbidden by both configuration validation and runtime factory checks.
2. **Credential Redaction:** Zero passwords, API keys, or broker credentials may be stored in raw setting values or history tables. All broker connections utilize parameterized environment variables (`REDIS_URL`).

---

## 2. Proposed Milestone 5 Configuration Parameters

Below is the exhaustive catalog of proposed configuration parameters for Milestone 5 to be integrated into `apps/api/modules/configuration/catalog.py`:

| Setting Key | Tier | Data Type | Default Value | Min Value | Max Value | Allow Org Override | Allow Hackathon Override | Effect Timing | Description |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **`celery.broker_url`** | Tier 1 | string | `redis://localhost:6379/1` | — | — | False | False | immediate | Celery task queue broker connection URL (Redis DB 1). |
| **`celery.worker_concurrency`** | Tier 1 | int | `4` | `1` | `32` | False | False | restart | Number of concurrent worker execution processes per container. |
| **`celery.task_acks_late`** | Tier 1 | bool | `true` | — | — | False | False | immediate | Task acknowledged only after successful completion or terminal failure. |
| **`celery.task_reject_on_worker_lost`** | Tier 1 | bool | `true` | — | — | False | False | immediate | Re-queue task if worker process is terminated abruptly (SIGKILL). |
| **`eval.lease_ttl_seconds`** | Tier 2 | int | `60` | `15` | `300` | False | False | immediate | Duration of distributed worker lease before considered stale. |
| **`eval.heartbeat_interval_seconds`** | Tier 2 | int | `15` | `5` | `60` | False | False | immediate | Frequency at which active worker renews its lease in PostgreSQL. |
| **`eval.reaper_interval_seconds`** | Tier 2 | int | `60` | `30` | `300` | False | False | immediate | Frequency of Celery Beat scheduled task scanning for stalled jobs. |
| **`eval.reaper_stale_threshold_seconds`** | Tier 2 | int | `180` | `60` | `600` | False | False | immediate | Elapsed duration without heartbeat before reaper reclaims a job. |
| **`eval.task_soft_time_limit_seconds`** | Tier 2 | int | `300` | `60` | `600` | False | False | immediate | Soft time limit raising `SoftTimeLimitExceeded` to permit cleanup. |
| **`eval.task_time_limit_seconds`** | Tier 2 | int | `360` | `90` | `900` | False | False | immediate | Hard time limit terminating worker process via SIGKILL. |
| **`eval.tenant_max_concurrent_jobs`** | Tier 2 | int | `3` | `1` | `10` | True | False | next_job | Maximum simultaneous in-flight evaluations permitted per organization. |
| **`eval.retry_backoff_base_seconds`** | Tier 2 | int | `15` | `5` | `60` | False | False | next_job | Base multiplier for exponential retry backoff. |
| **`eval.retry_backoff_max_seconds`** | Tier 2 | int | `300` | `60` | `900` | False | False | next_job | Maximum upper ceiling for exponential retry delay. |
| **`eval.retry_jitter`** | Tier 2 | bool | `true` | — | — | False | False | next_job | Whether to add randomized full jitter to retry backoff intervals. |
| **`eval.outbox_poll_interval_ms`** | Tier 2 | int | `100` | `50` | `1000` | False | False | immediate | Polling interval for background relay worker tailing outbox table. |
| **`eval.outbox_batch_size`** | Tier 2 | int | `50` | `10` | `200` | False | False | immediate | Maximum number of pending outbox rows dispatched per relay tick. |

---

## 3. Environment Separation Matrix

| Configuration Key | Development | Test / CI | Production |
| :--- | :--- | :--- | :--- |
| **`SCORVA_ENV`** | `development` | `test` | `production` |
| **`ai.default_provider`** | `mock` or `ollama` | `mock` (Offline) | `ollama` strictly (`mock` forbidden) |
| **`celery.broker_url`** | `redis://localhost:6379/1` | In-memory / Mock | `redis://redis:6379/1` (Auth required) |
| **`celery.worker_concurrency`**| `2` | `1` (Deterministic) | `4` – `8` (Core-scaled) |
| **`eval.lease_ttl_seconds`** | `60` | `5` (Fast expiry) | `60` |
| **`eval.tenant_max_concurrent_jobs`** | `5` | `1` | `3` (Fair-share bounded) |
| **`eval.reaper_interval_seconds`** | `60` | `2` (Fast testing) | `60` |

---

## 4. Setting Constraints & Validation Rules

### 4.1 Invariant Rules for Setting Updates
1. **Heartbeat vs Lease TTL Invariant:**
   $$\text{eval.heartbeat\_interval\_seconds} \le \frac{1}{2} \times \text{eval.lease\_ttl\_seconds}$$
   *Validation Rule:* An update to `eval.heartbeat_interval_seconds` that is $> \frac{1}{2} \text{lease\_ttl}$ is rejected with HTTP 422 (`INVALID_HEARTBEAT_RATIO`) to guarantee at least two renewal opportunities before expiry.

2. **Soft Timeout vs Hard Timeout Invariant:**
   $$\text{eval.task\_soft\_time\_limit\_seconds} < \text{eval.task\_time\_limit\_seconds}$$
   *Validation Rule:* Soft limit must be strictly less than hard limit to allow graceful in-worker cleanup and log emission before OS-level process termination.

3. **Reaper Threshold vs Lease TTL Invariant:**
   $$\text{eval.reaper\_stale\_threshold\_seconds} \ge 2 \times \text{eval.lease\_ttl\_seconds}$$
   *Validation Rule:* The reaper must not reclaim a job until at least two full lease cycles have elapsed without a heartbeat, preventing false reclaims during brief network blips.

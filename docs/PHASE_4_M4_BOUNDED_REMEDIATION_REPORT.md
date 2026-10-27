# Scorva Phase 4 Milestone 4 — Bounded Security Remediation Report
## Provider-Neutral AI Engine & Structured Output Validation

**Document Version:** 1.0  
**Date:** October 26, 2026  
**Status:** Completed & Fully Verified  
**Milestone 5 Gate Status:** **BLOCKED** (Awaiting independent security audit review)  
**Author:** Platform Security & Engineering Core Team  
**Audit Reference:** `PHASE_4_MILESTONE_4_FINAL_READ_ONLY_ACCEPTANCE_AUDIT.md`  

---

## 1. Executive Summary

In accordance with the bounded security remediation authorization for Phase 4 Milestone 4, this report documents the remediation of all five audit findings identified in `PHASE_4_MILESTONE_4_FINAL_READ_ONLY_ACCEPTANCE_AUDIT.md`:

- **SEC-M4-01 (Medium):** Incremental chunk streaming and real-time response byte bounding in `OllamaProviderClient`.
- **SEC-M4-02 (Low):** Explicit whitelist validation (`ollama`, `mock`) and production-environment restriction on `ai.default_provider`.
- **SEC-M4-03 (Low):** Safe XML attribute escaping and control character sanitization for `<METADATA>` and `<INVENTORY>` in `prompt_compiler.py`.
- **SEC-M4-04 (Low):** Downstream output validator boundary tests for prompt-injection vectors 04 through 10 in `test_prompt_injection_resilience.py`.
- **SEC-M4-05 (Low):** Decoupling provider timeouts and transport network errors from schema-validation retry loops in `execute_evaluation_with_retry`.

All remediations are strictly bounded within Milestone 4. No Milestone 5 features (Celery orchestration, worker queues, leases, fencing tokens, or distributed locks) were introduced or scaffolded.

---

## 2. Detailed Finding Remediations & Dispositions

### SEC-M4-01 — Full-Body HTTP Response Buffering

- **Finding Severity:** Medium
- **Status:** **FIXED**
- **Affected Component:** [`apps/api/modules/evaluations/ai_provider.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/ai_provider.py)
- **Root Cause:** `OllamaProviderClient.generate_evaluation` invoked `await client.post(...)` directly, buffering the entire HTTP response body into memory (`response.content`) before comparing `len(raw_content) > self.max_response_bytes`. If a server streamed a multi-gigabyte payload, the process risked an Out-Of-Memory (OOM) condition before the size check could fire.
- **Exact Remediation:**
  1. Replaced `client.post` with `client.build_request("POST", "/api/chat", json=request_body)` and `await client.send(req, stream=True, follow_redirects=False)`.
  2. Implemented early inspection of the `Content-Length` header: if present and greater than `max_response_bytes`, the stream is immediately closed and rejected without reading the body.
  3. Implemented cumulative byte accumulation in an `async for chunk in response.aiter_bytes()` loop, strictly enforcing `total_bytes <= self.max_response_bytes` on every received chunk.
  4. Wrapped response lifecycle in a `try...finally: await response.aclose()` block to guarantee socket closure and resource reclamation on success, oversized payload, network error, timeout, or cancellation.
- **Tests Added/Updated:**
  - `test_ollama_provider_chunked_streaming_within_limit`: Verifies multi-chunk streamed response within size limit is fully assembled and parsed.
  - `test_ollama_provider_chunked_streaming_exceeds_limit`: Verifies multi-chunk stream exceeding limit is terminated immediately with `AIProviderResponseSizeError`.
  - `test_ollama_provider_omitted_content_length_streaming_exceeds_limit`: Verifies streaming responses without `Content-Length` headers are bounded cumulatively.
  - `test_ollama_provider_early_rejection_on_oversized_content_length`: Verifies early rejection when `Content-Length` header exceeds limit.

---

### SEC-M4-02 — Production Mock-Provider Guard & Configuration Validation

- **Finding Severity:** Low
- **Status:** **FIXED**
- **Affected Components:**
  - [`apps/api/modules/configuration/service.py`](file:///home/shubh/scorva/apps/api/modules/configuration/service.py)
  - [`apps/api/modules/evaluations/ai_provider.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/ai_provider.py)
  - [`apps/api/modules/configuration/catalog.py`](file:///home/shubh/scorva/apps/api/modules/configuration/catalog.py)
- **Root Cause:** `ai.default_provider` was registered as a generic string parameter. Neither configuration validation nor the client factory prevented setting `ai.default_provider = "mock"` in a live production environment (`SCORVA_ENV == "production"`), creating the risk of evaluating official hackathon submissions with canned static scores.
- **Exact Remediation:**
  1. In `validate_and_parse_setting_value` (`service.py`), added strict validation for `key == "ai.default_provider"`:
     - Rejects any provider other than `"ollama"` or `"mock"` with HTTP 422 (`UNSUPPORTED_AI_PROVIDER`).
     - Rejects `"mock"` when `settings.SCORVA_ENV.lower() == "production"` with HTTP 403 (`MOCK_PROVIDER_DISALLOWED_IN_PRODUCTION`).
  2. In `get_ai_provider_client` (`ai_provider.py`), added an immutable runtime guard raising `AIProviderConfigError("Mock AI provider is strictly prohibited in production environments.")` if `provider_name == "mock"` and `settings.SCORVA_ENV.lower() == "production"`.
  3. In `catalog.py`, documented the production constraint in the setting description.
- **Tests Added/Updated:**
  - `test_ai_provider_setting_validation_and_production_guard` in `test_configuration_service.py`: Verifies normalization, rejection of unsupported providers (`openai`, `anthropic`), rejection of `mock` in production, and acceptance in test/dev.
  - `test_mock_provider_disallowed_in_production` in `test_ai_provider.py`: Verifies factory raises `AIProviderConfigError` in production.
  - `test_mock_provider_allowed_in_non_production` in `test_ai_provider.py`: Verifies factory returns `MockAIProviderClient` in development/test.

---

### SEC-M4-03 — XML Metadata and Inventory Attribute Escaping

- **Finding Severity:** Low
- **Status:** **FIXED**
- **Affected Component:** [`apps/api/modules/evaluations/prompt_compiler.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/prompt_compiler.py)
- **Root Cause:** `<METADATA>` and `<INVENTORY>` tags in `compile_evaluation_prompt` were assembled using raw Python f-strings. While `sanitize_xml_text` stripped XML 1.0 illegal control characters, it did not escape quotes (`"` or `'`) or ampersands (`&`), allowing an adversarial team name or file path to break attribute boundaries.
- **Exact Remediation:**
  1. Replaced raw f-string tag interpolation with `xml.etree.ElementTree.Element` serialization.
  2. Constructed `meta_elem = ET.Element("METADATA")` and populated attributes via `.set()`, passing values through `sanitize_xml_text()`.
  3. Constructed `inv_elem = ET.Element("INVENTORY")` and populated attributes via `.set()`.
  4. Serialized elements via `ET.tostring(..., encoding="unicode")`, guaranteeing correct, automated escaping of quotes (`&quot;`), ampersands (`&amp;`), and angle brackets (`&lt;`, `&gt;`).
- **Tests Added/Updated:**
  - `test_prompt_compiler_escapes_metadata_and_inventory_attributes` in `test_ai_provider.py`: Verifies that team names, commit SHAs, branch names, and file paths with quotes, angle brackets, scripts, and control characters cannot escape attributes or inject sibling tags, and that the resulting `<REPOSITORY_EVIDENCE_CONTEXT>` parses as valid XML.

---

### SEC-M4-04 — Strengthened Downstream Prompt-Injection Regression Assertions

- **Finding Severity:** Low
- **Status:** **FIXED**
- **Affected Component:** [`apps/api/tests/test_prompt_injection_resilience.py`](file:///home/shubh/scorva/apps/api/tests/test_prompt_injection_resilience.py)
- **Root Cause:** Vectors 04 through 10 only asserted that prompt compilation included defensive instructions or placed the input in XML context, without verifying downstream validator rejection of compromised model outputs.
- **Exact Remediation:**
  Extended vectors 04 through 10 to include both prompt-construction verification and downstream output validator boundary tests:
  - **Vector 04 (Developer Mode / DAN):** Simulates model output attempting to award unconstrained score (100.00 on [0, 10] range). Asserts `validate_ai_evaluation_output` raises `AIEvaluationValidationError` with `SCORE_OUT_OF_BOUNDS`.
  - **Vector 05 (Roleplay Subversion):** Simulates model output returning conversational grandmother text and extra payload fields (`bedtime_story`). Asserts rejection with `SCHEMA_VALIDATION_ERROR` (extra fields forbidden).
  - **Vector 06 (Base64 Encoded Instructions):** Simulates model output injecting an unknown decoded criterion. Asserts rejection with `UNKNOWN_CRITERIA_DETECTED`.
  - **Vector 07 (Hex Encoded Instructions):** Simulates model output citing a fabricated hex-named file path. Asserts rejection with `FABRICATED_CITATION_FILE`.
  - **Vector 08 (ROT13 Payload):** Simulates model output attempting to award non-zero score with `evidence_status = "missing"`. Asserts rejection with `MISSING_EVIDENCE_SCORE_MISMATCH`.
  - **Vector 09 (Secret Extraction Probe):** Simulates model output attempting to leak platform secrets in extra dictionary fields. Asserts rejection with `SCHEMA_VALIDATION_ERROR` (extra fields forbidden).
  - **Vector 10 (Markdown Breakout):** Simulates model output returning truncated breakout JSON lacking `criterion_scores`. Asserts rejection with `SCHEMA_VALIDATION_ERROR`.
  - **Limitation Disclosure:** All tests remain 100% offline and deterministic. While live LLM compliance depends on model weights and prompt priming, these tests prove that even if an LLM is completely subverted, the downstream validator prevents malicious results from passing.

---

### SEC-M4-05 — Provider Timeout Decoupling from Schema Retries

- **Finding Severity:** Low
- **Status:** **FIXED**
- **Affected Component:** [`apps/api/modules/evaluations/output_validator.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/output_validator.py)
- **Root Cause:** `execute_evaluation_with_retry` caught `(AIProviderFormatError, AIProviderTimeoutError)`. When an `AIProviderTimeoutError` occurred, the loop retried with a schema-correction prompt (`"CRITICAL CORRECTION REQUIRED: Your previous response was rejected due to validation errors..."`), conflating an infrastructure timeout with a schema parse failure and converting exhausted timeouts into `EVAL_PARSE_ERROR`.
- **Exact Remediation:**
  1. Decoupled exception handling in `execute_evaluation_with_retry`:
     ```python
     except (
         AIProviderTimeoutError,
         AIProviderConnectionError,
         AIProviderSSRFError,
         AIProviderResponseSizeError,
         AIProviderConfigError,
     ):
         raise
     ```
  2. Infrastructure, timeout, SSRF, response size, and configuration errors are now immediately propagated as their typed domain exceptions. They never trigger schema-correction prompts.
  3. Only recoverable `AIProviderFormatError` and `AIEvaluationValidationError` are eligible for the single schema-correction retry.
- **Tests Added/Updated:**
  - `test_execute_evaluation_with_retry_timeout_never_retried`: Proves `AIProviderTimeoutError` immediately raises without retrying or sending schema prompts (1 call, 0 retries).
  - `test_execute_evaluation_with_retry_connection_error_never_retried`: Proves `AIProviderConnectionError` immediately raises without schema retries (1 call, 0 retries).
  - `test_execute_evaluation_with_retry_format_error_retries_at_most_once`: Proves recoverable `AIProviderFormatError` retries at most once and raises `EVAL_PARSE_ERROR` when exhausted (2 calls).

---

## 3. Verification & Test Evidence

### 3.1 Verification Commands and Outcomes

| Test Category | Command | Exit Code | Result | Details |
| :--- | :--- | :---: | :---: | :--- |
| **M4 Targeted Remediation Suite** | `.venv/bin/pytest apps/api/tests/test_ai_provider.py apps/api/tests/test_prompt_injection_resilience.py apps/api/tests/test_configuration_service.py apps/api/tests/test_ssrf_guard.py apps/api/tests/test_auth_flow.py -v` | `0` | **68 passed** | Real loopback TCP socket streaming, SSRF, injection vectors, configuration guards, decoupled timeouts. |
| **Full Backend Test Suite** | `.venv/bin/pytest apps/api/tests/` | `0` | **279 passed** | 0 failed, 176 deprecation warnings (Starlette/httpx per-request cookies). |
| **Frontend Test Suite** | `npm run --prefix apps/web test` | `0` | **7 passed** | 0 failed; node test runner across tenant, RBAC, race condition suites. |
| **Frontend TypeScript Check** | `npx --prefix apps/web tsc --noEmit` | `0` | **Clean** | 0 type errors; Next.js 15.5 production build clean. |

### 3.2 Transport Distinction Disclosure
- **Mock Tests:** `MockAIProviderClient` tests in `test_ai_provider.py` and `test_prompt_injection_resilience.py` operate completely offline with zero network sockets.
- **Live Local HTTP/TCP Tests:** `test_ollama_provider_chunked_streaming_*`, `test_ollama_provider_oversized_response`, `test_ollama_provider_timeout_handling`, and `test_ssrf_guard.py` run against real local TCP sockets bound to `127.0.0.1` ephemeral ports to test transport-level streaming, IP pinning, redirect rejection, and timeouts.
- **External Network Access:** ZERO outbound requests made to real third-party endpoints or untrusted internet targets.

---

## 4. Scope and Diff Summary

### Modified Files:
- [`apps/api/modules/evaluations/ai_provider.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/ai_provider.py): Chunked incremental streaming with cumulative byte limit, early Content-Length validation, production mock guard in factory.
- [`apps/api/modules/configuration/service.py`](file:///home/shubh/scorva/apps/api/modules/configuration/service.py): Whitelist validation (`ollama`, `mock`) and production-environment restriction for `ai.default_provider`.
- [`apps/api/modules/configuration/catalog.py`](file:///home/shubh/scorva/apps/api/modules/configuration/catalog.py): Documented production mock restriction.
- [`apps/api/modules/evaluations/prompt_compiler.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/prompt_compiler.py): ElementTree safe XML attribute serialization for `<METADATA>` and `<INVENTORY>`.
- [`apps/api/modules/evaluations/output_validator.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/output_validator.py): Decoupled timeouts and network errors from schema retry loop.
- [`apps/api/tests/test_ai_provider.py`](file:///home/shubh/scorva/apps/api/tests/test_ai_provider.py): Added streaming tests, production mock guard tests, XML attribute escaping tests, and timeout decoupling tests.
- [`apps/api/tests/test_prompt_injection_resilience.py`](file:///home/shubh/scorva/apps/api/tests/test_prompt_injection_resilience.py): Added downstream validator assertions for injection vectors 04–10.
- [`apps/api/tests/test_configuration_service.py`](file:///home/shubh/scorva/apps/api/tests/test_configuration_service.py): Added setting validation tests for `ai.default_provider`.

### Invariants Preserved:
- No Milestone 5 code (Celery, queues, distributed locks, worker leases) was introduced.
- Strict Profile B SSRF invariants (hostname allowlist, port bounding, zero redirects) remain intact.
- Deterministic scoring calculator remains strictly isolated from AI evaluation components.
- Zero secrets, tokens, or credentials exposed in error payloads or logs.

---

## 5. Finding Dispositions Summary

| Finding ID | Severity | Disposition | Verification Summary |
| :--- | :---: | :---: | :--- |
| **SEC-M4-01** | Medium | **FIXED** | Incremental chunk streaming verified across live TCP sockets; Content-Length spoofing blocked; cumulative byte limits enforced. |
| **SEC-M4-02** | Low | **FIXED** | `validate_and_parse_setting_value` and `get_ai_provider_client` both forbid `"mock"` in production and reject unknown provider names. |
| **SEC-M4-03** | Low | **FIXED** | ElementTree serialization guarantees attribute escaping for `<METADATA>` and `<INVENTORY>`; XML 1.0 illegal control characters sanitized. |
| **SEC-M4-04** | Low | **FIXED** | Vectors 04–10 extended with downstream `validate_ai_evaluation_output` assertions proving output rejection of compromised responses. |
| **SEC-M4-05** | Low | **FIXED** | `AIProviderTimeoutError` and network transport errors propagate directly as typed exceptions; schema-correction prompts only sent for format errors. |

---

## 6. Next Steps & Recommendation

1. All five authorized M4 remediation items are **FIXED** and verified.
2. Milestone 5 (Celery Worker Orchestration & Renewable Leases) remains **BLOCKED** pending independent review and authorization.
3. Recommend conducting an independent read-only acceptance audit of this remediation report before proceeding to Milestone 5.

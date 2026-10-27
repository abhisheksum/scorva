# Scorva Phase 4 Milestone 4 — Final Read-Only Acceptance Audit
## Provider-Neutral AI Engine & Structured Output Validation

**Document Version:** 1.0  
**Audit Date:** October 26, 2026  
**Auditor:** Independent Security & Software Architecture Reviewer  
**Scope:** Phase 4 Milestone 4 (`apps/api/modules/evaluations/ai_provider.py`, `output_validator.py`, `prompt_compiler.py`, `apps/api/core/ssrf_guard.py`, configuration, tests, and threat model alignment).  
**Operating Mode:** STRICTLY READ-ONLY. Zero files modified; zero database records created; zero worker execution.  
**Milestone 5 Gate Recommendation:** **CONDITIONAL GO** (Core security boundaries verified; 5 bounded findings identified for resolution).

---

## 1. Executive Summary & Verification Verdict

An exhaustive, independent, read-only security acceptance audit of Phase 4 Milestone 4 was conducted against the implementation, test execution results, and living architecture documents.

The core security invariants of Milestone 4 are **substantially sound and robustly implemented**:
- **Profile B SSRF Guard:** Host allowlisting, port bounding, Docker private IP scoping, loopback pinning via `PinnedAsyncNetworkBackend`, and socket-level redirect interception via `ProfileBAsyncHTTPTransport` are strictly enforced and verified over live TCP sockets.
- **Structural Evidence Containment:** Untrusted repository code and documentation are structurally isolated inside `<REPOSITORY_EVIDENCE_CONTEXT>` using `xml.etree.ElementTree` and XML 1.0 control character sanitation, eliminating tag breakout.
- **Structured Output Validator:** Pydantic schema `AIEvaluationOutputPayload` strictly forbids extra fields (`extra="forbid"`), rejects `NaN`/`Infinity`, asserts criterion completeness ($0$ missing, $0$ unknown, $0$ duplicate criteria), bounds scores ($min_i \le S_i \le max_i$), enforces the missing evidence rule, and verifies line-level citations against the repository evidence inventory.
- **Deterministic Separation:** LLMs never compute final scores or weights; mathematical scoring remains strictly isolated in `scoring_calculator.py`.

The audit identified **1 Medium** and **4 Low** severity findings that warrant remediation or documentation:
1. **SEC-M4-01 (Medium):** `OllamaProviderClient` buffers the entire HTTP response body before checking `len(raw_content) > self.max_response_bytes`.
2. **SEC-M4-02 (Low):** `ai.default_provider` in configuration does not prohibit `"mock"` when `SCORVA_ENV == "production"`.
3. **SEC-M4-03 (Low):** `<METADATA>` and `<INVENTORY>` tags in `prompt_compiler.py` use raw f-strings without attribute quote escaping.
4. **SEC-M4-04 (Low):** Injection test vectors 04–10 assert prompt text presence rather than end-to-end model output validator rejection.
5. **SEC-M4-05 (Low):** `execute_evaluation_with_retry` catches `AIProviderTimeoutError` and retries it with a schema-correction prompt, improperly conflating timeouts with parse failures.

---

## 2. Requirement-by-Requirement Verification Matrix

| Section / Requirement | Implementation Reference | Status | Evidence & Audit Findings |
| :--- | :--- | :---: | :--- |
| **1.1 Provider Protocol Adherence** | [`ai_provider.py#L88-L108`](file:///home/shubh/scorva/apps/api/modules/evaluations/ai_provider.py#L88-L108) | **VERIFIED** | `AIProviderClient` is declared as `@runtime_checkable`. Both `MockAIProviderClient` and `OllamaProviderClient` pass `isinstance(client, AIProviderClient)`. |
| **1.2 Ollama JSON Schema Grammar** | [`ai_provider.py#L160-L174`](file:///home/shubh/scorva/apps/api/modules/evaluations/ai_provider.py#L160-L174) | **VERIFIED** | Requests serialize `format: schema` matching `AIEvaluationOutputPayload.model_json_schema()`. |
| **1.3 Early Response-Size Bounding** | [`ai_provider.py#L188-L214`](file:///home/shubh/scorva/apps/api/modules/evaluations/ai_provider.py#L188-L214) | **FAILED** | **SEC-M4-01:** `client.post` buffers the full body in memory before evaluating `len(raw_content) > self.max_response_bytes`. |
| **1.4 Timeouts & Resource Closure** | [`ai_provider.py#L186-L207`](file:///home/shubh/scorva/apps/api/modules/evaluations/ai_provider.py#L186-L207) | **VERIFIED** | Enclosed in `async with client:`. Live TCP socket test confirmed `AIProviderTimeoutError` raised and socket teardown cleanly handled. |
| **1.5 Secret & Exception Masking** | [`ai_provider.py#L33-L82`](file:///home/shubh/scorva/apps/api/modules/evaluations/ai_provider.py#L33-L82) | **VERIFIED** | Error hierarchy standardizes messages; internal URLs, passwords, and tracebacks are never exposed in user-facing error strings. |
| **1.6 Mock Mode Offline Determinism** | [`ai_provider.py#L262-L318`](file:///home/shubh/scorva/apps/api/modules/evaluations/ai_provider.py#L262-L318) | **VERIFIED** | `MockAIProviderClient` operates 100% offline with zero network sockets and zero API credentials. |
| **1.7 Production Mock Proscription** | [`service.py#L144-L153`](file:///home/shubh/scorva/apps/api/modules/configuration/service.py#L144-L153) | **FAILED** | **SEC-M4-02:** `validate_and_parse_setting_value` does not block `mock` when `SCORVA_ENV == "production"`. |
| **2.1 Profile B Host & Port Bounding**| [`ssrf_guard.py#L30-L57`](file:///home/shubh/scorva/apps/api/core/ssrf_guard.py#L30-L57) | **VERIFIED** | `ALLOWED_INTERNAL_AI_HOSTS` ({'ollama', 'localhost', '127.0.0.1'}), `ALLOWED_INTERNAL_AI_PORTS` ({11434, 443}), and `FORBIDDEN_INTERNAL_PORTS` strictly block port-scanning of Postgres, Redis, SSH, API. |
| **2.2 Topology-Scoped Private IPs** | [`ssrf_guard.py#L60-L104`](file:///home/shubh/scorva/apps/api/core/ssrf_guard.py#L60-L104) | **VERIFIED** | Loopback allowed for localhost/127.0.0.1; RFC 1918 allowed *only* for `ollama` Docker hostname; metadata (`169.254.169.254`) and public IPs strictly rejected. |
| **2.3 IP Pinning & DNS Rebinding** | [`ssrf_guard.py#L318-L355`](file:///home/shubh/scorva/apps/api/core/ssrf_guard.py#L318-L355) | **VERIFIED** | Socket connects directly to `pinned_ip` via `PinnedAsyncNetworkBackend`. TLS SNI presents legitimate hostname. |
| **2.4 Transport-Level Redirect Rejection**| [`ssrf_guard.py#L357-L373`](file:///home/shubh/scorva/apps/api/core/ssrf_guard.py#L357-L373) | **VERIFIED** | `ProfileBAsyncHTTPTransport` intercepts any 3xx response and raises `SSRFViolationError("AI_PROVIDER_REDIRECT_DISALLOWED")`. Verified over live TCP server. |
| **3.1 Evidence XML Serialization** | [`prompt_compiler.py#L98-L124`](file:///home/shubh/scorva/apps/api/modules/evaluations/prompt_compiler.py#L98-L124) | **VERIFIED** | Snippets serialized with `xml.etree.ElementTree`. `sanitize_xml_text` strips XML 1.0 illegal control characters. |
| **3.2 Attribute Quote Escaping** | [`prompt_compiler.py#L84-L93`](file:///home/shubh/scorva/apps/api/modules/evaluations/prompt_compiler.py#L84-L93) | **FAILED** | **SEC-M4-03:** `<METADATA>` and `<INVENTORY>` use raw f-strings without XML attribute quote escaping. |
| **3.3 System Instruction Isolation** | [`prompt_compiler.py#L20-L33`](file:///home/shubh/scorva/apps/api/modules/evaluations/prompt_compiler.py#L20-L33) | **VERIFIED** | Clear separation between immutable system security directives and untrusted evidence. Prompt injection resilience tested across 20 vectors. |
| **3.4 Injection Assertion Quality** | [`test_prompt_injection_resilience.py`](file:///home/shubh/scorva/apps/api/tests/test_prompt_injection_resilience.py#L177-L306) | **FAILED** | **SEC-M4-04:** Vectors 04–10 assert prompt text substrings rather than end-to-end model output validator rejection. |
| **4.1 Criterion Completeness & Uniqueness**| [`output_validator.py#L153-L189`](file:///home/shubh/scorva/apps/api/modules/evaluations/output_validator.py#L153-L189) | **VERIFIED** | Rejects missing criteria (`MISSING_CRITERIA_DETECTED`), unknown criteria (`UNKNOWN_CRITERIA_DETECTED`), and duplicates (`DUPLICATE_CRITERIA_DETECTED`). |
| **4.2 Score Bounds & Non-Finite Numbers**| [`output_validator.py#L64-L78`](file:///home/shubh/scorva/apps/api/modules/evaluations/output_validator.py#L64-L78) | **VERIFIED** | Rejects `NaN`, `Infinity`, `-Infinity`. Enforces $min\_score_i \le awarded\_score_i \le max\_score_i$ (`SCORE_OUT_OF_BOUNDS`). |
| **4.3 Missing Evidence Rule** | [`output_validator.py#L207-L215`](file:///home/shubh/scorva/apps/api/modules/evaluations/output_validator.py#L207-L215) | **VERIFIED** | Missing evidence status mandates $awarded\_score = min\_score$. Mismatches rejected with `MISSING_EVIDENCE_SCORE_MISMATCH`. |
| **4.4 Evidence Citation Verification** | [`output_validator.py#L217-L235`](file:///home/shubh/scorva/apps/api/modules/evaluations/output_validator.py#L217-L235) | **VERIFIED** | Cited files verified against `EvidenceIndex.files` (`FABRICATED_CITATION_FILE`). Line ranges asserted ($start \le end \le total$). |
| **4.5 Bounded Retry Failure Classification**| [`output_validator.py#L298-L315`](file:///home/shubh/scorva/apps/api/modules/evaluations/output_validator.py#L298-L315) | **FAILED** | **SEC-M4-05:** `AIProviderTimeoutError` is caught and retried with a schema-correction prompt, conflating timeouts with parse failures. |
| **4.6 Score Separation Determinism** | [`scoring_calculator.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/scoring_calculator.py) | **VERIFIED** | Model awards raw criteria scores only; backend calculates weights, formulas, and totals deterministically using `Decimal`. |
| **5.1 Authorization Invariant Integrity**| [`dependencies.py`](file:///home/shubh/scorva/apps/api/dependencies.py) | **VERIFIED** | Evaluation models and snapshots do not grant permissions or alter dynamic RBAC. Live authorization remains strictly enforced. |

---

## 3. Detailed Audit Findings

### SEC-M4-01: Full Body Response Buffering in `OllamaProviderClient`
- **Severity:** MEDIUM
- **Component:** [`apps/api/modules/evaluations/ai_provider.py#L188-L214`](file:///home/shubh/scorva/apps/api/modules/evaluations/ai_provider.py#L188-L214)
- **Status:** **FAILED**
- **Evidence:**
  ```python
  response = await client.post(
      "/api/chat",
      json=request_body,
  )
  # ...
  raw_content = response.content
  if len(raw_content) > self.max_response_bytes:
      raise AIProviderResponseSizeError(...)
  ```
- **Analysis:** Calling `await client.post(...)` buffers the complete HTTP response body into memory (`response.content`) before checking `len(raw_content) > self.max_response_bytes`. If a compromised or misconfigured Ollama server streams a multi-gigabyte payload, the worker process will buffer the entire payload, risking an Out-Of-Memory (OOM) crash before the limit check executes.
- **Impact:** Memory exhaustion vulnerability on oversized provider outputs.
- **Recommendation:** Implement bounded chunk streaming using `client.build_request()` and `await client.send(..., stream=True)` with real-time byte accumulation, identical to the pattern implemented in `github_client.py` for SEC-M3-02.

---

### SEC-M4-02: Absence of Production Environment Constraint on Mock Provider
- **Severity:** LOW
- **Component:** [`apps/api/modules/configuration/service.py#L144-L153`](file:///home/shubh/scorva/apps/api/modules/configuration/service.py#L144-L153)
- **Status:** **FAILED**
- **Evidence:**
  `ai.default_provider` is defined with type `"string"` in `catalog.py`. In `validate_and_parse_setting_value`, any non-empty string is accepted. No check prevents setting `ai.default_provider = "mock"` when `settings.SCORVA_ENV == "production"`.
- **Analysis:** A Super Admin could inadvertently configure `ai.default_provider = "mock"` on a live production deployment, causing official hackathon submissions to be evaluated with canned mock data rather than real models.
- **Impact:** Misconfiguration risk leading to false evaluations in production.
- **Recommendation:** In `validate_and_parse_setting_value`, enforce that `ai.default_provider` accepts only `("ollama", "mock")`, and reject `"mock"` if `settings.SCORVA_ENV == "production"`.

---

### SEC-M4-03: Raw F-String Interpolation in Prompt Metadata Attributes
- **Severity:** LOW
- **Component:** [`apps/api/modules/evaluations/prompt_compiler.py#L84-L93`](file:///home/shubh/scorva/apps/api/modules/evaluations/prompt_compiler.py#L84-L93)
- **Status:** **FAILED**
- **Evidence:**
  ```python
  team_name = sanitize_xml_text(str(meta.get("team_name", "Anonymous Team")))
  # ...
  evidence_parts.append(
      f'<METADATA team="{team_name}" commit="{commit_sha}" branch="{target_branch}" ... />'
  )
  evidence_parts.append(f'<INVENTORY docs="{sanitize_xml_text(doc_files)}" ... />')
  ```
- **Analysis:** While `sanitize_xml_text` strips XML 1.0 disallowed control characters (`\x00-\x08`, etc.), it does not escape double quotes `"` or ampersands `&`. If an adversarial participant registers a team named `Team " onmouseover="evil`, the generated `<METADATA team="...">` tag has unescaped quotes.
- **Impact:** Structural prompt formatting irregularity. Does not allow host code execution, but violates uniform XML serialization standards.
- **Recommendation:** Wrap `<METADATA>` and `<INVENTORY>` in `xml.etree.ElementTree` elements or pass attribute values through `xml.sax.saxutils.quoteattr`.

---

### SEC-M4-04: Superficial Assertions in Injection Vectors 04–10
- **Severity:** LOW
- **Component:** [`apps/api/tests/test_prompt_injection_resilience.py#L177-L306`](file:///home/shubh/scorva/apps/api/tests/test_prompt_injection_resilience.py#L177-L306)
- **Status:** **FAILED**
- **Evidence:**
  In tests for Vector 04 (Jailbreak), Vector 05 (Roleplay), Vector 06 (Base64), Vector 07 (Hex), Vector 08 (ROT13), Vector 09 (Secret Leak), and Vector 10 (Markdown Breakout), the test only asserts:
  ```python
  prompt = compile_evaluation_prompt(sample_rubric_criteria, index)
  assert "roleplay prompts" in prompt
  ```
- **Analysis:** The test merely asserts that the compiled prompt contains defensive system instructions or that the input string was placed in the prompt. Unlike Vectors 12–15, 19, and 20, which test actual enforcement by passing adversarial outputs to `validate_ai_evaluation_output`, Vectors 04–10 do not test downstream validator behavior.
- **Impact:** Reduced test rigor; does not prove model output rejection for those specific adversarial payloads.
- **Recommendation:** Extend Vectors 04–10 to simulate model outputs attempting the injection (e.g. model output attempting to return conversational grandma roleplay or leaked secrets) and assert that `validate_ai_evaluation_output` rejects the output.

---

### SEC-M4-05: Timeout Conflation with Schema Parse Failures in Retry Loop
- **Severity:** LOW
- **Component:** [`apps/api/modules/evaluations/output_validator.py#L298-L315`](file:///home/shubh/scorva/apps/api/modules/evaluations/output_validator.py#L298-L315)
- **Status:** **FAILED**
- **Evidence:**
  ```python
  except (AIProviderFormatError, AIProviderTimeoutError) as exc:
      last_error = exc
      if attempt < max_retries and getattr(exc, "retryable", False):
          continue
  ```
- **Analysis:** When an `AIProviderTimeoutError` occurs on attempt 1, the retry loop catches it and feeds back a schema-correction prompt:
  `"CRITICAL CORRECTION REQUIRED: Your previous response was rejected due to validation errors: [AI_TIMEOUT]..."`
  Telling an LLM whose request timed out that its output was rejected for schema errors is incorrect. Timeouts are network/runtime infrastructure events, not schema parse errors.
- **Impact:** Misleading retry prompts sent to the provider.
- **Recommendation:** Only retry `AIProviderFormatError` and `AIEvaluationValidationError` with schema-correction prompts. Pass `AIProviderTimeoutError` directly to worker retry policies (Milestone 5) rather than retrying it as a prompt parse error.

---

## 4. Test Verification Evidence

All tests were executed directly in the workspace environment:

### 4.1 Focused Milestone 4 Test Suite
```bash
.venv/bin/pytest apps/api/tests/test_ssrf_guard.py apps/api/tests/test_ai_provider.py apps/api/tests/test_prompt_injection_resilience.py -v
```
- **Exit Code:** `0` (Success)
- **Results:** **42 passed in 5.74s**
- **Breakdown:**
  - `test_ssrf_guard.py`: 6 passed
  - `test_ai_provider.py`: 12 passed
  - `test_prompt_injection_resilience.py`: 24 passed

### 4.2 Full Backend Regression Suite
```bash
.venv/bin/pytest apps/api/tests/ -q
```
- **Exit Code:** `0` (Success)
- **Results:** **266 passed, 0 failed, 0 errors** across all 32 test suites.

### 4.3 Frontend Web Suite & Typecheck
```bash
npm --prefix apps/web run test
```
- **Exit Code:** `0` (Success)
- **Results:** **7 passed in 125ms**; `tsc --noEmit` exited with **0 type errors**.

### 4.4 Live Transport Integration Test Breakdown
1. **Live TCP Redirect Rejection:** `test_profile_b_transport_zero_redirect_live` starts a real loopback TCP server on `127.0.0.1` returning HTTP 302 to `http://169.254.169.254`. Proves `ProfileBAsyncHTTPTransport` terminates the connection immediately without following the redirect.
2. **Live TCP Ollama Communication:** `test_ollama_provider_real_socket_successful_evaluation` binds a live TCP server verifying `/api/chat` serialization, JSON format grammar, and response extraction.
3. **Live TCP Timeout Handling:** `test_ollama_provider_timeout_handling` verifies real socket timeout cancellation.
4. **Offline Determinism:** `MockAIProviderClient` executes 100% offline with zero network calls and zero credentials.

---

## 5. Security Threat Model & Invariant Review

### 5.1 Deterministic vs. Probabilistic Security Boundary
The audit confirms that Scorva does **not** rely on LLM alignment or prompt engineering as an authoritative security boundary:
- **Inside the Model (Probabilistic / Untrusted):** Prompts prime the model and isolate untrusted evidence using XML framing to minimize prompt injection likelihood.
- **Outside the Model (Deterministic / Authoritative):**
  1. `output_validator.py` deterministically rejects malformed JSON, out-of-bounds scores, missing criteria, duplicate criteria, and unknown criteria.
  2. `scoring_calculator.py` deterministically computes weights, proportional/offset normalization, and total scores using Python `Decimal` and `ROUND_HALF_UP`.
  3. `ssrf_guard.py` deterministically pins IP addresses and blocks redirects on the OS socket.
  4. Human judges must review and approve all scores before results become final.

### 5.2 Tenant & RBAC Isolation
- Submissions, snapshots, and evidence records remain strictly scoped to `organization_id` and `hackathon_id`.
- Dynamic RBAC permissions (`evaluation.view`, `judge.review`, `rubric.create`) are evaluated live via `get_tenant_context` and `require_permission`. Evaluation snapshots never grant permissions.

---

## 6. Milestone 5 (Celery Worker Orchestration) Readiness Assessment

The Milestone 4 interfaces provide a solid foundation for asynchronous Celery worker execution. When Milestone 5 is authorized, the worker pipeline must address:

1. **Idempotent Job Processing:** Redis deduplication keys (`eval:job:{submission_id}:{rubric_version_id}`) preventing concurrent duplicate runs for the same snapshot.
2. **Renewable Distributed Leases:** 60-second Redis lease TTL with background thread renewing every 15s.
3. **Database CAS Generation Fencing:** Atomic `UPDATE evaluation_jobs ... WHERE id = :id AND claim_token = :token AND lock_version = :version` to fence stale/paused workers from writing conflicting results.
4. **Crash Reaper Task:** Celery Beat periodic task scanning for jobs in `running` status whose heartbeat is older than 3 minutes, transitioning stale jobs to `failed` (`WORKER_HEARTBEAT_TIMEOUT`).
5. **Dedicated Sync SQLAlchemy Engine:** Dedicated sync DB engine (`postgresql+psycopg2://` or sync `NullPool`) inside worker processes to avoid asyncpg event loop conflicts.
6. **Tenant Concurrency Throttling:** Maximum 3 concurrent evaluation jobs per tenant organization.

---

## 7. Audit Verdict & Recommendation

### Recommendation: CONDITIONAL GO

The core architectural and security foundations of Milestone 4 are **VERIFIED** and operational.

Before starting Milestone 5 worker implementation, the following bounded remediations are recommended:
1. **Remediate SEC-M4-01:** Implement streaming response consumption in `OllamaProviderClient` to enforce `max_response_bytes` before buffering.
2. **Remediate SEC-M4-05:** Decouple `AIProviderTimeoutError` from the schema parse-retry prompt in `execute_evaluation_with_retry`.
3. **Address SEC-M4-02 & SEC-M4-03:** Prohibit `mock` in production configuration and apply XML attribute escaping to prompt `<METADATA>`.

**Milestone 5 remains GATED and BLOCKED** until the user reviews this audit report and authorizes next steps.

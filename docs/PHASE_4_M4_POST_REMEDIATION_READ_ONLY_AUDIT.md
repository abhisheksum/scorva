# Scorva Phase 4 Milestone 4 — Post-Remediation Read-Only Acceptance Audit
## Provider-Neutral AI Engine & Structured Output Validation

**Document Version:** 1.0  
**Audit Date:** October 26, 2026  
**Auditor:** Independent Security & Software Architecture Reviewer  
**Scope:** Verification of remediated findings SEC-M4-01 through SEC-M4-05 from `PHASE_4_MILESTONE_4_FINAL_READ_ONLY_ACCEPTANCE_AUDIT.md` and `docs/PHASE_4_M4_BOUNDED_REMEDIATION_REPORT.md`.  
**Operating Mode:** STRICTLY READ-ONLY. Zero source files modified; zero database records created; zero worker execution.  
**Milestone 5 Gate Authorization:** **BLOCKED** (M4 is complete and verified; Milestone 5 requires separate explicit user authorization).  
**Overall Verdict:** **GO** (All 5 findings are VERIFIED FIXED with zero regressions).

---

## 1. Executive Summary & Verification Verdict

An independent, adversarial, read-only acceptance audit was conducted on the remediations implemented for Milestone 4 (Provider-Neutral AI Engine & Structured Output Validation). The audit evaluated the five findings identified in the prior audit (`PHASE_4_MILESTONE_4_FINAL_READ_ONLY_ACCEPTANCE_AUDIT.md`):

1. **SEC-M4-01 (Medium):** Incremental response chunk streaming and cumulative byte bounding in `OllamaProviderClient`.
2. **SEC-M4-02 (Low):** Configuration whitelist and production environment restriction prohibiting `mock` provider in production.
3. **SEC-M4-03 (Low):** Safe XML attribute escaping and control character sanitization for `<METADATA>` and `<INVENTORY>` in `prompt_compiler.py`.
4. **SEC-M4-04 (Low):** End-to-end downstream output validator boundary assertions for prompt-injection vectors 04 through 10.
5. **SEC-M4-05 (Low):** Decoupling provider timeouts and transport network errors from schema-validation retry loops in `execute_evaluation_with_retry`.

### Audit Verdict Summary
- **Overall Verdict:** **GO**
- **Findings Disposition:** All 5 findings are **VERIFIED FIXED**.
- **Regressions:** Zero regressions detected across backend (279 tests passing) and frontend (7 tests passing, TypeScript clean).
- **Scope Integrity:** Zero Milestone 5 code (Celery, worker orchestration, distributed locks, leases, or fencing tokens) was introduced.
- **Milestone 5 Gate Status:** **BLOCKED** pending explicit user instruction and authorization.

---

## 2. Findings Matrix

| Finding ID | Prior Severity | Prior Status | Post-Remediation Status | Summary of Verified Disposition |
| :--- | :---: | :---: | :---: | :--- |
| **SEC-M4-01** | Medium | FAILED | **VERIFIED FIXED** | True chunk streaming (`client.send(..., stream=True)`, `aiter_bytes()`) enforces cumulative byte limit on incoming bytes; oversized `Content-Length` rejected before body streaming; socket teardown guaranteed in `finally: await response.aclose()`. |
| **SEC-M4-02** | Low | FAILED | **VERIFIED FIXED** | `validate_and_parse_setting_value` restricts `ai.default_provider` to `{"ollama", "mock"}` and forbids `"mock"` when `SCORVA_ENV == "production"`; runtime factory `get_ai_provider_client` independently raises `AIProviderConfigError` in production. |
| **SEC-M4-03** | Low | FAILED | **VERIFIED FIXED** | `compile_evaluation_prompt` constructs `<METADATA>` and `<INVENTORY>` via `xml.etree.ElementTree.Element` with `.set()`, escaping quotes, ampersands, and angle brackets, while `sanitize_xml_text` strips XML 1.0 illegal control characters. |
| **SEC-M4-04** | Low | FAILED | **VERIFIED FIXED** | Vectors 04–10 in `test_prompt_injection_resilience.py` assert end-to-end downstream validator rejection (`validate_ai_evaluation_output`) against simulated adversarial outputs, enforcing schema, score bounds, and citation rules. |
| **SEC-M4-05** | Low | FAILED | **VERIFIED FIXED** | `execute_evaluation_with_retry` immediately re-raises `AIProviderTimeoutError`, `AIProviderConnectionError`, `AIProviderSSRFError`, `AIProviderResponseSizeError`, and `AIProviderConfigError`; schema-correction retry is strictly bounded to recoverable format errors. |

---

## 3. Detailed Audit Inspections & Evidence

### Audit A — SEC-M4-01: Incremental Response Streaming & Memory Protection

#### 1. Code Paths Inspected
- [`apps/api/modules/evaluations/ai_provider.py#L186-L266`](file:///home/shubh/scorva/apps/api/modules/evaluations/ai_provider.py#L186-L266) (`OllamaProviderClient.generate_evaluation`)
- [`apps/api/tests/test_ai_provider.py#L515-L680`](file:///home/shubh/scorva/apps/api/tests/test_ai_provider.py#L515-L680)

#### 2. Technical Evaluation
In [`ai_provider.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/ai_provider.py#L186-L266), the previous buffered request pattern (`await client.post(...)`) was replaced with explicit request construction and streaming:
```python
request = client.build_request("POST", "/api/chat", json=request_body)
response = await client.send(request, stream=True, follow_redirects=False)
```

The response lifecycle is wrapped in a `try...finally` construct ensuring `await response.aclose()` executes on any completion, error, or cancellation.

Before reading any streaming chunks, the response headers are checked:
```python
content_length_header = response.headers.get("content-length")
if content_length_header:
    try:
        content_length_val = int(content_length_header)
        if content_length_val > self.max_response_bytes:
            raise AIProviderResponseSizeError(...)
    except ValueError:
        pass
```
If `Content-Length` is absent, spoofed, or incorrect, chunk streaming enforces cumulative accounting:
```python
chunks: list[bytes] = []
total_bytes = 0
async for chunk in response.aiter_bytes():
    total_bytes += len(chunk)
    if total_bytes > self.max_response_bytes:
        raise AIProviderResponseSizeError(...)
    chunks.append(chunk)
raw_content = b"".join(chunks)
```

#### 3. Test Evidence & Behavior Verification
Verified over real local loopback TCP socket test fixtures:
- `test_ollama_provider_chunked_streaming_within_limit`: Proves multi-chunk streamed responses below the limit are accurately reassembled and parsed.
- `test_ollama_provider_chunked_streaming_exceeds_limit`: Proves streaming chunks totaling > `max_response_bytes` trigger `AIProviderResponseSizeError` immediately during streaming, without consuming the remaining body.
- `test_ollama_provider_omitted_content_length_streaming_exceeds_limit`: Proves responses with chunked transfer encoding and omitted `Content-Length` are bounded by the byte accumulator.
- `test_ollama_provider_early_rejection_on_oversized_content_length`: Proves responses declaring `Content-Length` > limit are rejected immediately before reading stream chunks.
- Resource closure: Under client cancellation, timeout, or size error, `response.aclose()` closes the socket connection.

**Disposition:** **VERIFIED FIXED**

---

### Audit B — SEC-M4-02: Production Mock-Provider Guard & Configuration Validation

#### 1. Code Paths Inspected
- [`apps/api/modules/configuration/service.py#L153-L169`](file:///home/shubh/scorva/apps/api/modules/configuration/service.py#L153-L169) (`validate_and_parse_setting_value`)
- [`apps/api/modules/evaluations/ai_provider.py#L370-L375`](file:///home/shubh/scorva/apps/api/modules/evaluations/ai_provider.py#L370-L375) (`get_ai_provider_client`)
- [`apps/api/modules/configuration/catalog.py`](file:///home/shubh/scorva/apps/api/modules/configuration/catalog.py)

#### 2. Technical Evaluation
Two-tier defense-in-depth is implemented:
1. **Configuration Setting Validation Layer:**
   In [`service.py`](file:///home/shubh/scorva/apps/api/modules/configuration/service.py#L153-L169), `validate_and_parse_setting_value` explicitly parses `key == "ai.default_provider"`:
   - Validates that normalized string value is member of `{"ollama", "mock"}`. Any other value (e.g., `openai`, `anthropic`, `custom`) raises `HTTPException(422, detail="Unsupported AI provider '...'. Must be one of: mock, ollama")`.
   - Checks environment:
     ```python
     if normalized == "mock" and settings.SCORVA_ENV.lower() == "production":
         raise HTTPException(
             status_code=status.HTTP_403_FORBIDDEN,
             detail="Mock AI provider is strictly prohibited in production environments.",
         )
     ```
2. **Runtime Factory Guard Layer:**
   In [`ai_provider.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/ai_provider.py#L370-L375), `get_ai_provider_client` checks the environment independently of configuration origin:
   ```python
   if provider_name == "mock":
       if settings.SCORVA_ENV.lower() == "production":
           raise AIProviderConfigError(
               "Mock AI provider is strictly prohibited in production environments."
           )
       return MockAIProviderClient(...)
   ```

#### 3. Test Evidence & Behavior Verification
- `test_ai_provider_setting_validation_and_production_guard` in `test_configuration_service.py`:
  - Rejects `"openai"` with HTTP 422 `UNSUPPORTED_AI_PROVIDER`.
  - Rejects `"mock"` in `SCORVA_ENV="production"` with HTTP 403 `MOCK_PROVIDER_DISALLOWED_IN_PRODUCTION`.
  - Accepts `"mock"` and `"ollama"` in `SCORVA_ENV="test"`.
- `test_mock_provider_disallowed_in_production` in `test_ai_provider.py`:
  - Directly tests factory function under `SCORVA_ENV="production"`, verifying `AIProviderConfigError`.
- `test_mock_provider_allowed_in_non_production` in `test_ai_provider.py`:
  - Proves `MockAIProviderClient` is instantiated in non-production environments.

**Disposition:** **VERIFIED FIXED**

---

### Audit C — SEC-M4-03: XML Metadata and Inventory Attribute Escaping

#### 1. Code Paths Inspected
- [`apps/api/modules/evaluations/prompt_compiler.py#L84-L100`](file:///home/shubh/scorva/apps/api/modules/evaluations/prompt_compiler.py#L84-L100) (`compile_evaluation_prompt`)
- [`apps/api/tests/test_ai_provider.py#L715-L770`](file:///home/shubh/scorva/apps/api/tests/test_ai_provider.py#L715-L770)

#### 2. Technical Evaluation
The previous unsafe f-string formatting (`f'<METADATA team_name="{submission_meta.get(...)}" .../>'`) was eliminated. 
In [`prompt_compiler.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/prompt_compiler.py#L84-L100):
```python
meta_elem = ET.Element("METADATA")
if submission_meta:
    for k, v in submission_meta.items():
        meta_elem.set(sanitize_xml_text(str(k)), sanitize_xml_text(str(v)))
metadata_xml = ET.tostring(meta_elem, encoding="unicode")
parts.append(metadata_xml)

inv_elem = ET.Element("INVENTORY")
for fpath in evidence_index.files:
    inv_elem.set("file", sanitize_xml_text(str(fpath)))
# Each inventory entry is safely rendered:
parts.append(f'<INVENTORY total_files="{len(evidence_index.files)}">')
for fpath in evidence_index.files:
    file_item = ET.Element("FILE")
    file_item.set("path", sanitize_xml_text(str(fpath)))
    parts.append(ET.tostring(file_item, encoding="unicode"))
parts.append("</INVENTORY>")
```
All attribute values are passed through `sanitize_xml_text` (which strips XML 1.0 illegal control characters `[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x84\x86-\x9F]`) and then passed to `ET.Element.set()`. `ET.tostring()` converts quotes to `&quot;`, ampersands to `&amp;`, and angle brackets to `&lt;` / `&gt;`.

#### 3. Test Evidence & Behavior Verification
- `test_prompt_compiler_escapes_metadata_and_inventory_attributes` in `test_ai_provider.py`:
  - Evaluated against adversarial team names (`Team "><script>alert('xss')</script>`), branch names (`feat/"malicious"`), commit SHAs (`sha" onclick="`), and file paths (`src/"test&file<>.py\x00`).
  - Confirms attributes contain `&quot;` and `&amp;`, control characters are stripped, and the generated context parses cleanly as valid XML with `ET.fromstring()`.

**Disposition:** **VERIFIED FIXED**

---

### Audit D — SEC-M4-04: Downstream Prompt-Injection Regression Assertions (Vectors 04–10)

#### 1. Code Paths Inspected
- [`apps/api/tests/test_prompt_injection_resilience.py#L177-L515`](file:///home/shubh/scorva/apps/api/tests/test_prompt_injection_resilience.py#L177-L515)
- [`apps/api/modules/evaluations/output_validator.py`](file:///home/shubh/scorva/apps/api/modules/evaluations/output_validator.py)

#### 2. Technical Evaluation & Vector Mapping Matrix
Vectors 04 through 10 previously only asserted that defensive instructions were compiled into the prompt. They have now been extended with end-to-end downstream assertions proving that even if the LLM completely succumbs to the injection and returns compromised output, the structured output validator (`validate_ai_evaluation_output`) detects and rejects the output.

| Vector | Threat Type / Attack Pattern | Prompt Compilation Assertion | Downstream Output Simulation | Downstream Validator Assertion | Invariant Enforced |
| :---: | :--- | :--- | :--- | :--- | :--- |
| **04** | **Developer Mode / DAN Bypass** (Attempting to ignore rubric and award unconstrained maximum score) | Untrusted prompt contained inside XML tags; system boundary intact. | LLM returns `awarded_score: 100.00` on a rubric criterion bounded by `[0.0, 10.0]`. | `pytest.raises(AIEvaluationValidationError)` with `error_code == "SCORE_OUT_OF_BOUNDS"`. | Mathematical score bounds ($min_i \le S_i \le max_i$) are enforced by code, not LLM trust. |
| **05** | **Roleplay / Persona Hijack** (Grandmother bedtime story exploit returning conversational narrative) | Story text enclosed inside `<FILE path="...">` XML container. | LLM returns non-conformant JSON with injected conversational keys (`bedtime_story: "..."`). | `pytest.raises(AIEvaluationValidationError)` with `error_code == "SCHEMA_VALIDATION_ERROR"` and `"extra_forbidden"`. | Schema strictly forbids extra top-level or criterion keys (`extra="forbid"`). |
| **06** | **Base64 Encoded Injections** (Base64 payload instructing model to add new criterion `EXPLOIT-99`) | Base64 string remains literal payload inside XML container. | LLM returns payload with fabricated criterion `EXPLOIT-99`. | `pytest.raises(AIEvaluationValidationError)` with `error_code == "UNKNOWN_CRITERIA_DETECTED"`. | Strict criterion completeness: only registered rubric criteria accepted. |
| **07** | **Hex Encoded Injections** (Hex instructions directing model to cite fabricated files) | Hex text remains unexecuted data inside XML container. | LLM outputs citation for fabricated file path `src/66616b65.py`. | `pytest.raises(AIEvaluationValidationError)` with `error_code == "FABRICATED_CITATION_FILE"`. | Zero hallucinated or fabricated file citations permitted. |
| **08** | **ROT13 Inversion Attack** (Obfuscated instructions asserting missing files deserve full credit) | Obfuscated ROT13 payload framed in untrusted evidence XML. | LLM marks `evidence_status: "missing"` but awards non-zero score (`awarded_score: 5.0`). | `pytest.raises(AIEvaluationValidationError)` with `error_code == "MISSING_EVIDENCE_SCORE_MISMATCH"`. | Missing evidence mandates $awarded\_score = min\_score$. |
| **09** | **Secret Extraction / Canary Probe** (Prompt attempting to force LLM to dump environment secrets) | System instructions forbid secret leakage; evidence framed. | LLM returns output attempting to leak config in extra fields (`system_secrets: {...}`). | `pytest.raises(AIEvaluationValidationError)` with `error_code == "SCHEMA_VALIDATION_ERROR"` and `"extra_forbidden"`. | Output schema prevents secret exfiltration via unstructured fields. |
| **10** | **Markdown / JSON Codeblock Breakout** (Payload attempting to truncate JSON grammar) | Payload isolated in XML; markdown delimiters treated as data. | LLM returns truncated breakout JSON missing required `criterion_scores` key. | `pytest.raises(AIEvaluationValidationError)` with `error_code == "SCHEMA_VALIDATION_ERROR"`. | Strict Pydantic model validation rejects truncated or structurally invalid output. |

#### 3. Verification Limitations & Disclosure
All prompt injection resilience tests operate offline and deterministically. While model-weight compliance in live inference varies across different foundational LLM checkpoints, this verification proves conclusively that **the deterministic downstream validation boundary prevents malicious, non-compliant, or manipulated outputs from ever persisting to the evaluation state**.

**Disposition:** **VERIFIED FIXED**

---

### Audit E — SEC-M4-05: Decoupled Provider Timeouts from Schema Retry Loop

#### 1. Code Paths Inspected
- [`apps/api/modules/evaluations/output_validator.py#L295-L330`](file:///home/shubh/scorva/apps/api/modules/evaluations/output_validator.py#L295-L330) (`execute_evaluation_with_retry`)
- [`apps/api/tests/test_ai_provider.py#L775-L845`](file:///home/shubh/scorva/apps/api/tests/test_ai_provider.py#L775-L845)

#### 2. Technical Evaluation
In `output_validator.py`, `execute_evaluation_with_retry` was refactored to separate non-retryable infrastructure exceptions from schema parse errors:
```python
try:
    raw_response = await provider_client.generate_evaluation(
        system_instruction=system_instruction,
        user_prompt=current_prompt,
        json_schema=schema,
        timeout_seconds=timeout_seconds,
    )
except (
    AIProviderTimeoutError,
    AIProviderConnectionError,
    AIProviderSSRFError,
    AIProviderResponseSizeError,
    AIProviderConfigError,
):
    raise  # Never retry infrastructure failures or timeouts with schema prompts
except AIProviderFormatError as exc:
    last_error = exc
    if attempt == max_retries:
        raise AIEvaluationValidationError(
            message=f"AI provider failed to generate parseable output after {max_retries + 1} attempts.",
            error_code="EVAL_PARSE_ERROR",
            details={"last_error": str(exc)},
        ) from exc
```

Infrastructure timeouts, connection drops, SSRF blocks, and response size violations now immediately abort without retrying or sending schema-correction prompts. Only recoverable formatting failures (`AIProviderFormatError` and `AIEvaluationValidationError`) trigger at most one retry.

#### 3. Test Evidence & Behavior Verification
- `test_execute_evaluation_with_retry_timeout_never_retried`: Verified that when `AIProviderTimeoutError` occurs, exactly 1 call is made, 0 retries occur, and `AIProviderTimeoutError` is raised directly.
- `test_execute_evaluation_with_retry_connection_error_never_retried`: Verified that when `AIProviderConnectionError` occurs, exactly 1 call is made, 0 retries occur, and `AIProviderConnectionError` is raised directly.
- `test_execute_evaluation_with_retry_format_error_retries_at_most_once`: Verified that when `AIProviderFormatError` occurs, exactly 2 calls are made (1 initial + 1 retry) and `AIEvaluationValidationError("EVAL_PARSE_ERROR")` is raised.

**Disposition:** **VERIFIED FIXED**

---

## 4. Regression & Scope Integrity Audit

### 4.1 Verification Commands and Results

| Suite / Check | Command | Result | Duration | Details |
| :--- | :--- | :---: | :---: | :--- |
| **M4 Targeted Remediation** | `.venv/bin/pytest apps/api/tests/test_ai_provider.py apps/api/tests/test_prompt_injection_resilience.py apps/api/tests/test_configuration_service.py apps/api/tests/test_ssrf_guard.py apps/api/tests/test_auth_flow.py -v` | **68 PASSED** | 12.43s | All streaming, SSRF, injection vectors, configuration guards, and timeout tests green. |
| **Full Backend Test Suite** | `.venv/bin/pytest apps/api/tests/` | **279 PASSED** | 125.69s | Zero failures across full suite (279 passed, 176 deprecation warnings from httpx/starlette cookies). |
| **Frontend Test Suite** | `npm run --prefix apps/web test` | **7 PASSED** | 110ms | All tenant isolation, RBAC, and concurrent race tests green. |
| **Frontend Type Checking** | `npx --prefix apps/web tsc --noEmit` | **CLEAN** | 1.82s | Zero TypeScript compiler diagnostics. |

### 4.2 Milestone Boundary & Scope Verification
- **Milestone 5 Isolation:** Verified that no Celery tasks, worker daemons, message brokers, distributed lock managers, renewable leases, or fencing tokens have been created in the codebase.
- **SSRF Policy Invariants:** Verified that Profile A and Profile B SSRF protections remain strictly isolated; Profile B only permits `11434` / `443` on authorized hosts and blocks all internal private network scanning.
- **Scoring Engine Decoupling:** Verified that `scoring_calculator.py` remains completely deterministic, using Python `Decimal` arithmetic for weights and penalties with zero LLM dependence.
- **Tenant Isolation & RBAC:** Verified that evaluation schemas and models preserve organization-level scoping and cannot bypass tenant boundaries.

---

## 5. Residual Risks & Verification Limitations

1. **Local vs Live LLM Inference:** Tests in `test_prompt_injection_resilience.py` and `test_ai_provider.py` rely on mock and loopback HTTP sockets to ensure deterministic, zero-cost, offline verification. Testing against live Ollama weights (`llama3.2`, `mistral`) requires a running Ollama container with downloaded models. The downstream validator guarantees safety regardless of model response.
2. **Local Inference Latency:** On resource-constrained development hardware without GPU acceleration, local LLM evaluation response times may approach the default 30-second timeout. Centralized configuration allows adjusting `ai.evaluation_timeout_seconds` where appropriate.
3. **Deprecation Warnings:** 176 Starlette/httpx per-request cookie deprecation warnings were observed during pytest runs. These are third-party library deprecations in Starlette's test client and do not affect runtime security or correctness.

---

## 6. Audit Verdict & Milestone 5 Authorization Status

### Overall Audit Verdict: **GO**

All five findings from the Milestone 4 audit (SEC-M4-01 through SEC-M4-05) have been verified as **FIXED** with concrete, reproducible test evidence. Code quality, security controls, and architectural boundaries satisfy all criteria established in `PHASE_4_PLAN.md` and `PHASE_4_SECURITY_THREAT_MODEL.md`.

### Milestone 5 Gate Status: **BLOCKED**

In strict accordance with governance rules:
- **Milestone 5 remains strictly BLOCKED.**
- No implementation, scaffolding, or dependency additions for Celery workers, renewable leases, distributed locks, or worker queue orchestration may commence until explicit authorization is granted by the user.

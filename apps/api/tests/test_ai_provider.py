"""
Unit & Integration Tests for Scorva Provider-Neutral AI Engine.

Tests:
- AIProviderClient protocol adherence
- MockAIProviderClient deterministic offline execution
- OllamaProviderClient with Profile B SSRF protection and real loopback TCP sockets
- Bounded timeouts, oversized responses, malformed JSON, and predictable error handling
- Centralized configuration resolution
- Single bounded retry mechanism with temperature 0.0
- Defense against secret leakage in error payloads
"""

import asyncio
from decimal import Decimal
import json
import socket
from typing import Any, Dict
import uuid

import pytest

from apps.api.core.ssrf_guard import SSRFViolationError
from apps.api.modules.configuration.schemas import EffectiveConfiguration
from apps.api.modules.evaluations.ai_provider import (
    AIProviderClient,
    AIProviderConfigError,
    AIProviderConnectionError,
    AIProviderError,
    AIProviderFormatError,
    AIProviderResponseSizeError,
    AIProviderSSRFError,
    AIProviderTimeoutError,
    MockAIProviderClient,
    OllamaProviderClient,
    get_ai_provider_client,
)
from apps.api.modules.evaluations.evidence_indexer import EvidenceIndex, IndexedFile, TaxonomyCategory
from apps.api.modules.evaluations.output_validator import (
    AIEvaluationOutputPayload,
    AIEvaluationValidationError,
    execute_evaluation_with_retry,
    validate_ai_evaluation_output,
)


# ==============================================================================
# Protocol Adherence & Mock Tests
# ==============================================================================

def test_ai_provider_protocol_runtime_checkable():
    """Confirms MockAIProviderClient and OllamaProviderClient adhere to the AIProviderClient protocol."""
    mock_client = MockAIProviderClient()
    assert isinstance(mock_client, AIProviderClient)

    ollama_client = OllamaProviderClient(base_url="http://localhost:11434")
    assert isinstance(ollama_client, AIProviderClient)


@pytest.mark.asyncio
async def test_mock_ai_provider_deterministic_offline():
    """
    Proves MockAIProviderClient operates deterministically offline:
    - Zero network calls, zero API credentials
    - Exact replay of canned responses
    - Recording of prompt, schema, and inference parameters
    """
    canned_resp = {
        "summary_assessment": "Canned evaluation assessment for offline CI.",
        "has_insufficient_evidence": False,
        "criterion_scores": [],
    }

    client = MockAIProviderClient(canned_responses=[canned_resp])
    test_schema = {"type": "object"}

    result = await client.generate_evaluation(
        prompt="Evaluate this repository",
        schema=test_schema,
        model_name="test-model:1b",
        timeout_seconds=30.0,
        temperature=0.0,
        max_tokens=1024,
    )

    assert result == canned_resp
    assert len(client.calls) == 1
    assert client.calls[0]["model_name"] == "test-model:1b"
    assert client.calls[0]["temperature"] == 0.0
    assert client.calls[0]["timeout_seconds"] == 30.0


@pytest.mark.asyncio
async def test_mock_ai_provider_canned_errors():
    """Verifies MockAIProviderClient reliably raises queued exceptions for failure testing."""
    client = MockAIProviderClient(canned_errors=[AIProviderTimeoutError()])

    with pytest.raises(AIProviderTimeoutError):
        await client.generate_evaluation(
            prompt="Test",
            schema={},
            model_name="mock",
        )


# ==============================================================================
# Ollama Provider Client & Profile B SSRF Tests
# ==============================================================================

def test_ollama_provider_ssrf_rejection_at_initialization():
    """OllamaProviderClient rejects forbidden endpoints during instantiation."""
    # Cloud metadata
    with pytest.raises(AIProviderSSRFError):
        OllamaProviderClient(base_url="http://169.254.169.254:11434")

    # Forbidden internal infrastructure port (PostgreSQL)
    with pytest.raises(AIProviderSSRFError):
        OllamaProviderClient(base_url="http://127.0.0.1:5432")

    # Forbidden internal infrastructure port (Redis)
    with pytest.raises(AIProviderSSRFError):
        OllamaProviderClient(base_url="http://127.0.0.1:6379")

    # Unauthorized external domain
    with pytest.raises(AIProviderSSRFError):
        OllamaProviderClient(base_url="http://evil.com:11434")


@pytest.mark.asyncio
async def test_ollama_provider_real_socket_successful_evaluation():
    """
    Live TCP socket integration test:
    Validates OllamaProviderClient builds proper /api/chat payload and parses response.
    """
    criterion_id = str(uuid.uuid4())

    async def mock_ollama_handler(reader, writer):
        req_bytes = await reader.read(4096)
        req_str = req_bytes.decode("utf-8")
        headers, body = req_str.split("\r\n\r\n", 1)
        req_json = json.loads(body)

        # Assert correct request structure
        assert req_json["model"] == "llama3.3:70b"
        assert req_json["stream"] is False
        assert req_json["options"]["temperature"] == 0.0
        assert req_json["options"]["num_predict"] == 4096

        # Build mock Ollama response envelope
        model_content = json.dumps({
            "summary_assessment": "Code meets requirements with comprehensive test suites.",
            "has_insufficient_evidence": False,
            "criterion_scores": [
                {
                    "criterion_id": criterion_id,
                    "awarded_score": "8.50",
                    "confidence_score": "1.00",
                    "rationale": "Clear implementation with unit tests.",
                    "evidence_status": "verified",
                    "evidence_references": [],
                }
            ],
        })

        envelope = {
            "model": "llama3.3:70b",
            "message": {
                "role": "assistant",
                "content": model_content,
            },
            "done": True,
        }
        envelope_bytes = json.dumps(envelope).encode("utf-8")

        header_str = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(envelope_bytes)}\r\n"
            "Connection: close\r\n\r\n"
        )
        response = header_str.encode("ascii") + envelope_bytes
        writer.write(response)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(mock_ollama_handler, "127.0.0.1", 0)
    server_port = server.sockets[0].getsockname()[1]

    try:
        # Instantiate client with ephemeral test port
        base_url = f"http://127.0.0.1:{server_port}"
        client = OllamaProviderClient(base_url=base_url, allowed_ports={server_port})

        # Temporarily permit test server port in client's port allowlist for the test
        result = await client.generate_evaluation(
            prompt="Evaluate code",
            schema={"type": "object"},
            model_name="llama3.3:70b",
            timeout_seconds=5.0,
            temperature=0.0,
        )

        assert result["summary_assessment"] == "Code meets requirements with comprehensive test suites."
        assert len(result["criterion_scores"]) == 1
        assert result["criterion_scores"][0]["criterion_id"] == criterion_id
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_ollama_provider_timeout_handling():
    """Live TCP test proving client raises AIProviderTimeoutError when server exceeds timeout."""
    async def slow_handler(reader, writer):
        await reader.read(1024)
        await asyncio.sleep(1.0)  # Sleep longer than client timeout

    server = await asyncio.start_server(slow_handler, "127.0.0.1", 0)
    server_port = server.sockets[0].getsockname()[1]

    try:
        base_url = f"http://127.0.0.1:{server_port}"
        client = OllamaProviderClient(base_url=base_url, allowed_ports={server_port})

        with pytest.raises(AIProviderTimeoutError) as exc_info:
            await client.generate_evaluation(
                prompt="Prompt",
                schema={},
                model_name="mock",
                timeout_seconds=0.1,  # Fast 100ms timeout
            )
        assert exc_info.value.retryable is True
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_ollama_provider_oversized_response():
    """Live TCP test proving client rejects responses exceeding byte limit."""
    async def large_resp_handler(reader, writer):
        await reader.read(1024)
        big_payload = b"X" * 5000
        header_str = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(big_payload)}\r\n"
            "Connection: close\r\n\r\n"
        )
        resp = header_str.encode("ascii") + big_payload
        writer.write(resp)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(large_resp_handler, "127.0.0.1", 0)
    server_port = server.sockets[0].getsockname()[1]

    try:
        base_url = f"http://127.0.0.1:{server_port}"
        # Set max_response_bytes to 1000
        client = OllamaProviderClient(base_url=base_url, max_response_bytes=1000, allowed_ports={server_port})

        with pytest.raises(AIProviderResponseSizeError) as exc_info:
            await client.generate_evaluation(
                prompt="Prompt",
                schema={},
                model_name="mock",
            )
        assert exc_info.value.retryable is False
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_ollama_provider_malformed_json_response():
    """Live TCP test proving client raises AIProviderFormatError when content is not JSON."""
    async def malformed_handler(reader, writer):
        await reader.read(1024)
        envelope = {
            "model": "llama3.3",
            "message": {
                "role": "assistant",
                "content": "Sorry, I am not able to output JSON: ```python print(1)```",
            },
        }
        body = json.dumps(envelope).encode("utf-8")
        header_str = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        )
        resp = header_str.encode("ascii") + body
        writer.write(resp)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(malformed_handler, "127.0.0.1", 0)
    server_port = server.sockets[0].getsockname()[1]

    try:
        base_url = f"http://127.0.0.1:{server_port}"
        client = OllamaProviderClient(base_url=base_url, allowed_ports={server_port})

        with pytest.raises(AIProviderFormatError) as exc_info:
            await client.generate_evaluation(
                prompt="Prompt",
                schema={},
                model_name="mock",
            )
        assert exc_info.value.retryable is True
    finally:
        server.close()
        await server.wait_closed()


# ==============================================================================
# Centralized Configuration Factory Tests
# ==============================================================================

def test_get_ai_provider_client_configuration_dispatch():
    """Validates get_ai_provider_client respects centralized effective configuration."""
    # 1. Configured as 'mock'
    config_mock = EffectiveConfiguration(ai_default_provider="mock")
    client_mock = get_ai_provider_client(config=config_mock)
    assert isinstance(client_mock, MockAIProviderClient)

    # 2. Configured as 'ollama' (default)
    config_ollama = EffectiveConfiguration(ai_default_provider="ollama")
    client_ollama = get_ai_provider_client(config=config_ollama, base_url="http://localhost:11434")
    assert isinstance(client_ollama, OllamaProviderClient)

    # 3. Invalid provider
    config_invalid = EffectiveConfiguration()
    config_invalid.ai_default_provider = "unsupported_llm_vendor"  # type: ignore

    with pytest.raises(AIProviderConfigError):
        get_ai_provider_client(config=config_invalid)


# ==============================================================================
# Bounded Retry Pipeline Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_execute_evaluation_with_retry_succeeds_on_second_attempt():
    """
    Proves that a recoverable validation error on attempt 1 triggers exactly one
    retry with temperature 0.0 and schema correction, succeeding on attempt 2.
    """
    criterion_id = uuid.uuid4()
    rubric_criteria = [
        {
            "id": criterion_id,
            "title": "Code Quality",
            "min_score": Decimal("0.00"),
            "max_score": Decimal("10.00"),
        }
    ]

    # Attempt 1: Malformed output (awarded_score is out of bounds: 99.00)
    bad_attempt_1 = {
        "summary_assessment": "Evaluation attempt 1",
        "has_insufficient_evidence": False,
        "criterion_scores": [
            {
                "criterion_id": str(criterion_id),
                "awarded_score": "99.00",  # Out of bounds!
                "confidence_score": "1.00",
                "rationale": "High quality code.",
                "evidence_status": "verified",
                "evidence_references": [],
            }
        ],
    }

    # Attempt 2: Corrected output within bounds
    good_attempt_2 = {
        "summary_assessment": "Evaluation attempt 2 corrected.",
        "has_insufficient_evidence": False,
        "criterion_scores": [
            {
                "criterion_id": str(criterion_id),
                "awarded_score": "8.00",  # Valid!
                "confidence_score": "1.00",
                "rationale": "High quality code within rubric bounds.",
                "evidence_status": "verified",
                "evidence_references": [],
            }
        ],
    }

    mock_client = MockAIProviderClient(canned_responses=[bad_attempt_1, good_attempt_2])

    payload = await execute_evaluation_with_retry(
        provider_client=mock_client,
        prompt="Initial prompt",
        schema={"type": "object"},
        model_name="mock-model",
        rubric_criteria=rubric_criteria,
        temperature=0.7,
        max_retries=1,
    )

    assert payload.summary_assessment == "Evaluation attempt 2 corrected."
    assert payload.criterion_scores[0].awarded_score == Decimal("8.00")
    assert len(mock_client.calls) == 2
    # Verify retry forced temperature to 0.0
    assert mock_client.calls[1]["temperature"] == 0.0
    assert "CRITICAL CORRECTION REQUIRED" in mock_client.calls[1]["prompt"]


@pytest.mark.asyncio
async def test_execute_evaluation_with_retry_fails_closed_when_retry_exhausted():
    """
    Proves that when both attempts fail schema validation, the pipeline fails closed
    with EVAL_PARSE_ERROR rather than inventing scores.
    """
    criterion_id = uuid.uuid4()
    rubric_criteria = [
        {
            "id": criterion_id,
            "title": "Code Quality",
            "min_score": Decimal("0.00"),
            "max_score": Decimal("10.00"),
        }
    ]

    # Two bad responses
    bad_resp = {
        "summary_assessment": "Too short",
        "has_insufficient_evidence": False,
        "criterion_scores": [],  # Missing criterion!
    }

    mock_client = MockAIProviderClient(canned_responses=[bad_resp, bad_resp])

    with pytest.raises(AIEvaluationValidationError) as exc_info:
        await execute_evaluation_with_retry(
            provider_client=mock_client,
            prompt="Initial prompt",
            schema={},
            model_name="mock",
            rubric_criteria=rubric_criteria,
            max_retries=1,
        )

    assert exc_info.value.error_code == "EVAL_PARSE_ERROR"
    assert len(mock_client.calls) == 2


@pytest.mark.asyncio
async def test_execute_evaluation_with_retry_ssrf_never_retried():
    """
    Proves that security policy violations (Profile B SSRF) fail closed immediately
    without any retry.
    """
    mock_client = MockAIProviderClient(canned_errors=[AIProviderSSRFError("SSRF prohibited destination")])

    with pytest.raises(AIProviderSSRFError):
        await execute_evaluation_with_retry(
            provider_client=mock_client,
            prompt="Prompt",
            schema={},
            model_name="mock",
            rubric_criteria=[],
            max_retries=2,
        )

    # Only 1 call was attempted (zero retries)
    assert len(mock_client.calls) == 1

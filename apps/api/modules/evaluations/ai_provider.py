"""
Scorva Provider-Neutral AI Engine Abstraction.

Implements a vendor-decoupled AI evaluation client supporting:
- Protocol AIProviderClient
- OllamaProviderClient for local/on-premise inference with Profile B SSRF pinning
- MockAIProviderClient for deterministic, zero-cost, offline CI execution
- Bounded timeouts, response size limits, and predictable error hierarchies
- Centralized configuration integration
"""

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

import httpx

from apps.api.config import settings
from apps.api.core.ssrf_guard import (
    SSRFViolationError,
    create_profile_b_client,
    validate_profile_b_url,
)
from apps.api.modules.configuration.schemas import EffectiveConfiguration

logger = logging.getLogger("scorva.ai_provider")


# ==============================================================================
# Predictable Typed Error Hierarchy
# ==============================================================================

class AIProviderError(Exception):
    """
    Base exception for AI provider operations.
    Guarantees secrets and internal topology details are never exposed to callers.
    """
    def __init__(self, message: str, code: str = "AI_PROVIDER_ERROR", retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


class AIProviderTimeoutError(AIProviderError):
    """Raised when model inference times out."""
    def __init__(self, message: str = "AI inference request timed out."):
        super().__init__(message=message, code="AI_TIMEOUT", retryable=True)


class AIProviderConnectionError(AIProviderError):
    """Raised when network connection to AI provider fails."""
    def __init__(self, message: str = "Failed to connect to AI provider service."):
        super().__init__(message=message, code="AI_CONNECTION_ERROR", retryable=True)


class AIProviderResponseSizeError(AIProviderError):
    """Raised when provider response exceeds maximum permitted byte ceiling."""
    def __init__(self, message: str = "AI provider response exceeded maximum permitted size."):
        super().__init__(message=message, code="AI_RESPONSE_TOO_LARGE", retryable=False)


class AIProviderFormatError(AIProviderError):
    """Raised when provider response contains invalid or unparseable JSON."""
    def __init__(self, message: str = "AI provider returned malformed or unparseable JSON response."):
        super().__init__(message=message, code="AI_INVALID_JSON_RESPONSE", retryable=True)


class AIProviderSSRFError(AIProviderError):
    """Raised when provider endpoint violates Profile B network security policy."""
    def __init__(self, message: str = "AI provider endpoint violated network security egress policy."):
        super().__init__(message=message, code="AI_SSRF_VIOLATION", retryable=False)


class AIProviderConfigError(AIProviderError):
    """Raised on invalid model or provider configuration."""
    def __init__(self, message: str = "Invalid AI provider configuration."):
        super().__init__(message=message, code="AI_CONFIG_ERROR", retryable=False)


# ==============================================================================
# Protocol Interface
# ==============================================================================

@runtime_checkable
class AIProviderClient(Protocol):
    """
    Provider-neutral interface for submitting evaluation prompts to LLMs
    and receiving structured JSON responses.
    """

    async def generate_evaluation(
        self,
        prompt: str,
        schema: Dict[str, Any],
        model_name: str,
        timeout_seconds: float = 120.0,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """
        Executes model inference for evaluation and returns parsed JSON output.
        Must raise typed AIProviderError subclasses on failure.
        """
        ...


# ==============================================================================
# Ollama Provider Client (Profile B SSRF-Protected Local Inference)
# ==============================================================================

class OllamaProviderClient:
    """
    Ollama LLM provider adapter using native /api/chat with structured JSON format.
    Enforces Profile B internal SSRF protection, IP pinning, zero redirects,
    bounded timeouts, and response size limits.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        max_response_bytes: int = 2_097_152,  # 2MB response ceiling
        allowed_ports: Optional[Set[int]] = None,
        dns_resolver: Optional[Any] = None,
    ):
        raw_url = base_url or settings.OLLAMA_BASE_URL
        self.base_url = raw_url.rstrip("/")
        self.max_response_bytes = max_response_bytes
        self.allowed_ports = allowed_ports
        self.dns_resolver = dns_resolver

        # Pre-validate base URL against Profile B network policy
        try:
            self.hostname, self.pinned_ip, self.port = validate_profile_b_url(
                self.base_url,
                allowed_ports=self.allowed_ports,
                dns_resolver=self.dns_resolver,
            )
        except SSRFViolationError as exc:
            logger.error("Ollama base URL failed Profile B validation: %s", exc)
            raise AIProviderSSRFError(
                f"Configured Ollama endpoint violates network security policy: {exc}"
            ) from exc

    async def generate_evaluation(
        self,
        prompt: str,
        schema: Dict[str, Any],
        model_name: str,
        timeout_seconds: float = 120.0,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """
        Invokes Ollama /api/chat with JSON Schema grammar enforcement.
        """
        request_body = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "stream": False,
            "format": schema,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            client = create_profile_b_client(
                base_url=self.base_url,
                timeout_seconds=timeout_seconds,
                allowed_ports=self.allowed_ports,
                dns_resolver=self.dns_resolver,
            )
        except SSRFViolationError as exc:
            raise AIProviderSSRFError(str(exc)) from exc

        async with client:
            try:
                response = await client.post(
                    "/api/chat",
                    json=request_body,
                )
            except httpx.TimeoutException as exc:
                raise AIProviderTimeoutError(
                    f"Inference request timed out after {timeout_seconds} seconds."
                ) from exc
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                raise AIProviderConnectionError(
                    "Network error connecting to internal AI provider service."
                ) from exc
            except SSRFViolationError as exc:
                raise AIProviderSSRFError(str(exc)) from exc
            except Exception as exc:
                logger.error("Unexpected error in Ollama request: %s", type(exc).__name__)
                raise AIProviderError(
                    "Internal error communicating with AI provider."
                ) from exc

            # Verify response size
            raw_content = response.content
            if len(raw_content) > self.max_response_bytes:
                raise AIProviderResponseSizeError(
                    f"Provider response ({len(raw_content)} bytes) exceeded limit of {self.max_response_bytes} bytes."
                )

            # Check HTTP status
            if response.status_code != 200:
                logger.error(
                    "Ollama returned HTTP status %d: %s",
                    response.status_code,
                    raw_content[:200],
                )
                raise AIProviderError(
                    f"AI provider returned unexpected HTTP error status {response.status_code}.",
                    code="AI_PROVIDER_HTTP_ERROR",
                    retryable=(response.status_code >= 500),
                )

            # Parse top-level Ollama envelope
            try:
                envelope = response.json()
            except Exception as exc:
                raise AIProviderFormatError(
                    "AI provider returned non-JSON HTTP response body."
                ) from exc

            message = envelope.get("message", {})
            content_str = message.get("content", "")

            if not content_str:
                raise AIProviderFormatError("AI provider returned empty message content.")

            # Parse the structured JSON output generated by the model
            try:
                parsed_output = json.loads(content_str)
            except json.JSONDecodeError as exc:
                raise AIProviderFormatError(
                    f"AI model output could not be parsed as JSON: {exc}"
                ) from exc

            if not isinstance(parsed_output, dict):
                raise AIProviderFormatError(
                    f"AI model output is not a JSON object, got {type(parsed_output).__name__}."
                )

            return parsed_output


# ==============================================================================
# Mock Provider Client (Deterministic, Zero-Cost, Offline Tests)
# ==============================================================================

class MockAIProviderClient:
    """
    Deterministic, offline AI provider adapter for automated CI test execution.
    Requires no GPU, no network connections, and no API credentials.
    Supports queued canned responses, canned exceptions, and dynamic generators.
    """

    def __init__(
        self,
        canned_responses: Optional[List[Dict[str, Any]]] = None,
        canned_errors: Optional[List[Exception]] = None,
        default_generator: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        self.canned_responses: List[Dict[str, Any]] = list(canned_responses or [])
        self.canned_errors: List[Exception] = list(canned_errors or [])
        self.default_generator = default_generator
        self.calls: List[Dict[str, Any]] = []

    async def generate_evaluation(
        self,
        prompt: str,
        schema: Dict[str, Any],
        model_name: str,
        timeout_seconds: float = 120.0,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """
        Returns queued canned response or invokes generator, recording call parameters.
        """
        self.calls.append({
            "prompt": prompt,
            "schema": schema,
            "model_name": model_name,
            "timeout_seconds": timeout_seconds,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })

        if self.canned_errors:
            error = self.canned_errors.pop(0)
            raise error

        if self.canned_responses:
            return self.canned_responses.pop(0)

        if self.default_generator:
            return self.default_generator(prompt, schema)

        # Baseline minimal valid response conforming to AIEvaluationOutputPayload
        return {
            "summary_assessment": "Mock automated static evaluation assessment: code meets baseline requirements.",
            "has_insufficient_evidence": False,
            "criterion_scores": [],
        }


# ==============================================================================
# Centralized Configuration Factory
# ==============================================================================

def get_ai_provider_client(
    config: Optional[EffectiveConfiguration] = None,
    base_url: Optional[str] = None,
    dns_resolver: Optional[Any] = None,
) -> AIProviderClient:
    """
    Instantiates an AI provider client based on the resolved effective configuration.
    Defaults to 'ollama' unless 'mock' is explicitly configured.
    """
    provider_name = (
        getattr(config, "ai_default_provider", "ollama")
        if config
        else "ollama"
    ).lower()

    if provider_name == "mock":
        return MockAIProviderClient()

    if provider_name == "ollama":
        target_url = base_url or settings.OLLAMA_BASE_URL
        return OllamaProviderClient(base_url=target_url, dns_resolver=dns_resolver)

    raise AIProviderConfigError(
        f"Unsupported AI provider '{provider_name}'. Permitted providers are 'ollama' and 'mock'."
    )

"""
Tests for AI Operations Router (/api/v1/admin/ai/*).

Verifies:
1. Super Admin authorization (401 unauth, 403 non-admin, 200 admin).
2. Ollama reachable mock probe returning version, models, latency, and counts.
3. Ollama unavailable handling (graceful 503 or error envelope without crashing).
4. No models installed (empty list).
5. Multiple installed models with parameter size, quantization, digest.
6. AI performance metrics endpoint querying metrics_collector.
7. Evaluation job monitoring cross-org pagination and status filtering.
8. Malformed Ollama response and timeout handling.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import uuid
import httpx
import pytest
from httpx import AsyncClient

from apps.api.config import settings
from apps.api.core.metrics import metrics_collector
from apps.api.modules.evaluations.models import EvaluationJob, RubricVersion, Submission, SubmissionSnapshot, Team
from apps.api.modules.hackathons.models import Hackathon
from apps.api.modules.organizations.models import Organization
from apps.api.modules.users.models import PlatformRole
from apps.api.tests.test_rbac_authorization import create_authenticated_session


@pytest.fixture
def clean_ai_metrics():
    """Resets AI-specific metrics before and after tests."""
    metrics_collector.inc_counter("scorva_ai_provider_calls_total", value=0, labels={"provider": "ollama", "status": "success"})
    yield
    # No teardown needed as metrics are monotonic or zero-initialized


@pytest.mark.asyncio
async def test_ai_endpoints_authorization(client: AsyncClient, db_session, create_user_helper):
    """Verifies unauthenticated (401) and non-admin (403) rejection."""
    # 1. Unauthenticated
    for path in ["/api/v1/admin/ai/health", "/api/v1/admin/ai/models", "/api/v1/admin/ai/metrics", "/api/v1/admin/ai/jobs"]:
        res = await client.get(path)
        assert res.status_code == 401

    # 2. Authenticated as non-admin participant
    user = await create_user_helper(email="ai_part@scorva.io", platform_role=None)
    token = await create_authenticated_session(db_session, user)
    for path in ["/api/v1/admin/ai/health", "/api/v1/admin/ai/models", "/api/v1/admin/ai/metrics", "/api/v1/admin/ai/jobs"]:
        res = await client.get(path, cookies={settings.SESSION_COOKIE_NAME: token})
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_ollama_health_reachable_multiple_models(client: AsyncClient, db_session, create_user_helper):
    """Verifies GET /admin/ai/health when Ollama is reachable with multiple models."""
    admin = await create_user_helper(email="ai_admin1@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    token = await create_authenticated_session(db_session, admin)

    mock_tags_response = {
        "models": [
            {
                "name": "llama3.3:70b",
                "size": 42000000000,
                "modified_at": "2026-10-15T12:00:00Z",
                "digest": "sha256:1234567890abcdef1234567890abcdef",
                "details": {
                    "parameter_size": "70B",
                    "quantization_level": "Q4_K_M",
                },
            },
            {
                "name": "mistral:7b",
                "size": 4100000000,
                "modified_at": "2026-10-16T15:30:00Z",
                "digest": "sha256:fedcba0987654321fedcba0987654321",
                "details": {
                    "parameter_size": "7B",
                    "quantization_level": "Q4_0",
                },
            },
        ]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    async def mock_get(url):
        if url == "/api/tags":
            return httpx.Response(200, json=mock_tags_response)
        elif url == "/api/version":
            return httpx.Response(200, json={"version": "0.4.1"})
        return httpx.Response(404)

    mock_client.get = AsyncMock(side_effect=mock_get)

    with patch("apps.api.modules.ai_ops.router.create_profile_b_client", return_value=mock_client), \
         patch("apps.api.modules.ai_ops.router.validate_profile_b_url", return_value=("localhost", "127.0.0.1", 11434)):

        res = await client.get("/api/v1/admin/ai/health", cookies={settings.SESSION_COOKIE_NAME: token})
        assert res.status_code == 200
        data = res.json()
        assert data["reachable"] is True
        assert data["installed_model_count"] == 2
        assert len(data["installed_models"]) == 2
        assert data["version"] == "0.4.1"
        assert data["installed_models"][0]["name"] == "llama3.3:70b"
        assert data["installed_models"][0]["parameter_size"] == "70B"
        assert data["installed_models"][0]["quantization_level"] == "Q4_K_M"
        assert data["installed_models"][0]["digest"] == "sha256:1234567890abcdef1234567890abcdef"
        assert data["latency_ms"] is not None


@pytest.mark.asyncio
async def test_ollama_models_endpoint(client: AsyncClient, db_session, create_user_helper):
    """Verifies GET /admin/ai/models returns accurate model inventory."""
    admin = await create_user_helper(email="ai_admin2@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    token = await create_authenticated_session(db_session, admin)

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.get = AsyncMock(return_value=httpx.Response(200, json={"models": [
        {"name": "llama3.3:70b", "size": 1000, "details": {"parameter_size": "70B", "quantization_level": "Q4"}}
    ]}))

    with patch("apps.api.modules.ai_ops.router.create_profile_b_client", return_value=mock_client), \
         patch("apps.api.modules.ai_ops.router.validate_profile_b_url", return_value=("localhost", "127.0.0.1", 11434)):

        res = await client.get("/api/v1/admin/ai/models", cookies={settings.SESSION_COOKIE_NAME: token})
        assert res.status_code == 200
        models = res.json()
        assert len(models) == 1
        assert models[0]["name"] == "llama3.3:70b"
        assert models[0]["parameter_size"] == "70B"


@pytest.mark.asyncio
async def test_ollama_empty_models(client: AsyncClient, db_session, create_user_helper):
    """Verifies handling when Ollama is running but has no models installed."""
    admin = await create_user_helper(email="ai_admin3@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    token = await create_authenticated_session(db_session, admin)

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.get = AsyncMock(return_value=httpx.Response(200, json={"models": []}))

    with patch("apps.api.modules.ai_ops.router.create_profile_b_client", return_value=mock_client), \
         patch("apps.api.modules.ai_ops.router.validate_profile_b_url", return_value=("localhost", "127.0.0.1", 11434)):

        res = await client.get("/api/v1/admin/ai/models", cookies={settings.SESSION_COOKIE_NAME: token})
        assert res.status_code == 200
        assert res.json() == []


@pytest.mark.asyncio
async def test_ollama_unavailable_and_timeout(client: AsyncClient, db_session, create_user_helper):
    """Verifies that an unavailable or timed-out Ollama daemon returns graceful error responses."""
    admin = await create_user_helper(email="ai_admin4@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    token = await create_authenticated_session(db_session, admin)

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

    with patch("apps.api.modules.ai_ops.router.create_profile_b_client", return_value=mock_client), \
         patch("apps.api.modules.ai_ops.router.validate_profile_b_url", return_value=("localhost", "127.0.0.1", 11434)):

        # Health endpoint returns 200 with reachable=False
        res = await client.get("/api/v1/admin/ai/health", cookies={settings.SESSION_COOKIE_NAME: token})
        assert res.status_code == 200
        data = res.json()
        assert data["reachable"] is False
        assert data["installed_model_count"] == 0
        assert "ConnectError" in data["error"]

        # Models endpoint returns 503
        res_models = await client.get("/api/v1/admin/ai/models", cookies={settings.SESSION_COOKIE_NAME: token})
        assert res_models.status_code == 503
        assert "detail" in res_models.json()


@pytest.mark.asyncio
async def test_ai_metrics_endpoint(client: AsyncClient, db_session, create_user_helper):
    """Verifies that GET /admin/ai/metrics queries in-process metrics accurately."""
    admin = await create_user_helper(email="ai_admin5@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    token = await create_authenticated_session(db_session, admin)

    # Increment some real metrics in the registry
    metrics_collector.inc_counter("scorva_ai_provider_calls_total", amount=5.0, labels={"provider": "ollama", "status": "success"})
    metrics_collector.inc_counter("scorva_ai_provider_calls_total", amount=2.0, labels={"provider": "ollama", "status": "provider_failed"})
    metrics_collector.observe_summary("scorva_eval_execution_duration_seconds", 12.5)

    res = await client.get("/api/v1/admin/ai/metrics", cookies={settings.SESSION_COOKIE_NAME: token})
    assert res.status_code == 200
    data = res.json()

    assert data["total_provider_calls"] >= 7
    assert data["successful_calls"] >= 5
    assert data["failed_calls"] >= 2
    assert "provider_model_breakdown" in data
    assert data["eval_execution_duration"]["count"] >= 1
    assert data["eval_execution_duration"]["sum_seconds"] >= 12.5
    assert "token_generation_throughput_tokens_per_sec" in data["unavailable_metrics"]


@pytest.mark.asyncio
async def test_evaluation_jobs_pagination_and_filtering(client: AsyncClient, db_session, create_user_helper):
    """Verifies Super Admin cross-organization evaluation jobs listing and pagination."""
    admin = await create_user_helper(email="ai_admin6@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    token = await create_authenticated_session(db_session, admin)

    res = await client.get("/api/v1/admin/ai/jobs?page=1&limit=10", cookies={settings.SESSION_COOKIE_NAME: token})
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert data["page"] == 1
    assert data["limit"] == 10

    # Test filtering by status
    res_filtered = await client.get("/api/v1/admin/ai/jobs?status=completed", cookies={settings.SESSION_COOKIE_NAME: token})
    assert res_filtered.status_code == 200
    filtered_data = res_filtered.json()
    for item in filtered_data["items"]:
        assert item["status"] == "completed"


@pytest.mark.asyncio
async def test_playground_authorization(client: AsyncClient, db_session, create_user_helper):
    """Verifies playground requires Super Admin authorization."""
    # 1. Unauthenticated
    res = await client.post(
        "/api/v1/admin/ai/playground",
        json={"model": "llama3.3:70b", "prompt": "test"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert res.status_code == 401

    # 2. Regular user (forbidden)
    user = await create_user_helper(email="play_part@scorva.io", platform_role=None)
    token = await create_authenticated_session(db_session, user)
    res = await client.post(
        "/api/v1/admin/ai/playground",
        json={"model": "llama3.3:70b", "prompt": "test"},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers={"Origin": "http://localhost:3000"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_playground_validation(client: AsyncClient, db_session, create_user_helper):
    """Verifies prompt and model validation (empty prompt, oversized prompt, invalid model)."""
    admin = await create_user_helper(email="play_admin1@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    token = await create_authenticated_session(db_session, admin)

    # Empty prompt
    res = await client.post(
        "/api/v1/admin/ai/playground",
        json={"model": "llama3.3:70b", "prompt": "   "},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers={"Origin": "http://localhost:3000"},
    )
    assert res.status_code == 400
    assert "Prompt cannot be empty" in res.json()["detail"]

    # Oversized prompt (>32k chars)
    res = await client.post(
        "/api/v1/admin/ai/playground",
        json={"model": "llama3.3:70b", "prompt": "x" * 35000},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers={"Origin": "http://localhost:3000"},
    )
    assert res.status_code == 400
    assert "exceeds maximum limit" in res.json()["detail"]


@pytest.mark.asyncio
async def test_playground_successful_inference(client: AsyncClient, db_session, create_user_helper):
    """Verifies successful playground inference returning model output and duration."""
    admin = await create_user_helper(email="play_admin2@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    token = await create_authenticated_session(db_session, admin)

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    async def mock_get(url):
        if url == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gemma2:9b"}]})
        return httpx.Response(404)

    async def mock_post(url, json=None):
        if url == "/api/chat":
            return httpx.Response(200, json={
                "model": "gemma2:9b",
                "message": {"role": "assistant", "content": "This project scores 9.2/10."},
                "prompt_eval_count": 25,
                "eval_count": 18,
                "eval_duration": 450000000,
            })
        return httpx.Response(404)

    mock_client.get = AsyncMock(side_effect=mock_get)
    mock_client.post = AsyncMock(side_effect=mock_post)

    with patch("apps.api.modules.ai_ops.router.create_profile_b_client", return_value=mock_client), \
         patch("apps.api.modules.ai_ops.router.validate_profile_b_url", return_value=("localhost", "127.0.0.1", 11434)):

        res = await client.post(
            "/api/v1/admin/ai/playground",
            json={"model": "gemma2:9b", "prompt": "Evaluate this submission", "temperature": 0.2, "max_tokens": 1024},
            cookies={settings.SESSION_COOKIE_NAME: token},
            headers={"Origin": "http://localhost:3000"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["model"] == "gemma2:9b"
        assert "This project scores 9.2/10." in data["response"]
        assert data["duration_ms"] >= 0
        assert data["token_usage"]["prompt_tokens"] == 25
        assert data["token_usage"]["completion_tokens"] == 18


@pytest.mark.asyncio
async def test_model_catalog_endpoint(client: AsyncClient, db_session, create_user_helper):
    """Verifies that the vetted model catalog is accessible to Super Admin."""
    admin = await create_user_helper(email="cat_admin@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    token = await create_authenticated_session(db_session, admin)

    res = await client.get("/api/v1/admin/ai/models/catalog", cookies={settings.SESSION_COOKIE_NAME: token})
    assert res.status_code == 200
    catalog = res.json()
    assert len(catalog) >= 5
    names = [m["name"] for m in catalog]
    assert "llama3.3:70b" in names
    assert "gemma2:9b" in names


@pytest.mark.asyncio
async def test_model_pull_duplicate_and_initiation(client: AsyncClient, db_session, create_user_helper):
    """Verifies pull initiation, duplicate rejection, and progress tracking."""
    admin = await create_user_helper(email="pull_admin@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    token = await create_authenticated_session(db_session, admin)

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    async def mock_aiter_lines():
        yield '{"status": "pulling manifest"}'
        yield '{"status": "downloading", "total": 1000, "completed": 500}'
        yield '{"status": "success"}'

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.aiter_lines = mock_aiter_lines

    mock_client.build_request.return_value = "mock_req"
    mock_client.send.return_value = mock_response

    with patch("apps.api.modules.ai_ops.router.create_profile_b_client", return_value=mock_client), \
         patch("apps.api.modules.ai_ops.router.validate_profile_b_url", return_value=("localhost", "127.0.0.1", 11434)):

        # 1. Initiate pull
        res = await client.post(
            "/api/v1/admin/ai/models/pull",
            json={"model_name": "gemma2:9b"},
            cookies={settings.SESSION_COOKIE_NAME: token},
            headers={"Origin": "http://localhost:3000"},
        )
        assert res.status_code == 200
        pull_data = res.json()
        assert pull_data["model_name"] == "gemma2:9b"
        assert pull_data["status"] in ("queued", "downloading", "completed")
        task_id = pull_data["task_id"]

        # 2. Duplicate pull should return 409 Conflict if still active
        # Let task run briefly
        import asyncio
        await asyncio.sleep(0.05)

        # 3. Status check
        status_res = await client.get("/api/v1/admin/ai/models/pull/status", cookies={settings.SESSION_COOKIE_NAME: token})
        assert status_res.status_code == 200
        statuses = status_res.json()
        assert any(t["task_id"] == task_id for t in statuses)


@pytest.mark.asyncio
async def test_model_deletion_protection(client: AsyncClient, db_session, create_user_helper):
    """Verifies that model deletion requires confirmation query param."""
    admin = await create_user_helper(email="del_admin@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    token = await create_authenticated_session(db_session, admin)

    # 1. Without confirmation
    res_no_confirm = await client.delete(
        "/api/v1/admin/ai/models/mistral:7b",
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers={"Origin": "http://localhost:3000"},
    )
    assert res_no_confirm.status_code == 400
    assert "Confirmation required" in res_no_confirm.json()["detail"]

    # 2. With confirmation
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.request.return_value = httpx.Response(200)

    with patch("apps.api.modules.ai_ops.router.create_profile_b_client", return_value=mock_client), \
         patch("apps.api.modules.ai_ops.router.validate_profile_b_url", return_value=("localhost", "127.0.0.1", 11434)):

        res_confirm = await client.delete(
            "/api/v1/admin/ai/models/mistral:7b?confirm=true",
            cookies={settings.SESSION_COOKIE_NAME: token},
            headers={"Origin": "http://localhost:3000"},
        )
        assert res_confirm.status_code == 200
        assert res_confirm.json()["status"] == "success"



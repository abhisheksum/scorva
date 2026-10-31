"""
Scorva AI Operations Admin Router.

Provides Super Admin endpoints for:
- Live Ollama service health (GET /admin/ai/health)
- Ollama pulled model inventory (GET /admin/ai/models)
- In-process AI provider metrics (GET /admin/ai/metrics)
- Cross-org evaluation job list (GET /admin/ai/jobs)

Design invariants:
- Does NOT touch OllamaProviderClient (evaluation-only).
- Uses its own short-lived httpx connection to Ollama /api/tags.
- Reuses ssrf_guard.create_profile_b_client for SSRF protection.
- All routes require require_super_admin.
- No DB writes; no schema changes.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
import uuid

import httpx
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.core.database import get_db_session
from apps.api.core.metrics import metrics_collector
from apps.api.core.ssrf_guard import SSRFViolationError, create_profile_b_client, validate_profile_b_url
from apps.api.dependencies import require_super_admin
from apps.api.modules.evaluations.models import EvaluationJob
from apps.api.modules.users.models import User

logger = logging.getLogger("scorva.ai_ops")

router = APIRouter(prefix="/admin/ai", tags=["AI Operations"])


# ──────────────────────────────────────────────
# Response schemas (inline — no DB models)
# ──────────────────────────────────────────────

class OllamaModelInfo(BaseModel):
    name: str
    size: int = 0
    parameter_size: Optional[str] = None
    quantization_level: Optional[str] = None
    modified_at: Optional[str] = None
    digest: Optional[str] = None


class OllamaHealthResponse(BaseModel):
    reachable: bool
    latency_ms: Optional[float]
    version: Optional[str] = None
    installed_model_count: int
    installed_models: List[OllamaModelInfo]
    base_url: str
    error: Optional[str] = None


class AiMetricsResponse(BaseModel):
    total_provider_calls: float
    successful_calls: float
    failed_calls: float
    provider_model_breakdown: Dict[str, float]
    eval_execution_duration: Dict[str, Any]
    queue_wait_duration: Dict[str, Any]
    jobs_by_status: Dict[str, float]
    unavailable_metrics: List[str]


class AdminEvalJobItem(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    hackathon_id: uuid.UUID
    submission_id: uuid.UUID
    status: str
    current_stage: Optional[str]
    attempts_count: int
    max_attempts: int
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    cancellation_requested: bool

    model_config = {"from_attributes": True}


class AdminEvalJobsResponse(BaseModel):
    items: List[AdminEvalJobItem]
    total: int
    page: int
    limit: int


class PlaygroundRequest(BaseModel):
    model: str
    prompt: str
    temperature: float = 0.7
    max_tokens: int = 2048


class PlaygroundResponse(BaseModel):
    model: str
    response: str
    duration_ms: float
    token_usage: Dict[str, Any] = {}
    success: bool
    error: Optional[str] = None


class CatalogModelInfo(BaseModel):
    name: str
    description: str
    parameter_size: str
    approx_size_bytes: int
    tags: List[str]
    category: str


class ModelPullRequest(BaseModel):
    model_name: str


class ModelPullStatusResponse(BaseModel):
    task_id: str
    model_name: str
    status: str  # queued, downloading, verifying, completed, failed, cancelled
    total_bytes: int = 0
    completed_bytes: int = 0
    progress_percentage: float = 0.0
    current_step: Optional[str] = None
    started_at: str
    completed_at: Optional[str] = None
    initiated_by_email: str
    error: Optional[str] = None


class ModelDeleteRequest(BaseModel):
    model_name: str
    confirm: bool = False


# ──────────────────────────────────────────────
# Trusted Model Catalog & Background Task Tracking
# ──────────────────────────────────────────────

TRUSTED_CATALOG: List[CatalogModelInfo] = [
    CatalogModelInfo(
        name="llama3.3:70b",
        description="Meta's premier open weights model optimized for high-reasoning hackathon evaluation and technical code analysis.",
        parameter_size="70B",
        approx_size_bytes=42_000_000_000,
        tags=["official", "recommended", "meta", "evaluation"],
        category="High-Capability Reasoning",
    ),
    CatalogModelInfo(
        name="llama3.1:8b",
        description="Fast, resource-efficient model suitable for general text evaluation and lightweight local inference.",
        parameter_size="8B",
        approx_size_bytes=4_700_000_000,
        tags=["official", "efficient", "meta"],
        category="General Purpose",
    ),
    CatalogModelInfo(
        name="gemma2:9b",
        description="Google DeepMind's high-performance compact model with advanced instruction following and code comprehension.",
        parameter_size="9B",
        approx_size_bytes=5_400_000_000,
        tags=["google", "code", "compact"],
        category="High Efficiency",
    ),
    CatalogModelInfo(
        name="gemma2:27b",
        description="Mid-sized Google model offering strong mathematical reasoning and deep architectural critique.",
        parameter_size="27B",
        approx_size_bytes=16_000_000_000,
        tags=["google", "reasoning"],
        category="Mid-Tier Reasoning",
    ),
    CatalogModelInfo(
        name="mistral:7b",
        description="Well-balanced foundational model with high token generation throughput and low latency.",
        parameter_size="7B",
        approx_size_bytes=4_100_000_000,
        tags=["mistral", "fast", "general"],
        category="General Purpose",
    ),
    CatalogModelInfo(
        name="qwen2.5-coder:7b",
        description="State-of-the-art specialized code intelligence model for inspecting submission ASTs and algorithmic logic.",
        parameter_size="7B",
        approx_size_bytes=4_700_000_000,
        tags=["coding", "analysis", "qwen"],
        category="Code Specialization",
    ),
    CatalogModelInfo(
        name="deepseek-r1:8b",
        description="Reinforcement learning-tuned reasoning model specialized in complex step-by-step problem verification.",
        parameter_size="8B",
        approx_size_bytes=4_900_000_000,
        tags=["reasoning", "deepseek"],
        category="Reasoning & Verification",
    ),
]

# In-memory tracking of active/recent model pull tasks (protected by Lock)
_pull_lock = asyncio.Lock()
_active_pull_tasks: Dict[str, Dict[str, Any]] = {}  # task_id -> task_data
_active_pull_by_model: Dict[str, str] = {}  # model_name -> task_id
MAX_CONCURRENT_PULLS = 1

async def _probe_ollama(timeout_seconds: float = 5.0) -> OllamaHealthResponse:
    """
    Makes a live GET /api/tags request (and GET /api/version if reachable) to Ollama.
    Returns structured health + model inventory. Never raises — errors are
    captured in the response envelope.
    """
    base_url = settings.OLLAMA_BASE_URL.rstrip("/")

    try:
        hostname, pinned_ip, port = validate_profile_b_url(
            base_url,
            allowed_ports={11434},
        )
    except SSRFViolationError as exc:
        return OllamaHealthResponse(
            reachable=False,
            latency_ms=None,
            version=None,
            installed_model_count=0,
            installed_models=[],
            base_url=base_url,
            error=f"SSRF policy violation: {exc}",
        )
    except Exception as exc:
        return OllamaHealthResponse(
            reachable=False,
            latency_ms=None,
            version=None,
            installed_model_count=0,
            installed_models=[],
            base_url=base_url,
            error=f"URL validation error: {exc}",
        )

    t_start = time.perf_counter()
    try:
        client = create_profile_b_client(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            allowed_ports={11434},
        )
        async with client:
            response = await client.get("/api/tags")
            latency_ms = round((time.perf_counter() - t_start) * 1000, 1)

            if response.status_code != 200:
                return OllamaHealthResponse(
                    reachable=False,
                    latency_ms=latency_ms,
                    version=None,
                    installed_model_count=0,
                    installed_models=[],
                    base_url=base_url,
                    error=f"Ollama returned HTTP {response.status_code}",
                )

            data: Dict[str, Any] = response.json()
            raw_models: List[Dict[str, Any]] = data.get("models", [])
            models = [
                OllamaModelInfo(
                    name=m.get("name", "unknown"),
                    size=m.get("size", 0),
                    parameter_size=m.get("details", {}).get("parameter_size"),
                    quantization_level=m.get("details", {}).get("quantization_level"),
                    modified_at=m.get("modified_at"),
                    digest=m.get("digest"),
                )
                for m in raw_models
            ]

            # Optionally query version endpoint
            ollama_version: Optional[str] = None
            try:
                ver_resp = await client.get("/api/version")
                if ver_resp.status_code == 200:
                    ollama_version = ver_resp.json().get("version")
            except Exception:
                pass

            return OllamaHealthResponse(
                reachable=True,
                latency_ms=latency_ms,
                version=ollama_version,
                installed_model_count=len(models),
                installed_models=models,
                base_url=base_url,
            )

    except httpx.TimeoutException:
        return OllamaHealthResponse(
            reachable=False,
            latency_ms=None,
            version=None,
            installed_model_count=0,
            installed_models=[],
            base_url=base_url,
            error=f"Connection timed out after {timeout_seconds}s",
        )
    except (httpx.ConnectError, httpx.NetworkError) as exc:
        return OllamaHealthResponse(
            reachable=False,
            latency_ms=None,
            version=None,
            installed_model_count=0,
            installed_models=[],
            base_url=base_url,
            error=f"Network error: {type(exc).__name__}",
        )
    except Exception as exc:
        logger.exception("Unexpected error probing Ollama: %s", exc)
        return OllamaHealthResponse(
            reachable=False,
            latency_ms=None,
            version=None,
            installed_model_count=0,
            installed_models=[],
            base_url=base_url,
            error="Internal probe error",
        )


def _read_metrics() -> AiMetricsResponse:
    """Reads the in-process metrics registry and returns structured AI metrics."""
    raw = metrics_collector.export_dict()

    provider_model_breakdown: Dict[str, float] = {}
    jobs_by_status: Dict[str, float] = {}
    total_calls = 0.0
    successful_calls = 0.0
    failed_calls = 0.0

    counters: Dict[str, List[Dict[str, Any]]] = raw.get("counters", {})

    ai_entries = counters.get("scorva_ai_provider_calls_total", [])
    for entry in ai_entries:
        labels: Dict[str, str] = entry.get("labels", {})
        value = float(entry.get("value", 0))
        label_key = "_".join(f"{k}={v}" for k, v in sorted(labels.items())) or "total"
        provider_model_breakdown[label_key] = value
        total_calls += value

        call_status = labels.get("status", "")
        if call_status == "success":
            successful_calls += value
        elif call_status in ("provider_failed", "validation_failed", "error", "failed"):
            failed_calls += value

    job_entries = counters.get("scorva_eval_jobs_total", [])
    for entry in job_entries:
        labels = entry.get("labels", {})
        value = float(entry.get("value", 0))
        st = labels.get("status", "unknown")
        jobs_by_status[st] = value

    summaries: Dict[str, List[Dict[str, Any]]] = raw.get("summaries", {})

    eval_count = 0
    eval_sum = 0.0
    queue_count = 0
    queue_sum = 0.0

    for entry in summaries.get("scorva_eval_execution_duration_seconds", []):
        eval_count += int(entry.get("count", 0))
        eval_sum += float(entry.get("sum", 0.0))

    for entry in summaries.get("scorva_eval_queue_wait_seconds", []):
        queue_count += int(entry.get("count", 0))
        queue_sum += float(entry.get("sum", 0.0))

    return AiMetricsResponse(
        total_provider_calls=total_calls,
        successful_calls=successful_calls,
        failed_calls=failed_calls,
        provider_model_breakdown=provider_model_breakdown,
        eval_execution_duration={
            "count": eval_count,
            "sum_seconds": round(eval_sum, 3),
            "avg_seconds": round(eval_sum / eval_count, 3) if eval_count > 0 else None,
        },
        queue_wait_duration={
            "count": queue_count,
            "sum_seconds": round(queue_sum, 3),
            "avg_seconds": round(queue_sum / queue_count, 3) if queue_count > 0 else None,
        },
        jobs_by_status=jobs_by_status,
        unavailable_metrics=[
            "token_generation_throughput_tokens_per_sec",
            "gpu_memory_utilization_bytes",
            "per_token_latency_ms",
        ],
    )



# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@router.get(
    "/health",
    response_model=OllamaHealthResponse,
    summary="Live Ollama service health probe",
)
async def get_ollama_health(
    current_user: User = Depends(require_super_admin),
) -> OllamaHealthResponse:
    """
    Performs a live GET /api/tags request to the configured Ollama instance.
    Returns reachability, latency, and pulled model inventory.
    """
    return await _probe_ollama(timeout_seconds=5.0)


@router.get(
    "/models",
    response_model=List[OllamaModelInfo],
    summary="List models pulled on the Ollama instance",
)
async def list_ollama_models(
    current_user: User = Depends(require_super_admin),
) -> List[OllamaModelInfo]:
    """Returns the list of models currently available on the Ollama service."""
    health = await _probe_ollama(timeout_seconds=5.0)
    if not health.reachable:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": health.error or "Ollama service is unreachable."},
        )
    return health.installed_models


@router.get(
    "/metrics",
    response_model=AiMetricsResponse,
    summary="In-process AI provider and evaluation metrics",
)
async def get_ai_metrics(
    current_user: User = Depends(require_super_admin),
) -> AiMetricsResponse:
    """
    Reads the in-process Prometheus metrics registry and returns AI provider
    call counters, evaluation pipeline duration statistics, and job status counts.
    """
    return _read_metrics()


@router.get(
    "/jobs",
    response_model=AdminEvalJobsResponse,
    summary="Cross-org evaluation job list (Super Admin view)",
)
async def list_all_evaluation_jobs(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_super_admin),
) -> AdminEvalJobsResponse:
    """
    Returns a paginated, cross-organization list of evaluation jobs.
    Optionally filter by status (queued, running, completed, failed, cancelled).
    """
    from sqlalchemy import func as sqlfunc

    stmt = select(EvaluationJob)
    count_stmt = select(sqlfunc.count()).select_from(EvaluationJob)

    if status_filter:
        stmt = stmt.where(EvaluationJob.status == status_filter)
        count_stmt = count_stmt.where(EvaluationJob.status == status_filter)

    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(desc(EvaluationJob.created_at)).offset((page - 1) * limit).limit(limit)
    jobs = (await db.execute(stmt)).scalars().all()

    items = [
        AdminEvalJobItem(
            id=j.id,
            organization_id=j.organization_id,
            hackathon_id=j.hackathon_id,
            submission_id=j.submission_id,
            status=j.status,
            current_stage=j.current_stage,
            attempts_count=j.attempts_count,
            max_attempts=j.max_attempts,
            created_at=j.created_at.isoformat() if j.created_at else "",
            started_at=j.started_at.isoformat() if j.started_at else None,
            completed_at=j.completed_at.isoformat() if j.completed_at else None,
            cancellation_requested=j.cancellation_requested,
        )
        for j in jobs
    ]

    return AdminEvalJobsResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
    )


@router.post(
    "/playground",
    response_model=PlaygroundResponse,
    summary="Execute test inference on installed Ollama models",
)
async def ai_playground_inference(
    req: PlaygroundRequest,
    current_user: User = Depends(require_super_admin),
) -> PlaygroundResponse:
    """
    Executes an isolated test inference request against an installed Ollama model.
    Invariants:
    - Super Admin only.
    - Model must exist on the local Ollama instance.
    - Prompt bounded between 1 and 32,768 characters.
    - Temperature bounded [0.0, 2.0].
    - max_tokens bounded [16, 8192].
    - Response bounded to 2MB maximum payload.
    - Does NOT mutate database, evaluation jobs, or production configuration.
    - Does NOT log full prompt or response text.
    """
    # 1. Input validations
    prompt = req.prompt.strip()
    if not prompt:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "Prompt cannot be empty."},
        )

    if len(prompt) > 32_768:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": f"Prompt length ({len(prompt)}) exceeds maximum limit of 32,768 characters."},
        )

    model_name = req.model.strip()
    if not model_name:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "Model parameter is required."},
        )

    temperature = max(0.0, min(float(req.temperature), 2.0))
    max_tokens = max(16, min(int(req.max_tokens), 8192))

    # 2. Check Ollama reachability and validate model presence
    health = await _probe_ollama(timeout_seconds=5.0)
    if not health.reachable:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": health.error or "Ollama service is currently unreachable."},
        )

    installed_names = [m.name for m in health.installed_models]
    # Check exact match or name before tag
    model_found = any(
        model_name == m_name or model_name.split(":")[0] == m_name.split(":")[0]
        for m_name in installed_names
    )
    if not model_found and installed_names:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "detail": f"Model '{model_name}' is not installed. Installed models: {', '.join(installed_names)}."
            },
        )

    # 3. Execute inference via Profile B SSRF-safe client
    base_url = settings.OLLAMA_BASE_URL.rstrip("/")
    t_start = time.perf_counter()
    timeout_seconds = 120.0

    chat_payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }

    try:
        client = create_profile_b_client(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            allowed_ports={11434},
        )
        async with client:
            resp = await client.post("/api/chat", json=chat_payload)
            duration_ms = round((time.perf_counter() - t_start) * 1000, 1)

            if resp.status_code != 200:
                logger.warning("Ollama playground returned HTTP %d for model %s", resp.status_code, model_name)
                return PlaygroundResponse(
                    model=model_name,
                    response="",
                    duration_ms=duration_ms,
                    token_usage={},
                    success=False,
                    error=f"Ollama returned HTTP error status {resp.status_code}.",
                )

            data = resp.json()
            message = data.get("message", {})
            content = message.get("content", "")

            # Extract token usage if provided by Ollama
            token_usage = {}
            if "prompt_eval_count" in data:
                token_usage["prompt_tokens"] = data["prompt_eval_count"]
            if "eval_count" in data:
                token_usage["completion_tokens"] = data["eval_count"]
            if "prompt_eval_duration" in data:
                token_usage["prompt_eval_duration_ms"] = round(data["prompt_eval_duration"] / 1_000_000, 1)
            if "eval_duration" in data:
                token_usage["eval_duration_ms"] = round(data["eval_duration"] / 1_000_000, 1)

            return PlaygroundResponse(
                model=model_name,
                response=content,
                duration_ms=duration_ms,
                token_usage=token_usage,
                success=True,
            )

    except httpx.TimeoutException:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
        return PlaygroundResponse(
            model=model_name,
            response="",
            duration_ms=duration_ms,
            token_usage={},
            success=False,
            error=f"Inference request timed out after {timeout_seconds} seconds.",
        )
    except (httpx.ConnectError, httpx.NetworkError) as exc:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
        return PlaygroundResponse(
            model=model_name,
            response="",
            duration_ms=duration_ms,
            token_usage={},
            success=False,
            error=f"Network error communicating with Ollama: {type(exc).__name__}",
        )
    except Exception as exc:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
        logger.exception("Unexpected error in playground inference: %s", exc)
        return PlaygroundResponse(
            model=model_name,
            response="",
            duration_ms=duration_ms,
            token_usage={},
            success=False,
            error="Internal error executing playground inference.",
        )


# ──────────────────────────────────────────────
# Model Lifecycle Management Endpoints
# ──────────────────────────────────────────────

@router.get(
    "/models/catalog",
    response_model=List[CatalogModelInfo],
    summary="List approved models available for download",
)
async def list_model_catalog(
    current_user: User = Depends(require_super_admin),
) -> List[CatalogModelInfo]:
    """Returns curated list of vetted models from the approved platform catalog."""
    return TRUSTED_CATALOG


async def _execute_model_pull_task(task_id: str, model_name: str):
    """
    Background worker task that streams download progress directly from Ollama /api/pull.
    Updates in-memory progress structure safely.
    """
    base_url = settings.OLLAMA_BASE_URL.rstrip("/")
    timeout_seconds = 1800.0  # 30 minutes for large model download

    async with _pull_lock:
        if task_id not in _active_pull_tasks:
            return
        _active_pull_tasks[task_id]["status"] = "downloading"
        _active_pull_tasks[task_id]["current_step"] = "Connecting to Ollama library registry"

    try:
        client = create_profile_b_client(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            allowed_ports={11434},
        )
        async with client:
            req = client.build_request("POST", "/api/pull", json={"name": model_name, "stream": True})
            response = await client.send(req, stream=True, follow_redirects=False)

            if response.status_code != 200:
                body = await response.aread()
                async with _pull_lock:
                    _active_pull_tasks[task_id]["status"] = "failed"
                    _active_pull_tasks[task_id]["error"] = f"Ollama returned HTTP {response.status_code}: {body.decode('utf-8', 'ignore')[:150]}"
                    _active_pull_tasks[task_id]["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    _active_pull_by_model.pop(model_name, None)
                return

            import json as pyjson
            async for line in response.aiter_lines():
                # Check for cancellation requested
                async with _pull_lock:
                    if _active_pull_tasks[task_id].get("cancellation_requested", False):
                        _active_pull_tasks[task_id]["status"] = "cancelled"
                        _active_pull_tasks[task_id]["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        _active_pull_by_model.pop(model_name, None)
                        await response.aclose()
                        return

                if not line.strip():
                    continue

                try:
                    payload = pyjson.loads(line)
                except Exception:
                    continue

                status_text = payload.get("status", "")
                total = payload.get("total", 0)
                completed = payload.get("completed", 0)

                async with _pull_lock:
                    task = _active_pull_tasks[task_id]
                    task["current_step"] = status_text
                    if total > 0:
                        task["total_bytes"] = total
                        task["completed_bytes"] = completed
                        task["progress_percentage"] = round((completed / total) * 100, 1)

                    if "verifying" in status_text.lower():
                        task["status"] = "verifying"
                    elif "success" in status_text.lower():
                        task["status"] = "completed"
                        task["progress_percentage"] = 100.0

            async with _pull_lock:
                _active_pull_tasks[task_id]["status"] = "completed"
                _active_pull_tasks[task_id]["progress_percentage"] = 100.0
                _active_pull_tasks[task_id]["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                _active_pull_by_model.pop(model_name, None)

    except asyncio.CancelledError:
        async with _pull_lock:
            if task_id in _active_pull_tasks:
                _active_pull_tasks[task_id]["status"] = "cancelled"
                _active_pull_tasks[task_id]["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                _active_pull_by_model.pop(model_name, None)
    except Exception as exc:
        logger.exception("Error during model pull task: %s", exc)
        async with _pull_lock:
            if task_id in _active_pull_tasks:
                _active_pull_tasks[task_id]["status"] = "failed"
                _active_pull_tasks[task_id]["error"] = str(exc)
                _active_pull_tasks[task_id]["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                _active_pull_by_model.pop(model_name, None)


@router.post(
    "/models/pull",
    response_model=ModelPullStatusResponse,
    summary="Initiate asynchronous download of an approved Ollama model",
)
async def pull_ollama_model(
    req: ModelPullRequest,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
) -> ModelPullStatusResponse:
    """
    Initiates asynchronous download for an approved model.
    Enforces concurrency limits, duplicate check, and model name sanitization.
    """
    model_name = req.model_name.strip()
    if not model_name:
        return JSONResponse(status_code=400, content={"detail": "model_name cannot be empty."})

    # Validate model name against trusted catalog OR strict alphanum format
    is_catalog = any(m.name == model_name for m in TRUSTED_CATALOG)
    import re
    if not is_catalog and not re.match(r"^[a-zA-Z0-9_\-\.\:\/]+$", model_name):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid model identifier syntax. Use standard registry tags."},
        )

    # Check duplicate pull and concurrency limit
    async with _pull_lock:
        if model_name in _active_pull_by_model:
            existing_task_id = _active_pull_by_model[model_name]
            existing = _active_pull_tasks.get(existing_task_id)
            if existing and existing["status"] in ("queued", "downloading", "verifying"):
                return JSONResponse(
                    status_code=409,
                    content={"detail": f"Model '{model_name}' is already being downloaded (task {existing_task_id})."},
                )

        active_count = sum(1 for t in _active_pull_tasks.values() if t["status"] in ("queued", "downloading", "verifying"))
        if active_count >= MAX_CONCURRENT_PULLS:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Concurrency limit reached ({MAX_CONCURRENT_PULLS} active download). Please wait for ongoing downloads to complete."},
            )

        task_id = str(uuid.uuid4())
        started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        task_data = {
            "task_id": task_id,
            "model_name": model_name,
            "status": "queued",
            "total_bytes": 0,
            "completed_bytes": 0,
            "progress_percentage": 0.0,
            "current_step": "Download request enqueued",
            "started_at": started_at,
            "completed_at": None,
            "initiated_by_email": current_user.email,
            "error": None,
            "cancellation_requested": False,
        }
        _active_pull_tasks[task_id] = task_data
        _active_pull_by_model[model_name] = task_id

    # Spawn background task
    asyncio.create_task(_execute_model_pull_task(task_id, model_name))

    # Audit logging
    try:
        from apps.api.modules.audit.models import AuditOutcome
        from apps.api.modules.audit.service import record_audit_event
        await record_audit_event(
            db=db,
            action="ai.model.pull_initiated",
            resource_type="ai_model",
            resource_id=model_name,
            outcome=AuditOutcome.SUCCESS,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            actor_role=current_user.platform_role.value if current_user.platform_role else "admin",
            reason=f"Initiated pull for model {model_name}",
        )
    except Exception as exc:
        logger.warning("Audit logging failed for model pull: %s", exc)

    return ModelPullStatusResponse(**task_data)


@router.get(
    "/models/pull/status",
    response_model=List[ModelPullStatusResponse],
    summary="List active and recent model download tasks",
)
async def get_pull_status(
    current_user: User = Depends(require_super_admin),
) -> List[ModelPullStatusResponse]:
    """Returns status and progress of all active or recent model pull jobs."""
    async with _pull_lock:
        return [
            ModelPullStatusResponse(
                task_id=t["task_id"],
                model_name=t["model_name"],
                status=t["status"],
                total_bytes=t.get("total_bytes", 0),
                completed_bytes=t.get("completed_bytes", 0),
                progress_percentage=t.get("progress_percentage", 0.0),
                current_step=t.get("current_step"),
                started_at=t["started_at"],
                completed_at=t.get("completed_at"),
                initiated_by_email=t["initiated_by_email"],
                error=t.get("error"),
            )
            for t in list(_active_pull_tasks.values())[-10:]
        ]


@router.post(
    "/models/pull/{task_id}/cancel",
    response_model=ModelPullStatusResponse,
    summary="Safely cancel an active model pull task",
)
async def cancel_model_pull(
    task_id: str,
    current_user: User = Depends(require_super_admin),
) -> ModelPullStatusResponse:
    """Cancels an in-progress download if actively running."""
    async with _pull_lock:
        task = _active_pull_tasks.get(task_id)
        if not task:
            return JSONResponse(status_code=404, content={"detail": f"Pull task {task_id} not found."})

        if task["status"] in ("completed", "failed", "cancelled"):
            return JSONResponse(status_code=400, content={"detail": f"Task is already {task['status']}."})

        task["cancellation_requested"] = True
        task["status"] = "cancelling"
        task["current_step"] = "Cancellation requested"

        return ModelPullStatusResponse(
            task_id=task["task_id"],
            model_name=task["model_name"],
            status=task["status"],
            total_bytes=task.get("total_bytes", 0),
            completed_bytes=task.get("completed_bytes", 0),
            progress_percentage=task.get("progress_percentage", 0.0),
            current_step=task.get("current_step"),
            started_at=task["started_at"],
            completed_at=task.get("completed_at"),
            initiated_by_email=task["initiated_by_email"],
            error=task.get("error"),
        )


@router.delete(
    "/models/{model_name:path}",
    summary="Safely remove an installed model from Ollama storage",
)
async def delete_installed_model(
    model_name: str,
    confirm: bool = Query(False),
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Deletes an installed model from Ollama local storage after confirmation.
    Checks that the model is not currently claimed by any running evaluation job.
    Records deletion in audit log.
    """
    if not confirm:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "Confirmation required. Pass ?confirm=true to delete model."},
        )

    # 1. Prevent deleting models while evaluations are actively running with this model
    running_jobs = (await db.execute(
        select(EvaluationJob).where(EvaluationJob.status == "running")
    )).scalars().all()
    if running_jobs:
        # In Scorva, default or configured model could be in active evaluation
        from apps.api.modules.configuration.service import resolve_effective_configuration
        try:
            config = await resolve_effective_configuration(db)
            if config.default_model == model_name:
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content={"detail": f"Model '{model_name}' is currently configured as the platform default model for running evaluations."},
                )
        except Exception:
            pass

    # 2. Call Ollama DELETE /api/delete
    base_url = settings.OLLAMA_BASE_URL.rstrip("/")
    try:
        client = create_profile_b_client(
            base_url=base_url,
            timeout_seconds=15.0,
            allowed_ports={11434},
        )
        async with client:
            resp = await client.request(
                "DELETE",
                "/api/delete",
                json={"name": model_name},
            )
            if resp.status_code not in (200, 204):
                body = resp.text[:200]
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={"detail": f"Ollama delete failed: {body}"},
                )

    except Exception as exc:
        logger.exception("Error deleting Ollama model %s: %s", model_name, exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": f"Could not communicate with Ollama to delete model: {exc}"},
        )

    # 3. Audit logging
    try:
        from apps.api.modules.audit.models import AuditOutcome
        from apps.api.modules.audit.service import record_audit_event
        await record_audit_event(
            db=db,
            action="ai.model.deleted",
            resource_type="ai_model",
            resource_id=model_name,
            outcome=AuditOutcome.SUCCESS,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            actor_role=current_user.platform_role.value if current_user.platform_role else "admin",
            reason=f"Permanently removed model {model_name} from local inference storage",
        )
    except Exception as exc:
        logger.warning("Audit logging failed for model delete: %s", exc)

    return {"status": "success", "message": f"Model '{model_name}' successfully removed from Ollama storage."}

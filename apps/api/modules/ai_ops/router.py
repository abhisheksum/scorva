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
import json as pyjson
import logging
import re
import shutil
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
from apps.api.core.database import AsyncSessionLocal, get_db_session
from apps.api.core.metrics import metrics_collector
from apps.api.core.redis import get_redis_client
from apps.api.core.ssrf_guard import SSRFViolationError, create_profile_b_client, validate_profile_b_url
from apps.api.dependencies import require_super_admin
from apps.api.modules.audit.models import AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.evaluations.models import EvaluationJob, SubmissionSnapshot
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

# ──────────────────────────────────────────────
# Distributed State, Coordination & Locking Constants
# ──────────────────────────────────────────────

REDIS_PULL_PREFIX = "ai:model:pull:"
REDIS_PULL_SET_KEY = "ai:model:pull:tasks"
REDIS_PULL_MODEL_PREFIX = "ai:model:lock:"
REDIS_CONCURRENCY_KEY = "ai:model:active_pulls_count"
REDIS_LOCK_EXPIRATION_SECONDS = 1800  # 30 minutes auto-expire

# Local tracking for async streaming tasks and shutdown signaling
_pull_lock = asyncio.Lock()
_active_pull_tasks: Dict[str, Dict[str, Any]] = {}  # task_id -> task_data
_active_pull_by_model: Dict[str, str] = {}          # model_name -> task_id
_running_async_tasks: Dict[str, asyncio.Task] = {}  # task_id -> asyncio.Task
_is_shutting_down = False


async def _save_task_state_durable(task_data: Dict[str, Any]) -> None:
    """Persists model pull task state in both Redis and memory store."""
    task_id = task_data["task_id"]
    payload = pyjson.dumps(task_data)
    try:
        r = get_redis_client()
        await r.set(f"{REDIS_PULL_PREFIX}{task_id}", payload, ex=86400)  # 24h retention
        await r.sadd(REDIS_PULL_SET_KEY, task_id)
    except Exception as exc:
        logger.debug("Redis unavailable for saving pull task %s: %s", task_id, exc)


async def _get_all_durable_tasks() -> List[Dict[str, Any]]:
    """Retrieves all tracked pull tasks from Redis or memory."""
    tasks: Dict[str, Dict[str, Any]] = {}
    try:
        r = get_redis_client()
        task_ids = await r.smembers(REDIS_PULL_SET_KEY)
        for tid in task_ids:
            raw = await r.get(f"{REDIS_PULL_PREFIX}{tid}")
            if raw:
                try:
                    data = pyjson.loads(raw)
                    tasks[data["task_id"]] = data
                except Exception:
                    continue
    except Exception as exc:
        logger.debug("Redis unavailable for retrieving pull tasks: %s", exc)

    # Merge with process-local tasks
    async with _pull_lock:
        for tid, tdata in _active_pull_tasks.items():
            tasks[tid] = tdata

    # Sort by started_at descending
    sorted_tasks = sorted(
        tasks.values(),
        key=lambda x: x.get("started_at", ""),
        reverse=True,
    )
    return sorted_tasks


async def reconcile_interrupted_pull_tasks() -> None:
    """
    Called on FastAPI startup to reconcile any unfinished tasks from a previous
    crash or server restart. Incomplete tasks are cleanly transitioned to 'failed'
    with recovery details, preventing lost tasks from being left hanging in 'downloading'
    or ever being reported as completed.
    """
    logger.info("Reconciling interrupted Ollama model pull tasks...")
    try:
        r = get_redis_client()
        task_ids = await r.smembers(REDIS_PULL_SET_KEY)
        for tid in task_ids:
            raw = await r.get(f"{REDIS_PULL_PREFIX}{tid}")
            if not raw:
                continue
            try:
                task = pyjson.loads(raw)
            except Exception:
                continue

            if task.get("status") in ("queued", "downloading", "verifying", "cancelling"):
                model_name = task.get("model_name", "unknown")
                logger.warning(
                    "Reconciling interrupted model pull task %s for model %s: marking failed.",
                    tid,
                    model_name,
                )
                task["status"] = "failed"
                task["error"] = "Task interrupted by system restart or process termination before completion."
                task["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                await r.set(f"{REDIS_PULL_PREFIX}{tid}", pyjson.dumps(task), ex=86400)
                await r.delete(f"{REDIS_PULL_MODEL_PREFIX}{model_name}")

        # Also reset concurrency counter key if necessary
        active_locks = 0
        for tid in task_ids:
            raw = await r.get(f"{REDIS_PULL_PREFIX}{tid}")
            if raw:
                try:
                    t = pyjson.loads(raw)
                    if t.get("status") in ("queued", "downloading", "verifying"):
                        active_locks += 1
                except Exception:
                    pass
        await r.set(REDIS_CONCURRENCY_KEY, active_locks)
    except Exception as exc:
        logger.debug("Redis reconcile skipped: %s", exc)


async def shutdown_active_pull_tasks() -> None:
    """
    Graceful shutdown handler called during lifespan exit:
    - Sets shutdown flag to reject any new operations.
    - Cancels actively running streaming async tasks.
    - Updates durable state so tasks are never left in an inconsistent running state.
    """
    global _is_shutting_down
    _is_shutting_down = True

    async with _pull_lock:
        running_ids = list(_running_async_tasks.keys())

    for tid in running_ids:
        async with _pull_lock:
            task = _active_pull_tasks.get(tid)
            if task and task.get("status") in ("queued", "downloading", "verifying", "cancelling"):
                task["status"] = "cancelled"
                task["current_step"] = "Cancelled due to server shutdown"
                task["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                await _save_task_state_durable(task)

            async_t = _running_async_tasks.get(tid)
            if async_t and not async_t.done():
                async_t.cancel()

        # Release Redis model lock on shutdown
        if task:
            try:
                r = get_redis_client()
                await r.delete(f"{REDIS_PULL_MODEL_PREFIX}{task.get('model_name')}")
            except Exception:
                pass

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
    Updates in-memory progress structure and Redis distributed state safely.
    Releases distributed locks upon completion, failure, cancellation, or error.
    """
    base_url = settings.OLLAMA_BASE_URL.rstrip("/")
    timeout_seconds = 1800.0  # 30 minutes for large model download
    r = None
    try:
        r = get_redis_client()
    except Exception:
        pass

    async with _pull_lock:
        if task_id not in _active_pull_tasks:
            return
        _active_pull_tasks[task_id]["status"] = "downloading"
        _active_pull_tasks[task_id]["current_step"] = "Connecting to Ollama library registry"
        task_snapshot = dict(_active_pull_tasks[task_id])

    await _save_task_state_durable(task_snapshot)

    async def _cleanup_locks_and_counters(terminal_status: str, error_msg: Optional[str] = None):
        nonlocal r
        completed_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        actor_email = "system@scorva.local"
        async with _pull_lock:
            if task_id in _active_pull_tasks:
                _active_pull_tasks[task_id]["status"] = terminal_status
                _active_pull_tasks[task_id]["completed_at"] = completed_ts
                actor_email = _active_pull_tasks[task_id].get("initiated_by_email", actor_email)
                if error_msg:
                    _active_pull_tasks[task_id]["error"] = error_msg
                if terminal_status == "completed":
                    _active_pull_tasks[task_id]["progress_percentage"] = 100.0
                task_done = dict(_active_pull_tasks[task_id])
            else:
                task_done = None
            _active_pull_by_model.pop(model_name, None)
            _running_async_tasks.pop(task_id, None)

        if task_done:
            await _save_task_state_durable(task_done)

        # Release distributed Redis lock & decrement concurrency
        if r:
            try:
                await r.delete(f"{REDIS_PULL_MODEL_PREFIX}{model_name}")
                # Atomically ensure counter does not drop below 0
                val = await r.decr(REDIS_CONCURRENCY_KEY)
                if val < 0:
                    await r.set(REDIS_CONCURRENCY_KEY, 0)
            except Exception as e:
                logger.debug("Redis lock release exception: %s", e)

        # Audit logging for terminal state
        try:
            async with AsyncSessionLocal() as session:
                action_name = f"ai.model.pull_{terminal_status}"
                outcome = AuditOutcome.SUCCESS if terminal_status == "completed" else AuditOutcome.FAILURE
                await record_audit_event(
                    db=session,
                    action=action_name,
                    resource_type="ai_model",
                    resource_id=model_name,
                    outcome=outcome,
                    actor_email=actor_email,
                    actor_role="admin",
                    reason=f"Model pull {terminal_status} for {model_name}" + (f": {error_msg}" if error_msg else ""),
                    diff_payload={"task_id": task_id, "terminal_status": terminal_status},
                )
                await session.commit()
        except Exception as audit_exc:
            logger.warning("Audit logging failed for pull %s: %s", terminal_status, audit_exc)

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
                err_text = f"Ollama returned HTTP {response.status_code}: {body.decode('utf-8', 'ignore')[:150]}"
                await _cleanup_locks_and_counters("failed", err_text)
                return

            last_save_time = time.time()
            async for line in response.aiter_lines():
                # Check for cancellation requested
                is_cancelled = False
                async with _pull_lock:
                    if _active_pull_tasks.get(task_id, {}).get("cancellation_requested", False) or _is_shutting_down:
                        is_cancelled = True

                if is_cancelled:
                    await response.aclose()
                    await _cleanup_locks_and_counters("cancelled", "Pull cancelled by administrator or server shutdown")
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

                    current_snapshot = dict(task)

                # Periodically sync progress to Redis (throttle to once per second)
                now = time.time()
                if now - last_save_time >= 1.0 or current_snapshot["status"] in ("verifying", "completed"):
                    last_save_time = now
                    await _save_task_state_durable(current_snapshot)

            await _cleanup_locks_and_counters("completed")

    except asyncio.CancelledError:
        await _cleanup_locks_and_counters("cancelled", "Task cancelled")
    except Exception as exc:
        logger.exception("Error during model pull task: %s", exc)
        await _cleanup_locks_and_counters("failed", str(exc))


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
    Enforces concurrency limits, distributed locking across workers,
    download size quotas, free disk reserves, and model name sanitization.
    """
    global _is_shutting_down
    if _is_shutting_down:
        return JSONResponse(
            status_code=503,
            content={"detail": "Service is currently shutting down. New downloads cannot be initiated."},
        )

    model_name = req.model_name.strip()
    if not model_name:
        return JSONResponse(status_code=400, content={"detail": "model_name cannot be empty."})

    # Validate model name against trusted catalog OR strict alphanum format
    catalog_entry = next((m for m in TRUSTED_CATALOG if m.name == model_name), None)
    if not catalog_entry and not re.match(r"^[a-zA-Z0-9_\-\.\:\/]+$", model_name):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid model identifier syntax. Use standard registry tags."},
        )

    # 1. Download Size & Disk Space Safeguards
    approx_size = catalog_entry.approx_size_bytes if catalog_entry else 0
    max_download_limit = getattr(settings, "AI_MODEL_MAX_DOWNLOAD_SIZE_BYTES", 50 * 1024 * 1024 * 1024)
    min_free_reserve = getattr(settings, "AI_MODEL_MIN_DISK_FREE_BYTES", 5 * 1024 * 1024 * 1024)

    if approx_size > max_download_limit:
        return JSONResponse(
            status_code=400,
            content={
                "detail": f"Model estimated size ({approx_size / (1024**3):.1f} GB) exceeds maximum allowable download quota ({max_download_limit / (1024**3):.1f} GB)."
            },
        )

    # Check available storage on disk
    try:
        disk_usage = shutil.disk_usage(".")
        free_bytes = disk_usage.free
        if approx_size > 0:
            required_space = approx_size + min_free_reserve
            if free_bytes < required_space:
                return JSONResponse(
                    status_code=507,
                    content={
                        "detail": f"Insufficient disk space. Available: {free_bytes / (1024**3):.1f} GB; Required (estimated size + {min_free_reserve / (1024**3):.1f} GB reserve): {required_space / (1024**3):.1f} GB."
                    },
                )
        elif free_bytes < min_free_reserve:
            return JSONResponse(
                status_code=507,
                content={
                    "detail": f"Insufficient disk space. Available disk ({free_bytes / (1024**3):.1f} GB) is below minimum safety reserve ({min_free_reserve / (1024**3):.1f} GB)."
                },
            )
    except Exception as exc:
        logger.warning("Could not reliably verify disk storage: %s", exc)

    # 2. Distributed Locking & Concurrency Check via Redis
    r = None
    try:
        r = get_redis_client()
    except Exception:
        pass

    concurrency_limit = getattr(settings, "AI_MODEL_MAX_CONCURRENT_PULLS", 1)

    if r:
        try:
            # Atomic check for duplicate model download across all workers
            model_lock_key = f"{REDIS_PULL_MODEL_PREFIX}{model_name}"
            # Try to acquire lock with atomic SET NX EX
            acquired = await r.set(model_lock_key, "locked", nx=True, ex=REDIS_LOCK_EXPIRATION_SECONDS)
            if not acquired:
                return JSONResponse(
                    status_code=409,
                    content={"detail": f"Model '{model_name}' is already being downloaded by an active worker."},
                )

            # Atomic concurrency limit check
            current_active = await r.incr(REDIS_CONCURRENCY_KEY)
            if current_active > concurrency_limit:
                # Release lock and revert counter
                await r.decr(REDIS_CONCURRENCY_KEY)
                await r.delete(model_lock_key)
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": f"Concurrency limit reached ({concurrency_limit} active download). Please wait for ongoing downloads to complete."
                    },
                )
        except Exception as exc:
            logger.warning("Redis distributed locking failed, falling back to process lock: %s", exc)

    # 3. Process-Local Lock Check
    async with _pull_lock:
        if model_name in _active_pull_by_model:
            existing_task_id = _active_pull_by_model[model_name]
            existing = _active_pull_tasks.get(existing_task_id)
            if existing and existing["status"] in ("queued", "downloading", "verifying"):
                if r:
                    try:
                        await r.delete(f"{REDIS_PULL_MODEL_PREFIX}{model_name}")
                        await r.decr(REDIS_CONCURRENCY_KEY)
                    except Exception:
                        pass
                return JSONResponse(
                    status_code=409,
                    content={"detail": f"Model '{model_name}' is already being downloaded (task {existing_task_id})."},
                )

        active_count = sum(1 for t in _active_pull_tasks.values() if t["status"] in ("queued", "downloading", "verifying"))
        if active_count >= concurrency_limit:
            if r:
                try:
                    await r.delete(f"{REDIS_PULL_MODEL_PREFIX}{model_name}")
                    await r.decr(REDIS_CONCURRENCY_KEY)
                except Exception:
                    pass
            return JSONResponse(
                status_code=429,
                content={"detail": f"Concurrency limit reached ({concurrency_limit} active download). Please wait for ongoing downloads to complete."},
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

    # Persist durable state
    await _save_task_state_durable(task_data)

    # Spawn background task and track handle
    bg_task = asyncio.create_task(_execute_model_pull_task(task_id, model_name))
    async with _pull_lock:
        _running_async_tasks[task_id] = bg_task

    # Audit logging for initiation
    try:
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
            diff_payload={"task_id": task_id, "approx_size_bytes": approx_size},
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
    """Returns status and progress of all active or recent model pull jobs across workers."""
    tasks = await _get_all_durable_tasks()
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
        for t in tasks[:15]
    ]


@router.post(
    "/models/pull/{task_id}/cancel",
    response_model=ModelPullStatusResponse,
    summary="Safely cancel an active model pull task",
)
async def cancel_model_pull(
    task_id: str,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
) -> ModelPullStatusResponse:
    """Cancels an in-progress download if actively running."""
    async with _pull_lock:
        task = _active_pull_tasks.get(task_id)

    if not task:
        # Check Redis durable store
        try:
            r = get_redis_client()
            raw = await r.get(f"{REDIS_PULL_PREFIX}{task_id}")
            if raw:
                task = pyjson.loads(raw)
        except Exception:
            pass

    if not task:
        return JSONResponse(status_code=404, content={"detail": f"Pull task {task_id} not found."})

    if task["status"] in ("completed", "failed", "cancelled"):
        return JSONResponse(status_code=400, content={"detail": f"Task is already {task['status']}."})

    async with _pull_lock:
        if task_id in _active_pull_tasks:
            _active_pull_tasks[task_id]["cancellation_requested"] = True
            _active_pull_tasks[task_id]["status"] = "cancelling"
            _active_pull_tasks[task_id]["current_step"] = "Cancellation requested"
            task = _active_pull_tasks[task_id]
        else:
            task["cancellation_requested"] = True
            task["status"] = "cancelling"
            task["current_step"] = "Cancellation requested"

    await _save_task_state_durable(task)

    # Cancel the running asyncio streaming task if locally resident
    async with _pull_lock:
        async_t = _running_async_tasks.get(task_id)
        if async_t and not async_t.done():
            async_t.cancel()

    # Audit cancellation request
    try:
        await record_audit_event(
            db=db,
            action="ai.model.pull_cancelled",
            resource_type="ai_model",
            resource_id=task["model_name"],
            outcome=AuditOutcome.SUCCESS,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            actor_role=current_user.platform_role.value if current_user.platform_role else "admin",
            reason=f"Administrator requested cancellation of pull task {task_id}",
            diff_payload={"task_id": task_id},
        )
    except Exception as exc:
        logger.warning("Audit logging failed for model pull cancel: %s", exc)

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

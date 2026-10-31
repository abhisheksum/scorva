import asyncio
from datetime import datetime, timezone
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from apps.api.config import settings
from apps.api.core.database import check_database_connection
from apps.api.core.metrics import metrics_collector
import apps.api.core.redis as core_async_redis
from apps.api.modules.health.schemas import (
    HealthResponse,
    HealthStatus,
    LivenessResponse,
    ServiceCheck,
)

router = APIRouter(tags=["System Health & Observability"])


@router.get("/health", response_model=HealthResponse, summary="Service health status")
async def get_health(response: Response) -> HealthResponse:
    """
    Returns general platform health and dependency readiness distinguishing
    database connectivity, broker/Redis availability, and core API responsive state.
    """
    start_time = time.perf_counter()

    # Core API internal latency
    api_latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    async def _check_ollama() -> tuple:
        try:
            o_start = time.perf_counter()
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags")
            o_lat = round((time.perf_counter() - o_start) * 1000, 2)
            if resp.status_code == 200:
                model_count = len(resp.json().get("models", []))
                return True, o_lat, f"Ollama reachable — {model_count} model(s) available"
            return False, o_lat, f"Ollama returned HTTP {resp.status_code}"
        except httpx.TimeoutException:
            return False, None, "Ollama probe timed out after 2s"
        except Exception as exc:
            return False, None, f"Ollama unreachable: {type(exc).__name__}"

    async def _check_redis() -> tuple:
        try:
            r_start = time.perf_counter()
            r_client = core_async_redis.get_redis_client()
            await asyncio.wait_for(r_client.ping(), timeout=1.5)
            r_lat = round((time.perf_counter() - r_start) * 1000, 2)
            return True, r_lat, "Redis connection responsive"
        except Exception as exc:
            return False, None, f"Redis connection check failed: {str(exc)}"

    # Run live database, Redis, and Ollama checks concurrently
    (db_healthy, db_latency, db_detail), (redis_healthy, redis_latency, redis_detail), (ollama_healthy, ollama_latency, ollama_detail) = await asyncio.gather(
        check_database_connection(timeout_seconds=2.0),
        _check_redis(),
        _check_ollama(),
    )


    db_status: HealthStatus = "healthy" if db_healthy else "unhealthy"
    redis_status: HealthStatus = "healthy" if redis_healthy else "unhealthy"
    ollama_status: HealthStatus = "healthy" if ollama_healthy else "unhealthy"

    services = {
        "api": ServiceCheck(
            status="healthy",
            latency_ms=api_latency_ms,
            details="FastAPI core service responsive",
        ),
        "database": ServiceCheck(
            status=db_status,
            latency_ms=db_latency,
            details=db_detail,
        ),
        "redis": ServiceCheck(
            status=redis_status,
            latency_ms=redis_latency,
            details=redis_detail,
        ),
        "broker": ServiceCheck(
            status=redis_status,
            latency_ms=redis_latency,
            details="Celery broker available via Redis" if redis_healthy else redis_detail,
        ),
        "ollama": ServiceCheck(
            status=ollama_status,
            latency_ms=ollama_latency,
            details=ollama_detail,
        ),
    }

    # If critical dependencies (database or redis) are down, platform status is unhealthy
    critical_ok = db_healthy and redis_healthy
    platform_status: HealthStatus = "healthy" if critical_ok else "unhealthy"
    if platform_status == "unhealthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status=platform_status,
        app_name="Scorva API",
        environment=settings.SCORVA_ENV,
        version="0.1.0",
        timestamp=datetime.now(timezone.utc),
        services=services,
    )



@router.get("/health/live", response_model=LivenessResponse, summary="Kubernetes liveness probe")
async def get_liveness() -> LivenessResponse:
    """Fast probe returning 200 OK when HTTP process is accepting traffic."""
    return LivenessResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/health/ready", response_model=HealthResponse, summary="Kubernetes readiness probe")
async def get_readiness(response: Response) -> HealthResponse:
    """Readiness probe verifying operational state."""
    return await get_health(response=response)


@router.get("/metrics", summary="Operational Prometheus Metrics Endpoint")
async def get_metrics_endpoint(request: Request, format: Optional[str] = None) -> Response:
    """
    Exports low-cardinality operational metrics in Prometheus text format
    (or structured JSON if requested via format=json or Accept: application/json).
    """
    accept = request.headers.get("accept", "")
    if format == "json" or "application/json" in accept.lower():
        return JSONResponse(content=metrics_collector.export_dict())

    return Response(
        content=metrics_collector.export_prometheus_text(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )

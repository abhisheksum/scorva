from datetime import datetime, timezone
import time
from fastapi import APIRouter, Response, status
from apps.api.config import settings
from apps.api.core.database import check_database_connection
from apps.api.modules.health.schemas import (
    HealthResponse,
    HealthStatus,
    LivenessResponse,
    ServiceCheck,
)

router = APIRouter(prefix="/health", tags=["System Health"])


@router.get("", response_model=HealthResponse, summary="Service health status")
async def get_health(response: Response = None) -> HealthResponse:
    """Returns general platform health and dependency readiness."""
    start_time = time.perf_counter()

    # Core API internal latency
    api_latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    # Live bounded database check
    db_healthy, db_latency, db_detail = await check_database_connection(timeout_seconds=2.0)
    db_status: HealthStatus = "healthy" if db_healthy else "unhealthy"

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
            status="unknown",
            details="Redis session store integration active in Phase 2",
        ),
        "ollama": ServiceCheck(
            status="unknown",
            details="Ollama client inference pipeline active in Phase 4",
        ),
    }

    # If database is down, platform status is unhealthy
    platform_status: HealthStatus = "healthy" if db_healthy else "unhealthy"
    if response and platform_status == "unhealthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status=platform_status,
        app_name="Scorva API",
        environment=settings.SCORVA_ENV,
        version="0.1.0",
        timestamp=datetime.now(timezone.utc),
        services=services,
    )


@router.get("/live", response_model=LivenessResponse, summary="Kubernetes liveness probe")
async def get_liveness() -> LivenessResponse:
    """Fast probe returning 200 OK when HTTP process is accepting traffic."""
    return LivenessResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/ready", response_model=HealthResponse, summary="Kubernetes readiness probe")
async def get_readiness(response: Response) -> HealthResponse:
    """Readiness probe verifying operational state."""
    return await get_health(response=response)

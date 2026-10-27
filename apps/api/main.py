from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Optional
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from apps.api.config import settings
from apps.api.core.exceptions import register_exception_handlers
from apps.api.core.logging import CorrelationIdMiddleware, logger, setup_logging
from apps.api.core.metrics import metrics_collector
from apps.api.core.redis import close_redis_client
from apps.api.middleware.csrf_origin import CsrfOriginMiddleware
from apps.api.middleware.proxy_headers import ProxyHeadersMiddleware

# Ensure all SQLAlchemy models are registered in Base.registry for relationship resolution
import apps.api.modules.audit.models  # noqa: F401
import apps.api.modules.auth.models  # noqa: F401
import apps.api.modules.configuration.models  # noqa: F401
import apps.api.modules.evaluations.models  # noqa: F401
import apps.api.modules.hackathons.models  # noqa: F401
import apps.api.modules.organizations.models  # noqa: F401
import apps.api.modules.rbac.models  # noqa: F401
import apps.api.modules.users.models  # noqa: F401

from apps.api.modules.audit.router import router as audit_router
from apps.api.modules.auth.router import router as auth_router
from apps.api.modules.configuration.router import router as configuration_router
from apps.api.modules.evaluations.router import router as evaluations_router
from apps.api.modules.evaluations.judge_router import router as judge_router
from apps.api.modules.evaluations.participant_router import router as participant_router
from apps.api.modules.hackathons.admin_router import router as admin_hackathons_router
from apps.api.modules.hackathons.router import router as hackathons_router
from apps.api.modules.health.router import router as health_router
from apps.api.modules.organizations.admin_router import router as admin_organizations_router
from apps.api.modules.organizations.router import router as organizations_router
from apps.api.modules.rbac.router import router as rbac_router
from apps.api.modules.users.router import router as users_router
from apps.api.modules.integrations.webhook_router import router as webhook_router
from apps.api.modules.dashboard.router import router as dashboard_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan context manager for startup and shutdown events."""
    setup_logging(debug=settings.DEBUG)
    logger.info(
        "Starting Scorva API in %s mode on %s:%s",
        settings.SCORVA_ENV,
        settings.HOST,
        settings.PORT,
    )
    yield
    logger.info("Closing Redis connection pool...")
    await close_redis_client()
    logger.info("Shutting down Scorva API service.")


def create_app() -> FastAPI:
    """Factory creating and configuring the FastAPI application."""
    app = FastAPI(
        title="Scorva Platform API",
        description="Scorva AI-Assisted Hackathon Evaluation SaaS Platform API",
        version="0.1.0",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # 1. Correlation Tracking
    app.add_middleware(CorrelationIdMiddleware)

    # 2. Trusted Proxy Client IP Extraction
    app.add_middleware(ProxyHeadersMiddleware)

    # 3. CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )

    # 4. Strict CSRF / Origin Verification
    app.add_middleware(CsrfOriginMiddleware)

    # Global Exception Handlers (RFC 7807 / RFC 9457)
    register_exception_handlers(app)

    # Register API Routers
    app.include_router(health_router, prefix=settings.API_V1_PREFIX)
    app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
    app.include_router(auth_router, prefix=f"{settings.API_V1_PREFIX}/admin")
    app.include_router(users_router, prefix=settings.API_V1_PREFIX)
    app.include_router(audit_router, prefix=settings.API_V1_PREFIX)
    app.include_router(admin_organizations_router, prefix=settings.API_V1_PREFIX)
    app.include_router(organizations_router, prefix=settings.API_V1_PREFIX)
    app.include_router(admin_hackathons_router, prefix=settings.API_V1_PREFIX)
    app.include_router(hackathons_router, prefix=settings.API_V1_PREFIX)
    app.include_router(configuration_router, prefix=settings.API_V1_PREFIX)
    app.include_router(rbac_router, prefix=settings.API_V1_PREFIX)
    app.include_router(evaluations_router, prefix=settings.API_V1_PREFIX)
    app.include_router(judge_router, prefix=settings.API_V1_PREFIX)
    app.include_router(participant_router, prefix=settings.API_V1_PREFIX)
    app.include_router(webhook_router, prefix=settings.API_V1_PREFIX)
    app.include_router(dashboard_router, prefix=settings.API_V1_PREFIX)

    @app.get("/metrics", tags=["Observability"])
    async def metrics_root(request: Request, format: Optional[str] = None) -> Response:
        accept = request.headers.get("accept", "")
        if format == "json" or "application/json" in accept.lower():
            return JSONResponse(content=metrics_collector.export_dict())
        return Response(
            content=metrics_collector.export_prometheus_text(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/", tags=["Root"])
    async def root() -> Dict[str, str]:
        return {
            "name": "Scorva Platform API",
            "version": "0.1.0",
            "environment": settings.SCORVA_ENV,
            "status": "operational",
            "docs": "/docs" if settings.DEBUG else "disabled",
        }

    return app


app = create_app()

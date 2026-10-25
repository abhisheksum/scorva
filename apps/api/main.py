from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apps.api.config import settings
from apps.api.core.exceptions import register_exception_handlers
from apps.api.core.logging import CorrelationIdMiddleware, logger, setup_logging
from apps.api.modules.health.router import router as health_router


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

    # Correlation ID & Logging Middleware
    app.add_middleware(CorrelationIdMiddleware)

    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )

    # Global Exception Handlers
    register_exception_handlers(app)

    # Register API Routers
    app.include_router(health_router, prefix=settings.API_V1_PREFIX)

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

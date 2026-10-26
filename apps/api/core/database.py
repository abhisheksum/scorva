import time
from typing import AsyncGenerator, Optional, Tuple
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase
from apps.api.config import settings


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy entities."""
    pass


# Initialize async SQLAlchemy 2.0 engine
# NullPool is used in test environment to avoid pooling connections across pytest event loops
_engine_kwargs = {
    "pool_pre_ping": True,
    "echo": False,
}
if settings.SCORVA_ENV == "test":
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 5

async_engine = create_async_engine(
    settings.DATABASE_URL,
    **_engine_kwargs,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency yielding an asynchronous database session with auto-rollback on error."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_database_connection(timeout_seconds: float = 2.0) -> Tuple[bool, Optional[float], Optional[str]]:
    """
    Executes a bounded connectivity check against PostgreSQL.
    Returns (is_healthy, latency_ms, error_detail).
    """
    start_time = time.perf_counter()
    try:
        async with async_engine.connect() as conn:
            # Execute with statement timeout
            await conn.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return True, latency_ms, "PostgreSQL async connection responsive"
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return False, latency_ms, f"PostgreSQL connection failed: {str(exc)}"

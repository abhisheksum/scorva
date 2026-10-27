from contextlib import contextmanager
import logging
from typing import Generator, Optional

from celery.signals import worker_process_init
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from apps.api.config import settings

logger = logging.getLogger(__name__)

_worker_engine: Optional[Engine] = None
_worker_session_factory: Optional[sessionmaker] = None


def get_sync_database_url() -> str:
    """Returns the synchronous database URL for worker processes (psycopg2)."""
    url = settings.DATABASE_URL
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "+psycopg2")
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def get_worker_engine() -> Engine:
    """
    Returns the singleton synchronous database engine for Celery workers.
    Configured with a bounded QueuePool, connection pre-ping, and recycling.
    """
    global _worker_engine
    if _worker_engine is None:
        sync_url = get_sync_database_url()
        _worker_engine = create_engine(
            sync_url,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30.0,
            pool_recycle=1800,
            pool_pre_ping=True,
            echo=False,
        )
    return _worker_engine


def get_worker_session_factory() -> sessionmaker:
    """Returns the session factory bound to the worker engine."""
    global _worker_session_factory
    if _worker_session_factory is None:
        _worker_session_factory = sessionmaker(
            bind=get_worker_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _worker_session_factory


@worker_process_init.connect
def on_worker_process_init(**kwargs) -> None:
    """
    Celery worker process initialization signal handler.
    Disposes of inherited parent process engine pool to prevent connection sharing across forks.
    """
    global _worker_engine, _worker_session_factory
    if _worker_engine is not None:
        _worker_engine.dispose()
        _worker_engine = None
        _worker_session_factory = None
    logger.info("Worker process initialized: reset database connection pool.")


@contextmanager
def worker_session_scope() -> Generator[Session, None, None]:
    """
    Dedicated Task-Scoped Synchronous Database Session Context Manager.

    Guarantees:
    1. Transaction commits on successful block execution.
    2. Automatic rollback on unhandled exceptions.
    3. Mandatory session closure in finally block, releasing the database connection
       back to the pool immediately.
    4. Short-lived usage: workers must never hold this session open during long
       network calls, archive streaming, or model inference.
    """
    factory = get_worker_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

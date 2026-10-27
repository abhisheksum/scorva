import pytest
from sqlalchemy import text
from apps.api.core.database import check_database_connection, get_db_session, async_engine
from alembic.config import Config
from alembic.script import ScriptDirectory


@pytest.mark.asyncio
async def test_database_connection_check():
    """Verifies that the bounded health probe connects to PostgreSQL and returns latency."""
    is_healthy, latency, detail = await check_database_connection(timeout_seconds=2.0)
    assert is_healthy is True
    assert latency is not None
    assert latency > 0.0
    assert "responsive" in detail


@pytest.mark.asyncio
async def test_database_session_execution():
    """Verifies that get_db_session yields a usable AsyncSession."""
    async for session in get_db_session():
        result = await session.execute(text("SELECT 1 AS num, 'scorva' AS app"))
        row = result.fetchone()
        assert row is not None
        assert row.num == 1
        assert row.app == "scorva"


def test_alembic_configuration_validity():
    """Verifies that alembic.ini and script directory are discoverable and valid."""
    alembic_cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)
    # Phase 4 Milestone 5.1 outbox head
    heads = script.get_heads()
    assert len(heads) == 1
    assert heads[0] == "9e37b1c1921d"

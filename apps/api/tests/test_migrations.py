import asyncio
import asyncpg
import pytest
from alembic.config import Config
from alembic import command
from apps.api.config import settings
from apps.api.core.database import check_database_connection


def test_alembic_downgrade_and_upgrade_cycle():
    """
    Verifies that Alembic can downgrade to base and re-upgrade to head cleanly.
    Runs against an isolated test database to protect active development state.
    """
    cycle_db_name = "scorva_cycle_test_db"
    
    async def _init_cycle_db():
        conn = await asyncpg.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
        await conn.execute(f"DROP DATABASE IF EXISTS {cycle_db_name};")
        await conn.execute(f"CREATE DATABASE {cycle_db_name};")
        await conn.close()
    asyncio.run(_init_cycle_db())

    try:
        cfg = Config("alembic.ini")
        cycle_url = settings.DATABASE_URL.rsplit("/", 1)[0] + f"/{cycle_db_name}"
        cfg.set_main_option("sqlalchemy.url", cycle_url)

        # Upgrade to head
        command.upgrade(cfg, "head")
        # Downgrade to base
        command.downgrade(cfg, "base")
        # Re-upgrade to head
        command.upgrade(cfg, "head")
    finally:
        async def _drop_cycle_db():
            conn = await asyncpg.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
            await conn.execute(f"DROP DATABASE IF EXISTS {cycle_db_name};")
            await conn.close()
        asyncio.run(_drop_cycle_db())


def test_clean_database_migration_cycle():
    """
    Verifies that Alembic upgrade head and downgrade base work cleanly against an entirely clean PostgreSQL database.
    """
    clean_db_name = "scorva_clean_test_db"
    
    # 1. Create clean db
    async def _init_clean_db():
        conn = await asyncpg.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
        await conn.execute(f"DROP DATABASE IF EXISTS {clean_db_name};")
        await conn.execute(f"CREATE DATABASE {clean_db_name};")
        await conn.close()
    asyncio.run(_init_clean_db())

    try:
        cfg = Config("alembic.ini")
        clean_url = settings.DATABASE_URL.rsplit("/", 1)[0] + f"/{clean_db_name}"
        cfg.set_main_option("sqlalchemy.url", clean_url)

        # 2. Upgrade to head
        command.upgrade(cfg, "head")

        # 3. Verify tables and trigger
        async def _verify_tables():
            conn = await asyncpg.connect(clean_url.replace("+asyncpg", ""))
            tables = await conn.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;"
            )
            table_names = [r["table_name"] for r in tables]
            trigger = await conn.fetchval(
                "SELECT tgname FROM pg_trigger WHERE tgname = 'trg_audit_events_immutable';"
            )
            enums = await conn.fetch(
                "SELECT typname FROM pg_type WHERE typname IN ('audit_outcome_enum', 'platform_role_enum', 'organization_status_enum', 'hackathon_status_enum', 'org_role_enum', 'membership_status_enum');"
            )
            await conn.close()
            return table_names, trigger, [r["typname"] for r in enums]

        table_names, trigger_name, enum_names = asyncio.run(_verify_tables())
        assert "audit_events" in table_names
        assert "users" in table_names
        assert "user_sessions" in table_names
        assert "organizations" in table_names
        assert "hackathons" in table_names
        assert "organization_memberships" in table_names
        assert trigger_name == "trg_audit_events_immutable"
        assert "audit_outcome_enum" in enum_names
        assert "platform_role_enum" in enum_names
        assert "organization_status_enum" in enum_names
        assert "hackathon_status_enum" in enum_names
        assert "org_role_enum" in enum_names
        assert "membership_status_enum" in enum_names

        # 4. Downgrade to base
        command.downgrade(cfg, "base")

        # 5. Verify tables and enums are dropped
        async def _verify_dropped():
            conn = await asyncpg.connect(clean_url.replace("+asyncpg", ""))
            tables = await conn.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;"
            )
            enums = await conn.fetch(
                "SELECT typname FROM pg_type WHERE typname IN ('audit_outcome_enum', 'platform_role_enum', 'organization_status_enum', 'hackathon_status_enum', 'org_role_enum', 'membership_status_enum');"
            )
            await conn.close()
            return [r["table_name"] for r in tables], [r["typname"] for r in enums]

        remaining_tables, remaining_enums = asyncio.run(_verify_dropped())
        assert "audit_events" not in remaining_tables
        assert "users" not in remaining_tables
        assert "user_sessions" not in remaining_tables
        assert "organizations" not in remaining_tables
        assert "hackathons" not in remaining_tables
        assert "organization_memberships" not in remaining_tables
        assert len(remaining_enums) == 0

    finally:
        # 6. Teardown clean db
        async def _drop_clean_db():
            conn = await asyncpg.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
            await conn.execute(f"DROP DATABASE IF EXISTS {clean_db_name};")
            await conn.close()
        asyncio.run(_drop_clean_db())


def test_migration_upgrade_from_phase2_head():
    """
    Verifies that Alembic can cleanly upgrade from the Phase 2 schema (89e5bd9e37a3)
    to Phase 3 head (de1a35a5cc94), and downgrade back to Phase 2 head without data loss.
    """
    phase2_db_name = "scorva_phase2_upgrade_test_db"

    # 1. Create clean db and apply up to Phase 2 head
    async def _init_phase2_db():
        conn = await asyncpg.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
        await conn.execute(f"DROP DATABASE IF EXISTS {phase2_db_name};")
        await conn.execute(f"CREATE DATABASE {phase2_db_name};")
        await conn.close()
    asyncio.run(_init_phase2_db())

    try:
        cfg = Config("alembic.ini")
        phase2_url = settings.DATABASE_URL.rsplit("/", 1)[0] + f"/{phase2_db_name}"
        cfg.set_main_option("sqlalchemy.url", phase2_url)

        # 2. Upgrade to Phase 2 head
        command.upgrade(cfg, "89e5bd9e37a3")

        # 3. Verify Phase 2 schema present, Phase 3 absent
        async def _verify_phase2_state():
            conn = await asyncpg.connect(phase2_url.replace("+asyncpg", ""))
            tables = [r["table_name"] for r in await conn.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
            )]
            await conn.close()
            return tables

        p2_tables = asyncio.run(_verify_phase2_state())
        assert "users" in p2_tables
        assert "audit_events" in p2_tables
        assert "organizations" not in p2_tables
        assert "hackathons" not in p2_tables

        # 4. Upgrade to Phase 3 head
        command.upgrade(cfg, "head")

        p3_tables = asyncio.run(_verify_phase2_state())
        assert "organizations" in p3_tables
        assert "hackathons" in p3_tables
        assert "organization_memberships" in p3_tables

        # 5. Downgrade back to Phase 2 head
        command.downgrade(cfg, "89e5bd9e37a3")

        post_downgrade_tables = asyncio.run(_verify_phase2_state())
        assert "users" in post_downgrade_tables
        assert "audit_events" in post_downgrade_tables
        assert "organizations" not in post_downgrade_tables
        assert "hackathons" not in post_downgrade_tables
        assert "organization_memberships" not in post_downgrade_tables

    finally:
        async def _drop_phase2_db():
            conn = await asyncpg.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
            await conn.execute(f"DROP DATABASE IF EXISTS {phase2_db_name};")
            await conn.close()
        asyncio.run(_drop_phase2_db())


@pytest.mark.asyncio
async def test_database_healthy_after_migration_cycle():
    """Verifies that database connection probe reports healthy after migration cycle."""
    is_healthy, latency, _ = await check_database_connection()
    assert is_healthy is True
    assert latency is not None

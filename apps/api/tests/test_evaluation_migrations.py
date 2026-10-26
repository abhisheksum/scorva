import asyncio
import asyncpg
import pytest
from alembic.config import Config
from alembic import command
from apps.api.config import settings


def test_m2_evaluation_schema_and_remediation_upgrade_and_downgrade_cycle():
    """
    Verifies the complete migration lifecycle:
    1. Upgrades from Milestone 1 head (ff171550944b) to Milestone 2 initial (c053567b0586).
    2. Upgrades from c053567b0586 to remediation migration (d630cee07d82).
       Verifies foreign key fk_evaluation_jobs_current_result_id,
       trg_rubric_versions_protect, and trg_submission_snapshots_immutable.
    3. Downgrades cleanly from d630cee07d82 back to c053567b0586.
    4. Downgrades cleanly from c053567b0586 back to ff171550944b.
    5. Re-upgrades all the way to head (d630cee07d82) to prove full idempotency.
    Runs against an isolated disposable database to protect active development state.
    """
    disposable_db_name = "scorva_m2_migration_test_db"
    base_url = settings.DATABASE_URL.replace("+asyncpg", "")

    # 1. Create clean disposable database
    async def _init_disposable_db():
        conn = await asyncpg.connect(base_url)
        await conn.execute(f"DROP DATABASE IF EXISTS {disposable_db_name};")
        await conn.execute(f"CREATE DATABASE {disposable_db_name};")
        await conn.close()
    asyncio.run(_init_disposable_db())

    try:
        cfg = Config("alembic.ini")
        m2_url = settings.DATABASE_URL.rsplit("/", 1)[0] + f"/{disposable_db_name}"
        cfg.set_main_option("sqlalchemy.url", m2_url)

        # 2. Upgrade to Milestone 1 head (ff171550944b)
        command.upgrade(cfg, "ff171550944b")

        async def _check_m1_state():
            conn = await asyncpg.connect(m2_url.replace("+asyncpg", ""))
            tables = [r["table_name"] for r in await conn.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
            )]
            await conn.close()
            return tables

        m1_tables = asyncio.run(_check_m1_state())
        assert "roles" in m1_tables
        assert "configuration_settings" in m1_tables
        assert "teams" not in m1_tables
        assert "rubrics" not in m1_tables

        # 3. Upgrade to Milestone 2 initial head (c053567b0586)
        command.upgrade(cfg, "c053567b0586")

        async def _check_m2_initial_state():
            conn = await asyncpg.connect(m2_url.replace("+asyncpg", ""))
            tables = [r["table_name"] for r in await conn.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
            )]
            trigger = await conn.fetchval(
                "SELECT tgname FROM pg_trigger WHERE tgname = 'trg_rubric_criteria_immutable';"
            )
            col_type = await conn.fetchval(
                """
                SELECT data_type FROM information_schema.columns
                WHERE table_name = 'submission_snapshots' AND column_name = 'configuration_snapshot';
                """
            )
            await conn.close()
            return tables, trigger, col_type

        expected_m2_tables = [
            "teams",
            "team_members",
            "submissions",
            "submission_snapshots",
            "rubrics",
            "rubric_versions",
            "rubric_criteria",
            "evaluation_jobs",
            "evaluation_results",
            "evaluation_criterion_scores",
            "evidence_references",
            "judge_reviews",
            "judge_criterion_scores",
            "organization_integrations",
            "hackathon_judges",
        ]
        m2_tables, m2_trigger, jsonb_col_type = asyncio.run(_check_m2_initial_state())
        for tbl in expected_m2_tables:
            assert tbl in m2_tables, f"Table '{tbl}' missing after initial M2 upgrade"
        assert m2_trigger == "trg_rubric_criteria_immutable"
        assert jsonb_col_type == "jsonb"

        # 4. Upgrade to M2 remediation head (d630cee07d82)
        command.upgrade(cfg, "d630cee07d82")

        async def _check_remediation_state():
            conn = await asyncpg.connect(m2_url.replace("+asyncpg", ""))
            fk_name = await conn.fetchval(
                """
                SELECT conname FROM pg_constraint
                WHERE conname = 'fk_evaluation_jobs_current_result_id';
                """
            )
            triggers = [r["tgname"] for r in await conn.fetch(
                """
                SELECT tgname FROM pg_trigger
                WHERE tgname IN (
                    'trg_rubric_criteria_immutable',
                    'trg_rubric_versions_protect',
                    'trg_submission_snapshots_immutable'
                );
                """
            )]
            await conn.close()
            return fk_name, triggers

        remed_fk, remed_triggers = asyncio.run(_check_remediation_state())
        assert remed_fk == "fk_evaluation_jobs_current_result_id"
        assert "trg_rubric_criteria_immutable" in remed_triggers
        assert "trg_rubric_versions_protect" in remed_triggers
        assert "trg_submission_snapshots_immutable" in remed_triggers

        # 5. Downgrade from d630cee07d82 back to c053567b0586
        command.downgrade(cfg, "c053567b0586")

        async def _check_post_remediation_downgrade():
            conn = await asyncpg.connect(m2_url.replace("+asyncpg", ""))
            fk_name = await conn.fetchval(
                "SELECT conname FROM pg_constraint WHERE conname = 'fk_evaluation_jobs_current_result_id';"
            )
            protect_trigger = await conn.fetchval(
                "SELECT tgname FROM pg_trigger WHERE tgname = 'trg_rubric_versions_protect';"
            )
            snapshot_trigger = await conn.fetchval(
                "SELECT tgname FROM pg_trigger WHERE tgname = 'trg_submission_snapshots_immutable';"
            )
            criteria_trigger = await conn.fetchval(
                "SELECT tgname FROM pg_trigger WHERE tgname = 'trg_rubric_criteria_immutable';"
            )
            await conn.close()
            return fk_name, protect_trigger, snapshot_trigger, criteria_trigger

        down_fk, down_pt, down_st, down_ct = asyncio.run(_check_post_remediation_downgrade())
        assert down_fk is None
        assert down_pt is None
        assert down_st is None
        assert down_ct == "trg_rubric_criteria_immutable"

        # 6. Downgrade from c053567b0586 back to ff171550944b
        command.downgrade(cfg, "ff171550944b")

        async def _check_post_m1_downgrade():
            conn = await asyncpg.connect(m2_url.replace("+asyncpg", ""))
            tables = [r["table_name"] for r in await conn.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
            )]
            trigger = await conn.fetchval(
                "SELECT tgname FROM pg_trigger WHERE tgname = 'trg_rubric_criteria_immutable';"
            )
            await conn.close()
            return tables, trigger

        post_tables, post_trigger = asyncio.run(_check_post_m1_downgrade())
        assert "roles" in post_tables
        assert "configuration_settings" in post_tables
        for tbl in expected_m2_tables:
            assert tbl not in post_tables, f"Table '{tbl}' remained after M2 downgrade"
        assert post_trigger is None

        # 7. Re-upgrade from ff171550944b all the way to head (d630cee07d82)
        command.upgrade(cfg, "head")

        re_fk, re_triggers = asyncio.run(_check_remediation_state())
        assert re_fk == "fk_evaluation_jobs_current_result_id"
        assert "trg_rubric_criteria_immutable" in re_triggers
        assert "trg_rubric_versions_protect" in re_triggers
        assert "trg_submission_snapshots_immutable" in re_triggers

    finally:
        async def _drop_disposable_db():
            conn = await asyncpg.connect(base_url)
            await conn.execute(f"DROP DATABASE IF EXISTS {disposable_db_name};")
            await conn.close()
        asyncio.run(_drop_disposable_db())

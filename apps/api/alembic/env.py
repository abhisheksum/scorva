import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from apps.api.config import settings
from apps.api.core.database import Base
from apps.api.modules.users.models import User, UserSession  # noqa: F401
from apps.api.modules.audit.models import AuditEvent  # noqa: F401
from apps.api.modules.auth.models import TotpReplayPrevention, RateLimitBucket, MfaPendingToken  # noqa: F401
from apps.api.modules.organizations.models import Organization, OrganizationMembership  # noqa: F401
from apps.api.modules.hackathons.models import Hackathon  # noqa: F401
from apps.api.modules.configuration.models import ConfigurationSetting, ConfigurationOverride, ConfigurationHistory  # noqa: F401
from apps.api.modules.rbac.models import Permission, Role, RolePermission, UserRoleAssignment, AuthzPolicyVersion, AuthzInvalidationOutbox  # noqa: F401
from apps.api.modules.evaluations.models import (  # noqa: F401
    Team,
    TeamMember,
    Submission,
    SubmissionSnapshot,
    Rubric,
    RubricVersion,
    RubricCriterion,
    EvaluationJob,
    EvaluationResult,
    EvaluationCriterionScore,
    EvidenceReference,
    JudgeReview,
    JudgeCriterionScore,
    OrganizationIntegration,
    HackathonJudge,
)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set database URL dynamically from Pydantic settings if not explicitly provided
url_in_config = config.get_main_option("sqlalchemy.url")
if not url_in_config or "driver://user:pass@localhost/dbname" in url_in_config:
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Target metadata for autogenerate support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

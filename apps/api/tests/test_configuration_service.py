import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.modules.configuration.models import ConfigurationHistory, ConfigurationOverride, ConfigurationSetting
from apps.api.modules.configuration.service import (
    get_all_platform_settings,
    get_setting_by_key,
    resolve_effective_configuration,
    rollback_platform_setting,
    set_configuration_override,
    update_platform_setting,
    validate_and_parse_setting_value,
)
from apps.api.modules.organizations.models import Organization, OrganizationMembership, OrganizationStatus, OrgRole
from apps.api.modules.users.models import PlatformRole, User


@pytest.mark.asyncio
async def test_configuration_defaults_and_validation(db_session: AsyncSession):
    """Verifies typed validation, default retrieval, and normalization."""
    # Boolean parsing
    assert validate_and_parse_setting_value("judge.require_override_rationale", "true", "bool") == "true"
    assert validate_and_parse_setting_value("judge.require_override_rationale", "false", "bool") == "false"
    assert validate_and_parse_setting_value("judge.require_override_rationale", "1", "bool") == "true"
    assert validate_and_parse_setting_value("judge.require_override_rationale", "0", "bool") == "false"

    # Integer parsing with bounds
    assert validate_and_parse_setting_value(
        "judge.min_override_rationale_length", "25", "int", min_val="10", max_val="100"
    ) == "25"

    # Out of range integer
    with pytest.raises(Exception) as exc_info:
        validate_and_parse_setting_value(
            "judge.min_override_rationale_length", "5", "int", min_val="10", max_val="100"
        )
    assert "below permissible minimum" in str(exc_info.value)

    with pytest.raises(Exception) as exc_info:
        validate_and_parse_setting_value(
            "judge.min_override_rationale_length", "150", "int", min_val="10", max_val="100"
        )
    assert "exceeds permissible maximum" in str(exc_info.value)

    # Architectural Two-Phase bounds (10MB to 100MB)
    with pytest.raises(Exception) as exc_info:
        validate_and_parse_setting_value("extract.max_compressed_bytes", "1000", "int")
    assert "between 10485760 and 104857600" in str(exc_info.value)


@pytest.mark.asyncio
async def test_immutable_security_invariant_cannot_be_modified(db_session: AsyncSession, create_user_helper):
    """Verifies Tier 5 security invariants (extract.allow_symlinks) strictly reject updates."""
    admin = await create_user_helper("config_admin@scorva.io", PlatformRole.PLATFORM_OWNER)

    # Direct validation check
    with pytest.raises(Exception) as exc_info:
        validate_and_parse_setting_value("extract.allow_symlinks", "true", "bool")
    assert "immutable security invariant" in str(exc_info.value)


@pytest.mark.asyncio
async def test_optimistic_concurrency_and_history(db_session: AsyncSession, create_user_helper):
    """Verifies update version increments, optimistic concurrency conflicts, and history tracking."""
    admin = await create_user_helper("opt_admin@scorva.io", PlatformRole.PLATFORM_OWNER)

    setting = await get_setting_by_key(db_session, "judge.min_override_rationale_length")
    initial_version = setting.version

    # Successful update
    from apps.api.modules.configuration.schemas import ConfigurationSettingUpdate
    updated = await update_platform_setting(
        db=db_session,
        key="judge.min_override_rationale_length",
        payload=ConfigurationSettingUpdate(value="30", expected_version=initial_version, change_reason="Testing update"),
        actor=admin,
    )
    assert updated.current_value == "30"
    assert updated.version == initial_version + 1

    # Stale update should fail with 409
    with pytest.raises(Exception) as exc_info:
        await update_platform_setting(
            db=db_session,
            key="judge.min_override_rationale_length",
            payload=ConfigurationSettingUpdate(value="40", expected_version=initial_version, change_reason="Stale update"),
            actor=admin,
        )
    assert "updated concurrently" in str(exc_info.value) or "OPTIMISTIC_CONCURRENCY_CONFLICT" in str(exc_info.value)

    # Verify history record exists
    hist = (await db_session.execute(
        select(ConfigurationHistory)
        .where(ConfigurationHistory.setting_key == "judge.min_override_rationale_length")
        .order_by(ConfigurationHistory.version.desc())
    )).scalars().first()
    assert hist is not None
    assert hist.new_value == "30"
    assert hist.actor_user_id == admin.id


@pytest.mark.asyncio
async def test_rollback_creates_new_version_and_preserves_history(db_session: AsyncSession, create_user_helper):
    """Verifies rollback creates a new version, preserves history, and re-validates bounds."""
    admin = await create_user_helper("rollback_admin@scorva.io", PlatformRole.PLATFORM_OWNER)

    # Current version is at version 2 (value "30") from previous test, let's update to "45"
    setting = await get_setting_by_key(db_session, "judge.min_override_rationale_length")
    from apps.api.modules.configuration.schemas import ConfigurationRollbackRequest, ConfigurationSettingUpdate

    v2 = setting.version
    await update_platform_setting(
        db=db_session,
        key="judge.min_override_rationale_length",
        payload=ConfigurationSettingUpdate(value="45", expected_version=v2),
        actor=admin,
    )

    # Now rollback to v2
    setting_after_update = await get_setting_by_key(db_session, "judge.min_override_rationale_length")
    current_ver = setting_after_update.version

    rolled_back = await rollback_platform_setting(
        db=db_session,
        key="judge.min_override_rationale_length",
        payload=ConfigurationRollbackRequest(target_version=v2, expected_version=current_ver),
        actor=admin,
    )

    assert rolled_back.current_value == "30"
    assert rolled_back.version == current_ver + 1

    # Verify history has a 'rollback' record with restored_from_version = v2
    hist_records = (await db_session.execute(
        select(ConfigurationHistory)
        .where(ConfigurationHistory.setting_key == "judge.min_override_rationale_length")
        .order_by(ConfigurationHistory.version.desc())
    )).scalars().all()

    latest_hist = hist_records[0]
    assert latest_hist.change_type == "rollback"
    assert latest_hist.restored_from_version == v2
    assert latest_hist.new_value == "30"


@pytest.mark.asyncio
async def test_hierarchical_configuration_precedence(db_session: AsyncSession, create_user_helper):
    """Verifies precedence: Default -> Platform -> Organization -> Hackathon."""
    admin = await create_user_helper("prec_admin@scorva.io", PlatformRole.PLATFORM_OWNER)

    # 1. Base platform resolution
    effective_base = await resolve_effective_configuration(db_session)
    assert effective_base.ai_default_model == "llama3.3:70b"

    # 2. Add Organization override
    org_id = uuid.uuid4()
    await set_configuration_override(
        db=db_session,
        setting_key="ai.default_model",
        scope_type="organization",
        scope_id=org_id,
        value="qwen2.5:32b",
        expected_version=None,
        actor=admin,
    )

    effective_org = await resolve_effective_configuration(db_session, organization_id=org_id)
    assert effective_org.ai_default_model == "qwen2.5:32b"

    # 3. Add Hackathon override
    hack_id = uuid.uuid4()
    await set_configuration_override(
        db=db_session,
        setting_key="ai.default_model",
        scope_type="hackathon",
        scope_id=hack_id,
        value="mistral-large:latest",
        expected_version=None,
        actor=admin,
    )

    # When resolving for both org and hackathon, hackathon override wins
    effective_hack = await resolve_effective_configuration(
        db_session, organization_id=org_id, hackathon_id=hack_id
    )
    assert effective_hack.ai_default_model == "mistral-large:latest"


@pytest.mark.asyncio
async def test_unauthorized_override_rejection(db_session: AsyncSession, create_user_helper):
    """Verifies that settings with allow_org_override=False reject organization overrides."""
    admin = await create_user_helper("unauth_admin@scorva.io", PlatformRole.PLATFORM_OWNER)

    # Setting 'judge.allow_score_adjustment_after_finalization' has allow_org_override = False
    org_id = uuid.uuid4()
    with pytest.raises(Exception) as exc_info:
        await set_configuration_override(
            db=db_session,
            setting_key="judge.allow_score_adjustment_after_finalization",
            scope_type="organization",
            scope_id=org_id,
            value="true",
            expected_version=None,
            actor=admin,
        )
    assert "not permitted" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_ai_provider_setting_validation_and_production_guard(monkeypatch):
    """
    SEC-M4-02: Verifies ai.default_provider accepts only 'ollama' and 'mock',
    and strictly forbids 'mock' when SCORVA_ENV == 'production'.
    """
    from apps.api.config import settings

    # In test/dev environment:
    assert validate_and_parse_setting_value("ai.default_provider", "ollama", "string") == "ollama"
    assert validate_and_parse_setting_value("ai.default_provider", "OLLAMA", "string") == "ollama"
    assert validate_and_parse_setting_value("ai.default_provider", "mock", "string") == "mock"

    # Unsupported provider names must be rejected with 422
    with pytest.raises(Exception) as exc_unsupported:
        validate_and_parse_setting_value("ai.default_provider", "openai", "string")
    assert "only supports 'ollama' or 'mock'" in str(exc_unsupported.value)

    with pytest.raises(Exception) as exc_anthropic:
        validate_and_parse_setting_value("ai.default_provider", "anthropic", "string")
    assert "only supports 'ollama' or 'mock'" in str(exc_anthropic.value)

    # In production environment: 'mock' must be strictly forbidden with 403
    monkeypatch.setattr(settings, "SCORVA_ENV", "production")
    with pytest.raises(Exception) as exc_prod:
        validate_and_parse_setting_value("ai.default_provider", "mock", "string")
    assert "Mock AI provider is strictly prohibited in production" in str(exc_prod.value)

    # 'ollama' remains allowed in production
    assert validate_and_parse_setting_value("ai.default_provider", "ollama", "string") == "ollama"

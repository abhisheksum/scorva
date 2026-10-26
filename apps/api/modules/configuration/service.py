from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.core.exceptions import AppException
from apps.api.modules.audit.models import AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.configuration.catalog import CONFIGURATION_CATALOG, SettingDefinition
from apps.api.modules.configuration.models import (
    ConfigurationHistory,
    ConfigurationOverride,
    ConfigurationSetting,
)
from apps.api.modules.configuration.schemas import (
    ConfigurationRollbackRequest,
    ConfigurationSettingResponse,
    ConfigurationSettingUpdate,
    EffectiveConfiguration,
)
from apps.api.modules.rbac.models import PLATFORM_SCOPE_ID
from apps.api.modules.users.models import User

logger = logging.getLogger("scorva.configuration.service")

# Catalog lookup index
CATALOG_BY_KEY: Dict[str, SettingDefinition] = {s.key: s for s in CONFIGURATION_CATALOG}

# Hard architectural bounds for Two-Phase Validation (Phase 1)
ABSOLUTE_LIMITS = {
    "extract.max_compressed_bytes": (10_485_760, 104_857_600),     # 10MB - 100MB
    "extract.max_uncompressed_bytes": (52_428_800, 524_288_000),   # 50MB - 500MB
    "extract.max_file_count": (100, 5_000),                         # 100 - 5000 files
    "extract.max_archive_depth": (1, 10),                           # 1 - 10 levels
}


def validate_and_parse_setting_value(
    key: str,
    value_str: str,
    data_type: str,
    min_val: Optional[str] = None,
    max_val: Optional[str] = None,
) -> str:
    """
    Validates, parses, and normalizes a configuration setting value.
    Enforces Phase 1 architectural bounds and data type integrity.
    """
    raw = value_str.strip()

    if data_type == "bool":
        lower = raw.lower()
        if lower in ("true", "1", "yes"):
            normalized = "true"
        elif lower in ("false", "0", "no"):
            normalized = "false"
        else:
            raise AppException(
                status_code=422,
                code="INVALID_BOOLEAN_VALUE",
                message=f"Setting '{key}' expects a boolean value ('true' or 'false'). Got '{value_str}'.",
                title="Invalid Setting Value",
            )
        # Check immutable security invariants
        if key == "extract.allow_symlinks" and normalized == "true":
            raise AppException(
                status_code=403,
                code="SECURITY_INVARIANT_IMMUTABLE",
                message="extract.allow_symlinks is an immutable security invariant and cannot be set to true.",
                title="Security Invariant Immutable",
            )
        return normalized

    elif data_type == "int":
        try:
            val_int = int(raw)
        except ValueError:
            raise AppException(
                status_code=422,
                code="INVALID_INTEGER_VALUE",
                message=f"Setting '{key}' expects an integer value. Got '{value_str}'.",
                title="Invalid Setting Value",
            )

        # Architectural bounds check (Two-Phase Phase 1)
        if key in ABSOLUTE_LIMITS:
            abs_min, abs_max = ABSOLUTE_LIMITS[key]
            if val_int < abs_min or val_int > abs_max:
                raise AppException(
                    status_code=422,
                    code="VALUE_EXCEEDS_ARCHITECTURAL_BOUNDS",
                    message=f"Setting '{key}' must be between {abs_min} and {abs_max}. Got {val_int}.",
                    title="Value Out of Bounds",
                )

        # Setting-specific min/max check
        if min_val is not None:
            if val_int < int(min_val):
                raise AppException(
                    status_code=422,
                    code="VALUE_BELOW_MINIMUM",
                    message=f"Setting '{key}' value {val_int} is below permissible minimum of {min_val}.",
                    title="Value Out of Bounds",
                )
        if max_val is not None:
            if val_int > int(max_val):
                raise AppException(
                    status_code=422,
                    code="VALUE_ABOVE_MAXIMUM",
                    message=f"Setting '{key}' value {val_int} exceeds permissible maximum of {max_val}.",
                    title="Value Out of Bounds",
                )
        return str(val_int)

    elif data_type == "float":
        try:
            val_float = float(raw)
        except ValueError:
            raise AppException(
                status_code=422,
                code="INVALID_FLOAT_VALUE",
                message=f"Setting '{key}' expects a floating point number. Got '{value_str}'.",
                title="Invalid Setting Value",
            )

        if min_val is not None and val_float < float(min_val):
            raise AppException(
                status_code=422,
                code="VALUE_BELOW_MINIMUM",
                message=f"Setting '{key}' value {val_float} is below minimum of {min_val}.",
                title="Value Out of Bounds",
            )
        if max_val is not None and val_float > float(max_val):
            raise AppException(
                status_code=422,
                code="VALUE_ABOVE_MAXIMUM",
                message=f"Setting '{key}' value {val_float} exceeds maximum of {max_val}.",
                title="Value Out of Bounds",
            )
        return str(val_float)

    elif data_type == "string":
        if not raw:
            raise AppException(
                status_code=422,
                code="EMPTY_STRING_VALUE",
                message=f"Setting '{key}' string value cannot be empty.",
                title="Invalid Setting Value",
            )
        return raw

    elif data_type == "json":
        try:
            json.loads(raw)
        except Exception as e:
            raise AppException(
                status_code=422,
                code="INVALID_JSON_VALUE",
                message=f"Setting '{key}' expects valid JSON: {str(e)}",
                title="Invalid Setting Value",
            )
        return raw

    return raw


async def get_all_platform_settings(db: AsyncSession) -> List[ConfigurationSettingResponse]:
    """Returns all platform configuration settings annotated with metadata."""
    stmt = select(ConfigurationSetting).order_by(ConfigurationSetting.key)
    result = await db.execute(stmt)
    records = result.scalars().all()

    responses = []
    for r in records:
        meta = CATALOG_BY_KEY.get(r.key)
        responses.append(
            ConfigurationSettingResponse(
                key=r.key,
                tier=r.tier,
                data_type=r.data_type,
                default_value=r.default_value,
                current_value=r.current_value,
                allow_org_override=r.allow_org_override,
                allow_hackathon_override=r.allow_hackathon_override,
                min_value=r.min_value,
                max_value=r.max_value,
                is_configurable=r.is_configurable,
                version=r.version,
                effect_timing=meta.effect_timing if meta else "immediate",
                description=meta.description if meta else None,
                updated_at=r.updated_at,
            )
        )
    return responses


async def get_setting_by_key(db: AsyncSession, key: str) -> ConfigurationSetting:
    """Retrieves a configuration setting by key or raises 404."""
    setting = await db.get(ConfigurationSetting, key)
    if not setting:
        raise AppException(
            status_code=404,
            code="SETTING_NOT_FOUND",
            message=f"Configuration setting '{key}' was not found in catalog.",
            title="Setting Not Found",
        )
    return setting


async def update_platform_setting(
    db: AsyncSession,
    key: str,
    payload: ConfigurationSettingUpdate,
    actor: User,
    client_ip: str = "127.0.0.1",
) -> ConfigurationSetting:
    """
    Updates a platform configuration setting with optimistic concurrency,
    bounds enforcement, history logging, and audit tracking.
    """
    setting = await get_setting_by_key(db, key)

    if not setting.is_configurable:
        raise AppException(
            status_code=403,
            code="SECURITY_INVARIANT_IMMUTABLE",
            message=f"Setting '{key}' is an immutable security invariant and cannot be modified.",
            title="Setting Immutable",
        )

    # Optimistic Concurrency Control
    if setting.version != payload.expected_version:
        raise AppException(
            status_code=409,
            code="OPTIMISTIC_CONCURRENCY_CONFLICT",
            message=(
                f"Setting '{key}' has been updated concurrently. "
                f"Expected version {payload.expected_version}, current version is {setting.version}."
            ),
            title="Concurrent Update Conflict",
        )

    normalized_value = validate_and_parse_setting_value(
        key=key,
        value_str=payload.value,
        data_type=setting.data_type,
        min_val=setting.min_value,
        max_val=setting.max_value,
    )

    old_val = setting.current_value
    setting.current_value = normalized_value
    setting.version += 1
    setting.updated_by_user_id = actor.id

    # Append History
    history = ConfigurationHistory(
        id=uuid.uuid4(),
        setting_key=key,
        scope_type="platform",
        scope_id=PLATFORM_SCOPE_ID,
        old_value=old_val,
        new_value=normalized_value,
        change_type="update",
        restored_from_version=None,
        version=setting.version,
        actor_user_id=actor.id,
        client_ip=client_ip,
        change_reason=payload.change_reason,
    )
    db.add(history)

    # Append Audit Event
    await record_audit_event(
        db=db,
        action="configuration.update",
        resource_type="configuration_setting",
        resource_id=key,
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.platform_role.value if actor.platform_role else "admin",
        reason=payload.change_reason,
        diff_payload={
            "old_value": old_val,
            "new_value": normalized_value,
            "version": setting.version,
        },
        ip_address=client_ip,
    )

    await db.commit()
    await db.refresh(setting)
    return setting


async def rollback_platform_setting(
    db: AsyncSession,
    key: str,
    payload: ConfigurationRollbackRequest,
    actor: User,
    client_ip: str = "127.0.0.1",
) -> ConfigurationSetting:
    """
    Rolls back a platform setting to a target historical version.
    Generates a new version without mutating historical records.
    Re-validates target value against current bounds.
    """
    setting = await get_setting_by_key(db, key)

    if not setting.is_configurable:
        raise AppException(
            status_code=403,
            code="SECURITY_INVARIANT_IMMUTABLE",
            message=f"Setting '{key}' is an immutable security invariant and cannot be modified.",
            title="Setting Immutable",
        )

    # Optimistic Concurrency Control
    if setting.version != payload.expected_version:
        raise AppException(
            status_code=409,
            code="OPTIMISTIC_CONCURRENCY_CONFLICT",
            message=(
                f"Setting '{key}' has been updated concurrently. "
                f"Expected version {payload.expected_version}, current version is {setting.version}."
            ),
            title="Concurrent Update Conflict",
        )

    # Locate Target Version in History
    stmt = (
        select(ConfigurationHistory)
        .where(
            ConfigurationHistory.setting_key == key,
            ConfigurationHistory.version == payload.target_version,
            ConfigurationHistory.scope_type == "platform",
        )
        .order_by(ConfigurationHistory.created_at.desc())
    )
    hist_record = (await db.execute(stmt)).scalar_one_or_none()

    if not hist_record:
        # Check if target_version is 1 and setting has never been modified
        if payload.target_version == 1:
            target_value = setting.default_value
        else:
            raise AppException(
                status_code=404,
                code="HISTORICAL_VERSION_NOT_FOUND",
                message=f"Version {payload.target_version} of setting '{key}' was not found in history.",
                title="Target Version Not Found",
            )
    else:
        target_value = hist_record.new_value

    # Re-validate target historical value against CURRENT bounds
    validated_target = validate_and_parse_setting_value(
        key=key,
        value_str=target_value,
        data_type=setting.data_type,
        min_val=setting.min_value,
        max_val=setting.max_value,
    )

    old_val = setting.current_value
    setting.current_value = validated_target
    setting.version += 1
    setting.updated_by_user_id = actor.id

    # Append New History Entry for Rollback
    history = ConfigurationHistory(
        id=uuid.uuid4(),
        setting_key=key,
        scope_type="platform",
        scope_id=PLATFORM_SCOPE_ID,
        old_value=old_val,
        new_value=validated_target,
        change_type="rollback",
        restored_from_version=payload.target_version,
        version=setting.version,
        actor_user_id=actor.id,
        client_ip=client_ip,
        change_reason=payload.change_reason or f"Rolled back to version {payload.target_version}",
    )
    db.add(history)

    # Append Audit Event
    await record_audit_event(
        db=db,
        action="configuration.rollback",
        resource_type="configuration_setting",
        resource_id=key,
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.platform_role.value if actor.platform_role else "admin",
        reason=payload.change_reason or f"Restored from version {payload.target_version}",
        diff_payload={
            "old_value": old_val,
            "new_value": validated_target,
            "restored_from_version": payload.target_version,
            "version": setting.version,
        },
        ip_address=client_ip,
    )

    await db.commit()
    await db.refresh(setting)
    return setting


async def set_configuration_override(
    db: AsyncSession,
    setting_key: str,
    scope_type: str,
    scope_id: uuid.UUID,
    value: str,
    expected_version: Optional[int],
    actor: User,
    client_ip: str = "127.0.0.1",
    change_reason: Optional[str] = None,
) -> ConfigurationOverride:
    """
    Sets or updates an organization or hackathon override within platform bounds.
    """
    setting = await get_setting_by_key(db, setting_key)

    if scope_type == "organization" and not setting.allow_org_override:
        raise AppException(
            status_code=403,
            code="OVERRIDE_NOT_PERMITTED",
            message=f"Organization overrides are not permitted for setting '{setting_key}'.",
            title="Override Not Permitted",
        )

    if scope_type == "hackathon" and not setting.allow_hackathon_override:
        raise AppException(
            status_code=403,
            code="OVERRIDE_NOT_PERMITTED",
            message=f"Hackathon overrides are not permitted for setting '{setting_key}'.",
            title="Override Not Permitted",
        )

    # Validate against platform bounds
    normalized_value = validate_and_parse_setting_value(
        key=setting_key,
        value_str=value,
        data_type=setting.data_type,
        min_val=setting.min_value,
        max_val=setting.max_value,
    )

    stmt = select(ConfigurationOverride).where(
        ConfigurationOverride.setting_key == setting_key,
        ConfigurationOverride.scope_type == scope_type,
        ConfigurationOverride.scope_id == scope_id,
    )
    override = (await db.execute(stmt)).scalar_one_or_none()

    if override:
        if expected_version is not None and override.version != expected_version:
            raise AppException(
                status_code=409,
                code="OPTIMISTIC_CONCURRENCY_CONFLICT",
                message=(
                    f"Override for '{setting_key}' was updated concurrently. "
                    f"Expected version {expected_version}, current is {override.version}."
                ),
                title="Concurrent Update Conflict",
            )
        old_val = override.override_value
        override.override_value = normalized_value
        override.version += 1
        override.updated_by_user_id = actor.id
    else:
        old_val = None
        override = ConfigurationOverride(
            id=uuid.uuid4(),
            setting_key=setting_key,
            scope_type=scope_type,
            scope_id=scope_id,
            override_value=normalized_value,
            version=1,
            updated_by_user_id=actor.id,
        )
        db.add(override)

    # History
    history = ConfigurationHistory(
        id=uuid.uuid4(),
        setting_key=setting_key,
        scope_type=scope_type,
        scope_id=scope_id,
        old_value=old_val,
        new_value=normalized_value,
        change_type="override",
        restored_from_version=None,
        version=override.version,
        actor_user_id=actor.id,
        client_ip=client_ip,
        change_reason=change_reason,
    )
    db.add(history)

    await record_audit_event(
        db=db,
        action="configuration.override.set",
        resource_type="configuration_override",
        resource_id=f"{setting_key}:{scope_type}:{scope_id}",
        organization_id=scope_id if scope_type == "organization" else None,
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.platform_role.value if actor.platform_role else "member",
        reason=change_reason,
        diff_payload={"old_value": old_val, "new_value": normalized_value, "version": override.version},
        ip_address=client_ip,
    )

    await db.commit()
    await db.refresh(override)
    return override


async def resolve_effective_configuration(
    db: AsyncSession,
    organization_id: Optional[uuid.UUID] = None,
    hackathon_id: Optional[uuid.UUID] = None,
) -> EffectiveConfiguration:
    """
    Deterministic hierarchical resolution of effective configuration parameters:
    System Catalog Default -> Platform Setting -> Organization Override -> Hackathon Override.
    Fails closed with safe system defaults if resolution fails.
    """
    raw_map: Dict[str, str] = {}

    try:
        # 1. Base from catalog defaults
        for s in CONFIGURATION_CATALOG:
            raw_map[s.key] = s.default_value

        # 2. Layer Platform Settings
        stmt = select(ConfigurationSetting)
        settings_res = await db.execute(stmt)
        for ps in settings_res.scalars().all():
            raw_map[ps.key] = ps.current_value

        # 3. Layer Organization Overrides (if allowed)
        if organization_id:
            org_stmt = select(ConfigurationOverride).where(
                ConfigurationOverride.scope_type == "organization",
                ConfigurationOverride.scope_id == organization_id,
            )
            org_res = await db.execute(org_stmt)
            for ov in org_res.scalars().all():
                meta = CATALOG_BY_KEY.get(ov.setting_key)
                if meta and meta.allow_org_override:
                    raw_map[ov.setting_key] = ov.override_value

        # 4. Layer Hackathon Overrides (if allowed)
        if hackathon_id:
            hack_stmt = select(ConfigurationOverride).where(
                ConfigurationOverride.scope_type == "hackathon",
                ConfigurationOverride.scope_id == hackathon_id,
            )
            hack_res = await db.execute(hack_stmt)
            for ov in hack_res.scalars().all():
                meta = CATALOG_BY_KEY.get(ov.setting_key)
                if meta and meta.allow_hackathon_override:
                    raw_map[ov.setting_key] = ov.override_value

        # Build typed object
        return EffectiveConfiguration(
            judge_require_override_rationale=raw_map.get("judge.require_override_rationale", "true").lower() == "true",
            judge_min_override_rationale_length=int(raw_map.get("judge.min_override_rationale_length", "20")),
            judge_allow_score_adjustment_after_finalization=raw_map.get("judge.allow_score_adjustment_after_finalization", "false").lower() == "true",

            extract_max_compressed_bytes=int(raw_map.get("extract.max_compressed_bytes", "52428800")),
            extract_max_uncompressed_bytes=int(raw_map.get("extract.max_uncompressed_bytes", "262144000")),
            extract_max_file_count=int(raw_map.get("extract.max_file_count", "1000")),
            extract_max_archive_depth=int(raw_map.get("extract.max_archive_depth", "5")),
            extract_allow_symlinks=False,  # Immutable Tier 5 invariant

            ai_default_provider=raw_map.get("ai.default_provider", "ollama"),
            ai_default_model=raw_map.get("ai.default_model", "llama3.3:70b"),
            ai_max_tokens=int(raw_map.get("ai.max_tokens", "4096")),
            ai_temperature=float(raw_map.get("ai.temperature", "0.0")),
            ai_evaluation_timeout_seconds=int(raw_map.get("ai.evaluation_timeout_seconds", "300")),

            eval_max_retries=int(raw_map.get("eval.max_retries", "3")),
            eval_lock_timeout_seconds=int(raw_map.get("eval.lock_timeout_seconds", "300")),

            authz_cache_ttl_seconds=int(raw_map.get("authz.cache_ttl_seconds", "30")),
            authz_policy_version_check_seconds=int(raw_map.get("authz.policy_version_check_seconds", "5")),

            raw_values=raw_map,
        )

    except Exception as exc:
        logger.error("Failed to safely resolve configuration: %s. Falling back to system defaults.", exc)
        return EffectiveConfiguration()

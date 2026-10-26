from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.core.database import get_db_session
from apps.api.dependencies import get_current_user, require_super_admin
from apps.api.modules.configuration.models import ConfigurationSetting
from apps.api.modules.configuration.schemas import (
    ConfigurationOverrideCreate,
    ConfigurationOverrideResponse,
    ConfigurationRollbackRequest,
    ConfigurationSettingResponse,
    ConfigurationSettingUpdate,
    EffectiveConfiguration,
)
from apps.api.modules.configuration.service import (
    get_all_platform_settings,
    get_setting_by_key,
    resolve_effective_configuration,
    rollback_platform_setting,
    set_configuration_override,
    update_platform_setting,
)
from apps.api.modules.users.models import User

router = APIRouter(prefix="/admin/configuration", tags=["Configuration"])


@router.get(
    "",
    response_model=List[ConfigurationSettingResponse],
    summary="List all platform configuration settings",
)
async def list_configurations(
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_super_admin),
) -> List[ConfigurationSettingResponse]:
    return await get_all_platform_settings(db)


@router.get(
    "/effective",
    response_model=EffectiveConfiguration,
    summary="Resolve effective configuration with hierarchical inheritance",
)
async def get_effective_configuration(
    org_id: Optional[uuid.UUID] = Query(None),
    hackathon_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> EffectiveConfiguration:
    return await resolve_effective_configuration(db, organization_id=org_id, hackathon_id=hackathon_id)


@router.get(
    "/{key}",
    response_model=ConfigurationSettingResponse,
    summary="Get single platform configuration setting",
)
async def get_configuration(
    key: str,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_super_admin),
) -> ConfigurationSettingResponse:
    setting = await get_setting_by_key(db, key)
    # Re-use list helper mapping for single
    all_settings = await get_all_platform_settings(db)
    for s in all_settings:
        if s.key == key:
            return s
    return ConfigurationSettingResponse.model_validate(setting)


@router.put(
    "/{key}",
    response_model=ConfigurationSettingResponse,
    summary="Update platform configuration setting with optimistic concurrency",
)
async def update_configuration(
    key: str,
    payload: ConfigurationSettingUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_super_admin),
) -> ConfigurationSettingResponse:
    client_ip = getattr(request.state, "client_ip", "127.0.0.1")
    setting = await update_platform_setting(
        db=db,
        key=key,
        payload=payload,
        actor=current_user,
        client_ip=client_ip,
    )
    all_settings = await get_all_platform_settings(db)
    for s in all_settings:
        if s.key == key:
            return s
    return ConfigurationSettingResponse.model_validate(setting)


@router.post(
    "/{key}/rollback",
    response_model=ConfigurationSettingResponse,
    summary="Roll back configuration setting to target version without rewriting history",
)
async def rollback_configuration(
    key: str,
    payload: ConfigurationRollbackRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_super_admin),
) -> ConfigurationSettingResponse:
    client_ip = getattr(request.state, "client_ip", "127.0.0.1")
    setting = await rollback_platform_setting(
        db=db,
        key=key,
        payload=payload,
        actor=current_user,
        client_ip=client_ip,
    )
    all_settings = await get_all_platform_settings(db)
    for s in all_settings:
        if s.key == key:
            return s
    return ConfigurationSettingResponse.model_validate(setting)


@router.post(
    "/overrides",
    response_model=ConfigurationOverrideResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or update tenant- or hackathon-scoped configuration override",
)
async def create_or_update_override(
    payload: ConfigurationOverrideCreate,
    key: str = Query(..., description="Setting key to override"),
    request: Request = None,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ConfigurationOverrideResponse:
    client_ip = getattr(request.state, "client_ip", "127.0.0.1") if request else "127.0.0.1"
    override = await set_configuration_override(
        db=db,
        setting_key=key,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        value=payload.value,
        expected_version=payload.expected_version,
        actor=current_user,
        client_ip=client_ip,
        change_reason=payload.change_reason,
    )
    return ConfigurationOverrideResponse.model_validate(override)

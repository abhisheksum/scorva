import logging
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import apps.api.modules.audit.models  # noqa: F401
import apps.api.modules.auth.models  # noqa: F401
import apps.api.modules.configuration.models  # noqa: F401
import apps.api.modules.hackathons.models  # noqa: F401
import apps.api.modules.organizations.models  # noqa: F401
import apps.api.modules.rbac.models  # noqa: F401
import apps.api.modules.users.models  # noqa: F401
from apps.api.modules.configuration.catalog import CONFIGURATION_CATALOG
from apps.api.modules.configuration.models import ConfigurationSetting
from apps.api.modules.rbac.catalog import PERMISSIONS_CATALOG, SYSTEM_ROLES_CATALOG
from apps.api.modules.rbac.models import (
    PLATFORM_SCOPE_ID,
    AuthzPolicyVersion,
    Permission,
    Role,
    RolePermission,
)

logger = logging.getLogger("scorva.rbac.seed")


async def seed_rbac_and_configuration(db: AsyncSession) -> None:
    """
    Idempotently seeds permissions, system roles, default role permissions,
    default configuration settings, and initial policy versions.
    """
    # 1. Seed Permissions
    for perm_def in PERMISSIONS_CATALOG:
        existing = await db.get(Permission, perm_def.id)
        if not existing:
            perm = Permission(
                id=perm_def.id,
                domain=perm_def.domain,
                action=perm_def.action,
                min_scope=perm_def.min_scope,
                is_delegable=perm_def.is_delegable,
                description=perm_def.description,
            )
            db.add(perm)
        else:
            existing.domain = perm_def.domain
            existing.action = perm_def.action
            existing.min_scope = perm_def.min_scope
            existing.is_delegable = perm_def.is_delegable
            existing.description = perm_def.description

    await db.flush()

    # 2. Seed System Roles & Role Permissions
    for role_def in SYSTEM_ROLES_CATALOG:
        role_stmt = select(Role).where(
            Role.name == role_def["name"],
            Role.scope_type == role_def["scope_type"],
            Role.scope_id == role_def["scope_id"],
        )
        existing_role = (await db.execute(role_stmt)).scalar_one_or_none()

        if not existing_role:
            role = Role(
                id=uuid.uuid4(),
                name=role_def["name"],
                display_name=role_def["display_name"],
                scope_type=role_def["scope_type"],
                scope_id=role_def["scope_id"],
                is_system=role_def["is_system"],
                is_immutable=role_def["is_immutable"],
            )
            db.add(role)
            await db.flush()
            role_id = role.id
        else:
            role_id = existing_role.id

        # Seed Role Permissions
        for perm_id in role_def["permissions"]:
            rp = await db.get(RolePermission, (role_id, perm_id))
            if not rp:
                db.add(RolePermission(role_id=role_id, permission_id=perm_id))

    await db.flush()

    # 3. Seed Default Configuration Settings
    for setting_def in CONFIGURATION_CATALOG:
        existing_setting = await db.get(ConfigurationSetting, setting_def.key)
        if not existing_setting:
            setting = ConfigurationSetting(
                key=setting_def.key,
                tier=setting_def.tier,
                data_type=setting_def.data_type,
                default_value=setting_def.default_value,
                current_value=setting_def.default_value,
                allow_org_override=setting_def.allow_org_override,
                allow_hackathon_override=setting_def.allow_hackathon_override,
                min_value=setting_def.min_value,
                max_value=setting_def.max_value,
                is_configurable=setting_def.is_configurable,
                version=1,
            )
            db.add(setting)

    # 4. Seed Platform Policy Version
    policy_ver = await db.get(AuthzPolicyVersion, ("platform", PLATFORM_SCOPE_ID))
    if not policy_ver:
        db.add(
            AuthzPolicyVersion(
                scope_type="platform",
                scope_id=PLATFORM_SCOPE_ID,
                current_version=1,
            )
        )

    await db.commit()
    logger.info("Successfully seeded dynamic RBAC and Configuration catalogs.")

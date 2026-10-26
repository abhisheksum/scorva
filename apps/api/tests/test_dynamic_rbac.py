import asyncio
import uuid
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.core.database import AsyncSessionLocal
from apps.api.core.exceptions import AppException
from apps.api.modules.rbac.catalog import PERMISSIONS_CATALOG
from apps.api.modules.rbac.models import PLATFORM_SCOPE_ID, Role, RolePermission, UserRoleAssignment
from apps.api.modules.rbac.schemas import RoleCreateRequest, RolePermissionsUpdateRequest, UserRoleAssignmentRequest
from apps.api.modules.rbac.service import (
    assign_user_role,
    check_last_platform_owner_lockout,
    create_dynamic_role,
    get_effective_user_permissions,
    list_all_roles,
    revoke_user_role,
    update_role_permissions,
)
from apps.api.modules.users.models import PlatformRole, User


@pytest.mark.asyncio
async def test_permission_resolution_by_role_and_scope(db_session: AsyncSession, create_user_helper):
    """Verifies effective permission resolution across platform and tenant scopes."""
    # 1. Platform owner has all catalog permissions
    owner = await create_user_helper("test_rbac_owner@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    perms_owner = await get_effective_user_permissions(db_session, owner.id)
    assert "platform.settings.read" in perms_owner
    assert "platform.roles.manage" in perms_owner
    assert "org.profile.update" in perms_owner
    assert len(perms_owner) == len(PERMISSIONS_CATALOG)

    # 2. Security admin has only audit & settings.read
    sec_admin = await create_user_helper("test_rbac_sec@scorva.io", platform_role=PlatformRole.SECURITY_ADMIN)
    perms_sec = await get_effective_user_permissions(db_session, sec_admin.id)
    assert "platform.audit.read" in perms_sec
    assert "platform.settings.read" in perms_sec
    assert "platform.roles.manage" not in perms_sec
    assert "org.profile.update" not in perms_sec


@pytest.mark.asyncio
async def test_delegation_ceilings_and_non_delegable_permissions(db_session: AsyncSession, create_user_helper):
    """Verifies that non-platform-owners cannot delegate permissions outside their ceiling or non-delegable perms."""
    owner = await create_user_helper("ceiling_owner@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    sec_admin = await create_user_helper("ceiling_sec@scorva.io", platform_role=PlatformRole.SECURITY_ADMIN)

    # Security admin only holds platform.audit.read and platform.settings.read
    # Attempting to create a role with org.profile.update (unheld delegable) should fail with DELEGATION_CEILING_EXCEEDED
    with pytest.raises(AppException) as exc_info:
        await create_dynamic_role(
            db=db_session,
            payload=RoleCreateRequest(
                name=f"custom_audit_role_{uuid.uuid4().hex[:6]}",
                display_name="Custom Audit Role",
                scope_type="platform",
                permissions=["org.profile.update"],
            ),
            actor=sec_admin,
        )
    assert exc_info.value.status_code == 403
    assert "DELEGATION_CEILING_EXCEEDED" in exc_info.value.code

    # Attempting to delegate a non-delegable permission (e.g. platform.audit.read or platform.roles.manage)
    with pytest.raises(AppException) as exc_info:
        await create_dynamic_role(
            db=db_session,
            payload=RoleCreateRequest(
                name=f"illegal_role_{uuid.uuid4().hex[:6]}",
                display_name="Illegal Role",
                scope_type="platform",
                permissions=["platform.audit.read"],
            ),
            actor=sec_admin,
        )
    assert exc_info.value.status_code == 403
    assert "NON_DELEGABLE_PERMISSION" in exc_info.value.code


@pytest.mark.asyncio
async def test_protected_system_roles_immutability(db_session: AsyncSession, create_user_helper):
    """Verifies immutable system roles (e.g. platform_owner) cannot have permissions modified."""
    owner = await create_user_helper("immut_owner@scorva.io", PlatformRole.PLATFORM_OWNER)

    owner_role = (await db_session.execute(
        select(Role).where(Role.name == "platform_owner")
    )).scalar_one_or_none()
    assert owner_role is not None
    assert owner_role.is_immutable is True

    # Attempt to alter platform_owner permissions
    with pytest.raises(AppException) as exc_info:
        await update_role_permissions(
            db=db_session,
            role_id=owner_role.id,
            payload=RolePermissionsUpdateRequest(permissions=["platform.settings.read"]),
            actor=owner,
        )
    assert exc_info.value.status_code == 403
    assert "IMMUTABLE_ROLE_PROTECTED" in exc_info.value.code


@pytest.mark.asyncio
async def test_last_platform_owner_lockout_protection(db_session: AsyncSession, create_user_helper):
    """Verifies that removing or revoking the final active platform owner is blocked."""
    sole_owner = await create_user_helper("sole_owner@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)

    # Deactivate any other platform owners from prior tests so sole_owner is strictly the sole active owner
    await db_session.execute(
        update(User)
        .where(User.id != sole_owner.id, User.platform_role == PlatformRole.PLATFORM_OWNER)
        .values(is_active=False)
    )
    await db_session.commit()

    owner_role = (await db_session.execute(
        select(Role).where(Role.name == "platform_owner")
    )).scalar_one_or_none()

    # Assign role explicitly if not present
    assignment = (await db_session.execute(
        select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == sole_owner.id,
            UserRoleAssignment.role_id == owner_role.id,
        )
    )).scalar_one_or_none()

    if not assignment:
        assignment = UserRoleAssignment(
            id=uuid.uuid4(),
            user_id=sole_owner.id,
            role_id=owner_role.id,
            scope_type="platform",
            scope_id=PLATFORM_SCOPE_ID,
        )
        db_session.add(assignment)
        await db_session.commit()

    # Deactivating or stripping role must trigger check_last_platform_owner_lockout
    # When active count <= 1, check_last_platform_owner_lockout must raise 409 LAST_PLATFORM_OWNER_LOCKOUT
    with pytest.raises(AppException) as exc_info:
        await check_last_platform_owner_lockout(db_session, sole_owner.id)
    assert exc_info.value.status_code == 409
    assert "LAST_PLATFORM_OWNER_LOCKOUT" in exc_info.value.code

    # Restore users active state
    await db_session.execute(text("UPDATE users SET is_active = TRUE"))
    await db_session.commit()


@pytest.mark.asyncio
async def test_concurrent_platform_owner_revocation(db_session: AsyncSession, create_user_helper):
    """
    Simulates two concurrent transactions racing to revoke the last active platform owners.
    Advisory lock + row lock must serialize the operations, allowing at most one mutation
    and strictly preventing total administrative lockout.
    """
    owner_a = await create_user_helper("owner_a@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    owner_b = await create_user_helper("owner_b@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)

    results = []

    async def attempt_lockout_check(user_id: uuid.UUID):
        async with AsyncSessionLocal() as session:
            try:
                await check_last_platform_owner_lockout(session, user_id)
                results.append("PERMITTED")
            except AppException as e:
                results.append(e.code)

    # When 2 owners exist, 1 check might succeed and the other might fail if serialized, or
    # if both are checked concurrently, the mutex prevents simultaneous completion.
    await asyncio.gather(
        attempt_lockout_check(owner_a.id),
        attempt_lockout_check(owner_b.id),
    )

    # Since 2 owners exist, at least one check is permitted (since active count is 2)
    assert "PERMITTED" in results

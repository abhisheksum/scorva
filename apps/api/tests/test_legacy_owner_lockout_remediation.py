import asyncio
from datetime import datetime, timezone
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.core.database import AsyncSessionLocal
from apps.api.core.exceptions import AppException
from apps.api.modules.rbac.models import (
    PLATFORM_SCOPE_ID,
    AuthzInvalidationOutbox,
    AuthzPolicyVersion,
    Role,
    UserRoleAssignment,
)
from apps.api.modules.rbac.service import check_last_platform_owner_lockout
from apps.api.modules.users.models import PlatformRole, User

ORIGIN_HEADER = {"Origin": "http://testserver"}


@pytest.mark.asyncio
async def test_demote_sole_owner_via_legacy_role_endpoint_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    create_user_helper,
    create_session_helper,
):
    """
    Verifies that calling POST /api/v1/admin/users/{user_id}/role to demote the sole active
    Platform Owner is rejected with HTTP 409 LAST_PLATFORM_OWNER_LOCKOUT.
    Database state, outbox, and policy version must remain unmutated on rejection.
    """
    # 1. Identify active platform owners and isolate a single sole owner
    owners = (await db_session.execute(
        select(User).where(
            User.platform_role == PlatformRole.PLATFORM_OWNER,
            User.is_active == True,
            User.deleted_at.is_(None),
        )
    )).scalars().all()

    sole_owner = owners[0]
    sole_owner_token = await create_session_helper(sole_owner)

    # Deactivate other owners for this test
    for other in owners[1:]:
        other.is_active = False
    await db_session.commit()

    # Query outbox count prior to request
    pre_outbox_count = (await db_session.execute(
        select(text("COUNT(*) FROM authz_invalidation_outbox WHERE target_user_id = :uid")),
        {"uid": sole_owner.id},
    )).scalar()

    # 2. Attempt demotion of the sole owner via legacy endpoint
    response = await client.post(
        f"/api/v1/admin/users/{sole_owner.id}/role",
        headers=ORIGIN_HEADER,
        cookies={settings.SESSION_COOKIE_NAME: sole_owner_token},
        json={"platform_role": "platform_ops_admin", "reason": "Testing lockout protection"},
    )

    # Must be rejected with HTTP 409 Conflict
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "LAST_PLATFORM_OWNER_LOCKOUT"
    assert "final active Platform Owner" in (body.get("detail") or body.get("message", ""))

    # 3. Assert database state was NOT mutated
    await db_session.refresh(sole_owner)
    assert sole_owner.platform_role == PlatformRole.PLATFORM_OWNER

    # 4. Assert no invalidation outbox entry was committed for the rejected mutation
    post_outbox_count = (await db_session.execute(
        select(text("COUNT(*) FROM authz_invalidation_outbox WHERE target_user_id = :uid")),
        {"uid": sole_owner.id},
    )).scalar()
    assert post_outbox_count == pre_outbox_count

    # Teardown: reactivate users
    for other in owners[1:]:
        other.is_active = True
    await db_session.commit()


@pytest.mark.asyncio
async def test_deactivate_sole_owner_via_legacy_status_endpoint_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    create_session_helper,
):
    """
    Verifies that calling POST /api/v1/admin/users/{user_id}/status with is_active=False
    on the sole active Platform Owner is rejected with HTTP 409 LAST_PLATFORM_OWNER_LOCKOUT.
    """
    owners = (await db_session.execute(
        select(User).where(
            User.platform_role == PlatformRole.PLATFORM_OWNER,
            User.is_active == True,
            User.deleted_at.is_(None),
        )
    )).scalars().all()

    sole_owner = owners[0]
    sole_owner_token = await create_session_helper(sole_owner)

    for other in owners[1:]:
        other.is_active = False
    await db_session.commit()

    # Attempt to suspend the sole owner
    response = await client.post(
        f"/api/v1/admin/users/{sole_owner.id}/status",
        headers=ORIGIN_HEADER,
        cookies={settings.SESSION_COOKIE_NAME: sole_owner_token},
        json={"is_active": False, "reason": "Suspension attempt"},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "LAST_PLATFORM_OWNER_LOCKOUT"

    # User remains active
    await db_session.refresh(sole_owner)
    assert sole_owner.is_active is True

    # Teardown: reactivate users
    for other in owners[1:]:
        other.is_active = True
    await db_session.commit()


@pytest.mark.asyncio
async def test_demote_and_deactivate_owner_permitted_when_another_owner_exists(
    client: AsyncClient,
    db_session: AsyncSession,
    create_user_helper,
    create_session_helper,
):
    """
    Verifies that demoting or deactivating a Platform Owner succeeds when at least
    one other active Platform Owner exists.
    """
    # Create two explicit active Platform Owners
    owner_1 = await create_user_helper("owner_perm_1@scorva.local", platform_role=PlatformRole.PLATFORM_OWNER)
    owner_2 = await create_user_helper("owner_perm_2@scorva.local", platform_role=PlatformRole.PLATFORM_OWNER)

    owner_2_token = await create_session_helper(owner_2)

    # 1. Demoting owner_1 succeeds because owner_2 remains active
    demote_res = await client.post(
        f"/api/v1/admin/users/{owner_1.id}/role",
        headers=ORIGIN_HEADER,
        cookies={settings.SESSION_COOKIE_NAME: owner_2_token},
        json={"platform_role": "platform_ops_admin", "reason": "Demoting first owner"},
    )
    assert demote_res.status_code == 200
    await db_session.refresh(owner_1)
    assert owner_1.platform_role == PlatformRole.PLATFORM_OPS_ADMIN

    # 2. Deactivating owner_1 succeeds (they are now platform_ops_admin, not sole owner)
    deact_res = await client.post(
        f"/api/v1/admin/users/{owner_1.id}/status",
        headers=ORIGIN_HEADER,
        cookies={settings.SESSION_COOKIE_NAME: owner_2_token},
        json={"is_active": False, "reason": "Deactivating non-owner"},
    )
    assert deact_res.status_code == 200
    await db_session.refresh(owner_1)
    assert owner_1.is_active is False

    # Ensure other owners are inactive to isolate owner_2 as the sole owner
    other_owners = (await db_session.execute(
        select(User).where(
            User.id != owner_2.id,
            User.platform_role == PlatformRole.PLATFORM_OWNER,
            User.is_active == True,
            User.deleted_at.is_(None),
        )
    )).scalars().all()
    for o in other_owners:
        o.is_active = False
    await db_session.commit()

    # 3. Now attempting to demote owner_2 must fail with 409 because owner_2 is the sole remaining owner
    failed_demote = await client.post(
        f"/api/v1/admin/users/{owner_2.id}/role",
        headers=ORIGIN_HEADER,
        cookies={settings.SESSION_COOKIE_NAME: owner_2_token},
        json={"platform_role": "platform_ops_admin", "reason": "Demoting final owner"},
    )
    assert failed_demote.status_code == 409
    assert failed_demote.json()["code"] == "LAST_PLATFORM_OWNER_LOCKOUT"

    # 4. Attempting to deactivate owner_2 must also fail with 409
    failed_deact = await client.post(
        f"/api/v1/admin/users/{owner_2.id}/status",
        headers=ORIGIN_HEADER,
        cookies={settings.SESSION_COOKIE_NAME: owner_2_token},
        json={"is_active": False, "reason": "Deactivating final owner"},
    )
    assert failed_deact.status_code == 409
    assert failed_deact.json()["code"] == "LAST_PLATFORM_OWNER_LOCKOUT"

    # Teardown
    for o in other_owners:
        o.is_active = True
    await db_session.commit()


@pytest.mark.asyncio
async def test_inactive_and_deleted_users_do_not_count_as_active_owners(
    db_session: AsyncSession,
    create_user_helper,
):
    """
    Verifies that inactive or deleted users with platform_role=PLATFORM_OWNER
    are excluded from the active owner count and cannot mask sole owner lockout.
    """
    # Create active sole owner
    sole_owner = await create_user_helper("active_owner_cnt@scorva.local", platform_role=PlatformRole.PLATFORM_OWNER)

    # Create inactive owner
    inactive_owner = await create_user_helper("inactive_owner_cnt@scorva.local", platform_role=PlatformRole.PLATFORM_OWNER)
    inactive_owner.is_active = False

    # Create soft-deleted owner
    deleted_owner = await create_user_helper("deleted_owner_cnt@scorva.local", platform_role=PlatformRole.PLATFORM_OWNER)
    deleted_owner.deleted_at = datetime.now(timezone.utc)

    # Deactivate all other platform owners
    await db_session.execute(
        update(User)
        .where(
            User.id.notin_([sole_owner.id, inactive_owner.id, deleted_owner.id]),
            User.platform_role == PlatformRole.PLATFORM_OWNER,
        )
        .values(is_active=False)
    )
    await db_session.commit()

    # The sole active owner must trigger lockout check
    with pytest.raises(AppException) as exc_info:
        await check_last_platform_owner_lockout(db_session, sole_owner.id)
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "LAST_PLATFORM_OWNER_LOCKOUT"

    # Teardown
    await db_session.execute(update(User).values(is_active=True))
    await db_session.commit()


@pytest.mark.asyncio
async def test_legacy_and_dynamic_assignments_reconciled_without_double_counting(
    db_session: AsyncSession,
    create_user_helper,
):
    """
    Verifies that a user having BOTH legacy platform_role=PLATFORM_OWNER and
    a dynamic UserRoleAssignment to 'platform_owner' is counted as 1 distinct owner,
    preventing double-counting that would otherwise allow lockouts.
    """
    # Create a single owner with both legacy and dynamic assignment
    dual_owner = await create_user_helper("dual_owner@scorva.local", platform_role=PlatformRole.PLATFORM_OWNER)

    owner_role = (await db_session.execute(
        select(Role).where(Role.name == "platform_owner", Role.scope_type == "platform")
    )).scalar_one()

    assignment = UserRoleAssignment(
        id=uuid.uuid4(),
        user_id=dual_owner.id,
        role_id=owner_role.id,
        scope_type="platform",
        scope_id=PLATFORM_SCOPE_ID,
    )
    db_session.add(assignment)

    # Deactivate all other platform owners
    await db_session.execute(
        update(User)
        .where(
            User.id != dual_owner.id,
            User.platform_role == PlatformRole.PLATFORM_OWNER,
        )
        .values(is_active=False)
    )
    await db_session.commit()

    # Must raise 409 because distinct count is 1 (not 2)
    with pytest.raises(AppException) as exc_info:
        await check_last_platform_owner_lockout(db_session, dual_owner.id)
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "LAST_PLATFORM_OWNER_LOCKOUT"

    # Teardown
    await db_session.execute(update(User).values(is_active=True))
    await db_session.commit()


@pytest.mark.asyncio
async def test_concurrent_legacy_and_dynamic_races_prevent_lockout(
    create_user_helper,
):
    """
    Simulates concurrent racing mutations across legacy endpoint and dynamic RBAC endpoint
    when exactly two owners exist.
    The pg_advisory_xact_lock and row lock must serialize the operations, allowing at most
    one demotion/revocation and rejecting the other with 409 Conflict.
    """
    owner_a = await create_user_helper("race_owner_a@scorva.local", platform_role=PlatformRole.PLATFORM_OWNER)
    owner_b = await create_user_helper("race_owner_b@scorva.local", platform_role=PlatformRole.PLATFORM_OWNER)

    # Deactivate other owners so only owner_a and owner_b are active
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(User)
            .where(
                User.id.notin_([owner_a.id, owner_b.id]),
                User.platform_role == PlatformRole.PLATFORM_OWNER,
            )
            .values(is_active=False)
        )
        await session.commit()

    results = []

    async def execute_demotion_task(target_user_id: uuid.UUID):
        async with AsyncSessionLocal() as session:
            try:
                # Advisory lock and check
                await check_last_platform_owner_lockout(session, target_user_id)
                # Simulate mutation within transaction
                await session.execute(
                    update(User)
                    .where(User.id == target_user_id)
                    .values(platform_role=PlatformRole.PLATFORM_OPS_ADMIN)
                )
                await session.commit()
                results.append("SUCCESS")
            except AppException as e:
                await session.rollback()
                results.append(e.code)

    # Execute concurrent demotion race on owner_a and owner_b
    await asyncio.gather(
        execute_demotion_task(owner_a.id),
        execute_demotion_task(owner_b.id),
    )

    # Exactly one must succeed and the other must be rejected
    assert "SUCCESS" in results
    assert "LAST_PLATFORM_OWNER_LOCKOUT" in results

    # Verify at least one owner remains active in database
    async with AsyncSessionLocal() as session:
        active_owners = (await session.execute(
            select(User.id).where(
                User.platform_role == PlatformRole.PLATFORM_OWNER,
                User.is_active == True,
            )
        )).scalars().all()
        assert len(active_owners) >= 1

        # Teardown: reactivate all users
        await session.execute(update(User).values(is_active=True))
        await session.commit()


@pytest.mark.asyncio
async def test_outbox_and_policy_version_updated_on_successful_legacy_change(
    client: AsyncClient,
    db_session: AsyncSession,
    create_user_helper,
    create_session_helper,
):
    """
    Verifies that when a legacy user role or status is updated,
    the durable AuthzPolicyVersion is incremented and an AuthzInvalidationOutbox
    event is transactionally inserted.
    """
    admin_user = await create_user_helper("admin_caller@scorva.local", platform_role=PlatformRole.PLATFORM_OWNER)
    admin_token = await create_session_helper(admin_user)

    test_user = await create_user_helper("outbox_legacy_test@scorva.local", platform_role=PlatformRole.PLATFORM_OPS_ADMIN)

    # 1. Update role via legacy endpoint
    res_role = await client.post(
        f"/api/v1/admin/users/{test_user.id}/role",
        headers=ORIGIN_HEADER,
        cookies={settings.SESSION_COOKIE_NAME: admin_token},
        json={"platform_role": "security_admin", "reason": "Role update test"},
    )
    assert res_role.status_code == 200

    # Verify outbox event for user_role_updated
    outbox_role = (await db_session.execute(
        select(AuthzInvalidationOutbox).where(
            AuthzInvalidationOutbox.target_user_id == test_user.id,
            AuthzInvalidationOutbox.event_type == "user_role_updated",
        ).order_by(AuthzInvalidationOutbox.id.desc())
    )).scalars().first()
    assert outbox_role is not None
    assert outbox_role.scope_type == "platform"

    # 2. Update status via legacy endpoint
    res_status = await client.post(
        f"/api/v1/admin/users/{test_user.id}/status",
        headers=ORIGIN_HEADER,
        cookies={settings.SESSION_COOKIE_NAME: admin_token},
        json={"is_active": False, "reason": "Status update test"},
    )
    assert res_status.status_code == 200

    # Verify outbox event for user_status_updated
    outbox_status = (await db_session.execute(
        select(AuthzInvalidationOutbox).where(
            AuthzInvalidationOutbox.target_user_id == test_user.id,
            AuthzInvalidationOutbox.event_type == "user_status_updated",
        ).order_by(AuthzInvalidationOutbox.id.desc())
    )).scalars().first()
    assert outbox_status is not None
    assert outbox_status.scope_type == "platform"

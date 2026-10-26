from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import uuid
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.core.database import AsyncSessionLocal
from apps.api.core.exceptions import AppException
from apps.api.modules.audit.models import AuditEvent
from apps.api.modules.rbac.models import (
    PLATFORM_SCOPE_ID,
    AuthzInvalidationOutbox,
    AuthzPolicyVersion,
    Role,
    RolePermission,
    UserRoleAssignment,
)
from apps.api.modules.rbac.outbox import purge_local_authz_cache, relay_authz_invalidation_outbox
from apps.api.modules.rbac.schemas import RoleCreateRequest
from apps.api.modules.rbac.service import (
    create_dynamic_role,
    get_effective_user_permissions,
    increment_policy_version_and_outbox,
)
from apps.api.modules.users.models import PlatformRole, User


@pytest.mark.asyncio
async def test_atomic_persistence_of_audit_version_and_outbox(db_session: AsyncSession, create_user_helper):
    """Verifies that role mutations atomically persist the role, policy version, outbox event, and audit record."""
    admin = await create_user_helper("atomic_admin@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)

    # Initial outbox and audit count
    outbox_count_before = (await db_session.execute(
        select(AuthzInvalidationOutbox)
    )).scalars().all()

    audit_count_before = (await db_session.execute(
        select(AuditEvent)
    )).scalars().all()

    role_name = f"atomic_role_{uuid.uuid4().hex[:6]}"
    # Create dynamic role
    role_resp = await create_dynamic_role(
        db=db_session,
        payload=RoleCreateRequest(
            name=role_name,
            display_name="Test Atomic Role",
            scope_type="platform",
            permissions=["platform.audit.read"],
        ),
        actor=admin,
    )

    # Verify role was created
    role = await db_session.get(Role, role_resp.id)
    assert role is not None

    # Verify policy version was incremented
    ver_record = await db_session.get(AuthzPolicyVersion, ("platform", PLATFORM_SCOPE_ID))
    assert ver_record is not None
    assert ver_record.current_version >= 2

    # Verify outbox event was recorded
    outbox_events = (await db_session.execute(
        select(AuthzInvalidationOutbox)
        .where(AuthzInvalidationOutbox.scope_type == "platform")
        .order_by(AuthzInvalidationOutbox.id.desc())
    )).scalars().all()
    assert len(outbox_events) > len(outbox_count_before)
    latest_outbox = outbox_events[0]
    assert latest_outbox.event_type == "role_created"
    assert latest_outbox.processed_at is None

    # Verify audit event was appended
    audit_events = (await db_session.execute(
        select(AuditEvent)
        .where(AuditEvent.action == "role.create")
        .order_by(AuditEvent.timestamp.desc())
    )).scalars().all()
    assert len(audit_events) > 0
    assert audit_events[0].resource_id == str(role.id)


@pytest.mark.asyncio
async def test_failed_transaction_leaves_no_partial_policy_changes(db_session: AsyncSession, create_user_helper):
    """Verifies that an aborted transaction rolls back role, outbox, and version changes completely."""
    admin = await create_user_helper("abort_admin@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)

    role_name = f"aborted_role_{uuid.uuid4().hex[:6]}"

    async with AsyncSessionLocal() as session:
        try:
            # Create a role but raise an exception before commit
            role = Role(
                id=uuid.uuid4(),
                name=role_name,
                display_name="Aborted Role",
                scope_type="platform",
                scope_id=PLATFORM_SCOPE_ID,
            )
            session.add(role)
            await session.flush()

            # Record outbox
            await increment_policy_version_and_outbox(session, "platform", PLATFORM_SCOPE_ID, "test_abort")
            raise RuntimeError("Simulated transaction failure")
        except RuntimeError:
            await session.rollback()

    # Verify role does not exist
    check_role = (await db_session.execute(
        select(Role).where(Role.name == role_name)
    )).scalar_one_or_none()
    assert check_role is None


@pytest.mark.asyncio
async def test_outbox_relay_propagation_and_retry(db_session: AsyncSession):
    """Verifies that relay_authz_invalidation_outbox publishes to Redis and handles retries."""
    # 1. Insert an unprocessed outbox event
    event = AuthzInvalidationOutbox(
        event_type="test_event",
        scope_type="platform",
        scope_id=PLATFORM_SCOPE_ID,
        target_user_id=uuid.uuid4(),
        version=10,
        retry_count=0,
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)

    # Mock Redis client
    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock(return_value=1)
    mock_redis.keys = AsyncMock(return_value=[])

    processed = await relay_authz_invalidation_outbox(db_session, redis_client=mock_redis)
    assert processed >= 1

    # Verify event was marked processed
    await db_session.refresh(event)
    assert event.processed_at is not None
    assert mock_redis.publish.called

    # 2. Test transient Redis error increments retry_count
    event_fail = AuthzInvalidationOutbox(
        event_type="test_fail_event",
        scope_type="platform",
        scope_id=PLATFORM_SCOPE_ID,
        target_user_id=None,
        version=11,
        retry_count=0,
    )
    db_session.add(event_fail)
    await db_session.commit()
    await db_session.refresh(event_fail)

    mock_failing_redis = AsyncMock()
    mock_failing_redis.publish = AsyncMock(side_effect=ConnectionError("Redis connection lost"))

    await relay_authz_invalidation_outbox(db_session, redis_client=mock_failing_redis)
    await db_session.refresh(event_fail)
    assert event_fail.processed_at is None
    assert event_fail.retry_count == 1


@pytest.mark.asyncio
async def test_audit_events_immutability_enforced_by_trigger(db_session: AsyncSession):
    """Verifies that the PostgreSQL database trigger trg_audit_events_immutable prevents UPDATE and DELETE on audit_events."""
    # Insert an audit event directly
    event_id = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO audit_events (
                id, timestamp, actor_email, actor_role, action,
                resource_type, resource_id, outcome, ip_address, user_agent, correlation_id
            ) VALUES (
                :id, now(), 'audit_test@scorva.local', 'platform_owner', 'test.immutable',
                'test', '123', 'SUCCESS', '127.0.0.1', 'pytest', :corr_id
            )
            """
        ),
        {"id": event_id, "corr_id": uuid.uuid4()},
    )
    await db_session.commit()

    # Attempt UPDATE - must fail with database exception from trigger
    with pytest.raises(Exception) as exc_info:
        await db_session.execute(
            text("UPDATE audit_events SET action = 'tampered' WHERE id = :id"),
            {"id": event_id},
        )
        await db_session.commit()
    assert "immutable" in str(exc_info.value).lower() or "forbidden" in str(exc_info.value).lower()
    await db_session.rollback()

    # Attempt DELETE - must fail with database exception from trigger
    with pytest.raises(Exception) as exc_info:
        await db_session.execute(
            text("DELETE FROM audit_events WHERE id = :id"),
            {"id": event_id},
        )
        await db_session.commit()
    assert "immutable" in str(exc_info.value).lower() or "forbidden" in str(exc_info.value).lower()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_fail_closed_on_authz_service_outage(create_user_helper):
    """Verifies that require_permission dependency strictly fails closed (HTTP 503) if authorization query fails."""
    user = await create_user_helper("failclosed_user@scorva.io", platform_role=PlatformRole.PLATFORM_OPS_ADMIN)

    from apps.api.modules.rbac.dependencies import require_permission
    from starlette.requests import Request

    guard = require_permission("platform.settings.write", scope_type="platform", authoritative=True)

    mock_request = AsyncMock(spec=Request)
    mock_request.path_params = {}

    # Mock DB session that raises database failure
    failing_db = AsyncMock()
    failing_db.get = AsyncMock(side_effect=Exception("Database connection timeout"))

    with pytest.raises(AppException) as exc_info:
        await guard(request=mock_request, user=user, db=failing_db)

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "AUTHZ_SERVICE_UNAVAILABLE"

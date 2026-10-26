import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from apps.api.config import settings
from apps.api.core.security import generate_secure_token, hash_session_token
from apps.api.modules.audit.models import AuditEvent, AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.users.models import PlatformRole, UserSession


@pytest.mark.asyncio
async def test_audit_append_only_trigger_blocks_update(db_session):
    """
    Verifies that the PostgreSQL append-only trigger strictly forbids UPDATE on audit_events.
    """
    event = await record_audit_event(
        db=db_session,
        action="security_check",
        resource_type="system",
        resource_id="sys_1",
        outcome=AuditOutcome.SUCCESS,
        reason="Baseline system event",
    )
    await db_session.commit()

    # Attempting to UPDATE the audit row MUST raise a PostgreSQL exception
    with pytest.raises(Exception) as exc_info:
        await db_session.execute(
            text("UPDATE audit_events SET reason = 'Tampered Reason' WHERE id = :event_id"),
            {"event_id": event.id},
        )
        await db_session.commit()

    err_msg = str(exc_info.value).lower()
    assert "immutable, append-only table" in err_msg or "update and delete operations are forbidden" in err_msg


@pytest.mark.asyncio
async def test_audit_append_only_trigger_blocks_delete(db_session):
    """
    Verifies that the PostgreSQL append-only trigger strictly forbids DELETE on audit_events.
    """
    event = await record_audit_event(
        db=db_session,
        action="security_check_delete",
        resource_type="system",
        resource_id="sys_2",
        outcome=AuditOutcome.SUCCESS,
        reason="Record to attempt deletion on",
    )
    await db_session.commit()

    # Attempting to DELETE the audit row MUST raise a PostgreSQL exception
    with pytest.raises(Exception) as exc_info:
        await db_session.execute(
            text("DELETE FROM audit_events WHERE id = :event_id"),
            {"event_id": event.id},
        )
        await db_session.commit()

    err_msg = str(exc_info.value).lower()
    assert "immutable, append-only table" in err_msg or "update and delete operations are forbidden" in err_msg


@pytest.mark.asyncio
async def test_audit_transactional_rollback(db_session):
    """
    Verifies that audit events written during a business transaction roll back
    if the transaction fails.
    """
    test_res_id = f"rollback_test_{uuid.uuid4().hex[:8]}"

    # Begin transaction, record audit event, then roll back
    await record_audit_event(
        db=db_session,
        action="pending_business_op",
        resource_type="test_rollback",
        resource_id=test_res_id,
        outcome=AuditOutcome.SUCCESS,
    )
    await db_session.rollback()

    # Verify event was NOT persisted
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM audit_events WHERE resource_id = :res_id"),
        {"res_id": test_res_id},
    )
    count = result.scalar()
    assert count == 0


@pytest.mark.asyncio
async def test_audit_events_api_retrieval(client: AsyncClient, db_session, create_user_helper):
    """
    Verifies that security administrators can query and filter the audit log via the API.
    """
    sec_admin = await create_user_helper(
        email="auditor_lead@scorva.io",
        platform_role=PlatformRole.SECURITY_ADMIN,
    )
    token_plain = generate_secure_token(32)
    session = UserSession(
        id=uuid.uuid4(),
        user_id=sec_admin.id,
        session_token_hash=hash_session_token(token_plain),
        ip_address="127.0.0.1",
        user_agent="Test/1.0",
        expires_at=text("NOW() + interval '12 hours'"),
        is_revoked=False,
    )
    db_session.add(session)

    # Insert test audit event
    await record_audit_event(
        db=db_session,
        action="test_api_log",
        resource_type="audit_test",
        resource_id="item_100",
        outcome=AuditOutcome.SUCCESS,
        actor_email="auditor_lead@scorva.io",
        actor_role="security_admin",
        reason="API query test record",
    )
    await db_session.commit()

    res = await client.get(
        "/api/v1/admin/security/audit-events?action=test_api_log",
        cookies={settings.SESSION_COOKIE_NAME: token_plain},
    )
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert len(data["items"]) >= 1
    assert data["items"][0]["action"] == "test_api_log"
    assert data["items"][0]["actor_email"] == "auditor_lead@scorva.io"

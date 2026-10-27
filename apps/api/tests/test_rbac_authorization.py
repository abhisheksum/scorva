from datetime import datetime, timedelta, timezone
import uuid
import pytest
from httpx import AsyncClient
from apps.api.config import settings
from apps.api.core.security import generate_secure_token, hash_session_token
from apps.api.modules.users.models import PlatformRole, User, UserSession


async def create_authenticated_session(db_session, user: User) -> str:
    """Helper creating a valid session in DB and returning token_plain."""
    token_plain = generate_secure_token(32)
    token_hash = hash_session_token(token_plain)
    session = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        session_token_hash=token_hash,
        ip_address="127.0.0.1",
        user_agent="TestRunner/1.0",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
        created_at=datetime.now(timezone.utc),
        last_active_at=datetime.now(timezone.utc),
        is_revoked=False,
    )
    db_session.add(session)
    await db_session.commit()
    return token_plain


@pytest.mark.asyncio
async def test_anonymous_request_blocked(client: AsyncClient):
    """Verifies that unauthenticated requests to protected admin endpoints are denied with 401."""
    res1 = await client.get("/api/v1/admin/auth/me")
    assert res1.status_code == 401
    assert res1.json()["code"] == "UNAUTHORIZED"

    res2 = await client.get("/api/v1/admin/users")
    assert res2.status_code == 401
    assert res2.json()["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_user_without_platform_role_denied_access(client: AsyncClient, db_session, create_user_helper):
    """Verifies that an authenticated user lacking any platform_role is blocked with 403."""
    user = await create_user_helper(
        email="plain_user@scorva.io",
        platform_role=None,
    )
    token = await create_authenticated_session(db_session, user)

    res = await client.get(
        "/api/v1/admin/users",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN_NOT_ADMIN"


@pytest.mark.asyncio
async def test_insufficient_platform_role_denied_access(client: AsyncClient, db_session, create_user_helper):
    """
    Verifies role boundaries:
    A billing_admin cannot access user administration (/admin/users requires security_admin or platform_owner).
    """
    billing_user = await create_user_helper(
        email="billing@scorva.io",
        platform_role=PlatformRole.BILLING_ADMIN,
    )
    token = await create_authenticated_session(db_session, billing_user)

    res = await client.get(
        "/api/v1/admin/users",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN_INSUFFICIENT_ROLE"


@pytest.mark.asyncio
async def test_authorized_roles_allowed(client: AsyncClient, db_session, create_user_helper):
    """Verifies that platform_owner and security_admin are authorized for user management."""
    sec_user = await create_user_helper(
        email="secadmin@scorva.io",
        platform_role=PlatformRole.SECURITY_ADMIN,
    )
    token = await create_authenticated_session(db_session, sec_user)

    res = await client.get(
        "/api/v1/admin/users",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, dict)
    assert "items" in data
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_suspended_user_session_immediately_rejected(client: AsyncClient, db_session, create_user_helper):
    """Verifies that a suspended user's active session is rejected on subsequent requests."""
    user = await create_user_helper(
        email="to_suspend@scorva.io",
        platform_role=PlatformRole.SECURITY_ADMIN,
        is_active=True,
    )
    token = await create_authenticated_session(db_session, user)

    # Verify session works
    res1 = await client.get(
        "/api/v1/admin/auth/me",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res1.status_code == 200

    # Suspend user directly in DB
    user.is_active = False
    await db_session.commit()

    # Next request must be rejected
    res2 = await client.get(
        "/api/v1/admin/auth/me",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res2.status_code == 401
    assert res2.json()["code"] == "ACCOUNT_SUSPENDED"


@pytest.mark.asyncio
async def test_admin_status_change_revokes_sessions(client: AsyncClient, db_session, create_user_helper):
    """
    Verifies that calling /admin/users/{id}/status to suspend a user invalidates all their sessions.
    """
    owner = await create_user_helper(
        email="owner_admin@scorva.io",
        platform_role=PlatformRole.PLATFORM_OWNER,
    )
    owner_token = await create_authenticated_session(db_session, owner)

    target_user = await create_user_helper(
        email="sub_admin@scorva.io",
        platform_role=PlatformRole.SUPPORT_ADMIN,
    )
    target_token = await create_authenticated_session(db_session, target_user)

    # Target session initially works
    res_initial = await client.get(
        "/api/v1/admin/auth/me",
        cookies={settings.SESSION_COOKIE_NAME: target_token},
    )
    assert res_initial.status_code == 200

    # Owner suspends target user
    suspend_res = await client.post(
        f"/api/v1/admin/users/{target_user.id}/status",
        json={"is_active": False, "reason": "Security investigation"},
        cookies={settings.SESSION_COOKIE_NAME: owner_token},
        headers={"Origin": "http://testserver"},
    )
    assert suspend_res.status_code == 200
    assert suspend_res.json()["is_active"] is False

    # Target user's session must now be rejected
    res_after = await client.get(
        "/api/v1/admin/auth/me",
        cookies={settings.SESSION_COOKIE_NAME: target_token},
    )
    assert res_after.status_code == 401
    assert res_after.json()["code"] in ("ACCOUNT_SUSPENDED", "SESSION_REVOKED")


@pytest.mark.asyncio
async def test_admin_role_change_revokes_sessions(client: AsyncClient, db_session, create_user_helper):
    """
    Verifies that altering a user's platform role revokes existing sessions to force re-authentication.
    """
    owner = await create_user_helper(
        email="owner_role_changer@scorva.io",
        platform_role=PlatformRole.PLATFORM_OWNER,
    )
    owner_token = await create_authenticated_session(db_session, owner)

    target_user = await create_user_helper(
        email="ops_candidate@scorva.io",
        platform_role=PlatformRole.SUPPORT_ADMIN,
    )
    target_token = await create_authenticated_session(db_session, target_user)

    # Change role to AI Ops Admin
    role_res = await client.post(
        f"/api/v1/admin/users/{target_user.id}/role",
        json={"platform_role": "ai_ops_admin", "reason": "Promoted to AI Ops"},
        cookies={settings.SESSION_COOKIE_NAME: owner_token},
        headers={"Origin": "http://testserver"},
    )
    assert role_res.status_code == 200
    assert role_res.json()["platform_role"] == "ai_ops_admin"

    # Target user's prior session must be rejected (SESSION_REVOKED)
    res_after = await client.get(
        "/api/v1/admin/auth/me",
        cookies={settings.SESSION_COOKIE_NAME: target_token},
    )
    assert res_after.status_code == 401
    assert res_after.json()["code"] == "SESSION_REVOKED"


@pytest.mark.asyncio
async def test_org_owner_cannot_access_super_admin_platform_api(client: AsyncClient, db_session, create_user_helper):
    """
    DUAL-01: An organization owner without platform administrative privileges is
    strictly blocked from accessing platform-level admin APIs with 403 FORBIDDEN_NOT_ADMIN.
    """
    org_owner = await create_user_helper(
        email="org_owner_dual01@scorva.io",
        platform_role=None,
    )
    token = await create_authenticated_session(db_session, org_owner)

    res = await client.get(
        "/api/v1/admin/organizations",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN_NOT_ADMIN"


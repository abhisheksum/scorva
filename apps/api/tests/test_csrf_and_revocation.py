from datetime import datetime, timedelta, timezone
import uuid
import pytest
from httpx import AsyncClient
from apps.api.config import settings
from apps.api.core.redis import delete_cached_session, get_cached_session
from apps.api.core.security import generate_secure_token, hash_session_token
from apps.api.modules.users.models import PlatformRole, UserSession


async def create_active_session(db_session, user) -> str:
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
async def test_csrf_origin_missing_rejected(client: AsyncClient, db_session, create_user_helper):
    """
    Verifies that state-mutating requests with a session cookie but NO Origin/Referer
    are rejected with 403 CSRF_ORIGIN_MISSING.
    """
    user = await create_user_helper(email="csrf_admin@scorva.io")
    token = await create_active_session(db_session, user)

    # Calling a mutation (logout) without Origin or Referer
    res = await client.post(
        "/api/v1/admin/auth/logout",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res.status_code == 403
    data = res.json()
    assert data["code"] == "CSRF_ORIGIN_MISSING"


@pytest.mark.asyncio
async def test_csrf_origin_untrusted_rejected(client: AsyncClient, db_session, create_user_helper):
    """
    Verifies that requests from an untrusted Origin are rejected with 403 CSRF_ORIGIN_INVALID.
    """
    user = await create_user_helper(email="csrf_attacker_target@scorva.io")
    token = await create_active_session(db_session, user)

    res = await client.post(
        "/api/v1/admin/auth/logout",
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers={"Origin": "https://evil-attacker.example.com"},
    )
    assert res.status_code == 403
    data = res.json()
    assert data["code"] == "CSRF_ORIGIN_INVALID"


@pytest.mark.asyncio
async def test_csrf_origin_trusted_allowed(client: AsyncClient, db_session, create_user_helper):
    """
    Verifies that requests with trusted Origin pass CSRF verification.
    """
    user = await create_user_helper(email="csrf_valid@scorva.io")
    token = await create_active_session(db_session, user)

    res = await client.post(
        "/api/v1/admin/auth/logout",
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers={"Origin": "http://localhost:3000"},
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_dual_barrier_redis_cache_miss_fallback_to_postgres(client: AsyncClient, db_session, create_user_helper):
    """
    Verifies that when Redis session cache is empty (cold start or cache eviction),
    request falls back to PostgreSQL source of truth and re-populates Redis cache.
    """
    user = await create_user_helper(email="cold_start@scorva.io")
    token = await create_active_session(db_session, user)
    token_hash = hash_session_token(token)

    # Ensure Redis cache does not have the session
    await delete_cached_session(token_hash)
    assert await get_cached_session(token_hash) is None

    # Request /me should query PostgreSQL, validate, and succeed
    res = await client.get(
        "/api/v1/admin/auth/me",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res.status_code == 200
    assert res.json()["email"] == "cold_start@scorva.io"

    # Verify Redis cache has been re-populated
    cached = await get_cached_session(token_hash)
    assert cached is not None
    assert cached["email"] == "cold_start@scorva.io"


@pytest.mark.asyncio
async def test_dual_barrier_revocation_safety_on_redis_flush(client: AsyncClient, db_session, create_user_helper):
    """
    Verifies failsafe revocation (§6.2):
    Even if Redis is flushed or desynchronized, a session marked is_revoked=True in PostgreSQL
    is NEVER honored.
    """
    user = await create_user_helper(email="revoked_safety@scorva.io")
    token = await create_active_session(db_session, user)
    token_hash = hash_session_token(token)

    # Invalidate session in PostgreSQL
    user.sessions_revoked_at = datetime.now(timezone.utc)
    from sqlalchemy import update
    await db_session.execute(
        update(UserSession).where(UserSession.session_token_hash == token_hash).values(is_revoked=True)
    )
    await db_session.commit()

    # Flush Redis cache
    await delete_cached_session(token_hash)

    # Subsequent request MUST be rejected by PostgreSQL source of truth
    res = await client.get(
        "/api/v1/admin/auth/me",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res.status_code == 401
    assert res.json()["code"] == "SESSION_REVOKED"

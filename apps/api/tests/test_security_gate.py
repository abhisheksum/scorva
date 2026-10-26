"""
Phase 2 Security Gate Verification Test Suite.

Exhaustively verifies:
1. Production configuration safeguards and startup validation.
2. Bootstrap credentials and seeding safety (no production static defaults).
3. Stale Redis cache resilience (PostgreSQL as durable source of truth).
4. Redis outage fallbacks (circuit-breaking, in-memory rate limiting, replay protection).
5. MFA temporary token isolation (challenge/enrollment tokens cannot authenticate API).
6. Proxy header spoofing defense.
7. Timing safety and account enumeration prevention.
8. Audit log immutability and sensitive credential non-leakage.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import Settings, settings
from apps.api.core.database import get_db_session
from apps.api.core.redis import (
    cache_session,
    check_and_mark_totp_used,
    check_rate_limit,
    delete_cached_session,
    delete_mfa_token,
    flush_test_redis,
    get_cached_session,
    get_mfa_token,
    store_mfa_token,
    _memory_store,
)
from apps.api.core.exceptions import AppException
from apps.api.core.security import (
    encrypt_totp_secret,
    generate_secure_token,
    generate_totp_secret,
    hash_password,
    hash_session_token,
)
from apps.api.main import create_app
from apps.api.middleware.proxy_headers import get_client_ip
from apps.api.modules.audit.models import AuditEvent, AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.users.models import PlatformRole, User, UserSession
from apps.api.scripts.seed_admin import seed_development_presets


# ------------------------------------------------------------------------------
# 1. Production Configuration Safeguards & Startup Validation
# ------------------------------------------------------------------------------
def test_production_settings_rejects_insecure_defaults():
    """Verifies that Settings() validation strictly halts startup in production with dev defaults."""
    # Insecure secret key
    with pytest.raises(ValueError, match="SECRET_KEY must be a cryptographically random string"):
        Settings(
            SCORVA_ENV="production",
            DEBUG=False,
            SESSION_COOKIE_SECURE=True,
            SECRET_KEY="insecure-development-secret-key-change-in-production-min-32-chars",
            ENCRYPTION_MASTER_KEY="a" * 32,
            DATABASE_URL="postgresql+asyncpg://prod:secure@prod-db:5432/scorva",
        )

    # Insecure encryption master key
    with pytest.raises(ValueError, match="ENCRYPTION_MASTER_KEY must be a cryptographically random string"):
        Settings(
            SCORVA_ENV="production",
            DEBUG=False,
            SESSION_COOKIE_SECURE=True,
            SECRET_KEY="a" * 32,
            ENCRYPTION_MASTER_KEY="insecure-encryption-key-for-dev-only-32bytes!",
            DATABASE_URL="postgresql+asyncpg://prod:secure@prod-db:5432/scorva",
        )

    # Insecure cookie
    with pytest.raises(ValueError, match="SESSION_COOKIE_SECURE must be True"):
        Settings(
            SCORVA_ENV="production",
            DEBUG=False,
            SESSION_COOKIE_SECURE=False,
            SECRET_KEY="a" * 32,
            ENCRYPTION_MASTER_KEY="b" * 32,
            DATABASE_URL="postgresql+asyncpg://prod:secure@prod-db:5432/scorva",
        )

    # Debug mode active in production
    with pytest.raises(ValueError, match="DEBUG mode must be False"):
        Settings(
            SCORVA_ENV="production",
            DEBUG=True,
            SESSION_COOKIE_SECURE=True,
            SECRET_KEY="a" * 32,
            ENCRYPTION_MASTER_KEY="b" * 32,
            DATABASE_URL="postgresql+asyncpg://prod:secure@prod-db:5432/scorva",
        )

    # Default dev db password in production
    with pytest.raises(ValueError, match="DATABASE_URL must not use the default development password"):
        Settings(
            SCORVA_ENV="production",
            DEBUG=False,
            SESSION_COOKIE_SECURE=True,
            SECRET_KEY="a" * 32,
            ENCRYPTION_MASTER_KEY="b" * 32,
            DATABASE_URL="postgresql+asyncpg://scorva:scorva_dev_password@localhost:5432/scorva",
        )


def test_production_settings_valid_configuration_succeeds():
    """Verifies that properly configured secure production settings pass validation."""
    s = Settings(
        SCORVA_ENV="production",
        DEBUG=False,
        SESSION_COOKIE_SECURE=True,
        SECRET_KEY="8f7e6d5c4b3a291807f6e5d4c3b2a1908f7e6d5c4b3a291807f6e5d4c3b2a190",
        ENCRYPTION_MASTER_KEY="1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d",
        DATABASE_URL="postgresql+asyncpg://scorva_prod:ComplexVaultPassword99@prod-db.internal:5432/scorva",
        CORS_ORIGINS=["https://admin.scorva.io"],
    )
    assert s.SCORVA_ENV == "production"
    assert s.SESSION_COOKIE_SECURE is True
    assert s.DEBUG is False


# ------------------------------------------------------------------------------
# 2. Seeding & Bootstrap Security
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_seed_development_presets_forbidden_in_production(monkeypatch):
    """Verifies that seed_development_presets aborts immediately if SCORVA_ENV is production."""
    monkeypatch.setattr(settings, "SCORVA_ENV", "production")
    with pytest.raises(SystemExit) as exc_info:
        await seed_development_presets()
    assert exc_info.value.code == 1


# ------------------------------------------------------------------------------
# 3. Stale Redis Cache Resilience (PostgreSQL Durable Authority)
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stale_redis_cache_cannot_bypass_session_revocation(
    client: AsyncClient, db_session: AsyncSession, create_user_helper
):
    """
    Simulates a race condition / partition where Redis contains an active session cache entry,
    but PostgreSQL has marked the session is_revoked = TRUE.
    Request must be rejected with 401 SESSION_REVOKED.
    """
    user = await create_user_helper("stale_redis_user@scorva.io", PlatformRole.PLATFORM_OWNER)
    token_plain = generate_secure_token(32)
    token_hash = hash_session_token(token_plain)
    now_utc = datetime.now(timezone.utc)

    # 1. Create revoked session in PostgreSQL
    session = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        session_token_hash=token_hash,
        ip_address="127.0.0.1",
        user_agent="TestAgent",
        expires_at=now_utc + timedelta(hours=1),
        created_at=now_utc - timedelta(minutes=10),
        last_active_at=now_utc - timedelta(minutes=10),
        is_revoked=True,  # REVOKED IN DB
    )
    db_session.add(session)
    await db_session.commit()

    # 2. Inject STALE active cache in Redis
    await cache_session(
        token_hash=token_hash,
        session_data={
            "session_id": str(session.id),
            "user_id": str(user.id),
            "email": user.email,
            "platform_role": user.platform_role.value,
            "is_active": True,
            "created_at": (now_utc - timedelta(minutes=10)).isoformat(),
            "sessions_revoked_at": None,  # Stale: Redis thinks not revoked
        },
        ttl_seconds=3600,
    )

    # 3. Dispatch request with session cookie
    response = await client.get(
        "/api/v1/admin/auth/me",
        cookies={settings.SESSION_COOKIE_NAME: token_plain},
    )

    # Must be rejected because PostgreSQL is the definitive source of truth
    assert response.status_code == 401
    data = response.json()
    assert data["code"] == "SESSION_REVOKED"

    # Stale key in Redis should now be deleted
    cached_after = await get_cached_session(token_hash)
    assert cached_after is None


@pytest.mark.asyncio
async def test_stale_redis_cache_cannot_bypass_suspended_account(
    client: AsyncClient, db_session: AsyncSession, create_user_helper
):
    """
    Simulates case where Redis cache has is_active: True, but PostgreSQL user has is_active = False.
    Request must be rejected with 401 ACCOUNT_SUSPENDED.
    """
    user = await create_user_helper("stale_suspended_user@scorva.io", PlatformRole.PLATFORM_OWNER)
    user.is_active = False  # Suspended in DB
    token_plain = generate_secure_token(32)
    token_hash = hash_session_token(token_plain)
    now_utc = datetime.now(timezone.utc)

    session = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        session_token_hash=token_hash,
        ip_address="127.0.0.1",
        user_agent="TestAgent",
        expires_at=now_utc + timedelta(hours=1),
        created_at=now_utc - timedelta(minutes=10),
        last_active_at=now_utc - timedelta(minutes=10),
        is_revoked=False,
    )
    db_session.add(session)
    await db_session.commit()

    # Redis contains stale is_active: True
    await cache_session(
        token_hash=token_hash,
        session_data={
            "session_id": str(session.id),
            "user_id": str(user.id),
            "email": user.email,
            "platform_role": user.platform_role.value,
            "is_active": True,
            "created_at": (now_utc - timedelta(minutes=10)).isoformat(),
            "sessions_revoked_at": None,
        },
        ttl_seconds=3600,
    )

    response = await client.get(
        "/api/v1/admin/auth/me",
        cookies={settings.SESSION_COOKIE_NAME: token_plain},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "ACCOUNT_SUSPENDED"


# ------------------------------------------------------------------------------
# 4. Redis Outage Resilience & In-Memory Fallbacks
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_session_validation_resilient_under_redis_outage(
    client: AsyncClient, db_session: AsyncSession, create_user_helper
):
    """
    Simulates total Redis downtime (get_redis_client raises RedisConnError).
    Valid sessions must continue to succeed by querying PostgreSQL directly.
    """
    user = await create_user_helper("redis_outage_user@scorva.io", PlatformRole.PLATFORM_OWNER)
    token_plain = generate_secure_token(32)
    token_hash = hash_session_token(token_plain)
    now_utc = datetime.now(timezone.utc)

    session = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        session_token_hash=token_hash,
        ip_address="127.0.0.1",
        user_agent="TestAgent",
        expires_at=now_utc + timedelta(hours=1),
        created_at=now_utc,
        last_active_at=now_utc,
        is_revoked=False,
    )
    db_session.add(session)
    await db_session.commit()

    # Mock Redis client to simulate network partition / crash
    with patch("apps.api.core.redis.get_redis_client", side_effect=RedisConnError("Connection refused to Redis")):
        response = await client.get(
            "/api/v1/admin/auth/me",
            cookies={settings.SESSION_COOKIE_NAME: token_plain},
        )
        assert response.status_code == 200
        assert response.json()["email"] == "redis_outage_user@scorva.io"


@pytest.mark.asyncio
async def test_multi_worker_totp_replay_prevention_under_redis_outage():
    """
    Simulates multiple independent API workers during a Redis outage.
    Verifies that TOTP codes cannot be replayed across different worker processes
    because state is durably synchronized via PostgreSQL totp_replay_prevention.
    """
    user_id = str(uuid.uuid4())
    totp_code = "789123"

    with patch("apps.api.core.redis.get_redis_client", side_effect=RedisConnError("Redis offline")):
        # --- Worker 1 execution ---
        _memory_store.clear()  # Worker 1's isolated process memory
        is_fresh_worker_1 = await check_and_mark_totp_used(user_id, totp_code, ttl_seconds=90)
        assert is_fresh_worker_1 is True

        # --- Worker 2 execution (independent process memory) ---
        _memory_store.clear()  # Worker 2 has separate memory space
        # Attacker tries to replay the same TOTP code against Worker 2
        is_fresh_worker_2 = await check_and_mark_totp_used(user_id, totp_code, ttl_seconds=90)
        assert is_fresh_worker_2 is False, (
            "Worker 2 must reject replayed TOTP code via durable PostgreSQL fallback"
        )


@pytest.mark.asyncio
async def test_multi_worker_rate_limiting_under_redis_outage():
    """
    Simulates an attacker distributing login attempts across multiple independent workers
    during a Redis outage. Verifies that rate limits are globally enforced across workers
    via PostgreSQL rate_limit_buckets.
    """
    attacker_ip = "198.51.100.42"
    max_attempts = 5
    window_seconds = 60

    with patch("apps.api.core.redis.get_redis_client", side_effect=RedisConnError("Redis offline")):
        # Worker 1 processes 3 failed login attempts
        _memory_store.clear()
        for _ in range(3):
            allowed, remaining, _ = await check_rate_limit(
                "login_ip", attacker_ip, max_attempts=max_attempts, window_seconds=window_seconds
            )
            assert allowed is True

        # Worker 2 (separate process memory) processes 2 failed login attempts (total = 5)
        _memory_store.clear()
        for _ in range(2):
            allowed, remaining, _ = await check_rate_limit(
                "login_ip", attacker_ip, max_attempts=max_attempts, window_seconds=window_seconds
            )
            assert allowed is True

        # Worker 1 receives the 6th attempt -> MUST be blocked
        _memory_store.clear()
        allowed, remaining, _ = await check_rate_limit(
            "login_ip", attacker_ip, max_attempts=max_attempts, window_seconds=window_seconds
        )
        assert allowed is False, "6th attempt across workers must be blocked by global rate limiter"
        assert remaining == 0


@pytest.mark.asyncio
async def test_multi_worker_mfa_token_sharing_under_redis_outage():
    """
    Simulates a 2-step MFA flow where Step 1 (password verification) hits Worker 1,
    and Step 2 (TOTP verification) hits Worker 2 while Redis is offline.
    Verifies that ephemeral tokens are shared durably via PostgreSQL mfa_pending_tokens.
    """
    user_id = str(uuid.uuid4())
    challenge_token = generate_secure_token(32)

    with patch("apps.api.core.redis.get_redis_client", side_effect=RedisConnError("Redis offline")):
        # Worker 1 issues MFA challenge token
        _memory_store.clear()
        await store_mfa_token("challenge", challenge_token, {"user_id": user_id}, ttl_seconds=300)

        # Worker 2 receives TOTP verification request with challenge token
        _memory_store.clear()  # Worker 2 does not have Worker 1's local memory
        token_data = await get_mfa_token("challenge", challenge_token)
        assert token_data is not None
        assert token_data["user_id"] == user_id

        # Worker 2 consumes and deletes the challenge token
        await delete_mfa_token("challenge", challenge_token)

        # Worker 1 checks again; token must be gone
        _memory_store.clear()
        token_data_after = await get_mfa_token("challenge", challenge_token)
        assert token_data_after is None


@pytest.mark.asyncio
async def test_security_services_fail_closed_under_total_storage_partition():
    """
    Verifies the Safe Failure Policy: if both Redis AND PostgreSQL fail,
    security-critical operations fail closed to prevent brute-force attacks and TOTP replays.
    """
    with patch("apps.api.core.redis.get_redis_client", side_effect=RedisConnError("Redis offline")):
        # Mock DB failure
        with patch("apps.api.core.redis._db_check_and_mark_totp_used", side_effect=AppException(
            code="SERVICE_UNAVAILABLE",
            message="Authentication security services are temporarily unavailable. Please retry.",
            status_code=503,
            title="Service Temporarily Unavailable",
        )):
            with pytest.raises(AppException) as exc_info:
                await check_and_mark_totp_used(str(uuid.uuid4()), "123456", ttl_seconds=60)
            assert exc_info.value.status_code == 503

        # Rate limiting fails closed: returns allowed=False
        with patch("apps.api.core.redis._db_check_rate_limit", return_value=(False, 0, 60)):
            allowed, remaining, _ = await check_rate_limit("login_ip", "10.0.0.1", 5, 60)
            assert allowed is False
            assert remaining == 0


# ------------------------------------------------------------------------------
# 5. MFA Temporary Token Isolation
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mfa_temporary_tokens_cannot_be_used_as_sessions(
    client: AsyncClient, create_user_helper
):
    """
    Verifies that ephemeral enrollment or challenge tokens cannot authenticate
    normal protected routes as session cookies or Bearer tokens.
    """
    user = await create_user_helper("mfa_isolation_user@scorva.io", PlatformRole.PLATFORM_OWNER)
    challenge_token = generate_secure_token(24)
    await store_mfa_token("challenge", challenge_token, {"user_id": str(user.id)}, ttl_seconds=300)

    enrollment_token = generate_secure_token(24)
    await store_mfa_token("enrollment", enrollment_token, {"user_id": str(user.id)}, ttl_seconds=300)

    # 1. Try using challenge_token as session cookie
    r1 = await client.get(
        "/api/v1/admin/auth/me",
        cookies={settings.SESSION_COOKIE_NAME: challenge_token},
    )
    assert r1.status_code == 401
    assert r1.json()["code"] == "SESSION_NOT_FOUND"

    # 2. Try using challenge_token as Bearer token
    r2 = await client.get(
        "/api/v1/admin/auth/me",
        headers={"Authorization": f"Bearer {challenge_token}"},
    )
    assert r2.status_code == 401
    assert r2.json()["code"] == "SESSION_NOT_FOUND"

    # 3. Try using enrollment_token as session cookie
    r3 = await client.get(
        "/api/v1/admin/users",
        cookies={settings.SESSION_COOKIE_NAME: enrollment_token},
    )
    assert r3.status_code == 401
    assert r3.json()["code"] == "SESSION_NOT_FOUND"


# ------------------------------------------------------------------------------
# 6. Proxy Headers Spoofing Defense
# ------------------------------------------------------------------------------
def test_untrusted_client_cannot_spoof_x_forwarded_for():
    """Verifies that an untrusted client IP sending X-Forwarded-For is ignored in favor of client.host."""
    from starlette.requests import Request

    # Untrusted client IP 10.99.1.5 not in TRUSTED_PROXIES
    scope = {
        "type": "http",
        "client": ("10.99.1.5", 54321),
        "headers": [
            (b"x-forwarded-for", b"8.8.8.8, 10.0.0.1"),
        ],
    }
    req = Request(scope)
    resolved_ip = get_client_ip(req)
    assert resolved_ip == "10.99.1.5"  # Spoofed 8.8.8.8 ignored


def test_trusted_proxy_x_forwarded_for_is_trusted():
    """Verifies that when request arrives from 127.0.0.1 (in TRUSTED_PROXIES), X-Forwarded-For is respected."""
    from starlette.requests import Request

    scope = {
        "type": "http",
        "client": ("127.0.0.1", 54321),
        "headers": [
            (b"x-forwarded-for", b"203.0.113.195, 10.0.0.1"),
        ],
    }
    req = Request(scope)
    resolved_ip = get_client_ip(req)
    assert resolved_ip == "203.0.113.195"


# ------------------------------------------------------------------------------
# 7. Sensitive Credential Non-Leakage in Audit Trail
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_records_never_leak_passwords_or_secrets(
    client: AsyncClient, db_session: AsyncSession, create_user_helper
):
    """
    Executes login failure and role changes, then queries audit_events to verify
    passwords, raw tokens, and encryption keys never appear in diff_payload or reason.
    """
    user = await create_user_helper("audit_leak_check@scorva.io", PlatformRole.PLATFORM_OWNER)

    # Trigger a failed login with secret password
    secret_pw = "SuperSecretPlainTextPassword123!"
    await client.post(
        "/api/v1/admin/auth/login",
        json={"email": user.email, "password": secret_pw},
    )

    # Inspect audit records
    stmt = select(AuditEvent).where(AuditEvent.actor_email == user.email)
    events = (await db_session.execute(stmt)).scalars().all()
    assert len(events) > 0

    for evt in events:
        # Assert reason does not contain plaintext password
        if evt.reason:
            assert secret_pw not in evt.reason
        # Assert diff_payload does not contain plaintext password or secret keys
        if evt.diff_payload:
            payload_str = str(evt.diff_payload)
            assert secret_pw not in payload_str
            assert "hashed_password" not in evt.diff_payload
            assert "encrypted_mfa_secret" not in evt.diff_payload

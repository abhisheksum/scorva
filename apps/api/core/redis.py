import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import time
from typing import Any, Dict, Optional, Tuple
import uuid
import redis.asyncio as aioredis
from redis.exceptions import ConnectionError, RedisError, TimeoutError
from sqlalchemy import text
from apps.api.config import settings

logger = logging.getLogger("scorva.redis")

_REDIS_ERRORS = (ConnectionError, TimeoutError, RedisError, RuntimeError, OSError)

# Singleton Redis client
_redis_pool: Optional[aioredis.Redis] = None

# Ephemeral process-local store used strictly for standalone in-memory unit tests
_memory_store: Dict[str, Tuple[Any, float]] = {}


def get_redis_client() -> aioredis.Redis:
    """
    Returns async Redis client instance.
    Guarantees connection pool is recreated if the active asyncio event loop changes (e.g. in pytest).
    """
    global _redis_pool
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if _redis_pool is not None:
        pool_loop = getattr(_redis_pool.connection_pool, "_loop", None)
        if pool_loop is not None and current_loop is not None and pool_loop is not current_loop:
            _redis_pool = None

    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=1.0,
            socket_connect_timeout=1.0,
        )
    return _redis_pool


async def close_redis_client() -> None:
    """Closes Redis client connection pool."""
    global _redis_pool
    if _redis_pool is not None:
        try:
            await _redis_pool.aclose()
        except Exception:
            pass
        _redis_pool = None


# ------------------------------------------------------------------------------
# In-Memory Ephemeral Store Helpers (Fallback & standalone test support)
# ------------------------------------------------------------------------------
def _mem_set(key: str, value: Any, ttl_seconds: int) -> None:
    expire_at = time.time() + ttl_seconds
    _memory_store[key] = (value, expire_at)


def _mem_get(key: str) -> Optional[Any]:
    entry = _memory_store.get(key)
    if not entry:
        return None
    val, expire_at = entry
    if time.time() > expire_at:
        del _memory_store[key]
        return None
    return val


def _mem_delete(key: str) -> None:
    _memory_store.pop(key, None)


# ------------------------------------------------------------------------------
# Session Cache API (§6.2 Fast-Path Cache)
# ------------------------------------------------------------------------------
async def cache_session(token_hash: str, session_data: Dict[str, Any], ttl_seconds: int) -> None:
    """Caches session metadata in Redis with remaining TTL."""
    key = f"session:{token_hash}"
    val = json.dumps(session_data)
    try:
        client = get_redis_client()
        await client.set(key, val, ex=ttl_seconds)
    except _REDIS_ERRORS as exc:
        logger.warning(f"Redis cache_session fallback to memory store: {exc}")
        _mem_set(key, val, ttl_seconds)


async def get_cached_session(token_hash: str) -> Optional[Dict[str, Any]]:
    """Retrieves session metadata from fast-path cache."""
    key = f"session:{token_hash}"
    raw: Optional[str] = None
    try:
        client = get_redis_client()
        raw = await client.get(key)
    except _REDIS_ERRORS as exc:
        logger.warning(f"Redis get_cached_session fallback to memory store: {exc}")
        raw = _mem_get(key)

    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return None
    return None


async def delete_cached_session(token_hash: str) -> None:
    """Deletes cached session from fast-path store."""
    key = f"session:{token_hash}"
    try:
        client = get_redis_client()
        await client.delete(key)
    except _REDIS_ERRORS as exc:
        logger.warning(f"Redis delete_cached_session fallback to memory store: {exc}")
    _mem_delete(key)


# ------------------------------------------------------------------------------
# Ephemeral MFA & Verification Tokens (Shared Multi-Worker Store)
# ------------------------------------------------------------------------------
async def _db_store_mfa_token(token_type: str, token: str, data: Dict[str, Any], ttl_seconds: int) -> None:
    from apps.api.core.database import AsyncSessionLocal
    now_utc = datetime.now(timezone.utc)
    expires_at = now_utc + timedelta(seconds=ttl_seconds)
    user_id_raw = data.get("user_id")
    user_uuid = uuid.UUID(user_id_raw) if user_id_raw else uuid.UUID(int=0)

    sql = text("""
        INSERT INTO mfa_pending_tokens (token, token_type, user_id, data, expires_at)
        VALUES (:token, :token_type, :user_id, :data, :expires_at)
        ON CONFLICT (token) DO UPDATE
        SET data = :data, expires_at = :expires_at;
    """)
    async with AsyncSessionLocal() as session:
        await session.execute(
            sql,
            {
                "token": token,
                "token_type": token_type,
                "user_id": user_uuid,
                "data": json.dumps(data),
                "expires_at": expires_at,
            },
        )
        await session.commit()


async def _db_get_mfa_token(token_type: str, token: str) -> Optional[Dict[str, Any]]:
    from apps.api.core.database import AsyncSessionLocal
    now_utc = datetime.now(timezone.utc)
    sql = text("""
        SELECT data FROM mfa_pending_tokens
        WHERE token = :token AND token_type = :token_type AND expires_at > :now_utc;
    """)
    async with AsyncSessionLocal() as session:
        result = await session.execute(sql, {"token": token, "token_type": token_type, "now_utc": now_utc})
        row = result.scalar_one_or_none()
        if row:
            if isinstance(row, dict):
                return row
            try:
                return json.loads(row)
            except Exception:
                return None
        return None


async def _db_delete_mfa_token(token_type: str, token: str) -> None:
    from apps.api.core.database import AsyncSessionLocal
    sql = text("DELETE FROM mfa_pending_tokens WHERE token = :token AND token_type = :token_type;")
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(sql, {"token": token, "token_type": token_type})
            await session.commit()
    except Exception as exc:
        logger.warning(f"Failed to delete mfa token from database: {exc}")


async def store_mfa_token(token_type: str, token: str, data: Dict[str, Any], ttl_seconds: int) -> None:
    """
    Stores temporary enrollment, challenge, or pending secret token.
    Fast-path: Redis. Multi-worker fallback: PostgreSQL.
    """
    key = f"mfa:{token_type}:{token}"
    val = json.dumps(data)
    try:
        client = get_redis_client()
        await client.set(key, val, ex=ttl_seconds)
    except _REDIS_ERRORS as exc:
        logger.warning(f"Redis store_mfa_token fallback to PostgreSQL: {exc}")
        await _db_store_mfa_token(token_type, token, data, ttl_seconds)


async def get_mfa_token(token_type: str, token: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves and deserializes temporary MFA token data.
    Fast-path: Redis. Multi-worker fallback: PostgreSQL.
    """
    key = f"mfa:{token_type}:{token}"
    raw: Optional[str] = None
    try:
        client = get_redis_client()
        raw = await client.get(key)
    except _REDIS_ERRORS as exc:
        logger.warning(f"Redis get_mfa_token fallback to PostgreSQL: {exc}")
        return await _db_get_mfa_token(token_type, token)

    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return None

    # Fallback to DB check in case token was saved during Redis outage
    return await _db_get_mfa_token(token_type, token)


async def delete_mfa_token(token_type: str, token: str) -> None:
    """Removes temporary MFA token from both Redis and PostgreSQL fallback."""
    key = f"mfa:{token_type}:{token}"
    try:
        client = get_redis_client()
        await client.delete(key)
    except _REDIS_ERRORS as exc:
        logger.warning(f"Redis delete_mfa_token fallback: {exc}")
    await _db_delete_mfa_token(token_type, token)


# ------------------------------------------------------------------------------
# Rate Limiting (Globally Consistent Across Multi-Worker Instances)
# ------------------------------------------------------------------------------
async def _db_check_rate_limit(
    key: str, max_attempts: int, window_seconds: int
) -> Tuple[bool, int, int]:
    """
    Durable multi-worker rate limiting via atomic PostgreSQL UPSERT.
    Guarantees rate limits are globally enforced across all API workers.
    """
    from apps.api.core.database import AsyncSessionLocal
    now_utc = datetime.now(timezone.utc)
    expires_at = now_utc + timedelta(seconds=window_seconds)

    sql = text("""
        INSERT INTO rate_limit_buckets (key, attempts, window_start, expires_at)
        VALUES (:key, 1, :now_utc, :expires_at)
        ON CONFLICT (key) DO UPDATE
        SET attempts = CASE 
            WHEN rate_limit_buckets.expires_at <= :now_utc THEN 1 
            ELSE rate_limit_buckets.attempts + 1 
        END,
        window_start = CASE
            WHEN rate_limit_buckets.expires_at <= :now_utc THEN :now_utc
            ELSE rate_limit_buckets.window_start
        END,
        expires_at = CASE 
            WHEN rate_limit_buckets.expires_at <= :now_utc THEN :expires_at 
            ELSE rate_limit_buckets.expires_at 
        END
        RETURNING attempts, EXTRACT(EPOCH FROM (expires_at - :now_utc))::INT AS ttl;
    """)
    try:
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                sql,
                {"key": key, "now_utc": now_utc, "expires_at": expires_at}
            )
            row = res.fetchone()
            await session.commit()
            if row:
                current_attempts = row[0]
                ttl = max(1, int(row[1]))
                allowed = current_attempts <= max_attempts
                remaining = max(0, max_attempts - current_attempts)
                return allowed, remaining, ttl
            return True, max_attempts - 1, window_seconds
    except Exception as db_exc:
        logger.error(f"Failed to record rate limit state in database: {db_exc}")
        # Safe Failure Policy: If both Redis and DB are down, fail closed for security
        return False, 0, window_seconds


async def check_rate_limit(
    key_prefix: str, identifier: str, max_attempts: int, window_seconds: int
) -> Tuple[bool, int, int]:
    """
    Fixed-window rate limiter.
    Fast-path: Redis INCR + EXPIRE.
    Durable Multi-Worker Fallback: PostgreSQL atomic rate_limit_buckets.
    Returns (is_allowed, remaining_attempts, retry_after_seconds).
    """
    key = f"rate_limit:{key_prefix}:{identifier}"
    try:
        client = get_redis_client()
        current = await client.incr(key)
        if current == 1:
            await client.expire(key, window_seconds)
            ttl = window_seconds
        else:
            ttl = await client.ttl(key)
            if ttl < 0:
                ttl = window_seconds

        allowed = current <= max_attempts
        remaining = max(0, max_attempts - current)
        return allowed, remaining, ttl
    except _REDIS_ERRORS as exc:
        logger.warning(f"Redis rate limiter fallback to PostgreSQL: {exc}")
        return await _db_check_rate_limit(key, max_attempts, window_seconds)


async def reset_rate_limit(key_prefix: str, identifier: str) -> None:
    """
    Clears rate limit counter (e.g. upon successful authentication).
    Removes the key from Redis and clears any PostgreSQL fallback record.
    """
    key = f"rate_limit:{key_prefix}:{identifier}"
    try:
        client = get_redis_client()
        await client.delete(key)
    except _REDIS_ERRORS as exc:
        logger.warning(f"Redis reset rate limit error: {exc}")

    try:
        from apps.api.core.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("DELETE FROM rate_limit_buckets WHERE key = :key"),
                {"key": key},
            )
            await session.commit()
    except Exception:
        pass


# ------------------------------------------------------------------------------
# TOTP Replay Protection (Globally Consistent Across Multi-Worker Instances)
# ------------------------------------------------------------------------------
async def _db_check_and_mark_totp_used(user_id: str, code: str, ttl_seconds: int) -> bool:
    """
    Atomic PostgreSQL check & mark used for TOTP replay prevention across all workers.
    """
    from apps.api.core.database import AsyncSessionLocal
    from apps.api.core.exceptions import AppException
    from fastapi import status
    now_utc = datetime.now(timezone.utc)
    expires_at = now_utc + timedelta(seconds=ttl_seconds)

    sql = text("""
        INSERT INTO totp_replay_prevention (user_id, code, expires_at)
        VALUES (:user_id, :code, :expires_at)
        ON CONFLICT (user_id, code) DO NOTHING;
    """)
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                sql,
                {"user_id": uuid.UUID(user_id), "code": code, "expires_at": expires_at}
            )
            await session.commit()
            return result.rowcount > 0
    except Exception as db_exc:
        logger.error(f"Failed to record TOTP replay state in database: {db_exc}")
        # Safe Failure Policy: Fail closed
        raise AppException(
            code="SERVICE_UNAVAILABLE",
            message="Authentication security services are temporarily unavailable. Please retry.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            title="Service Temporarily Unavailable",
        )


async def check_and_mark_totp_used(user_id: str, code: str, ttl_seconds: int = 90) -> bool:
    """
    Guarantees that a TOTP code cannot be replayed within its validity window.
    Fast-path: Redis SET with NX.
    Durable Multi-Worker Fallback: PostgreSQL totp_replay_prevention table.
    Returns True if code was fresh (not previously used), False if replayed.
    """
    key = f"totp_used:{user_id}:{code}"
    try:
        client = get_redis_client()
        # SET with NX (only set if not exists)
        is_fresh = await client.set(key, "1", ex=ttl_seconds, nx=True)
        return bool(is_fresh)
    except _REDIS_ERRORS as exc:
        logger.warning(f"Redis totp replay protection fallback to PostgreSQL: {exc}")
        return await _db_check_and_mark_totp_used(user_id, code, ttl_seconds)


async def flush_test_redis() -> None:
    """Flushes test Redis keys, clears in-memory fallback store, and purges test fallback tables."""
    global _memory_store
    _memory_store.clear()
    try:
        client = get_redis_client()
        await client.flushdb()
    except _REDIS_ERRORS:
        pass
    try:
        from apps.api.core.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            await session.execute(text("TRUNCATE TABLE totp_replay_prevention, rate_limit_buckets, mfa_pending_tokens;"))
            await session.commit()
    except Exception:
        pass

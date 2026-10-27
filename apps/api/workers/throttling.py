from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
import logging
import time
from typing import Any, AsyncIterator, Dict, Iterator, Optional
import uuid

import redis
from redis.exceptions import ConnectionError, RedisError, TimeoutError

from apps.api.config import settings
from apps.api.core.metrics import metrics_collector
import apps.api.core.redis as core_async_redis

logger = logging.getLogger("scorva.workers.throttling")


class RedisUnavailableError(Exception):
    """Raised when Redis is disconnected or unavailable during concurrency operations."""
    pass


class ConcurrencyLimitExceededError(Exception):
    """Raised when tenant evaluation concurrency capacity is saturated."""
    pass


@dataclass(frozen=True)
class TenantSlot:
    organization_id: uuid.UUID
    job_id: uuid.UUID
    worker_id: str
    slot_token: str
    acquired_at: float
    ttl_seconds: int

    @property
    def member_key(self) -> str:
        return f"{self.job_id}:{self.slot_token}"

    @property
    def redis_key(self) -> str:
        return f"scorva:eval:concurrency:{self.organization_id}"


# ------------------------------------------------------------------------------
# Atomic Lua Scripts for Atomic Distributed Semaphores
# ------------------------------------------------------------------------------

_LUA_ACQUIRE = """
-- KEYS[1]: scorva:eval:concurrency:{org_id}
-- ARGV[1]: now_epoch (float/number)
-- ARGV[2]: max_concurrency (number)
-- ARGV[3]: member ("{job_id}:{slot_token}")
-- ARGV[4]: expires_at_epoch (now + ttl_seconds)
-- ARGV[5]: job_id_prefix ("{job_id}:")

-- 1. Prune expired members (crashed workers recovered automatically)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])

-- 2. Idempotency check: Does this exact member already exist?
local existing = redis.call('ZSCORE', KEYS[1], ARGV[3])
if existing then
    redis.call('ZADD', KEYS[1], ARGV[4], ARGV[3])
    return 1
end

-- 3. Duplicate delivery check: Does ANY member for this job already hold a slot?
local all_members = redis.call('ZRANGE', KEYS[1], 0, -1)
for i, m in ipairs(all_members) do
    if string.sub(m, 1, string.len(ARGV[5])) == ARGV[5] then
        redis.call('ZADD', KEYS[1], ARGV[4], m)
        return 1
    end
end

-- 4. Check active slot count against tenant limit
local current_count = redis.call('ZCARD', KEYS[1])
if current_count < tonumber(ARGV[2]) then
    redis.call('ZADD', KEYS[1], ARGV[4], ARGV[3])
    return 1
else
    return 0
end
"""

_LUA_RELEASE = """
-- KEYS[1]: scorva:eval:concurrency:{org_id}
-- ARGV[1]: member ("{job_id}:{slot_token}")
-- Fencing check: Only the exact owning worker slot can be released
return redis.call('ZREM', KEYS[1], ARGV[1])
"""

_LUA_RENEW = """
-- KEYS[1]: scorva:eval:concurrency:{org_id}
-- ARGV[1]: member ("{job_id}:{slot_token}")
-- ARGV[2]: new_expires_at
local existing = redis.call('ZSCORE', KEYS[1], ARGV[1])
if existing then
    redis.call('ZADD', KEYS[1], ARGV[2], ARGV[1])
    return 1
else
    return 0
end
"""

_LUA_PRUNE_AND_COUNT = """
-- KEYS[1]: scorva:eval:concurrency:{org_id}
-- ARGV[1]: now_epoch
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
return redis.call('ZCARD', KEYS[1])
"""


class TenantConcurrencyGovernor:
    """
    Subsystem A Sub-Milestone 5.5: Distributed Tenant Evaluation Concurrency Governor.

    Invariants:
    1. Tenant Isolation: Each tenant's concurrency limit is enforced against its dedicated
       isolated Redis Sorted Set key (`scorva:eval:concurrency:{org_id}`).
    2. Atomic Lua Acquisition: Zero race conditions or over-subscription across concurrent workers.
    3. Fenced Ownership: Every slot has a unique token; a worker cannot release another worker's slot.
    4. Duplicate Delivery Safety: Duplicate tasks for the same job refresh existing lease without consuming slots.
    5. Automatic Dead-Worker Recovery: Expired slots are automatically pruned via sliding window scores.
    6. Failsafe Behavior: If Redis is unavailable, acquisition fails closed to prevent unbounded execution storms.
    """

    DEFAULT_TENANT_LIMIT = 3
    DEFAULT_TTL_SECONDS = 120

    def __init__(
        self,
        sync_redis_client: Optional[redis.Redis] = None,
        default_limit: int = DEFAULT_TENANT_LIMIT,
        default_ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._sync_client = sync_redis_client
        self._default_limit = max(1, default_limit)
        self._default_ttl_seconds = max(10, default_ttl_seconds)

    def _get_sync_client(self) -> redis.Redis:
        if self._sync_client is None:
            self._sync_client = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=1.5,
                socket_connect_timeout=1.5,
            )
        return self._sync_client

    # --------------------------------------------------------------------------
    # Synchronous Operations (Worker Execution Path)
    # --------------------------------------------------------------------------

    def acquire_sync(
        self,
        organization_id: uuid.UUID,
        job_id: uuid.UUID,
        worker_id: str,
        limit: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
    ) -> Optional[TenantSlot]:
        """
        Attempts to atomically acquire a tenant evaluation concurrency slot.
        Returns TenantSlot on success, None on saturation (limit reached).
        Raises RedisUnavailableError if Redis connection fails (fail closed).
        """
        effective_limit = limit if (limit is not None and limit > 0) else self._default_limit
        effective_ttl = ttl_seconds if (ttl_seconds is not None and ttl_seconds > 0) else self._default_ttl_seconds

        slot_token = f"slot-{uuid.uuid4().hex[:12]}"
        slot = TenantSlot(
            organization_id=organization_id,
            job_id=job_id,
            worker_id=worker_id,
            slot_token=slot_token,
            acquired_at=time.time(),
            ttl_seconds=effective_ttl,
        )

        now = time.time()
        expires_at = now + effective_ttl
        job_prefix = f"{job_id}:"

        try:
            client = self._get_sync_client()
            res = client.eval(
                _LUA_ACQUIRE,
                1,
                slot.redis_key,
                str(now),
                str(effective_limit),
                slot.member_key,
                str(expires_at),
                job_prefix,
            )
        except (ConnectionError, TimeoutError, RedisError, OSError) as e:
            logger.warning("Redis error during tenant concurrency acquisition for org %s: %s", organization_id, e)
            metrics_collector.inc_counter("scorva_redis_errors_total", labels={"operation": "acquire"})
            raise RedisUnavailableError(f"Redis unavailable during concurrency acquisition: {e}") from e

        if int(res) == 1:
            metrics_collector.inc_counter("scorva_tenant_concurrency_slots_acquired_total")
            metrics_collector.inc_gauge("scorva_tenant_concurrency_slots_active")
            logger.info("Concurrency slot acquired for job %s (org: %s, token: %s)", job_id, organization_id, slot_token)
            return slot
        else:
            metrics_collector.inc_counter("scorva_tenant_concurrency_rejected_total")
            logger.warning(
                "Tenant concurrency limit saturated (limit=%d) for org %s. Job %s rejected.",
                effective_limit, organization_id, job_id,
            )
            return None

    def release_sync(self, slot: TenantSlot) -> bool:
        """
        Releases an owned tenant concurrency slot.
        Fenced: Only removes the exact member key matching the slot token.
        Safe against duplicate release calls.
        """
        try:
            client = self._get_sync_client()
            res = client.eval(
                _LUA_RELEASE,
                1,
                slot.redis_key,
                slot.member_key,
            )
            removed = int(res) > 0
            if removed:
                metrics_collector.dec_gauge("scorva_tenant_concurrency_slots_active")
                logger.info("Concurrency slot released for job %s (org: %s)", slot.job_id, slot.organization_id)
            return removed
        except (ConnectionError, TimeoutError, RedisError, OSError) as e:
            logger.warning("Redis error during slot release for job %s: %s", slot.job_id, e)
            metrics_collector.inc_counter("scorva_redis_errors_total", labels={"operation": "release"})
            return False

    def renew_sync(self, slot: TenantSlot, ttl_seconds: Optional[int] = None) -> bool:
        """Renews the expiration TTL of an actively held slot."""
        effective_ttl = ttl_seconds if (ttl_seconds is not None and ttl_seconds > 0) else slot.ttl_seconds
        new_expires_at = time.time() + effective_ttl

        try:
            client = self._get_sync_client()
            res = client.eval(
                _LUA_RENEW,
                1,
                slot.redis_key,
                slot.member_key,
                str(new_expires_at),
            )
            return int(res) == 1
        except (ConnectionError, TimeoutError, RedisError, OSError) as e:
            logger.warning("Redis error during slot renewal for job %s: %s", slot.job_id, e)
            metrics_collector.inc_counter("scorva_redis_errors_total", labels={"operation": "renew"})
            return False

    def get_active_count_sync(self, organization_id: uuid.UUID) -> int:
        """Returns the current number of active (unexpired) slots for a tenant."""
        key = f"scorva:eval:concurrency:{organization_id}"
        now = time.time()
        try:
            client = self._get_sync_client()
            res = client.eval(_LUA_PRUNE_AND_COUNT, 1, key, str(now))
            return int(res)
        except (ConnectionError, TimeoutError, RedisError, OSError) as e:
            logger.warning("Redis error getting active count for org %s: %s", organization_id, e)
            metrics_collector.inc_counter("scorva_redis_errors_total", labels={"operation": "count"})
            raise RedisUnavailableError(f"Redis unavailable: {e}") from e

    @contextmanager
    def slot_scope_sync(
        self,
        organization_id: uuid.UUID,
        job_id: uuid.UUID,
        worker_id: str,
        limit: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
    ) -> Iterator[TenantSlot]:
        """Context manager guaranteeing slot release on ordinary completion, failure, or exception."""
        slot = self.acquire_sync(
            organization_id=organization_id,
            job_id=job_id,
            worker_id=worker_id,
            limit=limit,
            ttl_seconds=ttl_seconds,
        )
        if slot is None:
            raise ConcurrencyLimitExceededError(f"Tenant {organization_id} concurrency limit reached.")
        try:
            yield slot
        finally:
            self.release_sync(slot)

    # --------------------------------------------------------------------------
    # Asynchronous Operations (API / Async Calls / Integration Tests)
    # --------------------------------------------------------------------------

    async def acquire_async(
        self,
        organization_id: uuid.UUID,
        job_id: uuid.UUID,
        worker_id: str,
        limit: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
    ) -> Optional[TenantSlot]:
        effective_limit = limit if (limit is not None and limit > 0) else self._default_limit
        effective_ttl = ttl_seconds if (ttl_seconds is not None and ttl_seconds > 0) else self._default_ttl_seconds

        slot_token = f"slot-{uuid.uuid4().hex[:12]}"
        slot = TenantSlot(
            organization_id=organization_id,
            job_id=job_id,
            worker_id=worker_id,
            slot_token=slot_token,
            acquired_at=time.time(),
            ttl_seconds=effective_ttl,
        )

        now = time.time()
        expires_at = now + effective_ttl
        job_prefix = f"{job_id}:"

        try:
            client = core_async_redis.get_redis_client()
            res = await client.eval(
                _LUA_ACQUIRE,
                1,
                slot.redis_key,
                str(now),
                str(effective_limit),
                slot.member_key,
                str(expires_at),
                job_prefix,
            )
        except (ConnectionError, TimeoutError, RedisError, OSError) as e:
            logger.warning("Async Redis error during acquire for org %s: %s", organization_id, e)
            metrics_collector.inc_counter("scorva_redis_errors_total", labels={"operation": "acquire"})
            raise RedisUnavailableError(f"Redis unavailable during concurrency acquisition: {e}") from e

        if int(res) == 1:
            metrics_collector.inc_counter("scorva_tenant_concurrency_slots_acquired_total")
            metrics_collector.inc_gauge("scorva_tenant_concurrency_slots_active")
            return slot
        else:
            metrics_collector.inc_counter("scorva_tenant_concurrency_rejected_total")
            return None

    async def release_async(self, slot: TenantSlot) -> bool:
        try:
            client = core_async_redis.get_redis_client()
            res = await client.eval(
                _LUA_RELEASE,
                1,
                slot.redis_key,
                slot.member_key,
            )
            removed = int(res) > 0
            if removed:
                metrics_collector.dec_gauge("scorva_tenant_concurrency_slots_active")
            return removed
        except (ConnectionError, TimeoutError, RedisError, OSError) as e:
            logger.warning("Async Redis error during release for job %s: %s", slot.job_id, e)
            metrics_collector.inc_counter("scorva_redis_errors_total", labels={"operation": "release"})
            return False

    async def renew_async(self, slot: TenantSlot, ttl_seconds: Optional[int] = None) -> bool:
        effective_ttl = ttl_seconds if (ttl_seconds is not None and ttl_seconds > 0) else slot.ttl_seconds
        new_expires_at = time.time() + effective_ttl
        try:
            client = core_async_redis.get_redis_client()
            res = await client.eval(
                _LUA_RENEW,
                1,
                slot.redis_key,
                slot.member_key,
                str(new_expires_at),
            )
            return int(res) == 1
        except (ConnectionError, TimeoutError, RedisError, OSError) as e:
            logger.warning("Async Redis error during renew for job %s: %s", slot.job_id, e)
            metrics_collector.inc_counter("scorva_redis_errors_total", labels={"operation": "renew"})
            return False

    async def get_active_count_async(self, organization_id: uuid.UUID) -> int:
        key = f"scorva:eval:concurrency:{organization_id}"
        now = time.time()
        try:
            client = core_async_redis.get_redis_client()
            res = await client.eval(_LUA_PRUNE_AND_COUNT, 1, key, str(now))
            return int(res)
        except (ConnectionError, TimeoutError, RedisError, OSError) as e:
            logger.warning("Async Redis error getting count for org %s: %s", organization_id, e)
            metrics_collector.inc_counter("scorva_redis_errors_total", labels={"operation": "count"})
            raise RedisUnavailableError(f"Redis unavailable: {e}") from e

    @asynccontextmanager
    async def slot_scope_async(
        self,
        organization_id: uuid.UUID,
        job_id: uuid.UUID,
        worker_id: str,
        limit: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
    ) -> AsyncIterator[TenantSlot]:
        slot = await self.acquire_async(
            organization_id=organization_id,
            job_id=job_id,
            worker_id=worker_id,
            limit=limit,
            ttl_seconds=ttl_seconds,
        )
        if slot is None:
            raise ConcurrencyLimitExceededError(f"Tenant {organization_id} concurrency limit reached.")
        try:
            yield slot
        finally:
            await self.release_async(slot)


# Global default governor instance
concurrency_governor = TenantConcurrencyGovernor()

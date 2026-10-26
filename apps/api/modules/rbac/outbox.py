from datetime import datetime, timezone
import json
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.modules.rbac.models import AuthzInvalidationOutbox

logger = logging.getLogger("scorva.rbac.outbox")

# In-memory L1 cache for effective permissions (30s TTL bounded staleness)
_L1_AUTHZ_CACHE = {}


def purge_local_authz_cache() -> None:
    """Purges the in-process L1 authorization cache on reconnect or invalidation."""
    global _L1_AUTHZ_CACHE
    _L1_AUTHZ_CACHE.clear()
    logger.info("Purged in-memory L1 authorization cache.")


async def relay_authz_invalidation_outbox(
    db: AsyncSession,
    redis_client: Optional[object] = None,
    batch_size: int = 50,
) -> int:
    """
    Tails authz_invalidation_outbox and broadcasts events to Redis Pub/Sub.
    Marks records processed only after confirmed dispatch.
    Implements retry counter on transient dispatch failures.
    """
    stmt = (
        select(AuthzInvalidationOutbox)
        .where(
            AuthzInvalidationOutbox.processed_at.is_(None),
            AuthzInvalidationOutbox.retry_count < 5,
        )
        .order_by(AuthzInvalidationOutbox.id.asc())
        .limit(batch_size)
    )
    events = (await db.execute(stmt)).scalars().all()
    if not events:
        return 0

    processed_count = 0
    now_utc = datetime.now(timezone.utc)

    for event in events:
        payload = {
            "id": event.id,
            "event_type": event.event_type,
            "scope_type": event.scope_type,
            "scope_id": str(event.scope_id),
            "target_user_id": str(event.target_user_id) if event.target_user_id else None,
            "version": event.version,
            "created_at": event.created_at.isoformat() if event.created_at else now_utc.isoformat(),
        }

        try:
            if redis_client:
                # Publish event to channel
                await redis_client.publish("authz:invalidation", json.dumps(payload))

                # Evict specific user cached permissions in Redis if user targeted
                if event.target_user_id:
                    pattern = f"user_perms:{event.target_user_id}:*"
                    # Attempt key scan/deletion if supported
                    try:
                        keys = await redis_client.keys(pattern)
                        if keys:
                            await redis_client.delete(*keys)
                    except Exception as e:
                        logger.debug("Redis key eviction note: %s", e)

            # Evict local L1 memory cache
            purge_local_authz_cache()

            event.processed_at = now_utc
            processed_count += 1

        except Exception as exc:
            event.retry_count += 1
            logger.warning(
                "Failed to relay outbox event %s to Redis (attempt %s): %s",
                event.id,
                event.retry_count,
                exc,
            )

    await db.commit()
    return processed_count

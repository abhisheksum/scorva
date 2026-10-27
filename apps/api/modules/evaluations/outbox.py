from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.core.exceptions import AppException
from apps.api.core.metrics import metrics_collector
from apps.api.modules.audit.models import AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.evaluations.models import EvaluationJobOutbox


class OutboxStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    DEAD_LETTERED = "dead_lettered"


DEFAULT_LEASE_SECONDS = 30
DEFAULT_MAX_CLAIMS = 5


async def claim_outbox_batch(
    db: AsyncSession,
    relay_token: uuid.UUID,
    batch_size: int = 50,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    max_claims: int = DEFAULT_MAX_CLAIMS,
    organization_id: Optional[uuid.UUID] = None,
) -> List[EvaluationJobOutbox]:
    """
    Phase 1 Atomic Claim Transaction:
    Selects pending or expired processing rows using SELECT ... FOR UPDATE SKIP LOCKED.
    Atomically increments claim_count, updates status to processing, and installs relay lease.
    Zero network operations are performed within this transaction.
    """
    now = func.clock_timestamp()
    expiry_delta = func.make_interval(0, 0, 0, 0, 0, 0, lease_seconds)

    # 1. Subquery to lock candidate IDs with SKIP LOCKED
    candidate_stmt = (
        select(EvaluationJobOutbox.id)
        .where(
            (EvaluationJobOutbox.status == OutboxStatus.PENDING.value)
            | (
                (EvaluationJobOutbox.status == OutboxStatus.PROCESSING.value)
                & (EvaluationJobOutbox.relay_expires_at < now)
            )
        )
        .where(EvaluationJobOutbox.claim_count < max_claims)
        .where(EvaluationJobOutbox.dead_lettered_at.is_(None))
        .where(EvaluationJobOutbox.processed_at.is_(None))
    )
    if organization_id is not None:
        candidate_stmt = candidate_stmt.where(EvaluationJobOutbox.organization_id == organization_id)

    candidate_stmt = (
        candidate_stmt
        .order_by(EvaluationJobOutbox.id.asc())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )

    candidate_ids = (await db.execute(candidate_stmt)).scalars().all()
    if not candidate_ids:
        return []

    # 2. Update claim status on the locked rows
    update_stmt = (
        update(EvaluationJobOutbox)
        .where(EvaluationJobOutbox.id.in_(candidate_ids))
        .values(
            status=OutboxStatus.PROCESSING.value,
            relay_claim_token=relay_token,
            relay_claimed_at=now,
            relay_expires_at=now + expiry_delta,
            claim_count=EvaluationJobOutbox.claim_count + 1,
            retry_count=EvaluationJobOutbox.claim_count + 1,
        )
        .returning(EvaluationJobOutbox)
    )

    result = await db.execute(update_stmt)
    claimed_rows = list(result.scalars().all())
    await db.flush()
    return claimed_rows


async def settle_outbox_row(
    db: AsyncSession,
    outbox_id: int,
    relay_token: uuid.UUID,
) -> bool:
    """
    Phase 3 Conditional Settlement Transaction:
    Called upon confirmed Redis acknowledgment.
    Requires row to remain in 'processing' status, match relay_claim_token, and have processed_at IS NULL.
    Sets status = 'delivered', processed_at = clock_timestamp(), increments publish_attempts,
    and invalidates the relay lease token.
    """
    now = func.clock_timestamp()
    stmt = (
        update(EvaluationJobOutbox)
        .where(EvaluationJobOutbox.id == outbox_id)
        .where(EvaluationJobOutbox.relay_claim_token == relay_token)
        .where(EvaluationJobOutbox.status == OutboxStatus.PROCESSING.value)
        .where(EvaluationJobOutbox.processed_at.is_(None))
        .values(
            status=OutboxStatus.DELIVERED.value,
            processed_at=now,
            publish_attempts=EvaluationJobOutbox.publish_attempts + 1,
            relay_claim_token=None,
            relay_expires_at=None,
            last_error=None,
        )
    )
    res = await db.execute(stmt)
    await db.flush()
    if res.rowcount == 1:
        metrics_collector.inc_counter("scorva_outbox_operations_total", labels={"operation": "published"})
    return res.rowcount == 1


async def record_outbox_publish_error(
    db: AsyncSession,
    outbox_id: int,
    relay_token: uuid.UUID,
    error_message: str,
) -> bool:
    """
    Records an observed network publish failure without prematurely settling the row.
    Increments publish_attempts and records last_error if the token is still valid.
    """
    stmt = (
        update(EvaluationJobOutbox)
        .where(EvaluationJobOutbox.id == outbox_id)
        .where(EvaluationJobOutbox.relay_claim_token == relay_token)
        .where(EvaluationJobOutbox.status == OutboxStatus.PROCESSING.value)
        .values(
            last_error=error_message,
            publish_attempts=EvaluationJobOutbox.publish_attempts + 1,
        )
    )
    res = await db.execute(stmt)
    await db.flush()
    metrics_collector.inc_counter("scorva_outbox_operations_total", labels={"operation": "publish_failed"})
    return res.rowcount == 1


async def quarantine_exhausted_outbox_rows(
    db: AsyncSession,
    max_claims: int = DEFAULT_MAX_CLAIMS,
    actor_email: str = "system@scorva.local",
) -> List[EvaluationJobOutbox]:
    """
    Periodic Background Quarantine Sweep:
    Identifies rows in 'processing' whose lease has expired and that have reached or exceeded max_claims.
    Transitions them atomically to 'dead_lettered', clears claim tokens, and writes immutable AuditEvents.
    """
    now = func.clock_timestamp()

    # Query candidate IDs to quarantine
    select_stmt = (
        select(EvaluationJobOutbox)
        .where(EvaluationJobOutbox.status == OutboxStatus.PROCESSING.value)
        .where(EvaluationJobOutbox.claim_count >= max_claims)
        .where(EvaluationJobOutbox.relay_expires_at < now)
        .where(EvaluationJobOutbox.dead_lettered_at.is_(None))
        .with_for_update(skip_locked=True)
    )
    expired_rows = list((await db.execute(select_stmt)).scalars().all())
    if not expired_rows:
        return []

    quarantined = []
    metrics_collector.inc_counter("scorva_outbox_operations_total", amount=len(expired_rows), labels={"operation": "dead_lettered"})
    for row in expired_rows:
        reason = (
            "EXHAUSTED_BEFORE_PUBLISH"
            if row.publish_attempts == 0
            else "EXHAUSTED_DURING_PUBLISH_OR_SETTLEMENT"
        )
        row.status = OutboxStatus.DEAD_LETTERED.value
        row.dead_lettered_at = datetime.now(timezone.utc)
        row.dead_letter_reason = reason
        row.relay_claim_token = None
        row.relay_expires_at = None

        # Record immutable audit event in the SAME transaction
        await record_audit_event(
            db=db,
            action="outbox.quarantined",
            resource_type="evaluation_job_outbox",
            resource_id=str(row.id),
            outcome=AuditOutcome.FAILURE,
            organization_id=row.organization_id,
            actor_email=actor_email,
            reason=reason,
            diff_payload={
                "job_id": str(row.job_id),
                "claim_count": row.claim_count,
                "publish_attempts": row.publish_attempts,
                "dispatch_generation": row.dispatch_generation,
                "reason": reason,
            },
        )
        quarantined.append(row)

    await db.flush()
    return quarantined


async def replay_dead_lettered_outbox_row(
    db: AsyncSession,
    organization_id: uuid.UUID,
    outbox_id: int,
    actor_user_id: Optional[uuid.UUID] = None,
    actor_email: str = "operator@scorva.local",
    actor_role: str = "operator",
) -> EvaluationJobOutbox:
    """
    Authorized Operator Replay:
    Resets a dead-lettered outbox record to 'pending' with zeroed claim and publish counters.
    Scoped strictly by organization_id to enforce multi-tenant isolation.
    """
    stmt = (
        select(EvaluationJobOutbox)
        .where(EvaluationJobOutbox.id == outbox_id)
        .where(EvaluationJobOutbox.organization_id == organization_id)
        .with_for_update()
    )
    res = await db.execute(stmt)
    row = res.scalar_one_or_none()

    if not row:
        raise AppException(
            status_code=404,
            code="OUTBOX_RECORD_NOT_FOUND",
            message=f"Outbox record {outbox_id} not found in this organization.",
        )

    if row.status != OutboxStatus.DEAD_LETTERED.value:
        raise AppException(
            status_code=409,
            code="OUTBOX_NOT_DEAD_LETTERED",
            message=f"Outbox record {outbox_id} is in status '{row.status}', not dead_lettered.",
        )

    row.status = OutboxStatus.PENDING.value
    row.claim_count = 0
    row.retry_count = 0
    row.publish_attempts = 0
    row.dead_lettered_at = None
    row.dead_letter_reason = None
    row.last_error = None
    row.relay_claim_token = None
    row.relay_expires_at = None

    await record_audit_event(
        db=db,
        action="outbox.replayed",
        resource_type="evaluation_job_outbox",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        organization_id=organization_id,
        diff_payload={"job_id": str(row.job_id), "outbox_id": row.id},
    )

    await db.flush()
    return row


async def get_outbox_entry_by_id(
    db: AsyncSession,
    outbox_id: int,
    organization_id: Optional[uuid.UUID] = None,
) -> Optional[EvaluationJobOutbox]:
    """Retrieve an outbox entry optionally scoped to organization."""
    stmt = select(EvaluationJobOutbox).where(EvaluationJobOutbox.id == outbox_id)
    if organization_id is not None:
        stmt = stmt.where(EvaluationJobOutbox.organization_id == organization_id)
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


async def get_outbox_entries_for_job(
    db: AsyncSession,
    job_id: uuid.UUID,
    organization_id: Optional[uuid.UUID] = None,
) -> List[EvaluationJobOutbox]:
    """Retrieve all outbox entries for a specific evaluation job in generation order."""
    stmt = (
        select(EvaluationJobOutbox)
        .where(EvaluationJobOutbox.job_id == job_id)
        .order_by(EvaluationJobOutbox.dispatch_generation.asc(), EvaluationJobOutbox.id.asc())
    )
    if organization_id is not None:
        stmt = stmt.where(EvaluationJobOutbox.organization_id == organization_id)
    res = await db.execute(stmt)
    return list(res.scalars().all())

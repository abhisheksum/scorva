from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import random
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from apps.api.core.metrics import metrics_collector
from apps.api.modules.audit.models import AuditEvent, AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.evaluations.models import EvaluationJob, EvaluationJobOutbox
from apps.api.modules.evaluations.outbox import OutboxStatus
from apps.api.workers.celery_app import celery_app
from apps.api.workers.database import worker_session_scope

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReapedJobResult:
    job_id: uuid.UUID
    action: str  # "requeued", "exhausted", "cancelled", "skipped"
    attempts_count: int
    lock_version: int
    backoff_seconds: float = 0.0
    outbox_id: Optional[int] = None
    error_code: Optional[str] = None


@dataclass(frozen=True)
class ReaperBatchReport:
    total_candidates: int
    requeued_count: int
    exhausted_count: int
    cancelled_count: int
    skipped_count: int
    results: List[ReapedJobResult] = field(default_factory=list)


def calculate_exponential_backoff(
    attempt: int,
    base_seconds: float = 10.0,
    max_seconds: float = 300.0,
    jitter: bool = True,
) -> float:
    """
    Computes bounded exponential backoff with proportional jitter for retry scheduling:
    delay = min(max_seconds, base_seconds * 2^(attempts_count - 1)) + jitter
    """
    if base_seconds <= 0:
        return 0.0

    exp_delay = base_seconds * (2 ** max(0, attempt - 1))
    delay = min(exp_delay, max_seconds)

    if jitter and delay > 0:
        # Full/proportional jitter bounded between 0.1s and 2.0s (or 20% of delay)
        jitter_amount = random.uniform(0.1, min(2.0, delay * 0.2))
        delay += jitter_amount

    return round(delay, 2)


def reap_stalled_evaluation_jobs_sync(
    batch_size: int = 50,
    base_backoff_seconds: float = 10.0,
    max_backoff_seconds: float = 300.0,
    jitter: bool = True,
    organization_id: Optional[uuid.UUID] = None,
    job_id: Optional[uuid.UUID] = None,
) -> ReaperBatchReport:
    """
    Subsystem C Sub-Milestone 5.4: Synchronous Expired-Job Reaper Engine.
    Executes within a dedicated short-lived worker database session:

    1. Finds candidate running jobs whose leases expired according to PostgreSQL clock_timestamp().
    2. Acquires row locks using SELECT ... FOR UPDATE SKIP LOCKED to guarantee safe concurrent sweeps.
    3. Within the exclusive row lock, rechecks eligibility and classifies jobs into:
       - Cancelled: If cancellation_requested is True -> terminal 'cancelled' (does not requeue).
       - Exhausted: If attempts_count >= max_attempts -> terminal 'failed' with WORKER_LEASE_TIMEOUT_EXHAUSTED.
       - Retryable: If attempts_count < max_attempts -> requeued with exponential backoff & durable outbox.
    4. Enforces fencing by clearing claim_token and incrementing lock_version on every state mutation.
    5. Fails closed and preserves audit integrity for every reaped record.
    """
    results: List[ReapedJobResult] = []
    requeued_count = 0
    exhausted_count = 0
    cancelled_count = 0
    skipped_count = 0

    with worker_session_scope() as session:
        # 1. Lock expired candidates using SKIP LOCKED
        sql_candidates = text("""
            SELECT id, organization_id, attempts_count, max_attempts,
                   cancellation_requested, lock_version, dispatch_generation
            FROM evaluation_jobs
            WHERE status = 'running'
              AND lease_expires_at < clock_timestamp()
              AND (CAST(:org_id AS uuid) IS NULL OR organization_id = CAST(:org_id AS uuid))
              AND (CAST(:target_job_id AS uuid) IS NULL OR id = CAST(:target_job_id AS uuid))
            ORDER BY lease_expires_at ASC
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED;
        """)

        candidates = session.execute(sql_candidates, {
            "batch_size": batch_size,
            "org_id": organization_id,
            "target_job_id": job_id,
        }).fetchall()
        total_candidates = len(candidates)
        metrics_collector.inc_counter("scorva_reaper_sweeps_total")

        if not candidates:
            return ReaperBatchReport(
                total_candidates=0,
                requeued_count=0,
                exhausted_count=0,
                cancelled_count=0,
                skipped_count=0,
                results=[],
            )

        logger.info("Reaper: Processing %d expired candidate jobs.", total_candidates)

        for cand in candidates:
            job_id = cand.id
            org_id = cand.organization_id
            attempts_count = cand.attempts_count
            max_attempts = cand.max_attempts
            cancellation_requested = cand.cancellation_requested
            current_lock_version = cand.lock_version
            dispatch_gen = cand.dispatch_generation

            # Case A: Cooperative Cancellation requested before/during lease expiry
            if cancellation_requested:
                sql_cancel = text("""
                    UPDATE evaluation_jobs
                    SET status = 'cancelled',
                        completed_at = clock_timestamp(),
                        claim_token = NULL,
                        lease_expires_at = NULL,
                        lock_version = lock_version + 1,
                        error_code = 'CANCELLED_AFTER_LEASE_EXPIRY',
                        error_message = 'Job was cancelled and worker lease expired.'
                    WHERE id = :job_id
                      AND status = 'running'
                      AND lock_version = :lock_version;
                """)
                res_upd = session.execute(sql_cancel, {
                    "job_id": job_id,
                    "lock_version": current_lock_version,
                })
                if res_upd.rowcount != 1:
                    logger.warning("Reaper: Race detected on cancelled job %s. Skipping.", job_id)
                    skipped_count += 1
                    metrics_collector.inc_counter("scorva_reaper_recovered_jobs_total", labels={"action": "skipped"})
                    results.append(ReapedJobResult(job_id=job_id, action="skipped", attempts_count=attempts_count, lock_version=current_lock_version))
                    continue

                # Dead-letter any active outbox entries
                session.execute(text("""
                    UPDATE evaluation_job_outbox
                    SET status = 'dead_lettered',
                        dead_letter_reason = 'JOB_CANCELLED_AFTER_LEASE_EXPIRY',
                        dead_lettered_at = clock_timestamp()
                    WHERE job_id = :job_id
                      AND status IN ('pending', 'processing');
                """), {"job_id": job_id})

                # Insert audit event
                audit_ev = AuditEvent(
                    id=uuid.uuid4(),
                    timestamp=datetime.now(timezone.utc),
                    actor_user_id=None,
                    actor_email="system@scorva.local",
                    actor_role="system",
                    action="evaluation.cancelled",
                    resource_type="evaluation_job",
                    resource_id=str(job_id),
                    organization_id=org_id,
                    outcome=AuditOutcome.SUCCESS,
                    diff_payload={
                        "reason": "CANCELLED_AFTER_LEASE_EXPIRY",
                        "previous_status": "running",
                        "new_status": "cancelled",
                        "lock_version": current_lock_version + 1,
                    },
                    ip_address="127.0.0.1",
                    user_agent="Scorva-Reaper/1.0",
                    correlation_id=uuid.uuid4(),
                )
                session.add(audit_ev)

                cancelled_count += 1
                metrics_collector.inc_counter("scorva_reaper_recovered_jobs_total", labels={"action": "cancelled"})
                results.append(ReapedJobResult(
                    job_id=job_id,
                    action="cancelled",
                    attempts_count=attempts_count,
                    lock_version=current_lock_version + 1,
                    error_code="CANCELLED_AFTER_LEASE_EXPIRY",
                ))
                continue

            # Case B: Retry budget exhausted
            if attempts_count >= max_attempts:
                sql_exhaust = text("""
                    UPDATE evaluation_jobs
                    SET status = 'failed',
                        completed_at = clock_timestamp(),
                        claim_token = NULL,
                        lease_expires_at = NULL,
                        lock_version = lock_version + 1,
                        error_code = 'WORKER_LEASE_TIMEOUT_EXHAUSTED',
                        error_message = 'Worker lease expired and retry attempts budget is exhausted.'
                    WHERE id = :job_id
                      AND status = 'running'
                      AND lock_version = :lock_version;
                """)
                res_upd = session.execute(sql_exhaust, {
                    "job_id": job_id,
                    "lock_version": current_lock_version,
                })
                if res_upd.rowcount != 1:
                    logger.warning("Reaper: Race detected on exhausted job %s. Skipping.", job_id)
                    skipped_count += 1
                    metrics_collector.inc_counter("scorva_reaper_recovered_jobs_total", labels={"action": "skipped"})
                    results.append(ReapedJobResult(job_id=job_id, action="skipped", attempts_count=attempts_count, lock_version=current_lock_version))
                    continue

                session.execute(text("""
                    UPDATE evaluation_job_outbox
                    SET status = 'dead_lettered',
                        dead_letter_reason = 'RETRY_BUDGET_EXHAUSTED',
                        dead_lettered_at = clock_timestamp()
                    WHERE job_id = :job_id
                      AND status IN ('pending', 'processing');
                """), {"job_id": job_id})

                audit_ev = AuditEvent(
                    id=uuid.uuid4(),
                    timestamp=datetime.now(timezone.utc),
                    actor_user_id=None,
                    actor_email="system@scorva.local",
                    actor_role="system",
                    action="evaluation.reaped_exhausted",
                    resource_type="evaluation_job",
                    resource_id=str(job_id),
                    organization_id=org_id,
                    outcome=AuditOutcome.FAILURE,
                    diff_payload={
                        "reason": "WORKER_LEASE_TIMEOUT_EXHAUSTED",
                        "attempts_count": attempts_count,
                        "max_attempts": max_attempts,
                        "lock_version": current_lock_version + 1,
                    },
                    ip_address="127.0.0.1",
                    user_agent="Scorva-Reaper/1.0",
                    correlation_id=uuid.uuid4(),
                )
                session.add(audit_ev)

                exhausted_count += 1
                metrics_collector.inc_counter("scorva_reaper_recovered_jobs_total", labels={"action": "exhausted"})
                metrics_collector.inc_counter("scorva_retry_exhausted_total")
                results.append(ReapedJobResult(
                    job_id=job_id,
                    action="exhausted",
                    attempts_count=attempts_count,
                    lock_version=current_lock_version + 1,
                    error_code="WORKER_LEASE_TIMEOUT_EXHAUSTED",
                ))
                continue

            # Case C: Eligible for retry attempt
            backoff_seconds = calculate_exponential_backoff(
                attempt=attempts_count,
                base_seconds=base_backoff_seconds,
                max_seconds=max_backoff_seconds,
                jitter=jitter,
            )
            new_dispatch_gen = dispatch_gen + 1

            sql_requeue = text("""
                UPDATE evaluation_jobs
                SET status = 'queued',
                    claim_token = NULL,
                    last_heartbeat_at = NULL,
                    lease_expires_at = CASE
                        WHEN :backoff_secs > 0 THEN clock_timestamp() + (:backoff_secs * interval '1 second')
                        ELSE NULL
                    END,
                    lock_version = lock_version + 1,
                    dispatch_generation = :new_dispatch_gen,
                    current_stage = NULL,
                    error_code = 'LEASE_TIMEOUT_RETRY_SCHEDULED',
                    error_message = 'Previous worker lease expired. Retry scheduled.'
                WHERE id = :job_id
                  AND status = 'running'
                  AND lock_version = :lock_version;
            """)

            res_upd = session.execute(sql_requeue, {
                "job_id": job_id,
                "lock_version": current_lock_version,
                "backoff_secs": backoff_seconds,
                "new_dispatch_gen": new_dispatch_gen,
            })
            if res_upd.rowcount != 1:
                logger.warning("Reaper: Race detected on retryable job %s. Skipping.", job_id)
                skipped_count += 1
                results.append(ReapedJobResult(job_id=job_id, action="skipped", attempts_count=attempts_count, lock_version=current_lock_version))
                continue

            # Supersede any previous active outbox entry to prevent unique constraint collision
            session.execute(text("""
                UPDATE evaluation_job_outbox
                SET status = 'dead_lettered',
                    dead_letter_reason = 'SUPERSEDED_BY_RETRY',
                    dead_lettered_at = clock_timestamp()
                WHERE job_id = :job_id
                  AND status IN ('pending', 'processing');
            """), {"job_id": job_id})

            # Atomically insert fresh outbox record with scheduled backoff in the same transaction
            outbox_status = "processing" if backoff_seconds > 0 else "pending"
            sql_insert_outbox = text("""
                INSERT INTO evaluation_job_outbox (
                    job_id, organization_id, queue_name, routing_key, payload,
                    status, relay_expires_at, claim_count, publish_attempts,
                    dispatch_generation, created_at
                ) VALUES (
                    :job_id, :organization_id, 'evaluations.default', 'evaluations.default',
                    :payload, :outbox_status,
                    CASE WHEN :backoff_secs > 0 THEN clock_timestamp() + (:backoff_secs * interval '1 second') ELSE NULL END,
                    0, 0, :new_dispatch_gen, clock_timestamp()
                )
                RETURNING id;
            """)

            res_outbox = session.execute(sql_insert_outbox, {
                "job_id": job_id,
                "organization_id": org_id,
                "payload": json.dumps({"job_id": str(job_id)}),
                "outbox_status": outbox_status,
                "backoff_secs": backoff_seconds,
                "new_dispatch_gen": new_dispatch_gen,
            })
            new_outbox_id = res_outbox.fetchone()[0]

            # Insert immutable audit event
            audit_ev = AuditEvent(
                id=uuid.uuid4(),
                timestamp=datetime.now(timezone.utc),
                actor_user_id=None,
                actor_email="system@scorva.local",
                actor_role="system",
                action="evaluation.reaped_retry",
                resource_type="evaluation_job",
                resource_id=str(job_id),
                organization_id=org_id,
                outcome=AuditOutcome.SUCCESS,
                diff_payload={
                    "previous_attempts_count": attempts_count,
                    "max_attempts": max_attempts,
                    "backoff_seconds": backoff_seconds,
                    "new_dispatch_generation": new_dispatch_gen,
                    "new_outbox_id": new_outbox_id,
                    "lock_version": current_lock_version + 1,
                },
                ip_address="127.0.0.1",
                user_agent="Scorva-Reaper/1.0",
                correlation_id=uuid.uuid4(),
            )
            session.add(audit_ev)

            requeued_count += 1
            metrics_collector.inc_counter("scorva_reaper_recovered_jobs_total", labels={"action": "requeued"})
            results.append(ReapedJobResult(
                job_id=job_id,
                action="requeued",
                attempts_count=attempts_count,
                lock_version=current_lock_version + 1,
                backoff_seconds=backoff_seconds,
                outbox_id=new_outbox_id,
            ))

        session.flush()

    return ReaperBatchReport(
        total_candidates=total_candidates,
        requeued_count=requeued_count,
        exhausted_count=exhausted_count,
        cancelled_count=cancelled_count,
        skipped_count=skipped_count,
        results=results,
    )


async def reap_stalled_evaluation_jobs_async(
    db: AsyncSession,
    batch_size: int = 50,
    base_backoff_seconds: float = 10.0,
    max_backoff_seconds: float = 300.0,
    jitter: bool = True,
    organization_id: Optional[uuid.UUID] = None,
    job_id: Optional[uuid.UUID] = None,
) -> ReaperBatchReport:
    """Async equivalent of reap_stalled_evaluation_jobs_sync for async callers and integration tests."""
    results: List[ReapedJobResult] = []
    requeued_count = 0
    exhausted_count = 0
    cancelled_count = 0
    skipped_count = 0

    sql_candidates = text("""
        SELECT id, organization_id, attempts_count, max_attempts,
               cancellation_requested, lock_version, dispatch_generation
        FROM evaluation_jobs
        WHERE status = 'running'
          AND lease_expires_at < clock_timestamp()
          AND (CAST(:org_id AS uuid) IS NULL OR organization_id = CAST(:org_id AS uuid))
          AND (CAST(:target_job_id AS uuid) IS NULL OR id = CAST(:target_job_id AS uuid))
        ORDER BY lease_expires_at ASC
        LIMIT :batch_size
        FOR UPDATE SKIP LOCKED;
    """)

    res = await db.execute(sql_candidates, {
        "batch_size": batch_size,
        "org_id": organization_id,
        "target_job_id": job_id,
    })
    candidates = res.fetchall()
    total_candidates = len(candidates)
    metrics_collector.inc_counter("scorva_reaper_sweeps_total")

    if not candidates:
        return ReaperBatchReport(
            total_candidates=0,
            requeued_count=0,
            exhausted_count=0,
            cancelled_count=0,
            skipped_count=0,
            results=[],
        )

    for cand in candidates:
        job_id = cand.id
        org_id = cand.organization_id
        attempts_count = cand.attempts_count
        max_attempts = cand.max_attempts
        cancellation_requested = cand.cancellation_requested
        current_lock_version = cand.lock_version
        dispatch_gen = cand.dispatch_generation

        if cancellation_requested:
            sql_cancel = text("""
                UPDATE evaluation_jobs
                SET status = 'cancelled',
                    completed_at = clock_timestamp(),
                    claim_token = NULL,
                    lease_expires_at = NULL,
                    lock_version = lock_version + 1,
                    error_code = 'CANCELLED_AFTER_LEASE_EXPIRY',
                    error_message = 'Job was cancelled and worker lease expired.'
                WHERE id = :job_id
                  AND status = 'running'
                  AND lock_version = :lock_version;
            """)
            res_upd = await db.execute(sql_cancel, {
                "job_id": job_id,
                "lock_version": current_lock_version,
            })
            if res_upd.rowcount != 1:
                skipped_count += 1
                metrics_collector.inc_counter("scorva_reaper_recovered_jobs_total", labels={"action": "skipped"})
                results.append(ReapedJobResult(job_id=job_id, action="skipped", attempts_count=attempts_count, lock_version=current_lock_version))
                continue

            await db.execute(text("""
                UPDATE evaluation_job_outbox
                SET status = 'dead_lettered',
                    dead_letter_reason = 'JOB_CANCELLED_AFTER_LEASE_EXPIRY',
                    dead_lettered_at = clock_timestamp()
                WHERE job_id = :job_id
                  AND status IN ('pending', 'processing');
            """), {"job_id": job_id})

            audit_ev = AuditEvent(
                id=uuid.uuid4(),
                timestamp=datetime.now(timezone.utc),
                actor_user_id=None,
                actor_email="system@scorva.local",
                actor_role="system",
                action="evaluation.cancelled",
                resource_type="evaluation_job",
                resource_id=str(job_id),
                organization_id=org_id,
                outcome=AuditOutcome.SUCCESS,
                diff_payload={
                    "reason": "CANCELLED_AFTER_LEASE_EXPIRY",
                    "previous_status": "running",
                    "new_status": "cancelled",
                    "lock_version": current_lock_version + 1,
                },
                ip_address="127.0.0.1",
                user_agent="Scorva-Reaper/1.0",
                correlation_id=uuid.uuid4(),
            )
            db.add(audit_ev)

            cancelled_count += 1
            metrics_collector.inc_counter("scorva_reaper_recovered_jobs_total", labels={"action": "cancelled"})
            results.append(ReapedJobResult(
                job_id=job_id,
                action="cancelled",
                attempts_count=attempts_count,
                lock_version=current_lock_version + 1,
                error_code="CANCELLED_AFTER_LEASE_EXPIRY",
            ))
            continue

        if attempts_count >= max_attempts:
            sql_exhaust = text("""
                UPDATE evaluation_jobs
                SET status = 'failed',
                    completed_at = clock_timestamp(),
                    claim_token = NULL,
                    lease_expires_at = NULL,
                    lock_version = lock_version + 1,
                    error_code = 'WORKER_LEASE_TIMEOUT_EXHAUSTED',
                    error_message = 'Worker lease expired and retry attempts budget is exhausted.'
                WHERE id = :job_id
                  AND status = 'running'
                  AND lock_version = :lock_version;
            """)
            res_upd = await db.execute(sql_exhaust, {
                "job_id": job_id,
                "lock_version": current_lock_version,
            })
            if res_upd.rowcount != 1:
                skipped_count += 1
                metrics_collector.inc_counter("scorva_reaper_recovered_jobs_total", labels={"action": "skipped"})
                results.append(ReapedJobResult(job_id=job_id, action="skipped", attempts_count=attempts_count, lock_version=current_lock_version))
                continue

            await db.execute(text("""
                UPDATE evaluation_job_outbox
                SET status = 'dead_lettered',
                    dead_letter_reason = 'RETRY_BUDGET_EXHAUSTED',
                    dead_lettered_at = clock_timestamp()
                WHERE job_id = :job_id
                  AND status IN ('pending', 'processing');
            """), {"job_id": job_id})

            audit_ev = AuditEvent(
                id=uuid.uuid4(),
                timestamp=datetime.now(timezone.utc),
                actor_user_id=None,
                actor_email="system@scorva.local",
                actor_role="system",
                action="evaluation.reaped_exhausted",
                resource_type="evaluation_job",
                resource_id=str(job_id),
                organization_id=org_id,
                outcome=AuditOutcome.FAILURE,
                diff_payload={
                    "reason": "WORKER_LEASE_TIMEOUT_EXHAUSTED",
                    "attempts_count": attempts_count,
                    "max_attempts": max_attempts,
                    "lock_version": current_lock_version + 1,
                },
                ip_address="127.0.0.1",
                user_agent="Scorva-Reaper/1.0",
                correlation_id=uuid.uuid4(),
            )
            db.add(audit_ev)

            exhausted_count += 1
            metrics_collector.inc_counter("scorva_reaper_recovered_jobs_total", labels={"action": "exhausted"})
            metrics_collector.inc_counter("scorva_retry_exhausted_total")
            results.append(ReapedJobResult(
                job_id=job_id,
                action="exhausted",
                attempts_count=attempts_count,
                lock_version=current_lock_version + 1,
                error_code="WORKER_LEASE_TIMEOUT_EXHAUSTED",
            ))
            continue

        # Retryable attempt
        backoff_seconds = calculate_exponential_backoff(
            attempt=attempts_count,
            base_seconds=base_backoff_seconds,
            max_seconds=max_backoff_seconds,
            jitter=jitter,
        )
        new_dispatch_gen = dispatch_gen + 1

        sql_requeue = text("""
            UPDATE evaluation_jobs
            SET status = 'queued',
                claim_token = NULL,
                last_heartbeat_at = NULL,
                lease_expires_at = CASE
                    WHEN :backoff_secs > 0 THEN clock_timestamp() + (:backoff_secs * interval '1 second')
                    ELSE NULL
                END,
                lock_version = lock_version + 1,
                dispatch_generation = :new_dispatch_gen,
                current_stage = NULL,
                error_code = 'LEASE_TIMEOUT_RETRY_SCHEDULED',
                error_message = 'Previous worker lease expired. Retry scheduled.'
            WHERE id = :job_id
              AND status = 'running'
              AND lock_version = :lock_version;
        """)

        res_upd = await db.execute(sql_requeue, {
            "job_id": job_id,
            "lock_version": current_lock_version,
            "backoff_secs": backoff_seconds,
            "new_dispatch_gen": new_dispatch_gen,
        })
        if res_upd.rowcount != 1:
            skipped_count += 1
            results.append(ReapedJobResult(job_id=job_id, action="skipped", attempts_count=attempts_count, lock_version=current_lock_version))
            continue

        await db.execute(text("""
            UPDATE evaluation_job_outbox
            SET status = 'dead_lettered',
                dead_letter_reason = 'SUPERSEDED_BY_RETRY',
                dead_lettered_at = clock_timestamp()
            WHERE job_id = :job_id
              AND status IN ('pending', 'processing');
        """), {"job_id": job_id})

        outbox_status = "processing" if backoff_seconds > 0 else "pending"
        sql_insert_outbox = text("""
            INSERT INTO evaluation_job_outbox (
                job_id, organization_id, queue_name, routing_key, payload,
                status, relay_expires_at, claim_count, publish_attempts,
                dispatch_generation, created_at
            ) VALUES (
                :job_id, :organization_id, 'evaluations.default', 'evaluations.default',
                :payload, :outbox_status,
                CASE WHEN :backoff_secs > 0 THEN clock_timestamp() + (:backoff_secs * interval '1 second') ELSE NULL END,
                0, 0, :new_dispatch_gen, clock_timestamp()
            )
            RETURNING id;
        """)

        res_outbox = await db.execute(sql_insert_outbox, {
            "job_id": job_id,
            "organization_id": org_id,
            "payload": json.dumps({"job_id": str(job_id)}),
            "outbox_status": outbox_status,
            "backoff_secs": backoff_seconds,
            "new_dispatch_gen": new_dispatch_gen,
        })
        new_outbox_id = res_outbox.fetchone()[0]

        audit_ev = AuditEvent(
            id=uuid.uuid4(),
            timestamp=datetime.now(timezone.utc),
            actor_user_id=None,
            actor_email="system@scorva.local",
            actor_role="system",
            action="evaluation.reaped_retry",
            resource_type="evaluation_job",
            resource_id=str(job_id),
            organization_id=org_id,
            outcome=AuditOutcome.SUCCESS,
            diff_payload={
                "previous_attempts_count": attempts_count,
                "max_attempts": max_attempts,
                "backoff_seconds": backoff_seconds,
                "new_dispatch_generation": new_dispatch_gen,
                "new_outbox_id": new_outbox_id,
                "lock_version": current_lock_version + 1,
            },
            ip_address="127.0.0.1",
            user_agent="Scorva-Reaper/1.0",
            correlation_id=uuid.uuid4(),
        )
        db.add(audit_ev)

        requeued_count += 1
        metrics_collector.inc_counter("scorva_reaper_recovered_jobs_total", labels={"action": "requeued"})
        results.append(ReapedJobResult(
            job_id=job_id,
            action="requeued",
            attempts_count=attempts_count,
            lock_version=current_lock_version + 1,
            backoff_seconds=backoff_seconds,
            outbox_id=new_outbox_id,
        ))

    await db.flush()

    return ReaperBatchReport(
        total_candidates=total_candidates,
        requeued_count=requeued_count,
        exhausted_count=exhausted_count,
        cancelled_count=cancelled_count,
        skipped_count=skipped_count,
        results=results,
    )


@celery_app.task(
    name="apps.api.workers.reaper.reap_stalled_evaluation_jobs_task",
    acks_late=True,
    max_retries=0,
)
def reap_stalled_evaluation_jobs_task(batch_size: int = 50) -> Dict[str, Any]:
    """
    Subsystem C Sub-Milestone 5.4: Celery Beat periodic task for reaping stalled evaluation jobs.
    Runs periodically (e.g. every 15s) to recover crashed/abandoned workers safely.
    """
    report = reap_stalled_evaluation_jobs_sync(batch_size=batch_size)
    return {
        "total_candidates": report.total_candidates,
        "requeued_count": report.requeued_count,
        "exhausted_count": report.exhausted_count,
        "cancelled_count": report.cancelled_count,
        "skipped_count": report.skipped_count,
    }

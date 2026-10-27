from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Optional
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class LeaseManagerError(Exception):
    """Base exception for lease management errors."""
    pass


class StaleLeaseError(LeaseManagerError):
    """Raised when worker detects its lease expired or fencing token was revoked."""
    pass


class JobCancelledError(LeaseManagerError):
    """Raised when cooperative cancellation was requested for the job."""
    pass


@dataclass(frozen=True)
class WorkerClaim:
    """Represents an atomically established worker execution lease."""
    job_id: uuid.UUID
    organization_id: uuid.UUID
    hackathon_id: uuid.UUID
    submission_id: uuid.UUID
    snapshot_id: uuid.UUID
    rubric_version_id: uuid.UUID
    claim_token: str
    lock_version: int
    attempts_count: int
    max_attempts: int
    lease_expires_at: datetime
    worker_id: str


@dataclass(frozen=True)
class HeartbeatResult:
    """Outcome of an atomic heartbeat renewal operation."""
    success: bool
    lock_version: int
    lease_expires_at: Optional[datetime] = None
    cancellation_requested: bool = False
    error_code: Optional[str] = None


class WorkerLeaseManager:
    """
    Subsystem C Sub-Milestone 5.2:
    PostgreSQL-backed distributed worker lease manager and monotonic fencing protocol.
    Guarantees mutual exclusion and prevents stale worker writes using database-authoritative time.
    """

    @staticmethod
    def generate_claim_token(worker_id: str) -> str:
        """Generates a unique claim token tied to worker identity (<= 64 chars)."""
        clean_worker = worker_id.replace(":", "_")[:24]
        unique_suffix = uuid.uuid4().hex[:32]
        return f"{clean_worker}:{unique_suffix}"

    @classmethod
    def claim_job_sync(
        cls,
        db: Session,
        job_id: uuid.UUID,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> Optional[WorkerClaim]:
        """
        Synchronous Atomic Job Claim:
        1. Confirms the job is in 'queued' status, cancellation_requested is false,
           and attempts_count < max_attempts.
        2. Transitions status to 'running'.
        3. Installs unique claim_token, increments lock_version and attempts_count.
        4. Sets lease_expires_at, started_at, and last_heartbeat_at using PostgreSQL server clock.
        Returns WorkerClaim on success, or None if the job is not eligible (duplicate delivery harmless).
        """
        claim_token = cls.generate_claim_token(worker_id)
        sql = text("""
            UPDATE evaluation_jobs
            SET status = 'running',
                claim_token = :claim_token,
                lock_version = lock_version + 1,
                attempts_count = attempts_count + 1,
                started_at = clock_timestamp(),
                last_heartbeat_at = clock_timestamp(),
                lease_expires_at = clock_timestamp() + (:lease_seconds * interval '1 second')
            WHERE id = :job_id
              AND status = 'queued'
              AND cancellation_requested = false
              AND attempts_count < max_attempts
              AND (lease_expires_at IS NULL OR lease_expires_at <= clock_timestamp())
            RETURNING id, organization_id, hackathon_id, submission_id, snapshot_id,
                      rubric_version_id, status, lock_version, claim_token,
                      attempts_count, max_attempts, lease_expires_at, cancellation_requested;
        """)

        result = db.execute(sql, {
            "job_id": job_id,
            "claim_token": claim_token,
            "lease_seconds": lease_seconds,
        })
        row = result.fetchone()
        if not row:
            return None

        return WorkerClaim(
            job_id=row.id,
            organization_id=row.organization_id,
            hackathon_id=row.hackathon_id,
            submission_id=row.submission_id,
            snapshot_id=row.snapshot_id,
            rubric_version_id=row.rubric_version_id,
            claim_token=row.claim_token,
            lock_version=row.lock_version,
            attempts_count=row.attempts_count,
            max_attempts=row.max_attempts,
            lease_expires_at=row.lease_expires_at,
            worker_id=worker_id,
        )

    @classmethod
    async def claim_job_async(
        cls,
        db: AsyncSession,
        job_id: uuid.UUID,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> Optional[WorkerClaim]:
        """Async equivalent of claim_job_sync for async callers and integration tests."""
        claim_token = cls.generate_claim_token(worker_id)
        sql = text("""
            UPDATE evaluation_jobs
            SET status = 'running',
                claim_token = :claim_token,
                lock_version = lock_version + 1,
                attempts_count = attempts_count + 1,
                started_at = clock_timestamp(),
                last_heartbeat_at = clock_timestamp(),
                lease_expires_at = clock_timestamp() + (:lease_seconds * interval '1 second')
            WHERE id = :job_id
              AND status = 'queued'
              AND cancellation_requested = false
              AND attempts_count < max_attempts
              AND (lease_expires_at IS NULL OR lease_expires_at <= clock_timestamp())
            RETURNING id, organization_id, hackathon_id, submission_id, snapshot_id,
                      rubric_version_id, status, lock_version, claim_token,
                      attempts_count, max_attempts, lease_expires_at, cancellation_requested;
        """)

        result = await db.execute(sql, {
            "job_id": job_id,
            "claim_token": claim_token,
            "lease_seconds": lease_seconds,
        })
        row = result.fetchone()
        if not row:
            return None

        return WorkerClaim(
            job_id=row.id,
            organization_id=row.organization_id,
            hackathon_id=row.hackathon_id,
            submission_id=row.submission_id,
            snapshot_id=row.snapshot_id,
            rubric_version_id=row.rubric_version_id,
            claim_token=row.claim_token,
            lock_version=row.lock_version,
            attempts_count=row.attempts_count,
            max_attempts=row.max_attempts,
            lease_expires_at=row.lease_expires_at,
            worker_id=worker_id,
        )

    @classmethod
    def renew_lease_sync(
        cls,
        db: Session,
        job_id: uuid.UUID,
        claim_token: str,
        lock_version: int,
        lease_seconds: int = 60,
    ) -> HeartbeatResult:
        """
        Synchronous Atomic Lease Renewal / Heartbeat:
        1. Requires status = 'running', claim_token = :claim_token, lock_version = :lock_version.
        2. Requires lease_expires_at > clock_timestamp() (rejects already-expired leases).
        3. Updates last_heartbeat_at and advances lease_expires_at using PostgreSQL server clock.
        4. Detects cooperative cancellation flag (cancellation_requested).
        """
        sql_renew = text("""
            UPDATE evaluation_jobs
            SET last_heartbeat_at = clock_timestamp(),
                lease_expires_at = clock_timestamp() + (:lease_seconds * interval '1 second')
            WHERE id = :job_id
              AND status = 'running'
              AND claim_token = :claim_token
              AND lock_version = :lock_version
              AND lease_expires_at > clock_timestamp()
            RETURNING id, lock_version, lease_expires_at, cancellation_requested;
        """)

        res = db.execute(sql_renew, {
            "job_id": job_id,
            "claim_token": claim_token,
            "lock_version": lock_version,
            "lease_seconds": lease_seconds,
        })
        row = res.fetchone()
        if row:
            return HeartbeatResult(
                success=True,
                lock_version=row.lock_version,
                lease_expires_at=row.lease_expires_at,
                cancellation_requested=row.cancellation_requested,
            )

        # Heartbeat update matched 0 rows: Diagnose reason
        return cls._diagnose_failed_heartbeat_sync(db, job_id, claim_token, lock_version)

    @classmethod
    async def renew_lease_async(
        cls,
        db: AsyncSession,
        job_id: uuid.UUID,
        claim_token: str,
        lock_version: int,
        lease_seconds: int = 60,
    ) -> HeartbeatResult:
        """Async equivalent of renew_lease_sync for async callers and integration tests."""
        sql_renew = text("""
            UPDATE evaluation_jobs
            SET last_heartbeat_at = clock_timestamp(),
                lease_expires_at = clock_timestamp() + (:lease_seconds * interval '1 second')
            WHERE id = :job_id
              AND status = 'running'
              AND claim_token = :claim_token
              AND lock_version = :lock_version
              AND lease_expires_at > clock_timestamp()
            RETURNING id, lock_version, lease_expires_at, cancellation_requested;
        """)

        res = await db.execute(sql_renew, {
            "job_id": job_id,
            "claim_token": claim_token,
            "lock_version": lock_version,
            "lease_seconds": lease_seconds,
        })
        row = res.fetchone()
        if row:
            return HeartbeatResult(
                success=True,
                lock_version=row.lock_version,
                lease_expires_at=row.lease_expires_at,
                cancellation_requested=row.cancellation_requested,
            )

        return await cls._diagnose_failed_heartbeat_async(db, job_id, claim_token, lock_version)

    @staticmethod
    def _diagnose_failed_heartbeat_sync(
        db: Session,
        job_id: uuid.UUID,
        claim_token: str,
        lock_version: int,
    ) -> HeartbeatResult:
        sql_check = text("""
            SELECT status, claim_token, lock_version, cancellation_requested,
                   (lease_expires_at <= clock_timestamp()) AS is_expired
            FROM evaluation_jobs
            WHERE id = :job_id;
        """)
        check_row = db.execute(sql_check, {"job_id": job_id}).fetchone()
        if not check_row:
            return HeartbeatResult(success=False, lock_version=lock_version, error_code="JOB_NOT_FOUND")

        if check_row.status != "running":
            return HeartbeatResult(
                success=False,
                lock_version=check_row.lock_version,
                cancellation_requested=check_row.cancellation_requested,
                error_code="JOB_NOT_RUNNING",
            )
        if check_row.claim_token != claim_token:
            return HeartbeatResult(
                success=False,
                lock_version=check_row.lock_version,
                cancellation_requested=check_row.cancellation_requested,
                error_code="CLAIM_TOKEN_MISMATCH",
            )
        if check_row.lock_version != lock_version:
            return HeartbeatResult(
                success=False,
                lock_version=check_row.lock_version,
                cancellation_requested=check_row.cancellation_requested,
                error_code="FENCING_TOKEN_MISMATCH",
            )
        if check_row.is_expired:
            return HeartbeatResult(
                success=False,
                lock_version=check_row.lock_version,
                cancellation_requested=check_row.cancellation_requested,
                error_code="LEASE_EXPIRED",
            )

        return HeartbeatResult(success=False, lock_version=lock_version, error_code="UNKNOWN_RENEWAL_FAILURE")

    @staticmethod
    async def _diagnose_failed_heartbeat_async(
        db: AsyncSession,
        job_id: uuid.UUID,
        claim_token: str,
        lock_version: int,
    ) -> HeartbeatResult:
        sql_check = text("""
            SELECT status, claim_token, lock_version, cancellation_requested,
                   (lease_expires_at <= clock_timestamp()) AS is_expired
            FROM evaluation_jobs
            WHERE id = :job_id;
        """)
        res = await db.execute(sql_check, {"job_id": job_id})
        check_row = res.fetchone()
        if not check_row:
            return HeartbeatResult(success=False, lock_version=lock_version, error_code="JOB_NOT_FOUND")

        if check_row.status != "running":
            return HeartbeatResult(
                success=False,
                lock_version=check_row.lock_version,
                cancellation_requested=check_row.cancellation_requested,
                error_code="JOB_NOT_RUNNING",
            )
        if check_row.claim_token != claim_token:
            return HeartbeatResult(
                success=False,
                lock_version=check_row.lock_version,
                cancellation_requested=check_row.cancellation_requested,
                error_code="CLAIM_TOKEN_MISMATCH",
            )
        if check_row.lock_version != lock_version:
            return HeartbeatResult(
                success=False,
                lock_version=check_row.lock_version,
                cancellation_requested=check_row.cancellation_requested,
                error_code="FENCING_TOKEN_MISMATCH",
            )
        if check_row.is_expired:
            return HeartbeatResult(
                success=False,
                lock_version=check_row.lock_version,
                cancellation_requested=check_row.cancellation_requested,
                error_code="LEASE_EXPIRED",
            )

        return HeartbeatResult(success=False, lock_version=lock_version, error_code="UNKNOWN_RENEWAL_FAILURE")


class HeartbeatController:
    """
    Background heartbeat thread controller.
    Periodically renews the worker's lease using short-lived transactions.
    Detects lease expiration and cancellation requests, signaling the main thread.
    """

    def __init__(
        self,
        job_id: uuid.UUID,
        claim_token: str,
        lock_version: int,
        interval_seconds: float = 15.0,
        lease_seconds: int = 60,
    ):
        self.job_id = job_id
        self.claim_token = claim_token
        self.lock_version = lock_version
        self.interval_seconds = interval_seconds
        self.lease_seconds = lease_seconds

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._error: Optional[str] = None
        self._cancellation_requested: bool = False

    def start(self) -> None:
        """Starts the background heartbeat thread."""
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"heartbeat-{self.job_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stops the heartbeat thread and waits for termination."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def check_health(self) -> None:
        """Raises StaleLeaseError or JobCancelledError if heartbeat detected failure."""
        if self._cancellation_requested:
            raise JobCancelledError(f"Job {self.job_id} received cooperative cancellation request.")
        if self._error:
            raise StaleLeaseError(f"Heartbeat failed for job {self.job_id}: {self._error}")

    def _run_loop(self) -> None:
        from apps.api.workers.database import worker_session_scope

        while not self._stop_event.wait(timeout=self.interval_seconds):
            try:
                with worker_session_scope() as session:
                    result = WorkerLeaseManager.renew_lease_sync(
                        db=session,
                        job_id=self.job_id,
                        claim_token=self.claim_token,
                        lock_version=self.lock_version,
                        lease_seconds=self.lease_seconds,
                    )

                if not result.success:
                    self._error = result.error_code or "RENEWAL_FAILED"
                    logger.warning("Heartbeat failed for job %s: %s", self.job_id, self._error)
                    break

                if result.cancellation_requested:
                    self._cancellation_requested = True
                    logger.info("Cooperative cancellation detected during heartbeat for job %s.", self.job_id)
                    break

            except Exception as exc:
                self._error = f"UNEXPECTED_ERROR: {str(exc)}"
                logger.error("Exception in heartbeat thread for job %s: %s", self.job_id, exc, exc_info=True)
                break

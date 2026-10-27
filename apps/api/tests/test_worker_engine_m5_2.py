from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import time
from typing import List
import uuid
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from apps.api.modules.evaluations.models import (
    EvaluationJob,
    Rubric,
    RubricCriterion,
    RubricVersion,
    Submission,
    SubmissionSnapshot,
    Team,
)
from apps.api.modules.evaluations.service import dispatch_evaluation_job_atomic
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.modules.organizations.models import Organization, OrganizationMembership, OrganizationStatus, OrgRole
from apps.api.modules.users.models import User
from apps.api.workers.database import (
    get_worker_engine,
    get_worker_session_factory,
    worker_session_scope,
)
from apps.api.workers.lease_manager import (
    HeartbeatController,
    JobCancelledError,
    StaleLeaseError,
    WorkerClaim,
    WorkerLeaseManager,
)
from apps.api.workers.tasks import evaluate_submission


@pytest.fixture
async def setup_m5_2_env(db_session: AsyncSession):
    """Sets up an isolated test fixture with organization, hackathon, submission, and snapshot."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f"worker_tester_{suffix}@example.com",
        hashed_password="fakehash123",
        full_name="Worker Tester",
        platform_role=None,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    org = Organization(
        name=f"Worker Org {suffix}",
        slug=f"worker-org-{suffix}",
        owner_id=user.id,
        status=OrganizationStatus.ACTIVE,
    )
    db_session.add(org)
    await db_session.flush()

    membership = OrganizationMembership(
        organization_id=org.id,
        user_id=user.id,
        role=OrgRole.ORG_OWNER,
    )
    db_session.add(membership)
    await db_session.flush()

    hackathon = Hackathon(
        organization_id=org.id,
        title="Worker Test Hackathon",
        slug=f"worker-hack-{suffix}",
        status=HackathonStatus.PUBLISHED,
        start_date=text("now()"),
        end_date=text("now() + interval '7 days'"),
        submission_deadline=text("now() + interval '6 days'"),
        created_by_user_id=user.id,
    )
    db_session.add(hackathon)
    await db_session.flush()

    rubric = Rubric(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name=f"Rubric {suffix}",
        scoring_mode="offset_normalized",
    )
    db_session.add(rubric)
    await db_session.flush()

    rubric_version = RubricVersion(
        organization_id=org.id,
        rubric_id=rubric.id,
        version_number=1,
        status="draft",
    )
    db_session.add(rubric_version)
    await db_session.flush()

    criterion = RubricCriterion(
        rubric_version_id=rubric_version.id,
        title="Architecture Quality",
        description="Evaluates worker modularity and fencing token implementation",
        weight=Decimal("1.00"),
        min_score=Decimal("0.00"),
        max_score=Decimal("10.00"),
        evidence_requirements="source code",
        order_index=1,
    )
    db_session.add(criterion)
    await db_session.flush()

    rubric_version.status = "published"
    rubric_version.published_at = datetime.now(timezone.utc)
    await db_session.flush()

    team = Team(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name=f"Team {suffix}",
        join_code=uuid.uuid4().hex[:12],
        created_by_user_id=user.id,
    )
    db_session.add(team)
    await db_session.flush()

    submission = Submission(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        team_id=team.id,
        team_name=team.name,
        repository_url="https://github.com/scorva-test/worker-repo",
        target_branch="main",
        title="Submission Worker",
        status="pending",
    )
    db_session.add(submission)
    await db_session.flush()

    snapshot = SubmissionSnapshot(
        organization_id=org.id,
        submission_id=submission.id,
        commit_sha="a1b2c3d4e5f678901234567890abcdef12345678",
        file_count=5,
        total_bytes=5120,
        configuration_snapshot={"timeout": 60, "model": "mock-eval"},
        metadata_={},
    )
    db_session.add(snapshot)
    await db_session.commit()

    return user, org, hackathon, rubric_version, submission, snapshot


@pytest.mark.asyncio
async def test_successful_worker_claim(db_session: AsyncSession, setup_m5_2_env):
    """
    Verifies atomic worker claim:
    1. Confirms job is eligible ('queued').
    2. Transitions status to 'running'.
    3. Installs unique claim token with worker identity prefix.
    4. Increments lock_version from 0 to 1 and attempts_count from 0 to 1.
    5. Sets lease_expires_at using PostgreSQL server clock.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_2_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()
    assert job.status == "queued"
    assert job.lock_version == 0
    assert job.attempts_count == 0

    # Execute synchronous claim
    worker_id = "evaluator-node-1"
    with worker_session_scope() as session:
        claim = WorkerLeaseManager.claim_job_sync(
            db=session,
            job_id=job.id,
            worker_id=worker_id,
            lease_seconds=45,
        )

    assert claim is not None
    assert claim.job_id == job.id
    assert claim.lock_version == 1
    assert claim.attempts_count == 1
    assert claim.worker_id == worker_id
    assert claim.claim_token.startswith("evaluator-node-1:")
    assert claim.lease_expires_at is not None

    # Verify DB row
    await db_session.refresh(job)
    assert job.status == "running"
    assert job.lock_version == 1
    assert job.attempts_count == 1
    assert job.claim_token == claim.claim_token
    assert job.started_at is not None
    assert job.last_heartbeat_at is not None
    assert job.lease_expires_at is not None


@pytest.mark.asyncio
async def test_duplicate_message_while_job_running_discarded(db_session: AsyncSession, setup_m5_2_env):
    """
    Verifies that a duplicate message arriving while a job is running is discarded harmlessly:
    Second claim attempt returns None, and row lock_version / attempts_count are untouched.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_2_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    # Worker 1 claims job
    with worker_session_scope() as session:
        claim1 = WorkerLeaseManager.claim_job_sync(session, job.id, "worker-1", lease_seconds=60)
    assert claim1 is not None

    # Worker 2 attempts to claim the running job -> Must return None
    with worker_session_scope() as session:
        claim2 = WorkerLeaseManager.claim_job_sync(session, job.id, "worker-2", lease_seconds=60)
    assert claim2 is None

    # Worker 1 duplicate attempt -> Must return None
    with worker_session_scope() as session:
        claim1_dup = WorkerLeaseManager.claim_job_sync(session, job.id, "worker-1", lease_seconds=60)
    assert claim1_dup is None

    # Verify state unchanged
    await db_session.refresh(job)
    assert job.status == "running"
    assert job.lock_version == 1
    assert job.attempts_count == 1
    assert job.claim_token == claim1.claim_token


@pytest.mark.asyncio
async def test_terminal_and_cancelled_jobs_claim_rejected(db_session: AsyncSession, setup_m5_2_env):
    """
    Verifies that jobs in terminal states (completed, failed, cancelled) or with
    cancellation_requested=True cannot be claimed by workers.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_2_env

    # 1. Completed job
    job_comp, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key="comp-test",
    )
    job_comp.status = "completed"
    await db_session.commit()

    with worker_session_scope() as session:
        assert WorkerLeaseManager.claim_job_sync(session, job_comp.id, "worker-1") is None

    # 2. Failed job
    job_failed, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key="failed-test",
    )
    job_failed.status = "failed"
    await db_session.commit()

    with worker_session_scope() as session:
        assert WorkerLeaseManager.claim_job_sync(session, job_failed.id, "worker-1") is None

    # 3. Cancelled job
    job_cancelled, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key="cancelled-test",
    )
    job_cancelled.status = "cancelled"
    await db_session.commit()

    with worker_session_scope() as session:
        assert WorkerLeaseManager.claim_job_sync(session, job_cancelled.id, "worker-1") is None

    # 4. Job with cancellation_requested = True while queued
    job_queued_cancelling, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key="queued-cancelling-test",
    )
    job_queued_cancelling.cancellation_requested = True
    await db_session.commit()

    with worker_session_scope() as session:
        assert WorkerLeaseManager.claim_job_sync(session, job_queued_cancelling.id, "worker-1") is None

    # 5. Nonexistent job
    with worker_session_scope() as session:
        assert WorkerLeaseManager.claim_job_sync(session, uuid.uuid4(), "worker-1") is None

    # 6. Job exceeding max_attempts
    job_exhausted, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key="exhausted-test",
    )
    job_exhausted.attempts_count = 3
    job_exhausted.max_attempts = 3
    await db_session.commit()

    with worker_session_scope() as session:
        assert WorkerLeaseManager.claim_job_sync(session, job_exhausted.id, "worker-1") is None


@pytest.mark.asyncio
async def test_concurrent_worker_claims(db_session: AsyncSession, setup_m5_2_env):
    """
    PostgreSQL Integration Concurrency Test:
    Spawns 5 concurrent worker threads racing to claim the same queued job.
    Exactly one worker must succeed; all 4 competing workers must return None.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_2_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    results: List[Optional[WorkerClaim]] = []

    def _worker_attempt(w_idx: int):
        with worker_session_scope() as session:
            claim = WorkerLeaseManager.claim_job_sync(session, job.id, f"race-worker-{w_idx}", lease_seconds=60)
            return claim

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(_worker_attempt, i) for i in range(5)]
        for f in futures:
            results.append(f.result())

    successful_claims = [c for c in results if c is not None]
    failed_claims = [c for c in results if c is None]

    assert len(successful_claims) == 1
    assert len(failed_claims) == 4

    winner = successful_claims[0]
    assert winner.lock_version == 1
    assert winner.attempts_count == 1

    await db_session.refresh(job)
    assert job.status == "running"
    assert job.lock_version == 1
    assert job.attempts_count == 1
    assert job.claim_token == winner.claim_token


@pytest.mark.asyncio
async def test_valid_heartbeat_renewal(db_session: AsyncSession, setup_m5_2_env):
    """
    Verifies valid lease renewal:
    1. Holds valid claim token and lock_version.
    2. Lease is unexpired (lease_expires_at > clock_timestamp()).
    3. Heartbeat query updates last_heartbeat_at and extends lease_expires_at.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_2_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    with worker_session_scope() as session:
        claim = WorkerLeaseManager.claim_job_sync(session, job.id, "hb-worker-1", lease_seconds=30)
    assert claim is not None
    initial_lease = claim.lease_expires_at

    # Renew lease with 60s extension
    with worker_session_scope() as session:
        renew_res = WorkerLeaseManager.renew_lease_sync(
            session,
            job_id=job.id,
            claim_token=claim.claim_token,
            lock_version=claim.lock_version,
            lease_seconds=60,
        )

    assert renew_res.success is True
    assert renew_res.lock_version == claim.lock_version
    assert renew_res.cancellation_requested is False
    assert renew_res.lease_expires_at is not None
    assert renew_res.lease_expires_at > initial_lease


@pytest.mark.asyncio
async def test_expired_lease_renewal_rejected(db_session: AsyncSession, setup_m5_2_env):
    """
    Verifies that a late heartbeat cannot revive an expired lease:
    1. Worker claims job.
    2. Lease expires in database (lease_expires_at < clock_timestamp()).
    3. Late renew_lease attempt updates 0 rows and returns error LEASE_EXPIRED.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_2_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    with worker_session_scope() as session:
        claim = WorkerLeaseManager.claim_job_sync(session, job.id, "expired-worker", lease_seconds=10)
    assert claim is not None

    # Forcefully expire lease in database using server time
    await db_session.execute(
        text("UPDATE evaluation_jobs SET lease_expires_at = clock_timestamp() - interval '5 seconds' WHERE id = :id"),
        {"id": job.id},
    )
    await db_session.commit()

    # Worker attempts late heartbeat
    with worker_session_scope() as session:
        renew_res = WorkerLeaseManager.renew_lease_sync(
            session,
            job_id=job.id,
            claim_token=claim.claim_token,
            lock_version=claim.lock_version,
            lease_seconds=60,
        )

    assert renew_res.success is False
    assert renew_res.error_code == "LEASE_EXPIRED"

    # Verify lease was NOT revived
    await db_session.refresh(job)
    assert job.lease_expires_at < datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_stale_claim_token_rejection(db_session: AsyncSession, setup_m5_2_env):
    """
    Verifies that a stale worker cannot renew after a replacement worker claims the job:
    1. Worker 1 claims job (Token 1, lock_version 1).
    2. Reaper / Replacement: Worker 2 claims job (Token 2, lock_version 2).
    3. Stale Worker 1 attempts renewal with Token 1 -> Rejected.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_2_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    # Worker 1 claims job
    with worker_session_scope() as session:
        claim1 = WorkerLeaseManager.claim_job_sync(session, job.id, "worker-1", lease_seconds=30)
    assert claim1 is not None

    # Simulate reaper requeuing job
    await db_session.execute(
        text("UPDATE evaluation_jobs SET status = 'queued', claim_token = NULL, lease_expires_at = NULL, lock_version = 1 WHERE id = :id"),
        {"id": job.id},
    )
    await db_session.commit()

    # Worker 2 claims job
    with worker_session_scope() as session:
        claim2 = WorkerLeaseManager.claim_job_sync(session, job.id, "worker-2", lease_seconds=60)
    assert claim2 is not None
    assert claim2.claim_token != claim1.claim_token
    assert claim2.lock_version == 2

    # Stale Worker 1 attempts renewal with Token 1
    with worker_session_scope() as session:
        renew_res = WorkerLeaseManager.renew_lease_sync(
            session,
            job_id=job.id,
            claim_token=claim1.claim_token,
            lock_version=claim1.lock_version,
            lease_seconds=60,
        )

    assert renew_res.success is False
    assert renew_res.error_code in ("CLAIM_TOKEN_MISMATCH", "FENCING_TOKEN_MISMATCH")

    # Worker 2's lease remains valid and protected
    await db_session.refresh(job)
    assert job.claim_token == claim2.claim_token
    assert job.lock_version == 2


@pytest.mark.asyncio
async def test_lock_version_mismatch_rejection(db_session: AsyncSession, setup_m5_2_env):
    """
    Verifies that presenting a stale or mismatched lock_version aborts renewal.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_2_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    with worker_session_scope() as session:
        claim = WorkerLeaseManager.claim_job_sync(session, job.id, "mismatch-worker", lease_seconds=60)
    assert claim is not None

    # Renewal with mismatched lock_version
    with worker_session_scope() as session:
        renew_res = WorkerLeaseManager.renew_lease_sync(
            session,
            job_id=job.id,
            claim_token=claim.claim_token,
            lock_version=999,  # Mismatched fencing token
            lease_seconds=60,
        )

    assert renew_res.success is False
    assert renew_res.error_code == "FENCING_TOKEN_MISMATCH"


@pytest.mark.asyncio
async def test_cancellation_racing_with_heartbeat_renewal(db_session: AsyncSession, setup_m5_2_env):
    """
    Verifies cooperative cancellation detection:
    1. Job is claimed and running.
    2. Admin requests cancellation: cancellation_requested = true.
    3. Worker heartbeat executes and detects cancellation_requested = true in RETURNING row.
    4. Worker detects cancellation signal and aborts.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_2_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    with worker_session_scope() as session:
        claim = WorkerLeaseManager.claim_job_sync(session, job.id, "cancel-worker", lease_seconds=60)
    assert claim is not None

    # Admin requests cancellation
    await db_session.execute(
        text("UPDATE evaluation_jobs SET cancellation_requested = true WHERE id = :id"),
        {"id": job.id},
    )
    await db_session.commit()

    # Worker executes heartbeat renewal
    with worker_session_scope() as session:
        renew_res = WorkerLeaseManager.renew_lease_sync(
            session,
            job_id=job.id,
            claim_token=claim.claim_token,
            lock_version=claim.lock_version,
            lease_seconds=60,
        )

    assert renew_res.success is True
    assert renew_res.cancellation_requested is True


def test_worker_session_cleanup_and_transaction_rollback():
    """
    Verifies that worker_session_scope:
    1. Automatically commits on successful exit.
    2. Automatically rolls back on unhandled exception.
    3. Mandatory session closure returns connection to pool.
    """
    # 1. Successful transaction
    with worker_session_scope() as session:
        session.execute(text("SELECT 1"))
    # Connection is released back to pool

    # 2. Rollback on exception
    with pytest.raises(ValueError):
        with worker_session_scope() as session:
            session.execute(text("SELECT 1"))
            raise ValueError("Simulated task error")

    # Verify pool status is clean
    engine = get_worker_engine()
    assert engine.pool.checkedout() == 0


@pytest.mark.asyncio
async def test_celery_task_evaluate_submission_minimal_payload_and_idempotence(
    db_session: AsyncSession, setup_m5_2_env
):
    """
    Verifies Celery evaluate_submission task:
    1. Accepts minimal payload (job_id string only).
    2. Claims job and transitions to running.
    3. Duplicate delivery returns {'status': 'discarded'}.
    4. Invalid UUID returns {'status': 'error'}.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_2_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    # First delivery: claims job and runs pipeline
    res1 = evaluate_submission(str(job.id))
    assert res1["status"] in ("claimed", "completed")
    assert res1["job_id"] == str(job.id)
    assert res1["lock_version"] in (1, 2)
    assert res1["attempts_count"] == 1

    # Second delivery: duplicate delivery discarded harmlessly
    res2 = evaluate_submission(str(job.id))
    assert res2["status"] == "discarded"
    assert res2["reason"] == "NOT_CLAIMABLE"

    # Invalid job ID format
    res3 = evaluate_submission("not-a-valid-uuid")
    assert res3["status"] == "error"
    assert res3["error"] == "INVALID_JOB_ID"


@pytest.mark.asyncio
async def test_heartbeat_controller_background_thread_and_cancellation(
    db_session: AsyncSession, setup_m5_2_env
):
    """
    Verifies the HeartbeatController background thread:
    1. Periodically renews lease in the background using short-lived transactions.
    2. Detects cancellation flag and raises JobCancelledError on check_health.
    3. Stops cleanly.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_2_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    with worker_session_scope() as session:
        claim = WorkerLeaseManager.claim_job_sync(session, job.id, "thread-worker", lease_seconds=15)
    assert claim is not None

    controller = HeartbeatController(
        job_id=job.id,
        claim_token=claim.claim_token,
        lock_version=claim.lock_version,
        interval_seconds=0.1,  # Fast interval for test
        lease_seconds=15,
    )
    controller.start()

    try:
        time.sleep(0.2)
        controller.check_health()  # Should be healthy

        # Admin requests cancellation
        await db_session.execute(
            text("UPDATE evaluation_jobs SET cancellation_requested = true WHERE id = :id"),
            {"id": job.id},
        )
        await db_session.commit()

        time.sleep(0.3)
        with pytest.raises(JobCancelledError):
            controller.check_health()

    finally:
        controller.stop()

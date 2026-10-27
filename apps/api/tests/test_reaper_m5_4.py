import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import Any, Dict, List, Optional
import uuid

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from apps.api.core.exceptions import AppException
from apps.api.modules.audit.models import AuditEvent, AuditOutcome
from apps.api.modules.evaluations.models import (
    EvaluationJob,
    EvaluationJobOutbox,
    EvaluationResult,
    Rubric,
    RubricCriterion,
    RubricVersion,
    Submission,
    SubmissionSnapshot,
    Team,
)
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.modules.organizations.models import (
    Organization,
    OrganizationMembership,
    OrganizationStatus,
    OrgRole,
)
from apps.api.modules.users.models import User
from apps.api.modules.evaluations.outbox import (
    OutboxStatus,
    claim_outbox_batch,
    settle_outbox_row,
)
from apps.api.modules.evaluations.service import (
    CancellationResult,
    cancel_evaluation_job_atomic,
    cancel_evaluation_job_atomic_sync,
    dispatch_evaluation_job_atomic,
)
from apps.api.workers.database import worker_session_scope
from apps.api.workers.lease_manager import (
    HeartbeatResult,
    WorkerClaim,
    WorkerLeaseManager,
)
from apps.api.workers.pipeline import (
    CommitResult,
    commit_evaluation_result_fenced_async,
    commit_evaluation_result_fenced_sync,
)
from apps.api.workers.reaper import (
    ReapedJobResult,
    ReaperBatchReport,
    calculate_exponential_backoff,
    reap_stalled_evaluation_jobs_async,
    reap_stalled_evaluation_jobs_sync,
    reap_stalled_evaluation_jobs_task,
)


@pytest.fixture
async def setup_reaper_env(db_session: AsyncSession):
    """Sets up an isolated test fixture with user, org, hackathon, rubric, submission, and snapshot."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f"reaper_tester_{suffix}@example.com",
        hashed_password="fakehash123",
        full_name="Reaper Tester",
        platform_role=None,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    org = Organization(
        name=f"Reaper Org {suffix}",
        slug=f"reap-org-{suffix}",
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
        title="Reaper Hackathon",
        slug=f"reap-hack-{suffix}",
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

    crit1 = RubricCriterion(
        rubric_version_id=rubric_version.id,
        title="Architecture",
        description="Clean boundaries",
        weight=Decimal("0.50"),
        min_score=Decimal("0.00"),
        max_score=Decimal("10.00"),
        evidence_requirements="code",
        order_index=1,
    )
    db_session.add(crit1)

    crit2 = RubricCriterion(
        rubric_version_id=rubric_version.id,
        title="Security & Resilience",
        description="Fencing protocols",
        weight=Decimal("0.50"),
        min_score=Decimal("0.00"),
        max_score=Decimal("10.00"),
        evidence_requirements="code",
        order_index=2,
    )
    db_session.add(crit2)
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
        repository_url="https://github.com/scorva-test/reaper-repo",
        target_branch="main",
        title="Submission Reaper",
        status="pending",
    )
    db_session.add(submission)
    await db_session.flush()

    snapshot = SubmissionSnapshot(
        organization_id=org.id,
        submission_id=submission.id,
        commit_sha="c1b2c3d4e5f678901234567890abcdef12345678",
        file_count=1,
        total_bytes=2048,
        configuration_snapshot={"timeout": 60, "model": "mock-eval"},
        metadata_={"extracted_files_manifest": [{"path": "src/main.py", "lines": ["# code"]}]},
    )
    db_session.add(snapshot)
    await db_session.commit()

    return user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot


@pytest.mark.asyncio
async def test_expired_running_job_is_recovered_and_receives_durable_outbox_dispatch(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 1: Expired running job is recovered:
    - Atomically updates status = 'queued', clears claim_token, advances lock_version and dispatch_generation.
    - Creates a durable outbox entry in the exact same transaction.
    - Emits evaluation.reaped_retry audit event.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    # Worker claims job
    claim = await WorkerLeaseManager.claim_job_async(
        db=db_session,
        job_id=job.id,
        worker_id="worker-node-1",
        lease_seconds=60,
    )
    assert claim is not None
    await db_session.commit()

    # Expire lease by shifting lease_expires_at into past
    await db_session.execute(
        text("UPDATE evaluation_jobs SET lease_expires_at = clock_timestamp() - interval '5 seconds' WHERE id = :id"),
        {"id": job.id},
    )
    await db_session.commit()

    # Run reaper with base_backoff_seconds=0 for immediate eligibility
    report = await reap_stalled_evaluation_jobs_async(db=db_session, batch_size=10, base_backoff_seconds=0.0, jitter=False, organization_id=org.id)
    assert report.total_candidates == 1
    assert report.requeued_count == 1
    assert report.exhausted_count == 0
    await db_session.commit()

    # Verify job state in database
    await db_session.refresh(job)
    assert job.status == "queued"
    assert job.claim_token is None
    assert job.last_heartbeat_at is None
    assert job.lock_version == 2
    assert job.dispatch_generation == 2
    assert job.attempts_count == 1  # 1 attempt consumed; attempt budget intact

    # Verify durable outbox entry created
    stmt_outbox = select(EvaluationJobOutbox).where(
        EvaluationJobOutbox.job_id == job.id,
        EvaluationJobOutbox.dispatch_generation == 2,
    )
    outbox_entries = list((await db_session.execute(stmt_outbox)).scalars().all())
    assert len(outbox_entries) == 1
    entry = outbox_entries[0]
    assert entry.status == "pending"
    assert entry.claim_count == 0

    # Verify audit event recorded
    stmt_audit = select(AuditEvent).where(
        AuditEvent.resource_id == str(job.id),
        AuditEvent.action == "evaluation.reaped_retry",
    )
    audits = list((await db_session.execute(stmt_audit)).scalars().all())
    assert len(audits) == 1
    assert audits[0].outcome == AuditOutcome.SUCCESS


@pytest.mark.asyncio
async def test_unexpired_running_job_is_not_reclaimed(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 2: Unexpired running job is never reclaimed by reaper.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    # Worker claims job with 300s lease
    claim = await WorkerLeaseManager.claim_job_async(
        db=db_session,
        job_id=job.id,
        worker_id="active-worker",
        lease_seconds=300,
    )
    assert claim is not None
    await db_session.commit()

    # Run reaper
    report = await reap_stalled_evaluation_jobs_async(db=db_session, batch_size=10, organization_id=org.id)
    assert report.total_candidates == 0
    assert report.requeued_count == 0
    await db_session.commit()

    # Job is untouched
    await db_session.refresh(job)
    assert job.status == "running"
    assert job.claim_token == claim.claim_token
    assert job.lock_version == claim.lock_version


@pytest.mark.asyncio
async def test_completed_failed_cancelled_jobs_are_not_reclaimed(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 3: Jobs in terminal states (completed, failed, cancelled) are never reclaimed,
    even if their historical lease_expires_at is in the past.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    # Job 1: completed
    j1, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    # Job 2: failed
    j2, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    # Job 3: cancelled
    j3, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    await db_session.execute(
        text("UPDATE evaluation_jobs SET status = 'completed', lease_expires_at = clock_timestamp() - interval '1 hour' WHERE id = :id"),
        {"id": j1.id},
    )
    await db_session.execute(
        text("UPDATE evaluation_jobs SET status = 'failed', lease_expires_at = clock_timestamp() - interval '1 hour' WHERE id = :id"),
        {"id": j2.id},
    )
    await db_session.execute(
        text("UPDATE evaluation_jobs SET status = 'cancelled', lease_expires_at = clock_timestamp() - interval '1 hour' WHERE id = :id"),
        {"id": j3.id},
    )
    await db_session.commit()

    report = await reap_stalled_evaluation_jobs_async(db=db_session, batch_size=50, organization_id=org.id)
    assert report.total_candidates == 0
    assert report.requeued_count == 0


@pytest.mark.asyncio
async def test_exhausted_job_transitions_to_terminal_failure_state(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 4: Job that has reached max_attempts transitions to terminal 'failed' with
    WORKER_LEASE_TIMEOUT_EXHAUSTED and creates zero outbox records.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    # Set attempts_count = 3, max_attempts = 3, status = 'running', expired lease
    await db_session.execute(
        text("""
            UPDATE evaluation_jobs
            SET status = 'running',
                attempts_count = 3,
                max_attempts = 3,
                lock_version = 3,
                claim_token = 'worker-stale',
                lease_expires_at = clock_timestamp() - interval '10 seconds'
            WHERE id = :id
        """),
        {"id": job.id},
    )
    await db_session.commit()

    report = await reap_stalled_evaluation_jobs_async(db=db_session, batch_size=10, organization_id=org.id)
    assert report.total_candidates == 1
    assert report.exhausted_count == 1
    assert report.requeued_count == 0
    await db_session.commit()

    await db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_code == "WORKER_LEASE_TIMEOUT_EXHAUSTED"
    assert job.completed_at is not None
    assert job.claim_token is None

    # Zero new outbox records created
    stmt_outbox = select(EvaluationJobOutbox).where(
        EvaluationJobOutbox.job_id == job.id,
        EvaluationJobOutbox.status.in_(["pending", "processing"]),
    )
    active_outbox = list((await db_session.execute(stmt_outbox)).scalars().all())
    assert len(active_outbox) == 0


@pytest.mark.asyncio
async def test_retryable_jobs_respect_max_attempts(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 5: Validates exact retry budget progression:
    Job with max_attempts = 2:
    - Attempt 1: claimed -> expired -> reaped to queued.
    - Attempt 2: claimed -> expired -> reaped to failed terminal.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    job.max_attempts = 2
    await db_session.commit()

    # Attempt 1
    c1 = await WorkerLeaseManager.claim_job_async(db=db_session, job_id=job.id, worker_id="w1", lease_seconds=10)
    assert c1.attempts_count == 1
    await db_session.commit()

    # Expire attempt 1
    await db_session.execute(text("UPDATE evaluation_jobs SET lease_expires_at = clock_timestamp() - interval '1 second' WHERE id = :id"), {"id": job.id})
    await db_session.commit()

    r1 = await reap_stalled_evaluation_jobs_async(db=db_session, base_backoff_seconds=0.0, jitter=False, organization_id=org.id)
    assert r1.requeued_count == 1
    await db_session.commit()

    # Attempt 2
    c2 = await WorkerLeaseManager.claim_job_async(db=db_session, job_id=job.id, worker_id="w2", lease_seconds=10)
    assert c2.attempts_count == 2
    await db_session.commit()

    # Expire attempt 2
    await db_session.execute(text("UPDATE evaluation_jobs SET lease_expires_at = clock_timestamp() - interval '1 second' WHERE id = :id"), {"id": job.id})
    await db_session.commit()

    # Second reap: budget is exhausted (2 >= 2)
    r2 = await reap_stalled_evaluation_jobs_async(db=db_session, organization_id=org.id)
    assert r2.exhausted_count == 1
    assert r2.requeued_count == 0
    await db_session.commit()

    await db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_code == "WORKER_LEASE_TIMEOUT_EXHAUSTED"


@pytest.mark.asyncio
async def test_backoff_prevents_immediate_repeated_retries(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 6: Exponential backoff prevents hot loops:
    1. Reaping with backoff sets lease_expires_at into the future.
    2. WorkerLeaseManager.claim_job rejects claim attempts while backoff is active.
    3. Once backoff expires, claim succeeds.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    claim = await WorkerLeaseManager.claim_job_async(db=db_session, job_id=job.id, worker_id="w1", lease_seconds=10)
    await db_session.commit()

    # Expire lease
    await db_session.execute(text("UPDATE evaluation_jobs SET lease_expires_at = clock_timestamp() - interval '1 second' WHERE id = :id"), {"id": job.id})
    await db_session.commit()

    # Reaping with base_backoff_seconds = 30
    report = await reap_stalled_evaluation_jobs_async(db=db_session, base_backoff_seconds=30.0, jitter=False, organization_id=org.id)
    assert report.requeued_count == 1
    await db_session.commit()

    await db_session.refresh(job)
    assert job.status == "queued"
    assert job.lease_expires_at is not None

    # Immediate claim attempt: MUST be rejected by backoff check
    claim_early = await WorkerLeaseManager.claim_job_async(db=db_session, job_id=job.id, worker_id="w2")
    assert claim_early is None  # Rejected!

    # Simulate backoff expiration
    await db_session.execute(text("UPDATE evaluation_jobs SET lease_expires_at = clock_timestamp() - interval '1 second' WHERE id = :id"), {"id": job.id})
    await db_session.commit()

    # Now claim succeeds!
    claim_after = await WorkerLeaseManager.claim_job_async(db=db_session, job_id=job.id, worker_id="w2")
    assert claim_after is not None
    assert claim_after.attempts_count == 2


@pytest.mark.asyncio
async def test_duplicate_reaper_runs_do_not_create_duplicate_active_dispatch_records(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 7: Multiple consecutive reaper sweeps do not create duplicate active outbox dispatches
    and uphold the uq_eval_job_outbox_active_dispatch constraint.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    await WorkerLeaseManager.claim_job_async(db=db_session, job_id=job.id, worker_id="w1", lease_seconds=10)
    await db_session.execute(text("UPDATE evaluation_jobs SET lease_expires_at = clock_timestamp() - interval '1 second' WHERE id = :id"), {"id": job.id})
    await db_session.commit()

    # First reaper run
    r1 = await reap_stalled_evaluation_jobs_async(db=db_session, base_backoff_seconds=0.0, jitter=False, organization_id=org.id)
    assert r1.requeued_count == 1
    await db_session.commit()

    # Immediate second reaper run: job is 'queued', 0 candidates reaped
    r2 = await reap_stalled_evaluation_jobs_async(db=db_session, base_backoff_seconds=0.0, jitter=False, organization_id=org.id)
    assert r2.total_candidates == 0
    assert r2.requeued_count == 0
    await db_session.commit()

    # Verify exactly 1 active outbox record exists
    stmt = select(EvaluationJobOutbox).where(
        EvaluationJobOutbox.job_id == job.id,
        EvaluationJobOutbox.status.in_(["pending", "processing"]),
    )
    active_rows = list((await db_session.execute(stmt)).scalars().all())
    assert len(active_rows) == 1


@pytest.mark.asyncio
async def test_concurrent_reapers_safely_process_disjoint_rows_with_skip_locked(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 8: Concurrent reapers process disjoint sets of expired jobs without conflict
    using SELECT ... FOR UPDATE SKIP LOCKED.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    jobs = []
    for i in range(4):
        j, _ = await dispatch_evaluation_job_atomic(
            db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
            submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
            idempotency_key=f"conc-job-{i}-{uuid.uuid4().hex[:8]}",
        )
        jobs.append(j)
    await db_session.commit()

    for j in jobs:
        await WorkerLeaseManager.claim_job_async(db=db_session, job_id=j.id, worker_id="w-conc", lease_seconds=10)
    await db_session.execute(text("UPDATE evaluation_jobs SET lease_expires_at = clock_timestamp() - interval '5 seconds' WHERE id = ANY(:ids)"), {"ids": [j.id for j in jobs]})
    await db_session.commit()

    # Run two synchronous reapers with batch_size=2 simulating concurrent workers
    rep1 = reap_stalled_evaluation_jobs_sync(batch_size=2, base_backoff_seconds=0.0, jitter=False, organization_id=org.id)
    rep2 = reap_stalled_evaluation_jobs_sync(batch_size=2, base_backoff_seconds=0.0, jitter=False, organization_id=org.id)

    assert rep1.requeued_count == 2
    assert rep2.requeued_count == 2

    # Disjoint sets of job IDs processed
    set1 = {r.job_id for r in rep1.results}
    set2 = {r.job_id for r in rep2.results}
    assert len(set1.intersection(set2)) == 0


@pytest.mark.asyncio
async def test_stale_worker_cannot_heartbeat_after_recovery(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 9: Stale worker heartbeat is unconditionally rejected after reaper recovery
    due to lock_version increment and claim_token invalidation.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    claim = await WorkerLeaseManager.claim_job_async(db=db_session, job_id=job.id, worker_id="w-old", lease_seconds=10)
    await db_session.execute(text("UPDATE evaluation_jobs SET lease_expires_at = clock_timestamp() - interval '1 second' WHERE id = :id"), {"id": job.id})
    await db_session.commit()

    # Reaper recovers job
    await reap_stalled_evaluation_jobs_async(db=db_session, base_backoff_seconds=0.0, jitter=False, organization_id=org.id)
    await db_session.commit()

    # Stale worker attempts heartbeat renewal
    hb = await WorkerLeaseManager.renew_lease_async(
        db=db_session,
        job_id=job.id,
        claim_token=claim.claim_token,
        lock_version=claim.lock_version,
    )
    assert not hb.success
    assert hb.error_code in ("LOCK_VERSION_MISMATCH", "JOB_NOT_RUNNING", "TOKEN_MISMATCH")


@pytest.mark.asyncio
async def test_stale_worker_cannot_commit_results_after_recovery(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 10: Stale worker attempting result persistence after recovery is rejected by
    the pessimistic row lock fencing guard; zero rows written.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    claim = await WorkerLeaseManager.claim_job_async(db=db_session, job_id=job.id, worker_id="w-stale-commit", lease_seconds=10)
    await db_session.execute(text("UPDATE evaluation_jobs SET lease_expires_at = clock_timestamp() - interval '1 second' WHERE id = :id"), {"id": job.id})
    await db_session.commit()

    # Reaper recovers job
    await reap_stalled_evaluation_jobs_async(db=db_session, base_backoff_seconds=0.0, jitter=False, organization_id=org.id)
    await db_session.commit()

    # Stale worker attempts result persistence
    from apps.api.modules.evaluations.output_validator import AIEvaluationOutputPayload, AICriterionScorePayload
    from apps.api.modules.evaluations.scoring_calculator import EvaluationScoreResult, ScoringMode

    fake_output = AIEvaluationOutputPayload(
        summary_assessment="Valid summary assessment meets length requirement.",
        has_insufficient_evidence=False,
        criterion_scores=[
            AICriterionScorePayload(
                criterion_id=crit1.id, awarded_score=Decimal("8.00"), confidence_score=Decimal("1.0"),
                rationale="Valid rationale meets length.", evidence_status="verified", evidence_references=[],
            )
        ],
    )
    fake_score = EvaluationScoreResult(
        raw_score=Decimal("8.00"), normalized_score=Decimal("80.00"),
        scoring_mode=ScoringMode.OFFSET_NORMALIZED, criterion_scores=[],
    )

    commit_res = await commit_evaluation_result_fenced_async(
        db=db_session,
        claim=claim,
        ai_output=fake_output,
        score_result=fake_score,
    )
    assert not commit_res.success
    assert commit_res.error_code in ("JOB_NOT_RUNNING", "FENCING_TOKEN_MISMATCH", "CLAIM_TOKEN_MISMATCH")

    # Verify zero results were persisted
    res_stmt = select(EvaluationResult).where(EvaluationResult.job_id == job.id)
    results = list((await db_session.execute(res_stmt)).scalars().all())
    assert len(results) == 0


@pytest.mark.asyncio
async def test_heartbeat_versus_reaper_race_handled_safely(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 11: Heartbeat vs Reaper Race:
    If a legitimate worker renews its lease before the reaper evaluates the row,
    lease_expires_at is extended into the future, and reaper safely skips the job.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    claim = await WorkerLeaseManager.claim_job_async(db=db_session, job_id=job.id, worker_id="w-live", lease_seconds=10)
    await db_session.commit()

    # Worker heartbeats, extending lease by 120 seconds
    hb = await WorkerLeaseManager.renew_lease_async(
        db=db_session,
        job_id=job.id,
        claim_token=claim.claim_token,
        lock_version=claim.lock_version,
        lease_seconds=120,
    )
    assert hb.success
    await db_session.commit()

    # Reaper runs: lease is now valid, 0 rows reaped
    report = await reap_stalled_evaluation_jobs_async(db=db_session, organization_id=org.id)
    assert report.total_candidates == 0
    assert report.requeued_count == 0


@pytest.mark.asyncio
async def test_result_commit_versus_reaper_race_handled_safely(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 12: Result Commit vs Reaper Race:
    If a legitimate worker completes and commits results first, job transitions to 'completed'.
    The reaper subsequently ignores the job, preserving the completed evaluation.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    claim = await WorkerLeaseManager.claim_job_async(db=db_session, job_id=job.id, worker_id="w-commit-race", lease_seconds=60)
    await db_session.commit()

    from apps.api.modules.evaluations.output_validator import AIEvaluationOutputPayload, AICriterionScorePayload
    from apps.api.modules.evaluations.scoring_calculator import EvaluationScoreResult, ScoringMode

    fake_output = AIEvaluationOutputPayload(
        summary_assessment="Valid summary assessment meets length requirement.",
        has_insufficient_evidence=False,
        criterion_scores=[
            AICriterionScorePayload(
                criterion_id=crit1.id, awarded_score=Decimal("9.00"), confidence_score=Decimal("1.0"),
                rationale="Valid rationale meets length.", evidence_status="verified", evidence_references=[],
            )
        ],
    )
    fake_score = EvaluationScoreResult(
        raw_score=Decimal("9.00"), normalized_score=Decimal("90.00"),
        scoring_mode=ScoringMode.OFFSET_NORMALIZED, criterion_scores=[],
    )

    commit_res = await commit_evaluation_result_fenced_async(
        db=db_session, claim=claim, ai_output=fake_output, score_result=fake_score,
    )
    assert commit_res.success
    await db_session.commit()

    # Expire historical lease timestamp on the completed job
    await db_session.execute(text("UPDATE evaluation_jobs SET lease_expires_at = clock_timestamp() - interval '1 hour' WHERE id = :id"), {"id": job.id})
    await db_session.commit()

    # Reaper runs: completed job is NOT reaped
    report = await reap_stalled_evaluation_jobs_async(db=db_session, organization_id=org.id)
    assert report.total_candidates == 0

    await db_session.refresh(job)
    assert job.status == "completed"


@pytest.mark.asyncio
async def test_queued_cancellation_prevents_worker_execution(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 13: Cancelling a queued job transitions it immediately to 'cancelled' and
    dead-letters pending outbox entries. Worker cannot subsequently claim it.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    # Request cancellation while still in queued status
    cancel_res = await cancel_evaluation_job_atomic(
        db=db_session,
        job_id=job.id,
        organization_id=org.id,
        actor_user_id=user.id,
        actor_email=user.email,
    )
    assert cancel_res.status == "cancelled"
    await db_session.commit()

    await db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.cancellation_requested is True
    assert job.completed_at is not None

    # Verify pending outbox entry was dead-lettered
    stmt = select(EvaluationJobOutbox).where(EvaluationJobOutbox.job_id == job.id)
    outbox_entries = list((await db_session.execute(stmt)).scalars().all())
    assert len(outbox_entries) == 1
    assert outbox_entries[0].status == OutboxStatus.DEAD_LETTERED.value

    # Worker attempts to claim cancelled job: MUST return None
    claim = await WorkerLeaseManager.claim_job_async(db=db_session, job_id=job.id, worker_id="w-late")
    assert claim is None


@pytest.mark.asyncio
async def test_running_cancellation_prevents_result_commitment(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 14: Cancelling a running job sets cancellation_requested=True.
    When worker reaches result commitment, the in-lock guard aborts with CANCELLATION_REQUESTED
    and transitions job to terminal 'cancelled' with zero partial results.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    claim = await WorkerLeaseManager.claim_job_async(db=db_session, job_id=job.id, worker_id="w-cancel-run", lease_seconds=60)
    await db_session.commit()

    # User requests cancellation
    cancel_res = await cancel_evaluation_job_atomic(
        db=db_session, job_id=job.id, organization_id=org.id, actor_user_id=user.id, actor_email=user.email,
    )
    assert cancel_res.status == "cancellation_requested"
    await db_session.commit()

    # Worker attempts commit
    from apps.api.modules.evaluations.output_validator import AIEvaluationOutputPayload, AICriterionScorePayload
    from apps.api.modules.evaluations.scoring_calculator import EvaluationScoreResult, ScoringMode

    fake_output = AIEvaluationOutputPayload(
        summary_assessment="Valid summary assessment meets length requirement.",
        has_insufficient_evidence=False,
        criterion_scores=[
            AICriterionScorePayload(
                criterion_id=crit1.id, awarded_score=Decimal("8.00"), confidence_score=Decimal("1.0"),
                rationale="Valid rationale meets length.", evidence_status="verified", evidence_references=[],
            )
        ],
    )
    fake_score = EvaluationScoreResult(
        raw_score=Decimal("8.00"), normalized_score=Decimal("80.00"),
        scoring_mode=ScoringMode.OFFSET_NORMALIZED, criterion_scores=[],
    )

    commit_res = await commit_evaluation_result_fenced_async(
        db=db_session, claim=claim, ai_output=fake_output, score_result=fake_score,
    )
    assert not commit_res.success
    assert commit_res.error_code == "CANCELLATION_REQUESTED"
    await db_session.commit()

    # Verify zero results were persisted
    res_stmt = select(EvaluationResult).where(EvaluationResult.job_id == job.id)
    results = list((await db_session.execute(res_stmt)).scalars().all())
    assert len(results) == 0

    await db_session.refresh(job)
    assert job.status == "cancelled"


@pytest.mark.asyncio
async def test_abandoned_cancellation_finalized_after_lease_expiry(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 15: If cancellation was requested on a running job, but the worker died before
    cooperatively aborting, the reaper finalizes it as 'cancelled' upon lease expiry
    without requeuing.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    await WorkerLeaseManager.claim_job_async(db=db_session, job_id=job.id, worker_id="w-dead-cancel", lease_seconds=10)
    await db_session.commit()

    # Cancellation requested
    await cancel_evaluation_job_atomic(db=db_session, job_id=job.id, organization_id=org.id, actor_user_id=user.id, actor_email=user.email)
    await db_session.commit()

    # Worker crashes: lease expires
    await db_session.execute(text("UPDATE evaluation_jobs SET lease_expires_at = clock_timestamp() - interval '5 seconds' WHERE id = :id"), {"id": job.id})
    await db_session.commit()

    # Reaper sweeps
    report = await reap_stalled_evaluation_jobs_async(db=db_session, organization_id=org.id)
    assert report.total_candidates == 1
    assert report.cancelled_count == 1
    assert report.requeued_count == 0
    await db_session.commit()

    await db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.error_code == "CANCELLED_AFTER_LEASE_EXPIRY"
    assert job.completed_at is not None


@pytest.mark.asyncio
async def test_repeated_cancellation_requests_are_idempotent(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 16: Calling cancel_evaluation_job_atomic repeatedly is strictly idempotent
    and returns valid state without error.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    # 1. First cancel on queued
    r1 = await cancel_evaluation_job_atomic(db=db_session, job_id=job.id, organization_id=org.id, actor_user_id=user.id, actor_email=user.email)
    assert r1.status == "cancelled"
    await db_session.commit()

    # 2. Second cancel on now-cancelled job
    r2 = await cancel_evaluation_job_atomic(db=db_session, job_id=job.id, organization_id=org.id, actor_user_id=user.id, actor_email=user.email)
    assert r2.status == "already_terminal"
    assert r2.current_status == "cancelled"

    # 3. Conflict on completed job
    await db_session.execute(text("UPDATE evaluation_jobs SET status = 'completed' WHERE id = :id"), {"id": job.id})
    await db_session.commit()

    with pytest.raises(AppException) as exc_info:
        await cancel_evaluation_job_atomic(db=db_session, job_id=job.id, organization_id=org.id, actor_user_id=user.id, actor_email=user.email)
    assert exc_info.value.code == "CANNOT_CANCEL_COMPLETED"


@pytest.mark.asyncio
async def test_outbox_publication_failure_preserves_durable_recovery_state(
    db_session: AsyncSession, setup_reaper_env
):
    """
    Test 17: Outbox publication failure preserves durable recovery state:
    1. Expired job is reaped to 'queued' and outbox entry created in PostgreSQL.
    2. Simulated Redis outage during outbox relay leaves job safely queued and outbox entry durable.
    3. Relay subsequently succeeds when broker recovers.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_reaper_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    await WorkerLeaseManager.claim_job_async(db=db_session, job_id=job.id, worker_id="w-redis-test", lease_seconds=10)
    await db_session.execute(text("UPDATE evaluation_jobs SET lease_expires_at = clock_timestamp() - interval '1 second' WHERE id = :id"), {"id": job.id})
    await db_session.commit()

    # Reaper recovers job
    rep = await reap_stalled_evaluation_jobs_async(db=db_session, base_backoff_seconds=0.0, jitter=False, organization_id=org.id)
    assert rep.requeued_count == 1
    await db_session.commit()

    # Outbox relay claims batch
    relay_token = uuid.uuid4()
    claimed_rows = await claim_outbox_batch(db=db_session, relay_token=relay_token, batch_size=10, organization_id=org.id)
    assert len(claimed_rows) == 1
    outbox_entry = claimed_rows[0]
    await db_session.commit()

    # Simulate Redis publication failure: relay lease expires without settlement
    await db_session.execute(
        text("UPDATE evaluation_job_outbox SET relay_expires_at = clock_timestamp() - interval '1 second' WHERE id = :id"),
        {"id": outbox_entry.id},
    )
    await db_session.commit()

    # Verify job is STILL safely queued in PostgreSQL
    await db_session.refresh(job)
    assert job.status == "queued"
    assert job.dispatch_generation == 2

    # Relay claims it again after Redis recovery and settles
    relay_token_2 = uuid.uuid4()
    claimed_rows_2 = await claim_outbox_batch(db=db_session, relay_token=relay_token_2, batch_size=10, organization_id=org.id)
    assert len(claimed_rows_2) == 1
    assert claimed_rows_2[0].id == outbox_entry.id
    await db_session.commit()

    settled = await settle_outbox_row(db=db_session, outbox_id=outbox_entry.id, relay_token=relay_token_2)
    assert settled is True
    await db_session.commit()


def test_celery_reaper_task_execution():
    """
    Test 18: Celery reaper task interface:
    Verifies that reap_stalled_evaluation_jobs_task runs cleanly as a Celery task.
    """
    res = reap_stalled_evaluation_jobs_task(batch_size=10)
    assert isinstance(res, dict)
    assert "total_candidates" in res
    assert "requeued_count" in res
    assert "exhausted_count" in res
    assert "cancelled_count" in res
    assert "skipped_count" in res

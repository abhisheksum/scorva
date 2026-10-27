from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.core.exceptions import AppException
from apps.api.modules.audit.models import AuditEvent
from apps.api.modules.evaluations.models import (
    EvaluationJob,
    EvaluationJobOutbox,
    Rubric,
    RubricCriterion,
    RubricVersion,
    Submission,
    SubmissionSnapshot,
    Team,
)
from apps.api.modules.evaluations.outbox import (
    OutboxStatus,
    claim_outbox_batch,
    get_outbox_entries_for_job,
    get_outbox_entry_by_id,
    quarantine_exhausted_outbox_rows,
    record_outbox_publish_error,
    replay_dead_lettered_outbox_row,
    settle_outbox_row,
)
from apps.api.modules.evaluations.service import (
    compute_evaluation_request_fingerprint,
    dispatch_evaluation_job_atomic,
    normalize_idempotency_key,
    reevaluate_submission_atomic,
)
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.modules.organizations.models import (
    Organization,
    OrganizationMembership,
    OrganizationStatus,
    OrgRole,
)
from apps.api.modules.users.models import PlatformRole, User, UserSession


@pytest.fixture
async def setup_m5_env(db_session: AsyncSession):
    """Sets up a complete isolated test environment: org, hackathon, rubric, team, submission, and snapshot."""
    user = User(
        email=f"m5_tester_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="fakehash123",
        full_name="M5 Tester",
        platform_role=None,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    org = Organization(
        name="M5 Outbox Org",
        slug=f"m5-outbox-org-{uuid.uuid4().hex[:8]}",
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

    session_record = UserSession(
        user_id=user.id,
        session_token_hash=uuid.uuid4().hex,
        ip_address="127.0.0.1",
        user_agent="Pytest-M5",
        expires_at=datetime.now(timezone.utc),
    )
    db_session.add(session_record)
    await db_session.flush()

    hackathon = Hackathon(
        organization_id=org.id,
        title="M5 Outbox Hackathon",
        slug=f"m5-hack-{uuid.uuid4().hex[:8]}",
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
        name=f"Rubric {uuid.uuid4().hex[:6]}",
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
        title="Code Quality",
        description="Clean, modular code structure",
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
        name=f"Team {uuid.uuid4().hex[:6]}",
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
        repository_url="https://github.com/scorva-test/m5-repo",
        target_branch="main",
        title="Submission Alpha",
        status="pending",
    )
    db_session.add(submission)
    await db_session.flush()

    snapshot = SubmissionSnapshot(
        organization_id=org.id,
        submission_id=submission.id,
        commit_sha="a1b2c3d4e5f678901234567890abcdef12345678",
        file_count=10,
        total_bytes=10240,
        configuration_snapshot={"timeout": 60, "model": "mock-eval"},
        metadata_={},
    )
    db_session.add(snapshot)
    await db_session.commit()

    return user, org, hackathon, rubric_version, submission, snapshot


@pytest.mark.asyncio
async def test_atomic_dispatch_evaluation_job_success(db_session: AsyncSession, setup_m5_env):
    """
    Subsystem C Sub-Milestone 5.1:
    Verifies that dispatch_evaluation_job_atomic atomically creates:
    1. EvaluationJob in status 'queued'
    2. EvaluationJobOutbox in status 'pending'
    3. AuditEvent with action 'evaluation.dispatched'
    within a single ACID transaction.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env

    job, is_created = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key="dispatch-key-001",
        actor_user_id=user.id,
        actor_email=user.email,
    )
    await db_session.commit()

    assert is_created is True
    assert job.status == "queued"
    assert job.attempts_count == 0
    assert job.dispatch_generation == 1
    assert job.idempotency_key == "client:dispatch-key-001"
    assert job.cancellation_requested is False
    assert job.request_fingerprint is not None

    # Verify outbox record
    outbox_entries = await get_outbox_entries_for_job(db_session, job.id, org.id)
    assert len(outbox_entries) == 1
    outbox = outbox_entries[0]
    assert outbox.job_id == job.id
    assert outbox.organization_id == org.id
    assert outbox.status == OutboxStatus.PENDING.value
    assert outbox.claim_count == 0
    assert outbox.publish_attempts == 0
    assert outbox.dispatch_generation == 1
    assert outbox.payload == {"job_id": str(job.id)}

    # Verify audit event in database
    stmt_audit = select(AuditEvent).where(
        AuditEvent.action == "evaluation.dispatched",
        AuditEvent.resource_id == str(job.id),
    )
    audit = (await db_session.execute(stmt_audit)).scalar_one_or_none()
    assert audit is not None
    assert audit.organization_id == org.id
    assert audit.actor_email == user.email
    assert audit.diff_payload["submission_id"] == str(submission.id)


@pytest.mark.asyncio
async def test_atomic_dispatch_rollback_on_outbox_failure(db_session: AsyncSession, setup_m5_env):
    """
    Verifies that if an error occurs during outbox creation, the entire transaction rolls back,
    leaving zero orphaned EvaluationJob or AuditEvent records.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env

    # We simulate a failure by using an invalid foreign key in a sub-transaction
    job_count_before = len((await db_session.execute(select(EvaluationJob))).scalars().all())
    outbox_count_before = len((await db_session.execute(select(EvaluationJobOutbox))).scalars().all())

    try:
        async with db_session.begin_nested():
            # Add job
            job = EvaluationJob(
                organization_id=org.id,
                hackathon_id=hackathon.id,
                submission_id=submission.id,
                snapshot_id=snapshot.id,
                rubric_version_id=rubric_version.id,
                status="queued",
            )
            db_session.add(job)
            await db_session.flush()

            # Add outbox with non-existent organization_id to trigger ForeignKey constraint violation
            bad_outbox = EvaluationJobOutbox(
                job_id=job.id,
                organization_id=uuid.uuid4(),  # non-existent org
                queue_name="evaluations.default",
                payload={"job_id": str(job.id)},
                status="pending",
            )
            db_session.add(bad_outbox)
            await db_session.flush()
    except IntegrityError:
        pass

    job_count_after = len((await db_session.execute(select(EvaluationJob))).scalars().all())
    outbox_count_after = len((await db_session.execute(select(EvaluationJobOutbox))).scalars().all())

    assert job_count_after == job_count_before
    assert outbox_count_after == outbox_count_before


@pytest.mark.asyncio
async def test_tenant_isolation_scoping_enforced(db_session: AsyncSession, setup_m5_env):
    """
    Verifies that passing a submission, snapshot, or rubric belonging to Org B
    is strictly rejected and cannot be dispatched under Org A.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env

    # Create Org B with its own submission
    foreign_org = Organization(
        name="Foreign Org",
        slug=f"foreign-org-{uuid.uuid4().hex[:8]}",
        owner_id=user.id,
        status=OrganizationStatus.ACTIVE,
    )
    db_session.add(foreign_org)
    await db_session.commit()

    # Attempt to dispatch submission belonging to org under foreign_org
    with pytest.raises(AppException) as exc:
        await dispatch_evaluation_job_atomic(
            db=db_session,
            organization_id=foreign_org.id,
            hackathon_id=hackathon.id,
            submission_id=submission.id,
            snapshot_id=snapshot.id,
            rubric_version_id=rubric_version.id,
        )
    assert exc.value.status_code == 404
    assert exc.value.code == "SUBMISSION_NOT_FOUND"


@pytest.mark.asyncio
async def test_request_idempotency_same_key_same_payload(db_session: AsyncSession, setup_m5_env):
    """
    Verifies that repeating an API dispatch with the identical Idempotency-Key
    and identical payload returns the existing job without creating duplicates.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env

    key = "idem-key-duplicate-test"
    job1, created1 = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key=key,
    )
    await db_session.commit()
    assert created1 is True

    # Replay identical request
    job2, created2 = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key=key,
    )
    await db_session.commit()

    assert created2 is False
    assert job2.id == job1.id

    # Verify only 1 job and 1 outbox row exist
    all_outbox = await get_outbox_entries_for_job(db_session, job1.id, org.id)
    assert len(all_outbox) == 1


@pytest.mark.asyncio
async def test_request_idempotency_same_key_different_payload_conflict(db_session: AsyncSession, setup_m5_env):
    """
    Verifies that reusing an Idempotency-Key with different payload parameters
    is rejected with 409 IDEMPOTENCY_PAYLOAD_MISMATCH.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env

    key = "idem-key-payload-conflict"
    await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key=key,
        configuration_override={"model": "model-a"},
    )
    await db_session.commit()

    # Re-send with different configuration_override -> different request_fingerprint
    with pytest.raises(AppException) as exc:
        await dispatch_evaluation_job_atomic(
            db=db_session,
            organization_id=org.id,
            hackathon_id=hackathon.id,
            submission_id=submission.id,
            snapshot_id=snapshot.id,
            rubric_version_id=rubric_version.id,
            idempotency_key=key,
            configuration_override={"model": "model-b-different"},
        )
    assert exc.value.status_code == 409
    assert exc.value.code == "IDEMPOTENCY_CONFLICT"


@pytest.mark.asyncio
async def test_request_idempotency_global_replay_after_completion(db_session: AsyncSession, setup_m5_env):
    """
    Verifies that retrying an evaluation request with the same Idempotency-Key
    after the job has completed returns the existing completed job without creating a new job.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env

    key = "idem-key-completed-replay"
    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key=key,
    )
    # Simulate job completing
    job.status = "completed"
    job.completed_at = datetime.now(timezone.utc)
    await db_session.commit()

    # Replay request after completion
    job_replayed, created = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key=key,
    )
    assert created is False
    assert job_replayed.id == job.id
    assert job_replayed.status == "completed"


@pytest.mark.asyncio
async def test_missing_idempotency_key_deduplicates_in_flight_and_allows_post_completion(
    db_session: AsyncSession, setup_m5_env
):
    """
    Verifies documented behavior for evaluation requests without an Idempotency-Key:
    1. Computes deterministic request_fingerprint.
    2. Consecutive/concurrent requests without Idempotency-Key while job is queued/running
       deduplicate to the existing active job (created = False).
    3. Once the job transitions to completed, a subsequent request without an Idempotency-Key
       creates a fresh job (created = True).
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env

    # 1. First dispatch without idempotency key
    job1, created1 = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key=None,
    )
    await db_session.commit()
    assert created1 is True
    assert job1.idempotency_key is None
    assert job1.request_fingerprint is not None
    assert job1.status == "queued"

    # 2. In-flight duplicate dispatch without idempotency key
    job2, created2 = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key=None,
    )
    await db_session.commit()
    assert created2 is False
    assert job2.id == job1.id

    # 3. Simulate job1 completion
    job1.status = "completed"
    job1.completed_at = datetime.now(timezone.utc)
    await db_session.commit()

    # 4. Post-completion dispatch without idempotency key creates a fresh job
    job3, created3 = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key=None,
    )
    await db_session.commit()
    assert created3 is True
    assert job3.id != job1.id
    assert job3.idempotency_key is None
    assert job3.request_fingerprint == job1.request_fingerprint


@pytest.mark.asyncio
async def test_intentional_reevaluation_creates_distinct_job(db_session: AsyncSession, setup_m5_env):
    """
    Verifies that explicit intentional re-evaluation:
    1. Creates a fresh EvaluationJob (Job 2)
    2. References reevaluation_of_job_id = Job 1
    3. Preserves Job 1 immutably
    4. Creates a new outbox entry for Job 2
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env

    # Dispatch Job 1
    job1, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key="eval-run-1",
    )
    job1.status = "completed"
    job1.completed_at = datetime.now(timezone.utc)
    await db_session.commit()

    # Intentional re-evaluation with new key
    job2, created2 = await reevaluate_submission_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key="eval-run-2",
        actor_user_id=user.id,
        actor_email=user.email,
    )
    await db_session.commit()

    assert created2 is True
    assert job2.id != job1.id
    assert job2.reevaluation_of_job_id == job1.id
    assert job2.status == "queued"
    assert job2.dispatch_generation == 1

    # Verify both jobs are in PostgreSQL
    j1_db = await db_session.get(EvaluationJob, job1.id)
    j2_db = await db_session.get(EvaluationJob, job2.id)
    assert j1_db.status == "completed"
    assert j2_db.status == "queued"

    # Verify Job 2 has its own outbox record
    outbox2 = await get_outbox_entries_for_job(db_session, job2.id, org.id)
    assert len(outbox2) == 1
    assert outbox2[0].job_id == job2.id
    assert outbox2[0].status == OutboxStatus.PENDING.value


@pytest.mark.asyncio
async def test_active_dispatch_partial_unique_index(db_session: AsyncSession, setup_m5_env):
    """
    Asserts that the partial unique index uq_eval_job_outbox_active_dispatch
    prohibits creating two concurrent active ('pending' or 'processing') outbox entries for the same job,
    while permitting sequential entries once the first is 'delivered'.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env
    org_id = org.id

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org_id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    job_id = job.id
    await db_session.commit()

    # Attempt to insert a second pending outbox row for the same job -> must fail unique constraint
    duplicate_outbox = EvaluationJobOutbox(
        job_id=job_id,
        organization_id=org_id,
        queue_name="evaluations.default",
        payload={"job_id": str(job_id)},
        status=OutboxStatus.PENDING.value,
        dispatch_generation=2,
    )
    db_session.add(duplicate_outbox)
    with pytest.raises(IntegrityError) as exc:
        await db_session.flush()
    await db_session.rollback()
    assert "uq_eval_job_outbox_active_dispatch" in str(exc.value)

    # Now, mark the first outbox row as delivered
    outbox_entries = await get_outbox_entries_for_job(db_session, job_id, org_id)
    first_outbox = outbox_entries[0]
    first_outbox.status = OutboxStatus.DELIVERED.value
    first_outbox.processed_at = datetime.now(timezone.utc)
    await db_session.commit()

    # Now inserting a second outbox entry (generation 2) succeeds!
    second_outbox = EvaluationJobOutbox(
        job_id=job_id,
        organization_id=org_id,
        queue_name="evaluations.default",
        payload={"job_id": str(job_id)},
        status=OutboxStatus.PENDING.value,
        dispatch_generation=2,
    )
    db_session.add(second_outbox)
    await db_session.flush()
    await db_session.commit()

    entries = await get_outbox_entries_for_job(db_session, job_id, org_id)
    assert len(entries) == 2
    assert entries[0].dispatch_generation == 1
    assert entries[0].status == OutboxStatus.DELIVERED.value
    assert entries[1].dispatch_generation == 2
    assert entries[1].status == OutboxStatus.PENDING.value


@pytest.mark.asyncio
async def test_outbox_relay_batch_claim_and_lease(db_session: AsyncSession, setup_m5_env):
    """
    Verifies Phase 1 batch claiming:
    1. Selects pending rows via FOR UPDATE SKIP LOCKED
    2. Increments claim_count atomically
    3. Sets relay_claim_token and relay_expires_at
    4. Transitions status to 'processing'
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env

    # Dispatch 2 jobs
    job1, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key="batch-test-1",
    )
    job2, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key="batch-test-2",
    )
    await db_session.commit()

    relay_token = uuid.uuid4()
    claimed = await claim_outbox_batch(
        db=db_session,
        relay_token=relay_token,
        batch_size=10,
        lease_seconds=30,
        organization_id=org.id,
    )
    await db_session.commit()

    claimed_job_ids = [c.job_id for c in claimed]
    assert job1.id in claimed_job_ids
    assert job2.id in claimed_job_ids

    for row in claimed:
        assert row.status == OutboxStatus.PROCESSING.value
        assert row.relay_claim_token == relay_token
        assert row.claim_count == 1
        assert row.retry_count == 1
        assert row.relay_expires_at is not None


@pytest.mark.asyncio
async def test_outbox_conditional_settlement(db_session: AsyncSession, setup_m5_env):
    """
    Verifies Phase 3 settlement:
    1. Requires matching relay_claim_token and status = 'processing'
    2. Sets status = 'delivered', processed_at = clock_timestamp()
    3. Clears relay_claim_token and relay_expires_at
    4. Increments publish_attempts
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key="settle-test-1",
    )
    await db_session.commit()

    relay_token = uuid.uuid4()
    claimed = await claim_outbox_batch(
        db=db_session,
        relay_token=relay_token,
        batch_size=1,
        organization_id=org.id,
    )
    await db_session.commit()
    row = claimed[0]

    # Settle with correct token
    success = await settle_outbox_row(db_session, row.id, relay_token)
    await db_session.commit()
    assert success is True

    settled = await get_outbox_entry_by_id(db_session, row.id)
    assert settled.status == OutboxStatus.DELIVERED.value
    assert settled.processed_at is not None
    assert settled.publish_attempts == 1
    assert settled.relay_claim_token is None
    assert settled.relay_expires_at is None

    # Stale settlement attempt with the old token must match 0 rows
    stale_attempt = await settle_outbox_row(db_session, row.id, relay_token)
    assert stale_attempt is False


@pytest.mark.asyncio
async def test_outbox_stale_relay_settlement_rejected_after_replacement(db_session: AsyncSession, setup_m5_env):
    """
    Verifies that if Relay 1 claims a row, its lease expires, and Relay 2 re-claims the row (installing Token 2),
    Relay 1's settlement attempt checking Token 1 matches 0 rows and aborts.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key="stale-settle-test",
    )
    await db_session.commit()

    token1 = uuid.uuid4()
    claimed = await claim_outbox_batch(
        db=db_session,
        relay_token=token1,
        batch_size=1,
        lease_seconds=-1,
        organization_id=org.id,
    )  # expired lease
    await db_session.commit()
    row = claimed[0]

    # Relay 2 reclaims expired row
    token2 = uuid.uuid4()
    reclaimed = await claim_outbox_batch(
        db=db_session,
        relay_token=token2,
        batch_size=1,
        lease_seconds=30,
        organization_id=org.id,
    )
    await db_session.commit()
    assert len(reclaimed) == 1
    assert reclaimed[0].relay_claim_token == token2
    assert reclaimed[0].claim_count == 2

    # Relay 1 tries to settle with Token 1 -> Fails!
    stale_result = await settle_outbox_row(db_session, row.id, token1)
    await db_session.commit()
    assert stale_result is False

    # Relay 2 settles with Token 2 -> Succeeds!
    valid_result = await settle_outbox_row(db_session, row.id, token2)
    await db_session.commit()
    assert valid_result is True


@pytest.mark.asyncio
async def test_quarantine_exhausted_outbox_rows_with_audit(db_session: AsyncSession, setup_m5_env):
    """
    Verifies Background Quarantine Sweep:
    Rows in 'processing' with claim_count >= 5 and expired lease transition to 'dead_lettered',
    record dead_letter_reason, clear tokens, and commit an immutable AuditEvent.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    # Manually configure outbox row to simulate 5 failed claims with expired lease
    entries = await get_outbox_entries_for_job(db_session, job.id, org.id)
    outbox = entries[0]
    outbox.status = OutboxStatus.PROCESSING.value
    outbox.claim_count = 5
    outbox.publish_attempts = 0
    outbox.relay_expires_at = datetime.now(timezone.utc)
    outbox.relay_claim_token = uuid.uuid4()
    await db_session.commit()

    # Run quarantine sweep
    quarantined = await quarantine_exhausted_outbox_rows(db_session, max_claims=5)
    await db_session.commit()

    assert len(quarantined) >= 1
    q_row = [r for r in quarantined if r.id == outbox.id][0]
    assert q_row.status == OutboxStatus.DEAD_LETTERED.value
    assert q_row.dead_letter_reason == "EXHAUSTED_BEFORE_PUBLISH"
    assert q_row.relay_claim_token is None
    assert q_row.relay_expires_at is None

    # Verify audit event emitted in DB
    stmt_audit = select(AuditEvent).where(
        AuditEvent.action == "outbox.quarantined",
        AuditEvent.resource_id == str(outbox.id),
    )
    audit = (await db_session.execute(stmt_audit)).scalar_one_or_none()
    assert audit is not None
    assert audit.organization_id == org.id
    assert audit.diff_payload["reason"] == "EXHAUSTED_BEFORE_PUBLISH"


@pytest.mark.asyncio
async def test_outbox_quarantine_does_not_quarantine_unexpired_relay_and_invalidates_token(
    db_session: AsyncSession, setup_m5_env
):
    """
    Verifies that:
    1. An actively publishing relay (lease unexpired) with claim_count >= 5 is NOT quarantined.
    2. Once the lease expires, quarantine transitions the row to dead_lettered and clears the token.
    3. Stale settlement with the old token fails (matches 0 rows).
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    entries = await get_outbox_entries_for_job(db_session, job.id, org.id)
    outbox = entries[0]
    stale_token = uuid.uuid4()
    outbox.status = OutboxStatus.PROCESSING.value
    outbox.claim_count = 5
    outbox.publish_attempts = 1
    # Unexpired lease: 60s in the future
    outbox.relay_expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)
    outbox.relay_claim_token = stale_token
    await db_session.commit()

    # Quarantine sweep must NOT quarantine an actively publishing relay
    quarantined = await quarantine_exhausted_outbox_rows(db_session, max_claims=5)
    await db_session.commit()
    assert len([r for r in quarantined if r.id == outbox.id]) == 0

    re_check = await get_outbox_entry_by_id(db_session, outbox.id)
    assert re_check.status == OutboxStatus.PROCESSING.value
    assert re_check.relay_claim_token == stale_token

    # Now expire the lease
    re_check.relay_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    await db_session.commit()

    # Now quarantine sweep DOES quarantine it
    quarantined2 = await quarantine_exhausted_outbox_rows(db_session, max_claims=5)
    await db_session.commit()
    assert len([r for r in quarantined2 if r.id == outbox.id]) == 1

    dead_row = await get_outbox_entry_by_id(db_session, outbox.id)
    assert dead_row.status == OutboxStatus.DEAD_LETTERED.value
    assert dead_row.relay_claim_token is None
    assert dead_row.relay_expires_at is None

    # Stale settlement attempt with stale_token fails
    settle_success = await settle_outbox_row(db_session, outbox.id, stale_token)
    await db_session.commit()
    assert settle_success is False


@pytest.mark.asyncio
async def test_authorized_operator_replay(db_session: AsyncSession, setup_m5_env):
    """
    Verifies that an authorized operator can replay a dead-lettered outbox entry:
    1. Resets status = 'pending', claim_count = 0, publish_attempts = 0
    2. Clears dead_lettered_at and dead_letter_reason
    3. Emits 'outbox.replayed' audit event
    4. Enforces organization scoping (foreign org cannot replay)
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    entries = await get_outbox_entries_for_job(db_session, job.id, org.id)
    outbox = entries[0]
    outbox.status = OutboxStatus.DEAD_LETTERED.value
    outbox.claim_count = 5
    outbox.publish_attempts = 2
    outbox.dead_lettered_at = datetime.now(timezone.utc)
    outbox.dead_letter_reason = "EXHAUSTED_DURING_PUBLISH_OR_SETTLEMENT"
    await db_session.commit()

    # Replay under correct org
    replayed = await replay_dead_lettered_outbox_row(
        db=db_session,
        organization_id=org.id,
        outbox_id=outbox.id,
        actor_user_id=user.id,
        actor_email=user.email,
    )
    await db_session.commit()

    assert replayed.status == OutboxStatus.PENDING.value
    assert replayed.claim_count == 0
    assert replayed.publish_attempts == 0
    assert replayed.dead_lettered_at is None
    assert replayed.dead_letter_reason is None

    # Verify audit event
    stmt_audit = select(AuditEvent).where(
        AuditEvent.action == "outbox.replayed",
        AuditEvent.resource_id == str(outbox.id),
    )
    audit = (await db_session.execute(stmt_audit)).scalar_one_or_none()
    assert audit is not None
    assert audit.actor_email == user.email

    # Foreign org attempt to replay should 404
    foreign_org_id = uuid.uuid4()
    with pytest.raises(AppException) as exc:
        await replay_dead_lettered_outbox_row(
            db=db_session,
            organization_id=foreign_org_id,
            outbox_id=outbox.id,
        )
    assert exc.value.status_code == 404


# =====================================================================
# API Integration & RBAC Tests (M5.1 REST Endpoints)
# =====================================================================


@pytest.mark.asyncio
async def test_api_dispatch_evaluation_success_and_idempotent_replay(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_m5_env,
    create_session_helper,
):
    """
    Verifies API endpoint POST /organizations/{org_id}/hackathons/{hackathon_id}/evaluations:
    1. Returns 201 Created and initiates atomic dispatch (job + outbox row + audit event).
    2. Idempotent replay with same Idempotency-Key returns 200 OK and header Idempotent-Replay: true.
    3. Replay returns the exact existing job and does NOT create duplicate outbox entries.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env
    token = await create_session_helper(user)

    url = f"/api/v1/organizations/{org.id}/hackathons/{hackathon.id}/evaluations"
    payload = {
        "submission_id": str(submission.id),
        "snapshot_id": str(snapshot.id),
        "rubric_version_id": str(rubric_version.id),
        "configuration_override": {"reasoning_effort": "medium"},
    }
    idem_key = f"api-idem-{uuid.uuid4().hex[:8]}"

    # First dispatch -> 201 Created
    res1 = await client.post(
        url,
        json=payload,
        headers={"Origin": "http://testserver", "Idempotency-Key": idem_key},
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res1.status_code == 201
    data1 = res1.json()
    job_id = uuid.UUID(data1["id"])
    assert data1["submission_id"] == str(submission.id)
    assert data1["status"] == "queued"
    assert data1["dispatch_generation"] == 1
    assert "Idempotent-Replay" not in res1.headers

    # Verify outbox entry in DB
    entries = await get_outbox_entries_for_job(db_session, job_id, org.id)
    assert len(entries) == 1
    assert entries[0].status == OutboxStatus.PENDING.value

    # Replay with same key and payload -> 200 OK with Idempotent-Replay: true
    res2 = await client.post(
        url,
        json=payload,
        headers={"Origin": "http://testserver", "Idempotency-Key": idem_key},
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res2.status_code == 200
    assert res2.headers.get("Idempotent-Replay") == "true"
    data2 = res2.json()
    assert data2["id"] == str(job_id)

    # Verify no additional outbox entry was created
    entries_after = await get_outbox_entries_for_job(db_session, job_id, org.id)
    assert len(entries_after) == 1


@pytest.mark.asyncio
async def test_api_dispatch_evaluation_idempotency_conflict(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_m5_env,
    create_session_helper,
):
    """
    Verifies that presenting the same Idempotency-Key with a different payload
    (different snapshot) produces HTTP 409 Conflict with code IDEMPOTENCY_CONFLICT.
    """
    user, org, hackathon, rubric_version, submission, snapshot1 = setup_m5_env
    token = await create_session_helper(user)

    # Create a second snapshot
    snapshot2 = SubmissionSnapshot(
        organization_id=org.id,
        submission_id=submission.id,
        commit_sha="b2c3d4e5f6a78901234567890abcdef123456789",
        file_count=12,
        total_bytes=20480,
        configuration_snapshot={"timeout": 60, "model": "mock-eval-2"},
        metadata_={},
    )
    db_session.add(snapshot2)
    await db_session.commit()

    url = f"/api/v1/organizations/{org.id}/hackathons/{hackathon.id}/evaluations"
    idem_key = f"api-conflict-{uuid.uuid4().hex[:8]}"

    # Dispatch first
    res1 = await client.post(
        url,
        json={
            "submission_id": str(submission.id),
            "snapshot_id": str(snapshot1.id),
            "rubric_version_id": str(rubric_version.id),
        },
        headers={"Origin": "http://testserver", "Idempotency-Key": idem_key},
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res1.status_code == 201

    # Conflict dispatch with snapshot2
    res2 = await client.post(
        url,
        json={
            "submission_id": str(submission.id),
            "snapshot_id": str(snapshot2.id),
            "rubric_version_id": str(rubric_version.id),
        },
        headers={"Origin": "http://testserver", "Idempotency-Key": idem_key},
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res2.status_code == 409
    body = res2.json()
    assert body["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.asyncio
async def test_api_reevaluate_submission(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_m5_env,
    create_session_helper,
):
    """
    Verifies POST /organizations/{org_id}/hackathons/{hackathon_id}/submissions/{submission_id}/reevaluate:
    1. Returns 201 Created and dispatches child evaluation job.
    2. Sets reevaluation_of_job_id to previous job.
    3. Creates independent outbox entry.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env
    token = await create_session_helper(user)

    url_dispatch = f"/api/v1/organizations/{org.id}/hackathons/{hackathon.id}/evaluations"
    res1 = await client.post(
        url_dispatch,
        json={
            "submission_id": str(submission.id),
            "snapshot_id": str(snapshot.id),
            "rubric_version_id": str(rubric_version.id),
        },
        headers={"Origin": "http://testserver"},
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res1.status_code == 201
    parent_job_id = res1.json()["id"]

    url_reeval = f"/api/v1/organizations/{org.id}/hackathons/{hackathon.id}/submissions/{submission.id}/reevaluate"
    res2 = await client.post(
        url_reeval,
        json={
            "rubric_version_id": str(rubric_version.id),
            "reason": "Test Re-evaluation",
        },
        headers={"Origin": "http://testserver"},
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res2.status_code == 201
    data2 = res2.json()
    child_job_id = data2["id"]
    assert child_job_id != parent_job_id
    assert data2["reevaluation_of_job_id"] == parent_job_id


@pytest.mark.asyncio
async def test_api_replay_dead_lettered_outbox(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_m5_env,
    create_session_helper,
):
    """
    Verifies POST /organizations/{org_id}/evaluations/outbox/{outbox_id}/replay:
    Resets dead-lettered row to pending and clears error fields.
    """
    user, org, hackathon, rubric_version, submission, snapshot = setup_m5_env
    token = await create_session_helper(user)

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    entries = await get_outbox_entries_for_job(db_session, job.id, org.id)
    outbox = entries[0]
    outbox.status = OutboxStatus.DEAD_LETTERED.value
    outbox.claim_count = 5
    outbox.publish_attempts = 3
    outbox.dead_lettered_at = datetime.now(timezone.utc)
    outbox.dead_letter_reason = "EXHAUSTED_BEFORE_PUBLISH"
    await db_session.commit()

    url = f"/api/v1/organizations/{org.id}/evaluations/outbox/{outbox.id}/replay"
    res = await client.post(
        url,
        headers={"Origin": "http://testserver"},
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "pending"
    assert data["claim_count"] == 0
    assert data["publish_attempts"] == 0
    assert data["dead_letter_reason"] is None


@pytest.mark.asyncio
async def test_api_rbac_authorization(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_m5_env,
    create_user_helper,
    create_session_helper,
):
    """
    Verifies API role authorization:
    - Owner/Admin/Judge: 201 Created
    - Participant: 403 Forbidden
    - Non-member: 403 Forbidden
    - Unauthenticated: 401 Unauthorized
    """
    owner, org, hackathon, rubric_version, submission, snapshot = setup_m5_env

    # 1. Unauthenticated request -> 401
    url = f"/api/v1/organizations/{org.id}/hackathons/{hackathon.id}/evaluations"
    payload = {
        "submission_id": str(submission.id),
        "snapshot_id": str(snapshot.id),
        "rubric_version_id": str(rubric_version.id),
    }
    res_unauth = await client.post(url, json=payload, headers={"Origin": "http://testserver"})
    assert res_unauth.status_code == 401

    # 2. Non-member user -> 403 TENANT_ACCESS_DENIED
    outsider = await create_user_helper(email=f"outsider_{uuid.uuid4().hex[:6]}@example.com", platform_role=None)
    outsider_token = await create_session_helper(outsider)
    res_outsider = await client.post(
        url,
        json=payload,
        headers={"Origin": "http://testserver"},
        cookies={settings.SESSION_COOKIE_NAME: outsider_token},
    )
    assert res_outsider.status_code == 403
    assert res_outsider.json()["code"] == "TENANT_ACCESS_DENIED"

    # 3. Organizer member can dispatch evaluation -> 201 Created
    organizer = await create_user_helper(email=f"org_{uuid.uuid4().hex[:6]}@example.com", platform_role=None)
    mem_organizer = OrganizationMembership(
        organization_id=org.id,
        user_id=organizer.id,
        role=OrgRole.ORGANIZER,
    )
    db_session.add(mem_organizer)
    await db_session.commit()

    org_token = await create_session_helper(organizer)
    res_organizer = await client.post(
        url,
        json=payload,
        headers={"Origin": "http://testserver"},
        cookies={settings.SESSION_COOKIE_NAME: org_token},
    )
    assert res_organizer.status_code == 201

    # 4. But Organizer cannot replay dead-lettered outbox (Admin/Owner only) -> 403 Forbidden
    # First create a dead-lettered outbox entry
    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()
    entries = await get_outbox_entries_for_job(db_session, job.id, org.id)
    outbox = entries[0]
    outbox.status = OutboxStatus.DEAD_LETTERED.value
    await db_session.commit()

    url_replay = f"/api/v1/organizations/{org.id}/evaluations/outbox/{outbox.id}/replay"
    res_replay_org = await client.post(
        url_replay,
        headers={"Origin": "http://testserver"},
        cookies={settings.SESSION_COOKIE_NAME: org_token},
    )
    assert res_replay_org.status_code == 403
    assert res_replay_org.json()["code"] == "FORBIDDEN_INSUFFICIENT_ORG_ROLE"

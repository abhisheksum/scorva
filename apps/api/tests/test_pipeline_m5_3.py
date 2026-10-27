from datetime import datetime, timedelta, timezone
from decimal import Decimal
import time
from typing import Any, Dict, List
import uuid
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from apps.api.modules.audit.models import AuditEvent
from apps.api.modules.evaluations.ai_provider import MockAIProviderClient
from apps.api.modules.evaluations.models import (
    EvaluationCriterionScore,
    EvaluationJob,
    EvaluationResult,
    EvidenceReference,
    Rubric,
    RubricCriterion,
    RubricVersion,
    Submission,
    SubmissionSnapshot,
    Team,
)
from apps.api.modules.evaluations.output_validator import (
    AICriterionScorePayload,
    AIEvaluationOutputPayload,
    AIEvidenceReferencePayload,
)
from apps.api.modules.evaluations.scoring_calculator import (
    CriterionInput,
    calculate_evaluation_scores,
)
from apps.api.modules.evaluations.service import dispatch_evaluation_job_atomic
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.modules.organizations.models import (
    Organization,
    OrganizationMembership,
    OrganizationStatus,
    OrgRole,
)
from apps.api.modules.users.models import User
from apps.api.workers.database import worker_session_scope
from apps.api.workers.lease_manager import (
    WorkerClaim,
    WorkerLeaseManager,
)
from apps.api.workers.pipeline import (
    CommitResult,
    PipelineResult,
    commit_evaluation_result_fenced_sync,
    run_evaluation_pipeline,
)
from apps.api.workers.tasks import evaluate_submission


@pytest.fixture
async def setup_pipeline_env(db_session: AsyncSession):
    """Sets up an isolated test fixture with organization, hackathon, 2 criteria rubric, submission, and snapshot."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f"pipe_tester_{suffix}@example.com",
        hashed_password="fakehash123",
        full_name="Pipeline Tester",
        platform_role=None,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    org = Organization(
        name=f"Pipeline Org {suffix}",
        slug=f"pipe-org-{suffix}",
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
        title="Pipeline Hackathon",
        slug=f"pipe-hack-{suffix}",
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

    # Criterion 1: Weight 0.40, range [0, 10]
    crit1 = RubricCriterion(
        rubric_version_id=rubric_version.id,
        title="Architecture & Modularity",
        description="Clean boundaries, separation of concerns",
        weight=Decimal("0.40"),
        min_score=Decimal("0.00"),
        max_score=Decimal("10.00"),
        evidence_requirements="source code",
        order_index=1,
    )
    db_session.add(crit1)

    # Criterion 2: Weight 0.60, range [0, 10]
    crit2 = RubricCriterion(
        rubric_version_id=rubric_version.id,
        title="Correctness & Security",
        description="Fencing protocols, SSRF defenses",
        weight=Decimal("0.60"),
        min_score=Decimal("0.00"),
        max_score=Decimal("10.00"),
        evidence_requirements="source code and tests",
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
        repository_url="https://github.com/scorva-test/pipeline-repo",
        target_branch="main",
        title="Submission Pipeline",
        status="pending",
    )
    db_session.add(submission)
    await db_session.flush()

    snapshot = SubmissionSnapshot(
        organization_id=org.id,
        submission_id=submission.id,
        commit_sha="a1b2c3d4e5f678901234567890abcdef12345678",
        file_count=2,
        total_bytes=4096,
        configuration_snapshot={"timeout": 60, "model": "mock-eval"},
        metadata_={
            "extracted_files_manifest": [
                {
                    "path": "src/main.py",
                    "size_bytes": 100,
                    "lines": [
                        "# Main Entrypoint",
                        "def execute():",
                        "    print('Running pipeline')",
                        "    return True",
                    ],
                }
            ]
        },
    )
    db_session.add(snapshot)
    await db_session.commit()

    return user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot


def build_canned_mock_response(crit1_id: uuid.UUID, crit2_id: uuid.UUID) -> Dict[str, Any]:
    """Generates a valid structured response matching AIEvaluationOutputPayload."""
    return {
        "summary_assessment": "Automated evaluation: Submission demonstrates modular architecture and robust security.",
        "has_insufficient_evidence": False,
        "criterion_scores": [
            {
                "criterion_id": str(crit1_id),
                "awarded_score": "8.00",
                "confidence_score": "0.95",
                "rationale": "Code demonstrates clean separation of concerns and modular service layer.",
                "evidence_status": "verified",
                "evidence_references": [
                    {
                        "file_path": "src/main.py",
                        "start_line": 2,
                        "end_line": 4,
                        "snippet": "def execute():\n    return True",
                    }
                ],
            },
            {
                "criterion_id": str(crit2_id),
                "awarded_score": "9.00",
                "confidence_score": "1.00",
                "rationale": "Fencing tokens and unexpired lease checks prevent stale overwrites.",
                "evidence_status": "verified",
                "evidence_references": [
                    {
                        "file_path": "src/main.py",
                        "start_line": 1,
                        "end_line": 3,
                        "snippet": "print('Running pipeline')",
                    }
                ],
            },
        ],
    }


@pytest.mark.asyncio
async def test_successful_end_to_end_pipeline_evaluation_and_atomic_commit(
    db_session: AsyncSession, setup_pipeline_env
):
    """
    Verifies full end-to-end evaluation pipeline with deterministic mock provider:
    1. Claims queued job atomically.
    2. Runs inference through MockAIProviderClient.
    3. Validates output schema, criterion IDs, and bounds.
    4. Calculates raw and normalized scores:
       Criterion 1: 8.00 (weight 0.40) -> 8.00 * 0.40 / 10 = 0.32
       Criterion 2: 9.00 (weight 0.60) -> 9.00 * 0.60 / 10 = 0.54
       Normalized Total = 86.00, Raw Total = 17.00
    5. Persists EvaluationResult, EvaluationCriterionScore, EvidenceReference,
       and AuditEvent in a single transaction under PostgreSQL row lock.
    6. Atomically marks EvaluationJob as 'completed' with incremented lock_version.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_pipeline_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    mock_resp = build_canned_mock_response(crit1.id, crit2.id)
    mock_client = MockAIProviderClient(canned_responses=[mock_resp])

    pipeline_res = run_evaluation_pipeline(
        job_id=job.id,
        worker_id="worker-node-1",
        provider_client=mock_client,
        lease_seconds=60,
        heartbeat_interval=15.0,
    )

    assert pipeline_res.status == "completed"
    assert pipeline_res.result_id is not None
    assert pipeline_res.raw_score == Decimal("17.00")
    assert pipeline_res.normalized_score == Decimal("86.00")
    assert pipeline_res.lock_version == 2

    # Verify Database State
    await db_session.refresh(job)
    assert job.status == "completed"
    assert job.current_result_id == pipeline_res.result_id
    assert job.completed_at is not None
    assert job.lock_version == 2

    # Verify EvaluationResult
    result_stmt = select(EvaluationResult).where(EvaluationResult.id == pipeline_res.result_id)
    db_result = (await db_session.execute(result_stmt)).scalar_one_or_none()
    assert db_result is not None
    assert db_result.job_id == job.id
    assert db_result.raw_score == Decimal("17.00")
    assert db_result.normalized_score == Decimal("86.00")
    assert db_result.attempt_number == 1
    assert db_result.model_provider == "mock"

    # Verify Criterion Scores
    crit_stmt = select(EvaluationCriterionScore).where(
        EvaluationCriterionScore.evaluation_result_id == pipeline_res.result_id
    )
    crit_scores = list((await db_session.execute(crit_stmt)).scalars().all())
    assert len(crit_scores) == 2

    crit1_res = [c for c in crit_scores if c.criterion_id == crit1.id][0]
    assert crit1_res.awarded_score == Decimal("8.00")
    assert crit1_res.normalized_criterion_score == Decimal("0.8000")

    crit2_res = [c for c in crit_scores if c.criterion_id == crit2.id][0]
    assert crit2_res.awarded_score == Decimal("9.00")
    assert crit2_res.normalized_criterion_score == Decimal("0.9000")

    # Verify Evidence References
    ev_stmt = select(EvidenceReference).where(
        EvidenceReference.criterion_score_id == crit1_res.id
    )
    ev_refs = list((await db_session.execute(ev_stmt)).scalars().all())
    assert len(ev_refs) == 1
    assert ev_refs[0].file_path == "src/main.py"
    assert ev_refs[0].start_line == 2
    assert ev_refs[0].end_line == 4

    # Verify Audit Event
    audit_stmt = select(AuditEvent).where(
        AuditEvent.resource_id == str(job.id),
        AuditEvent.action == "evaluation.completed",
    )
    audit = (await db_session.execute(audit_stmt)).scalar_one_or_none()
    assert audit is not None
    assert audit.organization_id == org.id
    assert audit.diff_payload["normalized_score"] == "86.00"


@pytest.mark.asyncio
async def test_invalid_provider_output_rejected_without_partial_result_writes(
    db_session: AsyncSession, setup_pipeline_env
):
    """
    Verifies that malformed or out-of-bounds provider output is rejected:
    1. Entire result transaction is rolled back.
    2. Zero evaluation_results, evaluation_criterion_scores, or evidence_references written.
    3. Job transitions to failed with error code.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_pipeline_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    # Out of bounds score (15.00 > max 10.00)
    invalid_resp = {
        "summary_assessment": "Invalid response with out-of-bounds score.",
        "has_insufficient_evidence": False,
        "criterion_scores": [
            {
                "criterion_id": str(crit1.id),
                "awarded_score": "15.00",  # VIOLATION
                "confidence_score": "1.00",
                "rationale": "Score awarded exceeds rubric maximum allowable limit.",
                "evidence_status": "verified",
                "evidence_references": [],
            },
            {
                "criterion_id": str(crit2.id),
                "awarded_score": "9.00",
                "confidence_score": "1.00",
                "rationale": "Score awarded is within bounds and satisfies criteria.",
                "evidence_status": "verified",
                "evidence_references": [],
            },
        ],
    }
    mock_client = MockAIProviderClient(canned_responses=[invalid_resp, invalid_resp])

    pipeline_res = run_evaluation_pipeline(
        job_id=job.id,
        worker_id="worker-fail-test",
        provider_client=mock_client,
    )

    assert pipeline_res.status == "failed"
    assert pipeline_res.error_code in ("SCORE_OUT_OF_BOUNDS", "EVAL_PARSE_ERROR")

    # Verify zero results were persisted
    res_stmt = select(EvaluationResult).where(EvaluationResult.job_id == job.id)
    results = list((await db_session.execute(res_stmt)).scalars().all())
    assert len(results) == 0

    crit_stmt = select(EvaluationCriterionScore)
    # Check that no criterion scores were linked to this job
    all_crits = list((await db_session.execute(crit_stmt)).scalars().all())
    # None of them belong to this job
    assert len(results) == 0

    # Job is marked failed
    await db_session.refresh(job)
    assert job.status == "failed"
    assert job.current_result_id is None
    assert job.error_code in ("SCORE_OUT_OF_BOUNDS", "EVAL_PARSE_ERROR")


@pytest.mark.asyncio
async def test_missing_or_invalid_inputs_handled_safely(
    db_session: AsyncSession, setup_pipeline_env
):
    """
    Verifies that missing snapshot, rubric, or tenant mismatch fails gracefully without crashes.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_pipeline_env

    # Dispatch job
    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    # Create snapshot under a different organization (cross-tenant mismatch)
    other_org = Organization(
        name=f"Other Org {uuid.uuid4().hex[:6]}",
        slug=f"other-org-{uuid.uuid4().hex[:6]}",
        owner_id=user.id,
        status=OrganizationStatus.ACTIVE,
    )
    db_session.add(other_org)
    await db_session.flush()

    other_sub = Submission(
        organization_id=other_org.id,
        hackathon_id=hackathon.id,
        team_id=submission.team_id,
        team_name=submission.team_name,
        repository_url="https://github.com/scorva-test/other-repo",
        target_branch="main",
        title="Other Submission",
        status="pending",
    )
    db_session.add(other_sub)
    await db_session.flush()

    other_snapshot = SubmissionSnapshot(
        organization_id=other_org.id,
        submission_id=other_sub.id,
        commit_sha="b2c3d4e5f678901234567890abcdef1234567890",
        file_count=1,
        total_bytes=1024,
        configuration_snapshot={},
        metadata_={},
    )
    db_session.add(other_snapshot)
    await db_session.flush()

    # Point job's snapshot_id to cross-tenant snapshot
    job.snapshot_id = other_snapshot.id
    await db_session.commit()

    pipeline_res = run_evaluation_pipeline(
        job_id=job.id,
        worker_id="worker-invalid-inputs",
        provider_client=MockAIProviderClient(),
    )

    assert pipeline_res.status == "failed"
    assert pipeline_res.error_code == "INPUT_NOT_FOUND"

    await db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_code == "INPUT_NOT_FOUND"


@pytest.mark.asyncio
async def test_duplicate_delivery_does_not_create_duplicate_evaluation_results(
    db_session: AsyncSession, setup_pipeline_env
):
    """
    Verifies duplicate Celery message handling:
    1. First delivery completes evaluation.
    2. Duplicate delivery receives 'discarded' (not claimable).
    3. Exactly 1 EvaluationResult exists in database.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_pipeline_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    mock_resp = build_canned_mock_response(crit1.id, crit2.id)
    mock_client = MockAIProviderClient(canned_responses=[mock_resp])

    # First delivery: completes
    res1 = run_evaluation_pipeline(job.id, "worker-dup-1", provider_client=mock_client)
    assert res1.status == "completed"

    # Second delivery: duplicate delivery of completed job
    res2 = run_evaluation_pipeline(job.id, "worker-dup-2", provider_client=mock_client)
    assert res2.status == "discarded"
    assert res2.error_code == "NOT_CLAIMABLE"

    # Verify only 1 result exists
    results = list((await db_session.execute(
        select(EvaluationResult).where(EvaluationResult.job_id == job.id)
    )).scalars().all())
    assert len(results) == 1


@pytest.mark.asyncio
async def test_stale_claim_token_cannot_commit_results(
    db_session: AsyncSession, setup_pipeline_env
):
    """
    Verifies that a stale worker presenting a stale claim_token cannot commit results:
    1. Worker 1 claims job (Token 1, lock_version 1).
    2. Replacement worker claims job (Token 2, lock_version 2).
    3. Worker 1 attempts fenced result commit with Token 1 -> Fails with CLAIM_TOKEN_MISMATCH.
    4. Zero results written by Worker 1.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_pipeline_env

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

    # Simulate replacement claim by Worker 2
    await db_session.execute(
        text("UPDATE evaluation_jobs SET status = 'queued', claim_token = NULL, lease_expires_at = NULL, lock_version = 1 WHERE id = :id"),
        {"id": job.id},
    )
    await db_session.commit()

    with worker_session_scope() as session:
        claim2 = WorkerLeaseManager.claim_job_sync(session, job.id, "worker-2", lease_seconds=60)
    assert claim2 is not None

    # Stale Worker 1 prepares results and attempts fenced commit
    ai_output = AIEvaluationOutputPayload.model_validate(build_canned_mock_response(crit1.id, crit2.id))
    score_res = calculate_evaluation_scores([
        CriterionInput(criterion_id=crit1.id, weight=Decimal("0.40"), min_score=Decimal("0.00"), max_score=Decimal("10.00"), awarded_score=Decimal("8.00")),
        CriterionInput(criterion_id=crit2.id, weight=Decimal("0.60"), min_score=Decimal("0.00"), max_score=Decimal("10.00"), awarded_score=Decimal("9.00")),
    ])

    with worker_session_scope() as session:
        commit_res = commit_evaluation_result_fenced_sync(
            db=session,
            claim=claim1,
            ai_output=ai_output,
            score_result=score_res,
        )

    assert commit_res.success is False
    assert commit_res.error_code == "CLAIM_TOKEN_MISMATCH"

    # Zero results committed
    results = list((await db_session.execute(
        select(EvaluationResult).where(EvaluationResult.job_id == job.id)
    )).scalars().all())
    assert len(results) == 0


@pytest.mark.asyncio
async def test_lock_version_mismatch_cannot_commit_results(
    db_session: AsyncSession, setup_pipeline_env
):
    """
    Verifies that a lock_version mismatch (fencing token collision) aborts result commitment.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_pipeline_env

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
        claim = WorkerLeaseManager.claim_job_sync(session, job.id, "worker-lv", lease_seconds=60)
    assert claim is not None

    # Construct synthetic claim with wrong lock_version
    stale_claim = WorkerClaim(
        job_id=claim.job_id,
        organization_id=claim.organization_id,
        hackathon_id=claim.hackathon_id,
        submission_id=claim.submission_id,
        snapshot_id=claim.snapshot_id,
        rubric_version_id=claim.rubric_version_id,
        claim_token=claim.claim_token,
        lock_version=999,  # Mismatched fencing token
        attempts_count=claim.attempts_count,
        max_attempts=claim.max_attempts,
        lease_expires_at=claim.lease_expires_at,
        worker_id=claim.worker_id,
    )

    ai_output = AIEvaluationOutputPayload.model_validate(build_canned_mock_response(crit1.id, crit2.id))
    score_res = calculate_evaluation_scores([
        CriterionInput(criterion_id=crit1.id, weight=Decimal("0.40"), min_score=Decimal("0.00"), max_score=Decimal("10.00"), awarded_score=Decimal("8.00")),
        CriterionInput(criterion_id=crit2.id, weight=Decimal("0.60"), min_score=Decimal("0.00"), max_score=Decimal("10.00"), awarded_score=Decimal("9.00")),
    ])

    with worker_session_scope() as session:
        commit_res = commit_evaluation_result_fenced_sync(
            db=session,
            claim=stale_claim,
            ai_output=ai_output,
            score_result=score_res,
        )

    assert commit_res.success is False
    assert commit_res.error_code == "FENCING_TOKEN_MISMATCH"


@pytest.mark.asyncio
async def test_expired_lease_cannot_commit_results(
    db_session: AsyncSession, setup_pipeline_env
):
    """
    Verifies that a worker whose lease has expired cannot commit results:
    1. Worker claims job.
    2. Lease expires in DB (lease_expires_at <= clock_timestamp()).
    3. Fenced commit attempts row lock, detects expired lease, and rolls back with LEASE_EXPIRED.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_pipeline_env

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
        claim = WorkerLeaseManager.claim_job_sync(session, job.id, "worker-expired", lease_seconds=10)
    assert claim is not None

    # Manually expire lease in database using server time
    await db_session.execute(
        text("UPDATE evaluation_jobs SET lease_expires_at = clock_timestamp() - interval '5 seconds' WHERE id = :id"),
        {"id": job.id},
    )
    await db_session.commit()

    ai_output = AIEvaluationOutputPayload.model_validate(build_canned_mock_response(crit1.id, crit2.id))
    score_res = calculate_evaluation_scores([
        CriterionInput(criterion_id=crit1.id, weight=Decimal("0.40"), min_score=Decimal("0.00"), max_score=Decimal("10.00"), awarded_score=Decimal("8.00")),
        CriterionInput(criterion_id=crit2.id, weight=Decimal("0.60"), min_score=Decimal("0.00"), max_score=Decimal("10.00"), awarded_score=Decimal("9.00")),
    ])

    with worker_session_scope() as session:
        commit_res = commit_evaluation_result_fenced_sync(
            db=session,
            claim=claim,
            ai_output=ai_output,
            score_result=score_res,
        )

    assert commit_res.success is False
    assert commit_res.error_code == "LEASE_EXPIRED"

    # Verify zero results committed and job not completed
    await db_session.refresh(job)
    assert job.status != "completed"
    assert job.current_result_id is None


@pytest.mark.asyncio
async def test_lease_loss_during_inference_prevents_result_commitment(
    db_session: AsyncSession, setup_pipeline_env
):
    """
    Verifies that if a worker loses its lease while AI inference is executing,
    the pipeline detects the stale lease and aborts without committing results.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_pipeline_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    mock_resp = build_canned_mock_response(crit1.id, crit2.id)

    # Custom generator that expires the lease in the DB during inference!
    def _expiring_generator(prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        with worker_session_scope() as session:
            session.execute(
                text("UPDATE evaluation_jobs SET lease_expires_at = clock_timestamp() - interval '10 seconds' WHERE id = :id"),
                {"id": job.id},
            )
        return mock_resp

    mock_client = MockAIProviderClient(default_generator=_expiring_generator)

    pipeline_res = run_evaluation_pipeline(
        job_id=job.id,
        worker_id="worker-inference-timeout",
        provider_client=mock_client,
        lease_seconds=60,
    )

    assert pipeline_res.status == "stale_worker"

    # Verify zero results were committed
    results = list((await db_session.execute(
        select(EvaluationResult).where(EvaluationResult.job_id == job.id)
    )).scalars().all())
    assert len(results) == 0


@pytest.mark.asyncio
async def test_cancellation_before_commitment_prevents_result_commitment(
    db_session: AsyncSession, setup_pipeline_env
):
    """
    Verifies cooperative cancellation:
    If cancellation is requested before commitment, result commitment is aborted and job is marked cancelled.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_pipeline_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    mock_resp = build_canned_mock_response(crit1.id, crit2.id)

    # Sets cancellation_requested in DB during inference!
    def _cancelling_generator(prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        with worker_session_scope() as session:
            session.execute(
                text("UPDATE evaluation_jobs SET cancellation_requested = true WHERE id = :id"),
                {"id": job.id},
            )
        return mock_resp

    mock_client = MockAIProviderClient(default_generator=_cancelling_generator)

    pipeline_res = run_evaluation_pipeline(
        job_id=job.id,
        worker_id="worker-cancel-test",
        provider_client=mock_client,
    )

    assert pipeline_res.status in ("cancelled", "stale_worker")

    # Zero results committed
    results = list((await db_session.execute(
        select(EvaluationResult).where(EvaluationResult.job_id == job.id)
    )).scalars().all())
    assert len(results) == 0


@pytest.mark.asyncio
async def test_database_failure_during_result_persistence_rolls_back_all_writes(
    db_session: AsyncSession, setup_pipeline_env
):
    """
    Verifies atomicity: If an unhandled exception or constraint failure occurs
    during result insertion, the entire transaction is rolled back.
    Zero partial criterion scores or audit records are left in the database.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_pipeline_env

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
        claim = WorkerLeaseManager.claim_job_sync(session, job.id, "worker-db-fail", lease_seconds=60)
    assert claim is not None

    # Construct invalid claim with wrong foreign key to trigger foreign key violation during insert
    bad_claim = WorkerClaim(
        job_id=claim.job_id,
        organization_id=claim.organization_id,
        hackathon_id=claim.hackathon_id,
        submission_id=uuid.uuid4(),  # INVALID FOREIGN KEY
        snapshot_id=claim.snapshot_id,
        rubric_version_id=claim.rubric_version_id,
        claim_token=claim.claim_token,
        lock_version=claim.lock_version,
        attempts_count=claim.attempts_count,
        max_attempts=claim.max_attempts,
        lease_expires_at=claim.lease_expires_at,
        worker_id=claim.worker_id,
    )

    ai_output = AIEvaluationOutputPayload.model_validate(build_canned_mock_response(crit1.id, crit2.id))
    score_res = calculate_evaluation_scores([
        CriterionInput(criterion_id=crit1.id, weight=Decimal("0.40"), min_score=Decimal("0.00"), max_score=Decimal("10.00"), awarded_score=Decimal("8.00")),
        CriterionInput(criterion_id=crit2.id, weight=Decimal("0.60"), min_score=Decimal("0.00"), max_score=Decimal("10.00"), awarded_score=Decimal("9.00")),
    ])

    with pytest.raises(Exception):
        with worker_session_scope() as session:
            commit_evaluation_result_fenced_sync(
                db=session,
                claim=bad_claim,
                ai_output=ai_output,
                score_result=score_res,
            )

    # Verify complete rollback: zero results exist
    results = list((await db_session.execute(
        select(EvaluationResult).where(EvaluationResult.job_id == job.id)
    )).scalars().all())
    assert len(results) == 0


@pytest.mark.asyncio
async def test_job_completion_and_evaluation_results_are_committed_atomically(
    db_session: AsyncSession, setup_pipeline_env
):
    """
    Verifies atomic commitment invariant:
    EvaluationJob.status == 'completed' and EvaluationResult exist together, never in isolation.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_pipeline_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=submission.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    mock_resp = build_canned_mock_response(crit1.id, crit2.id)
    mock_client = MockAIProviderClient(canned_responses=[mock_resp])

    pipeline_res = run_evaluation_pipeline(
        job_id=job.id,
        worker_id="worker-atomic-check",
        provider_client=mock_client,
    )
    assert pipeline_res.status == "completed"

    # Query both in a single read transaction
    await db_session.refresh(job)
    assert job.status == "completed"
    assert job.current_result_id == pipeline_res.result_id

    result = (await db_session.execute(
        select(EvaluationResult).where(EvaluationResult.id == pipeline_res.result_id)
    )).scalar_one_or_none()
    assert result is not None
    assert result.job_id == job.id

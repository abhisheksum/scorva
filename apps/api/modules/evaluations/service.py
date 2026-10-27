from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import secrets
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from apps.api.core.exceptions import AppException
from apps.api.modules.audit.models import AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.evaluations.models import (
    EvaluationCriterionScore,
    EvaluationJob,
    EvaluationJobOutbox,
    EvaluationResult,
    EvidenceReference,
    Rubric,
    RubricCriterion,
    RubricVersion,
    Submission,
    SubmissionSnapshot,
    Team,
    TeamMember,
)
from apps.api.modules.hackathons.models import Hackathon
from apps.api.modules.evaluations.schemas import (
    CriterionScoreDetail,
    EvaluationJobListItem,
    EvaluationJobSummary,
    EvaluationResultDetail,
    EvaluationRubricSummary,
    EvaluationSnapshotSummary,
    EvidenceReferenceDetail,
    HackathonEvaluationSummaryResponse,
    PriorEvaluationRunSummary,
    SubmissionEvaluationTransparencyResponse,
    sanitize_error_for_display,
)
from apps.api.modules.evaluations.outbox import OutboxStatus
from apps.api.modules.evaluations.scoring_calculator import (
    CriterionInput,
    ScoringMode,
    validate_criteria_weights,
)


def generate_team_join_code() -> str:
    """Generate a secure, random 12-character alphanumeric join code."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(12))


async def create_rubric(
    db: AsyncSession,
    organization_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    name: str,
    description: Optional[str] = None,
    scoring_mode: str = ScoringMode.OFFSET_NORMALIZED.value,
) -> Rubric:
    """Create a new rubric container with an initial draft version (v1)."""
    # Check duplicate rubric name in hackathon
    stmt = select(Rubric).where(
        Rubric.hackathon_id == hackathon_id,
        Rubric.name == name,
    )
    res = await db.execute(stmt)
    if res.scalars().first():
        raise AppException(
            status_code=409,
            code="RUBRIC_NAME_CONFLICT",
            message=f"Rubric with name '{name}' already exists in this hackathon.",
        )

    rubric = Rubric(
        organization_id=organization_id,
        hackathon_id=hackathon_id,
        name=name,
        description=description,
        scoring_mode=scoring_mode,
    )
    db.add(rubric)
    await db.flush()

    # Create initial version 1 (draft)
    initial_version = RubricVersion(
        organization_id=organization_id,
        rubric_id=rubric.id,
        version_number=1,
        status="draft",
    )
    db.add(initial_version)
    await db.flush()

    return rubric


async def add_rubric_criterion(
    db: AsyncSession,
    rubric_version_id: uuid.UUID,
    title: str,
    description: str,
    weight: Decimal,
    min_score: Decimal = Decimal("0.00"),
    max_score: Decimal = Decimal("10.00"),
    evidence_requirements: str = "",
    order_index: int = 0,
    organization_id: Optional[uuid.UUID] = None,
) -> RubricCriterion:
    """Add a criterion to a draft rubric version with row locking and org scoping."""
    stmt = (
        select(RubricVersion)
        .where(RubricVersion.id == rubric_version_id)
        .with_for_update()
    )
    if organization_id is not None:
        stmt = stmt.where(RubricVersion.organization_id == organization_id)

    res = await db.execute(stmt)
    version = res.scalars().first()
    if not version:
        raise AppException(
            status_code=404,
            code="RUBRIC_VERSION_NOT_FOUND",
            message=f"Rubric version '{rubric_version_id}' not found.",
        )
    if version.status != "draft":
        raise AppException(
            status_code=400,
            code="RUBRIC_VERSION_FROZEN",
            message="Cannot add criteria to a published or archived rubric version.",
        )

    criterion = RubricCriterion(
        rubric_version_id=rubric_version_id,
        title=title,
        description=description,
        weight=weight,
        min_score=min_score,
        max_score=max_score,
        evidence_requirements=evidence_requirements,
        order_index=order_index,
    )
    db.add(criterion)
    await db.flush()
    return criterion


async def publish_rubric_version(
    db: AsyncSession,
    organization_id: uuid.UUID,
    rubric_version_id: uuid.UUID,
) -> RubricVersion:
    """
    Validate criteria weights and freeze a rubric version as 'published'.
    Once published, the PostgreSQL trigger blocks any modification to criteria.
    Acquires an exclusive row lock (FOR UPDATE) on the rubric version and criteria
    to prevent concurrent modifications or races.
    """
    stmt = (
        select(RubricVersion)
        .where(
            RubricVersion.id == rubric_version_id,
            RubricVersion.organization_id == organization_id,
        )
        .with_for_update()
    )
    res = await db.execute(stmt)
    version = res.scalars().first()
    if not version:
        raise AppException(
            status_code=404,
            code="RUBRIC_VERSION_NOT_FOUND",
            message=f"Rubric version '{rubric_version_id}' not found.",
        )

    if version.status == "published":
        raise AppException(
            status_code=400,
            code="RUBRIC_ALREADY_PUBLISHED",
            message="Rubric version is already published.",
        )

    if version.status == "archived":
        raise AppException(
            status_code=400,
            code="RUBRIC_VERSION_ARCHIVED",
            message="Cannot publish an archived rubric version.",
        )

    criteria_stmt = (
        select(RubricCriterion)
        .where(RubricCriterion.rubric_version_id == rubric_version_id)
        .order_by(RubricCriterion.order_index)
        .with_for_update()
    )
    criteria_res = await db.execute(criteria_stmt)
    criteria = list(criteria_res.scalars().all())

    if not criteria:
        raise AppException(
            status_code=400,
            code="RUBRIC_HAS_NO_CRITERIA",
            message="Cannot publish a rubric version with no criteria.",
        )

    # Validate weight sum invariant and uniqueness of criterion inputs
    criterion_inputs = [
        CriterionInput(
            criterion_id=str(c.id),
            weight=c.weight,
            min_score=c.min_score,
            max_score=c.max_score,
            awarded_score=c.min_score,
        )
        for c in criteria
    ]
    try:
        validate_criteria_weights(criterion_inputs)
    except ValueError as exc:
        raise AppException(
            status_code=400,
            code="INVALID_RUBRIC_WEIGHTS",
            message=str(exc),
        ) from exc

    version.status = "published"
    version.published_at = datetime.now(timezone.utc)
    await db.flush()
    return version


async def create_team(
    db: AsyncSession,
    organization_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
) -> Team:
    """Create a new team and add creator as leader."""
    # Check duplicate team name in hackathon
    stmt = select(Team).where(
        Team.hackathon_id == hackathon_id,
        Team.name == name,
    )
    res = await db.execute(stmt)
    if res.scalars().first():
        raise AppException(
            status_code=409,
            code="TEAM_NAME_CONFLICT",
            message=f"A team named '{name}' already exists in this hackathon.",
        )

    join_code = generate_team_join_code()
    team = Team(
        organization_id=organization_id,
        hackathon_id=hackathon_id,
        name=name,
        join_code=join_code,
        created_by_user_id=user_id,
    )
    db.add(team)
    await db.flush()

    # Add creator as leader
    member = TeamMember(
        team_id=team.id,
        user_id=user_id,
        role_in_team="leader",
    )
    db.add(member)
    await db.flush()

    return team


async def create_submission(
    db: AsyncSession,
    organization_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    team_id: uuid.UUID,
    team_name: str,
    repository_url: str,
    target_branch: str,
    title: str,
    description: Optional[str] = None,
) -> Submission:
    """Register a project repository submission."""
    # Check active unique repository_url in hackathon
    stmt = select(Submission).where(
        Submission.hackathon_id == hackathon_id,
        Submission.repository_url == repository_url,
        Submission.deleted_at.is_(None),
    )
    res = await db.execute(stmt)
    if res.scalars().first():
        raise AppException(
            status_code=409,
            code="REPOSITORY_ALREADY_SUBMITTED",
            message=f"Repository URL '{repository_url}' has already been submitted to this hackathon.",
        )

    submission = Submission(
        organization_id=organization_id,
        hackathon_id=hackathon_id,
        team_id=team_id,
        team_name=team_name,
        repository_url=repository_url,
        target_branch=target_branch,
        title=title,
        description=description,
        status="pending",
    )
    db.add(submission)
    await db.flush()
    return submission


async def create_submission_snapshot(
    db: AsyncSession,
    organization_id: uuid.UUID,
    submission_id: uuid.UUID,
    commit_sha: str,
    configuration_snapshot: Dict[str, Any],
    file_count: int = 0,
    total_bytes: int = 0,
    tree_sha: Optional[str] = None,
    snapshot_tarball_url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> SubmissionSnapshot:
    """Create an immutable snapshot of a submission frozen at evaluation time."""
    snapshot = SubmissionSnapshot(
        organization_id=organization_id,
        submission_id=submission_id,
        commit_sha=commit_sha,
        tree_sha=tree_sha,
        snapshot_tarball_url=snapshot_tarball_url,
        file_count=file_count,
        total_bytes=total_bytes,
        configuration_snapshot=configuration_snapshot,
        metadata_=metadata or {},
    )
    db.add(snapshot)
    await db.flush()
    return snapshot


def compute_evaluation_request_fingerprint(
    submission_id: uuid.UUID,
    rubric_version_id: uuid.UUID,
    snapshot_id: Optional[uuid.UUID] = None,
    configuration_override: Optional[Dict[str, Any]] = None,
) -> str:
    """Computes a deterministic SHA-256 canonical hash of the evaluation request parameters."""
    payload = {
        "submission_id": str(submission_id),
        "rubric_version_id": str(rubric_version_id),
        "snapshot_id": str(snapshot_id) if snapshot_id else None,
        "config": configuration_override or {},
    }
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def normalize_idempotency_key(key: Optional[str]) -> Optional[str]:
    """Validates and normalizes client-provided idempotency keys."""
    if not key:
        return None
    cleaned = key.strip()
    if not cleaned:
        return None
    if len(cleaned) > 120:
        raise AppException(
            status_code=400,
            code="INVALID_IDEMPOTENCY_KEY",
            message="Idempotency-Key header must not exceed 120 characters.",
        )
    return f"client:{cleaned}"


async def dispatch_evaluation_job_atomic(
    db: AsyncSession,
    organization_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    rubric_version_id: uuid.UUID,
    idempotency_key: Optional[str] = None,
    configuration_override: Optional[Dict[str, Any]] = None,
    actor_user_id: Optional[uuid.UUID] = None,
    actor_email: str = "system@scorva.local",
    actor_role: str = "system",
    ip_address: str = "127.0.0.1",
    user_agent: str = "Scorva-API/1.0",
    correlation_id: Optional[uuid.UUID] = None,
) -> tuple[EvaluationJob, bool]:
    """
    Subsystem C Sub-Milestone 5.1:
    Atomically creates an EvaluationJob, its EvaluationJobOutbox record, and the corresponding AuditEvent
    within a single ACID database transaction.
    Returns (job, is_created).
    If an evaluation with the same normalized idempotency_key already exists:
    - If the request fingerprint matches: returns (existing_job, False) without duplicate creation.
    - If the request fingerprint differs: raises 409 IDEMPOTENCY_CONFLICT.
    """
    # 1. Tenant ownership and scoping validation
    stmt_sub = select(Submission).where(
        Submission.id == submission_id,
        Submission.organization_id == organization_id,
        Submission.hackathon_id == hackathon_id,
        Submission.deleted_at.is_(None),
    )
    submission = (await db.execute(stmt_sub)).scalar_one_or_none()
    if not submission:
        raise AppException(
            status_code=404,
            code="SUBMISSION_NOT_FOUND",
            message="Submission not found within this organization and hackathon.",
        )

    stmt_snap = select(SubmissionSnapshot).where(
        SubmissionSnapshot.id == snapshot_id,
        SubmissionSnapshot.submission_id == submission_id,
        SubmissionSnapshot.organization_id == organization_id,
    )
    snapshot = (await db.execute(stmt_snap)).scalar_one_or_none()
    if not snapshot:
        raise AppException(
            status_code=404,
            code="SNAPSHOT_NOT_FOUND",
            message="Submission snapshot not found or does not belong to this submission.",
        )

    stmt_rubric = select(RubricVersion).where(
        RubricVersion.id == rubric_version_id,
        RubricVersion.organization_id == organization_id,
    )
    rubric_version = (await db.execute(stmt_rubric)).scalar_one_or_none()
    if not rubric_version:
        raise AppException(
            status_code=404,
            code="RUBRIC_VERSION_NOT_FOUND",
            message="Rubric version not found within this organization.",
        )

    # 2. Compute deterministic request fingerprint and normalized idempotency key
    fingerprint = compute_evaluation_request_fingerprint(
        submission_id=submission_id,
        rubric_version_id=rubric_version_id,
        snapshot_id=snapshot_id,
        configuration_override=configuration_override,
    )
    normalized_key = normalize_idempotency_key(idempotency_key)

    # 3. Check for existing job with same idempotency key or active in-flight duplicate
    if normalized_key is not None:
        stmt_existing = select(EvaluationJob).where(
            EvaluationJob.organization_id == organization_id,
            EvaluationJob.idempotency_key == normalized_key,
        )
        existing = (await db.execute(stmt_existing)).scalar_one_or_none()
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise AppException(
                    status_code=409,
                    code="IDEMPOTENCY_CONFLICT",
                    message="Idempotency key was previously used with different evaluation parameters.",
                )
            return existing, False
    else:
        # Missing Idempotency-Key: deduplicate against currently active in-flight jobs
        stmt_active = select(EvaluationJob).where(
            EvaluationJob.organization_id == organization_id,
            EvaluationJob.submission_id == submission_id,
            EvaluationJob.request_fingerprint == fingerprint,
            EvaluationJob.status.in_(["queued", "running"]),
        )
        active_job = (await db.execute(stmt_active)).scalars().first()
        if active_job:
            return active_job, False

    # 4. Atomic creation of Job + Outbox + Audit Event
    job_id = uuid.uuid4()
    job = EvaluationJob(
        id=job_id,
        organization_id=organization_id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        snapshot_id=snapshot_id,
        rubric_version_id=rubric_version_id,
        status="queued",
        attempts_count=0,
        max_attempts=3,
        lock_version=0,
        idempotency_key=normalized_key,
        request_fingerprint=fingerprint,
        dispatch_generation=1,
        cancellation_requested=False,
    )
    db.add(job)

    outbox = EvaluationJobOutbox(
        job_id=job_id,
        organization_id=organization_id,
        queue_name="evaluations.default",
        routing_key="evaluations.default",
        payload={"job_id": str(job_id)},
        status=OutboxStatus.PENDING.value,
        claim_count=0,
        publish_attempts=0,
        dispatch_generation=1,
    )
    db.add(outbox)

    # Audit event without exposing sensitive secrets
    await record_audit_event(
        db=db,
        action="evaluation.dispatched",
        resource_type="evaluation_job",
        resource_id=str(job_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        organization_id=organization_id,
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
        diff_payload={
            "submission_id": str(submission_id),
            "snapshot_id": str(snapshot_id),
            "rubric_version_id": str(rubric_version_id),
            "dispatch_generation": 1,
            "idempotency_key": normalized_key,
        },
    )

    try:
        await db.flush()
    except IntegrityError as exc:
        # Resolve concurrent insert race on uq_eval_jobs_organization_idempotency_key
        if normalized_key is not None and "uq_eval_jobs_organization_idempotency_key" in str(exc):
            await db.rollback()
            stmt_retry = select(EvaluationJob).where(
                EvaluationJob.organization_id == organization_id,
                EvaluationJob.idempotency_key == normalized_key,
            )
            concurrent_winner = (await db.execute(stmt_retry)).scalar_one_or_none()
            if concurrent_winner:
                if concurrent_winner.request_fingerprint != fingerprint:
                    raise AppException(
                        status_code=409,
                        code="IDEMPOTENCY_CONFLICT",
                        message="Idempotency key was previously used with different evaluation parameters.",
                    )
                return concurrent_winner, False
        raise

    return job, True


async def reevaluate_submission_atomic(
    db: AsyncSession,
    organization_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    rubric_version_id: uuid.UUID,
    idempotency_key: Optional[str] = None,
    configuration_override: Optional[Dict[str, Any]] = None,
    actor_user_id: Optional[uuid.UUID] = None,
    actor_email: str = "system@scorva.local",
    actor_role: str = "system",
    ip_address: str = "127.0.0.1",
    user_agent: str = "Scorva-API/1.0",
    correlation_id: Optional[uuid.UUID] = None,
) -> tuple[EvaluationJob, bool]:
    """
    Subsystem C Sub-Milestone 5.1:
    Explicit Intentional Re-Evaluation:
    Locates the previous evaluation for the submission, generates a fresh EvaluationJob record
    referencing reevaluation_of_job_id = previous_job.id, creates a fresh outbox record,
    and commits atomically while keeping historical evaluations immutable.
    """
    # 1. Verify previous evaluation exists for this submission
    stmt_prev = (
        select(EvaluationJob)
        .where(
            EvaluationJob.submission_id == submission_id,
            EvaluationJob.organization_id == organization_id,
        )
        .order_by(EvaluationJob.created_at.desc())
    )
    previous_job = (await db.execute(stmt_prev)).scalars().first()
    if not previous_job:
        raise AppException(
            status_code=404,
            code="PREVIOUS_EVALUATION_NOT_FOUND",
            message="Cannot re-evaluate submission: no prior evaluation found.",
        )

    # 2. Key normalization: client key or generated reevaluation key
    normalized_key = normalize_idempotency_key(idempotency_key)
    if normalized_key is None:
        normalized_key = f"reeval:{previous_job.id}:{uuid.uuid4().hex[:12]}"
    elif previous_job.idempotency_key == normalized_key:
        raise AppException(
            status_code=409,
            code="IDEMPOTENCY_KEY_REUSE",
            message="Re-evaluation cannot reuse the exact idempotency key of the prior evaluation run.",
        )

    # 3. Check if this re-evaluation request was already dispatched
    stmt_existing = select(EvaluationJob).where(
        EvaluationJob.organization_id == organization_id,
        EvaluationJob.idempotency_key == normalized_key,
    )
    existing = (await db.execute(stmt_existing)).scalar_one_or_none()
    if existing:
        return existing, False

    fingerprint = compute_evaluation_request_fingerprint(
        submission_id=submission_id,
        rubric_version_id=rubric_version_id,
        snapshot_id=snapshot_id,
        configuration_override=configuration_override,
    )

    job_id = uuid.uuid4()
    job = EvaluationJob(
        id=job_id,
        organization_id=organization_id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        snapshot_id=snapshot_id,
        rubric_version_id=rubric_version_id,
        status="queued",
        attempts_count=0,
        max_attempts=3,
        lock_version=0,
        idempotency_key=normalized_key,
        request_fingerprint=fingerprint,
        dispatch_generation=1,
        reevaluation_of_job_id=previous_job.id,
        cancellation_requested=False,
    )
    db.add(job)

    outbox = EvaluationJobOutbox(
        job_id=job_id,
        organization_id=organization_id,
        queue_name="evaluations.default",
        routing_key="evaluations.default",
        payload={"job_id": str(job_id)},
        status=OutboxStatus.PENDING.value,
        claim_count=0,
        publish_attempts=0,
        dispatch_generation=1,
    )
    db.add(outbox)

    await record_audit_event(
        db=db,
        action="evaluation.reevaluated",
        resource_type="evaluation_job",
        resource_id=str(job_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        organization_id=organization_id,
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
        diff_payload={
            "parent_job_id": str(previous_job.id),
            "submission_id": str(submission_id),
            "snapshot_id": str(snapshot_id),
            "rubric_version_id": str(rubric_version_id),
            "idempotency_key": normalized_key,
        },
    )

    try:
        await db.flush()
    except IntegrityError as exc:
        if normalized_key is not None and "uq_eval_jobs_organization_idempotency_key" in str(exc):
            await db.rollback()
            stmt_retry = select(EvaluationJob).where(
                EvaluationJob.organization_id == organization_id,
                EvaluationJob.idempotency_key == normalized_key,
            )
            concurrent_winner = (await db.execute(stmt_retry)).scalar_one_or_none()
            if concurrent_winner:
                return concurrent_winner, False
        raise

    return job, True


@dataclass(frozen=True)
class CancellationResult:
    status: str  # "cancelled", "cancellation_requested", "already_terminal", "conflict_completed"
    job_id: uuid.UUID
    current_status: str
    message: str


async def cancel_evaluation_job_atomic(
    db: AsyncSession,
    job_id: uuid.UUID,
    organization_id: Optional[uuid.UUID] = None,
    actor_user_id: Optional[uuid.UUID] = None,
    actor_email: Optional[str] = None,
    actor_role: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    correlation_id: Optional[uuid.UUID] = None,
) -> CancellationResult:
    """
    Subsystem C Sub-Milestone 5.4: Cooperative Evaluation Cancellation Protocol.
    Acquires exclusive pessimistic row lock (SELECT ... FOR UPDATE) on evaluation_jobs.

    State transition and locking rules:
    1. status == 'queued':
       - Atomically transitions directly to terminal 'cancelled' (completed_at = clock_timestamp()).
       - Clears claim_token, increments lock_version.
       - Marks any active outbox entries (pending/processing) as dead_lettered ('JOB_CANCELLED').
       - Emits audit event 'evaluation.cancelled'.
       - Returns CancellationResult(status='cancelled', ...)
    2. status == 'running':
       - If cancellation_requested is already True: idempotent return (status='cancellation_requested').
       - Sets cancellation_requested = True, updated_at = clock_timestamp().
       - Emits audit event 'evaluation.cancellation_requested'.
       - Worker heartbeat detects flag and aborts with JobCancelledError.
       - Returns CancellationResult(status='cancellation_requested', ...)
    3. status == 'completed':
       - Completion wins race with cancellation.
       - Raises AppException(409, 'CANNOT_CANCEL_COMPLETED', 'Cannot cancel an already completed evaluation job.')
    4. status in ('cancelled', 'failed'):
       - Terminal state is idempotent.
       - Returns CancellationResult(status='already_terminal', ...)
    """
    effective_email = actor_email or "system@scorva.local"
    effective_role = actor_role or "system"
    effective_ip = ip_address or "127.0.0.1"
    effective_ua = user_agent or "Scorva/1.0"
    correlation_id = correlation_id or uuid.uuid4()

    stmt = (
        select(EvaluationJob)
        .execution_options(populate_existing=True)
        .where(EvaluationJob.id == job_id)
        .with_for_update()
    )
    if organization_id is not None:
        stmt = stmt.where(EvaluationJob.organization_id == organization_id)

    job = (await db.execute(stmt)).scalar_one_or_none()
    if not job:
        raise AppException(
            status_code=404,
            code="EVALUATION_JOB_NOT_FOUND",
            message="Evaluation job not found.",
        )

    if job.status == "completed":
        raise AppException(
            status_code=409,
            code="CANNOT_CANCEL_COMPLETED",
            message="Cannot cancel an already completed evaluation job.",
        )

    if job.status == "cancelled":
        return CancellationResult(
            status="already_terminal",
            job_id=job.id,
            current_status="cancelled",
            message="Evaluation job is already cancelled.",
        )

    if job.status == "failed":
        return CancellationResult(
            status="already_terminal",
            job_id=job.id,
            current_status="failed",
            message="Evaluation job is already in terminal failed state.",
        )

    if job.status == "queued":
        # Atomically cancel queued job before any worker can claim it
        job.status = "cancelled"
        job.cancellation_requested = True
        job.completed_at = datetime.now(timezone.utc)
        job.lease_expires_at = None
        job.lock_version += 1
        job.error_code = "CANCELLED_BEFORE_EXECUTION"
        job.error_message = "Job was cancelled while queued."

        # Invalidate any active outbox dispatches for this job
        stmt_outbox = (
            update(EvaluationJobOutbox)
            .where(
                EvaluationJobOutbox.job_id == job.id,
                EvaluationJobOutbox.status.in_(["pending", "processing"]),
            )
            .values(
                status=OutboxStatus.DEAD_LETTERED.value,
                dead_letter_reason="JOB_CANCELLED_WHILE_QUEUED",
                dead_lettered_at=func.clock_timestamp(),
            )
        )
        await db.execute(stmt_outbox)

        await record_audit_event(
            db=db,
            action="evaluation.cancelled",
            resource_type="evaluation_job",
            resource_id=str(job.id),
            outcome=AuditOutcome.SUCCESS,
            actor_user_id=actor_user_id,
            actor_email=effective_email,
            actor_role=effective_role,
            organization_id=job.organization_id,
            ip_address=effective_ip,
            user_agent=effective_ua,
            correlation_id=correlation_id,
            diff_payload={
                "previous_status": "queued",
                "new_status": "cancelled",
                "lock_version": job.lock_version,
            },
        )
        await db.flush()
        return CancellationResult(
            status="cancelled",
            job_id=job.id,
            current_status="cancelled",
            message="Evaluation job was cancelled before execution.",
        )

    if job.status == "running":
        if job.cancellation_requested:
            # Idempotent repeated request
            return CancellationResult(
                status="cancellation_requested",
                job_id=job.id,
                current_status="running",
                message="Cancellation has already been requested.",
            )

        job.cancellation_requested = True
        job.updated_at = datetime.now(timezone.utc)

        await record_audit_event(
            db=db,
            action="evaluation.cancellation_requested",
            resource_type="evaluation_job",
            resource_id=str(job.id),
            outcome=AuditOutcome.SUCCESS,
            actor_user_id=actor_user_id,
            actor_email=effective_email,
            actor_role=effective_role,
            organization_id=job.organization_id,
            ip_address=effective_ip,
            user_agent=effective_ua,
            correlation_id=correlation_id,
            diff_payload={
                "previous_cancellation_requested": False,
                "new_cancellation_requested": True,
                "lock_version": job.lock_version,
            },
        )
        await db.flush()
        return CancellationResult(
            status="cancellation_requested",
            job_id=job.id,
            current_status="running",
            message="Cooperative cancellation request initiated.",
        )

    return CancellationResult(
        status="already_terminal",
        job_id=job.id,
        current_status=job.status,
        message=f"Job is in state {job.status}.",
    )


def cancel_evaluation_job_atomic_sync(
    db,
    job_id: uuid.UUID,
    organization_id: Optional[uuid.UUID] = None,
    actor_user_id: Optional[uuid.UUID] = None,
    actor_email: Optional[str] = None,
    actor_role: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    correlation_id: Optional[uuid.UUID] = None,
) -> CancellationResult:
    """Synchronous equivalent of cancel_evaluation_job_atomic for worker/sync contexts."""
    from sqlalchemy import text
    from apps.api.modules.audit.models import AuditEvent

    effective_email = actor_email or "system@scorva.local"
    effective_role = actor_role or "system"
    effective_ip = ip_address or "127.0.0.1"
    effective_ua = user_agent or "Scorva/1.0"
    correlation_id = correlation_id or uuid.uuid4()

    sql_lock = text("""
        SELECT id, organization_id, status, cancellation_requested, lock_version
        FROM evaluation_jobs
        WHERE id = :job_id
        FOR UPDATE;
    """)
    row = db.execute(sql_lock, {"job_id": job_id}).fetchone()
    if not row:
        raise AppException(
            status_code=404,
            code="EVALUATION_JOB_NOT_FOUND",
            message="Evaluation job not found.",
        )

    if organization_id is not None and row.organization_id != organization_id:
        raise AppException(
            status_code=404,
            code="EVALUATION_JOB_NOT_FOUND",
            message="Evaluation job not found.",
        )

    if row.status == "completed":
        raise AppException(
            status_code=409,
            code="CANNOT_CANCEL_COMPLETED",
            message="Cannot cancel an already completed evaluation job.",
        )

    if row.status == "cancelled":
        return CancellationResult(
            status="already_terminal",
            job_id=row.id,
            current_status="cancelled",
            message="Evaluation job is already cancelled.",
        )

    if row.status == "failed":
        return CancellationResult(
            status="already_terminal",
            job_id=row.id,
            current_status="failed",
            message="Evaluation job is already in terminal failed state.",
        )

    if row.status == "queued":
        db.execute(text("""
            UPDATE evaluation_jobs
            SET status = 'cancelled',
                cancellation_requested = true,
                completed_at = clock_timestamp(),
                lease_expires_at = NULL,
                lock_version = lock_version + 1,
                error_code = 'CANCELLED_BEFORE_EXECUTION',
                error_message = 'Job was cancelled while queued.'
            WHERE id = :job_id
              AND status = 'queued'
              AND lock_version = :lock_version;
        """), {"job_id": job_id, "lock_version": row.lock_version})

        db.execute(text("""
            UPDATE evaluation_job_outbox
            SET status = 'dead_lettered',
                dead_letter_reason = 'JOB_CANCELLED_WHILE_QUEUED',
                dead_lettered_at = clock_timestamp()
            WHERE job_id = :job_id
              AND status IN ('pending', 'processing');
        """), {"job_id": job_id})

        audit_ev = AuditEvent(
            id=uuid.uuid4(),
            timestamp=datetime.now(timezone.utc),
            actor_user_id=actor_user_id,
            actor_email=effective_email,
            actor_role=effective_role,
            action="evaluation.cancelled",
            resource_type="evaluation_job",
            resource_id=str(job_id),
            organization_id=row.organization_id,
            outcome=AuditOutcome.SUCCESS,
            diff_payload={
                "previous_status": "queued",
                "new_status": "cancelled",
                "lock_version": row.lock_version + 1,
            },
            ip_address=effective_ip,
            user_agent=effective_ua,
            correlation_id=correlation_id,
        )
        db.add(audit_ev)
        db.flush()
        return CancellationResult(
            status="cancelled",
            job_id=row.id,
            current_status="cancelled",
            message="Evaluation job was cancelled before execution.",
        )

    if row.status == "running":
        if row.cancellation_requested:
            return CancellationResult(
                status="cancellation_requested",
                job_id=row.id,
                current_status="running",
                message="Cancellation has already been requested.",
            )

        db.execute(text("""
            UPDATE evaluation_jobs
            SET cancellation_requested = true,
                updated_at = clock_timestamp()
            WHERE id = :job_id
              AND status = 'running'
              AND lock_version = :lock_version;
        """), {"job_id": job_id, "lock_version": row.lock_version})

        audit_ev = AuditEvent(
            id=uuid.uuid4(),
            timestamp=datetime.now(timezone.utc),
            actor_user_id=actor_user_id,
            actor_email=effective_email,
            actor_role=effective_role,
            action="evaluation.cancellation_requested",
            resource_type="evaluation_job",
            resource_id=str(job_id),
            organization_id=row.organization_id,
            outcome=AuditOutcome.SUCCESS,
            diff_payload={
                "previous_cancellation_requested": False,
                "new_cancellation_requested": True,
                "lock_version": row.lock_version,
            },
            ip_address=effective_ip,
            user_agent=effective_ua,
            correlation_id=correlation_id,
        )
        db.add(audit_ev)
        db.flush()
        return CancellationResult(
            status="cancellation_requested",
            job_id=row.id,
            current_status="running",
            message="Cooperative cancellation request initiated.",
        )

    return CancellationResult(
        status="already_terminal",
        job_id=row.id,
        current_status=row.status,
        message=f"Job is in state {row.status}.",
    )


# ==============================================================================
# Subsystem C Sub-Milestone 6.4: AI Evaluation Transparency Services
# ==============================================================================

async def get_submission_evaluation_detail(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    job_id: Optional[uuid.UUID] = None,
) -> SubmissionEvaluationTransparencyResponse:
    """
    Subsystem C Sub-Milestone 6.4:
    Retrieves complete evaluation transparency details for a submission:
    lifecycle state, rubric version, snapshot provenance, criterion-level scores,
    grounded evidence references, safe failure categories, and prior runs.
    Enforces organization and hackathon tenant scoping.
    """
    # 1. Scoped hackathon verification
    stmt_hack = select(Hackathon).where(
        Hackathon.id == hackathon_id,
        Hackathon.organization_id == org_id,
    )
    hackathon = (await db.execute(stmt_hack)).scalar_one_or_none()
    if not hackathon:
        raise AppException(
            status_code=404,
            code="HACKATHON_NOT_FOUND",
            message="Hackathon not found in this organization.",
        )

    # 2. Scoped submission verification
    stmt_sub = select(Submission).where(
        Submission.id == submission_id,
        Submission.hackathon_id == hackathon_id,
        Submission.organization_id == org_id,
        Submission.deleted_at.is_(None),
    )
    sub = (await db.execute(stmt_sub)).scalar_one_or_none()
    if not sub:
        raise AppException(
            status_code=404,
            code="SUBMISSION_NOT_FOUND",
            message="Submission not found in this hackathon.",
        )

    # 3. Check published rubric
    stmt_pub_rubric = (
        select(RubricVersion, Rubric)
        .join(Rubric, Rubric.id == RubricVersion.rubric_id)
        .where(
            Rubric.hackathon_id == hackathon_id,
            Rubric.organization_id == org_id,
            RubricVersion.status == "published",
        )
        .order_by(RubricVersion.version_number.desc())
    )
    pub_rubric_res = (await db.execute(stmt_pub_rubric)).first()
    has_pub_rubric = pub_rubric_res is not None

    # 4. Fetch all evaluation jobs for this submission
    stmt_all_jobs = (
        select(EvaluationJob)
        .where(
            EvaluationJob.submission_id == submission_id,
            EvaluationJob.organization_id == org_id,
        )
        .order_by(EvaluationJob.created_at.desc())
    )
    all_jobs = (await db.execute(stmt_all_jobs)).scalars().all()
    in_flight_job = next((j for j in all_jobs if j.status in ("queued", "running")), None)

    # 5. Determine whether submission can be evaluated
    can_evaluate = True
    cannot_evaluate_reason: Optional[str] = None
    if hackathon.status in ("archived", "completed"):
        can_evaluate = False
        cannot_evaluate_reason = f"Hackathon is {hackathon.status}."
    elif not has_pub_rubric:
        can_evaluate = False
        cannot_evaluate_reason = "No published rubric version is available for this hackathon."
    elif not sub.verified_commit_sha and sub.connection_status != "verified":
        can_evaluate = False
        cannot_evaluate_reason = "Repository must be verified with a commit SHA before evaluation."
    elif in_flight_job:
        can_evaluate = False
        cannot_evaluate_reason = "An evaluation is currently in progress for this submission."

    # 6. Target job selection
    if job_id is not None:
        target_job = next((j for j in all_jobs if j.id == job_id), None)
        if not target_job:
            raise AppException(
                status_code=404,
                code="EVALUATION_JOB_NOT_FOUND",
                message="Evaluation job not found for this submission.",
            )
    else:
        target_job = all_jobs[0] if all_jobs else None

    # If no evaluation exists yet
    if not target_job:
        return SubmissionEvaluationTransparencyResponse(
            submission_id=sub.id,
            submission_title=sub.title,
            team_name=sub.team_name,
            repository_url=sub.repository_url,
            target_branch=sub.target_branch,
            verified_commit_sha=sub.verified_commit_sha,
            can_evaluate=can_evaluate,
            cannot_evaluate_reason=cannot_evaluate_reason,
            has_evaluation=False,
            job=None,
            rubric=None,
            snapshot=None,
            result=None,
            prior_runs=[],
        )

    # 7. Resolve Rubric and RubricVersion
    stmt_rv = (
        select(RubricVersion, Rubric)
        .join(Rubric, Rubric.id == RubricVersion.rubric_id)
        .where(RubricVersion.id == target_job.rubric_version_id)
    )
    rv_res = (await db.execute(stmt_rv)).first()
    rubric_summary: Optional[EvaluationRubricSummary] = None
    if rv_res:
        rv, r = rv_res
        rubric_summary = EvaluationRubricSummary(
            rubric_id=r.id,
            rubric_name=r.name,
            rubric_version_id=rv.id,
            version_number=rv.version_number,
            scoring_mode=r.scoring_mode,
        )

    # 8. Resolve Snapshot
    stmt_snap = select(SubmissionSnapshot).where(SubmissionSnapshot.id == target_job.snapshot_id)
    snap = (await db.execute(stmt_snap)).scalar_one_or_none()
    snapshot_summary: Optional[EvaluationSnapshotSummary] = None
    if snap:
        snapshot_summary = EvaluationSnapshotSummary(
            snapshot_id=snap.id,
            commit_sha=snap.commit_sha,
            file_count=snap.file_count,
            total_bytes=snap.total_bytes,
            captured_at=snap.captured_at,
        )

    # 9. Format Safe Job Summary
    is_retryable = (
        target_job.status == "failed"
        and target_job.attempts_count < target_job.max_attempts
        and target_job.error_code in (
            "PROVIDER_RATE_LIMIT",
            "PROVIDER_TIMEOUT",
            "PROVIDER_UNAVAILABLE",
            "ACQUISITION_TIMEOUT",
            "LEASE_EXPIRED",
            "WORKER_CRASHED",
        )
    )
    safe_err_code, safe_err_msg = sanitize_error_for_display(
        target_job.error_code, target_job.error_message
    )
    job_summary = EvaluationJobSummary(
        id=target_job.id,
        status=target_job.status,
        current_stage=target_job.current_stage,
        attempts_count=target_job.attempts_count,
        max_attempts=target_job.max_attempts,
        error_code=safe_err_code,
        error_message=safe_err_msg,
        is_retryable=is_retryable,
        cancellation_requested=target_job.cancellation_requested,
        started_at=target_job.started_at,
        completed_at=target_job.completed_at,
        created_at=target_job.created_at,
    )

    # 10. Load EvaluationResult and Criterion-level Breakdown if completed
    result_detail: Optional[EvaluationResultDetail] = None
    if target_job.status == "completed":
        stmt_res = (
            select(EvaluationResult)
            .where(
                EvaluationResult.job_id == target_job.id,
                EvaluationResult.organization_id == org_id,
            )
            .order_by(EvaluationResult.attempt_number.desc())
        )
        res_model = (await db.execute(stmt_res)).scalars().first()
        if res_model:
            stmt_scores = (
                select(EvaluationCriterionScore, RubricCriterion)
                .join(RubricCriterion, RubricCriterion.id == EvaluationCriterionScore.criterion_id)
                .where(EvaluationCriterionScore.evaluation_result_id == res_model.id)
                .order_by(RubricCriterion.order_index.asc())
            )
            score_rows = (await db.execute(stmt_scores)).all()

            criterion_scores: List[CriterionScoreDetail] = []
            for cs, rc in score_rows:
                stmt_ev = (
                    select(EvidenceReference)
                    .where(EvidenceReference.criterion_score_id == cs.id)
                    .order_by(EvidenceReference.file_path.asc(), EvidenceReference.start_line.asc())
                )
                ev_models = (await db.execute(stmt_ev)).scalars().all()
                evidence_refs = [
                    EvidenceReferenceDetail(
                        id=ev.id,
                        file_path=ev.file_path,
                        start_line=ev.start_line,
                        end_line=ev.end_line,
                        snippet=ev.snippet,
                        is_verified_in_repo=ev.is_verified_in_repo,
                        verification_failure_reason=ev.verification_failure_reason,
                    )
                    for ev in ev_models
                ]
                criterion_scores.append(
                    CriterionScoreDetail(
                        id=cs.id,
                        criterion_id=cs.criterion_id,
                        title=rc.title,
                        description=rc.description,
                        weight=rc.weight,
                        min_score=rc.min_score,
                        max_score=rc.max_score,
                        order_index=rc.order_index,
                        awarded_score=cs.awarded_score,
                        normalized_criterion_score=cs.normalized_criterion_score,
                        confidence_score=cs.confidence_score,
                        rationale=cs.rationale,
                        evidence_status=cs.evidence_status,
                        evidence_references=evidence_refs,
                    )
                )

            result_detail = EvaluationResultDetail(
                id=res_model.id,
                attempt_number=res_model.attempt_number,
                model_provider=res_model.model_provider,
                model_name=res_model.model_name,
                prompt_version=res_model.prompt_version,
                raw_score=res_model.raw_score,
                normalized_score=res_model.normalized_score,
                summary_assessment=res_model.summary_assessment,
                has_insufficient_evidence=res_model.has_insufficient_evidence,
                created_at=res_model.created_at,
                criterion_scores=criterion_scores,
            )

    # 11. Format Prior Runs
    prior_runs: List[PriorEvaluationRunSummary] = []
    for other_job in all_jobs:
        if other_job.id == target_job.id:
            continue
        stmt_other_res = (
            select(EvaluationResult.raw_score, EvaluationResult.normalized_score)
            .where(
                EvaluationResult.job_id == other_job.id,
                EvaluationResult.organization_id == org_id,
            )
            .order_by(EvaluationResult.attempt_number.desc())
        )
        scores_res = (await db.execute(stmt_other_res)).first()
        raw_s = scores_res[0] if scores_res else None
        norm_s = scores_res[1] if scores_res else None

        prior_runs.append(
            PriorEvaluationRunSummary(
                job_id=other_job.id,
                status=other_job.status,
                attempts_count=other_job.attempts_count,
                raw_score=raw_s,
                normalized_score=norm_s,
                completed_at=other_job.completed_at,
                created_at=other_job.created_at,
            )
        )

    return SubmissionEvaluationTransparencyResponse(
        submission_id=sub.id,
        submission_title=sub.title,
        team_name=sub.team_name,
        repository_url=sub.repository_url,
        target_branch=sub.target_branch,
        verified_commit_sha=sub.verified_commit_sha,
        can_evaluate=can_evaluate,
        cannot_evaluate_reason=cannot_evaluate_reason,
        has_evaluation=True,
        job=job_summary,
        rubric=rubric_summary,
        snapshot=snapshot_summary,
        result=result_detail,
        prior_runs=prior_runs,
    )


async def get_hackathon_evaluations_summary(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
) -> HackathonEvaluationSummaryResponse:
    """
    Subsystem C Sub-Milestone 6.4:
    Aggregates evaluation counts, lifecycle distribution, average AI score,
    and published rubric availability for an organizer dashboard.
    """
    # 1. Scoped hackathon verification
    stmt_hack = select(Hackathon).where(
        Hackathon.id == hackathon_id,
        Hackathon.organization_id == org_id,
    )
    hackathon = (await db.execute(stmt_hack)).scalar_one_or_none()
    if not hackathon:
        raise AppException(
            status_code=404,
            code="HACKATHON_NOT_FOUND",
            message="Hackathon not found in this organization.",
        )

    # 2. Total active submissions
    stmt_subs = select(func.count(Submission.id)).where(
        Submission.hackathon_id == hackathon_id,
        Submission.organization_id == org_id,
        Submission.deleted_at.is_(None),
    )
    total_submissions = (await db.execute(stmt_subs)).scalar_one() or 0

    # 3. Evaluated submissions count
    stmt_eval = select(func.count(Submission.id)).where(
        Submission.hackathon_id == hackathon_id,
        Submission.organization_id == org_id,
        Submission.status == "evaluated",
        Submission.deleted_at.is_(None),
    )
    evaluated_submissions = (await db.execute(stmt_eval)).scalar_one() or 0

    # 4. Job lifecycle counts
    stmt_jobs = (
        select(EvaluationJob.status, func.count(EvaluationJob.id))
        .where(
            EvaluationJob.hackathon_id == hackathon_id,
            EvaluationJob.organization_id == org_id,
        )
        .group_by(EvaluationJob.status)
    )
    job_counts = dict((await db.execute(stmt_jobs)).all())

    queued_jobs = job_counts.get("queued", 0)
    running_jobs = job_counts.get("running", 0)
    completed_jobs = job_counts.get("completed", 0)
    failed_jobs = job_counts.get("failed", 0)
    cancelled_jobs = job_counts.get("cancelled", 0)

    # 5. Average score of completed evaluations
    stmt_avg = select(func.avg(EvaluationResult.normalized_score)).where(
        EvaluationResult.hackathon_id == hackathon_id,
        EvaluationResult.organization_id == org_id,
    )
    avg_score_raw = (await db.execute(stmt_avg)).scalar_one()
    avg_score = round(Decimal(str(avg_score_raw)), 2) if avg_score_raw is not None else None

    # 6. Published rubric availability
    stmt_pub_rubric = (
        select(RubricVersion, Rubric)
        .join(Rubric, Rubric.id == RubricVersion.rubric_id)
        .where(
            Rubric.hackathon_id == hackathon_id,
            Rubric.organization_id == org_id,
            RubricVersion.status == "published",
        )
        .order_by(RubricVersion.version_number.desc())
    )
    pub_rubric_res = (await db.execute(stmt_pub_rubric)).first()
    has_published_rubric = pub_rubric_res is not None
    published_rubric_id = pub_rubric_res[1].id if pub_rubric_res else None
    published_rubric_version_id = pub_rubric_res[0].id if pub_rubric_res else None
    published_rubric_name = pub_rubric_res[1].name if pub_rubric_res else None

    return HackathonEvaluationSummaryResponse(
        total_submissions=total_submissions,
        evaluated_submissions=evaluated_submissions,
        queued_jobs=queued_jobs,
        running_jobs=running_jobs,
        completed_jobs=completed_jobs,
        failed_jobs=failed_jobs,
        cancelled_jobs=cancelled_jobs,
        average_score=avg_score,
        has_published_rubric=has_published_rubric,
        published_rubric_id=published_rubric_id,
        published_rubric_version_id=published_rubric_version_id,
        published_rubric_name=published_rubric_name,
    )


async def list_hackathon_evaluation_jobs(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[EvaluationJobListItem]:
    """
    Subsystem C Sub-Milestone 6.4:
    Lists evaluation jobs for a hackathon without exposing another tenant's jobs or private repository data.
    """
    stmt = (
        select(EvaluationJob, Submission)
        .join(Submission, Submission.id == EvaluationJob.submission_id)
        .where(
            EvaluationJob.hackathon_id == hackathon_id,
            EvaluationJob.organization_id == org_id,
        )
    )
    if status:
        stmt = stmt.where(EvaluationJob.status == status)

    stmt = stmt.order_by(EvaluationJob.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).all()

    items: List[EvaluationJobListItem] = []
    for job, sub in rows:
        raw_score = None
        normalized_score = None
        if job.status == "completed":
            stmt_res = (
                select(EvaluationResult.raw_score, EvaluationResult.normalized_score)
                .where(
                    EvaluationResult.job_id == job.id,
                    EvaluationResult.organization_id == org_id,
                )
                .order_by(EvaluationResult.attempt_number.desc())
            )
            score_res = (await db.execute(stmt_res)).first()
            if score_res:
                raw_score, normalized_score = score_res[0], score_res[1]

        safe_err_code, _ = sanitize_error_for_display(job.error_code, job.error_message)
        items.append(
            EvaluationJobListItem(
                id=job.id,
                submission_id=sub.id,
                submission_title=sub.title,
                team_name=sub.team_name,
                status=job.status,
                current_stage=job.current_stage,
                attempts_count=job.attempts_count,
                max_attempts=job.max_attempts,
                raw_score=raw_score,
                normalized_score=normalized_score,
                error_code=safe_err_code,
                created_at=job.created_at,
                completed_at=job.completed_at,
            )
        )
    return items


async def trigger_submission_evaluation(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    idempotency_key: Optional[str] = None,
    configuration_override: Optional[Dict[str, Any]] = None,
    actor_user_id: Optional[uuid.UUID] = None,
    actor_email: str = "organizer@scorva.local",
    actor_role: str = "organizer",
    ip_address: str = "127.0.0.1",
    user_agent: str = "Scorva-API/1.0",
    correlation_id: Optional[uuid.UUID] = None,
) -> tuple[EvaluationJob, bool]:
    """
    Subsystem C Sub-Milestone 6.4:
    Direct evaluation initiation from the hackathon dashboard.
    Validates submission eligibility, published rubric availability,
    resolves/creates snapshot, and dispatches via transactional outbox.
    """
    # 1. Scoped hackathon verification
    stmt_hack = select(Hackathon).where(
        Hackathon.id == hackathon_id,
        Hackathon.organization_id == org_id,
    )
    hackathon = (await db.execute(stmt_hack)).scalar_one_or_none()
    if not hackathon:
        raise AppException(
            status_code=404,
            code="HACKATHON_NOT_FOUND",
            message="Hackathon not found in this organization.",
        )
    if hackathon.status in ("archived", "completed"):
        raise AppException(
            status_code=400,
            code="HACKATHON_LOCKED",
            message=f"Cannot initiate evaluation: Hackathon is {hackathon.status}.",
        )

    # 2. Scoped submission verification
    stmt_sub = select(Submission).where(
        Submission.id == submission_id,
        Submission.hackathon_id == hackathon_id,
        Submission.organization_id == org_id,
        Submission.deleted_at.is_(None),
    )
    sub = (await db.execute(stmt_sub)).scalar_one_or_none()
    if not sub:
        raise AppException(
            status_code=404,
            code="SUBMISSION_NOT_FOUND",
            message="Submission not found in this hackathon.",
        )

    # 3. Resolve published rubric
    stmt_rubric = (
        select(RubricVersion)
        .join(Rubric, Rubric.id == RubricVersion.rubric_id)
        .where(
            Rubric.hackathon_id == hackathon_id,
            Rubric.organization_id == org_id,
            RubricVersion.status == "published",
        )
        .order_by(RubricVersion.version_number.desc())
    )
    rubric_version = (await db.execute(stmt_rubric)).scalars().first()
    if not rubric_version:
        raise AppException(
            status_code=400,
            code="NO_PUBLISHED_RUBRIC",
            message="Cannot evaluate submission: No published rubric version exists for this hackathon. Please publish a rubric first.",
        )

    # 4. Resolve or create submission snapshot
    stmt_snap = (
        select(SubmissionSnapshot)
        .where(
            SubmissionSnapshot.submission_id == submission_id,
            SubmissionSnapshot.organization_id == org_id,
        )
        .order_by(SubmissionSnapshot.captured_at.desc())
    )
    snapshot = (await db.execute(stmt_snap)).scalars().first()
    if not snapshot:
        commit_sha = sub.verified_commit_sha
        if not commit_sha:
            raise AppException(
                status_code=400,
                code="CANNOT_EVALUATE_UNVERIFIED_REPO",
                message="Cannot evaluate submission: Repository has no verified commit SHA. Please verify the repository connection first.",
            )
        snapshot = await create_submission_snapshot(
            db=db,
            organization_id=org_id,
            submission_id=submission_id,
            commit_sha=commit_sha,
            configuration_snapshot={
                "branch": sub.target_branch,
                "repository_url": sub.repository_url,
            },
        )

    # 5. Dispatch evaluation job atomically via transactional outbox
    return await dispatch_evaluation_job_atomic(
        db=db,
        organization_id=org_id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        idempotency_key=idempotency_key,
        configuration_override=configuration_override,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )


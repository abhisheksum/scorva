from datetime import datetime, timezone
from decimal import Decimal
import secrets
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from apps.api.core.exceptions import AppException
from apps.api.modules.evaluations.models import (
    Rubric,
    RubricCriterion,
    RubricVersion,
    Submission,
    SubmissionSnapshot,
    Team,
    TeamMember,
)
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

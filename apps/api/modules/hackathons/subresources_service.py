from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.core.exceptions import AppException
from apps.api.core.ssrf_guard import SSRFViolationError
from apps.api.modules.audit.models import AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.evaluations.github_client import (
    GitHubIngestionClient,
    GitHubIngestionError,
    parse_github_url,
)
from apps.api.modules.evaluations.models import (
    EvaluationJob,
    EvaluationResult,
    HackathonJudge,
    Rubric,
    RubricCriterion,
    RubricVersion,
    Submission,
    SubmissionSnapshot,
    Team,
    TeamMember,
)
from apps.api.modules.evaluations import service as evaluations_service
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.modules.hackathons.subresources_schemas import (
    AddCriterionRequest,
    AssignJudgeRequest,
    CreateRubricRequest,
    CreateSubmissionRequest,
    CreateTeamRequest,
    CriterionResponse,
    HackathonOverviewResponse,
    JoinTeamRequest,
    JudgeListItem,
    LinkRepositoryRequest,
    RepositoryValidationResult,
    RubricDetailResponse,
    RubricVersionDetail,
    SubmissionDetailResponse,
    SubmissionListItem,
    TeamDetailResponse,
    TeamListItem,
    TeamMemberInfo,
    TeamSubmissionSummary,
    UpdateBranchRequest,
    ValidateRepositoryRequest,
)
from apps.api.modules.integrations.service import (
    decrypt_organization_integration_token,
    get_organization_integration,
)
from apps.api.modules.users.models import User



async def _ensure_hackathon(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
) -> Hackathon:
    """Validate hackathon existence and enforce tenant ownership."""
    stmt = select(Hackathon).where(
        Hackathon.id == hackathon_id,
        Hackathon.organization_id == org_id,
        Hackathon.deleted_at.is_(None),
    )
    hackathon = (await db.execute(stmt)).scalar_one_or_none()
    if not hackathon:
        raise AppException(
            status_code=404,
            code="HACKATHON_NOT_FOUND",
            message="Hackathon not found within this organization.",
        )
    return hackathon


# ==========================================
# Hackathon Overview & Statistics
# ==========================================

async def get_hackathon_overview(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
) -> HackathonOverviewResponse:
    hackathon = await _ensure_hackathon(db, org_id, hackathon_id)

    # 1. Total teams
    stmt_teams = select(func.count(Team.id)).where(
        Team.hackathon_id == hackathon_id,
        Team.organization_id == org_id,
    )
    total_teams = (await db.execute(stmt_teams)).scalar_one() or 0

    # 2. Total active submissions
    stmt_subs = select(func.count(Submission.id)).where(
        Submission.hackathon_id == hackathon_id,
        Submission.organization_id == org_id,
        Submission.deleted_at.is_(None),
    )
    total_submissions = (await db.execute(stmt_subs)).scalar_one() or 0

    # 3. Evaluation job counts
    stmt_evals = select(func.count(EvaluationJob.id)).where(
        EvaluationJob.hackathon_id == hackathon_id,
        EvaluationJob.organization_id == org_id,
    )
    total_evaluations = (await db.execute(stmt_evals)).scalar_one() or 0

    stmt_completed_evals = select(func.count(EvaluationJob.id)).where(
        EvaluationJob.hackathon_id == hackathon_id,
        EvaluationJob.organization_id == org_id,
        EvaluationJob.status == "completed",
    )
    completed_evaluations = (await db.execute(stmt_completed_evals)).scalar_one() or 0

    stmt_pending_evals = select(func.count(EvaluationJob.id)).where(
        EvaluationJob.hackathon_id == hackathon_id,
        EvaluationJob.organization_id == org_id,
        EvaluationJob.status.in_(["queued", "running"]),
    )
    pending_evaluations = (await db.execute(stmt_pending_evals)).scalar_one() or 0

    # 4. Total judges
    stmt_judges = select(func.count(HackathonJudge.id)).where(
        HackathonJudge.hackathon_id == hackathon_id,
    )
    total_judges = (await db.execute(stmt_judges)).scalar_one() or 0

    # 5. Average normalized score
    stmt_avg = select(func.avg(EvaluationResult.normalized_score)).where(
        EvaluationResult.hackathon_id == hackathon_id,
        EvaluationResult.organization_id == org_id,
    )
    avg_score = (await db.execute(stmt_avg)).scalar_one_or_none()
    if avg_score is not None:
        avg_score = Decimal(str(round(avg_score, 2)))

    return HackathonOverviewResponse(
        hackathon_id=hackathon.id,
        organization_id=org_id,
        title=hackathon.title,
        status=hackathon.status.value,
        total_teams=total_teams,
        total_submissions=total_submissions,
        total_evaluations=total_evaluations,
        completed_evaluations=completed_evaluations,
        pending_evaluations=pending_evaluations,
        total_judges=total_judges,
        average_score=avg_score,
    )


# ==========================================
# Teams & Participants Workflows
# ==========================================

async def list_hackathon_teams(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
) -> List[TeamListItem]:
    await _ensure_hackathon(db, org_id, hackathon_id)

    stmt = (
        select(Team)
        .where(
            Team.hackathon_id == hackathon_id,
            Team.organization_id == org_id,
        )
        .order_by(Team.created_at.desc())
    )
    teams = (await db.execute(stmt)).scalars().all()

    items: List[TeamListItem] = []
    for t in teams:
        # Count members
        stmt_count = select(func.count(TeamMember.id)).where(TeamMember.team_id == t.id)
        m_count = (await db.execute(stmt_count)).scalar_one() or 0

        # Primary active submission
        stmt_sub = (
            select(Submission)
            .where(
                Submission.team_id == t.id,
                Submission.deleted_at.is_(None),
            )
            .order_by(Submission.created_at.desc())
        )
        sub = (await db.execute(stmt_sub)).scalars().first()
        sub_summary = (
            TeamSubmissionSummary(
                id=sub.id,
                title=sub.title,
                repository_url=sub.repository_url,
                target_branch=sub.target_branch,
                status=sub.status,
            )
            if sub
            else None
        )

        items.append(
            TeamListItem(
                id=t.id,
                organization_id=t.organization_id,
                hackathon_id=t.hackathon_id,
                name=t.name,
                join_code=t.join_code,
                created_by_user_id=t.created_by_user_id,
                created_at=t.created_at,
                member_count=m_count,
                submission=sub_summary,
            )
        )
    return items


async def create_hackathon_team(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    data: CreateTeamRequest,
    actor_user_id: uuid.UUID,
    actor_email: str,
    actor_role: str,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[str] = None,
) -> TeamDetailResponse:
    await _ensure_hackathon(db, org_id, hackathon_id)

    # Check if user is already in a team in this hackathon
    stmt_existing = (
        select(TeamMember)
        .join(Team, TeamMember.team_id == Team.id)
        .where(
            Team.hackathon_id == hackathon_id,
            TeamMember.user_id == actor_user_id,
        )
    )
    existing_membership = (await db.execute(stmt_existing)).scalars().first()
    if existing_membership:
        raise AppException(
            status_code=409,
            code="ALREADY_IN_HACKATHON_TEAM",
            message="You are already a member of a team in this hackathon.",
        )

    team = await evaluations_service.create_team(
        db=db,
        organization_id=org_id,
        hackathon_id=hackathon_id,
        user_id=actor_user_id,
        name=data.name.strip(),
    )

    await record_audit_event(
        db=db,
        action="team_created",
        resource_type="team",
        resource_id=str(team.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        organization_id=org_id,
        reason=f"Registered team '{team.name}' in hackathon",
        diff_payload={"name": team.name, "join_code": team.join_code},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    # Retrieve user detail for creator
    user = (await db.execute(select(User).where(User.id == actor_user_id))).scalar_one_or_none()

    return TeamDetailResponse(
        id=team.id,
        organization_id=team.organization_id,
        hackathon_id=team.hackathon_id,
        name=team.name,
        join_code=team.join_code,
        created_by_user_id=team.created_by_user_id,
        created_at=team.created_at,
        members=[
            TeamMemberInfo(
                id=team.id,  # representative member id
                user_id=actor_user_id,
                role_in_team="leader",
                joined_at=team.created_at,
                user_email=user.email if user else actor_email,
                user_name=user.full_name if user else None,
            )
        ],
        submission=None,
    )


async def get_hackathon_team_detail(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    team_id: uuid.UUID,
) -> TeamDetailResponse:
    await _ensure_hackathon(db, org_id, hackathon_id)

    stmt = select(Team).where(
        Team.id == team_id,
        Team.organization_id == org_id,
        Team.hackathon_id == hackathon_id,
    )
    team = (await db.execute(stmt)).scalar_one_or_none()
    if not team:
        raise AppException(
            status_code=404,
            code="TEAM_NOT_FOUND",
            message="Team not found in this hackathon.",
        )

    # Load members with User info
    stmt_members = (
        select(TeamMember, User)
        .join(User, TeamMember.user_id == User.id)
        .where(TeamMember.team_id == team_id)
        .order_by(TeamMember.joined_at.asc())
    )
    member_rows = (await db.execute(stmt_members)).all()
    members_list = [
        TeamMemberInfo(
            id=tm.id,
            user_id=tm.user_id,
            role_in_team=tm.role_in_team,
            joined_at=tm.joined_at,
            user_email=u.email,
            user_name=u.full_name,
        )
        for tm, u in member_rows
    ]

    # Load active submission
    stmt_sub = (
        select(Submission)
        .where(
            Submission.team_id == team_id,
            Submission.deleted_at.is_(None),
        )
        .order_by(Submission.created_at.desc())
    )
    sub = (await db.execute(stmt_sub)).scalars().first()
    sub_summary = (
        TeamSubmissionSummary(
            id=sub.id,
            title=sub.title,
            repository_url=sub.repository_url,
            target_branch=sub.target_branch,
            status=sub.status,
        )
        if sub
        else None
    )

    return TeamDetailResponse(
        id=team.id,
        organization_id=team.organization_id,
        hackathon_id=team.hackathon_id,
        name=team.name,
        join_code=team.join_code,
        created_by_user_id=team.created_by_user_id,
        created_at=team.created_at,
        members=members_list,
        submission=sub_summary,
    )


async def join_hackathon_team(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    data: JoinTeamRequest,
    actor_user_id: uuid.UUID,
    actor_email: str,
    actor_role: str,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[str] = None,
) -> TeamDetailResponse:
    await _ensure_hackathon(db, org_id, hackathon_id)

    clean_code = data.join_code.strip()
    stmt_team = select(Team).where(
        Team.join_code == clean_code,
        Team.hackathon_id == hackathon_id,
        Team.organization_id == org_id,
    )
    team = (await db.execute(stmt_team)).scalar_one_or_none()
    if not team:
        raise AppException(
            status_code=404,
            code="TEAM_NOT_FOUND",
            message="Invalid join code or team not found in this hackathon.",
        )

    # Check if already a member of this team
    stmt_check = select(TeamMember).where(
        TeamMember.team_id == team.id,
        TeamMember.user_id == actor_user_id,
    )
    if (await db.execute(stmt_check)).scalar_one_or_none():
        raise AppException(
            status_code=409,
            code="ALREADY_IN_TEAM",
            message="You are already a member of this team.",
        )

    # Check if already in another team in this hackathon
    stmt_existing = (
        select(TeamMember)
        .join(Team, TeamMember.team_id == Team.id)
        .where(
            Team.hackathon_id == hackathon_id,
            TeamMember.user_id == actor_user_id,
        )
    )
    if (await db.execute(stmt_existing)).scalars().first():
        raise AppException(
            status_code=409,
            code="ALREADY_IN_HACKATHON_TEAM",
            message="You are already a member of another team in this hackathon.",
        )

    member = TeamMember(
        team_id=team.id,
        user_id=actor_user_id,
        role_in_team="member",
    )
    db.add(member)
    await db.flush()

    await record_audit_event(
        db=db,
        action="team_member_joined",
        resource_type="team",
        resource_id=str(team.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        organization_id=org_id,
        reason=f"Joined team '{team.name}' via join code",
        diff_payload={"team_name": team.name, "user_id": str(actor_user_id)},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    return await get_hackathon_team_detail(db, org_id, hackathon_id, team.id)


# ==========================================
# Submissions & Repository Linking Workflows
# ==========================================

async def validate_github_repository(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    data: ValidateRepositoryRequest,
    custom_client: Optional[Any] = None,
) -> RepositoryValidationResult:
    """Validates URL syntax, host, credentials absence, accessibility, default/target branch, and returns typed verification result."""
    await _ensure_hackathon(db, org_id, hackathon_id)

    # 1. Parse and validate repository URL
    try:
        owner, repo = parse_github_url(data.repository_url)
    except (GitHubIngestionError, SSRFViolationError) as exc:
        code = getattr(exc, "code", "MALFORMED_URL")
        msg = str(exc)
        return RepositoryValidationResult(
            is_valid_url=False,
            is_accessible=False,
            ownership_verified=False,
            connection_status="failed",
            diagnostic_code=code,
            message=msg,
            verified_at=datetime.now(timezone.utc),
        )

    # 2. Check organization integration
    integration = await get_organization_integration(db, org_id, "github")
    token = None
    has_token = False
    if integration:
        try:
            token = decrypt_organization_integration_token(integration)
            has_token = True
        except Exception:
            token = None
            has_token = False

    # 3. Verify repository and branch accessibility via GitHub client
    ingest_client = GitHubIngestionClient(token=token, custom_client=custom_client)
    try:
        meta = await ingest_client.verify_repository_access(
            owner=owner,
            repo=repo,
            target_branch=data.target_branch,
        )
        ownership_note = (
            "Access and organization credentials verified."
            if has_token
            else "Public repository access verified. Verified organization ownership requires configuring a GitHub integration token."
        )
        return RepositoryValidationResult(
            is_valid_url=True,
            is_accessible=True,
            ownership_verified=has_token,
            ownership_note=ownership_note,
            canonical_repo_id=meta.get("canonical_repo_id", f"{owner}/{repo}"),
            owner=meta.get("owner", owner),
            repo=meta.get("repo", repo),
            default_branch=meta.get("default_branch"),
            target_branch=meta.get("target_branch", data.target_branch),
            commit_sha=meta.get("commit_sha"),
            connection_status="verified",
            diagnostic_code="SUCCESS",
            message="Repository and target branch successfully verified.",
            verified_at=datetime.now(timezone.utc),
        )
    except GitHubIngestionError as exc:
        return RepositoryValidationResult(
            is_valid_url=True,
            is_accessible=False,
            ownership_verified=False,
            canonical_repo_id=f"{owner}/{repo}",
            owner=owner,
            repo=repo,
            target_branch=data.target_branch,
            connection_status="failed",
            diagnostic_code=exc.code,
            message=exc.message,
            verified_at=datetime.now(timezone.utc),
        )
    except SSRFViolationError as exc:
        return RepositoryValidationResult(
            is_valid_url=False,
            is_accessible=False,
            ownership_verified=False,
            connection_status="failed",
            diagnostic_code="SSRF_BLOCKED",
            message=str(exc),
            verified_at=datetime.now(timezone.utc),
        )
    except Exception as exc:
        return RepositoryValidationResult(
            is_valid_url=True,
            is_accessible=False,
            ownership_verified=False,
            connection_status="failed",
            diagnostic_code="GITHUB_API_ERROR",
            message=f"An unexpected error occurred while verifying the repository: {exc}",
            verified_at=datetime.now(timezone.utc),
        )


async def list_hackathon_submissions(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
) -> List[SubmissionListItem]:
    await _ensure_hackathon(db, org_id, hackathon_id)

    stmt = (
        select(Submission)
        .where(
            Submission.hackathon_id == hackathon_id,
            Submission.organization_id == org_id,
            Submission.deleted_at.is_(None),
        )
        .order_by(Submission.created_at.desc())
    )
    submissions = (await db.execute(stmt)).scalars().all()

    items: List[SubmissionListItem] = []
    for sub in submissions:
        # Find latest EvaluationJob
        stmt_job = (
            select(EvaluationJob)
            .where(
                EvaluationJob.submission_id == sub.id,
                EvaluationJob.organization_id == org_id,
            )
            .order_by(EvaluationJob.created_at.desc())
        )
        latest_job = (await db.execute(stmt_job)).scalars().first()

        latest_score: Optional[Decimal] = None
        if latest_job and latest_job.status == "completed":
            stmt_result = (
                select(EvaluationResult.normalized_score)
                .where(EvaluationResult.job_id == latest_job.id)
                .order_by(EvaluationResult.attempt_number.desc())
            )
            latest_score = (await db.execute(stmt_result)).scalar_one_or_none()

        items.append(
            SubmissionListItem(
                id=sub.id,
                organization_id=sub.organization_id,
                hackathon_id=sub.hackathon_id,
                team_id=sub.team_id,
                team_name=sub.team_name,
                repository_url=sub.repository_url,
                target_branch=sub.target_branch,
                title=sub.title,
                description=sub.description,
                status=sub.status,
                repository_owner=sub.repository_owner,
                repository_name=sub.repository_name,
                default_branch=sub.default_branch,
                verified_commit_sha=sub.verified_commit_sha,
                connection_status=sub.connection_status,
                verified_at=sub.verified_at,
                verification_diagnostic=sub.verification_diagnostic,
                created_at=sub.created_at,
                updated_at=sub.updated_at,
                latest_job_id=latest_job.id if latest_job else None,
                latest_job_status=latest_job.status if latest_job else None,
                latest_score=latest_score,
            )
        )
    return items


async def create_hackathon_submission(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    data: CreateSubmissionRequest,
    actor_user_id: uuid.UUID,
    actor_email: str,
    actor_role: str,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[str] = None,
    custom_client: Optional[Any] = None,
) -> SubmissionDetailResponse:
    hackathon = await _ensure_hackathon(db, org_id, hackathon_id)

    # Validate hackathon lifecycle status
    if hackathon.status in (HackathonStatus.COMPLETED, HackathonStatus.ARCHIVED):
        raise AppException(
            status_code=400,
            code="HACKATHON_NOT_ACCEPTING_SUBMISSIONS",
            message="This hackathon has completed or is archived and no longer accepts submissions.",
        )

    # Validate submission deadline
    now_utc = datetime.now(timezone.utc)
    if now_utc > hackathon.submission_deadline:
        raise AppException(
            status_code=400,
            code="SUBMISSION_DEADLINE_PASSED",
            message="The submission deadline for this hackathon has passed.",
        )

    # Validate team belongs to hackathon and org
    stmt_team = select(Team).where(
        Team.id == data.team_id,
        Team.hackathon_id == hackathon_id,
        Team.organization_id == org_id,
    )
    team = (await db.execute(stmt_team)).scalar_one_or_none()
    if not team:
        raise AppException(
            status_code=404,
            code="TEAM_NOT_FOUND",
            message="Specified team does not exist in this hackathon.",
        )

    # If actor is not org admin/owner, verify actor is a member of the team
    if actor_role not in ("org_owner", "org_admin"):
        stmt_mem = select(TeamMember).where(
            TeamMember.team_id == team.id,
            TeamMember.user_id == actor_user_id,
        )
        if not (await db.execute(stmt_mem)).scalar_one_or_none():
            raise AppException(
                status_code=403,
                code="NOT_A_TEAM_MEMBER",
                message="You must be a member of the team to submit a project.",
            )

    # Validate team does not already have an active submission
    stmt_active_sub = select(Submission).where(
        Submission.team_id == team.id,
        Submission.deleted_at.is_(None),
    )
    if (await db.execute(stmt_active_sub)).scalars().first():
        raise AppException(
            status_code=409,
            code="TEAM_ALREADY_SUBMITTED",
            message="This team has already submitted a project to this hackathon.",
        )

    clean_url = data.repository_url.strip()

    # Syntax and host validation
    try:
        parsed_owner, parsed_repo = parse_github_url(clean_url)
    except GitHubIngestionError as exc:
        raise AppException(status_code=400, code=exc.code, message=exc.message) from exc

    # Validate duplicate repository_url
    stmt_repo_dup = select(Submission).where(
        Submission.hackathon_id == hackathon_id,
        Submission.repository_url == clean_url,
        Submission.deleted_at.is_(None),
    )
    if (await db.execute(stmt_repo_dup)).scalars().first():
        raise AppException(
            status_code=409,
            code="REPOSITORY_ALREADY_SUBMITTED",
            message=f"Repository URL '{clean_url}' has already been submitted to this hackathon.",
        )

    # Attempt repository verification
    val_res = await validate_github_repository(
        db=db,
        org_id=org_id,
        hackathon_id=hackathon_id,
        data=ValidateRepositoryRequest(
            repository_url=clean_url,
            target_branch=data.target_branch,
        ),
        custom_client=custom_client,
    )

    if not val_res.is_valid_url:
        raise AppException(status_code=400, code=val_res.diagnostic_code, message=val_res.message)

    # Create submission
    submission = Submission(
        organization_id=org_id,
        hackathon_id=hackathon_id,
        team_id=team.id,
        team_name=team.name,
        repository_url=clean_url,
        target_branch=data.target_branch.strip() or "main",
        title=data.title.strip(),
        description=data.description.strip() if data.description else None,
        status="pending",
        repository_owner=val_res.owner or parsed_owner,
        repository_name=val_res.repo or parsed_repo,
        default_branch=val_res.default_branch,
        verified_commit_sha=val_res.commit_sha,
        connection_status="verified" if val_res.is_accessible else "unverified",
        verified_at=val_res.verified_at if val_res.is_accessible else None,
        verification_diagnostic=val_res.diagnostic_code,
        verification_error=None if val_res.is_accessible else val_res.message,
    )
    db.add(submission)
    await db.flush()

    await record_audit_event(
        db=db,
        action="submission_created",
        resource_type="submission",
        resource_id=str(submission.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        organization_id=org_id,
        reason=f"Registered submission '{submission.title}' for team '{team.name}'",
        diff_payload={
            "team_id": str(team.id),
            "repository_url": submission.repository_url,
            "target_branch": submission.target_branch,
            "title": submission.title,
            "connection_status": submission.connection_status,
        },
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    return await get_hackathon_submission_detail(db, org_id, hackathon_id, submission.id)


async def link_submission_repository(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    data: LinkRepositoryRequest,
    actor_user_id: uuid.UUID,
    actor_email: str,
    actor_role: str,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[str] = None,
    custom_client: Optional[Any] = None,
) -> SubmissionDetailResponse:
    """Links or replaces a verified repository on an existing submission."""
    hackathon = await _ensure_hackathon(db, org_id, hackathon_id)

    if hackathon.status in (HackathonStatus.COMPLETED, HackathonStatus.ARCHIVED):
        raise AppException(
            status_code=400,
            code="HACKATHON_NOT_ACCEPTING_SUBMISSIONS",
            message="This hackathon has completed or is archived and no longer accepts repository modifications.",
        )

    now_utc = datetime.now(timezone.utc)
    if now_utc > hackathon.submission_deadline:
        raise AppException(
            status_code=400,
            code="SUBMISSION_DEADLINE_PASSED",
            message="The submission deadline for this hackathon has passed.",
        )

    stmt_sub = (
        select(Submission)
        .where(
            Submission.id == submission_id,
            Submission.hackathon_id == hackathon_id,
            Submission.organization_id == org_id,
            Submission.deleted_at.is_(None),
        )
        .with_for_update()
    )
    sub = (await db.execute(stmt_sub)).scalar_one_or_none()
    if not sub:
        raise AppException(
            status_code=404,
            code="SUBMISSION_NOT_FOUND",
            message="Submission not found in this hackathon.",
        )

    # Authorize user
    if actor_role not in ("org_owner", "org_admin"):
        stmt_mem = select(TeamMember).where(
            TeamMember.team_id == sub.team_id,
            TeamMember.user_id == actor_user_id,
        )
        if not (await db.execute(stmt_mem)).scalar_one_or_none():
            raise AppException(
                status_code=403,
                code="NOT_A_TEAM_MEMBER",
                message="You must be a member of the team to modify this submission's repository.",
            )

    clean_url = data.repository_url.strip()

    # Check duplicate active repository URL across the hackathon
    stmt_dup = select(Submission).where(
        Submission.hackathon_id == hackathon_id,
        Submission.repository_url == clean_url,
        Submission.id != sub.id,
        Submission.deleted_at.is_(None),
    )
    if (await db.execute(stmt_dup)).scalars().first():
        raise AppException(
            status_code=409,
            code="REPOSITORY_ALREADY_SUBMITTED",
            message=f"Repository URL '{clean_url}' has already been submitted to this hackathon by another team.",
        )

    # Verify repository accessibility and requested branch
    val_res = await validate_github_repository(
        db=db,
        org_id=org_id,
        hackathon_id=hackathon_id,
        data=ValidateRepositoryRequest(
            repository_url=clean_url,
            target_branch=data.target_branch,
        ),
        custom_client=custom_client,
    )
    if not val_res.is_accessible:
        # Failsafe: leave existing valid link unchanged
        raise AppException(
            status_code=400,
            code=val_res.diagnostic_code,
            message=val_res.message,
        )

    old_url = sub.repository_url
    sub.repository_url = clean_url
    sub.target_branch = val_res.target_branch or "main"
    sub.repository_owner = val_res.owner
    sub.repository_name = val_res.repo
    sub.default_branch = val_res.default_branch
    sub.verified_commit_sha = val_res.commit_sha
    sub.connection_status = "verified"
    sub.verified_at = val_res.verified_at
    sub.verification_diagnostic = "SUCCESS"
    sub.verification_error = None
    await db.flush()

    await record_audit_event(
        db=db,
        action="repository_linked",
        resource_type="submission",
        resource_id=str(sub.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        organization_id=org_id,
        reason=f"Linked repository '{clean_url}' (branch: {sub.target_branch}, commit: {sub.verified_commit_sha}) to submission",
        diff_payload={
            "old_repository_url": old_url,
            "repository_url": sub.repository_url,
            "target_branch": sub.target_branch,
            "commit_sha": sub.verified_commit_sha,
            "ownership_verified": val_res.ownership_verified,
        },
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    return await get_hackathon_submission_detail(db, org_id, hackathon_id, sub.id)


async def update_submission_branch(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    data: UpdateBranchRequest,
    actor_user_id: uuid.UUID,
    actor_email: str,
    actor_role: str,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[str] = None,
    custom_client: Optional[Any] = None,
) -> SubmissionDetailResponse:
    """Updates the target branch after verifying the branch exists on GitHub."""
    hackathon = await _ensure_hackathon(db, org_id, hackathon_id)

    if hackathon.status in (HackathonStatus.COMPLETED, HackathonStatus.ARCHIVED):
        raise AppException(
            status_code=400,
            code="HACKATHON_NOT_ACCEPTING_SUBMISSIONS",
            message="This hackathon has completed or is archived.",
        )

    now_utc = datetime.now(timezone.utc)
    if now_utc > hackathon.submission_deadline:
        raise AppException(
            status_code=400,
            code="SUBMISSION_DEADLINE_PASSED",
            message="The submission deadline for this hackathon has passed.",
        )

    stmt_sub = (
        select(Submission)
        .where(
            Submission.id == submission_id,
            Submission.hackathon_id == hackathon_id,
            Submission.organization_id == org_id,
            Submission.deleted_at.is_(None),
        )
        .with_for_update()
    )
    sub = (await db.execute(stmt_sub)).scalar_one_or_none()
    if not sub:
        raise AppException(
            status_code=404,
            code="SUBMISSION_NOT_FOUND",
            message="Submission not found.",
        )

    if actor_role not in ("org_owner", "org_admin"):
        stmt_mem = select(TeamMember).where(
            TeamMember.team_id == sub.team_id,
            TeamMember.user_id == actor_user_id,
        )
        if not (await db.execute(stmt_mem)).scalar_one_or_none():
            raise AppException(
                status_code=403,
                code="NOT_A_TEAM_MEMBER",
                message="You must be a member of the team to modify this submission's branch.",
            )

    new_branch = data.target_branch.strip()

    # Verify that the new branch exists on GitHub
    val_res = await validate_github_repository(
        db=db,
        org_id=org_id,
        hackathon_id=hackathon_id,
        data=ValidateRepositoryRequest(
            repository_url=sub.repository_url,
            target_branch=new_branch,
        ),
        custom_client=custom_client,
    )
    if not val_res.is_accessible:
        raise AppException(
            status_code=400,
            code=val_res.diagnostic_code,
            message=val_res.message,
        )

    old_branch = sub.target_branch
    sub.target_branch = new_branch
    sub.verified_commit_sha = val_res.commit_sha
    sub.verified_at = val_res.verified_at
    sub.connection_status = "verified"
    sub.verification_diagnostic = "SUCCESS"
    sub.verification_error = None
    await db.flush()

    await record_audit_event(
        db=db,
        action="submission_branch_updated",
        resource_type="submission",
        resource_id=str(sub.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        organization_id=org_id,
        reason=f"Updated target branch from '{old_branch}' to '{new_branch}' (commit: {sub.verified_commit_sha})",
        diff_payload={"old_branch": old_branch, "new_branch": new_branch, "commit_sha": sub.verified_commit_sha},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    return await get_hackathon_submission_detail(db, org_id, hackathon_id, sub.id)


async def refresh_submission_verification(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_email: str,
    actor_role: str,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[str] = None,
    custom_client: Optional[Any] = None,
) -> SubmissionDetailResponse:
    """Refreshes repository connection status and updates commit SHA if changed."""
    await _ensure_hackathon(db, org_id, hackathon_id)

    stmt_sub = (
        select(Submission)
        .where(
            Submission.id == submission_id,
            Submission.hackathon_id == hackathon_id,
            Submission.organization_id == org_id,
            Submission.deleted_at.is_(None),
        )
        .with_for_update()
    )
    sub = (await db.execute(stmt_sub)).scalar_one_or_none()
    if not sub:
        raise AppException(
            status_code=404,
            code="SUBMISSION_NOT_FOUND",
            message="Submission not found.",
        )

    val_res = await validate_github_repository(
        db=db,
        org_id=org_id,
        hackathon_id=hackathon_id,
        data=ValidateRepositoryRequest(
            repository_url=sub.repository_url,
            target_branch=sub.target_branch,
        ),
        custom_client=custom_client,
    )

    if val_res.is_accessible:
        sub.connection_status = "verified"
        sub.verified_commit_sha = val_res.commit_sha
        sub.verified_at = val_res.verified_at
        sub.verification_diagnostic = "SUCCESS"
        sub.verification_error = None
    else:
        sub.connection_status = "failed"
        sub.verification_diagnostic = val_res.diagnostic_code
        sub.verification_error = val_res.message

    await db.flush()

    await record_audit_event(
        db=db,
        action="submission_verification_refreshed",
        resource_type="submission",
        resource_id=str(sub.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        organization_id=org_id,
        reason=f"Refreshed verification for submission: status={sub.connection_status}, diagnostic={sub.verification_diagnostic}",
        diff_payload={"connection_status": sub.connection_status, "diagnostic": sub.verification_diagnostic},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    return await get_hackathon_submission_detail(db, org_id, hackathon_id, sub.id)


async def unlink_submission_repository(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_email: str,
    actor_role: str,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[str] = None,
) -> SubmissionDetailResponse:
    """Unlinks a repository from a submission if no evaluations have run."""
    hackathon = await _ensure_hackathon(db, org_id, hackathon_id)

    if hackathon.status in (HackathonStatus.COMPLETED, HackathonStatus.ARCHIVED):
        raise AppException(
            status_code=400,
            code="HACKATHON_NOT_ACCEPTING_SUBMISSIONS",
            message="Cannot unlink repository from a completed or archived hackathon.",
        )

    now_utc = datetime.now(timezone.utc)
    if now_utc > hackathon.submission_deadline:
        raise AppException(
            status_code=400,
            code="SUBMISSION_DEADLINE_PASSED",
            message="The submission deadline for this hackathon has passed.",
        )

    stmt_sub = (
        select(Submission)
        .where(
            Submission.id == submission_id,
            Submission.hackathon_id == hackathon_id,
            Submission.organization_id == org_id,
            Submission.deleted_at.is_(None),
        )
        .with_for_update()
    )
    sub = (await db.execute(stmt_sub)).scalar_one_or_none()
    if not sub:
        raise AppException(
            status_code=404,
            code="SUBMISSION_NOT_FOUND",
            message="Submission not found.",
        )

    if actor_role not in ("org_owner", "org_admin"):
        stmt_mem = select(TeamMember).where(
            TeamMember.team_id == sub.team_id,
            TeamMember.user_id == actor_user_id,
        )
        if not (await db.execute(stmt_mem)).scalar_one_or_none():
            raise AppException(
                status_code=403,
                code="NOT_A_TEAM_MEMBER",
                message="You must be a member of the team to unlink this repository.",
            )

    # Check if submission has active or completed evaluation jobs
    stmt_jobs = select(func.count(EvaluationJob.id)).where(
        EvaluationJob.submission_id == sub.id,
        EvaluationJob.status.in_(["queued", "running", "completed"]),
    )
    job_count = (await db.execute(stmt_jobs)).scalar_one() or 0
    if job_count > 0:
        raise AppException(
            status_code=400,
            code="CANNOT_UNLINK_EVALUATED_SUBMISSION",
            message="Cannot unlink repository from a submission that has active evaluation runs or completed evaluations.",
        )

    sub.connection_status = "unlinked"
    sub.verified_commit_sha = None
    sub.verified_at = None
    sub.verification_diagnostic = "UNLINKED"
    await db.flush()

    await record_audit_event(
        db=db,
        action="repository_unlinked",
        resource_type="submission",
        resource_id=str(sub.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        organization_id=org_id,
        reason=f"Unlinked repository from submission '{sub.title}'",
        diff_payload={"submission_id": str(sub.id), "repository_url": sub.repository_url},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    return await get_hackathon_submission_detail(db, org_id, hackathon_id, sub.id)


async def get_hackathon_submission_detail(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
) -> SubmissionDetailResponse:
    await _ensure_hackathon(db, org_id, hackathon_id)

    stmt = select(Submission).where(
        Submission.id == submission_id,
        Submission.organization_id == org_id,
        Submission.hackathon_id == hackathon_id,
        Submission.deleted_at.is_(None),
    )
    sub = (await db.execute(stmt)).scalar_one_or_none()
    if not sub:
        raise AppException(
            status_code=404,
            code="SUBMISSION_NOT_FOUND",
            message="Submission not found in this hackathon.",
        )

    # Snapshots count
    stmt_snaps = select(func.count(SubmissionSnapshot.id)).where(
        SubmissionSnapshot.submission_id == sub.id,
        SubmissionSnapshot.organization_id == org_id,
    )
    snaps_count = (await db.execute(stmt_snaps)).scalar_one() or 0

    # Latest evaluation job
    stmt_job = (
        select(EvaluationJob)
        .where(
            EvaluationJob.submission_id == sub.id,
            EvaluationJob.organization_id == org_id,
        )
        .order_by(EvaluationJob.created_at.desc())
    )
    latest_job = (await db.execute(stmt_job)).scalars().first()

    latest_score: Optional[Decimal] = None
    summary_assessment: Optional[str] = None
    if latest_job and latest_job.status == "completed":
        stmt_result = (
            select(EvaluationResult)
            .where(EvaluationResult.job_id == latest_job.id)
            .order_by(EvaluationResult.attempt_number.desc())
        )
        result = (await db.execute(stmt_result)).scalars().first()
        if result:
            latest_score = result.normalized_score
            summary_assessment = result.summary_assessment

    return SubmissionDetailResponse(
        id=sub.id,
        organization_id=sub.organization_id,
        hackathon_id=sub.hackathon_id,
        team_id=sub.team_id,
        team_name=sub.team_name,
        repository_url=sub.repository_url,
        target_branch=sub.target_branch,
        title=sub.title,
        description=sub.description,
        status=sub.status,
        repository_owner=sub.repository_owner,
        repository_name=sub.repository_name,
        default_branch=sub.default_branch,
        verified_commit_sha=sub.verified_commit_sha,
        connection_status=sub.connection_status,
        verified_at=sub.verified_at,
        verification_diagnostic=sub.verification_diagnostic,
        verification_error=sub.verification_error,
        created_at=sub.created_at,
        updated_at=sub.updated_at,
        snapshots_count=snaps_count,
        latest_job_id=latest_job.id if latest_job else None,
        latest_job_status=latest_job.status if latest_job else None,
        latest_score=latest_score,
        summary_assessment=summary_assessment,
    )



# ==========================================
# Judges Workflows
# ==========================================

async def list_hackathon_judges(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
) -> List[JudgeListItem]:
    await _ensure_hackathon(db, org_id, hackathon_id)

    stmt = (
        select(HackathonJudge, User)
        .join(User, HackathonJudge.user_id == User.id)
        .where(HackathonJudge.hackathon_id == hackathon_id)
        .order_by(HackathonJudge.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()

    return [
        JudgeListItem(
            id=judge.id,
            hackathon_id=judge.hackathon_id,
            user_id=judge.user_id,
            assigned_by_user_id=judge.assigned_by_user_id,
            created_at=judge.created_at,
            user_email=u.email,
            user_name=u.full_name,
        )
        for judge, u in rows
    ]


async def assign_hackathon_judge(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    data: AssignJudgeRequest,
    actor_user_id: uuid.UUID,
    actor_email: str,
    actor_role: str,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[str] = None,
) -> JudgeListItem:
    await _ensure_hackathon(db, org_id, hackathon_id)

    # Resolve target user
    user: Optional[User] = None
    if data.user_id:
        user = (await db.execute(select(User).where(User.id == data.user_id))).scalar_one_or_none()
    elif data.email:
        user = (
            await db.execute(select(User).where(User.email == data.email.lower().strip()))
        ).scalar_one_or_none()
    else:
        raise AppException(
            status_code=400,
            code="USER_IDENTIFIER_REQUIRED",
            message="Either user_id or email must be provided to assign a judge.",
        )

    if not user:
        raise AppException(
            status_code=404,
            code="USER_NOT_FOUND",
            message="User not found. The target user must have a registered Scorva account.",
        )

    # Check duplicate assignment
    stmt_exist = select(HackathonJudge).where(
        HackathonJudge.hackathon_id == hackathon_id,
        HackathonJudge.user_id == user.id,
    )
    if (await db.execute(stmt_exist)).scalar_one_or_none():
        raise AppException(
            status_code=409,
            code="JUDGE_ALREADY_ASSIGNED",
            message=f"User '{user.email}' is already assigned as a judge for this hackathon.",
        )

    judge = HackathonJudge(
        hackathon_id=hackathon_id,
        user_id=user.id,
        assigned_by_user_id=actor_user_id,
    )
    db.add(judge)
    await db.flush()

    await record_audit_event(
        db=db,
        action="judge_assigned",
        resource_type="hackathon_judge",
        resource_id=str(judge.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        organization_id=org_id,
        reason=f"Assigned user '{user.email}' as judge to hackathon",
        diff_payload={"user_id": str(user.id), "email": user.email},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    return JudgeListItem(
        id=judge.id,
        hackathon_id=judge.hackathon_id,
        user_id=judge.user_id,
        assigned_by_user_id=judge.assigned_by_user_id,
        created_at=judge.created_at,
        user_email=user.email,
        user_name=user.full_name,
    )


async def remove_hackathon_judge(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    judge_user_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_email: str,
    actor_role: str,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[str] = None,
) -> None:
    await _ensure_hackathon(db, org_id, hackathon_id)

    stmt = select(HackathonJudge).where(
        HackathonJudge.hackathon_id == hackathon_id,
        HackathonJudge.user_id == judge_user_id,
    )
    judge = (await db.execute(stmt)).scalar_one_or_none()
    if not judge:
        raise AppException(
            status_code=404,
            code="JUDGE_NOT_FOUND",
            message="Judge assignment not found for this user in this hackathon.",
        )

    await db.delete(judge)
    await db.flush()

    await record_audit_event(
        db=db,
        action="judge_removed",
        resource_type="hackathon_judge",
        resource_id=str(judge.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        organization_id=org_id,
        reason=f"Removed judge assignment for user '{judge_user_id}'",
        diff_payload={"user_id": str(judge_user_id)},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )


# ==========================================
# Rubrics & Criteria Workflows
# ==========================================

async def get_hackathon_rubric_detail(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
) -> RubricDetailResponse:
    await _ensure_hackathon(db, org_id, hackathon_id)

    stmt = (
        select(Rubric)
        .where(
            Rubric.hackathon_id == hackathon_id,
            Rubric.organization_id == org_id,
        )
        .order_by(Rubric.created_at.desc())
    )
    rubric = (await db.execute(stmt)).scalars().first()
    if not rubric:
        raise AppException(
            status_code=404,
            code="RUBRIC_NOT_FOUND",
            message="No rubric configured for this hackathon.",
        )

    # Find the active version: first prefer published, then latest draft
    stmt_published = (
        select(RubricVersion)
        .options(selectinload(RubricVersion.criteria))
        .where(
            RubricVersion.rubric_id == rubric.id,
            RubricVersion.status == "published",
        )
        .order_by(RubricVersion.version_number.desc())
    )
    active_version = (await db.execute(stmt_published)).scalars().first()

    if not active_version:
        stmt_draft = (
            select(RubricVersion)
            .options(selectinload(RubricVersion.criteria))
            .where(
                RubricVersion.rubric_id == rubric.id,
            )
            .order_by(RubricVersion.version_number.desc())
        )
        active_version = (await db.execute(stmt_draft)).scalars().first()

    version_detail: Optional[RubricVersionDetail] = None
    if active_version:
        criteria_items = [
            CriterionResponse(
                id=c.id,
                rubric_version_id=c.rubric_version_id,
                title=c.title,
                description=c.description,
                weight=c.weight,
                min_score=c.min_score,
                max_score=c.max_score,
                evidence_requirements=c.evidence_requirements,
                order_index=c.order_index,
            )
            for c in sorted(active_version.criteria, key=lambda x: x.order_index)
        ]
        version_detail = RubricVersionDetail(
            id=active_version.id,
            rubric_id=active_version.rubric_id,
            version_number=active_version.version_number,
            status=active_version.status,
            published_at=active_version.published_at,
            criteria=criteria_items,
        )

    return RubricDetailResponse(
        id=rubric.id,
        organization_id=rubric.organization_id,
        hackathon_id=rubric.hackathon_id,
        name=rubric.name,
        description=rubric.description,
        scoring_mode=rubric.scoring_mode,
        created_at=rubric.created_at,
        active_version=version_detail,
    )


async def create_hackathon_rubric(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    data: CreateRubricRequest,
    actor_user_id: uuid.UUID,
    actor_email: str,
    actor_role: str,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[str] = None,
) -> RubricDetailResponse:
    await _ensure_hackathon(db, org_id, hackathon_id)

    rubric = await evaluations_service.create_rubric(
        db=db,
        organization_id=org_id,
        hackathon_id=hackathon_id,
        name=data.name.strip(),
        description=data.description.strip() if data.description else None,
        scoring_mode=data.scoring_mode,
    )

    await record_audit_event(
        db=db,
        action="rubric_created",
        resource_type="rubric",
        resource_id=str(rubric.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        organization_id=org_id,
        reason=f"Created rubric '{rubric.name}' with draft v1",
        diff_payload={"name": rubric.name, "scoring_mode": rubric.scoring_mode},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    return await get_hackathon_rubric_detail(db, org_id, hackathon_id)


async def add_hackathon_rubric_criterion(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    rubric_id: uuid.UUID,
    data: AddCriterionRequest,
) -> RubricDetailResponse:
    await _ensure_hackathon(db, org_id, hackathon_id)

    # Locate latest draft RubricVersion
    stmt = (
        select(RubricVersion)
        .where(
            RubricVersion.rubric_id == rubric_id,
            RubricVersion.organization_id == org_id,
            RubricVersion.status == "draft",
        )
        .order_by(RubricVersion.version_number.desc())
    )
    draft_version = (await db.execute(stmt)).scalars().first()
    if not draft_version:
        raise AppException(
            status_code=400,
            code="NO_DRAFT_RUBRIC_VERSION",
            message="No editable draft version found for this rubric. Published rubrics cannot be modified.",
        )

    await evaluations_service.add_rubric_criterion(
        db=db,
        rubric_version_id=draft_version.id,
        title=data.title.strip(),
        description=data.description.strip(),
        weight=data.weight,
        min_score=data.min_score,
        max_score=data.max_score,
        evidence_requirements=data.evidence_requirements,
        order_index=data.order_index,
        organization_id=org_id,
    )

    return await get_hackathon_rubric_detail(db, org_id, hackathon_id)


async def publish_hackathon_rubric(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    rubric_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_email: str,
    actor_role: str,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[str] = None,
) -> RubricDetailResponse:
    await _ensure_hackathon(db, org_id, hackathon_id)

    stmt = (
        select(RubricVersion)
        .where(
            RubricVersion.rubric_id == rubric_id,
            RubricVersion.organization_id == org_id,
            RubricVersion.status == "draft",
        )
        .order_by(RubricVersion.version_number.desc())
    )
    draft_version = (await db.execute(stmt)).scalars().first()
    if not draft_version:
        raise AppException(
            status_code=400,
            code="NO_DRAFT_RUBRIC_VERSION",
            message="No draft version found to publish.",
        )

    version = await evaluations_service.publish_rubric_version(
        db=db,
        organization_id=org_id,
        rubric_version_id=draft_version.id,
    )

    await record_audit_event(
        db=db,
        action="rubric_published",
        resource_type="rubric_version",
        resource_id=str(version.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        organization_id=org_id,
        reason=f"Published rubric version {version.version_number}",
        diff_payload={"version_number": version.version_number, "status": "published"},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    return await get_hackathon_rubric_detail(db, org_id, hackathon_id)

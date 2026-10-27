from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_db_session
from apps.api.dependencies import (
    OrgRole,
    TenantContext,
    get_current_user,
    require_org_admin,
    require_org_member,
    require_org_role,
)
from apps.api.modules.users.models import User
from apps.api.modules.hackathons.subresources_schemas import (
    AddCriterionRequest,
    AssignJudgeRequest,
    CreateRubricRequest,
    CreateSubmissionRequest,
    CreateTeamRequest,
    HackathonOverviewResponse,
    JoinTeamRequest,
    JudgeListItem,
    LinkRepositoryRequest,
    RepositoryActivityItem,
    RepositoryValidationResult,
    RubricDetailResponse,
    SubmissionDetailResponse,
    SubmissionListItem,
    TeamDetailResponse,
    TeamListItem,
    UpdateBranchRequest,
    ValidateRepositoryRequest,
)
from apps.api.modules.hackathons import subresources_service as service
from apps.api.modules.evaluations.webhook_service import (
    list_hackathon_activity,
    list_submission_activity,
)
from apps.api.modules.evaluations.schemas import (
    EvaluationJobListItem,
    EvaluationJobResponse,
    HackathonEvaluationSummaryResponse,
    JudgeProgressItem,
    JudgeQueueItem,
    JudgeReviewDetail,
    JudgeSubmissionReviewResponse,
    OrganizerReviewProgressResponse,
    SaveJudgeReviewRequest,
    SubmissionCoverageItem,
    SubmissionEvaluationTransparencyResponse,
    SubmissionReviewsResponse,
    SubmitJudgeReviewRequest,
    TriggerEvaluationRequest,
)
from apps.api.modules.evaluations.service import (
    get_hackathon_evaluations_summary,
    get_submission_evaluation_detail,
    list_hackathon_evaluation_jobs,
    trigger_submission_evaluation,
)
from apps.api.modules.evaluations import judge_service

router = APIRouter(prefix="/{hackathon_id}", tags=["Hackathon Subresources"])

require_evaluator = require_org_role(
    OrgRole.ORG_OWNER,
    OrgRole.ORG_ADMIN,
    OrgRole.ORGANIZER,
)


def _extract_telemetry(request: Request):
    ip_address = getattr(
        request.state,
        "client_ip",
        request.client.host if request.client else "127.0.0.1",
    )
    user_agent = request.headers.get("user-agent", "Unknown")
    correlation_id = getattr(request.state, "correlation_id", None)
    return ip_address, user_agent, correlation_id


# ==========================================
# Hackathon Overview
# ==========================================

@router.get("/overview", response_model=HackathonOverviewResponse)
async def get_overview(
    hackathon_id: uuid.UUID,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieves operational overview and metric counters for a hackathon."""
    return await service.get_hackathon_overview(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
    )


# ==========================================
# Teams & Participants
# ==========================================

@router.get("/teams", response_model=List[TeamListItem])
async def list_teams(
    hackathon_id: uuid.UUID,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Lists all teams registered for the given hackathon."""
    return await service.list_hackathon_teams(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
    )


@router.post("/teams", response_model=TeamDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    hackathon_id: uuid.UUID,
    payload: CreateTeamRequest,
    request: Request,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Registers a new participating team with the caller designated as leader."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await service.create_hackathon_team(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        data=payload,
        actor_user_id=tenant.user.id,
        actor_email=tenant.user.email,
        actor_role=tenant.membership.role.value,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.get("/teams/{team_id}", response_model=TeamDetailResponse)
async def get_team(
    hackathon_id: uuid.UUID,
    team_id: uuid.UUID,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieves detailed team information, member roster, and active submission."""
    return await service.get_hackathon_team_detail(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        team_id=team_id,
    )


@router.post("/teams/join", response_model=TeamDetailResponse)
async def join_team(
    hackathon_id: uuid.UUID,
    payload: JoinTeamRequest,
    request: Request,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Joins an existing team via 12-character join code."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await service.join_hackathon_team(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        data=payload,
        actor_user_id=tenant.user.id,
        actor_email=tenant.user.email,
        actor_role=tenant.membership.role.value,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


# ==========================================
# Submissions
# ==========================================

@router.get("/submissions", response_model=List[SubmissionListItem])
async def list_submissions(
    hackathon_id: uuid.UUID,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Lists all active submissions registered in the hackathon."""
    return await service.list_hackathon_submissions(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
    )


@router.post("/submissions", response_model=SubmissionDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_submission(
    hackathon_id: uuid.UUID,
    payload: CreateSubmissionRequest,
    request: Request,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Registers a project repository submission for a team."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await service.create_hackathon_submission(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        data=payload,
        actor_user_id=tenant.user.id,
        actor_email=tenant.user.email,
        actor_role=tenant.membership.role.value,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.get("/submissions/{submission_id}", response_model=SubmissionDetailResponse)
async def get_submission(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieves full details of a submission, its snapshots, and latest evaluation result."""
    return await service.get_hackathon_submission_detail(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
    )


@router.post("/repositories/validate", response_model=RepositoryValidationResult)
async def validate_repository(
    hackathon_id: uuid.UUID,
    payload: ValidateRepositoryRequest,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Validates GitHub repository URL syntax, accessibility, and default/target branch."""
    return await service.validate_github_repository(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        data=payload,
    )


@router.post("/submissions/{submission_id}/link-repository", response_model=SubmissionDetailResponse)
async def link_repository(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    payload: LinkRepositoryRequest,
    request: Request,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Links or replaces a verified repository on an existing submission."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await service.link_submission_repository(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        data=payload,
        actor_user_id=tenant.user.id,
        actor_email=tenant.user.email,
        actor_role=tenant.membership.role.value,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.patch("/submissions/{submission_id}/branch", response_model=SubmissionDetailResponse)
async def update_branch(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    payload: UpdateBranchRequest,
    request: Request,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Updates target branch after verifying the branch exists on GitHub."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await service.update_submission_branch(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        data=payload,
        actor_user_id=tenant.user.id,
        actor_email=tenant.user.email,
        actor_role=tenant.membership.role.value,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.post("/submissions/{submission_id}/verify", response_model=SubmissionDetailResponse)
async def refresh_verification(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    request: Request,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Refreshes repository connection status and updates latest commit SHA."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await service.refresh_submission_verification(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        actor_user_id=tenant.user.id,
        actor_email=tenant.user.email,
        actor_role=tenant.membership.role.value,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.post("/submissions/{submission_id}/unlink-repository", response_model=SubmissionDetailResponse)
async def unlink_repository(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    request: Request,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Unlinks a repository from a submission if no evaluations have run."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await service.unlink_submission_repository(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        actor_user_id=tenant.user.id,
        actor_email=tenant.user.email,
        actor_role=tenant.membership.role.value,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.get("/submissions/{submission_id}/activity", response_model=List[RepositoryActivityItem])
async def get_submission_activity(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    limit: int = 50,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieves chronological activity timeline events associated with a submission."""
    return await list_submission_activity(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        limit=limit,
    )


@router.get("/activity", response_model=List[RepositoryActivityItem])
async def get_hackathon_activity(
    hackathon_id: uuid.UUID,
    limit: int = 50,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieves chronological activity timeline events for all submissions in a hackathon."""
    return await list_hackathon_activity(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        limit=limit,
    )


# ==========================================
# Judges
# ==========================================

@router.get("/judges", response_model=List[JudgeListItem])
async def list_judges(
    hackathon_id: uuid.UUID,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Lists all judges assigned to evaluate this hackathon."""
    return await service.list_hackathon_judges(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
    )


@router.post("/judges", response_model=JudgeListItem, status_code=status.HTTP_201_CREATED)
async def assign_judge(
    hackathon_id: uuid.UUID,
    payload: AssignJudgeRequest,
    request: Request,
    tenant: TenantContext = Depends(require_evaluator),
    db: AsyncSession = Depends(get_db_session),
):
    """Assigns a registered user as a judge for this hackathon."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await service.assign_hackathon_judge(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        data=payload,
        actor_user_id=tenant.user.id,
        actor_email=tenant.user.email,
        actor_role=tenant.membership.role.value,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.delete("/judges/{judge_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_judge(
    hackathon_id: uuid.UUID,
    judge_user_id: uuid.UUID,
    request: Request,
    tenant: TenantContext = Depends(require_evaluator),
    db: AsyncSession = Depends(get_db_session),
):
    """Removes a judge assignment from this hackathon."""
    ip, ua, corr_id = _extract_telemetry(request)
    await service.remove_hackathon_judge(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        judge_user_id=judge_user_id,
        actor_user_id=tenant.user.id,
        actor_email=tenant.user.email,
        actor_role=tenant.membership.role.value,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ==========================================
# Rubrics & Criteria
# ==========================================

@router.get("/rubric", response_model=RubricDetailResponse)
async def get_rubric(
    hackathon_id: uuid.UUID,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieves the active rubric and criterion definitions for this hackathon."""
    return await service.get_hackathon_rubric_detail(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
    )


@router.post("/rubrics", response_model=RubricDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_rubric(
    hackathon_id: uuid.UUID,
    payload: CreateRubricRequest,
    request: Request,
    tenant: TenantContext = Depends(require_evaluator),
    db: AsyncSession = Depends(get_db_session),
):
    """Provisions a new rubric container with an initial draft v1."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await service.create_hackathon_rubric(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        data=payload,
        actor_user_id=tenant.user.id,
        actor_email=tenant.user.email,
        actor_role=tenant.membership.role.value,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.post("/rubrics/{rubric_id}/criteria", response_model=RubricDetailResponse, status_code=status.HTTP_201_CREATED)
async def add_criterion(
    hackathon_id: uuid.UUID,
    rubric_id: uuid.UUID,
    payload: AddCriterionRequest,
    tenant: TenantContext = Depends(require_evaluator),
    db: AsyncSession = Depends(get_db_session),
):
    """Adds a criterion to the current draft version of the rubric."""
    return await service.add_hackathon_rubric_criterion(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        rubric_id=rubric_id,
        data=payload,
    )


@router.post("/rubrics/{rubric_id}/publish", response_model=RubricDetailResponse)
async def publish_rubric(
    hackathon_id: uuid.UUID,
    rubric_id: uuid.UUID,
    request: Request,
    tenant: TenantContext = Depends(require_evaluator),
    db: AsyncSession = Depends(get_db_session),
):
    """Validates criteria weights and publishes/freezes the rubric version for evaluation."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await service.publish_hackathon_rubric(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        rubric_id=rubric_id,
        actor_user_id=tenant.user.id,
        actor_email=tenant.user.email,
        actor_role=tenant.membership.role.value,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


# ==============================================================================
# Subsystem C Sub-Milestone 6.4: AI Evaluation Transparency Endpoints
# ==============================================================================

@router.get("/evaluations/summary", response_model=HackathonEvaluationSummaryResponse)
async def get_evaluations_summary(
    hackathon_id: uuid.UUID,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Subsystem C Sub-Milestone 6.4:
    Aggregated evaluation metrics, lifecycle status counts, and published rubric status for a hackathon.
    """
    return await get_hackathon_evaluations_summary(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
    )


@router.get("/evaluations", response_model=List[EvaluationJobListItem])
async def list_evaluations(
    hackathon_id: uuid.UUID,
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by evaluation status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Subsystem C Sub-Milestone 6.4:
    Lists evaluation jobs for a hackathon with tenant and hackathon scoping.
    """
    return await list_hackathon_evaluation_jobs(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get("/submissions/{submission_id}/evaluation", response_model=SubmissionEvaluationTransparencyResponse)
async def get_submission_evaluation(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    job_id: Optional[uuid.UUID] = Query(None, description="Optional specific evaluation job ID"),
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Subsystem C Sub-Milestone 6.4:
    Full evaluation transparency detail for a submission:
    criterion-level scores, grounded citations, snapshot commit SHA, and safe error categories.
    """
    return await get_submission_evaluation_detail(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        job_id=job_id,
    )


@router.post(
    "/submissions/{submission_id}/evaluate",
    response_model=EvaluationJobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def evaluate_submission(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    request: Request,
    response: Response,
    payload: Optional[TriggerEvaluationRequest] = None,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    tenant: TenantContext = Depends(require_evaluator),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Subsystem C Sub-Milestone 6.4:
    Direct submission evaluation trigger from the organizer dashboard.
    Validates submission eligibility, published rubric availability,
    resolves/creates snapshot, and dispatches via transactional outbox.
    Returns 201 Created on fresh dispatch, or 200 OK with Idempotent-Replay on deduplication.
    """
    ip, ua, corr_id = _extract_telemetry(request)
    job, is_created = await trigger_submission_evaluation(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        idempotency_key=idempotency_key,
        configuration_override=payload.configuration_override if payload else None,
        actor_user_id=tenant.user.id,
        actor_email=tenant.user.email,
        actor_role=tenant.membership.role.value,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )
    if not is_created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replay"] = "true"

    return job


def _resolve_org_id(request: Request, org_id: Optional[uuid.UUID] = None) -> uuid.UUID:
    if org_id:
        return org_id
    raw = request.path_params.get("org_id")
    if isinstance(raw, uuid.UUID):
        return raw
    return uuid.UUID(str(raw))


# ==========================================
# Subsystem C Sub-Milestone 6.5: Judge Review & Human Decisions
# ==========================================

@router.get("/judge/queue", response_model=List[JudgeQueueItem])
async def get_judge_evaluation_queue(
    hackathon_id: uuid.UUID,
    request: Request,
    org_id: Optional[uuid.UUID] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Subsystem C Sub-Milestone 6.5:
    Returns the submission review queue for an assigned hackathon judge.
    """
    resolved_org_id = _resolve_org_id(request, org_id)
    return await judge_service.get_judge_queue(
        db=db,
        org_id=resolved_org_id,
        hackathon_id=hackathon_id,
        current_user=current_user,
    )


@router.get(
    "/submissions/{submission_id}/review",
    response_model=JudgeSubmissionReviewResponse,
)
async def get_submission_review(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    request: Request,
    org_id: Optional[uuid.UUID] = None,
    judge_id: Optional[uuid.UUID] = Query(None, description="Optional target judge user ID (organizers only)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Subsystem C Sub-Milestone 6.5:
    Retrieves the review form for a specific submission including published rubric criteria,
    advisory AI assessment findings, and the judge's own draft or submitted review.
    """
    resolved_org_id = _resolve_org_id(request, org_id)
    return await judge_service.get_submission_judge_review(
        db=db,
        org_id=resolved_org_id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        current_user=current_user,
        target_judge_user_id=judge_id,
    )


@router.post(
    "/submissions/{submission_id}/review",
    response_model=JudgeReviewDetail,
)
async def save_submission_review_draft(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    payload: SaveJudgeReviewRequest,
    request: Request,
    org_id: Optional[uuid.UUID] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Subsystem C Sub-Milestone 6.5:
    Saves or updates a draft judge review with optimistic concurrency control.
    Partial scoring is permitted on drafts.
    """
    resolved_org_id = _resolve_org_id(request, org_id)
    ip, ua, corr_id = _extract_telemetry(request)
    return await judge_service.save_judge_review_draft(
        db=db,
        org_id=resolved_org_id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        data=payload,
        current_user=current_user,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.put(
    "/submissions/{submission_id}/review",
    response_model=JudgeReviewDetail,
)
async def update_submission_review_draft(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    payload: SaveJudgeReviewRequest,
    request: Request,
    org_id: Optional[uuid.UUID] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Subsystem C Sub-Milestone 6.5:
    Updates a draft review with explicit concurrency version matching.
    """
    resolved_org_id = _resolve_org_id(request, org_id)
    ip, ua, corr_id = _extract_telemetry(request)
    return await judge_service.save_judge_review_draft(
        db=db,
        org_id=resolved_org_id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        data=payload,
        current_user=current_user,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.post(
    "/submissions/{submission_id}/review/submit",
    response_model=JudgeReviewDetail,
)
async def submit_submission_review(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    payload: SubmitJudgeReviewRequest,
    request: Request,
    org_id: Optional[uuid.UUID] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Subsystem C Sub-Milestone 6.5:
    Submits a final, immutable judge review.
    Enforces complete criterion scores, calculates weighted aggregate score,
    and records an immutable audit event.
    """
    resolved_org_id = _resolve_org_id(request, org_id)
    ip, ua, corr_id = _extract_telemetry(request)
    return await judge_service.submit_judge_review(
        db=db,
        org_id=resolved_org_id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        data=payload,
        current_user=current_user,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.get(
    "/reviews/progress",
    response_model=OrganizerReviewProgressResponse,
)
async def get_hackathon_review_progress(
    hackathon_id: uuid.UUID,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Subsystem C Sub-Milestone 6.5:
    Organizer dashboard showing review progress:
    judge assignments, submissions awaiting review, completion rates, and coverage.
    """
    return await judge_service.get_organizer_review_progress(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
    )


@router.get(
    "/submissions/{submission_id}/reviews",
    response_model=SubmissionReviewsResponse,
)
async def list_submission_all_reviews(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    request: Request,
    org_id: Optional[uuid.UUID] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Subsystem C Sub-Milestone 6.5:
    Lists submitted reviews for a submission.
    Organizers see all submitted reviews; judges see only their own.
    """
    resolved_org_id = _resolve_org_id(request, org_id)
    return await judge_service.list_submission_reviews(
        db=db,
        org_id=resolved_org_id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        current_user=current_user,
    )


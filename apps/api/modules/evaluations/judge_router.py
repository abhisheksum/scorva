from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_db_session
from apps.api.core.exceptions import AppException
from apps.api.dependencies import get_current_user
from apps.api.modules.evaluations.models import HackathonJudge, JudgeReview, Submission
from apps.api.modules.evaluations.schemas import (
    JudgeAssignmentItem,
    JudgeHackathonDetailResponse,
    JudgeQueueItem,
    JudgeReviewDetail,
    JudgeSubmissionReviewResponse,
    SaveJudgeReviewRequest,
    SubmissionEvaluationTransparencyResponse,
    SubmitJudgeReviewRequest,
)
from apps.api.modules.evaluations import judge_service
from apps.api.modules.evaluations.service import get_submission_evaluation_detail
from apps.api.modules.hackathons.models import Hackathon
from apps.api.modules.organizations.models import Organization
from apps.api.modules.users.models import User

router = APIRouter(prefix="/judge", tags=["Judge Workspace"])


def _extract_telemetry(request: Request):
    ip_address = getattr(
        request.state,
        "client_ip",
        request.client.host if request.client else "127.0.0.1",
    )
    user_agent = request.headers.get("user-agent", "Unknown")
    correlation_id = getattr(request.state, "correlation_id", None)
    return ip_address, user_agent, correlation_id


async def _verify_judge_access(
    db: AsyncSession,
    hackathon_id: uuid.UUID,
    user: User,
) -> tuple[Hackathon, Organization]:
    """
    Verifies that the caller has an active judge assignment for the specified hackathon
    or is a platform administrator. Strictly denies unauthorized or cross-hackathon requests.
    """
    stmt = (
        select(Hackathon, Organization)
        .join(Organization, Hackathon.organization_id == Organization.id)
        .where(Hackathon.id == hackathon_id, Hackathon.deleted_at.is_(None))
    )
    res = (await db.execute(stmt)).first()
    if not res:
        raise AppException(
            status_code=404,
            code="HACKATHON_NOT_FOUND",
            message="Hackathon event not found.",
        )
    hackathon, org = res

    # Platform administrator has global oversight; standard judges must be assigned
    if not user.platform_role:
        stmt_judge = select(HackathonJudge).where(
            HackathonJudge.hackathon_id == hackathon_id,
            HackathonJudge.user_id == user.id,
        )
        is_assigned = (await db.execute(stmt_judge)).scalar_one_or_none()
        if not is_assigned:
            raise AppException(
                status_code=status.HTTP_403_FORBIDDEN,
                code="FORBIDDEN_NOT_ASSIGNED_JUDGE",
                message="You are not assigned as a judge for this hackathon.",
            )

    return hackathon, org


@router.get("/assignments", response_model=List[JudgeAssignmentItem])
@router.get("/hackathons", response_model=List[JudgeAssignmentItem], include_in_schema=False)
async def get_my_judge_assignments(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[JudgeAssignmentItem]:
    """
    Lists all hackathon events where the authenticated caller is assigned as a judge,
    with real-time review progress and submission counts.
    """
    return await judge_service.list_judge_assignments(db=db, current_user_id=user.id)


@router.get("/submissions", response_model=List[JudgeQueueItem])
async def list_all_judge_submissions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[JudgeQueueItem]:
    """
    Returns all submissions across all hackathons where the authenticated caller is an assigned judge.
    Supports cross-hackathon overview on /judge/projects and /judge/reviews.
    """
    return await judge_service.list_all_assigned_submissions(db=db, current_user=user)


@router.get("/hackathons/{hackathon_id}", response_model=JudgeHackathonDetailResponse)
async def get_judge_hackathon_detail(
    hackathon_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> JudgeHackathonDetailResponse:
    """
    Retrieves hackathon summary information and review progress for an assigned judge.
    Does not require organization-level membership.
    """
    hackathon, org = await _verify_judge_access(db, hackathon_id, user)

    # Submissions count
    total_subs = (
        await db.execute(
            select(func.count(Submission.id)).where(
                Submission.hackathon_id == hackathon_id,
                Submission.deleted_at.is_(None),
            )
        )
    ).scalar_one() or 0

    # Judge's reviews
    submitted_count = (
        await db.execute(
            select(func.count(JudgeReview.id)).where(
                JudgeReview.hackathon_id == hackathon_id,
                JudgeReview.judge_user_id == user.id,
                JudgeReview.status == "submitted",
            )
        )
    ).scalar_one() or 0

    draft_count = (
        await db.execute(
            select(func.count(JudgeReview.id)).where(
                JudgeReview.hackathon_id == hackathon_id,
                JudgeReview.judge_user_id == user.id,
                JudgeReview.status == "draft",
            )
        )
    ).scalar_one() or 0

    pending_count = max(0, total_subs - submitted_count - draft_count)

    return JudgeHackathonDetailResponse(
        hackathon_id=hackathon.id,
        organization_id=org.id,
        organization_name=org.name,
        organization_slug=org.slug,
        hackathon_title=hackathon.title,
        hackathon_slug=hackathon.slug,
        hackathon_status=hackathon.status.value if hasattr(hackathon.status, "value") else str(hackathon.status),
        description=hackathon.description,
        submission_deadline=hackathon.submission_deadline,
        end_date=hackathon.end_date,
        total_submissions=total_subs,
        my_draft_count=draft_count,
        my_submitted_count=submitted_count,
        my_pending_count=pending_count,
    )


@router.get("/hackathons/{hackathon_id}/submissions", response_model=List[JudgeQueueItem])
@router.get("/hackathons/{hackathon_id}/queue", response_model=List[JudgeQueueItem], include_in_schema=False)
async def get_judge_hackathon_submissions(
    hackathon_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[JudgeQueueItem]:
    """
    Returns the submission review queue for an assigned hackathon judge.
    Strictly verifies judge assignment for the requested hackathon.
    """
    hackathon, org = await _verify_judge_access(db, hackathon_id, user)
    return await judge_service.get_judge_queue(
        db=db,
        org_id=org.id,
        hackathon_id=hackathon_id,
        current_user=user,
    )


@router.get(
    "/hackathons/{hackathon_id}/submissions/{submission_id}/review",
    response_model=JudgeSubmissionReviewResponse,
)
async def get_judge_submission_review(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> JudgeSubmissionReviewResponse:
    """
    Retrieves the review form for a specific submission including published rubric criteria,
    advisory AI assessment findings, and the judge's own review.
    """
    hackathon, org = await _verify_judge_access(db, hackathon_id, user)
    return await judge_service.get_submission_judge_review(
        db=db,
        org_id=org.id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        current_user=user,
    )


@router.post(
    "/hackathons/{hackathon_id}/submissions/{submission_id}/review",
    response_model=JudgeReviewDetail,
)
@router.put(
    "/hackathons/{hackathon_id}/submissions/{submission_id}/review",
    response_model=JudgeReviewDetail,
    include_in_schema=False,
)
async def save_judge_submission_review_draft(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    payload: SaveJudgeReviewRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> JudgeReviewDetail:
    """
    Saves or updates a draft judge review with optimistic concurrency control.
    """
    hackathon, org = await _verify_judge_access(db, hackathon_id, user)
    ip, ua, corr_id = _extract_telemetry(request)
    return await judge_service.save_judge_review_draft(
        db=db,
        org_id=org.id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        data=payload,
        current_user=user,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.post(
    "/hackathons/{hackathon_id}/submissions/{submission_id}/review/submit",
    response_model=JudgeReviewDetail,
)
async def submit_judge_submission_review(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    payload: SubmitJudgeReviewRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> JudgeReviewDetail:
    """
    Submits a final, immutable judge review for a submission.
    """
    hackathon, org = await _verify_judge_access(db, hackathon_id, user)
    ip, ua, corr_id = _extract_telemetry(request)
    return await judge_service.submit_judge_review(
        db=db,
        org_id=org.id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        data=payload,
        current_user=user,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.get(
    "/hackathons/{hackathon_id}/submissions/{submission_id}/transparency",
    response_model=SubmissionEvaluationTransparencyResponse,
)
async def get_judge_submission_ai_transparency(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SubmissionEvaluationTransparencyResponse:
    """
    Retrieves advisory AI evaluation transparency, criterion scores, and grounded evidence
    for an assigned judge without requiring organization-level membership.
    """
    hackathon, org = await _verify_judge_access(db, hackathon_id, user)
    return await get_submission_evaluation_detail(
        db=db,
        org_id=org.id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
    )

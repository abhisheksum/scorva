from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.core.exceptions import AppException
from apps.api.modules.audit.models import AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.evaluations.models import (
    EvaluationCriterionScore,
    EvaluationJob,
    EvaluationResult,
    HackathonJudge,
    JudgeCriterionScore,
    JudgeReview,
    Rubric,
    RubricCriterion,
    RubricVersion,
    Submission,
)
from apps.api.modules.evaluations.schemas import (
    CriterionScoreDetail,
    EvaluationResultDetail,
    EvidenceReferenceDetail,
    JudgeAssignmentItem,
    JudgeCriterionScoreDetail,
    JudgeProgressItem,
    JudgeQueueItem,
    JudgeReviewDetail,
    JudgeSubmissionReviewResponse,
    OrganizerReviewProgressResponse,
    SaveJudgeReviewRequest,
    SubmissionCoverageItem,
    SubmissionReviewsResponse,
    SubmitJudgeReviewRequest,
    sanitize_error_for_display,
)
from apps.api.modules.hackathons.models import Hackathon
from apps.api.modules.organizations.models import Organization, OrganizationMembership, OrgRole
from apps.api.modules.users.models import User


async def list_judge_assignments(
    db: AsyncSession,
    current_user_id: uuid.UUID,
) -> List[JudgeAssignmentItem]:
    """
    Returns all hackathons to which the authenticated user is currently assigned as a judge,
    including real-time review progress counters.
    """
    stmt = (
        select(HackathonJudge, Hackathon, Organization)
        .join(Hackathon, HackathonJudge.hackathon_id == Hackathon.id)
        .join(Organization, Hackathon.organization_id == Organization.id)
        .where(
            HackathonJudge.user_id == current_user_id,
            Organization.deleted_at.is_(None),
        )
        .order_by(Hackathon.start_date.desc().nullslast(), HackathonJudge.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()

    items: List[JudgeAssignmentItem] = []
    for judge_assignment, hackathon, org in rows:
        # Count total active submissions
        total_sub_stmt = select(func.count(Submission.id)).where(
            Submission.hackathon_id == hackathon.id,
            Submission.deleted_at.is_(None),
        )
        total_submissions = (await db.execute(total_sub_stmt)).scalar() or 0

        # Count judge's draft and submitted reviews
        draft_stmt = select(func.count(JudgeReview.id)).where(
            JudgeReview.hackathon_id == hackathon.id,
            JudgeReview.judge_user_id == current_user_id,
            JudgeReview.status == "draft",
        )
        my_draft_count = (await db.execute(draft_stmt)).scalar() or 0

        submitted_stmt = select(func.count(JudgeReview.id)).where(
            JudgeReview.hackathon_id == hackathon.id,
            JudgeReview.judge_user_id == current_user_id,
            JudgeReview.status == "submitted",
        )
        my_submitted_count = (await db.execute(submitted_stmt)).scalar() or 0
        my_pending_count = max(0, total_submissions - my_submitted_count)

        items.append(
            JudgeAssignmentItem(
                hackathon_id=hackathon.id,
                organization_id=org.id,
                organization_name=org.name,
                organization_slug=org.slug,
                hackathon_title=hackathon.title,
                hackathon_slug=hackathon.slug,
                hackathon_status=hackathon.status.value if hasattr(hackathon.status, "value") else str(hackathon.status),
                submission_deadline=hackathon.submission_deadline,
                end_date=hackathon.end_date,
                assigned_at=judge_assignment.created_at,
                total_submissions=total_submissions,
                my_draft_count=my_draft_count,
                my_submitted_count=my_submitted_count,
                my_pending_count=my_pending_count,
            )
        )

    return items


async def get_judge_queue(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    current_user: User,
) -> List[JudgeQueueItem]:
    """
    Returns the list of submissions in a hackathon for the judge review queue.
    Strictly verifies that the caller is an assigned judge or an organization admin/organizer.
    """
    # 1. Verify hackathon belongs to org
    hack_stmt = select(Hackathon).where(
        Hackathon.id == hackathon_id,
        Hackathon.organization_id == org_id,
    )
    hackathon = (await db.execute(hack_stmt)).scalar_one_or_none()
    if not hackathon:
        raise AppException(
            status_code=404,
            code="HACKATHON_NOT_FOUND",
            message="Hackathon not found in this organization.",
        )

    # 2. Verify caller is assigned judge
    is_judge = (
        await db.execute(
            select(HackathonJudge).where(
                HackathonJudge.hackathon_id == hackathon_id,
                HackathonJudge.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()

    if not is_judge:
        raise AppException(
            status_code=403,
            code="FORBIDDEN_NOT_ASSIGNED_JUDGE",
            message="You are not assigned as a judge for this hackathon.",
        )

    # 3. Retrieve all active submissions for hackathon
    sub_stmt = (
        select(Submission)
        .where(
            Submission.hackathon_id == hackathon_id,
            Submission.organization_id == org_id,
            Submission.deleted_at.is_(None),
        )
        .order_by(Submission.created_at.asc())
    )
    submissions = (await db.execute(sub_stmt)).scalars().all()

    queue_items: List[JudgeQueueItem] = []
    for sub in submissions:
        # Fetch latest evaluation job for AI status
        latest_job_stmt = (
            select(EvaluationJob)
            .where(EvaluationJob.submission_id == sub.id)
            .order_by(EvaluationJob.created_at.desc())
            .limit(1)
        )
        latest_job = (await db.execute(latest_job_stmt)).scalar_one_or_none()

        ai_status = "none"
        ai_normalized_score: Optional[Decimal] = None
        if latest_job:
            ai_status = latest_job.status
            if latest_job.current_result_id:
                res = (
                    await db.execute(
                        select(EvaluationResult).where(EvaluationResult.id == latest_job.current_result_id)
                    )
                ).scalar_one_or_none()
                if res:
                    ai_normalized_score = res.normalized_score

        # Fetch judge's review for this submission
        review_stmt = select(JudgeReview).where(
            JudgeReview.submission_id == sub.id,
            JudgeReview.judge_user_id == current_user.id,
        )
        my_review = (await db.execute(review_stmt)).scalar_one_or_none()

        review_status = "not_started"
        review_score: Optional[Decimal] = None
        review_submitted_at: Optional[datetime] = None
        review_updated_at: Optional[datetime] = None

        if my_review:
            review_status = my_review.status
            review_score = my_review.score
            review_submitted_at = my_review.submitted_at
            review_updated_at = my_review.updated_at

        queue_items.append(
            JudgeQueueItem(
                submission_id=sub.id,
                team_name=sub.team_name,
                title=sub.title,
                repository_owner=sub.repository_owner,
                repository_name=sub.repository_name,
                target_branch=sub.target_branch,
                verified_commit_sha=sub.verified_commit_sha,
                connection_status=sub.connection_status,
                ai_evaluation_status=ai_status,
                ai_normalized_score=ai_normalized_score,
                review_status=review_status,
                review_score=review_score,
                review_submitted_at=review_submitted_at,
                review_updated_at=review_updated_at,
                hackathon_id=hackathon_id,
                hackathon_title=hackathon.title if hackathon else None,
                created_at=sub.created_at,
            )
        )

    return queue_items


async def list_all_assigned_submissions(
    db: AsyncSession,
    current_user: User,
) -> List[JudgeQueueItem]:
    """
    Returns all submissions across all hackathons where the authenticated user is an assigned judge.
    Supports cross-hackathon overview on /judge/projects and /judge/reviews.
    """
    stmt = (
        select(HackathonJudge.hackathon_id, Hackathon.title, Hackathon.organization_id)
        .join(Hackathon, HackathonJudge.hackathon_id == Hackathon.id)
        .where(
            HackathonJudge.user_id == current_user.id,
            Hackathon.deleted_at.is_(None),
        )
    )
    assigned_hackathons = (await db.execute(stmt)).all()
    if not assigned_hackathons:
        return []

    hackathon_map = {row[0]: (row[1], row[2]) for row in assigned_hackathons}
    hackathon_ids = list(hackathon_map.keys())

    sub_stmt = (
        select(Submission)
        .where(
            Submission.hackathon_id.in_(hackathon_ids),
            Submission.deleted_at.is_(None),
        )
        .order_by(Submission.created_at.desc())
    )
    submissions = (await db.execute(sub_stmt)).scalars().all()

    queue_items: List[JudgeQueueItem] = []
    for sub in submissions:
        hack_title, _ = hackathon_map.get(sub.hackathon_id, (None, None))

        latest_job_stmt = (
            select(EvaluationJob)
            .where(EvaluationJob.submission_id == sub.id)
            .order_by(EvaluationJob.created_at.desc())
            .limit(1)
        )
        latest_job = (await db.execute(latest_job_stmt)).scalar_one_or_none()

        ai_status = "none"
        ai_normalized_score: Optional[Decimal] = None
        if latest_job:
            ai_status = latest_job.status
            if latest_job.current_result_id:
                res = (
                    await db.execute(
                        select(EvaluationResult).where(EvaluationResult.id == latest_job.current_result_id)
                    )
                ).scalar_one_or_none()
                if res:
                    ai_normalized_score = res.normalized_score

        review_stmt = select(JudgeReview).where(
            JudgeReview.submission_id == sub.id,
            JudgeReview.judge_user_id == current_user.id,
        )
        my_review = (await db.execute(review_stmt)).scalar_one_or_none()

        review_status = "not_started"
        review_score: Optional[Decimal] = None
        review_submitted_at: Optional[datetime] = None
        review_updated_at: Optional[datetime] = None

        if my_review:
            review_status = my_review.status
            review_score = my_review.score
            review_submitted_at = my_review.submitted_at
            review_updated_at = my_review.updated_at

        queue_items.append(
            JudgeQueueItem(
                submission_id=sub.id,
                team_name=sub.team_name,
                title=sub.title,
                repository_owner=sub.repository_owner,
                repository_name=sub.repository_name,
                target_branch=sub.target_branch,
                verified_commit_sha=sub.verified_commit_sha,
                connection_status=sub.connection_status,
                ai_evaluation_status=ai_status,
                ai_normalized_score=ai_normalized_score,
                review_status=review_status,
                review_score=review_score,
                review_submitted_at=review_submitted_at,
                review_updated_at=review_updated_at,
                hackathon_id=sub.hackathon_id,
                hackathon_title=hack_title,
                created_at=sub.created_at,
            )
        )

    return queue_items


async def get_submission_judge_review(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    current_user: User,
    target_judge_user_id: Optional[uuid.UUID] = None,
) -> JudgeSubmissionReviewResponse:
    """
    Retrieves the review form for a specific submission, including:
    - Submission details and repository metadata
    - Published rubric criteria
    - Advisory AI assessment results and grounded evidence citations (if available)
    - The judge's own draft or submitted review
    """
    # 1. Resolve submission & hackathon
    sub_stmt = select(Submission).where(
        Submission.id == submission_id,
        Submission.hackathon_id == hackathon_id,
        Submission.organization_id == org_id,
        Submission.deleted_at.is_(None),
    )
    submission = (await db.execute(sub_stmt)).scalar_one_or_none()
    if not submission:
        raise AppException(
            status_code=404,
            code="SUBMISSION_NOT_FOUND",
            message="Submission not found in this hackathon.",
        )

    hackathon_stmt = select(Hackathon).where(
        Hackathon.id == hackathon_id,
        Hackathon.deleted_at.is_(None),
    )
    hackathon = (await db.execute(hackathon_stmt)).scalar_one_or_none()

    # 2. Authorization check
    judge_user_id = target_judge_user_id or current_user.id
    is_self = judge_user_id == current_user.id

    is_assigned = (
        await db.execute(
            select(HackathonJudge).where(
                HackathonJudge.hackathon_id == hackathon_id,
                HackathonJudge.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()

    # Check if caller is org member
    mem = (
        await db.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == org_id,
                OrganizationMembership.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    is_org_staff = mem and mem.role in (OrgRole.ORG_OWNER, OrgRole.ORG_ADMIN, OrgRole.ORGANIZER)

    if is_self:
        if not is_assigned:
            raise AppException(
                status_code=403,
                code="FORBIDDEN_NOT_ASSIGNED_JUDGE",
                message="You are not assigned as a judge for this hackathon.",
            )
    else:
        # Caller is attempting to view another judge's review
        if not is_org_staff:
            raise AppException(
                status_code=403,
                code="FORBIDDEN_PRIVATE_REVIEW",
                message="You are not authorized to view another judge's review.",
            )
        # Even org staff cannot view private drafts of other judges
        target_rev = (
            await db.execute(
                select(JudgeReview).where(
                    JudgeReview.submission_id == submission_id,
                    JudgeReview.judge_user_id == judge_user_id,
                )
            )
        ).scalar_one_or_none()
        if target_rev and target_rev.status == "draft":
            raise AppException(
                status_code=403,
                code="FORBIDDEN_PRIVATE_REVIEW",
                message="Draft reviews are private to the assigned judge.",
            )

    # 3. Resolve published rubric
    rubric_stmt = (
        select(Rubric)
        .options(
            selectinload(Rubric.versions).selectinload(RubricVersion.criteria)
        )
        .where(
            Rubric.hackathon_id == hackathon_id,
            Rubric.organization_id == org_id,
        )
    )
    rubric = (await db.execute(rubric_stmt)).scalar_one_or_none()
    if not rubric:
        raise AppException(
            status_code=404,
            code="RUBRIC_NOT_FOUND",
            message="No rubric has been configured for this hackathon.",
        )

    published_version: Optional[RubricVersion] = None
    for v in rubric.versions:
        if v.status == "published":
            published_version = v
            break

    if not published_version:
        raise AppException(
            status_code=400,
            code="NO_PUBLISHED_RUBRIC",
            message="The rubric for this hackathon has not been published yet.",
        )

    criteria_list = sorted(published_version.criteria, key=lambda c: c.order_index)

    # 4. Resolve AI evaluation results (if available)
    ai_eval_detail: Optional[EvaluationResultDetail] = None
    ai_scores_map: Dict[uuid.UUID, Dict[str, Any]] = {}

    try:
        from apps.api.modules.evaluations.service import get_submission_evaluation_detail
        ai_transparency = await get_submission_evaluation_detail(
            db=db,
            org_id=org_id,
            hackathon_id=hackathon_id,
            submission_id=submission_id,
        )
        if ai_transparency.result:
            ai_eval_detail = ai_transparency.result
            for cs in ai_eval_detail.criterion_scores:
                ai_scores_map[cs.criterion_id] = {
                    "score": cs.awarded_score,
                    "rationale": cs.rationale,
                }
    except Exception:
        ai_eval_detail = None

    # 5. Fetch human judge review
    review_stmt = (
        select(JudgeReview)
        .options(selectinload(JudgeReview.criterion_scores))
        .where(
            JudgeReview.submission_id == submission_id,
            JudgeReview.judge_user_id == judge_user_id,
        )
    )
    existing_review = (await db.execute(review_stmt)).scalar_one_or_none()

    judge_user: Optional[User] = None
    if existing_review:
        judge_user = (await db.execute(select(User).where(User.id == existing_review.judge_user_id))).scalar_one_or_none()

    review_detail: Optional[JudgeReviewDetail] = None
    if existing_review:
        human_scores_map = {cs.criterion_id: cs for cs in existing_review.criterion_scores}
        review_criterion_details: List[JudgeCriterionScoreDetail] = []
        for c in criteria_list:
            cs = human_scores_map.get(c.id)
            ai_data = ai_scores_map.get(c.id, {})
            review_criterion_details.append(
                JudgeCriterionScoreDetail(
                    id=cs.id if cs else None,
                    criterion_id=c.id,
                    criterion_title=c.title,
                    weight=c.weight,
                    min_score=c.min_score,
                    max_score=c.max_score,
                    score=cs.score if cs else None,
                    judge_notes=cs.judge_notes if cs else None,
                    ai_suggested_score=ai_data.get("score"),
                    ai_rationale=ai_data.get("rationale"),
                )
            )

        review_detail = JudgeReviewDetail(
            id=existing_review.id,
            organization_id=existing_review.organization_id,
            hackathon_id=existing_review.hackathon_id,
            submission_id=existing_review.submission_id,
            rubric_version_id=existing_review.rubric_version_id,
            judge_user_id=existing_review.judge_user_id,
            judge_name=judge_user.full_name if judge_user else None,
            judge_email=judge_user.email if judge_user else None,
            status=existing_review.status,
            score=existing_review.score,
            overall_feedback=existing_review.overall_feedback,
            decision=existing_review.decision,
            version=existing_review.version,
            created_at=existing_review.created_at,
            updated_at=existing_review.updated_at,
            submitted_at=existing_review.submitted_at,
            criterion_scores=review_criterion_details,
        )

    # 6. Check can_edit
    can_edit = bool(
        is_assigned
        and is_self
        and (not existing_review or existing_review.status == "draft")
    )

    rubric_criteria_dicts = [
        {
            "id": c.id,
            "title": c.title,
            "description": c.description,
            "weight": c.weight,
            "min_score": c.min_score,
            "max_score": c.max_score,
            "evidence_requirements": c.evidence_requirements,
            "order_index": c.order_index,
        }
        for c in criteria_list
    ]

    return JudgeSubmissionReviewResponse(
        submission_id=submission.id,
        hackathon_id=hackathon_id,
        organization_id=org_id,
        team_name=submission.team_name,
        submission_title=submission.title,
        description=submission.description,
        created_at=submission.created_at,
        hackathon_title=hackathon.title if hackathon else None,
        repository_url=submission.repository_url,
        repository_owner=submission.repository_owner,
        repository_name=submission.repository_name,
        target_branch=submission.target_branch,
        verified_commit_sha=submission.verified_commit_sha,
        connection_status=submission.connection_status,
        rubric_id=rubric.id,
        rubric_version_id=published_version.id,
        rubric_name=rubric.name,
        rubric_criteria=rubric_criteria_dicts,
        ai_evaluation=ai_eval_detail,
        review=review_detail,
        can_edit=can_edit,
    )


async def save_judge_review_draft(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    data: SaveJudgeReviewRequest,
    current_user: User,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[str] = None,
) -> JudgeReviewDetail:
    """
    Saves or updates a draft judge review with optimistic concurrency control.
    Partial criterion scoring is permitted on drafts.
    """
    # 1. Verify active judge assignment
    is_judge = (
        await db.execute(
            select(HackathonJudge).where(
                HackathonJudge.hackathon_id == hackathon_id,
                HackathonJudge.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()

    if not is_judge:
        raise AppException(
            status_code=403,
            code="FORBIDDEN_NOT_ASSIGNED_JUDGE",
            message="You are not assigned as a judge for this hackathon.",
        )

    # 2. Verify submission belongs to hackathon and organization
    sub_stmt = select(Submission).where(
        Submission.id == submission_id,
        Submission.hackathon_id == hackathon_id,
        Submission.organization_id == org_id,
        Submission.deleted_at.is_(None),
    )
    submission = (await db.execute(sub_stmt)).scalar_one_or_none()
    if not submission:
        raise AppException(
            status_code=404,
            code="SUBMISSION_NOT_FOUND",
            message="Submission not found.",
        )

    # 3. Resolve published rubric version
    rubric_stmt = (
        select(Rubric)
        .options(selectinload(Rubric.versions).selectinload(RubricVersion.criteria))
        .where(
            Rubric.hackathon_id == hackathon_id,
            Rubric.organization_id == org_id,
        )
    )
    rubric = (await db.execute(rubric_stmt)).scalar_one_or_none()
    if not rubric:
        raise AppException(status_code=400, code="RUBRIC_NOT_FOUND", message="Rubric not found.")

    published_version: Optional[RubricVersion] = None
    for v in rubric.versions:
        if v.status == "published":
            published_version = v
            break

    if not published_version:
        raise AppException(
            status_code=400,
            code="NO_PUBLISHED_RUBRIC",
            message="Hackathon does not have a published rubric.",
        )

    criteria_by_id = {c.id: c for c in published_version.criteria}

    # 4. Validate supplied criteria
    for cs in data.criterion_scores:
        if cs.criterion_id not in criteria_by_id:
            raise AppException(
                status_code=400,
                code="UNKNOWN_CRITERION_ID",
                message=f"Criterion '{cs.criterion_id}' is not part of the published rubric version.",
            )
        crit = criteria_by_id[cs.criterion_id]
        if cs.score < crit.min_score or cs.score > crit.max_score:
            raise AppException(
                status_code=400,
                code="SCORE_OUT_OF_BOUNDS",
                message=f"Score {cs.score} for '{crit.title}' is outside permitted range [{crit.min_score}, {crit.max_score}].",
            )

    # 5. Load or create review
    review_stmt = (
        select(JudgeReview)
        .options(selectinload(JudgeReview.criterion_scores))
        .where(
            JudgeReview.submission_id == submission_id,
            JudgeReview.judge_user_id == current_user.id,
        )
    )
    existing_review = (await db.execute(review_stmt)).scalar_one_or_none()

    is_new = False
    if existing_review:
        if existing_review.status == "submitted":
            raise AppException(
                status_code=400,
                code="REVIEW_ALREADY_SUBMITTED",
                message="This review has already been submitted and cannot be modified.",
            )
        # Optimistic concurrency check
        if data.version is not None and data.version != existing_review.version:
            raise AppException(
                status_code=409,
                code="CONCURRENT_MODIFICATION_DETECTED",
                message="This review was updated by another request. Please reload and try again.",
            )
        review = existing_review
        review.overall_feedback = data.overall_feedback
        review.decision = data.decision
        review.version += 1
    else:
        is_new = True
        review = JudgeReview(
            organization_id=org_id,
            hackathon_id=hackathon_id,
            submission_id=submission_id,
            rubric_version_id=published_version.id,
            judge_user_id=current_user.id,
            status="draft",
            overall_feedback=data.overall_feedback,
            decision=data.decision,
            version=1,
        )
        db.add(review)
        await db.flush()

    # 6. Sync criterion scores
    if not is_new:
        await db.execute(
            delete(JudgeCriterionScore).where(JudgeCriterionScore.judge_review_id == review.id)
        )
        await db.flush()

    # Calculate tentative weighted score if criteria are provided
    total_weight = Decimal("0.00")
    weighted_sum = Decimal("0.00")
    for cs in data.criterion_scores:
        crit = criteria_by_id[cs.criterion_id]
        score_row = JudgeCriterionScore(
            judge_review_id=review.id,
            criterion_id=cs.criterion_id,
            score=cs.score,
            adjusted_awarded_score=cs.score,
            judge_notes=cs.judge_notes,
        )
        db.add(score_row)
        weighted_sum += cs.score * crit.weight
        total_weight += crit.weight

    if total_weight > 0:
        review.score = (weighted_sum / total_weight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        review.adjusted_score = review.score

    await db.flush()

    # 7. Record audit event
    await record_audit_event(
        db=db,
        action="judge_review_draft_saved",
        resource_type="judge_review",
        resource_id=str(review.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        actor_role="judge",
        organization_id=org_id,
        reason=f"Saved draft review for submission '{submission.title}'",
        diff_payload={
            "submission_id": str(submission_id),
            "version": review.version,
            "status": review.status,
            "scored_criteria_count": len(data.criterion_scores),
        },
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    # Refresh review to ensure all server defaults/onupdate attributes are loaded
    await db.refresh(review)

    # Re-query saved criterion scores
    stmt_scores = select(JudgeCriterionScore).where(
        JudgeCriterionScore.judge_review_id == review.id
    )
    saved_scores = (await db.execute(stmt_scores)).scalars().all()
    human_scores_map = {cs.criterion_id: cs for cs in saved_scores}
    criterion_details = [
        JudgeCriterionScoreDetail(
            id=human_scores_map[c.id].id if c.id in human_scores_map else None,
            criterion_id=c.id,
            criterion_title=c.title,
            weight=c.weight,
            min_score=c.min_score,
            max_score=c.max_score,
            score=human_scores_map[c.id].score if c.id in human_scores_map else None,
            judge_notes=human_scores_map[c.id].judge_notes if c.id in human_scores_map else None,
        )
        for c in sorted(published_version.criteria, key=lambda x: x.order_index)
    ]

    return JudgeReviewDetail(
        id=review.id,
        organization_id=review.organization_id,
        hackathon_id=review.hackathon_id,
        submission_id=review.submission_id,
        rubric_version_id=review.rubric_version_id,
        judge_user_id=review.judge_user_id,
        judge_name=current_user.full_name,
        judge_email=current_user.email,
        status=review.status,
        score=review.score,
        overall_feedback=review.overall_feedback,
        decision=review.decision,
        version=review.version,
        created_at=review.created_at,
        updated_at=review.updated_at,
        submitted_at=review.submitted_at,
        criterion_scores=criterion_details,
    )


async def submit_judge_review(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    data: SubmitJudgeReviewRequest,
    current_user: User,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[str] = None,
) -> JudgeReviewDetail:
    """
    Submits a final, immutable judge review.
    Enforces that ALL published criteria are complete, valid, and within range.
    Atomically calculates weighted aggregate score and records audit event.
    """
    # 1. Verify judge assignment
    is_judge = (
        await db.execute(
            select(HackathonJudge).where(
                HackathonJudge.hackathon_id == hackathon_id,
                HackathonJudge.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()

    if not is_judge:
        raise AppException(
            status_code=403,
            code="FORBIDDEN_NOT_ASSIGNED_JUDGE",
            message="You are not assigned as a judge for this hackathon.",
        )

    # 2. Verify submission
    sub_stmt = select(Submission).where(
        Submission.id == submission_id,
        Submission.hackathon_id == hackathon_id,
        Submission.organization_id == org_id,
        Submission.deleted_at.is_(None),
    )
    submission = (await db.execute(sub_stmt)).scalar_one_or_none()
    if not submission:
        raise AppException(
            status_code=404,
            code="SUBMISSION_NOT_FOUND",
            message="Submission not found.",
        )

    # 3. Resolve published rubric
    rubric_stmt = (
        select(Rubric)
        .options(selectinload(Rubric.versions).selectinload(RubricVersion.criteria))
        .where(
            Rubric.hackathon_id == hackathon_id,
            Rubric.organization_id == org_id,
        )
    )
    rubric = (await db.execute(rubric_stmt)).scalar_one_or_none()
    if not rubric:
        raise AppException(status_code=400, code="RUBRIC_NOT_FOUND", message="Rubric not found.")

    published_version: Optional[RubricVersion] = None
    for v in rubric.versions:
        if v.status == "published":
            published_version = v
            break

    if not published_version:
        raise AppException(
            status_code=400,
            code="NO_PUBLISHED_RUBRIC",
            message="Hackathon does not have a published rubric.",
        )

    criteria_by_id = {c.id: c for c in published_version.criteria}
    required_criterion_ids = set(criteria_by_id.keys())
    provided_criterion_ids = {cs.criterion_id for cs in data.criterion_scores}

    # 4. Enforce that ALL criteria are scored
    missing = required_criterion_ids - provided_criterion_ids
    if missing:
        missing_titles = [criteria_by_id[cid].title for cid in missing]
        raise AppException(
            status_code=400,
            code="MISSING_REQUIRED_CRITERIA",
            message=f"All published criteria must be scored to submit review. Missing: {', '.join(missing_titles)}.",
        )

    unknown = provided_criterion_ids - required_criterion_ids
    if unknown:
        raise AppException(
            status_code=400,
            code="UNKNOWN_CRITERION_ID",
            message=f"Submitted criteria contains unknown IDs not in the published rubric version: {unknown}.",
        )

    # 5. Validate score bounds and compute weighted score
    total_weight = Decimal("0.00")
    weighted_sum = Decimal("0.00")
    for cs in data.criterion_scores:
        crit = criteria_by_id[cs.criterion_id]
        if cs.score < crit.min_score or cs.score > crit.max_score:
            raise AppException(
                status_code=400,
                code="SCORE_OUT_OF_BOUNDS",
                message=f"Score {cs.score} for '{crit.title}' is outside permitted range [{crit.min_score}, {crit.max_score}].",
            )
        weighted_sum += cs.score * crit.weight
        total_weight += crit.weight

    if total_weight <= Decimal("0.00"):
        raise AppException(
            status_code=400,
            code="INVALID_RUBRIC_WEIGHTS",
            message="Rubric criteria total weight must be greater than zero.",
        )

    final_score = (weighted_sum / total_weight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 6. Load or create review
    review_stmt = (
        select(JudgeReview)
        .options(selectinload(JudgeReview.criterion_scores))
        .where(
            JudgeReview.submission_id == submission_id,
            JudgeReview.judge_user_id == current_user.id,
        )
    )
    existing_review = (await db.execute(review_stmt)).scalar_one_or_none()

    now_utc = datetime.now(timezone.utc)
    is_new = False
    if existing_review:
        if existing_review.status == "submitted":
            raise AppException(
                status_code=400,
                code="REVIEW_ALREADY_SUBMITTED",
                message="This review has already been submitted and cannot be modified.",
            )
        if data.version is not None and data.version != existing_review.version:
            raise AppException(
                status_code=409,
                code="CONCURRENT_MODIFICATION_DETECTED",
                message="This review was updated by another request. Please reload and try again.",
            )
        review = existing_review
        review.status = "submitted"
        review.submitted_at = now_utc
        review.score = final_score
        review.adjusted_score = final_score
        review.overall_feedback = data.overall_feedback
        review.decision = data.decision or "accepted"
        review.version += 1
    else:
        is_new = True
        review = JudgeReview(
            organization_id=org_id,
            hackathon_id=hackathon_id,
            submission_id=submission_id,
            rubric_version_id=published_version.id,
            judge_user_id=current_user.id,
            status="submitted",
            submitted_at=now_utc,
            score=final_score,
            adjusted_score=final_score,
            overall_feedback=data.overall_feedback,
            decision=data.decision or "accepted",
            version=1,
        )
        db.add(review)
        await db.flush()

    # 7. Persist criterion scores atomically
    if not is_new:
        await db.execute(
            delete(JudgeCriterionScore).where(JudgeCriterionScore.judge_review_id == review.id)
        )
        await db.flush()

    for cs in data.criterion_scores:
        score_row = JudgeCriterionScore(
            judge_review_id=review.id,
            criterion_id=cs.criterion_id,
            score=cs.score,
            adjusted_awarded_score=cs.score,
            judge_notes=cs.judge_notes,
        )
        db.add(score_row)

    await db.flush()

    # 8. Immutable audit event
    await record_audit_event(
        db=db,
        action="judge_review_submitted",
        resource_type="judge_review",
        resource_id=str(review.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        actor_role="judge",
        organization_id=org_id,
        reason=f"Submitted final judge review for submission '{submission.title}' with score {final_score}",
        diff_payload={
            "submission_id": str(submission_id),
            "version": review.version,
            "status": review.status,
            "final_score": str(final_score),
            "decision": review.decision,
            "criteria_count": len(data.criterion_scores),
        },
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    # Refresh review to ensure all server defaults/onupdate attributes are loaded
    await db.refresh(review)

    # Re-query saved criterion scores
    stmt_scores = select(JudgeCriterionScore).where(
        JudgeCriterionScore.judge_review_id == review.id
    )
    saved_scores = (await db.execute(stmt_scores)).scalars().all()
    human_scores_map = {cs.criterion_id: cs for cs in saved_scores}
    criterion_details = [
        JudgeCriterionScoreDetail(
            id=human_scores_map[c.id].id if c.id in human_scores_map else None,
            criterion_id=c.id,
            criterion_title=c.title,
            weight=c.weight,
            min_score=c.min_score,
            max_score=c.max_score,
            score=human_scores_map[c.id].score if c.id in human_scores_map else None,
            judge_notes=human_scores_map[c.id].judge_notes if c.id in human_scores_map else None,
        )
        for c in sorted(published_version.criteria, key=lambda x: x.order_index)
    ]

    return JudgeReviewDetail(
        id=review.id,
        organization_id=review.organization_id,
        hackathon_id=review.hackathon_id,
        submission_id=review.submission_id,
        rubric_version_id=review.rubric_version_id,
        judge_user_id=review.judge_user_id,
        judge_name=current_user.full_name,
        judge_email=current_user.email,
        status=review.status,
        score=review.score,
        overall_feedback=review.overall_feedback,
        decision=review.decision,
        version=review.version,
        created_at=review.created_at,
        updated_at=review.updated_at,
        submitted_at=review.submitted_at,
        criterion_scores=criterion_details,
    )


async def get_organizer_review_progress(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
) -> OrganizerReviewProgressResponse:
    """
    Returns hackathon review progress for organizers:
    - Total submissions, assigned judges, submissions awaiting review
    - Draft and submitted review counts
    - Per-judge review completion counts
    - Submission coverage breakdown with average human scores
    """
    # 1. Total submissions
    total_submissions = (
        await db.execute(
            select(func.count(Submission.id)).where(
                Submission.hackathon_id == hackathon_id,
                Submission.organization_id == org_id,
                Submission.deleted_at.is_(None),
            )
        )
    ).scalar() or 0

    # 2. Total judges
    total_judges = (
        await db.execute(
            select(func.count(HackathonJudge.id)).where(
                HackathonJudge.hackathon_id == hackathon_id
            )
        )
    ).scalar() or 0

    # 3. Overall reviews counts
    draft_reviews_count = (
        await db.execute(
            select(func.count(JudgeReview.id)).where(
                JudgeReview.hackathon_id == hackathon_id,
                JudgeReview.status == "draft",
            )
        )
    ).scalar() or 0

    submitted_reviews_count = (
        await db.execute(
            select(func.count(JudgeReview.id)).where(
                JudgeReview.hackathon_id == hackathon_id,
                JudgeReview.status == "submitted",
            )
        )
    ).scalar() or 0

    # 4. Submissions with reviews & submissions fully reviewed
    submissions_with_reviews = (
        await db.execute(
            select(func.count(func.distinct(JudgeReview.submission_id))).where(
                JudgeReview.hackathon_id == hackathon_id
            )
        )
    ).scalar() or 0

    submissions_fully_reviewed = (
        await db.execute(
            select(func.count(func.distinct(JudgeReview.submission_id))).where(
                JudgeReview.hackathon_id == hackathon_id,
                JudgeReview.status == "submitted",
            )
        )
    ).scalar() or 0

    submissions_awaiting_review = max(0, total_submissions - submissions_fully_reviewed)

    # 5. Judge progress breakdown
    judge_stmt = (
        select(HackathonJudge, User)
        .join(User, HackathonJudge.user_id == User.id)
        .where(HackathonJudge.hackathon_id == hackathon_id)
        .order_by(HackathonJudge.created_at.asc())
    )
    judge_rows = (await db.execute(judge_stmt)).all()

    judge_progress: List[JudgeProgressItem] = []
    for hj, u in judge_rows:
        j_submitted = (
            await db.execute(
                select(func.count(JudgeReview.id)).where(
                    JudgeReview.hackathon_id == hackathon_id,
                    JudgeReview.judge_user_id == hj.user_id,
                    JudgeReview.status == "submitted",
                )
            )
        ).scalar() or 0

        j_draft = (
            await db.execute(
                select(func.count(JudgeReview.id)).where(
                    JudgeReview.hackathon_id == hackathon_id,
                    JudgeReview.judge_user_id == hj.user_id,
                    JudgeReview.status == "draft",
                )
            )
        ).scalar() or 0

        judge_progress.append(
            JudgeProgressItem(
                judge_user_id=hj.user_id,
                judge_name=u.full_name,
                judge_email=u.email,
                assigned_at=hj.created_at,
                submitted_count=j_submitted,
                draft_count=j_draft,
                pending_count=max(0, total_submissions - j_submitted),
            )
        )

    # 6. Submission coverage breakdown
    sub_stmt = (
        select(Submission)
        .where(
            Submission.hackathon_id == hackathon_id,
            Submission.organization_id == org_id,
            Submission.deleted_at.is_(None),
        )
        .order_by(Submission.created_at.asc())
    )
    subs = (await db.execute(sub_stmt)).scalars().all()

    submission_coverage: List[SubmissionCoverageItem] = []
    for s in subs:
        s_submitted = (
            await db.execute(
                select(func.count(JudgeReview.id)).where(
                    JudgeReview.submission_id == s.id,
                    JudgeReview.status == "submitted",
                )
            )
        ).scalar() or 0

        s_draft = (
            await db.execute(
                select(func.count(JudgeReview.id)).where(
                    JudgeReview.submission_id == s.id,
                    JudgeReview.status == "draft",
                )
            )
        ).scalar() or 0

        avg_score_raw = (
            await db.execute(
                select(func.avg(JudgeReview.score)).where(
                    JudgeReview.submission_id == s.id,
                    JudgeReview.status == "submitted",
                )
            )
        ).scalar()
        avg_score = Decimal(str(avg_score_raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if avg_score_raw is not None else None

        submission_coverage.append(
            SubmissionCoverageItem(
                submission_id=s.id,
                team_name=s.team_name,
                title=s.title,
                submitted_reviews_count=s_submitted,
                draft_reviews_count=s_draft,
                average_human_score=avg_score,
            )
        )

    return OrganizerReviewProgressResponse(
        total_submissions=total_submissions,
        total_judges=total_judges,
        submissions_with_reviews=submissions_with_reviews,
        submissions_fully_reviewed=submissions_fully_reviewed,
        submissions_awaiting_review=submissions_awaiting_review,
        draft_reviews_count=draft_reviews_count,
        submitted_reviews_count=submitted_reviews_count,
        judge_progress=judge_progress,
        submission_coverage=submission_coverage,
    )


async def list_submission_reviews(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    current_user: User,
) -> SubmissionReviewsResponse:
    """
    Returns submitted reviews for a submission.
    Organizers can view all submitted reviews.
    Judges can only view their own reviews.
    """
    # 1. Verify submission
    sub_stmt = select(Submission).where(
        Submission.id == submission_id,
        Submission.hackathon_id == hackathon_id,
        Submission.organization_id == org_id,
        Submission.deleted_at.is_(None),
    )
    submission = (await db.execute(sub_stmt)).scalar_one_or_none()
    if not submission:
        raise AppException(
            status_code=404,
            code="SUBMISSION_NOT_FOUND",
            message="Submission not found.",
        )

    # 2. Check if organizer
    mem = (
        await db.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == org_id,
                OrganizationMembership.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    is_org_staff = mem and mem.role in (OrgRole.ORG_OWNER, OrgRole.ORG_ADMIN, OrgRole.ORGANIZER)

    # 3. Query reviews
    if is_org_staff:
        stmt = (
            select(JudgeReview, User)
            .join(User, JudgeReview.judge_user_id == User.id)
            .options(selectinload(JudgeReview.criterion_scores))
            .where(
                JudgeReview.submission_id == submission_id,
                JudgeReview.status == "submitted",
            )
            .order_by(JudgeReview.submitted_at.desc())
        )
    else:
        # Judge only sees their own review
        stmt = (
            select(JudgeReview, User)
            .join(User, JudgeReview.judge_user_id == User.id)
            .options(selectinload(JudgeReview.criterion_scores))
            .where(
                JudgeReview.submission_id == submission_id,
                JudgeReview.judge_user_id == current_user.id,
            )
        )

    rows = (await db.execute(stmt)).all()

    reviews: List[JudgeReviewDetail] = []
    for r, u in rows:
        criterion_details = [
            JudgeCriterionScoreDetail(
                id=cs.id,
                criterion_id=cs.criterion_id,
                criterion_title="",
                weight=Decimal("1.00"),
                min_score=Decimal("0.00"),
                max_score=Decimal("10.00"),
                score=cs.score,
                judge_notes=cs.judge_notes,
            )
            for cs in r.criterion_scores
        ]
        reviews.append(
            JudgeReviewDetail(
                id=r.id,
                organization_id=r.organization_id,
                hackathon_id=r.hackathon_id,
                submission_id=r.submission_id,
                rubric_version_id=r.rubric_version_id,
                judge_user_id=r.judge_user_id,
                judge_name=u.full_name,
                judge_email=u.email,
                status=r.status,
                score=r.score,
                overall_feedback=r.overall_feedback,
                decision=r.decision,
                version=r.version,
                created_at=r.created_at,
                updated_at=r.updated_at,
                submitted_at=r.submitted_at,
                criterion_scores=criterion_details,
            )
        )

    return SubmissionReviewsResponse(
        submission_id=submission_id,
        reviews=reviews,
    )

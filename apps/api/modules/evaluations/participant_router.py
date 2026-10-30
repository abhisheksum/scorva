from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
import uuid
import secrets

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.core.database import get_db_session
from apps.api.core.exceptions import AppException
from apps.api.dependencies import get_current_user
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.evaluations.models import (
    EvaluationJob,
    EvaluationResult,
    JudgeCriterionScore,
    JudgeReview,
    Rubric,
    RubricCriterion,
    RubricVersion,
    Submission,
    Team,
    TeamMember,
)
from apps.api.modules.hackathons.models import Hackathon
from apps.api.modules.organizations.models import Organization
from apps.api.modules.users.models import User

router = APIRouter(prefix="/participant", tags=["Participant Workspace"])


# =========================================================================
# SCHEMAS
# =========================================================================

class ParticipantSubmissionSummary(BaseModel):
    submission_id: uuid.UUID
    title: str
    description: Optional[str] = None
    repository_url: str
    repository_owner: Optional[str] = None
    repository_name: Optional[str] = None
    default_branch: Optional[str] = None
    verified_commit_sha: Optional[str] = None
    connection_status: str = "unverified"
    status: str = "pending"
    verified_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ParticipantTeamItem(BaseModel):
    team_id: uuid.UUID
    team_name: str
    join_code: str
    role_in_team: str
    joined_at: datetime
    hackathon_id: uuid.UUID
    hackathon_title: str
    hackathon_status: str
    submission_deadline: Optional[datetime] = None
    organization_id: uuid.UUID
    organization_name: str
    team_members: List[str] = Field(default_factory=list)
    submission: Optional[ParticipantSubmissionSummary] = None

    model_config = ConfigDict(from_attributes=True)


class LifecycleStageItem(BaseModel):
    id: str
    name: str
    status: str  # 'completed' | 'in_progress' | 'upcoming'
    completed_at: Optional[datetime] = None
    description: str


class ParticipantOverviewResponse(BaseModel):
    welcome_name: str
    active_hackathons_count: int
    submission_status: str
    current_rank: Optional[int] = None
    total_score: Optional[float] = None
    participations: List[ParticipantTeamItem] = Field(default_factory=list)
    stages: List[LifecycleStageItem] = Field(default_factory=list)
    recent_updates: List[Dict[str, Any]] = Field(default_factory=list)
    upcoming_deadlines: List[Dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class LeaderboardEntry(BaseModel):
    rank: int
    team_name: str
    project_title: str
    score: float
    status: str
    is_my_team: bool


class LeaderboardResponse(BaseModel):
    hackathon_id: uuid.UUID
    hackathon_title: str
    is_published: bool
    message: Optional[str] = None
    entries: List[LeaderboardEntry] = Field(default_factory=list)


class CriterionBreakdownItem(BaseModel):
    criterion_id: str
    criterion_name: str
    max_score: float
    awarded_score: Optional[float] = None
    weight: float
    progress_percentage: float
    rationale: Optional[str] = None


class PerformanceResponse(BaseModel):
    has_submission: bool
    submission_id: Optional[uuid.UUID] = None
    submission_title: Optional[str] = None
    team_name: Optional[str] = None
    hackathon_title: Optional[str] = None
    evaluation_status: str  # 'pending' | 'evaluating' | 'completed' | 'published'
    final_score: Optional[float] = None
    max_score: float = 100.0
    current_rank: Optional[int] = None
    completed_reviews_count: int = 0
    criteria_breakdown: List[CriterionBreakdownItem] = Field(default_factory=list)
    authorized_feedback: List[str] = Field(default_factory=list)
    ai_summary: Optional[str] = None


class ParticipantTaskItem(BaseModel):
    id: str
    title: str
    description: str
    issued_by: str
    hackathon_title: str
    category: str  # 'task' | 'sponsorship' | 'requirement'
    due_date: Optional[str] = None
    status: str  # 'new' | 'in_progress' | 'completed' | 'overdue'
    action_url: Optional[str] = None
    sponsor_name: Optional[str] = None


class UpdateTaskStatusRequest(BaseModel):
    status: str = Field(..., description="'new', 'in_progress', or 'completed'")


class ParticipantNotificationItem(BaseModel):
    id: str
    title: str
    description: str
    created_at: str
    type: str  # 'team' | 'submission' | 'evaluation' | 'announcement' | 'support'
    is_read: bool
    action_url: Optional[str] = None


class NotificationListResponse(BaseModel):
    unread_count: int
    notifications: List[ParticipantNotificationItem] = Field(default_factory=list)


class SupportTicketItem(BaseModel):
    id: uuid.UUID
    ticket_number: str
    category: str
    subject: str
    description: str
    status: str  # 'open' | 'in_progress' | 'waiting_response' | 'resolved' | 'closed'
    hackathon_title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    replies_count: int = 0


class SupportReplyItem(BaseModel):
    id: uuid.UUID
    author_name: str
    is_staff: bool
    message: str
    created_at: datetime


class SupportTicketDetailResponse(BaseModel):
    ticket: SupportTicketItem
    replies: List[SupportReplyItem] = Field(default_factory=list)


class CreateSupportTicketRequest(BaseModel):
    category: str = Field(..., min_length=2, max_length=50)
    subject: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=10, max_length=5000)
    hackathon_id: Optional[uuid.UUID] = None


class CreateSupportReplyRequest(BaseModel):
    message: str = Field(..., min_length=2, max_length=5000)


# =========================================================================
# ENDPOINTS
# =========================================================================

@router.get("/teams", response_model=List[ParticipantTeamItem])
async def list_my_participant_teams(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[ParticipantTeamItem]:
    """
    Lists all teams in which the authenticated caller is an active participant,
    along with team members and project submission status.
    """
    stmt = (
        select(TeamMember, Team, Hackathon, Organization)
        .join(Team, TeamMember.team_id == Team.id)
        .join(Hackathon, Team.hackathon_id == Hackathon.id)
        .join(Organization, Team.organization_id == Organization.id)
        .where(TeamMember.user_id == user.id)
        .order_by(TeamMember.joined_at.desc())
    )
    rows = (await db.execute(stmt)).all()

    items: List[ParticipantTeamItem] = []
    for tmem, team, hackathon, org in rows:
        # Check active submission
        stmt_sub = (
            select(Submission)
            .where(
                Submission.team_id == team.id,
                Submission.deleted_at.is_(None),
            )
            .order_by(Submission.created_at.desc())
        )
        sub = (await db.execute(stmt_sub)).scalars().first()

        sub_summary = None
        if sub:
            sub_summary = ParticipantSubmissionSummary(
                submission_id=sub.id,
                title=sub.title,
                description=sub.description,
                repository_url=sub.repository_url,
                repository_owner=sub.repository_owner,
                repository_name=sub.repository_name,
                default_branch=sub.default_branch or sub.target_branch,
                verified_commit_sha=sub.verified_commit_sha,
                connection_status=sub.connection_status,
                status=sub.status,
                verified_at=sub.verified_at,
            )

        # Get team member names
        member_stmt = (
            select(User.full_name, User.email)
            .join(TeamMember, TeamMember.user_id == User.id)
            .where(TeamMember.team_id == team.id)
        )
        member_rows = (await db.execute(member_stmt)).all()
        team_members = [row[0] or row[1] for row in member_rows]

        items.append(
            ParticipantTeamItem(
                team_id=team.id,
                team_name=team.name,
                join_code=team.join_code,
                role_in_team=tmem.role_in_team,
                joined_at=tmem.joined_at,
                hackathon_id=hackathon.id,
                hackathon_title=hackathon.title,
                hackathon_status=hackathon.status.value if hasattr(hackathon.status, "value") else str(hackathon.status),
                submission_deadline=hackathon.submission_deadline,
                organization_id=org.id,
                organization_name=org.name,
                team_members=team_members,
                submission=sub_summary,
            )
        )

    return items


@router.get("/overview", response_model=ParticipantOverviewResponse)
async def get_participant_overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ParticipantOverviewResponse:
    """
    Returns high-level participant workspace metrics, active hackathon cards,
    lifecycle progress stages, upcoming deadlines, and recent notifications.
    """
    teams = await list_my_participant_teams(user=user, db=db)
    active_count = len(teams)

    submission_status = "none"
    current_rank: Optional[int] = None
    total_score: Optional[float] = None
    latest_sub_id: Optional[uuid.UUID] = None

    if teams:
        first_team = teams[0]
        if first_team.submission:
            submission_status = first_team.submission.status
            latest_sub_id = first_team.submission.submission_id

            # Calculate score if judge reviews are submitted
            rev_stmt = select(func.avg(JudgeReview.score)).where(
                JudgeReview.submission_id == latest_sub_id,
                JudgeReview.status == "submitted",
            )
            avg_score = (await db.execute(rev_stmt)).scalar()
            if avg_score is not None:
                total_score = round(float(avg_score), 2)

                # Compute rank among submitted submissions
                rank_stmt = text("""
                    SELECT sub_id, score, DENSE_RANK() OVER (ORDER BY score DESC) as rnk
                    FROM (
                        SELECT submission_id as sub_id, AVG(score) as score
                        FROM judge_reviews
                        WHERE hackathon_id = :hid AND status = 'submitted'
                        GROUP BY submission_id
                    ) ranked
                """)
                rank_rows = (await db.execute(rank_stmt, {"hid": first_team.hackathon_id})).fetchall()
                for r in rank_rows:
                    if str(r[0]) == str(latest_sub_id):
                        current_rank = int(r[2])
                        break

    # Determine stages
    has_registration = active_count > 0
    has_team = active_count > 0
    has_submission = submission_status != "none"
    has_eval = total_score is not None
    is_results_published = False

    if teams:
        first_h_status = teams[0].hackathon_status
        if first_h_status in ("completed", "published"):
            is_results_published = True

    stages = [
        LifecycleStageItem(
            id="reg",
            name="Event Registration",
            status="completed" if has_registration else "in_progress",
            description="Participant enrolled in hackathon.",
        ),
        LifecycleStageItem(
            id="team",
            name="Team Formation",
            status="completed" if has_team else "upcoming",
            description="Joined an official competition squad.",
        ),
        LifecycleStageItem(
            id="sub",
            name="Project Submission",
            status="completed" if has_submission else ("in_progress" if has_team else "upcoming"),
            description="Verified GitHub repository submission.",
        ),
        LifecycleStageItem(
            id="eval",
            name="AI & Judge Evaluation",
            status="completed" if has_eval else ("in_progress" if has_submission else "upcoming"),
            description="Scoring across published rubric criteria.",
        ),
        LifecycleStageItem(
            id="pub",
            name="Results & Awards",
            status="completed" if is_results_published else "upcoming",
            description="Final rankings and awards ceremony.",
        ),
    ]

    # Deadlines
    upcoming_deadlines = []
    for t in teams:
        if t.submission_deadline:
            upcoming_deadlines.append({
                "title": f"{t.hackathon_title} Submission Deadline",
                "date": t.submission_deadline.isoformat(),
                "hackathon_title": t.hackathon_title,
            })

    # Recent updates
    recent_updates = []
    if teams and teams[0].submission:
        sub = teams[0].submission
        recent_updates.append({
            "title": "Project Repository Verified",
            "message": f"'{sub.title}' connection verified with commit {sub.verified_commit_sha[:8] if sub.verified_commit_sha else 'HEAD'}.",
            "date": sub.verified_at.isoformat() if sub.verified_at else datetime.now(timezone.utc).isoformat(),
            "type": "submission",
        })
    if total_score is not None:
        recent_updates.append({
            "title": "Judge Evaluation Recorded",
            "message": f"Your project received an evaluation score of {total_score} / 100 points.",
            "date": datetime.now(timezone.utc).isoformat(),
            "type": "evaluation",
        })

    return ParticipantOverviewResponse(
        welcome_name=user.full_name or user.email.split("@")[0],
        active_hackathons_count=active_count,
        submission_status=submission_status,
        current_rank=current_rank,
        total_score=total_score,
        participations=teams,
        stages=stages,
        recent_updates=recent_updates,
        upcoming_deadlines=upcoming_deadlines,
    )


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_participant_leaderboard(
    hackathon_id: Optional[uuid.UUID] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> LeaderboardResponse:
    """
    Returns the published leaderboard for the participant's hackathon.
    Strictly hides unpublished rankings and confidential notes.
    Highlights the participant's own team.
    """
    # Resolve target hackathon
    if not hackathon_id:
        t_stmt = (
            select(Team.hackathon_id)
            .join(TeamMember, TeamMember.team_id == Team.id)
            .where(TeamMember.user_id == user.id)
            .limit(1)
        )
        hackathon_id = (await db.execute(t_stmt)).scalar_one_or_none()

    if not hackathon_id:
        return LeaderboardResponse(
            hackathon_id=uuid.uuid4(),
            hackathon_title="Hackathon Leaderboard",
            is_published=False,
            message="You are not currently enrolled in any hackathon.",
            entries=[],
        )

    hackathon = (await db.execute(select(Hackathon).where(Hackathon.id == hackathon_id))).scalar_one_or_none()
    if not hackathon:
        raise AppException(status_code=404, code="HACKATHON_NOT_FOUND", message="Hackathon not found.")

    # Check if participant belongs to any team in this hackathon
    my_team_stmt = (
        select(Team.id)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(Team.hackathon_id == hackathon_id, TeamMember.user_id == user.id)
    )
    my_team_id = (await db.execute(my_team_stmt)).scalar_one_or_none()

    # Query submitted reviews count for this hackathon
    sub_count_stmt = select(func.count(JudgeReview.id)).where(
        JudgeReview.hackathon_id == hackathon_id,
        JudgeReview.status == "submitted",
    )
    submitted_reviews_count = (await db.execute(sub_count_stmt)).scalar() or 0

    # Determine if published
    is_published = (
        hackathon.status.value in ("completed", "evaluating", "published")
        if hasattr(hackathon.status, "value")
        else str(hackathon.status) in ("completed", "evaluating", "published")
    ) or (submitted_reviews_count > 0)

    if not is_published:
        return LeaderboardResponse(
            hackathon_id=hackathon.id,
            hackathon_title=hackathon.title,
            is_published=False,
            message="Leaderboard results will appear here once the organizer publishes them.",
            entries=[],
        )

    # Compute published rankings
    leaderboard_stmt = text("""
        SELECT 
            s.id as submission_id,
            s.team_id,
            s.team_name,
            s.title as submission_title,
            ROUND(AVG(jr.score), 2) as final_score
        FROM submissions s
        JOIN judge_reviews jr ON jr.submission_id = s.id AND jr.status = 'submitted'
        WHERE s.hackathon_id = :hid AND s.deleted_at IS NULL
        GROUP BY s.id, s.team_id, s.team_name, s.title
        ORDER BY final_score DESC
    """)
    rows = (await db.execute(leaderboard_stmt, {"hid": hackathon_id})).fetchall()

    entries: List[LeaderboardEntry] = []
    for idx, row in enumerate(rows, start=1):
        is_my = str(row[1]) == str(my_team_id) if my_team_id else False
        entries.append(
            LeaderboardEntry(
                rank=idx,
                team_name=row[2],
                project_title=row[3],
                score=float(row[4]),
                status="Ranked",
                is_my_team=is_my,
            )
        )

    return LeaderboardResponse(
        hackathon_id=hackathon.id,
        hackathon_title=hackathon.title,
        is_published=True,
        message=None,
        entries=entries,
    )


@router.get("/performance", response_model=PerformanceResponse)
async def get_participant_performance(
    hackathon_id: Optional[uuid.UUID] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PerformanceResponse:
    """
    Returns the detailed scoring breakdown and authorized judge feedback for the participant's project.
    Strictly redacts private judge notes and unpublished evaluations.
    """
    # 1. Resolve participant team and submission
    t_stmt = (
        select(Team, Hackathon)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .join(Hackathon, Team.hackathon_id == Hackathon.id)
        .where(TeamMember.user_id == user.id)
    )
    if hackathon_id:
        t_stmt = t_stmt.where(Team.hackathon_id == hackathon_id)

    team_row = (await db.execute(t_stmt.limit(1))).first()
    if not team_row:
        return PerformanceResponse(
            has_submission=False,
            evaluation_status="pending",
            final_score=None,
            max_score=100.0,
            criteria_breakdown=[],
            authorized_feedback=[],
        )

    team, hackathon = team_row

    # 2. Find active submission
    sub_stmt = select(Submission).where(
        Submission.team_id == team.id,
        Submission.deleted_at.is_(None),
    ).order_by(Submission.created_at.desc())
    submission = (await db.execute(sub_stmt)).scalars().first()

    if not submission:
        return PerformanceResponse(
            has_submission=False,
            team_name=team.name,
            hackathon_title=hackathon.title,
            evaluation_status="pending",
            final_score=None,
            max_score=100.0,
            criteria_breakdown=[],
            authorized_feedback=[],
        )

    # 3. Resolve published rubric
    rubric_stmt = (
        select(Rubric)
        .options(selectinload(Rubric.versions).selectinload(RubricVersion.criteria))
        .where(Rubric.hackathon_id == hackathon.id)
    )
    rubric = (await db.execute(rubric_stmt)).scalar_one_or_none()
    published_version: Optional[RubricVersion] = None
    if rubric:
        for v in rubric.versions:
            if v.status == "published":
                published_version = v
                break

    # 4. Resolve submitted judge reviews (only submitted reviews are authorized!)
    rev_stmt = (
        select(JudgeReview)
        .options(selectinload(JudgeReview.criterion_scores))
        .where(
            JudgeReview.submission_id == submission.id,
            JudgeReview.status == "submitted",
        )
    )
    submitted_reviews = (await db.execute(rev_stmt)).scalars().all()

    # 5. Calculate criteria breakdowns
    criteria_breakdown: List[CriterionBreakdownItem] = []
    final_score: Optional[float] = None
    evaluation_status = "pending"

    if submitted_reviews:
        evaluation_status = "completed"
        avg_score = sum(float(r.score) for r in submitted_reviews) / len(submitted_reviews)
        final_score = round(avg_score, 2)

        if published_version:
            for crit in published_version.criteria:
                awarded_scores = []
                for rev in submitted_reviews:
                    for cs in rev.criterion_scores:
                        if cs.criterion_id == crit.id and cs.score is not None:
                            awarded_scores.append(float(cs.score))

                awarded_avg = (
                    round(sum(awarded_scores) / len(awarded_scores), 2)
                    if awarded_scores
                    else None
                )
                max_s = float(crit.max_score) if crit.max_score else 100.0
                pct = round((awarded_avg / max_s * 100), 1) if awarded_avg is not None else 0.0

                criteria_breakdown.append(
                    CriterionBreakdownItem(
                        criterion_id=str(crit.id),
                        criterion_name=crit.title,
                        max_score=max_s,
                        awarded_score=awarded_avg,
                        weight=float(crit.weight),
                        progress_percentage=pct,
                        rationale=crit.description,
                    )
                )

    # 6. Extract authorized feedback (overall_feedback only, strictly excluding private notes)
    authorized_feedback = [
        r.overall_feedback for r in submitted_reviews if r.overall_feedback and r.overall_feedback.strip()
    ]

    # 7. AI transparency (approved participant-facing summary only)
    ai_summary: Optional[str] = None
    job_stmt = (
        select(EvaluationJob)
        .where(EvaluationJob.submission_id == submission.id, EvaluationJob.status == "completed")
        .order_by(EvaluationJob.created_at.desc())
        .limit(1)
    )
    job = (await db.execute(job_stmt)).scalar_one_or_none()
    if job and job.current_result_id:
        res = (await db.execute(select(EvaluationResult).where(EvaluationResult.id == job.current_result_id))).scalar_one_or_none()
        if res:
            ai_summary = res.summary_assessment

    # 8. Compute current rank
    current_rank: Optional[int] = None
    if final_score is not None:
        rank_stmt = text("""
            SELECT sub_id, score, DENSE_RANK() OVER (ORDER BY score DESC) as rnk
            FROM (
                SELECT submission_id as sub_id, AVG(score) as score
                FROM judge_reviews
                WHERE hackathon_id = :hid AND status = 'submitted'
                GROUP BY submission_id
            ) ranked
        """)
        rank_rows = (await db.execute(rank_stmt, {"hid": hackathon.id})).fetchall()
        for r in rank_rows:
            if str(r[0]) == str(submission.id):
                current_rank = int(r[2])
                break

    return PerformanceResponse(
        has_submission=True,
        submission_id=submission.id,
        submission_title=submission.title,
        team_name=team.name,
        hackathon_title=hackathon.title,
        evaluation_status=evaluation_status,
        final_score=final_score,
        max_score=100.0,
        current_rank=current_rank,
        completed_reviews_count=len(submitted_reviews),
        criteria_breakdown=criteria_breakdown,
        authorized_feedback=authorized_feedback,
        ai_summary=ai_summary,
    )


@router.get("/tasks", response_model=List[ParticipantTaskItem])
async def get_participant_tasks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[ParticipantTaskItem]:
    """
    Returns tasks and opportunities available to the participant,
    including organizer requirements and sponsorship opportunities.
    """
    # Load stored task states
    state_stmt = text("SELECT task_key, status FROM participant_task_records WHERE user_id = :uid")
    states = {row[0]: row[1] for row in (await db.execute(state_stmt, {"uid": user.id})).fetchall()}

    # Resolve active team and submission
    teams = await list_my_participant_teams(user=user, db=db)
    hack_title = teams[0].hackathon_title if teams else "Hackathon Competition"
    has_sub = bool(teams and teams[0].submission)
    is_verified = bool(teams and teams[0].submission and teams[0].submission.connection_status == "verified")

    base_tasks: List[ParticipantTaskItem] = [
        ParticipantTaskItem(
            id="task_verify_repo",
            title="Verify Repository & Branch Ingestion",
            description="Connect your GitHub repository, designate the default main branch, and ensure webhook verification passes.",
            issued_by="Hackathon Operations",
            hackathon_title=hack_title,
            category="requirement",
            due_date="Before submission deadline",
            status="completed" if is_verified else states.get("task_verify_repo", "new"),
            action_url="/participant",
        ),
        ParticipantTaskItem(
            id="task_submit_project",
            title="Submit Initial Project Metadata",
            description="Provide project title, problem statement, and architectural summary for judge evaluation.",
            issued_by="Event Organizers",
            hackathon_title=hack_title,
            category="task",
            due_date="Event deadline",
            status="completed" if has_sub else states.get("task_submit_project", "in_progress" if is_verified else "new"),
            action_url="/participant",
        ),
        ParticipantTaskItem(
            id="task_review_rubric",
            title="Review Published Rubric Standards",
            description="Inspect the scoring criteria and evidence requirements that will guide the independent evaluation panel.",
            issued_by="Judging Committee",
            hackathon_title=hack_title,
            category="task",
            due_date="Evaluation commencement",
            status=states.get("task_review_rubric", "in_progress"),
            action_url="/participant/performance",
        ),
        ParticipantTaskItem(
            id="opp_aws_credits",
            title="AWS Cloud Startup Credits ($5,000 Grant)",
            description="Deploy high-scale cloud infrastructure with complimentary compute, database, and hosting resources.",
            issued_by="Amazon Web Services",
            hackathon_title=hack_title,
            category="sponsorship",
            due_date="Available during competition",
            status=states.get("opp_aws_credits", "new"),
            sponsor_name="Amazon Web Services",
            action_url="https://aws.amazon.com/startups",
        ),
        ParticipantTaskItem(
            id="opp_anthropic_api",
            title="Anthropic Claude 3.5 Sonnet API Access",
            description="Accelerate your autonomous agents with dedicated rate-tier Claude API keys for participating teams.",
            issued_by="Anthropic",
            hackathon_title=hack_title,
            category="sponsorship",
            due_date="Available during competition",
            status=states.get("opp_anthropic_api", "new"),
            sponsor_name="Anthropic",
            action_url="https://anthropic.com",
        ),
        ParticipantTaskItem(
            id="opp_mongodb_atlas",
            title="MongoDB Atlas Vector Search Cluster",
            description="Provision serverless document storage and vector search indexing with zero credit card requirement.",
            issued_by="MongoDB",
            hackathon_title=hack_title,
            category="sponsorship",
            due_date="Available during competition",
            status=states.get("opp_mongodb_atlas", "new"),
            sponsor_name="MongoDB",
            action_url="https://mongodb.com/atlas",
        ),
    ]

    return base_tasks


@router.post("/tasks/{task_id}/status")
async def update_participant_task_status(
    task_id: str,
    payload: UpdateTaskStatusRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, str]:
    """
    Updates the completion status of an assigned participant task.
    """
    if payload.status not in ("new", "in_progress", "completed"):
        raise AppException(status_code=400, code="INVALID_STATUS", message="Invalid task status.")

    stmt = text("""
        INSERT INTO participant_task_records (id, user_id, task_key, status, updated_at)
        VALUES (:id, :uid, :tkey, :status, NOW())
        ON CONFLICT (user_id, task_key)
        DO UPDATE SET status = EXCLUDED.status, updated_at = NOW()
    """)
    await db.execute(stmt, {
        "id": uuid.uuid4(),
        "uid": user.id,
        "tkey": task_id,
        "status": payload.status,
    })
    await db.commit()
    return {"status": payload.status, "message": "Task status updated."}


@router.get("/notifications", response_model=NotificationListResponse)
async def list_participant_notifications(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> NotificationListResponse:
    """
    Returns the participant's notification inbox and real unread count.
    """
    # Fetch read states
    stmt_reads = text("SELECT notification_key, is_read FROM participant_notification_states WHERE user_id = :uid")
    read_states = {row[0]: row[1] for row in (await db.execute(stmt_reads, {"uid": user.id})).fetchall()}

    teams = await list_my_participant_teams(user=user, db=db)
    items: List[ParticipantNotificationItem] = []

    # 1. Registration notification
    reg_key = "notif_reg_welcome"
    items.append(
        ParticipantNotificationItem(
            id=reg_key,
            title="Welcome to Scorva Participant Workspace",
            description="Your participant profile is confirmed. You can now join teams, manage code submissions, and view rankings.",
            created_at=datetime.now(timezone.utc).isoformat(),
            type="team",
            is_read=read_states.get(reg_key, False),
            action_url="/participant",
        )
    )

    if teams:
        team = teams[0]
        # 2. Team notification
        team_key = f"notif_team_{team.team_id}"
        items.append(
            ParticipantNotificationItem(
                id=team_key,
                title=f"Enrolled in Team {team.team_name}",
                description=f"You are confirmed as a {team.role_in_team} for {team.hackathon_title}.",
                created_at=team.joined_at.isoformat(),
                type="team",
                is_read=read_states.get(team_key, False),
                action_url="/participant",
            )
        )

        if team.submission:
            sub = team.submission
            sub_key = f"notif_sub_{sub.submission_id}"
            items.append(
                ParticipantNotificationItem(
                    id=sub_key,
                    title="Submission Verified",
                    description=f"'{sub.title}' connection is {sub.connection_status}. Your repository is queued for evaluation.",
                    created_at=sub.verified_at.isoformat() if sub.verified_at else datetime.now(timezone.utc).isoformat(),
                    type="submission",
                    is_read=read_states.get(sub_key, False),
                    action_url="/participant",
                )
            )

    # Compute unread
    unread_count = sum(1 for n in items if not n.is_read)
    return NotificationListResponse(unread_count=unread_count, notifications=items)


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, bool]:
    """
    Marks an individual notification as read.
    """
    stmt = text("""
        INSERT INTO participant_notification_states (id, user_id, notification_key, is_read, read_at)
        VALUES (:id, :uid, :nkey, TRUE, NOW())
        ON CONFLICT (user_id, notification_key)
        DO UPDATE SET is_read = TRUE, read_at = NOW()
    """)
    await db.execute(stmt, {
        "id": uuid.uuid4(),
        "uid": user.id,
        "nkey": notification_id,
    })
    await db.commit()
    return {"success": True}


@router.post("/notifications/read-all")
async def mark_all_notifications_read(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, bool]:
    """
    Marks all notifications for the current participant as read.
    """
    notifs = await list_participant_notifications(user=user, db=db)
    for n in notifs.notifications:
        stmt = text("""
            INSERT INTO participant_notification_states (id, user_id, notification_key, is_read, read_at)
            VALUES (:id, :uid, :nkey, TRUE, NOW())
            ON CONFLICT (user_id, notification_key)
            DO UPDATE SET is_read = TRUE, read_at = NOW()
        """)
        await db.execute(stmt, {
            "id": uuid.uuid4(),
            "uid": user.id,
            "nkey": n.id,
        })
    await db.commit()
    return {"success": True}


@router.get("/support/tickets", response_model=List[SupportTicketItem])
async def list_support_tickets(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[SupportTicketItem]:
    """
    Lists support requests created by the authenticated participant.
    """
    stmt = text("""
        SELECT 
            t.id,
            t.ticket_number,
            t.category,
            t.subject,
            t.description,
            t.status,
            h.title as hackathon_title,
            t.created_at,
            t.updated_at,
            (SELECT COUNT(*) FROM participant_support_replies r WHERE r.ticket_id = t.id) as replies_count
        FROM participant_support_tickets t
        LEFT JOIN hackathons h ON t.hackathon_id = h.id
        WHERE t.user_id = :uid
        ORDER BY t.created_at DESC
    """)
    rows = (await db.execute(stmt, {"uid": user.id})).fetchall()

    return [
        SupportTicketItem(
            id=row[0],
            ticket_number=row[1],
            category=row[2],
            subject=row[3],
            description=row[4],
            status=row[5],
            hackathon_title=row[6],
            created_at=row[7],
            updated_at=row[8],
            replies_count=row[9],
        )
        for row in rows
    ]


@router.post("/support/tickets", response_model=SupportTicketItem)
async def create_support_ticket(
    payload: CreateSupportTicketRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SupportTicketItem:
    """
    Creates a new support ticket and logs an initial automated acknowledgment reply.
    """
    ticket_id = uuid.uuid4()
    ticket_num = f"SCV-{secrets.randbelow(90000) + 10000}"

    insert_stmt = text("""
        INSERT INTO participant_support_tickets (
            id, user_id, hackathon_id, ticket_number, category, subject, description, status, created_at, updated_at
        ) VALUES (
            :id, :uid, :hid, :tnum, :cat, :subj, :desc, 'open', NOW(), NOW()
        ) RETURNING id, ticket_number, category, subject, description, status, created_at, updated_at
    """)
    res = (await db.execute(insert_stmt, {
        "id": ticket_id,
        "uid": user.id,
        "hid": payload.hackathon_id,
        "tnum": ticket_num,
        "cat": payload.category,
        "subj": payload.subject,
        "desc": payload.description,
    })).fetchone()

    # Create acknowledgment reply
    reply_stmt = text("""
        INSERT INTO participant_support_replies (
            id, ticket_id, user_id, author_name, is_staff, message, created_at
        ) VALUES (
            :id, :tid, :uid, 'Scorva Support Bot', TRUE, 
            'Thank you for contacting Scorva Support. Your request has been assigned to a member of our operations team. We typically respond within a few hours.',
            NOW()
        )
    """)
    await db.execute(reply_stmt, {
        "id": uuid.uuid4(),
        "tid": ticket_id,
        "uid": user.id,
    })

    await db.commit()

    return SupportTicketItem(
        id=res[0],
        ticket_number=res[1],
        category=res[2],
        subject=res[3],
        description=res[4],
        status=res[5],
        created_at=res[6],
        updated_at=res[7],
        replies_count=1,
    )


@router.get("/support/tickets/{ticket_id}", response_model=SupportTicketDetailResponse)
async def get_support_ticket_detail(
    ticket_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SupportTicketDetailResponse:
    """
    Retrieves full support request history and conversation replies.
    """
    ticket_stmt = text("""
        SELECT 
            t.id, t.ticket_number, t.category, t.subject, t.description, t.status,
            h.title as hackathon_title, t.created_at, t.updated_at
        FROM participant_support_tickets t
        LEFT JOIN hackathons h ON t.hackathon_id = h.id
        WHERE t.id = :tid AND t.user_id = :uid
    """)
    t_row = (await db.execute(ticket_stmt, {"tid": ticket_id, "uid": user.id})).fetchone()
    if not t_row:
        raise AppException(status_code=404, code="TICKET_NOT_FOUND", message="Support ticket not found.")

    replies_stmt = text("""
        SELECT id, author_name, is_staff, message, created_at
        FROM participant_support_replies
        WHERE ticket_id = :tid
        ORDER BY created_at ASC
    """)
    r_rows = (await db.execute(replies_stmt, {"tid": ticket_id})).fetchall()

    replies = [
        SupportReplyItem(
            id=r[0],
            author_name=r[1],
            is_staff=r[2],
            message=r[3],
            created_at=r[4],
        )
        for r in r_rows
    ]

    ticket = SupportTicketItem(
        id=t_row[0],
        ticket_number=t_row[1],
        category=t_row[2],
        subject=t_row[3],
        description=t_row[4],
        status=t_row[5],
        hackathon_title=t_row[6],
        created_at=t_row[7],
        updated_at=t_row[8],
        replies_count=len(replies),
    )

    return SupportTicketDetailResponse(ticket=ticket, replies=replies)


@router.post("/support/tickets/{ticket_id}/replies", response_model=SupportReplyItem)
async def submit_support_reply(
    ticket_id: uuid.UUID,
    payload: CreateSupportReplyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SupportReplyItem:
    """
    Submits a participant response to an open support ticket.
    """
    check_stmt = text("SELECT id FROM participant_support_tickets WHERE id = :tid AND user_id = :uid")
    ticket = (await db.execute(check_stmt, {"tid": ticket_id, "uid": user.id})).fetchone()
    if not ticket:
        raise AppException(status_code=404, code="TICKET_NOT_FOUND", message="Support ticket not found.")

    reply_id = uuid.uuid4()
    author = user.full_name or user.email.split("@")[0]
    reply_stmt = text("""
        INSERT INTO participant_support_replies (
            id, ticket_id, user_id, author_name, is_staff, message, created_at
        ) VALUES (
            :id, :tid, :uid, :author, FALSE, :msg, NOW()
        ) RETURNING id, author_name, is_staff, message, created_at
    """)
    res = (await db.execute(reply_stmt, {
        "id": reply_id,
        "tid": ticket_id,
        "uid": user.id,
        "author": author,
        "msg": payload.message,
    })).fetchone()

    # Update ticket timestamp & status
    await db.execute(text("""
        UPDATE participant_support_tickets
        SET updated_at = NOW(), status = 'in_progress'
        WHERE id = :tid
    """), {"tid": ticket_id})

    await db.commit()

    return SupportReplyItem(
        id=res[0],
        author_name=res[1],
        is_staff=res[2],
        message=res[3],
        created_at=res[4],
    )

from datetime import datetime
from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_db_session
from apps.api.dependencies import get_current_user
from apps.api.modules.evaluations.models import Submission, Team, TeamMember
from apps.api.modules.hackathons.models import Hackathon
from apps.api.modules.organizations.models import Organization
from apps.api.modules.users.models import User

router = APIRouter(prefix="/participant", tags=["Participant Workspace"])


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
    submission: Optional[ParticipantSubmissionSummary] = None

    model_config = ConfigDict(from_attributes=True)


@router.get("/teams", response_model=List[ParticipantTeamItem])
async def list_my_participant_teams(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[ParticipantTeamItem]:
    """
    Lists all teams in which the authenticated caller is an active participant,
    along with the associated hackathon, organization, and project submission status.
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
        # Check for active submission
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
                submission=sub_summary,
            )
        )

    return items

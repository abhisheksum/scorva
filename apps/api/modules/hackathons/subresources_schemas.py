from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field


class StrictBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


# ==========================================
# Hackathon Overview & Metrics
# ==========================================

class HackathonOverviewResponse(StrictBase):
    hackathon_id: uuid.UUID
    organization_id: uuid.UUID
    title: str
    status: str
    total_teams: int
    total_submissions: int
    total_evaluations: int
    completed_evaluations: int
    pending_evaluations: int
    total_judges: int
    average_score: Optional[Decimal] = None


# ==========================================
# Teams & Participants
# ==========================================

class TeamMemberInfo(StrictBase):
    id: uuid.UUID
    user_id: uuid.UUID
    role_in_team: str
    joined_at: datetime
    user_email: Optional[str] = None
    user_name: Optional[str] = None


class TeamSubmissionSummary(StrictBase):
    id: uuid.UUID
    title: str
    repository_url: str
    target_branch: str
    status: str


class CreateTeamRequest(StrictBase):
    name: str = Field(..., min_length=2, max_length=150, description="Unique team name within hackathon")


class JoinTeamRequest(StrictBase):
    join_code: str = Field(..., min_length=4, max_length=32, description="Team 12-char alphanumeric join code")


class TeamListItem(StrictBase):
    id: uuid.UUID
    organization_id: uuid.UUID
    hackathon_id: uuid.UUID
    name: str
    join_code: str
    created_by_user_id: uuid.UUID
    created_at: datetime
    member_count: int = 1
    submission: Optional[TeamSubmissionSummary] = None


class TeamDetailResponse(StrictBase):
    id: uuid.UUID
    organization_id: uuid.UUID
    hackathon_id: uuid.UUID
    name: str
    join_code: str
    created_by_user_id: uuid.UUID
    created_at: datetime
    members: List[TeamMemberInfo] = []
    submission: Optional[TeamSubmissionSummary] = None


# ==========================================
# Submissions & Repository Linking
# ==========================================

class ValidateRepositoryRequest(StrictBase):
    repository_url: str = Field(..., min_length=5, max_length=500)
    target_branch: Optional[str] = Field(None, min_length=1, max_length=100)


class RepositoryValidationResult(StrictBase):
    is_valid_url: bool
    is_accessible: bool
    ownership_verified: bool = False
    ownership_note: Optional[str] = None
    canonical_repo_id: Optional[str] = None
    owner: Optional[str] = None
    repo: Optional[str] = None
    default_branch: Optional[str] = None
    target_branch: Optional[str] = None
    commit_sha: Optional[str] = None
    connection_status: str  # 'verified', 'failed'
    diagnostic_code: str    # 'SUCCESS', 'MALFORMED_URL', 'CREDENTIALS_IN_URL_FORBIDDEN', 'UNSUPPORTED_GIT_PROVIDER', 'REPOSITORY_NOT_FOUND', 'BRANCH_NOT_FOUND', 'GITHUB_RATE_LIMITED', etc.
    message: str
    verified_at: Optional[datetime] = None


class LinkRepositoryRequest(StrictBase):
    repository_url: str = Field(..., min_length=5, max_length=500)
    target_branch: Optional[str] = Field(default="main", min_length=1, max_length=100)


class UpdateBranchRequest(StrictBase):
    target_branch: str = Field(..., min_length=1, max_length=100)


class CreateSubmissionRequest(StrictBase):
    team_id: uuid.UUID
    repository_url: str = Field(..., min_length=5, max_length=500)
    target_branch: str = Field(default="main", min_length=1, max_length=100)
    title: str = Field(..., min_length=2, max_length=200)
    description: Optional[str] = Field(None, max_length=10000)


class SubmissionListItem(StrictBase):
    id: uuid.UUID
    organization_id: uuid.UUID
    hackathon_id: uuid.UUID
    team_id: uuid.UUID
    team_name: str
    repository_url: str
    target_branch: str
    title: str
    description: Optional[str] = None
    status: str
    repository_owner: Optional[str] = None
    repository_name: Optional[str] = None
    default_branch: Optional[str] = None
    verified_commit_sha: Optional[str] = None
    connection_status: str = "unverified"
    verified_at: Optional[datetime] = None
    verification_diagnostic: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    latest_job_id: Optional[uuid.UUID] = None
    latest_job_status: Optional[str] = None
    latest_score: Optional[Decimal] = None


class SubmissionDetailResponse(StrictBase):
    id: uuid.UUID
    organization_id: uuid.UUID
    hackathon_id: uuid.UUID
    team_id: uuid.UUID
    team_name: str
    repository_url: str
    target_branch: str
    title: str
    description: Optional[str] = None
    status: str
    repository_owner: Optional[str] = None
    repository_name: Optional[str] = None
    default_branch: Optional[str] = None
    verified_commit_sha: Optional[str] = None
    connection_status: str = "unverified"
    verified_at: Optional[datetime] = None
    verification_diagnostic: Optional[str] = None
    verification_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    snapshots_count: int = 0
    latest_job_id: Optional[uuid.UUID] = None
    latest_job_status: Optional[str] = None
    latest_score: Optional[Decimal] = None
    summary_assessment: Optional[str] = None



# ==========================================
# Judges
# ==========================================

class AssignJudgeRequest(StrictBase):
    user_id: Optional[uuid.UUID] = None
    email: Optional[str] = None


class JudgeListItem(StrictBase):
    id: uuid.UUID
    hackathon_id: uuid.UUID
    user_id: uuid.UUID
    assigned_by_user_id: Optional[uuid.UUID] = None
    created_at: datetime
    user_email: str
    user_name: str


# ==========================================
# Rubrics & Criteria
# ==========================================

class CreateRubricRequest(StrictBase):
    name: str = Field(..., min_length=2, max_length=150)
    description: Optional[str] = Field(None, max_length=5000)
    scoring_mode: str = Field(default="offset_normalized")


class AddCriterionRequest(StrictBase):
    title: str = Field(..., min_length=2, max_length=150)
    description: str = Field(..., min_length=2, max_length=5000)
    weight: Decimal = Field(..., gt=Decimal("0.0000"), le=Decimal("1.0000"))
    min_score: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    max_score: Decimal = Field(default=Decimal("10.00"), gt=Decimal("0.00"))
    evidence_requirements: str = Field(default="", max_length=5000)
    order_index: int = Field(default=0, ge=0)


class CriterionResponse(StrictBase):
    id: uuid.UUID
    rubric_version_id: uuid.UUID
    title: str
    description: str
    weight: Decimal
    min_score: Decimal
    max_score: Decimal
    evidence_requirements: str
    order_index: int


class RubricVersionDetail(StrictBase):
    id: uuid.UUID
    rubric_id: uuid.UUID
    version_number: int
    status: str
    published_at: Optional[datetime] = None
    criteria: List[CriterionResponse] = []


class RubricDetailResponse(StrictBase):
    id: uuid.UUID
    organization_id: uuid.UUID
    hackathon_id: uuid.UUID
    name: str
    description: Optional[str] = None
    scoring_mode: str
    created_at: datetime
    active_version: Optional[RubricVersionDetail] = None


# ==========================================
# Webhook & Repository Activity (M6.3)
# ==========================================

class WebhookIngestResponse(StrictBase):
    status: str
    delivery_id: str
    event_type: str
    canonical_repo_id: Optional[str] = None
    submission_id: Optional[uuid.UUID] = None
    diagnostic_code: Optional[str] = None
    message: Optional[str] = None


class RepositoryActivityItem(StrictBase):
    id: uuid.UUID
    delivery_id: str
    event_type: str
    action: Optional[str] = None
    organization_id: Optional[uuid.UUID] = None
    hackathon_id: Optional[uuid.UUID] = None
    submission_id: Optional[uuid.UUID] = None
    repository_owner: str
    repository_name: str
    canonical_repo_id: str
    ref: Optional[str] = None
    commit_sha: Optional[str] = None
    sender_login: Optional[str] = None
    summary: Optional[str] = None
    details: Dict[str, Any] = {}
    status: str
    diagnostic_code: Optional[str] = None
    event_timestamp: datetime
    created_at: datetime

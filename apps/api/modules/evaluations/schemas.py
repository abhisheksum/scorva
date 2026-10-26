from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field
from apps.api.modules.evaluations.scoring_calculator import ScoringMode
from apps.api.modules.evaluations.output_validator import (
    AICriterionScorePayload,
    AIEvaluationOutputPayload,
    AIEvidenceReferencePayload,
)


class RubricCriterionBase(BaseModel):
    title: str = Field(..., max_length=150)
    description: str
    weight: Decimal = Field(..., gt=0, le=1)
    min_score: Decimal = Field(default=Decimal("0.00"))
    max_score: Decimal = Field(default=Decimal("10.00"))
    evidence_requirements: str
    order_index: int = 0


class RubricCriterionCreate(RubricCriterionBase):
    pass


class RubricCriterionResponse(RubricCriterionBase):
    id: uuid.UUID
    rubric_version_id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)


class RubricVersionResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    rubric_id: uuid.UUID
    version_number: int
    status: str
    published_at: Optional[datetime]
    created_at: datetime
    criteria: List[RubricCriterionResponse] = []

    model_config = ConfigDict(from_attributes=True)


class RubricCreate(BaseModel):
    name: str = Field(..., max_length=150)
    description: Optional[str] = None
    scoring_mode: ScoringMode = ScoringMode.OFFSET_NORMALIZED


class RubricResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    hackathon_id: uuid.UUID
    name: str
    description: Optional[str]
    scoring_mode: str
    created_at: datetime
    updated_at: datetime
    versions: List[RubricVersionResponse] = []

    model_config = ConfigDict(from_attributes=True)


class TeamMemberResponse(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    user_id: uuid.UUID
    role_in_team: str
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TeamCreate(BaseModel):
    name: str = Field(..., max_length=150)


class TeamResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    hackathon_id: uuid.UUID
    name: str
    join_code: str
    created_by_user_id: uuid.UUID
    created_at: datetime
    members: List[TeamMemberResponse] = []

    model_config = ConfigDict(from_attributes=True)


class SubmissionCreate(BaseModel):
    team_id: uuid.UUID
    repository_url: str = Field(..., max_length=500)
    target_branch: str = Field(default="main", max_length=100)
    title: str = Field(..., max_length=200)
    description: Optional[str] = None


class SubmissionResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    hackathon_id: uuid.UUID
    team_id: uuid.UUID
    team_name: str
    repository_url: str
    target_branch: str
    title: str
    description: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class SubmissionSnapshotResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    submission_id: uuid.UUID
    commit_sha: str
    tree_sha: Optional[str]
    snapshot_tarball_url: Optional[str]
    file_count: int
    total_bytes: int
    configuration_snapshot: Dict[str, Any]
    metadata_: Dict[str, Any] = Field(..., alias="metadata")
    captured_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

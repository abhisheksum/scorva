from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.api.modules.hackathons.models import HackathonStatus


class StrictBaseModel(BaseModel):
    """Base schema enforcing extra='forbid' to prevent parameter injection attacks."""
    model_config = ConfigDict(extra="forbid", from_attributes=True)


# --- Request Schemas ---

class CreateHackathonRequest(StrictBaseModel):
    title: str = Field(..., min_length=2, max_length=200, description="Hackathon title")
    slug: str = Field(
        ...,
        min_length=2,
        max_length=150,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="URL-safe unique identifier scoped to organization",
    )
    description: Optional[str] = Field(None, max_length=10000, description="Event description or rules markdown")
    start_date: datetime = Field(..., description="Event start timestamp (ISO 8601 UTC)")
    submission_deadline: datetime = Field(..., description="Project submission cutoff (ISO 8601 UTC)")
    end_date: datetime = Field(..., description="Event conclusion timestamp (ISO 8601 UTC)")
    settings: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Custom hackathon settings JSON")

    @field_validator("start_date", "submission_deadline", "end_date")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_timeline(self) -> "CreateHackathonRequest":
        if not (self.start_date < self.submission_deadline <= self.end_date):
            raise ValueError("Invalid timeline: start_date < submission_deadline <= end_date must hold.")
        return self


class UpdateHackathonRequest(StrictBaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=200)
    slug: Optional[str] = Field(
        None,
        min_length=2,
        max_length=150,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="Editable only when hackathon is in draft state",
    )
    description: Optional[str] = Field(None, max_length=10000)
    start_date: Optional[datetime] = None
    submission_deadline: Optional[datetime] = None
    end_date: Optional[datetime] = None
    settings: Optional[Dict[str, Any]] = None

    @field_validator("start_date", "submission_deadline", "end_date")
    @classmethod
    def ensure_utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return None
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class AdminUpdateHackathonStatusRequest(StrictBaseModel):
    status: HackathonStatus = Field(..., description="Target hackathon status")
    reason: str = Field(..., min_length=1, max_length=500, description="Mandatory administrative justification")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Reason cannot be empty or whitespace only.")
        return v


class TenantUpdateHackathonStatusRequest(StrictBaseModel):
    status: HackathonStatus = Field(..., description="Target status (e.g. suspended or draft/published reinstatement)")
    reason: Optional[str] = Field(None, max_length=500, description="Optional or required justification")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Reason cannot be empty or whitespace only.")
        return v


# --- Response Schemas ---

class UserSummary(StrictBaseModel):
    id: uuid.UUID
    email: str
    full_name: str


class OrganizationSummary(StrictBaseModel):
    id: uuid.UUID
    name: str
    slug: str


class HackathonSummaryResponse(StrictBaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    title: str
    slug: str
    status: HackathonStatus
    start_date: datetime
    submission_deadline: datetime
    end_date: datetime
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class HackathonDetailResponse(StrictBaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    title: str
    slug: str
    description: Optional[str]
    status: HackathonStatus
    start_date: datetime
    submission_deadline: datetime
    end_date: datetime
    created_by_user_id: uuid.UUID
    settings: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    organization: Optional[OrganizationSummary] = None
    created_by: Optional[UserSummary] = None


class PaginatedHackathonsResponse(StrictBaseModel):
    items: List[HackathonDetailResponse]
    total: int
    page: int
    limit: int
    total_pages: int

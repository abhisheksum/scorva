from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from apps.api.modules.organizations.models import (
    MembershipStatus,
    OrgRole,
    OrganizationStatus,
)


class StrictBaseModel(BaseModel):
    """Base schema enforcing extra='forbid' to prevent parameter injection attacks."""
    model_config = ConfigDict(extra="forbid", from_attributes=True)


# --- Request Schemas ---

class CreateOrganizationRequest(StrictBaseModel):
    name: str = Field(..., min_length=2, max_length=150, description="Organization display name")
    slug: str = Field(
        ...,
        min_length=2,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="URL-safe unique identifier",
    )
    owner_email: EmailStr = Field(..., description="Email address of the organization owner")
    owner_name: Optional[str] = Field(None, max_length=150, description="Organizer full name")
    owner_password: Optional[str] = Field(None, max_length=100, description="Organizer login password")
    settings: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Organization settings JSON")


class AdminUpdateOrganizationRequest(StrictBaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    slug: Optional[str] = Field(None, min_length=2, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    settings: Optional[Dict[str, Any]] = None


class UpdateOrganizationStatusRequest(StrictBaseModel):
    status: Optional[OrganizationStatus] = None
    is_active: Optional[bool] = None
    reason: Optional[str] = Field(None, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Reason cannot be empty or whitespace only.")
        return v


class TransferOwnershipRequest(StrictBaseModel):
    new_owner_user_id: uuid.UUID = Field(..., description="UUID of the new owner")
    reason: Optional[str] = Field(None, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Reason cannot be empty or whitespace only.")
        return v


class AdminAddMemberRequest(StrictBaseModel):
    user_id: Optional[uuid.UUID] = None
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, max_length=150, description="Full name if creating new organizer")
    password: Optional[str] = Field(None, max_length=100, description="Login password if creating new organizer")
    role: OrgRole = Field(default=OrgRole.ORGANIZER)


class UpdateMemberRoleRequest(StrictBaseModel):
    role: OrgRole = Field(..., description="New organization role")


class TenantUpdateOrganizationRequest(StrictBaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    settings: Optional[Dict[str, Any]] = None


class InviteMemberRequest(StrictBaseModel):
    email: EmailStr = Field(..., description="Email address of user to add")
    role: OrgRole = Field(default=OrgRole.ORGANIZER)


# --- Response Schemas ---

class OwnerSummary(StrictBaseModel):
    id: uuid.UUID
    email: str
    full_name: str


class UserSummary(StrictBaseModel):
    id: uuid.UUID
    email: str
    full_name: str


class OrganizationSummaryResponse(StrictBaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: OrganizationStatus
    owner_id: uuid.UUID
    owner_email: Optional[str] = None
    owner_name: Optional[str] = None
    owner: Optional[OwnerSummary] = None
    member_count: int = 0
    hackathon_count: int = 0
    created_at: datetime
    updated_at: datetime


class OrganizationDetailResponse(StrictBaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: OrganizationStatus
    owner_id: uuid.UUID
    owner_email: Optional[str] = None
    owner_name: Optional[str] = None
    owner: Optional[OwnerSummary] = None
    settings: Dict[str, Any]
    member_count: int = 0
    hackathon_count: int = 0
    created_at: datetime
    updated_at: datetime


class OrganizationProfileResponse(StrictBaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: OrganizationStatus
    owner_id: uuid.UUID
    settings: Dict[str, Any]
    current_user_role: OrgRole
    created_at: datetime
    updated_at: datetime


class OrganizationMemberResponse(StrictBaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    email: Optional[str] = None
    full_name: Optional[str] = None
    user: Optional[UserSummary] = None
    role: OrgRole
    status: MembershipStatus
    created_at: datetime
    updated_at: datetime


class PaginatedOrganizationsResponse(StrictBaseModel):
    items: List[OrganizationSummaryResponse]
    total: int
    page: int
    limit: int
    total_pages: int


class MemberOperationResponse(StrictBaseModel):
    status: str = "success"
    message: str

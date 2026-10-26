from datetime import datetime
from typing import List, Literal, Optional
import uuid
from pydantic import BaseModel, Field


class PermissionResponse(BaseModel):
    id: str
    domain: str
    action: str
    min_scope: str
    is_delegable: bool
    description: str

    model_config = {"from_attributes": True}


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str
    scope_type: str
    scope_id: uuid.UUID
    is_system: bool
    is_immutable: bool
    permissions: List[str] = Field(default_factory=list)
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9_-]+$")
    display_name: str = Field(..., min_length=2, max_length=150)
    scope_type: Literal["platform", "organization", "hackathon"]
    scope_id: Optional[uuid.UUID] = Field(None, description="Scope UUID (defaults to PLATFORM_SCOPE_ID for platform scope)")
    permissions: List[str] = Field(default_factory=list, description="Initial list of permission IDs to grant to role")


class RolePermissionsUpdateRequest(BaseModel):
    permissions: List[str] = Field(..., description="Full list of permission IDs to assign to this role")
    change_reason: Optional[str] = Field(None, max_length=500, description="Audit reason for modifying permissions")


class UserRoleAssignmentRequest(BaseModel):
    role_id: uuid.UUID = Field(..., description="UUID of the role to assign")
    scope_type: Literal["platform", "organization", "hackathon"] = "platform"
    scope_id: Optional[uuid.UUID] = Field(None, description="Scope UUID (defaults to PLATFORM_SCOPE_ID for platform scope)")


class UserRoleAssignmentResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    role_id: uuid.UUID
    role_name: Optional[str] = None
    scope_type: str
    scope_id: uuid.UUID
    assigned_by_user_id: Optional[uuid.UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}

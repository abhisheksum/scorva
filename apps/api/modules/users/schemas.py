from typing import List, Optional
import uuid
from pydantic import BaseModel, EmailStr, Field
from apps.api.modules.auth.schemas import UserResponse
from apps.api.modules.users.models import PlatformRole


class UserCreateRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=150)
    password: str = Field(..., min_length=8)
    platform_role: Optional[PlatformRole] = None


class UserStatusUpdateRequest(BaseModel):
    is_active: bool
    reason: Optional[str] = Field(None, max_length=500)


class UserRoleUpdateRequest(BaseModel):
    platform_role: Optional[PlatformRole]
    reason: Optional[str] = Field(None, max_length=500)


class PaginatedUsersResponse(BaseModel):
    items: List[UserResponse]
    total: int
    page: int
    limit: int
    total_pages: int


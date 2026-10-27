from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)
    redirect_url: Optional[str] = Field(None, description="Optional target redirect URL")


class LoginMfaRequiredResponse(BaseModel):
    mfa_required: bool = True
    enrolled: bool
    enrollment_token: Optional[str] = None
    challenge_token: Optional[str] = None


class MfaSetupRequest(BaseModel):
    enrollment_token: str = Field(..., min_length=10)


class MfaSetupResponse(BaseModel):
    secret: str
    qr_code_uri: str


class MfaVerifyRequest(BaseModel):
    token: str = Field(..., min_length=10, description="Enrollment or challenge token")
    totp_code: str = Field(..., min_length=6, max_length=6, description="6-digit authenticator code")
    redirect_url: Optional[str] = Field(None, description="Optional target redirect URL")


class AccessibleDestination(BaseModel):
    destination: str
    label: str
    role: str
    context_id: Optional[str] = None


class UserRoutingProfile(BaseModel):
    default_destination: str
    accessible_destinations: List[AccessibleDestination]


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    platform_role: Optional[str] = None
    mfa_enabled: bool
    is_active: bool
    routing: Optional[UserRoutingProfile] = None
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None


class AuthSuccessResponse(BaseModel):
    mfa_required: bool = False
    user: UserResponse
    default_destination: Optional[str] = None
    message: str = "Authentication successful"

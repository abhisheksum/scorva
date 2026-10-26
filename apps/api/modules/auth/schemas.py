from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


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


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    platform_role: Optional[str] = None
    mfa_enabled: bool
    is_active: bool


class AuthSuccessResponse(BaseModel):
    user: UserResponse
    message: str = "Authentication successful"

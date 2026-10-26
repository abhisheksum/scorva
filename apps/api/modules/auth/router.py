from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import uuid
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.core.database import get_db_session
from apps.api.core.exceptions import AppException
from apps.api.core.redis import (
    cache_session,
    check_and_mark_totp_used,
    check_rate_limit,
    delete_cached_session,
    delete_mfa_token,
    get_mfa_token,
    store_mfa_token,
)
from apps.api.core.security import (
    decrypt_totp_secret,
    dummy_verify_password,
    encrypt_totp_secret,
    generate_secure_token,
    generate_totp_secret,
    get_totp_provisioning_uri,
    hash_session_token,
    verify_password,
    verify_totp_code,
)
from apps.api.dependencies import get_current_session, get_current_user
from apps.api.middleware.proxy_headers import get_client_ip
from apps.api.modules.audit.models import AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.auth.schemas import (
    AuthSuccessResponse,
    LoginMfaRequiredResponse,
    LoginRequest,
    MfaSetupRequest,
    MfaSetupResponse,
    MfaVerifyRequest,
    UserResponse,
)
from apps.api.modules.users.models import User, UserSession

router = APIRouter(prefix="/admin/auth", tags=["Admin Authentication"])


@router.post(
    "/login",
    response_model=LoginMfaRequiredResponse,
    summary="Authenticate platform administrator",
)
async def admin_login(
    req: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> LoginMfaRequiredResponse:
    """
    Step 1 of privileged login.
    Verifies Argon2id password hash, checks platform role and suspension,
    and returns a short-lived MFA enrollment or challenge token.
    Generic 401 is returned on any credential or account mismatch.
    """
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "Unknown")
    correlation_id = getattr(request.state, "correlation_id", uuid.uuid4())

    # Rate limiting: max 10 attempts per minute per IP
    allowed, remaining, retry_after = await check_rate_limit(
        "login_ip", client_ip, max_attempts=10, window_seconds=60
    )
    if not allowed:
        raise AppException(
            code="RATE_LIMITED",
            message=f"Too many login attempts from this network. Retry in {retry_after} seconds.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            title="Rate Limit Exceeded",
        )

    # Rate limiting: max 5 failed attempts per 15 minutes per email
    account_allowed, _, account_retry = await check_rate_limit(
        "login_email", req.email.lower().strip(), max_attempts=5, window_seconds=900
    )
    if not account_allowed:
        raise AppException(
            code="RATE_LIMITED",
            message=f"Account locked temporarily due to repeated failed attempts. Retry in {account_retry} seconds.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            title="Rate Limit Exceeded",
        )

    # Look up user
    stmt = select(User).where(User.email == req.email.lower().strip(), User.deleted_at.is_(None))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        dummy_verify_password()
        await record_audit_event(
            db=db,
            action="login_failed",
            resource_type="auth",
            resource_id=req.email.lower().strip(),
            outcome=AuditOutcome.FAILURE,
            actor_email=req.email.lower().strip(),
            actor_role="unknown",
            reason="Invalid credentials (user not found)",
            ip_address=client_ip,
            user_agent=user_agent,
            correlation_id=correlation_id,
        )
        await db.commit()
        raise AppException(
            code="INVALID_CREDENTIALS",
            message="Invalid email or password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            title="Authentication Failed",
        )

    # Password check
    is_valid_pw = verify_password(req.password, user.hashed_password)
    if not is_valid_pw:
        await record_audit_event(
            db=db,
            action="login_failed",
            resource_type="auth",
            resource_id=str(user.id),
            outcome=AuditOutcome.FAILURE,
            actor_user_id=user.id,
            actor_email=user.email,
            actor_role=user.platform_role.value if user.platform_role else "none",
            reason="Invalid credentials (password mismatch)",
            ip_address=client_ip,
            user_agent=user_agent,
            correlation_id=correlation_id,
        )
        await db.commit()
        raise AppException(
            code="INVALID_CREDENTIALS",
            message="Invalid email or password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            title="Authentication Failed",
        )

    # Account status check (generic 401 error protects account status exposure)
    if not user.is_active:
        await record_audit_event(
            db=db,
            action="login_failed",
            resource_type="auth",
            resource_id=str(user.id),
            outcome=AuditOutcome.DENIED,
            actor_user_id=user.id,
            actor_email=user.email,
            actor_role=user.platform_role.value if user.platform_role else "none",
            reason="Suspended account login attempt blocked",
            ip_address=client_ip,
            user_agent=user_agent,
            correlation_id=correlation_id,
        )
        await db.commit()
        raise AppException(
            code="INVALID_CREDENTIALS",
            message="Invalid email or password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            title="Authentication Failed",
        )

    # Platform role enforcement: standard users cannot log into Super Admin console
    if not user.platform_role:
        await record_audit_event(
            db=db,
            action="login_failed",
            resource_type="auth",
            resource_id=str(user.id),
            outcome=AuditOutcome.DENIED,
            actor_user_id=user.id,
            actor_email=user.email,
            actor_role="none",
            reason="Non-administrative user attempted Super Admin login",
            ip_address=client_ip,
            user_agent=user_agent,
            correlation_id=correlation_id,
        )
        await db.commit()
        raise AppException(
            code="FORBIDDEN_NOT_ADMIN",
            message="Access to the administrative dashboard requires a designated platform role.",
            status_code=status.HTTP_403_FORBIDDEN,
            title="Access Forbidden",
        )

    # Multi-Factor Authentication: Mandatory for all privileged platform users
    if not user.mfa_enabled:
        enrollment_token = generate_secure_token(24)
        await store_mfa_token(
            token_type="enrollment",
            token=enrollment_token,
            data={"user_id": str(user.id), "email": user.email},
            ttl_seconds=settings.MFA_ENROLLMENT_TTL_SECONDS,
        )
        return LoginMfaRequiredResponse(
            mfa_required=True,
            enrolled=False,
            enrollment_token=enrollment_token,
        )

    challenge_token = generate_secure_token(24)
    await store_mfa_token(
        token_type="challenge",
        token=challenge_token,
        data={"user_id": str(user.id), "email": user.email},
        ttl_seconds=settings.MFA_CHALLENGE_TTL_SECONDS,
    )
    return LoginMfaRequiredResponse(
        mfa_required=True,
        enrolled=True,
        challenge_token=challenge_token,
    )


@router.post(
    "/mfa/setup",
    response_model=MfaSetupResponse,
    summary="Initialize TOTP enrollment for platform administrator",
)
async def mfa_setup(
    req: MfaSetupRequest,
    db: AsyncSession = Depends(get_db_session),
) -> MfaSetupResponse:
    """
    Step 2a (Enrollment): Generates a random Base32 TOTP seed,
    encrypts it with AES-256-GCM, and returns otpauth:// URI and plaintext key for setup.
    """
    token_data = await get_mfa_token("enrollment", req.enrollment_token)
    if not token_data or "user_id" not in token_data:
        raise AppException(
            code="MFA_TOKEN_EXPIRED",
            message="MFA enrollment session has expired. Please sign in again.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            title="Session Expired",
        )

    stmt = select(User).where(User.id == uuid.UUID(token_data["user_id"]))
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user or not user.is_active:
        raise AppException(
            code="USER_NOT_FOUND",
            message="User account not found or suspended.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            title="Invalid User",
        )

    secret = generate_totp_secret()
    qr_uri = get_totp_provisioning_uri(secret=secret, email=user.email, issuer="Scorva")
    encrypted_secret = encrypt_totp_secret(secret, settings.ENCRYPTION_MASTER_KEY)

    # Store pending secret associated with this enrollment token
    await store_mfa_token(
        token_type="pending_secret",
        token=req.enrollment_token,
        data={"encrypted_secret": encrypted_secret, "user_id": str(user.id)},
        ttl_seconds=settings.MFA_ENROLLMENT_TTL_SECONDS,
    )

    return MfaSetupResponse(secret=secret, qr_code_uri=qr_uri)


@router.post(
    "/mfa/verify",
    response_model=AuthSuccessResponse,
    summary="Verify TOTP code and issue session",
)
async def mfa_verify(
    req: MfaVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> AuthSuccessResponse:
    """
    Step 2b: Verifies 6-digit TOTP code against active challenge or pending enrollment.
    Enforces replay protection and rate limits.
    On success: issues 256-bit CSPRNG session, saves SHA-256 hash in PostgreSQL and Redis,
    and sets HttpOnly SameSite=Lax cookie.
    """
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "Unknown")
    correlation_id = getattr(request.state, "correlation_id", uuid.uuid4())

    # Rate limiting on verification attempts: max 5 attempts per token
    allowed, _, _ = await check_rate_limit(
        "mfa_verify", req.token, max_attempts=settings.MFA_MAX_ATTEMPTS, window_seconds=300
    )
    if not allowed:
        raise AppException(
            code="RATE_LIMITED",
            message="Too many invalid verification attempts. Please sign in again.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            title="Rate Limit Exceeded",
        )

    user: Optional[User] = None
    is_enrollment = False

    # 1. Check if token is challenge token
    challenge_data = await get_mfa_token("challenge", req.token)
    if challenge_data:
        user_id = uuid.UUID(challenge_data["user_id"])
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if not user or not user.is_active or not user.mfa_enabled or not user.encrypted_mfa_secret:
            raise AppException(
                code="MFA_INVALID_SESSION",
                message="Invalid challenge session.",
                status_code=status.HTTP_401_UNAUTHORIZED,
                title="MFA Verification Failed",
            )
        try:
            totp_secret = decrypt_totp_secret(
                user.encrypted_mfa_secret, settings.ENCRYPTION_MASTER_KEY
            )
        except Exception:
            raise AppException(
                code="MFA_INTERNAL_ERROR",
                message="Decryption of MFA credentials failed.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                title="Security Error",
            )
    else:
        # 2. Check if token is enrollment token
        enrollment_data = await get_mfa_token("enrollment", req.token)
        if not enrollment_data:
            raise AppException(
                code="MFA_TOKEN_INVALID",
                message="MFA challenge or enrollment session expired. Please sign in again.",
                status_code=status.HTTP_401_UNAUTHORIZED,
                title="Session Expired",
            )
        pending_secret_data = await get_mfa_token("pending_secret", req.token)
        if not pending_secret_data:
            raise AppException(
                code="MFA_SETUP_REQUIRED",
                message="MFA setup was not completed. Please request a new setup QR code.",
                status_code=status.HTTP_400_BAD_REQUEST,
                title="MFA Setup Incomplete",
            )

        user_id = uuid.UUID(enrollment_data["user_id"])
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if not user or not user.is_active:
            raise AppException(
                code="USER_NOT_FOUND",
                message="User not found or suspended.",
                status_code=status.HTTP_401_UNAUTHORIZED,
                title="Invalid User",
            )

        encrypted_secret = pending_secret_data["encrypted_secret"]
        try:
            totp_secret = decrypt_totp_secret(
                encrypted_secret, settings.ENCRYPTION_MASTER_KEY
            )
        except Exception:
            raise AppException(
                code="MFA_INTERNAL_ERROR",
                message="Decryption of pending MFA secret failed.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                title="Security Error",
            )
        is_enrollment = True

    # 3. Check for TOTP code replay
    is_fresh = await check_and_mark_totp_used(str(user.id), req.totp_code)
    if not is_fresh:
        raise AppException(
            code="MFA_CODE_REPLAYED",
            message="This verification code has already been used. Please wait for the next code.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            title="Code Replay Rejected",
        )

    # 4. Verify code with window=1 (current step ±30s)
    is_valid_code = verify_totp_code(totp_secret, req.totp_code, window=1)
    if not is_valid_code:
        await record_audit_event(
            db=db,
            action="mfa_verification_failed",
            resource_type="auth",
            resource_id=str(user.id),
            outcome=AuditOutcome.FAILURE,
            actor_user_id=user.id,
            actor_email=user.email,
            actor_role=user.platform_role.value if user.platform_role else "none",
            reason="Invalid TOTP 6-digit code",
            ip_address=client_ip,
            user_agent=user_agent,
            correlation_id=correlation_id,
        )
        await db.commit()
        raise AppException(
            code="MFA_INVALID_CODE",
            message="Invalid verification code. Please check your authenticator application.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            title="Verification Failed",
        )

    # 5. If this was initial enrollment, commit encrypted_mfa_secret to users table
    if is_enrollment:
        user.mfa_enabled = True
        user.encrypted_mfa_secret = encrypted_secret
        await record_audit_event(
            db=db,
            action="mfa_enrolled",
            resource_type="user",
            resource_id=str(user.id),
            outcome=AuditOutcome.SUCCESS,
            actor_user_id=user.id,
            actor_email=user.email,
            actor_role=user.platform_role.value if user.platform_role else "none",
            reason="User successfully enrolled mandatory MFA",
            ip_address=client_ip,
            user_agent=user_agent,
            correlation_id=correlation_id,
        )
        await delete_mfa_token("enrollment", req.token)
        await delete_mfa_token("pending_secret", req.token)
    else:
        await delete_mfa_token("challenge", req.token)

    # 6. Issue 256-bit CSPRNG Session Token
    token_plain = generate_secure_token(32)
    token_hash = hash_session_token(token_plain)
    now_utc = datetime.now(timezone.utc)
    expires_at = now_utc + timedelta(seconds=settings.SESSION_TTL_SECONDS)

    new_session = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        session_token_hash=token_hash,
        ip_address=client_ip,
        user_agent=user_agent,
        expires_at=expires_at,
        created_at=now_utc,
        last_active_at=now_utc,
        is_revoked=False,
    )
    db.add(new_session)
    user.last_login_at = now_utc

    # Record login audit event transactionally
    await record_audit_event(
        db=db,
        action="login_mfa_success",
        resource_type="auth",
        resource_id=str(new_session.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=user.id,
        actor_email=user.email,
        actor_role=user.platform_role.value if user.platform_role else "none",
        reason="MFA verified; session issued",
        ip_address=client_ip,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )
    await db.commit()

    # 7. Fast-Path Cache in Redis
    await cache_session(
        token_hash=token_hash,
        session_data={
            "session_id": str(new_session.id),
            "user_id": str(user.id),
            "email": user.email,
            "platform_role": user.platform_role.value if user.platform_role else None,
            "is_active": user.is_active,
            "created_at": new_session.created_at.isoformat(),
            "sessions_revoked_at": user.sessions_revoked_at.isoformat() if user.sessions_revoked_at else None,
        },
        ttl_seconds=settings.SESSION_TTL_SECONDS,
    )

    # 8. Set Secure HttpOnly Session Cookie
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token_plain,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE or (settings.SCORVA_ENV == "production"),
        samesite=settings.SESSION_COOKIE_SAMESITE,
        max_age=settings.SESSION_TTL_SECONDS,
        path="/",
    )

    return AuthSuccessResponse(
        user=UserResponse(
            id=str(user.id),
            email=user.email,
            full_name=user.full_name,
            platform_role=user.platform_role.value if user.platform_role else None,
            mfa_enabled=user.mfa_enabled,
            is_active=user.is_active,
        ),
        message="Authentication successful",
    )


@router.post(
    "/logout",
    summary="Revoke active session and clear session cookie",
)
async def admin_logout(
    request: Request,
    response: Response,
    session_data: Tuple[User, UserSession] = Depends(get_current_session),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Terminates active session: marks session revoked in PostgreSQL,
    deletes Redis fast-path cache, appends audit log, and clears cookie.
    """
    user, session = session_data
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "Unknown")
    correlation_id = getattr(request.state, "correlation_id", uuid.uuid4())

    session.is_revoked = True
    await record_audit_event(
        db=db,
        action="logout",
        resource_type="session",
        resource_id=str(session.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=user.id,
        actor_email=user.email,
        actor_role=user.platform_role.value if user.platform_role else "none",
        reason="User explicit logout",
        ip_address=client_ip,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )
    await db.commit()

    # Fast-path cache purge
    await delete_cached_session(session.session_token_hash)

    # Clear cookie
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite=settings.SESSION_COOKIE_SAMESITE,
    )

    return {"message": "Logged out successfully"}


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated administrator details",
)
async def get_me(
    user: User = Depends(get_current_user),
) -> UserResponse:
    """Returns current active user details for the caller."""
    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        platform_role=user.platform_role.value if user.platform_role else None,
        mfa_enabled=user.mfa_enabled,
        is_active=user.is_active,
    )

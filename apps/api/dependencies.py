from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple
import uuid
from fastapi import Cookie, Depends, Header, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.config import settings
from apps.api.core.database import get_db_session
from apps.api.core.exceptions import AppException
from apps.api.core.redis import (
    cache_session,
    delete_cached_session,
    get_cached_session,
)
from apps.api.core.security import hash_session_token
from apps.api.modules.organizations.models import (
    MembershipStatus,
    OrgRole,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
)
from apps.api.modules.users.models import PlatformRole, User, UserSession


def get_session_token_from_request(
    request: Request,
    authorization: Optional[str] = Header(None),
    cookie_token: Optional[str] = Cookie(None, alias=settings.SESSION_COOKIE_NAME),
) -> str:
    """Extracts session token from Cookie or Authorization Bearer header."""
    if cookie_token:
        return cookie_token.strip()

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token

    # Check request cookies directly as fallback
    raw_cookie = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if raw_cookie:
        return raw_cookie.strip()

    raise AppException(
        code="UNAUTHORIZED",
        message="Authentication required. Please sign in.",
        status_code=status.HTTP_401_UNAUTHORIZED,
        title="Authentication Required",
    )


async def get_current_session(
    request: Request,
    token_plain: str = Depends(get_session_token_from_request),
    db: AsyncSession = Depends(get_db_session),
) -> Tuple[User, UserSession]:
    """
    Dual-barrier session validator (§6.2).
    Evaluates fast-path Redis cache first; falls back safely to durable PostgreSQL user_sessions.
    """
    token_hash = hash_session_token(token_plain)
    now_utc = datetime.now(timezone.utc)

    # 1. Fast-Path: Redis Cache Hit
    cached = await get_cached_session(token_hash)
    if cached:
        cached_user_id = cached.get("user_id")
        created_at_iso = cached.get("created_at")
        revoked_at_iso = cached.get("sessions_revoked_at")

        # Check if user-level revocation timestamp predates session
        if revoked_at_iso and created_at_iso:
            created_at = datetime.fromisoformat(created_at_iso)
            revoked_at = datetime.fromisoformat(revoked_at_iso)
            if created_at <= revoked_at:
                await delete_cached_session(token_hash)
                raise AppException(
                    code="SESSION_REVOKED",
                    message="Session has been revoked due to a privilege or status change.",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    title="Session Invalid",
                )

        if not cached.get("is_active", True):
            await delete_cached_session(token_hash)
            raise AppException(
                code="ACCOUNT_SUSPENDED",
                message="Account has been suspended.",
                status_code=status.HTTP_401_UNAUTHORIZED,
                title="Account Suspended",
            )

    # 2. Slow-Path / Source-of-Truth: Query PostgreSQL
    stmt = (
        select(UserSession)
        .options(selectinload(UserSession.user))
        .where(UserSession.session_token_hash == token_hash)
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if not session:
        raise AppException(
            code="SESSION_NOT_FOUND",
            message="Invalid or expired session. Please log in again.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            title="Session Invalid",
        )

    if session.is_revoked:
        await delete_cached_session(token_hash)
        raise AppException(
            code="SESSION_REVOKED",
            message="Session has been revoked.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            title="Session Revoked",
        )

    if session.expires_at <= now_utc:
        await delete_cached_session(token_hash)
        raise AppException(
            code="SESSION_EXPIRED",
            message="Session has expired. Please sign in again.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            title="Session Expired",
        )

    user = session.user
    if not user or not user.is_active or user.deleted_at is not None:
        await delete_cached_session(token_hash)
        raise AppException(
            code="ACCOUNT_SUSPENDED",
            message="Your account is not active or has been suspended.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            title="Account Suspended",
        )

    if user.sessions_revoked_at and session.created_at <= user.sessions_revoked_at:
        session.is_revoked = True
        await db.commit()
        await delete_cached_session(token_hash)
        raise AppException(
            code="SESSION_REVOKED",
            message="Session was invalidated by a privilege update or administrative action.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            title="Session Invalid",
        )

    # Re-populate / slide Redis cache with remaining TTL
    remaining_seconds = max(1, int((session.expires_at - now_utc).total_seconds()))
    await cache_session(
        token_hash=token_hash,
        session_data={
            "session_id": str(session.id),
            "user_id": str(user.id),
            "email": user.email,
            "platform_role": user.platform_role.value if user.platform_role else None,
            "is_active": user.is_active,
            "created_at": session.created_at.isoformat(),
            "sessions_revoked_at": user.sessions_revoked_at.isoformat() if user.sessions_revoked_at else None,
        },
        ttl_seconds=remaining_seconds,
    )

    request.state.current_user = user
    request.state.current_session = session
    return user, session


async def get_current_user(
    session_tuple: Tuple[User, UserSession] = Depends(get_current_session)
) -> User:
    """Dependency returning the current authenticated active User."""
    return session_tuple[0]


def require_platform_role(*allowed_roles: str) -> Callable:
    """
    Strict authorization dependency builder.
    Verifies that the authenticated user possesses an authorized platform_role.
    platform_owner possesses superuser privileges across all routes.
    """
    async def role_guard(user: User = Depends(get_current_user)) -> User:
        if not user.platform_role:
            raise AppException(
                code="FORBIDDEN_NOT_ADMIN",
                message="Administrative role required for this resource.",
                status_code=status.HTTP_403_FORBIDDEN,
                title="Access Forbidden",
            )

        user_role = user.platform_role.value if isinstance(user.platform_role, PlatformRole) else str(user.platform_role)

        # Platform owner bypasses specific sub-role restrictions
        if user_role == PlatformRole.PLATFORM_OWNER.value:
            return user

        if allowed_roles and user_role not in allowed_roles:
            raise AppException(
                code="FORBIDDEN_INSUFFICIENT_ROLE",
                message=f"Access denied. Requires one of roles: {', '.join(allowed_roles)}.",
                status_code=status.HTTP_403_FORBIDDEN,
                title="Insufficient Permissions",
            )

        return user

    return role_guard


# Role shortcuts
require_super_admin = require_platform_role(
    PlatformRole.PLATFORM_OWNER.value,
    PlatformRole.PLATFORM_OPS_ADMIN.value,
)

require_platform_owner = require_platform_role(
    PlatformRole.PLATFORM_OWNER.value,
)

require_security_admin = require_platform_role(
    PlatformRole.PLATFORM_OWNER.value,
    PlatformRole.SECURITY_ADMIN.value,
)


@dataclass
class TenantContext:
    """
    Typed tenant context yielded by get_tenant_context dependency.
    Contains verified user, organization, membership, and organization role.
    """
    user: User
    organization: Organization
    membership: OrganizationMembership
    role: OrgRole


async def get_tenant_context(
    request: Request,
    org_id: Optional[uuid.UUID] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TenantContext:
    """
    Server-side tenant isolation dependency (§4.2).
    1. Authenticates request using existing server-side session validation.
    2. Verifies account status.
    3. Resolves and validates requested organization against the database.
    4. Requires active organization membership for organization-scoped operations.
    5. Rejects suspended memberships and suspended/archived organizations where access is not permitted.
    6. Yields typed TenantContext failing closed at every barrier.
    """
    # 1. Verify account status
    if not user.is_active or user.deleted_at is not None:
        raise AppException(
            code="ACCOUNT_SUSPENDED",
            message="Your account is not active or has been suspended.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            title="Account Suspended",
        )

    # 2. Resolve organization id from route path
    resolved_id = org_id
    if resolved_id is None:
        raw = request.path_params.get("org_id") or request.path_params.get("organization_id")
        if not raw:
            raise AppException(
                code="TENANT_CONTEXT_MISSING",
                message="Organization identifier missing from route path.",
                status_code=status.HTTP_400_BAD_REQUEST,
                title="Tenant Context Missing",
            )
        if isinstance(raw, uuid.UUID):
            resolved_id = raw
        else:
            try:
                resolved_id = uuid.UUID(str(raw))
            except (ValueError, TypeError):
                raise AppException(
                    code="INVALID_ORGANIZATION_ID",
                    message="Invalid organization UUID in route.",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    title="Invalid Organization ID",
                )

    # 3. Query organization
    org_stmt = (
        select(Organization)
        .where(
            Organization.id == resolved_id,
            Organization.deleted_at.is_(None),
        )
    )
    org_result = await db.execute(org_stmt)
    organization = org_result.scalar_one_or_none()

    if not organization:
        raise AppException(
            code="ORGANIZATION_NOT_FOUND",
            message="Organization not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Organization Not Found",
        )

    # 4. Verify organization membership
    mem_stmt = (
        select(OrganizationMembership)
        .where(
            OrganizationMembership.organization_id == resolved_id,
            OrganizationMembership.user_id == user.id,
        )
    )
    mem_result = await db.execute(mem_stmt)
    membership = mem_result.scalar_one_or_none()

    if not membership:
        raise AppException(
            code="TENANT_ACCESS_DENIED",
            message="You do not have access to this organization.",
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant Access Denied",
        )

    # 5. Check membership status
    if membership.status == MembershipStatus.SUSPENDED:
        raise AppException(
            code="MEMBERSHIP_SUSPENDED",
            message="Your membership in this organization has been suspended.",
            status_code=status.HTTP_403_FORBIDDEN,
            title="Membership Suspended",
        )

    # 6. Check organization status
    if organization.status == OrganizationStatus.ARCHIVED:
        raise AppException(
            code="ORGANIZATION_ARCHIVED",
            message="This organization has been archived.",
            status_code=status.HTTP_403_FORBIDDEN,
            title="Organization Archived",
        )

    if organization.status == OrganizationStatus.SUSPENDED:
        # State-mutating methods blocked; read-only metadata permitted to active members
        if request.method in ("POST", "PATCH", "PUT", "DELETE"):
            raise AppException(
                code="ORGANIZATION_SUSPENDED",
                message="This organization is suspended. State-modifying actions are blocked.",
                status_code=status.HTTP_403_FORBIDDEN,
                title="Organization Suspended",
            )

    tenant_ctx = TenantContext(
        user=user,
        organization=organization,
        membership=membership,
        role=membership.role,
    )
    request.state.tenant_context = tenant_ctx
    return tenant_ctx


def require_org_role(*allowed_roles: OrgRole) -> Callable:
    """
    Organization-scoped authorization guard.
    Verifies that the caller possesses an authorized OrgRole within the requested organization.
    """
    async def role_guard(
        tenant: TenantContext = Depends(get_tenant_context),
    ) -> TenantContext:
        if allowed_roles and tenant.role not in allowed_roles:
            raise AppException(
                code="FORBIDDEN_INSUFFICIENT_ORG_ROLE",
                message=f"Access denied. Requires one of organization roles: {', '.join(r.value for r in allowed_roles)}.",
                status_code=status.HTTP_403_FORBIDDEN,
                title="Insufficient Permissions",
            )
        return tenant

    return role_guard


require_org_member = require_org_role(
    OrgRole.ORGANIZER,
    OrgRole.ORG_ADMIN,
    OrgRole.ORG_OWNER,
)

require_org_admin = require_org_role(
    OrgRole.ORG_ADMIN,
    OrgRole.ORG_OWNER,
)

require_org_owner = require_org_role(
    OrgRole.ORG_OWNER,
)


import math
from datetime import datetime, timezone
from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_db_session
from apps.api.core.exceptions import AppException
from apps.api.core.redis import delete_cached_session
from apps.api.core.security import hash_password
from apps.api.dependencies import get_current_user, require_security_admin, require_super_admin
from apps.api.middleware.proxy_headers import get_client_ip
from apps.api.modules.audit.models import AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.auth.schemas import UserResponse
from apps.api.modules.rbac.models import PLATFORM_SCOPE_ID
from apps.api.modules.rbac.service import (
    check_last_platform_owner_lockout,
    increment_policy_version_and_outbox,
)
from apps.api.modules.users.models import PlatformRole, User, UserSession
from apps.api.modules.users.schemas import (
    PaginatedUsersResponse,
    UserCreateRequest,
    UserRoleUpdateRequest,
    UserStatusUpdateRequest,
)

router = APIRouter(prefix="/admin/users", tags=["Admin User Management"])


@router.get(
    "",
    response_model=PaginatedUsersResponse,
    summary="List platform users with pagination and search (Super Admin or Security Admin)",
)
@router.get("/", response_model=PaginatedUsersResponse, include_in_schema=False)
async def list_users(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(15, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search term for full name or email"),
    role: Optional[str] = Query(None, description="Filter by platform role or 'none'"),
    status: Optional[str] = Query(None, description="Filter by account status ('active', 'suspended')"),
    sort_by: str = Query("created_at", description="Sort field ('created_at', 'full_name', 'email')"),
    sort_order: str = Query("desc", description="Sort order ('asc', 'desc')"),
    db: AsyncSession = Depends(get_db_session),
    admin_user: User = Depends(require_security_admin),
) -> PaginatedUsersResponse:
    """Retrieves paginated directory of platform users with search and filtering."""
    filters = [User.deleted_at.is_(None)]

    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(or_(User.email.ilike(term), User.full_name.ilike(term)))

    if role:
        role_cleaned = role.strip().lower()
        if role_cleaned == "none":
            filters.append(User.platform_role.is_(None))
        else:
            try:
                matched_role = PlatformRole(role_cleaned)
                filters.append(User.platform_role == matched_role)
            except ValueError:
                pass

    if status:
        status_cleaned = status.strip().lower()
        if status_cleaned == "active":
            filters.append(User.is_active.is_(True))
        elif status_cleaned in ("suspended", "inactive"):
            filters.append(User.is_active.is_(False))

    count_stmt = select(func.count(User.id)).where(*filters)
    total = (await db.execute(count_stmt)).scalar() or 0
    total_pages = math.ceil(total / limit) if total > 0 else 0

    order_map = {
        "created_at": User.created_at,
        "full_name": User.full_name,
        "email": User.email,
    }
    order_col = order_map.get(sort_by, User.created_at)
    order_expr = order_col.desc() if sort_order.lower() == "desc" else order_col.asc()

    stmt = (
        select(User)
        .where(*filters)
        .order_by(order_expr)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    users = result.scalars().all()

    items = [
        UserResponse(
            id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            platform_role=u.platform_role.value if u.platform_role else None,
            mfa_enabled=u.mfa_enabled,
            is_active=u.is_active,
            created_at=u.created_at,
            last_login_at=u.last_login_at,
        )
        for u in users
    ]

    return PaginatedUsersResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user or organizer with credentials (Super Admin)",
)
@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_user(
    req: UserCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    admin_user: User = Depends(require_super_admin),
) -> UserResponse:
    """
    Creates a new user account with credentials directly.
    Organizers and users do not need to self-register; super admins can provision them directly.
    Optionally assigns them to an organization.
    """
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "Unknown")
    correlation_id = getattr(request.state, "correlation_id", uuid.uuid4())

    email_clean = req.email.lower().strip()
    stmt = select(User).where(User.email == email_clean, User.deleted_at.is_(None))
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise AppException(
            code="USER_EMAIL_EXISTS",
            message=f"User with email '{email_clean}' already exists.",
            status_code=status.HTTP_409_CONFLICT,
            title="Email Already Registered",
        )

    hashed_pw = hash_password(req.password)
    user_id = uuid.uuid4()
    new_user = User(
        id=user_id,
        email=email_clean,
        full_name=req.full_name.strip(),
        hashed_password=hashed_pw,
        platform_role=req.platform_role,
        is_active=True,
        is_verified=True,
        mfa_enabled=False,
    )
    db.add(new_user)

    if req.organization_id:
        from apps.api.modules.organizations.models import Organization, OrganizationMembership, MembershipStatus, OrgRole
        org_stmt = select(Organization).where(Organization.id == req.organization_id, Organization.deleted_at.is_(None))
        org = (await db.execute(org_stmt)).scalar_one_or_none()
        if not org:
            raise AppException(
                code="ORGANIZATION_NOT_FOUND",
                message="Target organization not found.",
                status_code=status.HTTP_404_NOT_FOUND,
                title="Organization Not Found",
            )
        role_enum = OrgRole.ORGANIZER
        if req.org_role:
            try:
                role_enum = OrgRole(req.org_role.lower())
            except ValueError:
                role_enum = OrgRole.ORGANIZER

        membership = OrganizationMembership(
            id=uuid.uuid4(),
            organization_id=org.id,
            user_id=user_id,
            role=role_enum,
            status=MembershipStatus.ACTIVE,
        )
        db.add(membership)

    role_desc = req.platform_role.value if req.platform_role else (req.org_role or "organizer")
    await record_audit_event(
        db=db,
        action="user_created",
        resource_type="user",
        resource_id=str(user_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=admin_user.id,
        actor_email=admin_user.email,
        actor_role=admin_user.platform_role.value if admin_user.platform_role else "none",
        reason=f"User {email_clean} created with role {role_desc}",
        diff_payload={"email": email_clean, "role": role_desc},
        ip_address=client_ip,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    await db.commit()
    await db.refresh(new_user)

    return UserResponse(
        id=str(new_user.id),
        email=new_user.email,
        full_name=new_user.full_name,
        platform_role=new_user.platform_role.value if new_user.platform_role else None,
        mfa_enabled=new_user.mfa_enabled,
        is_active=new_user.is_active,
        created_at=new_user.created_at,
        last_login_at=new_user.last_login_at,
    )


@router.post(
    "/{user_id}/status",
    response_model=UserResponse,
    summary="Suspend or activate user account",
)
async def update_user_status(
    user_id: uuid.UUID,
    req: UserStatusUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    admin_user: User = Depends(require_super_admin),
) -> UserResponse:
    """
    Suspends or activates a user account.
    If suspending: transactionally revokes all active sessions in PostgreSQL,
    sets users.sessions_revoked_at = NOW(), and appends an immutable audit event.
    """
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "Unknown")
    correlation_id = getattr(request.state, "correlation_id", uuid.uuid4())

    stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
    result = await db.execute(stmt)
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise AppException(
            code="USER_NOT_FOUND",
            message="Target user not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # Concurrency-safe lockout protection: cannot deactivate the last active Platform Owner
    if not req.is_active:
        await check_last_platform_owner_lockout(db, user_id)

    now_utc = datetime.now(timezone.utc)
    target_user.is_active = req.is_active

    if not req.is_active:
        # Immediate session invalidation for suspended user
        target_user.sessions_revoked_at = now_utc
        # Proactively purge session cache from Redis
        active_sessions_stmt = select(UserSession.session_token_hash).where(UserSession.user_id == user_id)
        session_hashes = (await db.execute(active_sessions_stmt)).scalars().all()
        for s_hash in session_hashes:
            await delete_cached_session(s_hash)

        await db.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id)
            .values(is_revoked=True)
        )

    # Durable authorization policy invalidation & outbox emission
    await increment_policy_version_and_outbox(
        db=db,
        scope_type="platform",
        scope_id=PLATFORM_SCOPE_ID,
        event_type="user_status_updated",
        target_user_id=target_user.id,
    )

    action_name = "user_activated" if req.is_active else "user_suspended"
    await record_audit_event(
        db=db,
        action=action_name,
        resource_type="user",
        resource_id=str(target_user.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=admin_user.id,
        actor_email=admin_user.email,
        actor_role=admin_user.platform_role.value if admin_user.platform_role else "none",
        reason=req.reason or f"Account {'reactivated' if req.is_active else 'suspended'} by admin",
        diff_payload={"is_active": req.is_active},
        ip_address=client_ip,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )
    await db.commit()

    return UserResponse(
        id=str(target_user.id),
        email=target_user.email,
        full_name=target_user.full_name,
        platform_role=target_user.platform_role.value if target_user.platform_role else None,
        mfa_enabled=target_user.mfa_enabled,
        is_active=target_user.is_active,
    )


@router.post(
    "/{user_id}/role",
    response_model=UserResponse,
    summary="Update platform role for a user",
)
async def update_user_role(
    user_id: uuid.UUID,
    req: UserRoleUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    admin_user: User = Depends(require_super_admin),
) -> UserResponse:
    """
    Modifies a user's platform role.
    Role changes immediately revoke all active sessions to force re-authentication.
    """
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "Unknown")
    correlation_id = getattr(request.state, "correlation_id", uuid.uuid4())

    stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
    result = await db.execute(stmt)
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise AppException(
            code="USER_NOT_FOUND",
            message="Target user not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # Concurrency-safe lockout protection: cannot demote the last active Platform Owner
    if target_user.platform_role == PlatformRole.PLATFORM_OWNER and req.platform_role != PlatformRole.PLATFORM_OWNER:
        await check_last_platform_owner_lockout(db, user_id)

    now_utc = datetime.now(timezone.utc)
    old_role = target_user.platform_role.value if target_user.platform_role else None
    target_user.platform_role = req.platform_role
    target_user.sessions_revoked_at = now_utc

    # Proactively purge session cache from Redis
    active_sessions_stmt = select(UserSession.session_token_hash).where(UserSession.user_id == user_id)
    session_hashes = (await db.execute(active_sessions_stmt)).scalars().all()
    for s_hash in session_hashes:
        await delete_cached_session(s_hash)

    # Invalidate all prior sessions
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id)
        .values(is_revoked=True)
    )

    # Durable authorization policy invalidation & outbox emission
    await increment_policy_version_and_outbox(
        db=db,
        scope_type="platform",
        scope_id=PLATFORM_SCOPE_ID,
        event_type="user_role_updated",
        target_user_id=target_user.id,
    )

    await record_audit_event(
        db=db,
        action="user_role_changed",
        resource_type="user",
        resource_id=str(target_user.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=admin_user.id,
        actor_email=admin_user.email,
        actor_role=admin_user.platform_role.value if admin_user.platform_role else "none",
        reason=req.reason or f"Role updated from {old_role} to {req.platform_role}",
        diff_payload={"old_role": old_role, "new_role": req.platform_role.value if req.platform_role else None},
        ip_address=client_ip,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )
    await db.commit()

    return UserResponse(
        id=str(target_user.id),
        email=target_user.email,
        full_name=target_user.full_name,
        platform_role=target_user.platform_role.value if target_user.platform_role else None,
        mfa_enabled=target_user.mfa_enabled,
        is_active=target_user.is_active,
    )


@router.post(
    "/{user_id}/revoke-sessions",
    summary="Revoke all active sessions for a user",
)
async def revoke_user_sessions(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    admin_user: User = Depends(require_security_admin),
) -> dict:
    """
    Terminates all active sessions for a target user.
    Sets users.sessions_revoked_at = NOW() and marks user_sessions.is_revoked = TRUE.
    """
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "Unknown")
    correlation_id = getattr(request.state, "correlation_id", uuid.uuid4())

    stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
    result = await db.execute(stmt)
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise AppException(
            code="USER_NOT_FOUND",
            message="Target user not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    now_utc = datetime.now(timezone.utc)
    target_user.sessions_revoked_at = now_utc

    # Proactively purge session cache from Redis
    active_sessions_stmt = select(UserSession.session_token_hash).where(UserSession.user_id == user_id)
    session_hashes = (await db.execute(active_sessions_stmt)).scalars().all()
    for s_hash in session_hashes:
        await delete_cached_session(s_hash)

    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id)
        .values(is_revoked=True)
    )

    await record_audit_event(
        db=db,
        action="user_sessions_revoked",
        resource_type="user",
        resource_id=str(target_user.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=admin_user.id,
        actor_email=admin_user.email,
        actor_role=admin_user.platform_role.value if admin_user.platform_role else "none",
        reason="Administrative session revocation",
        ip_address=client_ip,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )
    await db.commit()

    return {"message": f"All sessions for user {target_user.email} revoked successfully"}

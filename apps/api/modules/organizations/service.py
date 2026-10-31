import math
from typing import Any, Dict, List, Optional, Tuple
import uuid
from fastapi import status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.core.exceptions import AppException
from apps.api.core.security import hash_password
from apps.api.modules.audit.models import AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.hackathons.models import Hackathon
from apps.api.modules.integrations.service import assert_settings_does_not_contain_credentials
from apps.api.modules.organizations.models import (
    MembershipStatus,
    OrgRole,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
)
from apps.api.modules.organizations.schemas import (
    AdminAddMemberRequest,
    AdminUpdateOrganizationRequest,
    CreateOrganizationRequest,
    InviteMemberRequest,
    OrganizationDetailResponse,
    OrganizationMemberResponse,
    OrganizationProfileResponse,
    OrganizationSummaryResponse,
    OwnerSummary,
    TenantUpdateOrganizationRequest,
    UpdateMemberRoleRequest,
    UpdateOrganizationStatusRequest,
    UserSummary,
)
from apps.api.modules.users.models import PlatformRole, User


async def list_admin_organizations(
    db: AsyncSession,
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    org_status: Optional[OrganizationStatus] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> Tuple[List[OrganizationSummaryResponse], int, int]:
    """
    Paginated directory of organizations for platform administrators (§8.1).
    Supports search by name/slug, status filtering, and dynamic ordering.
    """
    # Base filter: exclude soft-deleted
    filters = [Organization.deleted_at.is_(None)]

    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(or_(Organization.name.ilike(term), Organization.slug.ilike(term)))

    if org_status:
        filters.append(Organization.status == org_status)

    # Subqueries for member and hackathon counts
    member_count_subq = (
        select(func.count(OrganizationMembership.id))
        .where(OrganizationMembership.organization_id == Organization.id)
        .scalar_subquery()
    )
    hackathon_count_subq = (
        select(func.count(Hackathon.id))
        .where(
            Hackathon.organization_id == Organization.id,
            Hackathon.deleted_at.is_(None),
        )
        .scalar_subquery()
    )

    # Count total matching records
    count_stmt = select(func.count(Organization.id)).where(*filters)
    total = (await db.execute(count_stmt)).scalar() or 0
    total_pages = math.ceil(total / limit) if total > 0 else 0

    # Query items
    stmt = (
        select(
            Organization,
            member_count_subq.label("member_count"),
            hackathon_count_subq.label("hackathon_count"),
        )
        .options(selectinload(Organization.owner))
        .where(*filters)
    )

    if sort_by == "name":
        order_col = Organization.name.desc() if sort_order.lower() == "desc" else Organization.name.asc()
    else:
        order_col = Organization.created_at.desc() if sort_order.lower() == "desc" else Organization.created_at.asc()

    stmt = stmt.order_by(order_col).offset((page - 1) * limit).limit(limit)
    rows = (await db.execute(stmt)).all()

    items: List[OrganizationSummaryResponse] = []
    for org, m_count, h_count in rows:
        owner_summary = None
        if org.owner:
            owner_summary = OwnerSummary(
                id=org.owner.id,
                email=org.owner.email,
                full_name=org.owner.full_name,
            )
        items.append(
            OrganizationSummaryResponse(
                id=org.id,
                name=org.name,
                slug=org.slug,
                status=org.status,
                owner_id=org.owner_id,
                owner_email=org.owner.email if org.owner else None,
                owner_name=org.owner.full_name if org.owner else None,
                owner=owner_summary,
                member_count=m_count or 0,
                hackathon_count=h_count or 0,
                created_at=org.created_at,
                updated_at=org.updated_at,
            )
        )

    return items, total, total_pages


async def get_organization_detail(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> OrganizationDetailResponse:
    """Retrieves full organization metadata with member and hackathon counts."""
    member_count_subq = (
        select(func.count(OrganizationMembership.id))
        .where(OrganizationMembership.organization_id == Organization.id)
        .scalar_subquery()
    )
    hackathon_count_subq = (
        select(func.count(Hackathon.id))
        .where(
            Hackathon.organization_id == Organization.id,
            Hackathon.deleted_at.is_(None),
        )
        .scalar_subquery()
    )

    stmt = (
        select(
            Organization,
            member_count_subq.label("member_count"),
            hackathon_count_subq.label("hackathon_count"),
        )
        .options(selectinload(Organization.owner))
        .where(Organization.id == org_id, Organization.deleted_at.is_(None))
    )
    row = (await db.execute(stmt)).first()
    if not row:
        raise AppException(
            code="ORGANIZATION_NOT_FOUND",
            message="Organization not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Organization Not Found",
        )

    org, m_count, h_count = row
    owner_summary = None
    if org.owner:
        owner_summary = OwnerSummary(
            id=org.owner.id,
            email=org.owner.email,
            full_name=org.owner.full_name,
        )

    return OrganizationDetailResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        status=org.status,
        owner_id=org.owner_id,
        owner_email=org.owner.email if org.owner else None,
        owner_name=org.owner.full_name if org.owner else None,
        owner=owner_summary,
        settings=org.settings or {},
        member_count=m_count or 0,
        hackathon_count=h_count or 0,
        created_at=org.created_at,
        updated_at=org.updated_at,
    )


async def create_organization(
    db: AsyncSession,
    data: CreateOrganizationRequest,
    actor: User,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[uuid.UUID] = None,
) -> OrganizationDetailResponse:
    """Creates a new organization tenant and assigns initial ORG_OWNER membership."""
    # 1. Lookup owner user; if not found, automatically provision organizer credentials
    owner_email_clean = data.owner_email.lower().strip()
    owner_stmt = select(User).where(User.email == owner_email_clean, User.deleted_at.is_(None))
    owner = (await db.execute(owner_stmt)).scalar_one_or_none()
    if not owner:
        owner_name = data.owner_name.strip() if data.owner_name else "Event Organizer"
        raw_password = data.owner_password if data.owner_password else "OrganizerPass123!"
        hashed_pw = hash_password(raw_password)
        owner = User(
            id=uuid.uuid4(),
            email=owner_email_clean,
            full_name=owner_name,
            hashed_password=hashed_pw,
            platform_role=None,
            is_active=True,
            is_verified=True,
            mfa_enabled=False,
        )
        db.add(owner)
        await db.flush()
    elif not owner.is_active:
        raise AppException(
            code="USER_INACTIVE",
            message="Target owner account is not active.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Inactive Owner",
        )
    elif data.owner_password:
        owner.hashed_password = hash_password(data.owner_password)
        if data.owner_name:
            owner.full_name = data.owner_name.strip()
        await db.flush()

    # 2. Check slug uniqueness
    slug_stmt = select(Organization.id).where(Organization.slug == data.slug)
    existing_org = (await db.execute(slug_stmt)).scalar_one_or_none()
    if existing_org:
        raise AppException(
            code="ORGANIZATION_SLUG_TAKEN",
            message=f"Organization slug '{data.slug}' is already taken.",
            status_code=status.HTTP_409_CONFLICT,
            title="Slug Conflict",
        )

    org_id = uuid.uuid4()
    org_settings = data.settings or {"max_hackathons": 10, "timezone": "UTC"}
    assert_settings_does_not_contain_credentials(org_settings)

    org = Organization(
        id=org_id,
        name=data.name,
        slug=data.slug,
        owner_id=owner.id,
        status=OrganizationStatus.ACTIVE,
        settings=org_settings,
    )
    db.add(org)

    membership = OrganizationMembership(
        id=uuid.uuid4(),
        organization_id=org_id,
        user_id=owner.id,
        role=OrgRole.ORG_OWNER,
        status=MembershipStatus.ACTIVE,
    )
    db.add(membership)

    # Append audit event
    await record_audit_event(
        db=db,
        action="organization_created",
        resource_type="organization",
        resource_id=str(org_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.platform_role.value if actor.platform_role else "system",
        organization_id=org_id,
        reason="Organization created via platform administration",
        diff_payload={"name": data.name, "slug": data.slug, "owner_id": str(owner.id)},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppException(
            code="ORGANIZATION_SLUG_TAKEN",
            message=f"Organization slug '{data.slug}' is already taken.",
            status_code=status.HTTP_409_CONFLICT,
            title="Slug Conflict",
        )

    return await get_organization_detail(db, org_id)


async def update_organization_admin(
    db: AsyncSession,
    org_id: uuid.UUID,
    data: AdminUpdateOrganizationRequest,
    actor: User,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[uuid.UUID] = None,
) -> OrganizationDetailResponse:
    """Updates organization profile, slug, or settings via platform admin plane."""
    stmt = select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
    org = (await db.execute(stmt)).scalar_one_or_none()
    if not org:
        raise AppException(
            code="ORGANIZATION_NOT_FOUND",
            message="Organization not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Organization Not Found",
        )

    diff: Dict[str, Any] = {}
    if data.name is not None and data.name != org.name:
        diff["name"] = {"old": org.name, "new": data.name}
        org.name = data.name

    if data.slug is not None and data.slug != org.slug:
        # Check uniqueness
        slug_stmt = select(Organization.id).where(Organization.slug == data.slug, Organization.id != org_id)
        if (await db.execute(slug_stmt)).scalar_one_or_none():
            raise AppException(
                code="ORGANIZATION_SLUG_TAKEN",
                message=f"Organization slug '{data.slug}' is already in use.",
                status_code=status.HTTP_409_CONFLICT,
                title="Slug Conflict",
            )
        diff["slug"] = {"old": org.slug, "new": data.slug}
        org.slug = data.slug

    if data.settings is not None:
        merged_settings = {**(org.settings or {}), **data.settings} if isinstance(org.settings, dict) else data.settings
        assert_settings_does_not_contain_credentials(merged_settings)
        diff["settings"] = {"old": org.settings, "new": merged_settings}
        org.settings = merged_settings

    await record_audit_event(
        db=db,
        action="organization_updated",
        resource_type="organization",
        resource_id=str(org_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.platform_role.value if actor.platform_role else "system",
        organization_id=org_id,
        reason="Organization updated via platform admin plane",
        diff_payload=diff,
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppException(
            code="ORGANIZATION_SLUG_TAKEN",
            message="Organization slug conflict detected.",
            status_code=status.HTTP_409_CONFLICT,
            title="Slug Conflict",
        )

    return await get_organization_detail(db, org_id)


async def change_organization_status(
    db: AsyncSession,
    org_id: uuid.UUID,
    data: UpdateOrganizationStatusRequest,
    actor: User,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[uuid.UUID] = None,
) -> OrganizationDetailResponse:
    """Suspends, reactivates, or archives an organization with mandatory audit logging."""
    stmt = select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
    org = (await db.execute(stmt)).scalar_one_or_none()
    if not org:
        raise AppException(
            code="ORGANIZATION_NOT_FOUND",
            message="Organization not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Organization Not Found",
        )

    target_status = data.status
    if target_status is None:
        if data.is_active is False:
            target_status = OrganizationStatus.SUSPENDED
        elif data.is_active is True:
            target_status = OrganizationStatus.ACTIVE

    if target_status is None:
        raise AppException(
            code="INVALID_STATUS_UPDATE",
            message="Either 'status' or 'is_active' must be provided.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid Request",
        )

    # Require non-empty reason for suspension or archival
    if target_status in (OrganizationStatus.SUSPENDED, OrganizationStatus.ARCHIVED):
        if not data.reason or not data.reason.strip():
            raise AppException(
                code="REASON_REQUIRED",
                message=f"A non-empty reason is required when {target_status.value} an organization.",
                status_code=status.HTTP_400_BAD_REQUEST,
                title="Reason Required",
            )

    # Least privilege (Table 5.2): Only Platform Owner can archive an organization
    if target_status == OrganizationStatus.ARCHIVED:
        user_role = (
            actor.platform_role.value
            if isinstance(actor.platform_role, PlatformRole)
            else str(actor.platform_role)
            if actor.platform_role
            else None
        )
        if user_role and user_role != PlatformRole.PLATFORM_OWNER.value:
            raise AppException(
                code="FORBIDDEN_INSUFFICIENT_ROLE",
                message="Only Platform Owner can archive an organization.",
                status_code=status.HTTP_403_FORBIDDEN,
                title="Insufficient Permissions",
            )

    old_status = org.status
    org.status = target_status

    reason_str = (data.reason.strip() if data.reason else None) or f"Organization status changed from {old_status.value} to {target_status.value}"

    await record_audit_event(
        db=db,
        action="organization_status_changed",
        resource_type="organization",
        resource_id=str(org_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.platform_role.value if actor.platform_role else "system",
        organization_id=org_id,
        reason=reason_str,
        diff_payload={"old_status": old_status.value, "new_status": target_status.value},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    await db.commit()
    return await get_organization_detail(db, org_id)


async def transfer_organization_ownership(
    db: AsyncSession,
    org_id: uuid.UUID,
    data: TransferOwnershipRequest,
    actor: User,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[uuid.UUID] = None,
) -> OrganizationDetailResponse:
    """
    Transfers organization ownership to another active member (§8.1 / §8.2).
    Demotes the previous owner to ORG_ADMIN and promotes the target member to ORG_OWNER.
    Uses row-level locking (with_for_update) to serialize concurrent transfer requests.
    """
    stmt = (
        select(Organization)
        .where(Organization.id == org_id, Organization.deleted_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    org = (await db.execute(stmt)).scalar_one_or_none()
    if not org:
        raise AppException(
            code="ORGANIZATION_NOT_FOUND",
            message="Organization not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Organization Not Found",
        )

    new_owner_id = data.new_owner_user_id
    if org.owner_id == new_owner_id:
        raise AppException(
            code="ALREADY_OWNER",
            message="Target user is already the owner of this organization.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Already Owner",
        )

    # Verify target user exists
    target_user_stmt = select(User).where(User.id == new_owner_id, User.deleted_at.is_(None))
    target_user = (await db.execute(target_user_stmt)).scalar_one_or_none()
    if not target_user:
        raise AppException(
            code="USER_NOT_FOUND",
            message="Target owner user does not exist.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="User Not Found",
        )

    # Verify target user has an active membership in this organization (with row lock)
    target_mem_stmt = (
        select(OrganizationMembership)
        .where(
            OrganizationMembership.organization_id == org_id,
            OrganizationMembership.user_id == new_owner_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    target_membership = (await db.execute(target_mem_stmt)).scalar_one_or_none()
    if not target_membership:
        raise AppException(
            code="TARGET_USER_NOT_MEMBER",
            message="Target user must be an active member of the organization to receive ownership.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Target User Not Member",
        )

    if target_membership.status == MembershipStatus.SUSPENDED:
        raise AppException(
            code="TARGET_MEMBER_SUSPENDED",
            message="Cannot transfer ownership to a suspended member.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Target Member Suspended",
        )

    # Demote previous owner to ORG_ADMIN (with row lock)
    old_owner_id = org.owner_id
    old_mem_stmt = (
        select(OrganizationMembership)
        .where(
            OrganizationMembership.organization_id == org_id,
            OrganizationMembership.user_id == old_owner_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    old_membership = (await db.execute(old_mem_stmt)).scalar_one_or_none()
    if old_membership:
        old_membership.role = OrgRole.ORG_ADMIN

    # Promote new owner
    target_membership.role = OrgRole.ORG_OWNER
    org.owner_id = new_owner_id

    reason_str = (data.reason.strip() if data.reason else None) or f"Transferred ownership from {old_owner_id} to {new_owner_id}"

    await record_audit_event(
        db=db,
        action="organization_ownership_transferred",
        resource_type="organization",
        resource_id=str(org_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.platform_role.value if actor.platform_role else "org_owner",
        organization_id=org_id,
        reason=reason_str,
        diff_payload={"old_owner_id": str(old_owner_id), "new_owner_id": str(new_owner_id)},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    await db.commit()
    return await get_organization_detail(db, org_id)


async def list_organization_members(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> List[OrganizationMemberResponse]:
    """Retrieves all members of an organization with user profile details."""
    stmt = (
        select(OrganizationMembership)
        .options(selectinload(OrganizationMembership.user))
        .where(OrganizationMembership.organization_id == org_id)
        .order_by(OrganizationMembership.created_at.asc())
    )
    memberships = (await db.execute(stmt)).scalars().all()

    items: List[OrganizationMemberResponse] = []
    for m in memberships:
        user_summary = None
        if m.user:
            user_summary = UserSummary(
                id=m.user.id,
                email=m.user.email,
                full_name=m.user.full_name,
            )
        items.append(
            OrganizationMemberResponse(
                id=m.id,
                organization_id=m.organization_id,
                user_id=m.user_id,
                email=m.user.email if m.user else None,
                full_name=m.user.full_name if m.user else None,
                user=user_summary,
                role=m.role,
                status=m.status,
                created_at=m.created_at,
                updated_at=m.updated_at,
            )
        )
    return items


async def add_organization_member(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: Optional[uuid.UUID],
    email: Optional[str],
    role: OrgRole,
    actor: User,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[uuid.UUID] = None,
    audit_action: str = "org_member_added",
    full_name: Optional[str] = None,
    password: Optional[str] = None,
) -> OrganizationMemberResponse:
    """Adds a user to an organization's membership roster. Automatically provisions user if they do not exist."""
    # Find user
    if user_id:
        user_stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
    elif email:
        user_stmt = select(User).where(User.email == email.lower().strip(), User.deleted_at.is_(None))
    else:
        raise AppException(
            code="USER_NOT_SPECIFIED",
            message="Either user_id or email must be specified.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="User Not Specified",
        )

    target_user = (await db.execute(user_stmt)).scalar_one_or_none()
    if not target_user:
        if email:
            # Organiser does not need to register - create account directly
            new_name = full_name.strip() if full_name else "Event Organizer"
            raw_password = password if password else "OrganizerPass123!"
            target_user = User(
                id=uuid.uuid4(),
                email=email.lower().strip(),
                full_name=new_name,
                hashed_password=hash_password(raw_password),
                platform_role=None,
                is_active=True,
                is_verified=True,
                mfa_enabled=False,
            )
            db.add(target_user)
            await db.flush()
        else:
            raise AppException(
                code="USER_NOT_FOUND",
                message="Target user not found.",
                status_code=status.HTTP_404_NOT_FOUND,
                title="User Not Found",
            )
    elif not target_user.is_active:
        raise AppException(
            code="USER_INACTIVE",
            message="Target user account is not active.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="User Inactive",
        )
    elif password:
        target_user.hashed_password = hash_password(password)
        if full_name:
            target_user.full_name = full_name.strip()
        await db.flush()

    # Check for existing membership
    existing_stmt = select(OrganizationMembership).where(
        OrganizationMembership.organization_id == org_id,
        OrganizationMembership.user_id == target_user.id,
    )
    if (await db.execute(existing_stmt)).scalar_one_or_none():
        raise AppException(
            code="MEMBERSHIP_ALREADY_EXISTS",
            message="User is already a member of this organization.",
            status_code=status.HTTP_409_CONFLICT,
            title="Membership Already Exists",
        )

    membership = OrganizationMembership(
        id=uuid.uuid4(),
        organization_id=org_id,
        user_id=target_user.id,
        role=role,
        status=MembershipStatus.ACTIVE,
    )
    db.add(membership)

    await record_audit_event(
        db=db,
        action=audit_action,
        resource_type="organization_membership",
        resource_id=str(membership.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.platform_role.value if actor.platform_role else "org_admin",
        organization_id=org_id,
        reason=f"Added member {target_user.email} with role {role.value}",
        diff_payload={"user_id": str(target_user.id), "role": role.value},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppException(
            code="MEMBERSHIP_ALREADY_EXISTS",
            message="User is already a member of this organization.",
            status_code=status.HTTP_409_CONFLICT,
            title="Membership Already Exists",
        )

    await db.refresh(membership)
    return OrganizationMemberResponse(
        id=membership.id,
        organization_id=membership.organization_id,
        user_id=membership.user_id,
        email=target_user.email,
        full_name=target_user.full_name,
        user=UserSummary(
            id=target_user.id,
            email=target_user.email,
            full_name=target_user.full_name,
        ),
        role=membership.role,
        status=membership.status,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    )


async def update_organization_member_role(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    new_role: OrgRole,
    actor: User,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[uuid.UUID] = None,
    audit_action: str = "org_member_role_updated",
) -> OrganizationMemberResponse:
    """Updates member role within an organization."""
    # Find org
    org_stmt = select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
    org = (await db.execute(org_stmt)).scalar_one_or_none()
    if not org:
        raise AppException(
            code="ORGANIZATION_NOT_FOUND",
            message="Organization not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Organization Not Found",
        )

    # Disallow promoting to org_owner directly
    if new_role == OrgRole.ORG_OWNER:
        raise AppException(
            code="FORBIDDEN_INSUFFICIENT_ORG_ROLE",
            message="Cannot promote to org_owner directly. Use transfer-ownership.",
            status_code=status.HTTP_403_FORBIDDEN,
            title="Cannot Set Owner Role",
        )

    # Least privilege (Table 5.2): In admin plane, only Platform Owner can promote to Org Admin
    if new_role == OrgRole.ORG_ADMIN and actor.platform_role:
        user_role = (
            actor.platform_role.value
            if isinstance(actor.platform_role, PlatformRole)
            else str(actor.platform_role)
        )
        if user_role != PlatformRole.PLATFORM_OWNER.value:
            raise AppException(
                code="FORBIDDEN_INSUFFICIENT_ROLE",
                message="Only Platform Owner can promote members to Organization Administrator.",
                status_code=status.HTTP_403_FORBIDDEN,
                title="Insufficient Permissions",
            )

    # If target is current owner, cannot change role directly
    if user_id == org.owner_id:
        raise AppException(
            code="CANNOT_MODIFY_OWNER_ROLE",
            message="Cannot change role of organization owner directly. Use transfer-ownership.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Cannot Modify Owner Role",
        )

    stmt = (
        select(OrganizationMembership)
        .options(selectinload(OrganizationMembership.user))
        .where(
            OrganizationMembership.organization_id == org_id,
            OrganizationMembership.user_id == user_id,
        )
    )
    membership = (await db.execute(stmt)).scalar_one_or_none()
    if not membership:
        raise AppException(
            code="MEMBERSHIP_NOT_FOUND",
            message="Member not found in this organization.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Membership Not Found",
        )

    old_role = membership.role
    membership.role = new_role

    await record_audit_event(
        db=db,
        action=audit_action,
        resource_type="organization_membership",
        resource_id=str(membership.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.platform_role.value if actor.platform_role else "org_owner",
        organization_id=org_id,
        reason=f"Updated member role from {old_role.value} to {new_role.value}",
        diff_payload={"old_role": old_role.value, "new_role": new_role.value},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    await db.commit()
    await db.refresh(membership)

    return OrganizationMemberResponse(
        id=membership.id,
        organization_id=membership.organization_id,
        user_id=membership.user_id,
        email=membership.user.email if membership.user else None,
        full_name=membership.user.full_name if membership.user else None,
        user=UserSummary(
            id=membership.user.id,
            email=membership.user.email,
            full_name=membership.user.full_name,
        ) if membership.user else None,
        role=membership.role,
        status=membership.status,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    )


async def remove_organization_member(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    actor: User,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[uuid.UUID] = None,
    is_admin_plane: bool = False,
) -> None:
    """Removes a user from an organization's membership roster."""
    org_stmt = select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
    org = (await db.execute(org_stmt)).scalar_one_or_none()
    if not org:
        raise AppException(
            code="ORGANIZATION_NOT_FOUND",
            message="Organization not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Organization Not Found",
        )

    # Protect owner removal
    if user_id == org.owner_id:
        if actor.id == org.owner_id:
            raise AppException(
                code="CANNOT_REMOVE_LAST_OWNER",
                message="Cannot remove organization owner. Transfer ownership before leaving.",
                status_code=status.HTTP_400_BAD_REQUEST,
                title="Cannot Remove Owner",
            )
        else:
            raise AppException(
                code="CANNOT_REMOVE_OWNER",
                message="Cannot remove the organization owner.",
                status_code=status.HTTP_403_FORBIDDEN if not is_admin_plane else status.HTTP_400_BAD_REQUEST,
                title="Cannot Remove Owner",
            )

    stmt = select(OrganizationMembership).where(
        OrganizationMembership.organization_id == org_id,
        OrganizationMembership.user_id == user_id,
    )
    membership = (await db.execute(stmt)).scalar_one_or_none()
    if not membership:
        raise AppException(
            code="MEMBERSHIP_NOT_FOUND",
            message="Member not found in this organization.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Membership Not Found",
        )

    await record_audit_event(
        db=db,
        action="org_member_removed",
        resource_type="organization_membership",
        resource_id=str(membership.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.platform_role.value if actor.platform_role else "org_admin",
        organization_id=org_id,
        reason=f"Removed user {user_id} from organization",
        diff_payload={"user_id": str(user_id), "role": membership.role.value},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    await db.delete(membership)
    await db.commit()


async def update_tenant_organization_profile(
    db: AsyncSession,
    org_id: uuid.UUID,
    data: TenantUpdateOrganizationRequest,
    actor: User,
    ip_address: str,
    user_agent: str,
    current_user_role: OrgRole,
    correlation_id: Optional[uuid.UUID] = None,
) -> OrganizationProfileResponse:
    """Updates display name or settings from tenant plane."""
    stmt = select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
    org = (await db.execute(stmt)).scalar_one_or_none()
    if not org:
        raise AppException(
            code="ORGANIZATION_NOT_FOUND",
            message="Organization not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Organization Not Found",
        )

    diff: Dict[str, Any] = {}
    if data.name is not None and data.name != org.name:
        diff["name"] = {"old": org.name, "new": data.name}
        org.name = data.name

    if data.settings is not None:
        merged_settings = {**(org.settings or {}), **data.settings} if isinstance(org.settings, dict) else data.settings
        assert_settings_does_not_contain_credentials(merged_settings)
        diff["settings"] = {"old": org.settings, "new": merged_settings}
        org.settings = merged_settings

    await record_audit_event(
        db=db,
        action="org_profile_updated",
        resource_type="organization",
        resource_id=str(org_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=current_user_role.value,
        organization_id=org_id,
        reason="Organization profile updated by organization administrator",
        diff_payload=diff,
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    await db.commit()
    await db.refresh(org)

    return OrganizationProfileResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        status=org.status,
        owner_id=org.owner_id,
        settings=org.settings or {},
        current_user_role=current_user_role,
        created_at=org.created_at,
        updated_at=org.updated_at,
    )

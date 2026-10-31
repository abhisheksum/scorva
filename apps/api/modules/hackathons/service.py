from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple
import uuid
from fastapi import status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.core.exceptions import AppException
from apps.api.modules.audit.models import AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.integrations.service import assert_settings_does_not_contain_credentials
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.modules.hackathons.schemas import (
    AdminUpdateHackathonStatusRequest,
    CreateHackathonRequest,
    HackathonDetailResponse,
    OrganizationSummary,
    TenantUpdateHackathonStatusRequest,
    UpdateHackathonRequest,
    UserSummary,
)
from apps.api.modules.organizations.models import (
    OrgRole,
    Organization,
    OrganizationStatus,
)
from apps.api.modules.users.models import PlatformRole, User


def _build_detail_response(h: Hackathon) -> HackathonDetailResponse:
    """Helper formatting Hackathon ORM entity into typed response with relations."""
    org_summary = None
    if h.organization:
        org_summary = OrganizationSummary(
            id=h.organization.id,
            name=h.organization.name,
            slug=h.organization.slug,
        )
    user_summary = None
    if h.created_by:
        user_summary = UserSummary(
            id=h.created_by.id,
            email=h.created_by.email,
            full_name=h.created_by.full_name,
        )

    return HackathonDetailResponse(
        id=h.id,
        organization_id=h.organization_id,
        title=h.title,
        slug=h.slug,
        description=h.description,
        status=h.status,
        start_date=h.start_date,
        submission_deadline=h.submission_deadline,
        end_date=h.end_date,
        created_by_user_id=h.created_by_user_id,
        settings=h.settings or {},
        created_at=h.created_at,
        updated_at=h.updated_at,
        organization=org_summary,
        created_by=user_summary,
    )


# =====================================================================
# Tenant Plane Operations (/api/v1/organizations/{org_id}/hackathons)
# =====================================================================

async def list_tenant_hackathons(
    db: AsyncSession,
    org_id: uuid.UUID,
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    hackathon_status: Optional[HackathonStatus] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> Tuple[List[HackathonDetailResponse], int, int]:
    """Lists hackathons owned strictly by the authorized organization (§8.2)."""
    filters = [
        Hackathon.organization_id == org_id,
        Hackathon.deleted_at.is_(None),
    ]

    if search and search.strip():
        words = search.strip().split()
        for w in words:
            term = f"%{w}%"
            filters.append(or_(Hackathon.title.ilike(term), Hackathon.slug.ilike(term)))

    if hackathon_status:
        filters.append(Hackathon.status == hackathon_status)

    count_stmt = select(func.count(Hackathon.id)).where(*filters)
    total = (await db.execute(count_stmt)).scalar() or 0
    total_pages = math.ceil(total / limit) if total > 0 else 0

    stmt = (
        select(Hackathon)
        .options(
            selectinload(Hackathon.created_by),
            selectinload(Hackathon.organization),
        )
        .where(*filters)
    )

    if sort_by == "title":
        order_col = Hackathon.title.desc() if sort_order.lower() == "desc" else Hackathon.title.asc()
    elif sort_by == "start_date":
        order_col = Hackathon.start_date.desc() if sort_order.lower() == "desc" else Hackathon.start_date.asc()
    else:
        order_col = Hackathon.created_at.desc() if sort_order.lower() == "desc" else Hackathon.created_at.asc()

    stmt = stmt.order_by(order_col).offset((page - 1) * limit).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    items = [_build_detail_response(h) for h in rows]
    return items, total, total_pages


async def create_hackathon(
    db: AsyncSession,
    org_id: uuid.UUID,
    data: CreateHackathonRequest,
    actor: User,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[uuid.UUID] = None,
) -> HackathonDetailResponse:
    """Provisions a new draft hackathon under the authorized organization tenant (§6.2)."""
    # 1. Organization verification
    org_stmt = select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
    org = (await db.execute(org_stmt)).scalar_one_or_none()
    if not org:
        raise AppException(
            code="ORGANIZATION_NOT_FOUND",
            message="Organization not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Organization Not Found",
        )

    if org.status == OrganizationStatus.ARCHIVED:
        raise AppException(
            code="ORGANIZATION_ARCHIVED",
            message="Cannot create hackathon under an archived organization.",
            status_code=status.HTTP_403_FORBIDDEN,
            title="Organization Archived",
        )

    if org.status == OrganizationStatus.SUSPENDED:
        raise AppException(
            code="ORGANIZATION_SUSPENDED",
            message="Cannot create hackathon under a suspended organization.",
            status_code=status.HTTP_403_FORBIDDEN,
            title="Organization Suspended",
        )

    # 2. Timeline validation
    if not (data.start_date < data.submission_deadline <= data.end_date):
        raise AppException(
            code="INVALID_TIMELINE_DATES",
            message="Invalid timeline: start_date < submission_deadline <= end_date must hold.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Invalid Timeline Dates",
        )

    # 3. Slug uniqueness within this organization
    slug_stmt = select(Hackathon.id).where(
        Hackathon.organization_id == org_id,
        Hackathon.slug == data.slug,
        Hackathon.deleted_at.is_(None),
    )
    if (await db.execute(slug_stmt)).scalar_one_or_none():
        raise AppException(
            code="HACKATHON_SLUG_TAKEN",
            message=f"Hackathon slug '{data.slug}' is already taken within this organization.",
            status_code=status.HTTP_409_CONFLICT,
            title="Slug Conflict",
        )

    # 4. Quota check
    max_hackathons = (org.settings or {}).get("max_hackathons", 10)
    current_count_stmt = select(func.count(Hackathon.id)).where(
        Hackathon.organization_id == org_id,
        Hackathon.deleted_at.is_(None),
        Hackathon.status != HackathonStatus.ARCHIVED,
    )
    active_count = (await db.execute(current_count_stmt)).scalar() or 0
    if active_count >= max_hackathons:
        raise AppException(
            code="HACKATHON_QUOTA_EXCEEDED",
            message=f"Organization hackathon quota of {max_hackathons} has been reached.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Quota Exceeded",
        )

    hackathon_id = uuid.uuid4()
    h_settings = data.settings or {}
    assert_settings_does_not_contain_credentials(h_settings)
    hackathon = Hackathon(
        id=hackathon_id,
        organization_id=org_id,
        title=data.title,
        slug=data.slug,
        description=data.description,
        status=HackathonStatus.DRAFT,
        start_date=data.start_date,
        submission_deadline=data.submission_deadline,
        end_date=data.end_date,
        created_by_user_id=actor.id,
        settings=h_settings,
    )
    db.add(hackathon)

    await record_audit_event(
        db=db,
        action="hackathon_created",
        resource_type="hackathon",
        resource_id=str(hackathon_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.platform_role.value if actor.platform_role else "organizer",
        organization_id=org_id,
        reason=f"Draft hackathon '{data.title}' created",
        diff_payload={"title": data.title, "slug": data.slug, "status": "draft"},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppException(
            code="HACKATHON_SLUG_TAKEN",
            message=f"Hackathon slug '{data.slug}' conflict detected.",
            status_code=status.HTTP_409_CONFLICT,
            title="Slug Conflict",
        )

    return await get_hackathon_detail(db, org_id, hackathon_id)


async def get_hackathon_detail(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
) -> HackathonDetailResponse:
    """Retrieves hackathon detail strictly scoped to the specified organization (§8.2)."""
    stmt = (
        select(Hackathon)
        .options(
            selectinload(Hackathon.created_by),
            selectinload(Hackathon.organization),
        )
        .where(
            Hackathon.id == hackathon_id,
            Hackathon.organization_id == org_id,
            Hackathon.deleted_at.is_(None),
        )
    )
    hackathon = (await db.execute(stmt)).scalar_one_or_none()
    if not hackathon:
        raise AppException(
            code="HACKATHON_NOT_FOUND",
            message="Hackathon not found in this organization.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Hackathon Not Found",
        )
    return _build_detail_response(hackathon)


async def update_hackathon(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    data: UpdateHackathonRequest,
    actor: User,
    actor_role: OrgRole,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[uuid.UUID] = None,
) -> HackathonDetailResponse:
    """Updates hackathon metadata, timeline, or settings with strict immutability rules (§6.2)."""
    stmt = (
        select(Hackathon)
        .where(
            Hackathon.id == hackathon_id,
            Hackathon.organization_id == org_id,
            Hackathon.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    hackathon = (await db.execute(stmt)).scalar_one_or_none()
    if not hackathon:
        raise AppException(
            code="HACKATHON_NOT_FOUND",
            message="Hackathon not found in this organization.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Hackathon Not Found",
        )

    # 1. State lifecycle block
    if hackathon.status == HackathonStatus.ARCHIVED:
        raise AppException(
            code="HACKATHON_ARCHIVED",
            message="Archived hackathons cannot be modified.",
            status_code=status.HTTP_403_FORBIDDEN,
            title="Hackathon Archived",
        )

    if hackathon.status == HackathonStatus.SUSPENDED:
        raise AppException(
            code="HACKATHON_SUSPENDED",
            message="Suspended hackathons cannot be modified.",
            status_code=status.HTTP_403_FORBIDDEN,
            title="Hackathon Suspended",
        )

    # 2. Organizer role permission check: can only edit own created hackathon (Table 5.2)
    if actor_role == OrgRole.ORGANIZER and hackathon.created_by_user_id != actor.id:
        raise AppException(
            code="FORBIDDEN_INSUFFICIENT_ORG_ROLE",
            message="Organizers can only edit hackathons they created.",
            status_code=status.HTTP_403_FORBIDDEN,
            title="Insufficient Permissions",
        )

    diff: Dict[str, Any] = {}

    # 3. Slug immutability once published or completed
    if data.slug is not None and data.slug != hackathon.slug:
        if hackathon.status in (HackathonStatus.PUBLISHED, HackathonStatus.COMPLETED):
            raise AppException(
                code="PUBLISHED_SLUG_IMMUTABLE",
                message="Cannot change the slug of a published or completed hackathon.",
                status_code=status.HTTP_400_BAD_REQUEST,
                title="Slug Immutable",
            )
        # Check uniqueness in org
        slug_stmt = select(Hackathon.id).where(
            Hackathon.organization_id == org_id,
            Hackathon.slug == data.slug,
            Hackathon.id != hackathon_id,
            Hackathon.deleted_at.is_(None),
        )
        if (await db.execute(slug_stmt)).scalar_one_or_none():
            raise AppException(
                code="HACKATHON_SLUG_TAKEN",
                message=f"Hackathon slug '{data.slug}' is already in use within this organization.",
                status_code=status.HTTP_409_CONFLICT,
                title="Slug Conflict",
            )
        diff["slug"] = {"old": hackathon.slug, "new": data.slug}
        hackathon.slug = data.slug

    # 4. Timeline validation (evaluating the complete resulting timeline)
    new_start = data.start_date if data.start_date is not None else hackathon.start_date
    new_sub = data.submission_deadline if data.submission_deadline is not None else hackathon.submission_deadline
    new_end = data.end_date if data.end_date is not None else hackathon.end_date

    if data.start_date is not None or data.submission_deadline is not None or data.end_date is not None:
        if not (new_start < new_sub <= new_end):
            raise AppException(
                code="INVALID_TIMELINE_DATES",
                message="Invalid timeline: start_date < submission_deadline <= end_date must hold.",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                title="Invalid Timeline Dates",
            )
        if data.start_date is not None and data.start_date != hackathon.start_date:
            diff["start_date"] = {"old": hackathon.start_date.isoformat(), "new": data.start_date.isoformat()}
            hackathon.start_date = data.start_date
        if data.submission_deadline is not None and data.submission_deadline != hackathon.submission_deadline:
            diff["submission_deadline"] = {"old": hackathon.submission_deadline.isoformat(), "new": data.submission_deadline.isoformat()}
            hackathon.submission_deadline = data.submission_deadline
        if data.end_date is not None and data.end_date != hackathon.end_date:
            diff["end_date"] = {"old": hackathon.end_date.isoformat(), "new": data.end_date.isoformat()}
            hackathon.end_date = data.end_date

    if data.title is not None and data.title != hackathon.title:
        diff["title"] = {"old": hackathon.title, "new": data.title}
        hackathon.title = data.title

    if data.description is not None and data.description != hackathon.description:
        diff["description"] = "updated"
        hackathon.description = data.description

    if data.settings is not None:
        merged = dict(hackathon.settings or {})
        merged.update(data.settings)
        assert_settings_does_not_contain_credentials(merged)
        diff["settings"] = {"old": hackathon.settings, "new": merged}
        hackathon.settings = merged

    await record_audit_event(
        db=db,
        action="hackathon_updated",
        resource_type="hackathon",
        resource_id=str(hackathon_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor_role.value,
        organization_id=org_id,
        reason="Hackathon details updated",
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
            code="HACKATHON_SLUG_TAKEN",
            message="Hackathon update violated database constraints.",
            status_code=status.HTTP_409_CONFLICT,
            title="Update Conflict",
        )

    return await get_hackathon_detail(db, org_id, hackathon_id)


async def publish_hackathon(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    actor: User,
    actor_role: OrgRole,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[uuid.UUID] = None,
) -> HackathonDetailResponse:
    """Transitions a hackathon from DRAFT to PUBLISHED with prerequisite checks (§6.2)."""
    # 1. Organization active verification
    org_stmt = select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
    org = (await db.execute(org_stmt)).scalar_one_or_none()
    if not org or org.status != OrganizationStatus.ACTIVE:
        raise AppException(
            code="ORGANIZATION_NOT_ACTIVE",
            message="Cannot publish hackathon unless organization is active.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Organization Not Active",
        )

    stmt = (
        select(Hackathon)
        .where(
            Hackathon.id == hackathon_id,
            Hackathon.organization_id == org_id,
            Hackathon.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    hackathon = (await db.execute(stmt)).scalar_one_or_none()
    if not hackathon:
        raise AppException(
            code="HACKATHON_NOT_FOUND",
            message="Hackathon not found in this organization.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Hackathon Not Found",
        )

    # 2. State machine transition check
    if hackathon.status == HackathonStatus.PUBLISHED:
        raise AppException(
            code="ALREADY_IN_STATE",
            message="Hackathon is already published.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Already Published",
        )

    if hackathon.status == HackathonStatus.ARCHIVED:
        raise AppException(
            code="HACKATHON_ARCHIVED",
            message="Archived hackathons cannot be published.",
            status_code=status.HTTP_403_FORBIDDEN,
            title="Hackathon Archived",
        )

    if hackathon.status != HackathonStatus.DRAFT:
        raise AppException(
            code="INVALID_STATUS_TRANSITION",
            message=f"Cannot publish hackathon currently in '{hackathon.status.value}' state. Must be in 'draft'.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid Status Transition",
        )

    # 3. Content prerequisites
    if not hackathon.title or not hackathon.title.strip():
        raise AppException(
            code="PUBLISH_PREREQUISITES_NOT_MET",
            message="Hackathon title must not be empty.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Prerequisites Not Met",
        )

    if not hackathon.description or not hackathon.description.strip():
        raise AppException(
            code="PUBLISH_PREREQUISITES_NOT_MET",
            message="Hackathon description must not be empty before publishing.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Prerequisites Not Met",
        )

    # 4. End date must be in the future
    now_utc = datetime.now(timezone.utc)
    if hackathon.end_date <= now_utc:
        raise AppException(
            code="PUBLISH_PREREQUISITES_NOT_MET",
            message="Cannot publish a hackathon whose end date is in the past.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Prerequisites Not Met",
        )

    old_status = hackathon.status
    hackathon.status = HackathonStatus.PUBLISHED
    new_settings = dict(hackathon.settings or {})
    new_settings["published_at"] = now_utc.isoformat()
    hackathon.settings = new_settings

    await record_audit_event(
        db=db,
        action="hackathon_published",
        resource_type="hackathon",
        resource_id=str(hackathon_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor_role.value,
        organization_id=org_id,
        reason="Hackathon published and open for participants",
        diff_payload={"old_status": old_status.value, "new_status": HackathonStatus.PUBLISHED.value},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    await db.commit()
    return await get_hackathon_detail(db, org_id, hackathon_id)


async def complete_hackathon(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    actor: User,
    actor_role: OrgRole,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[uuid.UUID] = None,
) -> HackathonDetailResponse:
    """Transitions an active hackathon to COMPLETED status (§6.1)."""
    stmt = (
        select(Hackathon)
        .where(
            Hackathon.id == hackathon_id,
            Hackathon.organization_id == org_id,
            Hackathon.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    hackathon = (await db.execute(stmt)).scalar_one_or_none()
    if not hackathon:
        raise AppException(
            code="HACKATHON_NOT_FOUND",
            message="Hackathon not found in this organization.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Hackathon Not Found",
        )

    if hackathon.status == HackathonStatus.COMPLETED:
        raise AppException(
            code="ALREADY_IN_STATE",
            message="Hackathon is already completed.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Already Completed",
        )

    if hackathon.status != HackathonStatus.PUBLISHED:
        raise AppException(
            code="INVALID_STATUS_TRANSITION",
            message=f"Cannot complete hackathon in '{hackathon.status.value}' state. Must be 'published'.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid Status Transition",
        )

    old_status = hackathon.status
    hackathon.status = HackathonStatus.COMPLETED
    new_settings = dict(hackathon.settings or {})
    new_settings["completed_at"] = datetime.now(timezone.utc).isoformat()
    hackathon.settings = new_settings

    await record_audit_event(
        db=db,
        action="hackathon_completed",
        resource_type="hackathon",
        resource_id=str(hackathon_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor_role.value,
        organization_id=org_id,
        reason="Hackathon finalized and marked completed",
        diff_payload={"old_status": old_status.value, "new_status": HackathonStatus.COMPLETED.value},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    await db.commit()
    return await get_hackathon_detail(db, org_id, hackathon_id)


async def archive_hackathon(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    actor: User,
    actor_role: OrgRole,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[uuid.UUID] = None,
) -> HackathonDetailResponse:
    """Archives a draft (cancelled) or completed hackathon (§6.1)."""
    stmt = (
        select(Hackathon)
        .where(
            Hackathon.id == hackathon_id,
            Hackathon.organization_id == org_id,
            Hackathon.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    hackathon = (await db.execute(stmt)).scalar_one_or_none()
    if not hackathon:
        raise AppException(
            code="HACKATHON_NOT_FOUND",
            message="Hackathon not found in this organization.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Hackathon Not Found",
        )

    if hackathon.status == HackathonStatus.ARCHIVED:
        raise AppException(
            code="ALREADY_IN_STATE",
            message="Hackathon is already archived.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Already Archived",
        )

    if hackathon.status not in (HackathonStatus.DRAFT, HackathonStatus.COMPLETED):
        raise AppException(
            code="INVALID_STATUS_TRANSITION",
            message=f"Cannot archive hackathon currently in '{hackathon.status.value}' state. Must be 'draft' or 'completed'.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid Status Transition",
        )

    old_status = hackathon.status
    hackathon.status = HackathonStatus.ARCHIVED

    await record_audit_event(
        db=db,
        action="hackathon_archived",
        resource_type="hackathon",
        resource_id=str(hackathon_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor_role.value,
        organization_id=org_id,
        reason="Hackathon archived",
        diff_payload={"old_status": old_status.value, "new_status": HackathonStatus.ARCHIVED.value},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    await db.commit()
    return await get_hackathon_detail(db, org_id, hackathon_id)


async def tenant_update_hackathon_status(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    data: TenantUpdateHackathonStatusRequest,
    actor: User,
    actor_role: OrgRole,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[uuid.UUID] = None,
) -> HackathonDetailResponse:
    """Allows ORG_OWNER to suspend or reinstate an organization hackathon (Table 5.2)."""
    if actor_role != OrgRole.ORG_OWNER:
        raise AppException(
            code="FORBIDDEN_INSUFFICIENT_ORG_ROLE",
            message="Only Organization Owner can suspend or reinstate hackathons on the tenant plane.",
            status_code=status.HTTP_403_FORBIDDEN,
            title="Insufficient Permissions",
        )

    stmt = (
        select(Hackathon)
        .where(
            Hackathon.id == hackathon_id,
            Hackathon.organization_id == org_id,
            Hackathon.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    hackathon = (await db.execute(stmt)).scalar_one_or_none()
    if not hackathon:
        raise AppException(
            code="HACKATHON_NOT_FOUND",
            message="Hackathon not found in this organization.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Hackathon Not Found",
        )

    target_status = data.status
    old_status = hackathon.status

    if target_status == old_status:
        raise AppException(
            code="ALREADY_IN_STATE",
            message=f"Hackathon is already in '{old_status.value}' state.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Already in State",
        )

    # Tenant status update rules:
    # 1. Suspend: requires non-empty reason
    if target_status == HackathonStatus.SUSPENDED:
        if not data.reason or not data.reason.strip():
            raise AppException(
                code="REASON_REQUIRED",
                message="A non-empty reason is required when suspending a hackathon.",
                status_code=status.HTTP_400_BAD_REQUEST,
                title="Reason Required",
            )
        if old_status not in (HackathonStatus.DRAFT, HackathonStatus.PUBLISHED):
            raise AppException(
                code="INVALID_STATUS_TRANSITION",
                message=f"Cannot suspend hackathon from '{old_status.value}' state.",
                status_code=status.HTTP_400_BAD_REQUEST,
                title="Invalid Transition",
            )
    elif target_status in (HackathonStatus.PUBLISHED, HackathonStatus.DRAFT):
        # Reinstating from suspended
        if old_status != HackathonStatus.SUSPENDED:
            raise AppException(
                code="INVALID_STATUS_TRANSITION",
                message=f"Cannot transition to '{target_status.value}' via status override. Use designated endpoints.",
                status_code=status.HTTP_400_BAD_REQUEST,
                title="Invalid Transition",
            )
    else:
        raise AppException(
            code="INVALID_STATUS_TRANSITION",
            message=f"Unsupported status transition to '{target_status.value}'.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid Transition",
        )

    hackathon.status = target_status
    reason_str = data.reason.strip() if data.reason else f"Status changed from {old_status.value} to {target_status.value}"

    await record_audit_event(
        db=db,
        action="hackathon_status_changed",
        resource_type="hackathon",
        resource_id=str(hackathon_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor_role.value,
        organization_id=org_id,
        reason=reason_str,
        diff_payload={"old_status": old_status.value, "new_status": target_status.value},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    await db.commit()
    return await get_hackathon_detail(db, org_id, hackathon_id)


# =====================================================================
# Platform Admin Plane Operations (/api/v1/admin/hackathons)
# =====================================================================

async def list_admin_hackathons(
    db: AsyncSession,
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    hackathon_status: Optional[HackathonStatus] = None,
    org_id: Optional[uuid.UUID] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> Tuple[List[HackathonDetailResponse], int, int]:
    """Cross-tenant hackathon directory with search and filtering for platform admins (§8.1)."""
    filters = [Hackathon.deleted_at.is_(None)]

    if search and search.strip():
        words = search.strip().split()
        for w in words:
            term = f"%{w}%"
            filters.append(or_(Hackathon.title.ilike(term), Hackathon.slug.ilike(term)))

    if hackathon_status:
        filters.append(Hackathon.status == hackathon_status)

    if org_id:
        filters.append(Hackathon.organization_id == org_id)

    count_stmt = select(func.count(Hackathon.id)).where(*filters)
    total = (await db.execute(count_stmt)).scalar() or 0
    total_pages = math.ceil(total / limit) if total > 0 else 0

    stmt = (
        select(Hackathon)
        .options(
            selectinload(Hackathon.created_by),
            selectinload(Hackathon.organization),
        )
        .where(*filters)
    )

    if sort_by == "title":
        order_col = Hackathon.title.desc() if sort_order.lower() == "desc" else Hackathon.title.asc()
    elif sort_by == "start_date":
        order_col = Hackathon.start_date.desc() if sort_order.lower() == "desc" else Hackathon.start_date.asc()
    else:
        order_col = Hackathon.created_at.desc() if sort_order.lower() == "desc" else Hackathon.created_at.asc()

    stmt = stmt.order_by(order_col).offset((page - 1) * limit).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    items = [_build_detail_response(h) for h in rows]
    return items, total, total_pages


async def get_admin_hackathon_detail(
    db: AsyncSession,
    hackathon_id: uuid.UUID,
) -> HackathonDetailResponse:
    """Retrieves full hackathon details across tenants for authorized platform admins (§8.1)."""
    stmt = (
        select(Hackathon)
        .options(
            selectinload(Hackathon.created_by),
            selectinload(Hackathon.organization),
        )
        .where(Hackathon.id == hackathon_id, Hackathon.deleted_at.is_(None))
    )
    hackathon = (await db.execute(stmt)).scalar_one_or_none()
    if not hackathon:
        raise AppException(
            code="HACKATHON_NOT_FOUND",
            message="Hackathon not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Hackathon Not Found",
        )
    return _build_detail_response(hackathon)


async def override_admin_hackathon_status(
    db: AsyncSession,
    hackathon_id: uuid.UUID,
    data: AdminUpdateHackathonStatusRequest,
    actor: User,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[uuid.UUID] = None,
) -> HackathonDetailResponse:
    """
    Administrative status override for hackathons (§8.1).
    Enforces Table 5.2 role restrictions:
    - Suspend Hackathon: PLATFORM_OWNER or PLATFORM_OPS_ADMIN.
    - Archive Hackathon: PLATFORM_OWNER only.
    Mandatory reason required and recorded in append-only audit trail.
    """
    stmt = (
        select(Hackathon)
        .where(Hackathon.id == hackathon_id, Hackathon.deleted_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    hackathon = (await db.execute(stmt)).scalar_one_or_none()
    if not hackathon:
        raise AppException(
            code="HACKATHON_NOT_FOUND",
            message="Hackathon not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Hackathon Not Found",
        )

    target_status = data.status
    old_status = hackathon.status

    if target_status == old_status:
        raise AppException(
            code="ALREADY_IN_STATE",
            message=f"Hackathon is already in '{old_status.value}' state.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Already in State",
        )

    # 1. Least privilege check (Table 5.2): Archive Hackathon is PLATFORM_OWNER only
    if target_status == HackathonStatus.ARCHIVED:
        user_role = (
            actor.platform_role.value
            if isinstance(actor.platform_role, PlatformRole)
            else str(actor.platform_role)
            if actor.platform_role
            else None
        )
        if user_role != PlatformRole.PLATFORM_OWNER.value:
            raise AppException(
                code="FORBIDDEN_INSUFFICIENT_ROLE",
                message="Only Platform Owner can archive a hackathon via administrative override.",
                status_code=status.HTTP_403_FORBIDDEN,
                title="Insufficient Permissions",
            )

    # 2. Transition rules
    if target_status == HackathonStatus.SUSPENDED:
        if old_status == HackathonStatus.ARCHIVED:
            raise AppException(
                code="INVALID_STATUS_TRANSITION",
                message="Cannot suspend an archived hackathon.",
                status_code=status.HTTP_400_BAD_REQUEST,
                title="Invalid Transition",
            )
    elif target_status in (HackathonStatus.PUBLISHED, HackathonStatus.DRAFT):
        if old_status != HackathonStatus.SUSPENDED:
            raise AppException(
                code="INVALID_STATUS_TRANSITION",
                message=f"Cannot transition to '{target_status.value}' via administrative status override unless currently suspended.",
                status_code=status.HTTP_400_BAD_REQUEST,
                title="Invalid Transition",
            )
    elif target_status == HackathonStatus.COMPLETED:
        if old_status != HackathonStatus.PUBLISHED:
            raise AppException(
                code="INVALID_STATUS_TRANSITION",
                message="Can only complete a published hackathon.",
                status_code=status.HTTP_400_BAD_REQUEST,
                title="Invalid Transition",
            )

    hackathon.status = target_status
    reason_str = data.reason.strip()

    await record_audit_event(
        db=db,
        action="hackathon_status_overridden",
        resource_type="hackathon",
        resource_id=str(hackathon.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.platform_role.value if actor.platform_role else "platform_admin",
        organization_id=hackathon.organization_id,
        reason=reason_str,
        diff_payload={"old_status": old_status.value, "new_status": target_status.value},
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    await db.commit()
    return await get_admin_hackathon_detail(db, hackathon_id)


async def publish_hackathon_results(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    actor: User,
    actor_role: OrgRole,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[uuid.UUID] = None,
) -> HackathonDetailResponse:
    """Publishes evaluation results and releases official leaderboard for participants (§6.5)."""
    stmt = (
        select(Hackathon)
        .where(
            Hackathon.id == hackathon_id,
            Hackathon.organization_id == org_id,
            Hackathon.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    hackathon = (await db.execute(stmt)).scalar_one_or_none()
    if not hackathon:
        raise AppException(
            code="HACKATHON_NOT_FOUND",
            message="Hackathon not found in this organization.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Hackathon Not Found",
        )

    if hackathon.status not in (HackathonStatus.PUBLISHED, HackathonStatus.COMPLETED):
        raise AppException(
            code="INVALID_STATUS_FOR_PUBLICATION",
            message="Results can only be published for active published or completed hackathons.",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid Status for Publication",
        )

    new_settings = dict(hackathon.settings or {})
    new_settings["results_published"] = True
    new_settings["results_published_at"] = datetime.now(timezone.utc).isoformat()
    hackathon.settings = new_settings

    await record_audit_event(
        db=db,
        action="hackathon_results_published",
        resource_type="hackathon",
        resource_id=str(hackathon_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor_role.value,
        organization_id=org_id,
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
        diff_payload={"hackathon_title": hackathon.title, "results_published": True},
    )

    await db.commit()
    return await get_hackathon_detail(db, org_id, hackathon_id)


async def unpublish_hackathon_results(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    actor: User,
    actor_role: OrgRole,
    ip_address: str,
    user_agent: str,
    correlation_id: Optional[uuid.UUID] = None,
) -> HackathonDetailResponse:
    """Unpublishes evaluation results and conceals leaderboard from participants."""
    stmt = (
        select(Hackathon)
        .where(
            Hackathon.id == hackathon_id,
            Hackathon.organization_id == org_id,
            Hackathon.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    hackathon = (await db.execute(stmt)).scalar_one_or_none()
    if not hackathon:
        raise AppException(
            code="HACKATHON_NOT_FOUND",
            message="Hackathon not found in this organization.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Hackathon Not Found",
        )

    new_settings = dict(hackathon.settings or {})
    new_settings["results_published"] = False
    hackathon.settings = new_settings

    await record_audit_event(
        db=db,
        action="hackathon_results_unpublished",
        resource_type="hackathon",
        resource_id=str(hackathon_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor_role.value,
        organization_id=org_id,
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
        diff_payload={"hackathon_title": hackathon.title, "results_published": False},
    )

    await db.commit()
    return await get_hackathon_detail(db, org_id, hackathon_id)


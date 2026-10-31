from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_db_session
from apps.api.dependencies import require_platform_owner, require_super_admin
from apps.api.modules.organizations.models import OrganizationStatus
from apps.api.modules.organizations.schemas import (
    AdminAddMemberRequest,
    AdminUpdateOrganizationRequest,
    CreateOrganizationRequest,
    MemberOperationResponse,
    OrganizationDetailResponse,
    OrganizationMemberResponse,
    PaginatedOrganizationsResponse,
    TransferOwnershipRequest,
    UpdateMemberRoleRequest,
    UpdateOrganizationStatusRequest,
)
from apps.api.modules.organizations.service import (
    add_organization_member,
    change_organization_status,
    create_organization,
    get_organization_detail,
    list_admin_organizations,
    list_organization_members,
    remove_organization_member,
    transfer_organization_ownership,
    update_organization_admin,
    update_organization_member_role,
)
from apps.api.modules.users.models import User

router = APIRouter(prefix="/admin/organizations", tags=["Admin - Organizations"])


def _extract_telemetry(request: Request):
    ip_address = getattr(request.state, "client_ip", request.client.host if request.client else "127.0.0.1")
    user_agent = request.headers.get("user-agent", "Unknown")
    correlation_id = getattr(request.state, "correlation_id", None)
    return ip_address, user_agent, correlation_id


@router.get("", response_model=PaginatedOrganizationsResponse)
@router.get("/", response_model=PaginatedOrganizationsResponse, include_in_schema=False)
async def get_organizations(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search term for name or slug"),
    status: Optional[OrganizationStatus] = Query(None, description="Filter by status"),
    sort_by: str = Query("created_at", description="Sort field ('created_at', 'name')"),
    sort_order: str = Query("desc", description="Sort order ('asc', 'desc')"),
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Lists all platform organizations with pagination, search, and status filters."""
    items, total, total_pages = await list_admin_organizations(
        db=db,
        page=page,
        limit=limit,
        search=search,
        org_status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedOrganizationsResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


@router.post("", response_model=OrganizationDetailResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=OrganizationDetailResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def post_create_organization(
    data: CreateOrganizationRequest,
    request: Request,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Provisions a new tenant organization with an initial owner."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await create_organization(
        db=db,
        data=data,
        actor=current_admin,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.get("/{org_id}", response_model=OrganizationDetailResponse)
async def get_organization(
    org_id: uuid.UUID,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieves detailed organization metadata, owner info, and resource counts."""
    return await get_organization_detail(db, org_id)


@router.patch("/{org_id}", response_model=OrganizationDetailResponse)
async def patch_update_organization(
    org_id: uuid.UUID,
    data: AdminUpdateOrganizationRequest,
    request: Request,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Updates organization name, slug, or settings via platform administration."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await update_organization_admin(
        db=db,
        org_id=org_id,
        data=data,
        actor=current_admin,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.post("/{org_id}/status", response_model=OrganizationDetailResponse)
async def post_update_organization_status(
    org_id: uuid.UUID,
    data: UpdateOrganizationStatusRequest,
    request: Request,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Suspends, reactivates, or archives an organization tenant."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await change_organization_status(
        db=db,
        org_id=org_id,
        data=data,
        actor=current_admin,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.post("/{org_id}/transfer-ownership", response_model=OrganizationDetailResponse)
async def post_transfer_organization_ownership(
    org_id: uuid.UUID,
    data: TransferOwnershipRequest,
    request: Request,
    current_admin: User = Depends(require_platform_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Transfers ownership of an organization to another active member."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await transfer_organization_ownership(
        db=db,
        org_id=org_id,
        data=data,
        actor=current_admin,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.get("/{org_id}/members", response_model=List[OrganizationMemberResponse])
async def get_organization_members(
    org_id: uuid.UUID,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Lists all members of an organization with role and status scoping."""
    return await list_organization_members(db, org_id)


@router.post("/{org_id}/members", response_model=OrganizationMemberResponse, status_code=status.HTTP_201_CREATED)
async def post_add_organization_member(
    org_id: uuid.UUID,
    data: AdminAddMemberRequest,
    request: Request,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Adds a user to an organization's membership roster."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await add_organization_member(
        db=db,
        org_id=org_id,
        user_id=data.user_id,
        email=data.email,
        role=data.role,
        actor=current_admin,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
        audit_action="org_member_added",
        full_name=data.full_name,
        password=data.password,
    )


@router.patch("/{org_id}/members/{user_id}", response_model=OrganizationMemberResponse)
async def patch_update_organization_member_role(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    data: UpdateMemberRoleRequest,
    request: Request,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Updates member role within an organization."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await update_organization_member_role(
        db=db,
        org_id=org_id,
        user_id=user_id,
        new_role=data.role,
        actor=current_admin,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
        audit_action="org_member_role_updated",
    )


@router.delete("/{org_id}/members/{user_id}", response_model=MemberOperationResponse)
async def delete_organization_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Removes a user from an organization's membership roster."""
    ip, ua, corr_id = _extract_telemetry(request)
    await remove_organization_member(
        db=db,
        org_id=org_id,
        user_id=user_id,
        actor=current_admin,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
        is_admin_plane=True,
    )
    return MemberOperationResponse(status="success", message="Member removed successfully.")

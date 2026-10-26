from typing import List
import uuid
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_db_session
from apps.api.core.exceptions import AppException
from apps.api.dependencies import (
    TenantContext,
    require_org_admin,
    require_org_member,
    require_org_owner,
)
from apps.api.modules.organizations.models import OrgRole
from apps.api.modules.organizations.schemas import (
    InviteMemberRequest,
    MemberOperationResponse,
    OrganizationMemberResponse,
    OrganizationProfileResponse,
    TenantUpdateOrganizationRequest,
    TransferOwnershipRequest,
    UpdateMemberRoleRequest,
)
from apps.api.modules.organizations.service import (
    add_organization_member,
    list_organization_members,
    remove_organization_member,
    transfer_organization_ownership,
    update_organization_member_role,
    update_tenant_organization_profile,
)

router = APIRouter(prefix="/organizations/{org_id}", tags=["Organizations"])


def _extract_telemetry(request: Request):
    ip_address = getattr(request.state, "client_ip", request.client.host if request.client else "127.0.0.1")
    user_agent = request.headers.get("user-agent", "Unknown")
    correlation_id = getattr(request.state, "correlation_id", None)
    return ip_address, user_agent, correlation_id


@router.get("", response_model=OrganizationProfileResponse)
@router.get("/", response_model=OrganizationProfileResponse, include_in_schema=False)
async def get_organization_profile(
    tenant: TenantContext = Depends(require_org_member),
):
    """Retrieves organization profile metadata for an authorized organization member."""
    org = tenant.organization
    return OrganizationProfileResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        status=org.status,
        owner_id=org.owner_id,
        settings=org.settings or {},
        current_user_role=tenant.role,
        created_at=org.created_at,
        updated_at=org.updated_at,
    )


@router.patch("", response_model=OrganizationProfileResponse)
@router.patch("/", response_model=OrganizationProfileResponse, include_in_schema=False)
async def patch_organization_profile(
    data: TenantUpdateOrganizationRequest,
    request: Request,
    tenant: TenantContext = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Updates display name or settings for the organization (ORG_ADMIN or ORG_OWNER required)."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await update_tenant_organization_profile(
        db=db,
        org_id=tenant.organization.id,
        data=data,
        actor=tenant.user,
        ip_address=ip,
        user_agent=ua,
        current_user_role=tenant.role,
        correlation_id=corr_id,
    )


@router.get("/members", response_model=List[OrganizationMemberResponse])
async def get_tenant_members(
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Lists all members of the organization roster (ORGANIZER+)."""
    return await list_organization_members(db, tenant.organization.id)


@router.post("/members", response_model=OrganizationMemberResponse, status_code=status.HTTP_201_CREATED)
async def post_invite_member(
    data: InviteMemberRequest,
    request: Request,
    tenant: TenantContext = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Invites / adds a member to the organization roster (ORG_ADMIN+)."""
    # 1. Role hierarchy check: only owner can add admin; nobody can add owner directly
    if data.role == OrgRole.ORG_OWNER:
        raise AppException(
            code="FORBIDDEN_INSUFFICIENT_ORG_ROLE",
            message="Cannot assign owner role when adding members. Use transfer-ownership.",
            status_code=status.HTTP_403_FORBIDDEN,
            title="Cannot Assign Owner Role",
        )

    if tenant.role == OrgRole.ORG_ADMIN and data.role == OrgRole.ORG_ADMIN:
        raise AppException(
            code="FORBIDDEN_INSUFFICIENT_ORG_ROLE",
            message="Only organization owner can add organization administrators.",
            status_code=status.HTTP_403_FORBIDDEN,
            title="Insufficient Permissions",
        )

    ip, ua, corr_id = _extract_telemetry(request)
    return await add_organization_member(
        db=db,
        org_id=tenant.organization.id,
        user_id=None,
        email=data.email,
        role=data.role,
        actor=tenant.user,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
        audit_action="org_member_invited",
    )


@router.patch("/members/{user_id}", response_model=OrganizationMemberResponse)
async def patch_modify_member_role(
    user_id: uuid.UUID,
    data: UpdateMemberRoleRequest,
    request: Request,
    tenant: TenantContext = Depends(require_org_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Modifies a member's role (ORG_OWNER only)."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await update_organization_member_role(
        db=db,
        org_id=tenant.organization.id,
        user_id=user_id,
        new_role=data.role,
        actor=tenant.user,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
        audit_action="org_member_role_changed",
    )


@router.delete("/members/{user_id}", response_model=MemberOperationResponse)
async def delete_tenant_member(
    user_id: uuid.UUID,
    request: Request,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Removes a member from the organization roster.
    Permission rules:
    - ORGANIZER: Denied (403 FORBIDDEN_INSUFFICIENT_ORG_ROLE)
    - ORG_ADMIN: Can only remove ORGANIZERs (cannot remove admins or owner)
    - ORG_OWNER: Can remove anyone except self
    """
    # 1. Organizer check
    if tenant.role == OrgRole.ORGANIZER:
        raise AppException(
            code="FORBIDDEN_INSUFFICIENT_ORG_ROLE",
            message="Organizers cannot remove members.",
            status_code=status.HTTP_403_FORBIDDEN,
            title="Insufficient Permissions",
        )

    # 2. Owner self-removal check
    if user_id == tenant.organization.owner_id:
        if tenant.user.id == tenant.organization.owner_id:
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
                status_code=status.HTTP_403_FORBIDDEN,
                title="Cannot Remove Owner",
            )

    # 3. Org Admin cannot remove other Org Admins
    if tenant.role == OrgRole.ORG_ADMIN:
        # Check target user's role
        from sqlalchemy import select
        from apps.api.modules.organizations.models import OrganizationMembership
        target_mem_stmt = select(OrganizationMembership).where(
            OrganizationMembership.organization_id == tenant.organization.id,
            OrganizationMembership.user_id == user_id,
        )
        target_mem = (await db.execute(target_mem_stmt)).scalar_one_or_none()
        if not target_mem:
            raise AppException(
                code="MEMBERSHIP_NOT_FOUND",
                message="Member not found in this organization.",
                status_code=status.HTTP_404_NOT_FOUND,
                title="Member Not Found",
            )
        if target_mem.role != OrgRole.ORGANIZER:
            raise AppException(
                code="FORBIDDEN_INSUFFICIENT_ORG_ROLE",
                message="Organization administrators can only remove organizers.",
                status_code=status.HTTP_403_FORBIDDEN,
                title="Insufficient Permissions",
            )

    ip, ua, corr_id = _extract_telemetry(request)
    await remove_organization_member(
        db=db,
        org_id=tenant.organization.id,
        user_id=user_id,
        actor=tenant.user,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
        is_admin_plane=False,
    )
    return MemberOperationResponse(status="success", message="Member removed successfully.")


@router.post("/transfer-ownership", response_model=OrganizationProfileResponse)
async def post_transfer_ownership_tenant(
    data: TransferOwnershipRequest,
    request: Request,
    tenant: TenantContext = Depends(require_org_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Transfers organization ownership to another active member (ORG_OWNER only)."""
    ip, ua, corr_id = _extract_telemetry(request)
    detail = await transfer_organization_ownership(
        db=db,
        org_id=tenant.organization.id,
        data=data,
        actor=tenant.user,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )
    return OrganizationProfileResponse(
        id=detail.id,
        name=detail.name,
        slug=detail.slug,
        status=detail.status,
        owner_id=detail.owner_id,
        settings=detail.settings,
        current_user_role=OrgRole.ORG_ADMIN,  # Previous owner is now org_admin
        created_at=detail.created_at,
        updated_at=detail.updated_at,
    )

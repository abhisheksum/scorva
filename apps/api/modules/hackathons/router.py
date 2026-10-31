from typing import Optional
import uuid
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_db_session
from apps.api.dependencies import (
    TenantContext,
    require_org_admin,
    require_org_member,
    require_org_owner,
)
from apps.api.modules.hackathons.models import HackathonStatus
from apps.api.modules.hackathons.schemas import (
    CreateHackathonRequest,
    HackathonDetailResponse,
    PaginatedHackathonsResponse,
    TenantUpdateHackathonStatusRequest,
    UpdateHackathonRequest,
)
from apps.api.modules.hackathons.service import (
    archive_hackathon,
    complete_hackathon,
    create_hackathon,
    get_hackathon_detail,
    list_tenant_hackathons,
    publish_hackathon,
    publish_hackathon_results,
    tenant_update_hackathon_status,
    unpublish_hackathon_results,
    update_hackathon,
)

router = APIRouter(prefix="/organizations/{org_id}/hackathons", tags=["Hackathons"])


def _extract_telemetry(request: Request):
    ip_address = getattr(request.state, "client_ip", request.client.host if request.client else "127.0.0.1")
    user_agent = request.headers.get("user-agent", "Unknown")
    correlation_id = getattr(request.state, "correlation_id", None)
    return ip_address, user_agent, correlation_id


@router.get("", response_model=PaginatedHackathonsResponse)
@router.get("/", response_model=PaginatedHackathonsResponse, include_in_schema=False)
async def get_hackathons(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search term for title or slug"),
    status: Optional[HackathonStatus] = Query(None, description="Filter by hackathon lifecycle status"),
    sort_by: str = Query("created_at", description="Sort field ('created_at', 'start_date', 'title')"),
    sort_order: str = Query("desc", description="Sort direction ('asc', 'desc')"),
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Lists hackathons owned strictly by the authorized organization (§8.2)."""
    items, total, total_pages = await list_tenant_hackathons(
        db=db,
        org_id=tenant.organization.id,
        page=page,
        limit=limit,
        search=search,
        hackathon_status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedHackathonsResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


@router.post("", response_model=HackathonDetailResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=HackathonDetailResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def post_create_hackathon(
    data: CreateHackathonRequest,
    request: Request,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Provisions a new draft hackathon under the authorized organization (§6.2)."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await create_hackathon(
        db=db,
        org_id=tenant.organization.id,
        data=data,
        actor=tenant.user,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.get("/{hackathon_id}", response_model=HackathonDetailResponse)
async def get_hackathon(
    hackathon_id: uuid.UUID,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieves full hackathon details scoped strictly to the authorized tenant."""
    return await get_hackathon_detail(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
    )


@router.patch("/{hackathon_id}", response_model=HackathonDetailResponse)
async def patch_update_hackathon(
    hackathon_id: uuid.UUID,
    data: UpdateHackathonRequest,
    request: Request,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Updates hackathon metadata, timeline, or settings with strict immutability checks."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await update_hackathon(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        data=data,
        actor=tenant.user,
        actor_role=tenant.role,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.post("/{hackathon_id}/publish", response_model=HackathonDetailResponse)
async def post_publish_hackathon(
    hackathon_id: uuid.UUID,
    request: Request,
    tenant: TenantContext = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Validates prerequisites and publishes a draft hackathon (ORG_ADMIN or ORG_OWNER required)."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await publish_hackathon(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        actor=tenant.user,
        actor_role=tenant.role,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.post("/{hackathon_id}/complete", response_model=HackathonDetailResponse)
async def post_complete_hackathon(
    hackathon_id: uuid.UUID,
    request: Request,
    tenant: TenantContext = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Finalizes an active hackathon and transitions to COMPLETED status."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await complete_hackathon(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        actor=tenant.user,
        actor_role=tenant.role,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.post("/{hackathon_id}/archive", response_model=HackathonDetailResponse)
async def post_archive_hackathon(
    hackathon_id: uuid.UUID,
    request: Request,
    tenant: TenantContext = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Archives a draft or completed hackathon."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await archive_hackathon(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        actor=tenant.user,
        actor_role=tenant.role,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.post("/{hackathon_id}/status", response_model=HackathonDetailResponse)
async def post_tenant_update_hackathon_status(
    hackathon_id: uuid.UUID,
    data: TenantUpdateHackathonStatusRequest,
    request: Request,
    tenant: TenantContext = Depends(require_org_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Allows Organization Owner to suspend or reinstate a hackathon (ORG_OWNER only)."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await tenant_update_hackathon_status(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        data=data,
        actor=tenant.user,
        actor_role=tenant.role,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.post("/{hackathon_id}/publish-results", response_model=HackathonDetailResponse)
async def post_publish_results(
    hackathon_id: uuid.UUID,
    request: Request,
    tenant: TenantContext = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Publishes evaluation results and releases official leaderboard for participants (§6.5)."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await publish_hackathon_results(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        actor=tenant.user,
        actor_role=tenant.role,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


@router.post("/{hackathon_id}/unpublish-results", response_model=HackathonDetailResponse)
async def post_unpublish_results(
    hackathon_id: uuid.UUID,
    request: Request,
    tenant: TenantContext = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Unpublishes evaluation results and conceals leaderboard from participants."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await unpublish_hackathon_results(
        db=db,
        org_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        actor=tenant.user,
        actor_role=tenant.role,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )


# Mount Subresources Router (Teams, Submissions, Judges, Rubrics, Overview)
from apps.api.modules.hackathons.subresources_router import router as subresources_router
router.include_router(subresources_router)


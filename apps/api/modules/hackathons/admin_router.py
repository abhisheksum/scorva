from typing import Optional
import uuid
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_db_session
from apps.api.dependencies import require_super_admin
from apps.api.modules.hackathons.models import HackathonStatus
from apps.api.modules.hackathons.schemas import (
    AdminUpdateHackathonStatusRequest,
    HackathonDetailResponse,
    PaginatedHackathonsResponse,
)
from apps.api.modules.hackathons.service import (
    get_admin_hackathon_detail,
    list_admin_hackathons,
    override_admin_hackathon_status,
)
from apps.api.modules.users.models import User

router = APIRouter(prefix="/admin/hackathons", tags=["Admin - Hackathons"])


def _extract_telemetry(request: Request):
    ip_address = getattr(request.state, "client_ip", request.client.host if request.client else "127.0.0.1")
    user_agent = request.headers.get("user-agent", "Unknown")
    correlation_id = getattr(request.state, "correlation_id", None)
    return ip_address, user_agent, correlation_id


@router.get("", response_model=PaginatedHackathonsResponse)
@router.get("/", response_model=PaginatedHackathonsResponse, include_in_schema=False)
async def get_admin_hackathons(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search term for title or slug"),
    status: Optional[HackathonStatus] = Query(None, description="Filter by status"),
    organization_id: Optional[uuid.UUID] = Query(None, description="Filter by owning organization UUID"),
    sort_by: str = Query("created_at", description="Sort field ('created_at', 'start_date', 'title')"),
    sort_order: str = Query("desc", description="Sort direction ('asc', 'desc')"),
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Cross-tenant hackathon directory with search and filtering for platform administrators (§8.1)."""
    items, total, total_pages = await list_admin_hackathons(
        db=db,
        page=page,
        limit=limit,
        search=search,
        hackathon_status=status,
        org_id=organization_id,
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


@router.get("/{hackathon_id}", response_model=HackathonDetailResponse)
async def get_admin_hackathon(
    hackathon_id: uuid.UUID,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieves full hackathon details across tenants for authorized platform administrators (§8.1)."""
    return await get_admin_hackathon_detail(
        db=db,
        hackathon_id=hackathon_id,
    )


@router.post("/{hackathon_id}/status", response_model=HackathonDetailResponse)
async def post_admin_override_hackathon_status(
    hackathon_id: uuid.UUID,
    data: AdminUpdateHackathonStatusRequest,
    request: Request,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Overrides hackathon status with mandatory justification and audit logging (§8.1)."""
    ip, ua, corr_id = _extract_telemetry(request)
    return await override_admin_hackathon_status(
        db=db,
        hackathon_id=hackathon_id,
        data=data,
        actor=current_admin,
        ip_address=ip,
        user_agent=ua,
        correlation_id=corr_id,
    )

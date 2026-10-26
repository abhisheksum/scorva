from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_db_session
from apps.api.dependencies import require_security_admin
from apps.api.modules.audit.models import AuditEvent
from apps.api.modules.users.models import User

router = APIRouter(prefix="/admin/security/audit-events", tags=["Admin Audit Log"])


class AuditEventResponse(BaseModel):
    id: str
    timestamp: str
    actor_user_id: Optional[str]
    actor_email: str
    actor_role: str
    action: str
    resource_type: str
    resource_id: str
    organization_id: Optional[str]
    outcome: str
    reason: Optional[str]
    diff_payload: Optional[Dict[str, Any]]
    ip_address: str
    user_agent: str
    correlation_id: str


class AuditEventsListResponse(BaseModel):
    items: List[AuditEventResponse]
    total: int


@router.get(
    "",
    response_model=AuditEventsListResponse,
    summary="Search and retrieve immutable audit events (Security Admin or Super Admin)",
)
async def list_audit_events(
    actor_email: Optional[str] = Query(None, description="Filter by actor email"),
    action: Optional[str] = Query(None, description="Filter by action name"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    organization_id: Optional[str] = Query(None, description="Filter by organization ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
    admin_user: User = Depends(require_security_admin),
) -> AuditEventsListResponse:
    """Retrieves paginated audit trail records."""
    stmt = select(AuditEvent)
    if actor_email:
        stmt = stmt.where(AuditEvent.actor_email == actor_email.strip())
    if action:
        stmt = stmt.where(AuditEvent.action == action.strip())
    if resource_type:
        stmt = stmt.where(AuditEvent.resource_type == resource_type.strip())
    if organization_id:
        try:
            org_uuid = uuid.UUID(organization_id.strip())
            stmt = stmt.where(AuditEvent.organization_id == org_uuid)
        except ValueError:
            pass

    stmt = stmt.order_by(AuditEvent.timestamp.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    events = result.scalars().all()

    items = [
        AuditEventResponse(
            id=str(e.id),
            timestamp=e.timestamp.isoformat(),
            actor_user_id=str(e.actor_user_id) if e.actor_user_id else None,
            actor_email=e.actor_email,
            actor_role=e.actor_role,
            action=e.action,
            resource_type=e.resource_type,
            resource_id=e.resource_id,
            organization_id=str(e.organization_id) if e.organization_id else None,
            outcome=e.outcome.value,
            reason=e.reason,
            diff_payload=e.diff_payload,
            ip_address=e.ip_address,
            user_agent=e.user_agent,
            correlation_id=str(e.correlation_id),
        )
        for e in events
    ]
    return AuditEventsListResponse(items=items, total=len(items))

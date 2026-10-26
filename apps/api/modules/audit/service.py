from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.modules.audit.models import AuditEvent, AuditOutcome


async def record_audit_event(
    db: AsyncSession,
    action: str,
    resource_type: str,
    resource_id: str,
    outcome: AuditOutcome,
    actor_user_id: Optional[uuid.UUID] = None,
    actor_email: str = "system@scorva.local",
    actor_role: str = "system",
    organization_id: Optional[uuid.UUID] = None,
    reason: Optional[str] = None,
    diff_payload: Optional[Dict[str, Any]] = None,
    ip_address: str = "127.0.0.1",
    user_agent: str = "Scorva-API/1.0",
    correlation_id: Optional[uuid.UUID] = None,
) -> AuditEvent:
    """
    Appends an immutable audit event to PostgreSQL within the current session/transaction.
    Guarantees transactional consistency with the corresponding domain mutation.
    """
    event = AuditEvent(
        id=uuid.uuid4(),
        timestamp=datetime.now(timezone.utc),
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        organization_id=organization_id,
        outcome=outcome,
        reason=reason,
        diff_payload=diff_payload,
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id or uuid.uuid4(),
    )
    db.add(event)
    await db.flush()
    return event

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, desc, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_db_session
from apps.api.core.exceptions import AppException
from apps.api.dependencies import get_current_user, require_platform_role
from apps.api.modules.users.models import PlatformRole, User
from apps.api.modules.evaluations.announcement_models import Announcement, ParticipantNotificationState

router = APIRouter(tags=["Announcements & Notifications"])


# ---------------------------------------------------------
# Schemas
# ---------------------------------------------------------

class CreateAnnouncementRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    content: str = Field(..., min_length=5, max_length=10000)
    target_role: str = Field(default="all", description="'all' | 'organizers' | 'judges' | 'participants'")
    placement: str = Field(default="all", description="'all' | 'home' | 'header' | 'announcements'")
    priority: str = Field(default="normal", description="'normal' | 'important' | 'urgent'")
    recipient_ids: List[str] = Field(default_factory=list)
    action_url: Optional[str] = Field(default=None, max_length=500)

    @field_validator("action_url")
    @classmethod
    def validate_action_url(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        v = v.strip()
        if not v:
            return None
        # Disallow unsafe schemes (javascript:, data:, vbscript:)
        if re.match(r"^(javascript|data|vbscript):", v, re.IGNORECASE):
            raise ValueError("Unsafe URL scheme prohibited.")
        # Allow relative internal paths or http/https
        if v.startswith("/") or re.match(r"^https?://", v, re.IGNORECASE):
            return v
        raise ValueError("Action URL must be an internal path (starting with '/') or a valid HTTP/HTTPS URL.")

    @field_validator("target_role")
    @classmethod
    def validate_target_role(cls, v: str) -> str:
        valid = {"all", "organizers", "judges", "participants"}
        if v.lower() not in valid:
            raise ValueError(f"target_role must be one of {valid}")
        return v.lower()

    @field_validator("placement")
    @classmethod
    def validate_placement(cls, v: str) -> str:
        valid = {"all", "home", "header", "announcements"}
        if v.lower() not in valid:
            raise ValueError(f"placement must be one of {valid}")
        return v.lower()

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        valid = {"normal", "important", "urgent"}
        if v.lower() not in valid:
            raise ValueError(f"priority must be one of {valid}")
        return v.lower()


class AnnouncementResponse(BaseModel):
    id: str
    title: str
    content: str
    target_role: str
    placement: str
    priority: str
    recipient_ids: List[str]
    recipient_count: int
    author_name: str
    created_at: str
    status: str
    action_url: Optional[str] = None
    is_read: Optional[bool] = False

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------
# Super Admin Endpoints
# ---------------------------------------------------------

@router.get("/admin/announcements", response_model=List[AnnouncementResponse])
async def list_admin_announcements(
    admin_user: User = Depends(require_platform_role()),
    db: AsyncSession = Depends(get_db_session),
) -> List[AnnouncementResponse]:
    """
    Super Admin endpoint to list all platform announcements.
    """
    stmt = (
        select(Announcement, User.full_name)
        .outerjoin(User, Announcement.created_by_user_id == User.id)
        .order_by(Announcement.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()

    result = []
    for ann, author_name in rows:
        rec_ids = ann.recipient_ids or []
        count = len(rec_ids) if rec_ids else 500  # Broadcast approximation if universal
        result.append(
            AnnouncementResponse(
                id=str(ann.id),
                title=ann.title,
                content=ann.content,
                target_role=ann.target_role,
                placement=ann.placement,
                priority=ann.priority,
                recipient_ids=rec_ids,
                recipient_count=count,
                author_name=author_name or "Super Admin",
                created_at=ann.created_at.isoformat(),
                status=ann.status,
                action_url=ann.action_url,
                is_read=True,
            )
        )
    return result


@router.post("/admin/announcements", response_model=AnnouncementResponse, status_code=status.HTTP_201_CREATED)
async def create_admin_announcement(
    payload: CreateAnnouncementRequest,
    admin_user: User = Depends(require_platform_role()),
    db: AsyncSession = Depends(get_db_session),
) -> AnnouncementResponse:
    """
    Super Admin endpoint to create and dispatch an announcement.
    """
    # Sanitize and validate recipient UUIDs if provided
    cleaned_recipients: List[str] = []
    if payload.recipient_ids:
        for r_id in payload.recipient_ids:
            try:
                cleaned_recipients.append(str(uuid.UUID(str(r_id))))
            except ValueError:
                continue

    new_ann = Announcement(
        id=uuid.uuid4(),
        title=payload.title.strip(),
        content=payload.content.strip(),
        target_role=payload.target_role,
        placement=payload.placement,
        priority=payload.priority,
        recipient_ids=cleaned_recipients,
        action_url=payload.action_url,
        status="active",
        created_by_user_id=admin_user.id,
    )
    db.add(new_ann)
    await db.commit()
    await db.refresh(new_ann)

    return AnnouncementResponse(
        id=str(new_ann.id),
        title=new_ann.title,
        content=new_ann.content,
        target_role=new_ann.target_role,
        placement=new_ann.placement,
        priority=new_ann.priority,
        recipient_ids=new_ann.recipient_ids,
        recipient_count=len(new_ann.recipient_ids) if new_ann.recipient_ids else 500,
        author_name=admin_user.full_name or "Super Admin",
        created_at=new_ann.created_at.isoformat(),
        status=new_ann.status,
        action_url=new_ann.action_url,
        is_read=True,
    )


@router.delete("/admin/announcements/{announcement_id}", status_code=status.HTTP_200_OK)
async def delete_admin_announcement(
    announcement_id: uuid.UUID,
    admin_user: User = Depends(require_platform_role()),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Super Admin endpoint to delete an announcement.
    """
    stmt = select(Announcement).where(Announcement.id == announcement_id)
    ann = (await db.execute(stmt)).scalar_one_or_none()
    if not ann:
        raise AppException(
            code="ANNOUNCEMENT_NOT_FOUND",
            message="Announcement not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
        )

    await db.delete(ann)
    await db.commit()
    return {"status": "success", "message": "Announcement deleted successfully."}


# ---------------------------------------------------------
# Cross-Role General Endpoint (for Organizers, Judges, etc.)
# ---------------------------------------------------------

@router.get("/announcements", response_model=List[AnnouncementResponse])
async def get_user_announcements(
    user: User = Depends(get_current_user),
    placement: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db_session),
) -> List[AnnouncementResponse]:
    """
    Authenticated endpoint returning active announcements tailored to the user's role and ID.
    """
    # Determine user roles
    uid_str = str(user.id)
    allowed_roles = ["all"]
    if user.platform_role:
        allowed_roles.append("super_admin")

    # Check if organizer
    org_stmt = text("SELECT 1 FROM organization_memberships WHERE user_id = :uid LIMIT 1")
    if (await db.execute(org_stmt, {"uid": user.id})).first():
        allowed_roles.append("organizers")

    # Check if judge
    judge_stmt = text("SELECT 1 FROM hackathon_judges WHERE user_id = :uid LIMIT 1")
    if (await db.execute(judge_stmt, {"uid": user.id})).first():
        allowed_roles.append("judges")

    # Check if participant
    part_stmt = text("SELECT 1 FROM team_members WHERE user_id = :uid LIMIT 1")
    if (await db.execute(part_stmt, {"uid": user.id})).first():
        allowed_roles.append("participants")

    # Fetch announcements matching role or specific recipient
    stmt = (
        select(Announcement, User.full_name)
        .outerjoin(User, Announcement.created_by_user_id == User.id)
        .where(Announcement.status == "active")
        .order_by(Announcement.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()

    # Load read states
    read_stmt = select(ParticipantNotificationState.notification_key).where(
        ParticipantNotificationState.user_id == user.id,
        ParticipantNotificationState.is_read.is_(True),
    )
    read_keys = set((await db.execute(read_stmt)).scalars().all())

    items = []
    for ann, author_name in rows:
        # Placement filter if specified
        if placement and placement != "all" and ann.placement != "all" and ann.placement != placement:
            continue

        rec_ids = ann.recipient_ids or []
        is_targeted = False

        if rec_ids:
            if uid_str in rec_ids:
                is_targeted = True
        else:
            if ann.target_role in allowed_roles:
                is_targeted = True

        if is_targeted:
            is_read = f"ann_{ann.id}" in read_keys
            items.append(
                AnnouncementResponse(
                    id=str(ann.id),
                    title=ann.title,
                    content=ann.content,
                    target_role=ann.target_role,
                    placement=ann.placement,
                    priority=ann.priority,
                    recipient_ids=rec_ids,
                    recipient_count=len(rec_ids) if rec_ids else len(allowed_roles),
                    author_name=author_name or "Platform Operations",
                    created_at=ann.created_at.isoformat(),
                    status=ann.status,
                    action_url=ann.action_url,
                    is_read=is_read,
                )
            )

    return items

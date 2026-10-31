from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.core.database import Base


class Announcement(Base):
    """
    Centralized Announcements & Operational Broadcasts.
    Dispatched by Super Admins to specific roles (organizers, judges, participants)
    or explicitly targeted recipient user IDs, displayed across home, header, or dedicated sections.
    """
    __tablename__ = "announcements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    target_role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="all", index=True
    )  # 'all', 'organizers', 'judges', 'participants'
    placement: Mapped[str] = mapped_column(
        String(50), nullable=False, default="all"
    )  # 'all', 'home', 'header', 'announcements'
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normal"
    )  # 'normal', 'important', 'urgent'
    recipient_ids: Mapped[List[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )  # List of target User UUID strings
    action_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", index=True
    )  # 'active', 'scheduled', 'archived'
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ParticipantNotificationState(Base):
    """
    Read/Unread state tracking for participant notifications and announcements.
    """
    __tablename__ = "participant_notification_states"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notification_key: Mapped[str] = mapped_column(String(255), nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "notification_key", name="uq_user_notification_key"),
    )

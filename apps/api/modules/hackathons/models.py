from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Optional
import uuid
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
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

if TYPE_CHECKING:
    from apps.api.modules.organizations.models import Organization
    from apps.api.modules.users.models import User


class HackathonStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    COMPLETED = "completed"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class Hackathon(Base):
    __tablename__ = "hackathons"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[HackathonStatus] = mapped_column(
        SQLEnum(
            HackathonStatus,
            name="hackathon_status_enum",
            native_enum=True,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=HackathonStatus.DRAFT,
        index=True,
    )
    start_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    submission_deadline: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    settings: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "slug", name="uq_hackathons_org_slug"
        ),
        CheckConstraint(
            "start_date < submission_deadline AND submission_deadline <= end_date",
            name="chk_hackathon_timeline",
        ),
        Index("idx_hackathons_org_status", "organization_id", "status"),
        Index("idx_hackathons_status_dates", "status", "start_date"),
    )

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="hackathons"
    )
    created_by: Mapped["User"] = relationship(
        "User", foreign_keys=[created_by_user_id], back_populates="created_hackathons"
    )

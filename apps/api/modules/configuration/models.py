from datetime import datetime
from typing import Optional
import uuid
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from apps.api.core.database import Base
import apps.api.modules.users.models  # noqa: F401


class ConfigurationSetting(Base):
    """
    Subsystem A: Platform-wide configuration setting registry.
    Stores typed system defaults, live effective platform values, and override boundaries.
    """
    __tablename__ = "configuration_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    data_type: Mapped[str] = mapped_column(String(20), nullable=False)
    default_value: Mapped[str] = mapped_column(Text, nullable=False)
    current_value: Mapped[str] = mapped_column(Text, nullable=False)
    allow_org_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_hackathon_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    max_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_configurable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ConfigurationOverride(Base):
    """
    Subsystem A: Tenant- and hackathon-scoped configuration overrides.
    Explicitly bounded by platform setting override permissions and range envelopes.
    """
    __tablename__ = "configuration_overrides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    setting_key: Mapped[str] = mapped_column(
        String(100), ForeignKey("configuration_settings.key", ondelete="CASCADE"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    override_value: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("setting_key", "scope_type", "scope_id", name="uq_configuration_overrides_key_scope"),
        Index("ix_configuration_overrides_scope", "scope_type", "scope_id"),
        CheckConstraint("scope_type IN ('organization', 'hackathon')", name="chk_configuration_overrides_scope_type"),
    )


class ConfigurationHistory(Base):
    """
    Subsystem A: Immutable append-only configuration history.
    Tracks all updates, rollbacks, and overrides with user attribution, IP, and rollback linkages.
    """
    __tablename__ = "configuration_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    setting_key: Mapped[str] = mapped_column(
        String(100), ForeignKey("configuration_settings.key", ondelete="CASCADE"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[str] = mapped_column(Text, nullable=False)
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    restored_from_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    client_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    change_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_configuration_history_key_created", "setting_key", "created_at"),
        CheckConstraint("scope_type IN ('platform', 'organization', 'hackathon')", name="chk_configuration_history_scope_type"),
    )

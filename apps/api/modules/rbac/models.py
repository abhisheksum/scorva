from datetime import datetime
from typing import Optional
import uuid
from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship
from apps.api.core.database import Base
import apps.api.modules.users.models  # noqa: F401

PLATFORM_SCOPE_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


class Permission(Base):
    """
    Subsystem B: Declarative permission catalog.
    Stores stable permission identifiers with domain, action, minimum scope, and delegation flags.
    """
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    domain: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    min_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    is_delegable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Role(Base):
    """
    Subsystem B: Dynamic and system roles scoped to platform, organization, or hackathon.
    System roles cannot be deleted or renamed.
    """
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("name", "scope_type", "scope_id", name="uq_roles_name_scope"),
        Index("ix_roles_scope", "scope_type", "scope_id"),
        CheckConstraint("scope_type IN ('platform', 'organization', 'hackathon')", name="chk_roles_scope_type"),
    )


class RolePermission(Base):
    """
    Subsystem B: Dynamic mapping between roles and permissions.
    """
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserRoleAssignment(Base):
    """
    Subsystem B: Direct assignment of roles to users within explicit platform, organization, or hackathon scopes.
    """
    __tablename__ = "user_role_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    assigned_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "scope_type", "scope_id", name="uq_user_role_scope_assignment"),
        Index("ix_user_role_assignments_lookup", "user_id", "scope_type", "scope_id"),
        CheckConstraint("scope_type IN ('platform', 'organization', 'hackathon')", name="chk_user_role_assignments_scope_type"),
    )


class AuthzPolicyVersion(Base):
    """
    Subsystem B: Durable authority of record for authorization and policy versions.
    Redis caches compare against this durable counter to detect policy mutations.
    """
    __tablename__ = "authz_policy_versions"

    scope_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    current_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("scope_type IN ('platform', 'organization', 'hackathon')", name="chk_authz_policy_versions_scope_type"),
    )


class AuthzInvalidationOutbox(Base):
    """
    Subsystem B: Transactional Outbox for reliable propagation of permission revocations and policy updates to Redis Pub/Sub.
    Committed atomically in the same database transaction as the policy update.
    """
    __tablename__ = "authz_invalidation_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_authz_invalidation_outbox_pending", "processed_at", "retry_count"),
    )

from datetime import datetime, timezone
from typing import Any, Dict
import uuid
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.core.database import Base


class TotpReplayPrevention(Base):
    """
    Durable multi-worker store for used TOTP codes during Redis outages.
    Enforces atomic uniqueness across (user_id, code) to prevent replay attacks across workers.
    """
    __tablename__ = "totp_replay_prevention"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class RateLimitBucket(Base):
    """
    Durable multi-worker store for rate limiting during Redis outages.
    Guarantees that rate limits are globally enforced across all API workers.
    """
    __tablename__ = "rate_limit_buckets"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class MfaPendingToken(Base):
    """
    Durable multi-worker store for ephemeral enrollment, challenge, and setup tokens
    during Redis outages. Allows cross-worker session completion.
    """
    __tablename__ = "mfa_pending_tokens"

    token: Mapped[str] = mapped_column(String(128), primary_key=True)
    token_type: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    data: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

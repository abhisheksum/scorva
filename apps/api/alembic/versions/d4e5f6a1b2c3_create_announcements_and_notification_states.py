"""create_announcements_and_notification_states

Revision ID: d4e5f6a1b2c3
Revises: c3d4e5f6a1b2
Create Date: 2026-10-31 15:45:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "d4e5f6a1b2c3"
down_revision = "c3d4e5f6a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create announcements table
    op.create_table(
        "announcements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("target_role", sa.String(length=50), nullable=False, server_default="all"),
        sa.Column("placement", sa.String(length=50), nullable=False, server_default="all"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("recipient_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("action_url", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_announcements_target_role", "announcements", ["target_role"])
    op.create_index("ix_announcements_status", "announcements", ["status"])
    op.create_index("ix_announcements_created_at", "announcements", ["created_at"])

    # 2. Create participant_notification_states table
    op.create_table(
        "participant_notification_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notification_key", sa.String(length=255), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("read_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("user_id", "notification_key", name="uq_user_notification_key"),
    )
    op.create_index("ix_participant_notif_user", "participant_notification_states", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_participant_notif_user", table_name="participant_notification_states")
    op.drop_table("participant_notification_states")
    op.drop_index("ix_announcements_created_at", table_name="announcements")
    op.drop_index("ix_announcements_status", table_name="announcements")
    op.drop_index("ix_announcements_target_role", table_name="announcements")
    op.drop_table("announcements")

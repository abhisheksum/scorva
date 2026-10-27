"""m6_3_github_events_ingestion

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-10-26 23:48:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a1"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_id", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("hackathon_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repository_owner", sa.String(length=150), nullable=False),
        sa.Column("repository_name", sa.String(length=150), nullable=False),
        sa.Column("canonical_repo_id", sa.String(length=300), nullable=False),
        sa.Column("ref", sa.String(length=255), nullable=True),
        sa.Column("commit_sha", sa.String(length=40), nullable=True),
        sa.Column("sender_login", sa.String(length=100), nullable=True),
        sa.Column("summary", sa.String(length=500), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("diagnostic_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('received', 'processed', 'ignored', 'failed')",
            name="chk_github_events_status",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["hackathon_id"], ["hackathons.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_github_events_delivery_id", "github_events", ["delivery_id"], unique=True)
    op.create_index("ix_github_events_event_type", "github_events", ["event_type"], unique=False)
    op.create_index("ix_github_events_status", "github_events", ["status"], unique=False)
    op.create_index("ix_github_events_canonical_repo_id", "github_events", ["canonical_repo_id"], unique=False)
    op.create_index("ix_github_events_event_timestamp", "github_events", ["event_timestamp"], unique=False)
    op.create_index("ix_github_events_organization_id", "github_events", ["organization_id"], unique=False)
    op.create_index("ix_github_events_hackathon_id", "github_events", ["hackathon_id"], unique=False)
    op.create_index("ix_github_events_submission_id", "github_events", ["submission_id"], unique=False)
    op.create_index(
        "ix_github_events_org_hack_sub",
        "github_events",
        ["organization_id", "hackathon_id", "submission_id"],
        unique=False,
    )
    op.create_index(
        "ix_github_events_repo_timestamp",
        "github_events",
        ["canonical_repo_id", "event_timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_github_events_repo_timestamp", table_name="github_events")
    op.drop_index("ix_github_events_org_hack_sub", table_name="github_events")
    op.drop_index("ix_github_events_submission_id", table_name="github_events")
    op.drop_index("ix_github_events_hackathon_id", table_name="github_events")
    op.drop_index("ix_github_events_organization_id", table_name="github_events")
    op.drop_index("ix_github_events_event_timestamp", table_name="github_events")
    op.drop_index("ix_github_events_canonical_repo_id", table_name="github_events")
    op.drop_index("ix_github_events_status", table_name="github_events")
    op.drop_index("ix_github_events_event_type", table_name="github_events")
    op.drop_index("ix_github_events_delivery_id", table_name="github_events")
    op.drop_table("github_events")

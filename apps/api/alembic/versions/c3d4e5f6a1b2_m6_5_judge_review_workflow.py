"""m6_5_judge_review_workflow

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-10-27 00:45:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c3d4e5f6a1b2"
down_revision = "b2c3d4e5f6a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Update judge_reviews table
    op.add_column(
        "judge_reviews",
        sa.Column("hackathon_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_foreign_key(
        "fk_judge_reviews_hackathon_id",
        "judge_reviews",
        "hackathons",
        ["hackathon_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_judge_reviews_hackathon_id", "judge_reviews", ["hackathon_id"])

    op.add_column(
        "judge_reviews",
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_foreign_key(
        "fk_judge_reviews_submission_id",
        "judge_reviews",
        "submissions",
        ["submission_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_judge_reviews_submission_id", "judge_reviews", ["submission_id"])

    op.add_column(
        "judge_reviews",
        sa.Column("rubric_version_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_foreign_key(
        "fk_judge_reviews_rubric_version_id",
        "judge_reviews",
        "rubric_versions",
        ["rubric_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_judge_reviews_rubric_version_id", "judge_reviews", ["rubric_version_id"])

    op.alter_column("judge_reviews", "evaluation_result_id", nullable=True)
    op.alter_column("judge_reviews", "original_score", nullable=True)
    op.alter_column("judge_reviews", "adjusted_score", nullable=True)
    op.alter_column("judge_reviews", "overall_feedback", nullable=True)
    op.alter_column("judge_reviews", "decision", nullable=True)

    op.add_column(
        "judge_reviews",
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
    )
    op.add_column(
        "judge_reviews",
        sa.Column("score", sa.Numeric(precision=5, scale=2), nullable=True),
    )
    op.add_column(
        "judge_reviews",
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "judge_reviews",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )

    op.drop_constraint("chk_judge_reviews_decision", "judge_reviews", type_="check")
    op.create_check_constraint(
        "chk_judge_reviews_decision",
        "judge_reviews",
        "decision IS NULL OR decision IN ('accepted', 'adjusted', 'rejected')",
    )
    op.create_check_constraint(
        "chk_judge_reviews_status",
        "judge_reviews",
        "status IN ('draft', 'submitted')",
    )
    op.create_unique_constraint(
        "uq_judge_reviews_submission_judge",
        "judge_reviews",
        ["submission_id", "judge_user_id"],
    )
    op.create_index(
        "ix_judge_reviews_hackathon_status",
        "judge_reviews",
        ["hackathon_id", "status"],
    )
    op.create_index(
        "ix_judge_reviews_submission_status",
        "judge_reviews",
        ["submission_id", "status"],
    )

    # 2. Update judge_criterion_scores table
    op.alter_column("judge_criterion_scores", "original_awarded_score", nullable=True)
    op.alter_column("judge_criterion_scores", "adjusted_awarded_score", nullable=True)
    op.alter_column("judge_criterion_scores", "judge_notes", nullable=True)
    op.add_column(
        "judge_criterion_scores",
        sa.Column("score", sa.Numeric(precision=5, scale=2), nullable=True),
    )
    op.create_unique_constraint(
        "uq_judge_criterion_scores_review_criterion",
        "judge_criterion_scores",
        ["judge_review_id", "criterion_id"],
    )


def downgrade() -> None:
    # 2. Revert judge_criterion_scores table
    op.drop_constraint(
        "uq_judge_criterion_scores_review_criterion",
        "judge_criterion_scores",
        type_="unique",
    )
    op.drop_column("judge_criterion_scores", "score")
    op.alter_column("judge_criterion_scores", "judge_notes", nullable=False)
    op.alter_column("judge_criterion_scores", "adjusted_awarded_score", nullable=False)
    op.alter_column("judge_criterion_scores", "original_awarded_score", nullable=False)

    # 1. Revert judge_reviews table
    op.drop_index("ix_judge_reviews_submission_status", table_name="judge_reviews")
    op.drop_index("ix_judge_reviews_hackathon_status", table_name="judge_reviews")
    op.drop_constraint("uq_judge_reviews_submission_judge", "judge_reviews", type_="unique")
    op.drop_constraint("chk_judge_reviews_status", "judge_reviews", type_="check")
    op.drop_constraint("chk_judge_reviews_decision", "judge_reviews", type_="check")
    op.create_check_constraint(
        "chk_judge_reviews_decision",
        "judge_reviews",
        "decision IN ('accepted', 'adjusted', 'rejected')",
    )

    op.drop_column("judge_reviews", "version")
    op.drop_column("judge_reviews", "submitted_at")
    op.drop_column("judge_reviews", "score")
    op.drop_column("judge_reviews", "status")

    op.alter_column("judge_reviews", "decision", nullable=False)
    op.alter_column("judge_reviews", "overall_feedback", nullable=False)
    op.alter_column("judge_reviews", "adjusted_score", nullable=False)
    op.alter_column("judge_reviews", "original_score", nullable=False)
    op.alter_column("judge_reviews", "evaluation_result_id", nullable=False)

    op.drop_index("ix_judge_reviews_rubric_version_id", table_name="judge_reviews")
    op.drop_constraint("fk_judge_reviews_rubric_version_id", "judge_reviews", type_="foreignkey")
    op.drop_column("judge_reviews", "rubric_version_id")

    op.drop_index("ix_judge_reviews_submission_id", table_name="judge_reviews")
    op.drop_constraint("fk_judge_reviews_submission_id", "judge_reviews", type_="foreignkey")
    op.drop_column("judge_reviews", "submission_id")

    op.drop_index("ix_judge_reviews_hackathon_id", table_name="judge_reviews")
    op.drop_constraint("fk_judge_reviews_hackathon_id", "judge_reviews", type_="foreignkey")
    op.drop_column("judge_reviews", "hackathon_id")

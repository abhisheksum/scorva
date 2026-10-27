"""m6_2_submission_repository_linking

Revision ID: a1b2c3d4e5f6
Revises: 9e37b1c1921d
Create Date: 2026-10-26 22:48:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9e37b1c1921d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema for Sub-Milestone 6.2: Submission GitHub Repository Linking & Verification."""
    op.add_column(
        'submissions',
        sa.Column('repository_owner', sa.String(length=100), nullable=True),
    )
    op.add_column(
        'submissions',
        sa.Column('repository_name', sa.String(length=100), nullable=True),
    )
    op.add_column(
        'submissions',
        sa.Column('default_branch', sa.String(length=100), nullable=True),
    )
    op.add_column(
        'submissions',
        sa.Column('verified_commit_sha', sa.String(length=40), nullable=True),
    )
    op.add_column(
        'submissions',
        sa.Column(
            'connection_status',
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'unverified'"),
        ),
    )
    op.add_column(
        'submissions',
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'submissions',
        sa.Column('verification_diagnostic', sa.String(length=50), nullable=True),
    )
    op.add_column(
        'submissions',
        sa.Column('verification_error', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema for Sub-Milestone 6.2."""
    op.drop_column('submissions', 'verification_error')
    op.drop_column('submissions', 'verification_diagnostic')
    op.drop_column('submissions', 'verified_at')
    op.drop_column('submissions', 'connection_status')
    op.drop_column('submissions', 'verified_commit_sha')
    op.drop_column('submissions', 'default_branch')
    op.drop_column('submissions', 'repository_name')
    op.drop_column('submissions', 'repository_owner')

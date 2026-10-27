"""m5_1_evaluation_outbox_and_idempotency

Revision ID: 9e37b1c1921d
Revises: d630cee07d82
Create Date: 2026-10-26 18:22:12.800894

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9e37b1c1921d'
down_revision: Union[str, Sequence[str], None] = 'd630cee07d82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema for Sub-Milestone 5.1: Transactional Outbox and Idempotency."""
    # 1. Extend evaluation_jobs with lease, cancellation, idempotency, and reevaluation metadata
    op.add_column(
        'evaluation_jobs',
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'evaluation_jobs',
        sa.Column(
            'cancellation_requested',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )
    op.add_column(
        'evaluation_jobs',
        sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    )
    op.add_column(
        'evaluation_jobs',
        sa.Column('request_fingerprint', sa.String(length=64), nullable=True),
    )
    op.add_column(
        'evaluation_jobs',
        sa.Column(
            'reevaluation_of_job_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('evaluation_jobs.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.add_column(
        'evaluation_jobs',
        sa.Column(
            'dispatch_generation',
            sa.Integer(),
            nullable=False,
            server_default=sa.text('1'),
        ),
    )

    # 2. Add global request idempotency partial unique index on evaluation_jobs
    op.create_index(
        'uq_eval_jobs_organization_idempotency_key',
        'evaluation_jobs',
        ['organization_id', 'idempotency_key'],
        unique=True,
        postgresql_where=sa.text('idempotency_key IS NOT NULL'),
    )

    op.create_index(
        'ix_eval_jobs_reevaluation_of',
        'evaluation_jobs',
        ['reevaluation_of_job_id'],
        unique=False,
        postgresql_where=sa.text('reevaluation_of_job_id IS NOT NULL'),
    )

    # 3. Create evaluation_job_outbox table
    op.create_table(
        'evaluation_job_outbox',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('job_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            'queue_name',
            sa.String(length=50),
            nullable=False,
            server_default='evaluations.default',
        ),
        sa.Column(
            'routing_key',
            sa.String(length=50),
            nullable=False,
            server_default='evaluations.default',
        ),
        sa.Column(
            'payload',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            'status',
            sa.String(length=20),
            nullable=False,
            server_default='pending',
        ),
        sa.Column('relay_claim_token', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('relay_claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('relay_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('claim_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('publish_attempts', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('dispatch_generation', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('dead_lettered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dead_letter_reason', sa.String(length=100), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('clock_timestamp()'),
        ),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ['job_id'],
            ['evaluation_jobs.id'],
            name='fk_evaluation_job_outbox_job_id',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['organizations.id'],
            name='fk_evaluation_job_outbox_organization_id',
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_evaluation_job_outbox'),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'delivered', 'dead_lettered')",
            name='chk_outbox_status',
        ),
    )

    # 4. Create indexes on evaluation_job_outbox
    op.create_index(
        'ix_eval_job_outbox_job_id',
        'evaluation_job_outbox',
        ['job_id'],
        unique=False,
    )
    op.create_index(
        'ix_eval_job_outbox_org_id',
        'evaluation_job_outbox',
        ['organization_id'],
        unique=False,
    )
    # Active dispatch uniqueness (at most 1 pending or processing row per job)
    op.create_index(
        'uq_eval_job_outbox_active_dispatch',
        'evaluation_job_outbox',
        ['job_id'],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )
    # Fast candidate selection for outbox relays
    op.create_index(
        'ix_eval_job_outbox_claimable',
        'evaluation_job_outbox',
        ['status', 'claim_count', 'relay_expires_at', 'id'],
        unique=False,
        postgresql_where=sa.text('dead_lettered_at IS NULL AND processed_at IS NULL'),
    )
    # Quarantine sweep index
    op.create_index(
        'ix_eval_job_outbox_quarantine',
        'evaluation_job_outbox',
        ['id'],
        unique=False,
        postgresql_where=sa.text("status = 'processing' AND claim_count >= 5 AND dead_lettered_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema for Sub-Milestone 5.1."""
    # 1. Drop evaluation_job_outbox indexes and table
    op.drop_index(
        'ix_eval_job_outbox_quarantine',
        table_name='evaluation_job_outbox',
        postgresql_where=sa.text("status = 'processing' AND claim_count >= 5 AND dead_lettered_at IS NULL"),
    )
    op.drop_index(
        'ix_eval_job_outbox_claimable',
        table_name='evaluation_job_outbox',
        postgresql_where=sa.text('dead_lettered_at IS NULL AND processed_at IS NULL'),
    )
    op.drop_index(
        'uq_eval_job_outbox_active_dispatch',
        table_name='evaluation_job_outbox',
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )
    op.drop_index('ix_eval_job_outbox_org_id', table_name='evaluation_job_outbox')
    op.drop_index('ix_eval_job_outbox_job_id', table_name='evaluation_job_outbox')
    op.drop_table('evaluation_job_outbox')

    # 2. Drop evaluation_jobs indexes and columns
    op.drop_index(
        'ix_eval_jobs_reevaluation_of',
        table_name='evaluation_jobs',
        postgresql_where=sa.text('reevaluation_of_job_id IS NOT NULL'),
    )
    op.drop_index(
        'uq_eval_jobs_organization_idempotency_key',
        table_name='evaluation_jobs',
        postgresql_where=sa.text('idempotency_key IS NOT NULL'),
    )
    op.drop_column('evaluation_jobs', 'dispatch_generation')
    op.drop_column('evaluation_jobs', 'reevaluation_of_job_id')
    op.drop_column('evaluation_jobs', 'request_fingerprint')
    op.drop_column('evaluation_jobs', 'idempotency_key')
    op.drop_column('evaluation_jobs', 'cancellation_requested')
    op.drop_column('evaluation_jobs', 'lease_expires_at')

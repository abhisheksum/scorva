"""remedy_m2_evaluation_schema_constraints

Revision ID: d630cee07d82
Revises: c053567b0586
Create Date: 2026-10-26 04:07:07.280293

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd630cee07d82'
down_revision: Union[str, Sequence[str], None] = 'c053567b0586'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to patch M2 integrity gaps."""
    # 1. Verify no orphan/invalid references before adding foreign key
    conn = op.get_bind()
    invalid_count = conn.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM evaluation_jobs
            WHERE current_result_id IS NOT NULL
              AND current_result_id NOT IN (SELECT id FROM evaluation_results)
            """
        )
    ).scalar()
    if invalid_count > 0:
        raise RuntimeError(
            f"Cannot add foreign key fk_evaluation_jobs_current_result_id: "
            f"found {invalid_count} evaluation_jobs rows with invalid current_result_id references."
        )

    # 2. Add PostgreSQL-enforced foreign key fk_evaluation_jobs_current_result_id
    op.create_foreign_key(
        'fk_evaluation_jobs_current_result_id',
        'evaluation_jobs',
        'evaluation_results',
        ['current_result_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # 3. Update check_rubric_version_immutability function to prevent reparenting and moving criteria
    op.execute(
        """
        CREATE OR REPLACE FUNCTION check_rubric_version_immutability()
        RETURNS TRIGGER AS $$
        DECLARE
            v_status VARCHAR(20);
            v_old_status VARCHAR(20);
            v_new_status VARCHAR(20);
        BEGIN
            IF (TG_OP = 'INSERT') THEN
                SELECT status INTO v_status
                FROM rubric_versions
                WHERE id = NEW.rubric_version_id
                FOR SHARE;

                IF (v_status IN ('published', 'archived')) THEN
                    RAISE EXCEPTION 'Cannot insert criteria for a % rubric version (id=%)', v_status, NEW.rubric_version_id;
                END IF;

            ELSIF (TG_OP = 'UPDATE') THEN
                SELECT status INTO v_old_status
                FROM rubric_versions
                WHERE id = OLD.rubric_version_id
                FOR SHARE;

                IF (v_old_status IN ('published', 'archived')) THEN
                    RAISE EXCEPTION 'Cannot update criteria in a % rubric version (id=%)', v_old_status, OLD.rubric_version_id;
                END IF;

                IF (NEW.rubric_version_id <> OLD.rubric_version_id) THEN
                    SELECT status INTO v_new_status
                    FROM rubric_versions
                    WHERE id = NEW.rubric_version_id
                    FOR SHARE;

                    IF (v_new_status IN ('published', 'archived')) THEN
                        RAISE EXCEPTION 'Cannot move criteria into a % rubric version (id=%)', v_new_status, NEW.rubric_version_id;
                    END IF;
                END IF;

            ELSIF (TG_OP = 'DELETE') THEN
                SELECT status INTO v_old_status
                FROM rubric_versions
                WHERE id = OLD.rubric_version_id;

                IF (v_old_status IN ('published', 'archived')) THEN
                    RAISE EXCEPTION 'Cannot delete criteria from a % rubric version (id=%)', v_old_status, OLD.rubric_version_id;
                END IF;
            END IF;

            IF (TG_OP = 'DELETE') THEN
                RETURN OLD;
            ELSE
                RETURN NEW;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # 4. Create check_rubric_version_lifecycle function and trigger on rubric_versions
    op.execute(
        """
        CREATE OR REPLACE FUNCTION check_rubric_version_lifecycle()
        RETURNS TRIGGER AS $$
        BEGIN
            IF (TG_OP = 'DELETE') THEN
                IF (OLD.status IN ('published', 'archived')) THEN
                    RAISE EXCEPTION 'Cannot delete a % rubric version (id=%)', OLD.status, OLD.id;
                END IF;
                RETURN OLD;
            ELSIF (TG_OP = 'UPDATE') THEN
                IF (OLD.status = 'published') THEN
                    IF (NEW.status = 'draft') THEN
                        RAISE EXCEPTION 'Cannot revert published rubric version back to draft (id=%)', OLD.id;
                    END IF;
                    IF (NEW.organization_id <> OLD.organization_id) THEN
                        RAISE EXCEPTION 'Cannot change organization_id on published rubric version (id=%)', OLD.id;
                    END IF;
                    IF (NEW.rubric_id <> OLD.rubric_id) THEN
                        RAISE EXCEPTION 'Cannot change rubric_id on published rubric version (id=%)', OLD.id;
                    END IF;
                    IF (NEW.version_number <> OLD.version_number) THEN
                        RAISE EXCEPTION 'Cannot change version_number on published rubric version (id=%)', OLD.id;
                    END IF;
                ELSIF (OLD.status = 'archived') THEN
                    IF (NEW.status <> 'archived') THEN
                        RAISE EXCEPTION 'Cannot change status of archived rubric version (id=%)', OLD.id;
                    END IF;
                    IF (NEW.organization_id <> OLD.organization_id OR NEW.rubric_id <> OLD.rubric_id OR NEW.version_number <> OLD.version_number) THEN
                        RAISE EXCEPTION 'Cannot modify identity columns of archived rubric version (id=%)', OLD.id;
                    END IF;
                END IF;
                RETURN NEW;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rubric_versions_protect
        BEFORE UPDATE OR DELETE ON rubric_versions
        FOR EACH ROW
        EXECUTE FUNCTION check_rubric_version_lifecycle();
        """
    )

    # 5. Create check_submission_snapshot_immutability function and trigger on submission_snapshots
    op.execute(
        """
        CREATE OR REPLACE FUNCTION check_submission_snapshot_immutability()
        RETURNS TRIGGER AS $$
        BEGIN
            IF (TG_OP = 'UPDATE') THEN
                IF (NEW.configuration_snapshot IS DISTINCT FROM OLD.configuration_snapshot) THEN
                    RAISE EXCEPTION 'configuration_snapshot is immutable and cannot be modified (snapshot_id=%)', OLD.id;
                END IF;
                IF (NEW.organization_id <> OLD.organization_id) THEN
                    RAISE EXCEPTION 'organization_id on submission_snapshot is immutable (snapshot_id=%)', OLD.id;
                END IF;
                IF (NEW.submission_id <> OLD.submission_id) THEN
                    RAISE EXCEPTION 'submission_id on submission_snapshot is immutable (snapshot_id=%)', OLD.id;
                END IF;
                IF (NEW.commit_sha <> OLD.commit_sha) THEN
                    RAISE EXCEPTION 'commit_sha on submission_snapshot is immutable (snapshot_id=%)', OLD.id;
                END IF;
                RETURN NEW;
            ELSIF (TG_OP = 'DELETE') THEN
                IF EXISTS (SELECT 1 FROM evaluation_jobs WHERE snapshot_id = OLD.id) OR
                   EXISTS (SELECT 1 FROM evaluation_results WHERE snapshot_id = OLD.id) THEN
                    RAISE EXCEPTION 'Cannot delete submission snapshot referenced by evaluation jobs or results (snapshot_id=%)', OLD.id;
                END IF;
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_submission_snapshots_immutable
        BEFORE UPDATE OR DELETE ON submission_snapshots
        FOR EACH ROW
        EXECUTE FUNCTION check_submission_snapshot_immutability();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Drop submission snapshots immutability trigger and function
    op.execute("DROP TRIGGER IF EXISTS trg_submission_snapshots_immutable ON submission_snapshots;")
    op.execute("DROP FUNCTION IF EXISTS check_submission_snapshot_immutability();")

    # 2. Drop rubric versions lifecycle trigger and function
    op.execute("DROP TRIGGER IF EXISTS trg_rubric_versions_protect ON rubric_versions;")
    op.execute("DROP FUNCTION IF EXISTS check_rubric_version_lifecycle();")

    # 3. Restore original check_rubric_version_immutability function
    op.execute(
        """
        CREATE OR REPLACE FUNCTION check_rubric_version_immutability()
        RETURNS TRIGGER AS $$
        DECLARE
            v_status VARCHAR(20);
            target_version_id UUID;
        BEGIN
            IF (TG_OP = 'DELETE') THEN
                target_version_id := OLD.rubric_version_id;
            ELSE
                target_version_id := NEW.rubric_version_id;
            END IF;

            SELECT status INTO v_status
            FROM rubric_versions
            WHERE id = target_version_id;

            IF (v_status = 'published') THEN
                IF (TG_OP = 'INSERT') THEN
                    RAISE EXCEPTION 'Cannot insert criteria for a published rubric version';
                ELSIF (TG_OP = 'UPDATE') THEN
                    RAISE EXCEPTION 'Cannot update criteria in a published rubric version';
                ELSIF (TG_OP = 'DELETE') THEN
                    RAISE EXCEPTION 'Cannot delete criteria from a published rubric version';
                END IF;
            END IF;

            IF (TG_OP = 'DELETE') THEN
                RETURN OLD;
            ELSE
                RETURN NEW;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # 4. Drop foreign key constraint
    op.drop_constraint('fk_evaluation_jobs_current_result_id', 'evaluation_jobs', type_='foreignkey')

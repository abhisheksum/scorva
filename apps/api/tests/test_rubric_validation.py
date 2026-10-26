from decimal import Decimal
import uuid
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.core.exceptions import AppException
from apps.api.modules.evaluations.models import Rubric, RubricCriterion, RubricVersion
from apps.api.modules.evaluations.service import (
    add_rubric_criterion,
    create_rubric,
    publish_rubric_version,
)
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.modules.organizations.models import Organization, OrganizationStatus
from apps.api.modules.users.models import PlatformRole, User


@pytest.fixture
async def setup_test_context(db_session: AsyncSession):
    """Fixture providing a verified User, Organization, and Hackathon."""
    user = User(
        email=f"organizer_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="fakehash",
        full_name="Rubric Test Organizer",
        platform_role=None,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    org = Organization(
        name="Rubric Test Org",
        slug=f"rubric-org-{uuid.uuid4().hex[:8]}",
        owner_id=user.id,
        status=OrganizationStatus.ACTIVE,
    )
    db_session.add(org)
    await db_session.flush()

    hackathon = Hackathon(
        organization_id=org.id,
        title="Rubric Test Hackathon",
        slug=f"rubric-hack-{uuid.uuid4().hex[:8]}",
        status=HackathonStatus.PUBLISHED,
        start_date=text("now()"),
        end_date=text("now() + interval '7 days'"),
        submission_deadline=text("now() + interval '6 days'"),
        created_by_user_id=user.id,
    )
    db_session.add(hackathon)
    await db_session.commit()

    return user, org, hackathon


@pytest.mark.asyncio
async def test_rubric_creation_and_criteria_addition(db_session: AsyncSession, setup_test_context):
    """Test creating a rubric with initial draft version and adding valid criteria."""
    user, org, hackathon = setup_test_context

    rubric = await create_rubric(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name="AI Quality Rubric",
        description="Rubric for evaluating AI models and code quality",
        scoring_mode="offset_normalized",
    )
    assert rubric.id is not None
    assert rubric.scoring_mode == "offset_normalized"

    # Get the created draft version (v1)
    stmt = select(RubricVersion).where(RubricVersion.rubric_id == rubric.id)
    version = (await db_session.execute(stmt)).scalars().first()
    assert version is not None
    assert version.version_number == 1
    assert version.status == "draft"

    # Add criteria
    c1 = await add_rubric_criterion(
        db=db_session,
        rubric_version_id=version.id,
        title="Code Quality & Architecture",
        description="Assesses clean code principles and architecture design",
        weight=Decimal("0.5000"),
        min_score=Decimal("0.00"),
        max_score=Decimal("10.00"),
        evidence_requirements="Must contain clean modular packages and docstrings",
        order_index=1,
    )
    c2 = await add_rubric_criterion(
        db=db_session,
        rubric_version_id=version.id,
        title="Evidence Grounding",
        description="Assesses verifiable citations in repository files",
        weight=Decimal("0.5000"),
        min_score=Decimal("0.00"),
        max_score=Decimal("10.00"),
        evidence_requirements="Citations to concrete AST files and test cases",
        order_index=2,
    )

    assert c1.id is not None
    assert c2.id is not None
    assert c1.weight == Decimal("0.5000")
    assert c2.weight == Decimal("0.5000")


@pytest.mark.asyncio
async def test_publish_rubric_fails_with_invalid_weights(db_session: AsyncSession, setup_test_context):
    """Publishing a rubric version fails if weight sum deviates from 1.0000 ± 0.0001."""
    user, org, hackathon = setup_test_context

    rubric = await create_rubric(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name="Bad Weight Rubric",
    )
    stmt = select(RubricVersion).where(RubricVersion.rubric_id == rubric.id)
    version = (await db_session.execute(stmt)).scalars().first()
    assert version is not None

    # Add criteria summing to 0.7000 (invalid)
    await add_rubric_criterion(
        db=db_session,
        rubric_version_id=version.id,
        title="Criterion 1",
        description="Desc",
        weight=Decimal("0.4000"),
        evidence_requirements="Req 1",
    )
    await add_rubric_criterion(
        db=db_session,
        rubric_version_id=version.id,
        title="Criterion 2",
        description="Desc",
        weight=Decimal("0.3000"),
        evidence_requirements="Req 2",
    )

    with pytest.raises(AppException) as exc_info:
        await publish_rubric_version(db_session, org.id, version.id)

    assert exc_info.value.code == "INVALID_RUBRIC_WEIGHTS"
    assert "Rubric criteria weights must sum to 1.0000 ± 0.0001" in exc_info.value.message


@pytest.mark.asyncio
async def test_publish_rubric_and_postgres_immutability_trigger(
    db_session: AsyncSession, setup_test_context
):
    """
    Publishing freezes the rubric version and causes the PostgreSQL trigger
    `trg_rubric_criteria_immutable` to reject any INSERT, UPDATE, or DELETE on criteria.
    """
    user, org, hackathon = setup_test_context

    rubric = await create_rubric(
        db=db_session,
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name="Immutability Test Rubric",
    )
    stmt = select(RubricVersion).where(RubricVersion.rubric_id == rubric.id)
    version = (await db_session.execute(stmt)).scalars().first()
    assert version is not None

    # Add criteria summing to exactly 1.0000
    c1 = await add_rubric_criterion(
        db=db_session,
        rubric_version_id=version.id,
        title="Performance",
        description="Response latency and benchmark metrics",
        weight=Decimal("0.6000"),
        evidence_requirements="Benchmarks output log",
    )
    c2 = await add_rubric_criterion(
        db=db_session,
        rubric_version_id=version.id,
        title="Documentation",
        description="API and deployment documentation",
        weight=Decimal("0.4000"),
        evidence_requirements="README and architecture documents",
    )
    await db_session.commit()

    # Publish version
    pub_version = await publish_rubric_version(db_session, org.id, version.id)
    assert pub_version.status == "published"
    assert pub_version.published_at is not None
    await db_session.commit()

    ver_id = version.id
    c1_id = c1.id

    # 1. Application-level check blocks adding criterion to published version
    with pytest.raises(AppException) as app_exc:
        await add_rubric_criterion(
            db=db_session,
            rubric_version_id=ver_id,
            title="Sneak Criterion",
            description="Attempt to add after publishing",
            weight=Decimal("0.1000"),
            evidence_requirements="None",
        )
    assert app_exc.value.code == "RUBRIC_VERSION_FROZEN"

    # 2. Direct PostgreSQL INSERT trigger check
    with pytest.raises(Exception) as db_exc_insert:
        await db_session.execute(
            text(
                """
                INSERT INTO rubric_criteria (id, rubric_version_id, title, description, weight, min_score, max_score, evidence_requirements, order_index)
                VALUES (:id, :ver_id, 'Direct SQL Criterion', 'Direct insert', 0.1000, 0, 10, 'Req', 3);
                """
            ),
            {"id": uuid.uuid4(), "ver_id": ver_id},
        )
    await db_session.rollback()
    assert "Cannot insert criteria for a published rubric version" in str(db_exc_insert.value)

    # 3. Direct PostgreSQL UPDATE trigger check
    with pytest.raises(Exception) as db_exc_update:
        await db_session.execute(
            text(
                """
                UPDATE rubric_criteria
                SET weight = 0.7000
                WHERE id = :cid;
                """
            ),
            {"cid": c1_id},
        )
    await db_session.rollback()
    assert "Cannot update criteria in a published rubric version" in str(db_exc_update.value)

    # 4. Direct PostgreSQL DELETE trigger check
    with pytest.raises(Exception) as db_exc_delete:
        await db_session.execute(
            text(
                """
                DELETE FROM rubric_criteria
                WHERE id = :cid;
                """
            ),
            {"cid": c1_id},
        )
    await db_session.rollback()
    assert "Cannot delete criteria from a published rubric version" in str(db_exc_delete.value)

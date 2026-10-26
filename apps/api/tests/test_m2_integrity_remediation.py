import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import uuid
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import AsyncSessionLocal
from apps.api.core.exceptions import AppException
from apps.api.modules.evaluations.models import (
    EvaluationJob,
    EvaluationResult,
    Rubric,
    RubricCriterion,
    RubricVersion,
    Submission,
    SubmissionSnapshot,
    Team,
)
from apps.api.modules.evaluations.scoring_calculator import (
    CriterionInput,
    calculate_evaluation_scores,
    validate_criteria_weights,
)
from apps.api.modules.evaluations.service import (
    add_rubric_criterion,
    create_rubric,
    publish_rubric_version,
)
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.modules.organizations.models import Organization, OrganizationStatus
from apps.api.modules.users.models import User


# ==============================================================================
# Helper fixture for clean test entities
# ==============================================================================
@pytest.fixture
async def remediation_context(db_session: AsyncSession):
    user = User(
        email=f"remed_org_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="fakehash",
        full_name="Remediation Test Organizer",
        platform_role=None,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    org = Organization(
        name="Remediation Test Org",
        slug=f"remed-org-{uuid.uuid4().hex[:8]}",
        owner_id=user.id,
        status=OrganizationStatus.ACTIVE,
    )
    db_session.add(org)
    await db_session.flush()

    hackathon = Hackathon(
        organization_id=org.id,
        title="Remediation Test Hackathon",
        slug=f"remed-hack-{uuid.uuid4().hex[:8]}",
        status=HackathonStatus.PUBLISHED,
        start_date=text("now()"),
        end_date=text("now() + interval '7 days'"),
        submission_deadline=text("now() + interval '6 days'"),
        created_by_user_id=user.id,
    )
    db_session.add(hackathon)
    await db_session.flush()

    team = Team(
        id=uuid.uuid4(),
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name=f"Team {uuid.uuid4().hex[:6]}",
        join_code=f"CODE_{uuid.uuid4().hex[:4]}",
        created_by_user_id=user.id,
    )
    db_session.add(team)
    await db_session.flush()

    submission = Submission(
        id=uuid.uuid4(),
        organization_id=org.id,
        hackathon_id=hackathon.id,
        team_id=team.id,
        team_name=team.name,
        title="Remediation Submission Project",
        description="Project description",
        repository_url="https://github.com/scorva-org/remediation-repo",
        target_branch="main",
        status="pending",
    )
    db_session.add(submission)
    await db_session.commit()

    return {
        "user_id": user.id,
        "org_id": org.id,
        "hackathon_id": hackathon.id,
        "team_id": team.id,
        "submission_id": submission.id,
    }


# ==============================================================================
# Finding 1 Tests: Published Rubric & Criteria Immutability
# ==============================================================================
@pytest.mark.asyncio
async def test_finding_1_published_rubric_cannot_insert_or_modify_criteria(
    db_session: AsyncSession, remediation_context
):
    ctx = remediation_context
    rubric = await create_rubric(db_session, ctx["org_id"], ctx["hackathon_id"], "F1 Rubric 1")
    stmt = select(RubricVersion).where(RubricVersion.rubric_id == rubric.id)
    version = (await db_session.execute(stmt)).scalars().first()

    c1 = await add_rubric_criterion(
        db_session, version.id, "Criterion 1", "Desc", Decimal("1.0000"),
        organization_id=ctx["org_id"]
    )
    await db_session.commit()

    # Publish version
    await publish_rubric_version(db_session, ctx["org_id"], version.id)
    await db_session.commit()

    vid = version.id
    c1_id = c1.id

    # 1. Direct SQL INSERT into published version must fail
    with pytest.raises(Exception) as exc_insert:
        await db_session.execute(
            text(
                """
                INSERT INTO rubric_criteria (id, rubric_version_id, title, description, weight, min_score, max_score, evidence_requirements, order_index)
                VALUES (:id, :vid, 'Sneak Insert', 'desc', 0.2, 0, 10, 'req', 2);
                """
            ),
            {"id": uuid.uuid4(), "vid": vid},
        )
    await db_session.rollback()
    assert "Cannot insert criteria for a published rubric version" in str(exc_insert.value)

    # 2. Direct SQL UPDATE on criteria of published version must fail
    with pytest.raises(Exception) as exc_update:
        await db_session.execute(
            text("UPDATE rubric_criteria SET weight = 0.5000 WHERE id = :cid;"),
            {"cid": c1_id},
        )
    await db_session.rollback()
    assert "Cannot update criteria in a published rubric version" in str(exc_update.value)

    # 3. Direct SQL DELETE of criteria in published version must fail
    with pytest.raises(Exception) as exc_delete:
        await db_session.execute(
            text("DELETE FROM rubric_criteria WHERE id = :cid;"),
            {"cid": c1_id},
        )
    await db_session.rollback()
    assert "Cannot delete criteria from a published rubric version" in str(exc_delete.value)


@pytest.mark.asyncio
async def test_finding_1_reparenting_criteria_between_published_and_draft_blocked(
    db_session: AsyncSession, remediation_context
):
    ctx = remediation_context
    rubric = await create_rubric(db_session, ctx["org_id"], ctx["hackathon_id"], "F1 Reparent Rubric")
    stmt = select(RubricVersion).where(RubricVersion.rubric_id == rubric.id)
    v1 = (await db_session.execute(stmt)).scalars().first()

    c1 = await add_rubric_criterion(
        db_session, v1.id, "V1 Criterion", "Desc", Decimal("1.0000"),
        organization_id=ctx["org_id"]
    )
    await db_session.commit()
    await publish_rubric_version(db_session, ctx["org_id"], v1.id)
    await db_session.commit()

    # Create a draft version v2 on the same rubric
    v2 = RubricVersion(
        id=uuid.uuid4(),
        organization_id=ctx["org_id"],
        rubric_id=rubric.id,
        version_number=2,
        status="draft",
    )
    db_session.add(v2)
    c2 = RubricCriterion(
        id=uuid.uuid4(),
        rubric_version_id=v2.id,
        title="V2 Draft Criterion",
        description="desc",
        weight=Decimal("1.0000"),
        min_score=Decimal("0.00"),
        max_score=Decimal("10.00"),
        evidence_requirements="req",
        order_index=1,
    )
    db_session.add(c2)
    await db_session.commit()

    v1_id = v1.id
    v2_id = v2.id
    c1_id = c1.id
    c2_id = c2.id

    # Attempt 1: Moving C1 (published V1) into V2 (draft) must FAIL
    with pytest.raises(Exception) as exc_move_out:
        await db_session.execute(
            text("UPDATE rubric_criteria SET rubric_version_id = :v2_id WHERE id = :c1_id;"),
            {"v2_id": v2_id, "c1_id": c1_id},
        )
    await db_session.rollback()
    assert "Cannot update criteria in a published rubric version" in str(exc_move_out.value)

    # Attempt 2: Moving C2 (draft V2) into V1 (published) must FAIL
    with pytest.raises(Exception) as exc_move_in:
        await db_session.execute(
            text("UPDATE rubric_criteria SET rubric_version_id = :v1_id WHERE id = :c2_id;"),
            {"v1_id": v1_id, "c2_id": c2_id},
        )
    await db_session.rollback()
    assert "Cannot move criteria into a published rubric version" in str(exc_move_in.value)


@pytest.mark.asyncio
async def test_finding_1_published_rubric_version_deletion_and_unpublish_blocked(
    db_session: AsyncSession, remediation_context
):
    ctx = remediation_context
    rubric = await create_rubric(db_session, ctx["org_id"], ctx["hackathon_id"], "F1 Lifecycle Rubric")
    stmt = select(RubricVersion).where(RubricVersion.rubric_id == rubric.id)
    version = (await db_session.execute(stmt)).scalars().first()

    await add_rubric_criterion(
        db_session, version.id, "Criterion", "Desc", Decimal("1.0000"),
        organization_id=ctx["org_id"]
    )
    await db_session.commit()
    await publish_rubric_version(db_session, ctx["org_id"], version.id)
    await db_session.commit()

    vid = version.id

    # 1. Attempting to DELETE published rubric version must FAIL
    with pytest.raises(Exception) as exc_del_ver:
        await db_session.execute(
            text("DELETE FROM rubric_versions WHERE id = :vid;"),
            {"vid": vid},
        )
    await db_session.rollback()
    assert "Cannot delete a published rubric version" in str(exc_del_ver.value)

    # 2. Attempting to revert published rubric version back to 'draft' must FAIL
    with pytest.raises(Exception) as exc_unpub:
        await db_session.execute(
            text("UPDATE rubric_versions SET status = 'draft' WHERE id = :vid;"),
            {"vid": vid},
        )
    await db_session.rollback()
    assert "Cannot revert published rubric version back to draft" in str(exc_unpub.value)


@pytest.mark.asyncio
async def test_finding_1_draft_rubric_and_criteria_remain_mutable_and_deletable(
    db_session: AsyncSession, remediation_context
):
    ctx = remediation_context
    rubric = await create_rubric(db_session, ctx["org_id"], ctx["hackathon_id"], "F1 Draft Mutability")
    stmt = select(RubricVersion).where(RubricVersion.rubric_id == rubric.id)
    version = (await db_session.execute(stmt)).scalars().first()

    # In draft status: adding, updating, and deleting criteria succeeds
    c1 = await add_rubric_criterion(
        db_session, version.id, "Draft C1", "Desc", Decimal("0.5000"),
        organization_id=ctx["org_id"]
    )
    await db_session.commit()

    cid = c1.id
    vid = version.id

    # Update in draft
    await db_session.execute(
        text("UPDATE rubric_criteria SET title = 'Draft C1 Updated' WHERE id = :cid;"),
        {"cid": cid},
    )
    await db_session.commit()

    # Delete in draft
    await db_session.execute(
        text("DELETE FROM rubric_criteria WHERE id = :cid;"),
        {"cid": cid},
    )
    await db_session.commit()

    # Deleting draft rubric version succeeds and cascades cleanly
    await db_session.execute(
        text("DELETE FROM rubric_versions WHERE id = :vid;"),
        {"vid": vid},
    )
    await db_session.commit()


# ==============================================================================
# Finding 2 Tests: evaluation_jobs.current_result_id Foreign Key
# ==============================================================================
@pytest.mark.asyncio
async def test_finding_2_foreign_key_current_result_id(
    db_session: AsyncSession, remediation_context
):
    ctx = remediation_context
    rubric = await create_rubric(db_session, ctx["org_id"], ctx["hackathon_id"], "F2 FK Rubric")
    stmt = select(RubricVersion).where(RubricVersion.rubric_id == rubric.id)
    version = (await db_session.execute(stmt)).scalars().first()
    await add_rubric_criterion(db_session, version.id, "C1", "D", Decimal("1.0000"))
    await publish_rubric_version(db_session, ctx["org_id"], version.id)

    snapshot = SubmissionSnapshot(
        id=uuid.uuid4(),
        organization_id=ctx["org_id"],
        submission_id=ctx["submission_id"],
        commit_sha="a" * 40,
        configuration_snapshot={"scoring.mode": "offset_normalized"},
        file_count=5,
        total_bytes=1000,
    )
    db_session.add(snapshot)
    await db_session.commit()

    # 1. Creating job with current_result_id=None succeeds
    job = EvaluationJob(
        id=uuid.uuid4(),
        organization_id=ctx["org_id"],
        hackathon_id=ctx["hackathon_id"],
        submission_id=ctx["submission_id"],
        snapshot_id=snapshot.id,
        rubric_version_id=version.id,
        current_result_id=None,
        status="queued",
    )
    db_session.add(job)
    await db_session.commit()
    assert job.current_result_id is None

    jid = job.id
    snap_id = snapshot.id
    vid = version.id

    # 2. Assigning a non-existent UUID fails with ForeignKeyViolation
    invalid_result_id = uuid.uuid4()
    with pytest.raises(Exception) as exc_fk:
        await db_session.execute(
            text("UPDATE evaluation_jobs SET current_result_id = :rid WHERE id = :jid;"),
            {"rid": invalid_result_id, "jid": jid},
        )
    await db_session.rollback()
    assert "violates foreign key constraint" in str(exc_fk.value).lower() or "fk_evaluation_jobs_current_result_id" in str(exc_fk.value)

    # 3. Assigning a real result succeeds
    result = EvaluationResult(
        id=uuid.uuid4(),
        organization_id=ctx["org_id"],
        hackathon_id=ctx["hackathon_id"],
        submission_id=ctx["submission_id"],
        rubric_version_id=vid,
        job_id=jid,
        snapshot_id=snap_id,
        attempt_number=1,
        model_provider="ollama",
        model_name="qwen2.5-coder:7b",
        prompt_version="1.0",
        raw_score=Decimal("85.00"),
        normalized_score=Decimal("85.00"),
        summary_assessment="Great test run",
        has_insufficient_evidence=False,
    )
    db_session.add(result)
    await db_session.commit()
    rid = result.id

    await db_session.execute(
        text("UPDATE evaluation_jobs SET current_result_id = :rid WHERE id = :jid;"),
        {"rid": rid, "jid": jid},
    )
    await db_session.commit()

    # 4. Deleting the result sets current_result_id to NULL (ON DELETE SET NULL)
    await db_session.execute(
        text("DELETE FROM evaluation_results WHERE id = :rid;"),
        {"rid": rid},
    )
    await db_session.commit()

    res = await db_session.execute(
        text("SELECT current_result_id FROM evaluation_jobs WHERE id = :jid;"),
        {"jid": jid},
    )
    current_val = res.scalar()
    assert current_val is None


# ==============================================================================
# Finding 3 Tests: submission_snapshots Immutability Contract
# ==============================================================================
@pytest.mark.asyncio
async def test_finding_3_snapshot_configuration_immutability(
    db_session: AsyncSession, remediation_context
):
    ctx = remediation_context
    snapshot = SubmissionSnapshot(
        id=uuid.uuid4(),
        organization_id=ctx["org_id"],
        submission_id=ctx["submission_id"],
        commit_sha="b" * 40,
        configuration_snapshot={"scoring.mode": "offset_normalized", "eval.model": "qwen2.5"},
        file_count=10,
        total_bytes=2048,
    )
    db_session.add(snapshot)
    await db_session.commit()
    sid = snapshot.id

    # 1. Attempting to UPDATE configuration_snapshot fails
    with pytest.raises(Exception) as exc_cfg:
        await db_session.execute(
            text(
                """
                UPDATE submission_snapshots
                SET configuration_snapshot = '{"scoring.mode": "raw_proportional"}'
                WHERE id = :sid;
                """
            ),
            {"sid": sid},
        )
    await db_session.rollback()
    assert "configuration_snapshot is immutable and cannot be modified" in str(exc_cfg.value)

    # 2. Attempting to UPDATE commit_sha or identity columns fails
    with pytest.raises(Exception) as exc_sha:
        await db_session.execute(
            text("UPDATE submission_snapshots SET commit_sha = :sha WHERE id = :sid;"),
            {"sha": "c" * 40, "sid": sid},
        )
    await db_session.rollback()
    assert "commit_sha on submission_snapshot is immutable" in str(exc_sha.value)

    # 3. Legitimate update to lifecycle ingestion fields succeeds
    await db_session.execute(
        text(
            """
            UPDATE submission_snapshots
            SET snapshot_tarball_url = 's3://bucket/tarball.tar.gz',
                file_count = 25,
                total_bytes = 4096,
                metadata = '{"extracted": true}'
            WHERE id = :sid;
            """
        ),
        {"sid": sid},
    )
    await db_session.commit()

    res = await db_session.execute(
        text("SELECT snapshot_tarball_url, file_count, total_bytes, metadata FROM submission_snapshots WHERE id = :sid;"),
        {"sid": sid},
    )
    row = res.fetchone()
    assert row[0] == "s3://bucket/tarball.tar.gz"
    assert row[1] == 25
    assert row[2] == 4096
    assert row[3] == {"extracted": True}


# ==============================================================================
# Finding 4 Tests: Real PostgreSQL Concurrency Locking
# ==============================================================================
@pytest.mark.asyncio
async def test_finding_4_concurrent_add_criterion_and_publish_race(
    remediation_context
):
    """
    Simulates real PostgreSQL race condition using two independent database sessions:
    - Session 1 begins publishing draft version V (holds SELECT ... FOR UPDATE).
    - Session 2 concurrently attempts to add a criterion to version V.
    - Session 2 must be blocked until Session 1 completes publication.
    - Once Session 1 commits 'published', Session 2 unblocks and is rejected.
    """
    ctx = remediation_context

    async with AsyncSessionLocal() as init_session:
        rubric = await create_rubric(init_session, ctx["org_id"], ctx["hackathon_id"], "F4 Race Rubric")
        stmt = select(RubricVersion).where(RubricVersion.rubric_id == rubric.id)
        version = (await init_session.execute(stmt)).scalars().first()
        await add_rubric_criterion(init_session, version.id, "Original C1", "D", Decimal("1.0000"))
        await init_session.commit()
        vid = version.id

    session1_locked = asyncio.Event()
    session2_done = asyncio.Event()
    session2_result = {"status": None, "error": None}

    async def worker_publish():
        async with AsyncSessionLocal() as session1:
            # 1. Lock the version FOR UPDATE
            stmt = select(RubricVersion).where(RubricVersion.id == vid).with_for_update()
            v = (await session1.execute(stmt)).scalars().first()
            assert v is not None

            # Signal that lock is held
            session1_locked.set()

            # Hold lock for 0.4 seconds to let worker_add run concurrently
            await asyncio.sleep(0.4)

            # Publish the version and commit
            v.status = "published"
            v.published_at = datetime.now(timezone.utc)
            await session1.commit()

    async def worker_add():
        # Wait until worker_publish holds the lock
        await session1_locked.wait()
        async with AsyncSessionLocal() as session2:
            try:
                # Attempt to add criterion (will block on FOR UPDATE on version)
                await add_rubric_criterion(
                    db=session2,
                    rubric_version_id=vid,
                    title="Sneak Concurrent Criterion",
                    description="Should be rejected",
                    weight=Decimal("0.5000"),
                    organization_id=ctx["org_id"],
                )
                await session2.commit()
                session2_result["status"] = "success"
            except AppException as exc:
                session2_result["status"] = "error"
                session2_result["error"] = exc.code
            finally:
                session2_done.set()

    await asyncio.gather(worker_publish(), worker_add())
    await session2_done.wait()

    # Session 2 must have failed with RUBRIC_VERSION_FROZEN after Session 1 committed!
    assert session2_result["status"] == "error"
    assert session2_result["error"] == "RUBRIC_VERSION_FROZEN"

    # Verify final criteria count: exactly 1 criterion, sum of weights = 1.0000
    async with AsyncSessionLocal() as verify_session:
        stmt = select(RubricCriterion).where(RubricCriterion.rubric_version_id == vid)
        criteria = (await verify_session.execute(stmt)).scalars().all()
        assert len(criteria) == 1
        assert criteria[0].weight == Decimal("1.0000")


@pytest.mark.asyncio
async def test_finding_4_concurrent_publish_calls_serialize(remediation_context):
    """
    Two sessions concurrently call publish_rubric_version.
    Exactly one succeeds and the other receives RUBRIC_ALREADY_PUBLISHED.
    """
    ctx = remediation_context

    async with AsyncSessionLocal() as init_session:
        rubric = await create_rubric(init_session, ctx["org_id"], ctx["hackathon_id"], "F4 Serialize Rubric")
        stmt = select(RubricVersion).where(RubricVersion.rubric_id == rubric.id)
        version = (await init_session.execute(stmt)).scalars().first()
        await add_rubric_criterion(init_session, version.id, "C1", "D", Decimal("1.0000"))
        await init_session.commit()
        vid = version.id

    results = []

    async def call_publish():
        async with AsyncSessionLocal() as session:
            try:
                await publish_rubric_version(session, ctx["org_id"], vid)
                await session.commit()
                results.append("success")
            except AppException as exc:
                results.append(exc.code)

    await asyncio.gather(call_publish(), call_publish())
    assert results.count("success") == 1
    assert results.count("RUBRIC_ALREADY_PUBLISHED") == 1


# ==============================================================================
# Finding 3.1 Tests: Calculator Duplicate Criterion ID Detection
# ==============================================================================
def test_calculator_rejects_duplicate_criterion_id():
    cid = str(uuid.uuid4())
    criteria = [
        CriterionInput(
            criterion_id=cid,
            weight=Decimal("0.5000"),
            min_score=Decimal("0.00"),
            max_score=Decimal("10.00"),
            awarded_score=Decimal("5.00"),
        ),
        CriterionInput(
            criterion_id=cid,  # DUPLICATE!
            weight=Decimal("0.5000"),
            min_score=Decimal("0.00"),
            max_score=Decimal("10.00"),
            awarded_score=Decimal("5.00"),
        ),
    ]

    with pytest.raises(ValueError) as exc:
        validate_criteria_weights(criteria)
    assert f"Duplicate criterion_id '{cid}' detected" in str(exc.value)

    with pytest.raises(ValueError) as exc_calc:
        calculate_evaluation_scores(criteria)
    assert f"Duplicate criterion_id '{cid}' detected" in str(exc_calc.value)

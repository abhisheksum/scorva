from decimal import Decimal
import uuid
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.modules.evaluations.models import (
    EvaluationJob,
    EvaluationResult,
    HackathonJudge,
    OrganizationIntegration,
    Rubric,
    RubricCriterion,
    RubricVersion,
    Submission,
    SubmissionSnapshot,
    Team,
    TeamMember,
)
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.modules.organizations.models import Organization, OrganizationStatus
from apps.api.modules.users.models import PlatformRole, User


@pytest.fixture
async def setup_eval_env(db_session: AsyncSession):
    """Sets up user, organization, and hackathon for database constraint testing."""
    user = User(
        email=f"eval_test_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="fakehash",
        full_name="Constraint Tester",
        platform_role=None,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    user2 = User(
        email=f"eval_test2_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="fakehash",
        full_name="Second Tester",
        platform_role=None,
        is_active=True,
    )
    db_session.add(user2)
    await db_session.flush()

    org = Organization(
        name="Eval Constraint Org",
        slug=f"eval-org-{uuid.uuid4().hex[:8]}",
        owner_id=user.id,
        status=OrganizationStatus.ACTIVE,
    )
    db_session.add(org)
    await db_session.flush()

    hackathon = Hackathon(
        organization_id=org.id,
        title="Eval Constraint Hackathon",
        slug=f"eval-hack-{uuid.uuid4().hex[:8]}",
        status=HackathonStatus.PUBLISHED,
        start_date=text("now()"),
        end_date=text("now() + interval '7 days'"),
        submission_deadline=text("now() + interval '6 days'"),
        created_by_user_id=user.id,
    )
    db_session.add(hackathon)
    await db_session.commit()

    return user, user2, org, hackathon


@pytest.mark.asyncio
async def test_uq_teams_hackathon_name(db_session: AsyncSession, setup_eval_env):
    """Assert duplicate team name in same hackathon is rejected by unique constraint."""
    user, _, org, hackathon = setup_eval_env

    t1 = Team(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name="Team Alpha",
        join_code=uuid.uuid4().hex[:12],
        created_by_user_id=user.id,
    )
    db_session.add(t1)
    await db_session.flush()

    t2 = Team(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name="Team Alpha",  # duplicate name
        join_code=uuid.uuid4().hex[:12],
        created_by_user_id=user.id,
    )
    db_session.add(t2)
    with pytest.raises(IntegrityError) as exc:
        await db_session.flush()
    await db_session.rollback()
    assert "uq_teams_hackathon_name" in str(exc.value)


@pytest.mark.asyncio
async def test_uq_team_members_team_user(db_session: AsyncSession, setup_eval_env):
    """Assert user cannot join the same team twice."""
    user, _, org, hackathon = setup_eval_env

    team = Team(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name="Team Beta",
        join_code=uuid.uuid4().hex[:12],
        created_by_user_id=user.id,
    )
    db_session.add(team)
    await db_session.flush()

    m1 = TeamMember(team_id=team.id, user_id=user.id, role_in_team="leader")
    db_session.add(m1)
    await db_session.flush()

    m2 = TeamMember(team_id=team.id, user_id=user.id, role_in_team="member")
    db_session.add(m2)
    with pytest.raises(IntegrityError) as exc:
        await db_session.flush()
    await db_session.rollback()
    assert "uq_team_members_team_user" in str(exc.value)


@pytest.mark.asyncio
async def test_uq_submissions_hackathon_repo_active(db_session: AsyncSession, setup_eval_env):
    """
    Assert partial unique index rejects duplicate active repository URLs in same hackathon,
    but allows re-submission if deleted_at is set.
    """
    user, _, org, hackathon = setup_eval_env

    team = Team(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name="Team Submissions",
        join_code=uuid.uuid4().hex[:12],
        created_by_user_id=user.id,
    )
    db_session.add(team)
    await db_session.flush()

    repo_url = "https://github.com/scorva-org/sample-project"
    sub1 = Submission(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        team_id=team.id,
        team_name=team.name,
        repository_url=repo_url,
        target_branch="main",
        title="Project 1",
    )
    db_session.add(sub1)
    await db_session.flush()

    # Second active submission with same repo -> rejected
    sub2 = Submission(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        team_id=team.id,
        team_name=team.name,
        repository_url=repo_url,
        target_branch="main",
        title="Project 2",
    )
    db_session.add(sub2)
    with pytest.raises(IntegrityError) as exc:
        await db_session.flush()
    await db_session.rollback()
    assert "uq_submissions_hackathon_repo_active" in str(exc.value)


@pytest.mark.asyncio
async def test_uq_rubric_versions_version_number(db_session: AsyncSession, setup_eval_env):
    """Assert unique version numbers per rubric."""
    _, _, org, hackathon = setup_eval_env

    rubric = Rubric(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name="Unique Version Rubric",
    )
    db_session.add(rubric)
    await db_session.flush()

    v1_a = RubricVersion(
        organization_id=org.id,
        rubric_id=rubric.id,
        version_number=1,
        status="draft",
    )
    db_session.add(v1_a)
    await db_session.flush()

    v1_b = RubricVersion(
        organization_id=org.id,
        rubric_id=rubric.id,
        version_number=1,
        status="draft",
    )
    db_session.add(v1_b)
    with pytest.raises(IntegrityError) as exc:
        await db_session.flush()
    await db_session.rollback()
    assert "uq_rubric_versions_rubric_version" in str(exc.value)


@pytest.mark.asyncio
async def test_chk_rubric_criteria_min_max_and_weight(db_session: AsyncSession, setup_eval_env):
    """Assert check constraints on rubric criteria min/max scores and weights."""
    _, _, org, hackathon = setup_eval_env

    rubric = Rubric(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name="Criteria Check Rubric",
    )
    db_session.add(rubric)
    await db_session.flush()

    version = RubricVersion(
        organization_id=org.id,
        rubric_id=rubric.id,
        version_number=1,
    )
    db_session.add(version)
    await db_session.flush()

    # 1. min_score >= max_score fails chk_rubric_criteria_min_max
    bad_min_max = RubricCriterion(
        rubric_version_id=version.id,
        title="Bad Min Max",
        description="Desc",
        weight=Decimal("0.5000"),
        min_score=Decimal("10.00"),
        max_score=Decimal("5.00"),  # min > max
        evidence_requirements="Req",
    )
    db_session.add(bad_min_max)
    with pytest.raises(IntegrityError) as exc_min_max:
        await db_session.flush()
    await db_session.rollback()
    assert "chk_rubric_criteria_min_max" in str(exc_min_max.value)

    # 2. weight <= 0 fails chk_rubric_criteria_weight
    bad_weight = RubricCriterion(
        rubric_version_id=version.id,
        title="Bad Weight",
        description="Desc",
        weight=Decimal("0.0000"),  # weight <= 0
        min_score=Decimal("0.00"),
        max_score=Decimal("10.00"),
        evidence_requirements="Req",
    )
    db_session.add(bad_weight)
    with pytest.raises(IntegrityError) as exc_weight:
        await db_session.flush()
    await db_session.rollback()
    assert "chk_rubric_criteria_weight" in str(exc_weight.value)


@pytest.mark.asyncio
async def test_uq_submission_snapshots_commit(db_session: AsyncSession, setup_eval_env):
    """Assert unique commit_sha per submission."""
    user, _, org, hackathon = setup_eval_env

    team = Team(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name="Team Snapshot",
        join_code=uuid.uuid4().hex[:12],
        created_by_user_id=user.id,
    )
    db_session.add(team)
    await db_session.flush()

    sub = Submission(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        team_id=team.id,
        team_name=team.name,
        repository_url="https://github.com/scorva/test-repo-snapshot",
        target_branch="main",
        title="Snapshot Project",
    )
    db_session.add(sub)
    await db_session.flush()

    commit_sha = "a" * 40
    snap1 = SubmissionSnapshot(
        organization_id=org.id,
        submission_id=sub.id,
        commit_sha=commit_sha,
        file_count=10,
        total_bytes=1024,
        configuration_snapshot={"eval_mode": "strict", "scoring_mode": "offset_normalized"},
    )
    db_session.add(snap1)
    await db_session.flush()

    snap2 = SubmissionSnapshot(
        organization_id=org.id,
        submission_id=sub.id,
        commit_sha=commit_sha,  # duplicate commit
        file_count=10,
        total_bytes=1024,
        configuration_snapshot={"eval_mode": "strict", "scoring_mode": "offset_normalized"},
    )
    db_session.add(snap2)
    with pytest.raises(IntegrityError) as exc:
        await db_session.flush()
    await db_session.rollback()
    assert "uq_submission_snapshots_submission_commit" in str(exc.value)


@pytest.mark.asyncio
async def test_configuration_snapshot_jsonb_persistence(db_session: AsyncSession, setup_eval_env):
    """Assert submission_snapshots accurately persists frozen configuration JSONB."""
    user, _, org, hackathon = setup_eval_env

    team = Team(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name="Team Config Freeze",
        join_code=uuid.uuid4().hex[:12],
        created_by_user_id=user.id,
    )
    db_session.add(team)
    await db_session.flush()

    sub = Submission(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        team_id=team.id,
        team_name=team.name,
        repository_url="https://github.com/scorva/test-config-freeze",
        target_branch="main",
        title="Frozen Config Project",
    )
    db_session.add(sub)
    await db_session.flush()

    config_payload = {
        "scoring.mode": "offset_normalized",
        "eval.max_attempts": 3,
        "evidence.grounding_required": True,
        "judge.rationale_min_length": 30,
    }

    snap = SubmissionSnapshot(
        organization_id=org.id,
        submission_id=sub.id,
        commit_sha="b" * 40,
        file_count=42,
        total_bytes=1048576,
        configuration_snapshot=config_payload,
    )
    db_session.add(snap)
    await db_session.commit()

    # Re-fetch and assert exact JSON structure
    fetched = await db_session.get(SubmissionSnapshot, snap.id)
    assert fetched is not None
    assert fetched.configuration_snapshot == config_payload
    assert fetched.configuration_snapshot["scoring.mode"] == "offset_normalized"


@pytest.mark.asyncio
async def test_uq_evaluation_results_job_attempt(db_session: AsyncSession, setup_eval_env):
    """Assert unique attempt_number per evaluation job."""
    user, _, org, hackathon = setup_eval_env

    team = Team(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name="Team Eval Res",
        join_code=uuid.uuid4().hex[:12],
        created_by_user_id=user.id,
    )
    db_session.add(team)
    await db_session.flush()

    sub = Submission(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        team_id=team.id,
        team_name=team.name,
        repository_url="https://github.com/scorva/eval-results-test",
        target_branch="main",
        title="Eval Res Project",
    )
    db_session.add(sub)
    await db_session.flush()

    snap = SubmissionSnapshot(
        organization_id=org.id,
        submission_id=sub.id,
        commit_sha="c" * 40,
        file_count=5,
        total_bytes=512,
        configuration_snapshot={"mode": "default"},
    )
    db_session.add(snap)
    await db_session.flush()

    rubric = Rubric(organization_id=org.id, hackathon_id=hackathon.id, name="Job Rubric")
    db_session.add(rubric)
    await db_session.flush()

    r_version = RubricVersion(organization_id=org.id, rubric_id=rubric.id, version_number=1)
    db_session.add(r_version)
    await db_session.flush()

    job = EvaluationJob(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=sub.id,
        snapshot_id=snap.id,
        rubric_version_id=r_version.id,
        status="running",
    )
    db_session.add(job)
    await db_session.flush()

    r1 = EvaluationResult(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=sub.id,
        rubric_version_id=r_version.id,
        job_id=job.id,
        snapshot_id=snap.id,
        attempt_number=1,
        model_provider="ollama",
        model_name="llama3:8b",
        prompt_version="v1.0",
        raw_score=Decimal("85.00"),
        normalized_score=Decimal("85.00"),
        summary_assessment="Solid evaluation output.",
    )
    db_session.add(r1)
    await db_session.flush()

    r2 = EvaluationResult(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        submission_id=sub.id,
        rubric_version_id=r_version.id,
        job_id=job.id,
        snapshot_id=snap.id,
        attempt_number=1,  # duplicate attempt number
        model_provider="ollama",
        model_name="llama3:8b",
        prompt_version="v1.0",
        raw_score=Decimal("86.00"),
        normalized_score=Decimal("86.00"),
        summary_assessment="Duplicate attempt.",
    )
    db_session.add(r2)
    with pytest.raises(IntegrityError) as exc:
        await db_session.flush()
    await db_session.rollback()
    assert "uq_evaluation_results_job_attempt" in str(exc.value)


@pytest.mark.asyncio
async def test_uq_hackathon_judges(db_session: AsyncSession, setup_eval_env):
    """Assert duplicate judge assignment to same hackathon is rejected."""
    user, _, _, hackathon = setup_eval_env

    j1 = HackathonJudge(hackathon_id=hackathon.id, user_id=user.id)
    db_session.add(j1)
    await db_session.flush()

    j2 = HackathonJudge(hackathon_id=hackathon.id, user_id=user.id)
    db_session.add(j2)
    with pytest.raises(IntegrityError) as exc:
        await db_session.flush()
    await db_session.rollback()
    assert "uq_hackathon_judges_hackathon_user" in str(exc.value)


@pytest.mark.asyncio
async def test_uq_organization_integrations_active_provider(db_session: AsyncSession, setup_eval_env):
    """Assert unique active provider integration per organization."""
    user, _, org, _ = setup_eval_env

    i1 = OrganizationIntegration(
        organization_id=org.id,
        provider="github",
        credential_type="pat",
        encrypted_token=b"fake_encrypted_bytes",
        token_preview="ghp_****1234",
        created_by_user_id=user.id,
    )
    db_session.add(i1)
    await db_session.flush()

    i2 = OrganizationIntegration(
        organization_id=org.id,
        provider="github",
        credential_type="pat",
        encrypted_token=b"fake_encrypted_bytes_2",
        token_preview="ghp_****5678",
        created_by_user_id=user.id,
    )
    db_session.add(i2)
    with pytest.raises(IntegrityError) as exc:
        await db_session.flush()
    await db_session.rollback()
    assert "uq_org_integrations_org_provider_active" in str(exc.value)


@pytest.mark.asyncio
async def test_on_delete_restrict_on_organizations(
    db_session: AsyncSession, setup_eval_env
):
    """Assert ON DELETE RESTRICT blocks accidental cascade deletion of organizations."""
    user, _, org, hackathon = setup_eval_env

    team = Team(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name="Team Restrict Org",
        join_code=uuid.uuid4().hex[:12],
        created_by_user_id=user.id,
    )
    db_session.add(team)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await db_session.delete(org)
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_on_delete_restrict_on_hackathons(
    db_session: AsyncSession, setup_eval_env
):
    """Assert ON DELETE RESTRICT blocks accidental cascade deletion of hackathons."""
    user, _, org, hackathon = setup_eval_env

    team = Team(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name="Team Restrict Hack",
        join_code=uuid.uuid4().hex[:12],
        created_by_user_id=user.id,
    )
    db_session.add(team)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await db_session.delete(hackathon)
        await db_session.flush()
    await db_session.rollback()

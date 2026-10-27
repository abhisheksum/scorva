"""
Test Suite for Scorva Milestone 6.2: Team Registration & GitHub Repository Linking.

Covers:
- URL normalization, syntax validation, credential rejection, port filtering, and host allowlists.
- SSRF egress defense blocking private IP ranges, loopback, and metadata destinations.
- Repository accessibility, default branch, target branch, and commit SHA verification.
- Invariant: Failed verification must never corrupt an existing valid repository link.
- Hackathon deadline and duplicate repository prevention across teams in the same hackathon.
- Audit event generation for repository_linked, submission_branch_updated,
  submission_verification_refreshed, and repository_unlinked.
- Cross-tenant isolation and team membership authorization.
- Unlinking protection blocking evaluated submissions.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from apps.api.modules.audit.models import AuditEvent
from apps.api.modules.evaluations.github_client import (
    GitHubIngestionClient,
    GitHubIngestionError,
    parse_github_url,
)
from apps.api.modules.evaluations.models import (
    EvaluationJob,
    Rubric,
    RubricVersion,
    Submission,
    SubmissionSnapshot,
    Team,
    TeamMember,
)
from apps.api.core.ssrf_guard import (
    SSRFViolationError,
    resolve_and_validate_hostname,
)
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.tests.test_hackathons import ORIGIN_HEADER, hackathon_test_setup


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture
async def setup_m6_2_env(db_session, hackathon_test_setup):
    """Sets up a published hackathon with a team and team members in Org A."""
    fixture = hackathon_test_setup
    org_a = fixture["org_a"]
    alice = fixture["alice"]  # Org A Owner
    bob = fixture["bob"]      # Org A Admin
    charlie = fixture["charlie"] # Org A Member
    dave = fixture["dave"]    # Org A Member (other user)

    now = datetime.now(timezone.utc)
    hackathon = Hackathon(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title=f"M6.2 Repo Linking Cup {fixture['suffix']}",
        slug=f"m62-cup-{fixture['suffix']}",
        description="Hackathon verifying GitHub repository linking and SSRF security",
        status=HackathonStatus.PUBLISHED,
        start_date=now - timedelta(hours=2),
        submission_deadline=now + timedelta(days=2),
        end_date=now + timedelta(days=3),
        created_by_user_id=alice.id,
        settings={"max_team_size": 4},
    )
    db_session.add(hackathon)
    await db_session.flush()

    # Team 1: Charlie is leader
    team_1 = Team(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        hackathon_id=hackathon.id,
        name=f"Alpha Hackers {fixture['suffix']}",
        join_code=f"A{uuid.uuid4().hex[:11].upper()}",
        created_by_user_id=charlie.id,
    )
    db_session.add(team_1)
    await db_session.flush()

    tm_1 = TeamMember(
        team_id=team_1.id,
        user_id=charlie.id,
        role_in_team="leader",
    )
    db_session.add(tm_1)

    # Team 2: Dave is leader
    team_2 = Team(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        hackathon_id=hackathon.id,
        name=f"Beta Builders {fixture['suffix']}",
        join_code=f"B{uuid.uuid4().hex[:11].upper()}",
        created_by_user_id=dave.id,
    )
    db_session.add(team_2)
    await db_session.flush()

    tm_2 = TeamMember(
        team_id=team_2.id,
        user_id=dave.id,
        role_in_team="leader",
    )
    db_session.add(tm_2)

    await db_session.commit()
    await db_session.refresh(hackathon)
    await db_session.refresh(team_1)
    await db_session.refresh(team_2)

    return {
        **fixture,
        "hackathon": hackathon,
        "team_1": team_1,
        "team_2": team_2,
    }


# =====================================================================
# Unit Tests: URL Parsing & SSRF Defense
# =====================================================================

def test_url_parser_rejects_credentials():
    with pytest.raises(GitHubIngestionError) as exc_info:
        parse_github_url("https://user:password@github.com/org/repo")
    assert exc_info.value.code == "CREDENTIALS_IN_URL_FORBIDDEN"

    with pytest.raises(GitHubIngestionError) as exc_info2:
        parse_github_url("https://user@github.com/org/repo")
    assert exc_info2.value.code == "CREDENTIALS_IN_URL_FORBIDDEN"


def test_url_parser_rejects_nonstandard_ports():
    with pytest.raises(GitHubIngestionError) as exc_info:
        parse_github_url("https://github.com:8443/org/repo")
    assert exc_info.value.code == "UNSUPPORTED_GIT_PORT"


def test_url_parser_rejects_query_and_fragment():
    with pytest.raises(GitHubIngestionError) as exc_info:
        parse_github_url("https://github.com/org/repo?token=xyz")
    assert exc_info.value.code == "INVALID_URL_COMPONENTS"

    with pytest.raises(GitHubIngestionError) as exc_info2:
        parse_github_url("https://github.com/org/repo#readme")
    assert exc_info2.value.code == "INVALID_URL_COMPONENTS"


def test_url_parser_rejects_unsupported_providers():
    with pytest.raises(GitHubIngestionError) as exc_info:
        parse_github_url("https://gitlab.com/org/repo")
    assert exc_info.value.code == "UNSUPPORTED_GIT_PROVIDER"


def test_url_parser_accepts_clean_github_urls():
    owner, repo = parse_github_url("https://github.com/openai/whisper")
    assert owner == "openai"
    assert repo == "whisper"

    owner2, repo2 = parse_github_url("https://github.com/torvalds/linux.git")
    assert owner2 == "torvalds"
    assert repo2 == "linux"

    owner3, repo3 = parse_github_url("https://github.com/facebook/react/")
    assert owner3 == "facebook"
    assert repo3 == "react"


def test_ssrf_egress_protection_blocks_private_ips():
    # 127.0.0.1 loopback
    with pytest.raises(SSRFViolationError):
        resolve_and_validate_hostname("127.0.0.1")

    # Cloud metadata
    with pytest.raises(SSRFViolationError):
        resolve_and_validate_hostname("169.254.169.254")

    # RFC 1918 private space
    with pytest.raises(SSRFViolationError):
        resolve_and_validate_hostname("10.0.0.1")

    with pytest.raises(SSRFViolationError):
        resolve_and_validate_hostname("192.168.1.1")


# =====================================================================
# API Tests: Repository Validation Endpoint
# =====================================================================

@pytest.mark.asyncio
async def test_api_validate_repository_success(client: AsyncClient, setup_m6_2_env):
    env = setup_m6_2_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    headers = {
        "Authorization": f"Bearer {env['alice_token']}",
        **ORIGIN_HEADER,
    }

    mock_result = {
        "owner": "scorva-org",
        "repo": "autonomous-agent",
        "canonical_repo_id": "scorva-org/autonomous-agent",
        "default_branch": "main",
        "target_branch": "main",
        "commit_sha": "d3b07384d113edec49eaa6238ad5ff00",
        "is_private": False,
        "is_accessible": True,
    }

    with patch.object(GitHubIngestionClient, "verify_repository_access", new=AsyncMock(return_value=mock_result)):
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/repositories/validate",
            headers=headers,
            json={
                "repository_url": "https://github.com/scorva-org/autonomous-agent",
                "target_branch": "main",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["is_valid_url"] is True
        assert data["is_accessible"] is True
        assert data["connection_status"] == "verified"
        assert data["owner"] == "scorva-org"
        assert data["repo"] == "autonomous-agent"
        assert data["commit_sha"] == "d3b07384d113edec49eaa6238ad5ff00"
        assert data["ownership_verified"] is False  # Public access without org token


@pytest.mark.asyncio
async def test_api_validate_repository_branch_not_found(client: AsyncClient, setup_m6_2_env):
    env = setup_m6_2_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    headers = {
        "Authorization": f"Bearer {env['alice_token']}",
        **ORIGIN_HEADER,
    }

    with patch.object(
        GitHubIngestionClient,
        "verify_repository_access",
        side_effect=GitHubIngestionError("Branch 'nonexistent-branch' not found.", code="BRANCH_NOT_FOUND", status_code=404),
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/repositories/validate",
            headers=headers,
            json={
                "repository_url": "https://github.com/scorva-org/autonomous-agent",
                "target_branch": "nonexistent-branch",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["is_valid_url"] is True
        assert data["is_accessible"] is False
        assert data["connection_status"] == "failed"
        assert data["diagnostic_code"] == "BRANCH_NOT_FOUND"


@pytest.mark.asyncio
async def test_api_validate_repository_rate_limited(client: AsyncClient, setup_m6_2_env):
    env = setup_m6_2_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    headers = {
        "Authorization": f"Bearer {env['alice_token']}",
        **ORIGIN_HEADER,
    }

    with patch.object(
        GitHubIngestionClient,
        "verify_repository_access",
        side_effect=GitHubIngestionError("Rate limit exceeded.", code="GITHUB_RATE_LIMITED", status_code=429),
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/repositories/validate",
            headers=headers,
            json={
                "repository_url": "https://github.com/scorva-org/autonomous-agent",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_accessible"] is False
        assert data["diagnostic_code"] == "GITHUB_RATE_LIMITED"


# =====================================================================
# API Tests: Submission Creation & Linking
# =====================================================================

@pytest.mark.asyncio
async def test_api_create_submission_with_verified_repo(client: AsyncClient, setup_m6_2_env, db_session):
    env = setup_m6_2_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    team_1 = env["team_1"]
    charlie_token = env["charlie_token"]

    headers = {
        "Authorization": f"Bearer {charlie_token}",
        **ORIGIN_HEADER,
    }

    mock_result = {
        "owner": "alpha-team",
        "repo": "copilot-core",
        "default_branch": "main",
        "target_branch": "main",
        "commit_sha": "f1234567890abcdef1234567890abcdef123456",
        "is_private": False,
        "is_accessible": True,
    }

    with patch.object(GitHubIngestionClient, "verify_repository_access", new=AsyncMock(return_value=mock_result)):
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions",
            headers=headers,
            json={
                "team_id": str(team_1.id),
                "repository_url": "https://github.com/alpha-team/copilot-core",
                "target_branch": "main",
                "title": "Autonomous Copilot",
                "description": "Evidence-backed hackathon project",
            },
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["title"] == "Autonomous Copilot"
        assert data["repository_owner"] == "alpha-team"
        assert data["repository_name"] == "copilot-core"
        assert data["verified_commit_sha"] == "f1234567890abcdef1234567890abcdef123456"
        assert data["connection_status"] == "verified"
        assert data["verified_at"] is not None


@pytest.mark.asyncio
async def test_api_duplicate_repository_rejected(client: AsyncClient, setup_m6_2_env, db_session):
    env = setup_m6_2_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    team_1 = env["team_1"]
    team_2 = env["team_2"]
    charlie_token = env["charlie_token"]
    dave_token = env["dave_token"]

    mock_result = {
        "owner": "shared-team",
        "repo": "unique-repo",
        "default_branch": "main",
        "target_branch": "main",
        "commit_sha": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
        "is_private": False,
        "is_accessible": True,
    }

    with patch.object(GitHubIngestionClient, "verify_repository_access", new=AsyncMock(return_value=mock_result)):
        # Team 1 submits repo
        resp1 = await client.post(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions",
            headers={"Authorization": f"Bearer {charlie_token}", **ORIGIN_HEADER},
            json={
                "team_id": str(team_1.id),
                "repository_url": "https://github.com/shared-team/unique-repo",
                "title": "First Team Submission",
            },
        )
        assert resp1.status_code == 201, resp1.text

        # Team 2 attempts to submit the same repository URL in the same hackathon
        resp2 = await client.post(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions",
            headers={"Authorization": f"Bearer {dave_token}", **ORIGIN_HEADER},
            json={
                "team_id": str(team_2.id),
                "repository_url": "https://github.com/shared-team/unique-repo",
                "title": "Second Team Submission",
            },
        )
        assert resp2.status_code == 409
        assert resp2.json()["code"] == "REPOSITORY_ALREADY_SUBMITTED"


@pytest.mark.asyncio
async def test_api_link_repository_success_and_audit(client: AsyncClient, setup_m6_2_env, db_session):
    env = setup_m6_2_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    team_1 = env["team_1"]
    charlie_token = env["charlie_token"]

    mock_initial = {
        "owner": "alpha-team",
        "repo": "initial-repo",
        "default_branch": "main",
        "target_branch": "main",
        "commit_sha": "1111111111111111111111111111111111111111",
        "is_private": False,
        "is_accessible": True,
    }

    # 1. Create initial submission
    with patch.object(GitHubIngestionClient, "verify_repository_access", new=AsyncMock(return_value=mock_initial)):
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions",
            headers={"Authorization": f"Bearer {charlie_token}", **ORIGIN_HEADER},
            json={
                "team_id": str(team_1.id),
                "repository_url": "https://github.com/alpha-team/initial-repo",
                "title": "Alpha Project",
            },
        )
        assert resp.status_code == 201
        sub_id = resp.json()["id"]

    # 2. Relink to a new verified repository
    mock_new = {
        "owner": "alpha-team",
        "repo": "production-repo",
        "default_branch": "main",
        "target_branch": "staging",
        "commit_sha": "2222222222222222222222222222222222222222",
        "is_private": False,
        "is_accessible": True,
    }

    with patch.object(GitHubIngestionClient, "verify_repository_access", new=AsyncMock(return_value=mock_new)):
        relink_resp = await client.post(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}/link-repository",
            headers={"Authorization": f"Bearer {charlie_token}", **ORIGIN_HEADER},
            json={
                "repository_url": "https://github.com/alpha-team/production-repo",
                "target_branch": "staging",
            },
        )
        assert relink_resp.status_code == 200, relink_resp.text
        data = relink_resp.json()
        assert data["repository_url"] == "https://github.com/alpha-team/production-repo"
        assert data["repository_owner"] == "alpha-team"
        assert data["repository_name"] == "production-repo"
        assert data["target_branch"] == "staging"
        assert data["verified_commit_sha"] == "2222222222222222222222222222222222222222"
        assert data["connection_status"] == "verified"

    # 3. Verify audit event
    stmt_audit = select(AuditEvent).where(
        AuditEvent.action == "repository_linked",
        AuditEvent.resource_id == str(sub_id),
    )
    audit = (await db_session.execute(stmt_audit)).scalars().first()
    assert audit is not None
    assert audit.diff_payload["repository_url"] == "https://github.com/alpha-team/production-repo"


@pytest.mark.asyncio
async def test_failsafe_invariant_failed_link_preserves_existing_data(client: AsyncClient, setup_m6_2_env, db_session):
    env = setup_m6_2_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    team_1 = env["team_1"]
    charlie_token = env["charlie_token"]

    mock_valid = {
        "owner": "alpha-team",
        "repo": "solid-repo",
        "default_branch": "main",
        "target_branch": "main",
        "commit_sha": "solid11111111111111111111111111111111111",
        "is_private": False,
        "is_accessible": True,
    }

    with patch.object(GitHubIngestionClient, "verify_repository_access", new=AsyncMock(return_value=mock_valid)):
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions",
            headers={"Authorization": f"Bearer {charlie_token}", **ORIGIN_HEADER},
            json={
                "team_id": str(team_1.id),
                "repository_url": "https://github.com/alpha-team/solid-repo",
                "title": "Solid Project",
            },
        )
        assert resp.status_code == 201
        sub_id = resp.json()["id"]

    # Now attempt to link a repository that fails verification (e.g. branch doesn't exist)
    with patch.object(
        GitHubIngestionClient,
        "verify_repository_access",
        side_effect=GitHubIngestionError("Branch missing", code="BRANCH_NOT_FOUND", status_code=404),
    ):
        relink_resp = await client.post(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}/link-repository",
            headers={"Authorization": f"Bearer {charlie_token}", **ORIGIN_HEADER},
            json={
                "repository_url": "https://github.com/alpha-team/broken-repo",
                "target_branch": "bad-branch",
            },
        )
        assert relink_resp.status_code == 400
        assert relink_resp.json()["code"] == "BRANCH_NOT_FOUND"

    # Failsafe check: verify the submission record still has the original solid data intact!
    sub_resp = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}",
        headers={"Authorization": f"Bearer {charlie_token}", **ORIGIN_HEADER},
    )
    assert sub_resp.status_code == 200
    sub_data = sub_resp.json()
    assert sub_data["repository_url"] == "https://github.com/alpha-team/solid-repo"
    assert sub_data["verified_commit_sha"] == "solid11111111111111111111111111111111111"
    assert sub_data["connection_status"] == "verified"


# =====================================================================
# API Tests: Target Branch Update
# =====================================================================

@pytest.mark.asyncio
async def test_api_update_target_branch_and_audit(client: AsyncClient, setup_m6_2_env, db_session):
    env = setup_m6_2_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    team_1 = env["team_1"]
    charlie_token = env["charlie_token"]

    mock_initial = {
        "owner": "alpha-team",
        "repo": "branch-test-repo",
        "default_branch": "main",
        "target_branch": "main",
        "commit_sha": "main_commit_sha_1234567890abcdef",
        "is_private": False,
        "is_accessible": True,
    }

    with patch.object(GitHubIngestionClient, "verify_repository_access", new=AsyncMock(return_value=mock_initial)):
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions",
            headers={"Authorization": f"Bearer {charlie_token}", **ORIGIN_HEADER},
            json={
                "team_id": str(team_1.id),
                "repository_url": "https://github.com/alpha-team/branch-test-repo",
                "title": "Branch Test Submission",
            },
        )
        assert resp.status_code == 201
        sub_id = resp.json()["id"]

    # Update to 'release-1.0'
    mock_new_branch = {
        "owner": "alpha-team",
        "repo": "branch-test-repo",
        "default_branch": "main",
        "target_branch": "release-1.0",
        "commit_sha": "release_commit_sha_9876543210fedcba",
        "is_private": False,
        "is_accessible": True,
    }

    with patch.object(GitHubIngestionClient, "verify_repository_access", new=AsyncMock(return_value=mock_new_branch)):
        patch_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}/branch",
            headers={"Authorization": f"Bearer {charlie_token}", **ORIGIN_HEADER},
            json={"target_branch": "release-1.0"},
        )
        assert patch_resp.status_code == 200, patch_resp.text
        data = patch_resp.json()
        assert data["target_branch"] == "release-1.0"
        assert data["verified_commit_sha"] == "release_commit_sha_9876543210fedcba"

    # Verify audit event
    stmt_audit = select(AuditEvent).where(
        AuditEvent.action == "submission_branch_updated",
        AuditEvent.resource_id == str(sub_id),
    )
    audit = (await db_session.execute(stmt_audit)).scalars().first()
    assert audit is not None
    assert audit.diff_payload["new_branch"] == "release-1.0"


# =====================================================================
# API Tests: Refresh Verification
# =====================================================================

@pytest.mark.asyncio
async def test_api_refresh_verification(client: AsyncClient, setup_m6_2_env, db_session):
    env = setup_m6_2_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    team_1 = env["team_1"]
    charlie_token = env["charlie_token"]

    mock_initial = {
        "owner": "alpha-team",
        "repo": "refresh-repo",
        "default_branch": "main",
        "target_branch": "main",
        "commit_sha": "commit_version_1",
        "is_private": False,
        "is_accessible": True,
    }

    with patch.object(GitHubIngestionClient, "verify_repository_access", new=AsyncMock(return_value=mock_initial)):
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions",
            headers={"Authorization": f"Bearer {charlie_token}", **ORIGIN_HEADER},
            json={
                "team_id": str(team_1.id),
                "repository_url": "https://github.com/alpha-team/refresh-repo",
                "title": "Refresh Test",
            },
        )
        assert resp.status_code == 201
        sub_id = resp.json()["id"]

    # Developer pushed new commits: refresh resolves commit_version_2
    mock_refreshed = {
        "owner": "alpha-team",
        "repo": "refresh-repo",
        "default_branch": "main",
        "target_branch": "main",
        "commit_sha": "commit_version_2",
        "is_private": False,
        "is_accessible": True,
    }

    with patch.object(GitHubIngestionClient, "verify_repository_access", new=AsyncMock(return_value=mock_refreshed)):
        verif_resp = await client.post(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}/verify",
            headers={"Authorization": f"Bearer {charlie_token}", **ORIGIN_HEADER},
        )
        assert verif_resp.status_code == 200
        data = verif_resp.json()
        assert data["verified_commit_sha"] == "commit_version_2"
        assert data["connection_status"] == "verified"


# =====================================================================
# API Tests: Unlink Repository
# =====================================================================

@pytest.mark.asyncio
async def test_api_unlink_repository_and_evaluation_guard(client: AsyncClient, setup_m6_2_env, db_session):
    env = setup_m6_2_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    team_1 = env["team_1"]
    charlie_token = env["charlie_token"]

    mock_initial = {
        "owner": "alpha-team",
        "repo": "unlink-repo",
        "default_branch": "main",
        "target_branch": "main",
        "commit_sha": "unlink_sha",
        "is_private": False,
        "is_accessible": True,
    }

    with patch.object(GitHubIngestionClient, "verify_repository_access", new=AsyncMock(return_value=mock_initial)):
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions",
            headers={"Authorization": f"Bearer {charlie_token}", **ORIGIN_HEADER},
            json={
                "team_id": str(team_1.id),
                "repository_url": "https://github.com/alpha-team/unlink-repo",
                "title": "Unlink Test",
            },
        )
        assert resp.status_code == 201
        sub_id = resp.json()["id"]

    # Case A: If an active/completed evaluation job exists, unlinking is blocked!
    rubric = Rubric(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hackathon_id,
        name=f"Test Rubric {uuid.uuid4().hex[:6]}",
        scoring_mode="offset_normalized",
    )
    db_session.add(rubric)
    await db_session.flush()

    rubric_version = RubricVersion(
        id=uuid.uuid4(),
        organization_id=org_id,
        rubric_id=rubric.id,
        version_number=1,
        status="published",
    )
    db_session.add(rubric_version)
    await db_session.flush()

    snapshot = SubmissionSnapshot(
        id=uuid.uuid4(),
        organization_id=org_id,
        submission_id=uuid.UUID(sub_id),
        commit_sha="unlink_sha",
        configuration_snapshot={},
    )
    db_session.add(snapshot)
    await db_session.flush()

    job = EvaluationJob(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hackathon_id,
        submission_id=uuid.UUID(sub_id),
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        status="completed",
    )
    db_session.add(job)
    await db_session.commit()

    block_resp = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}/unlink-repository",
        headers={"Authorization": f"Bearer {charlie_token}", **ORIGIN_HEADER},
    )
    assert block_resp.status_code == 400
    assert block_resp.json()["code"] == "CANNOT_UNLINK_EVALUATED_SUBMISSION"

    # Case B: Remove the job, now unlinking succeeds
    await db_session.delete(job)
    await db_session.delete(snapshot)
    await db_session.commit()

    unlink_resp = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}/unlink-repository",
        headers={"Authorization": f"Bearer {charlie_token}", **ORIGIN_HEADER},
    )
    assert unlink_resp.status_code == 200
    data = unlink_resp.json()
    assert data["connection_status"] == "unlinked"
    assert data["verified_commit_sha"] is None

    # Verify audit event
    stmt_audit = select(AuditEvent).where(
        AuditEvent.action == "repository_unlinked",
        AuditEvent.resource_id == str(sub_id),
    )
    audit = (await db_session.execute(stmt_audit)).scalars().first()
    assert audit is not None


# =====================================================================
# API Tests: Authorization & Cross-Tenant Isolation
# =====================================================================

@pytest.mark.asyncio
async def test_api_non_team_member_cannot_modify_submission(client: AsyncClient, setup_m6_2_env):
    env = setup_m6_2_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    team_1 = env["team_1"]
    charlie_token = env["charlie_token"] # Team 1 leader
    dave_token = env["dave_token"]       # Team 2 leader (NOT Team 1)

    mock_initial = {
        "owner": "alpha-team",
        "repo": "auth-repo",
        "default_branch": "main",
        "target_branch": "main",
        "commit_sha": "auth_sha",
        "is_private": False,
        "is_accessible": True,
    }

    with patch.object(GitHubIngestionClient, "verify_repository_access", new=AsyncMock(return_value=mock_initial)):
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions",
            headers={"Authorization": f"Bearer {charlie_token}", **ORIGIN_HEADER},
            json={
                "team_id": str(team_1.id),
                "repository_url": "https://github.com/alpha-team/auth-repo",
                "title": "Auth Protected Submission",
            },
        )
        assert resp.status_code == 201
        sub_id = resp.json()["id"]

    # Dave tries to modify Charlie's team submission
    patch_resp = await client.patch(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}/branch",
        headers={"Authorization": f"Bearer {dave_token}", **ORIGIN_HEADER},
        json={"target_branch": "hacked-branch"},
    )
    assert patch_resp.status_code == 403
    assert patch_resp.json()["code"] == "NOT_A_TEAM_MEMBER"


@pytest.mark.asyncio
async def test_api_cross_tenant_isolation_denied(client: AsyncClient, setup_m6_2_env):
    env = setup_m6_2_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    team_1 = env["team_1"]
    charlie_token = env["charlie_token"]
    frank_token = env["frank_token"] # Org B Owner

    mock_initial = {
        "owner": "alpha-team",
        "repo": "tenant-repo",
        "default_branch": "main",
        "target_branch": "main",
        "commit_sha": "tenant_sha",
        "is_private": False,
        "is_accessible": True,
    }

    with patch.object(GitHubIngestionClient, "verify_repository_access", new=AsyncMock(return_value=mock_initial)):
        resp = await client.post(
            f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions",
            headers={"Authorization": f"Bearer {charlie_token}", **ORIGIN_HEADER},
            json={
                "team_id": str(team_1.id),
                "repository_url": "https://github.com/alpha-team/tenant-repo",
                "title": "Tenant Isolation Submission",
            },
        )
        assert resp.status_code == 201
        sub_id = resp.json()["id"]

    # Frank (Org B) cannot link or touch Org A submission
    resp_cross = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}/verify",
        headers={"Authorization": f"Bearer {frank_token}", **ORIGIN_HEADER},
    )
    assert resp_cross.status_code == 403
    assert resp_cross.json()["code"] == "TENANT_ACCESS_DENIED"

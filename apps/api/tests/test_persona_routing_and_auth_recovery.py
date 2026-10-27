from datetime import datetime, timezone, timedelta
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from apps.api.modules.evaluations.models import (
    HackathonJudge,
    Rubric,
    RubricCriterion,
    RubricVersion,
    Submission,
    Team,
    TeamMember,
)
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.modules.organizations.models import (
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
    OrgRole,
)
from apps.api.modules.users.models import PlatformRole, User


@pytest.fixture
async def seeded_personas(db_session, create_user_helper):
    """Sets up a complete deterministic universe with all 4 personas and 2 organizations."""
    now = datetime.now(timezone.utc)

    # 1. Platform Admin
    admin = await create_user_helper(
        email="test_admin@scorva.io",
        password="AdminPassword123!",
        full_name="Platform Admin",
        platform_role=PlatformRole.PLATFORM_OWNER,
    )

    # 2. Org A Organizer
    organizer = await create_user_helper(
        email="test_organizer@scorva.io",
        password="OrgPassword123!",
        full_name="Alice Organizer",
        platform_role=None,
    )

    # 3. Judge
    judge = await create_user_helper(
        email="test_judge@scorva.io",
        password="JudgePassword123!",
        full_name="Carol Judge",
        platform_role=None,
    )

    # 4. Participant
    participant = await create_user_helper(
        email="test_participant@scorva.io",
        password="PartPassword123!",
        full_name="Bob Participant",
        platform_role=None,
    )

    # 5. Org B Organizer (for cross-tenant checks)
    other_organizer = await create_user_helper(
        email="test_other_organizer@scorva.io",
        password="OtherOrgPassword123!",
        full_name="Eve Other Organizer",
        platform_role=None,
    )

    # 6. Multi-role User (both Org Owner and Judge in another hackathon)
    multirole_user = await create_user_helper(
        email="test_multirole@scorva.io",
        password="MultiPassword123!",
        full_name="Dave MultiRole",
        platform_role=None,
    )

    # Create Organization A
    org_a = Organization(
        id=uuid.uuid4(),
        name="Nova Technologies",
        slug=f"nova-tech-{uuid.uuid4().hex[:6]}",
        owner_id=organizer.id,
        status=OrganizationStatus.ACTIVE,
    )
    db_session.add(org_a)
    await db_session.flush()

    mem_org_a = OrganizationMembership(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        user_id=organizer.id,
        role=OrgRole.ORG_OWNER,
        status=MembershipStatus.ACTIVE,
    )
    db_session.add(mem_org_a)

    # Create Organization B
    org_b = Organization(
        id=uuid.uuid4(),
        name="Apex Robotics",
        slug=f"apex-robotics-{uuid.uuid4().hex[:6]}",
        owner_id=other_organizer.id,
        status=OrganizationStatus.ACTIVE,
    )
    db_session.add(org_b)
    await db_session.flush()

    mem_org_b = OrganizationMembership(
        id=uuid.uuid4(),
        organization_id=org_b.id,
        user_id=other_organizer.id,
        role=OrgRole.ORG_OWNER,
        status=MembershipStatus.ACTIVE,
    )
    db_session.add(mem_org_b)

    # Organization for MultiRole User
    org_multi = Organization(
        id=uuid.uuid4(),
        name="Dave Labs",
        slug=f"dave-labs-{uuid.uuid4().hex[:6]}",
        owner_id=multirole_user.id,
        status=OrganizationStatus.ACTIVE,
    )
    db_session.add(org_multi)
    await db_session.flush()
    mem_multi = OrganizationMembership(
        id=uuid.uuid4(),
        organization_id=org_multi.id,
        user_id=multirole_user.id,
        role=OrgRole.ORG_OWNER,
        status=MembershipStatus.ACTIVE,
    )
    db_session.add(mem_multi)

    # Create Hackathon A under Org A
    hack_a = Hackathon(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title="Nova AI Hackathon",
        slug=f"nova-ai-{uuid.uuid4().hex[:6]}",
        description="University reasoning challenge",
        status=HackathonStatus.PUBLISHED,
        start_date=now - timedelta(days=2),
        end_date=now + timedelta(days=3),
        submission_deadline=now + timedelta(days=2),
        created_by_user_id=organizer.id,
    )
    db_session.add(hack_a)
    await db_session.flush()

    # Create Unassigned Hackathon under Org B
    hack_b = Hackathon(
        id=uuid.uuid4(),
        organization_id=org_b.id,
        title="Apex Robotics Cup",
        slug=f"apex-cup-{uuid.uuid4().hex[:6]}",
        status=HackathonStatus.PUBLISHED,
        start_date=now - timedelta(days=1),
        end_date=now + timedelta(days=4),
        submission_deadline=now + timedelta(days=3),
        created_by_user_id=other_organizer.id,
    )
    db_session.add(hack_b)
    await db_session.flush()

    # Assign Judge Carol to Hackathon A
    judge_assignment = HackathonJudge(
        id=uuid.uuid4(),
        hackathon_id=hack_a.id,
        user_id=judge.id,
        assigned_by_user_id=organizer.id,
    )
    db_session.add(judge_assignment)

    # Also assign MultiRole Dave as judge to Hackathon A
    judge_assignment_dave = HackathonJudge(
        id=uuid.uuid4(),
        hackathon_id=hack_a.id,
        user_id=multirole_user.id,
        assigned_by_user_id=organizer.id,
    )
    db_session.add(judge_assignment_dave)

    # Team & Submission in Hackathon A for Participant Bob
    team = Team(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        hackathon_id=hack_a.id,
        name="Team Alpha",
        join_code="ALPHA123456",
        created_by_user_id=participant.id,
    )
    db_session.add(team)
    await db_session.flush()

    tmem = TeamMember(
        id=uuid.uuid4(),
        team_id=team.id,
        user_id=participant.id,
        role_in_team="leader",
    )
    db_session.add(tmem)

    sub = Submission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        hackathon_id=hack_a.id,
        team_id=team.id,
        team_name=team.name,
        title="Autonomous AI Agent",
        description="Reasoning pipeline",
        repository_url="https://github.com/scorva-org/alpha-reasoning",
        target_branch="main",
        repository_owner="scorva-org",
        repository_name="alpha-reasoning",
        default_branch="main",
        verified_commit_sha="1234567890abcdef1234567890abcdef12345678",
        connection_status="verified",
        status="evaluated",
    )
    db_session.add(sub)

    await db_session.commit()

    return {
        "admin": admin,
        "organizer": organizer,
        "judge": judge,
        "participant": participant,
        "other_organizer": other_organizer,
        "multirole_user": multirole_user,
        "org_a": org_a,
        "org_b": org_b,
        "hack_a": hack_a,
        "hack_b": hack_b,
        "team": team,
        "submission": sub,
    }


# -----------------------------------------------------------------------------
# Regression Tests (Covering Acceptance Criteria 1 - 12)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_01_platform_admin_login_lands_on_admin(client: AsyncClient, seeded_personas):
    """1. Platform administrator can log in and reach /admin."""
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "test_admin@scorva.io", "password": "AdminPassword123!"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["mfa_required"] is False
    assert data["default_destination"] == "/admin"
    assert data["user"]["platform_role"] == "platform_owner"
    assert any(d["destination"] == "/admin" for d in data["user"]["routing"]["accessible_destinations"])


@pytest.mark.asyncio
async def test_02_organizer_login_lands_on_organization_workspace(client: AsyncClient, seeded_personas):
    """2. Organizer without a platform role can log in and reach an authorized organizer destination."""
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "test_organizer@scorva.io", "password": "OrgPassword123!"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["mfa_required"] is False
    assert data["user"]["platform_role"] is None
    expected_org_dest = f"/organizations/{seeded_personas['org_a'].id}"
    assert data["default_destination"] == expected_org_dest
    assert any(d["destination"] == expected_org_dest for d in data["user"]["routing"]["accessible_destinations"])


@pytest.mark.asyncio
async def test_03_judge_login_lands_on_judge_portal(client: AsyncClient, seeded_personas):
    """3. Assigned judge without a platform role can log in and reach /judge."""
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "test_judge@scorva.io", "password": "JudgePassword123!"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["mfa_required"] is False
    assert data["user"]["platform_role"] is None
    assert data["default_destination"] == "/judge"
    assert any(d["destination"] == "/judge" for d in data["user"]["routing"]["accessible_destinations"])


@pytest.mark.asyncio
async def test_04_participant_login_lands_on_participant_workspace(client: AsyncClient, seeded_personas):
    """4. Participant without a platform role can log in and reach /participant."""
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "test_participant@scorva.io", "password": "PartPassword123!"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["mfa_required"] is False
    assert data["user"]["platform_role"] is None
    assert data["default_destination"] == "/participant"
    assert any(d["destination"] == "/participant" for d in data["user"]["routing"]["accessible_destinations"])

    # Verify participant teams endpoint returns real team
    cookies = res.cookies
    teams_res = await client.get("/api/v1/participant/teams", cookies=cookies)
    assert teams_res.status_code == 200
    teams_data = teams_res.json()
    assert len(teams_data) == 1
    assert teams_data[0]["team_name"] == "Team Alpha"
    assert teams_data[0]["role_in_team"] == "leader"
    assert teams_data[0]["submission"]["repository_name"] == "alpha-reasoning"


@pytest.mark.asyncio
async def test_05_invalid_credentials_rejected(client: AsyncClient, seeded_personas):
    """5. Invalid credentials are rejected with 401."""
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "test_admin@scorva.io", "password": "IncorrectPassword123!"},
    )
    assert res.status_code == 401
    assert res.json()["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_06_suspended_or_disabled_account_cannot_gain_access(client: AsyncClient, create_user_helper):
    """6. Suspended or disabled accounts cannot gain access."""
    await create_user_helper(
        email="suspended_user@scorva.io",
        password="PassWord123!",
        is_active=False,
    )
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "suspended_user@scorva.io", "password": "PassWord123!"},
    )
    assert res.status_code == 401
    assert res.json()["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_07_users_without_privileges_not_granted_privileged_access(client: AsyncClient, seeded_personas):
    """7. Users without a valid role, membership, or assignment are not granted privileged access."""
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": "test_participant@scorva.io", "password": "PartPassword123!"},
    )
    cookies = login_res.cookies

    # Try accessing Super Admin endpoint
    admin_probe = await client.get("/api/v1/admin/users", cookies=cookies)
    assert admin_probe.status_code == 403
    assert admin_probe.json()["code"] == "FORBIDDEN_NOT_ADMIN"

    # Try accessing Org A tenant profile directly
    org_probe = await client.get(f"/api/v1/organizations/{seeded_personas['org_a'].id}", cookies=cookies)
    assert org_probe.status_code == 403
    assert org_probe.json()["code"] == "TENANT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_08_multirole_user_receives_deterministic_valid_destination(client: AsyncClient, seeded_personas):
    """8. Users with multiple roles receive a deterministic, valid destination and complete destination list."""
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "test_multirole@scorva.io", "password": "MultiPassword123!"},
    )
    assert res.status_code == 200
    data = res.json()
    # Organizer role takes deterministic precedence over Judge
    assert data["default_destination"].startswith("/organizations/")
    dest_urls = [d["destination"] for d in data["user"]["routing"]["accessible_destinations"]]
    # Has both their organization AND judge portal in destinations
    assert any("/organizations/" in url for url in dest_urls)
    assert "/judge" in dest_urls


@pytest.mark.asyncio
async def test_09_judge_access_assigned_hackathon_but_denied_unassigned(client: AsyncClient, seeded_personas):
    """9. A judge can access assigned hackathon submissions but cannot access an unassigned hackathon."""
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": "test_judge@scorva.io", "password": "JudgePassword123!"},
    )
    cookies = login_res.cookies
    hack_a_id = seeded_personas["hack_a"].id
    hack_b_id = seeded_personas["hack_b"].id

    # 1. Access assigned hackathon submissions via dedicated judge API
    assigned_res = await client.get(f"/api/v1/judge/hackathons/{hack_a_id}/submissions", cookies=cookies)
    assert assigned_res.status_code == 200
    queue = assigned_res.json()
    assert len(queue) == 1
    assert queue[0]["title"] == "Autonomous AI Agent"

    # 2. Access unassigned hackathon submissions -> DENIED (403)
    unassigned_res = await client.get(f"/api/v1/judge/hackathons/{hack_b_id}/submissions", cookies=cookies)
    assert unassigned_res.status_code == 403
    assert unassigned_res.json()["code"] == "FORBIDDEN_NOT_ASSIGNED_JUDGE"


@pytest.mark.asyncio
async def test_10_tenant_user_cannot_access_super_admin_apis(client: AsyncClient, seeded_personas):
    """10. An ordinary tenant user cannot access Super Admin APIs."""
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": "test_organizer@scorva.io", "password": "OrgPassword123!"},
    )
    cookies = login_res.cookies

    res = await client.get("/api/v1/admin/hackathons", cookies=cookies)
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN_NOT_ADMIN"


@pytest.mark.asyncio
async def test_11_cross_tenant_api_access_remains_denied(client: AsyncClient, seeded_personas):
    """11. Cross-tenant API access remains denied."""
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": "test_other_organizer@scorva.io", "password": "OtherOrgPassword123!"},
    )
    cookies = login_res.cookies
    org_a_id = seeded_personas["org_a"].id

    # Organizer from Org B tries to access Org A profile
    res = await client.get(f"/api/v1/organizations/{org_a_id}", cookies=cookies)
    assert res.status_code == 403
    assert res.json()["code"] == "TENANT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_12_untrusted_redirect_parameters_sanitized(client: AsyncClient, seeded_personas):
    """12. Untrusted redirect parameters cannot redirect users to arbitrary external URLs or unauthorized routes."""
    # Attempt 1: External URL open redirect attack
    res_ext = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "test_participant@scorva.io",
            "password": "PartPassword123!",
            "redirect_url": "https://attacker.com/steal-token",
        },
    )
    assert res_ext.status_code == 200
    # Sanitized to authorized default destination
    assert res_ext.json()["default_destination"] == "/participant"

    # Attempt 2: Protocol relative open redirect
    res_proto = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "test_participant@scorva.io",
            "password": "PartPassword123!",
            "redirect_url": "//attacker.com/phishing",
        },
    )
    assert res_proto.status_code == 200
    assert res_proto.json()["default_destination"] == "/participant"

    # Attempt 3: Participant attempting to redirect into /admin
    res_priv = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "test_participant@scorva.io",
            "password": "PartPassword123!",
            "redirect_url": "/admin/security",
        },
    )
    assert res_priv.status_code == 200
    # Participant has no access to /admin, sanitized to /participant
    assert res_priv.json()["default_destination"] == "/participant"

    # Attempt 4: Admin authorized redirect to /admin/security
    res_admin = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "test_admin@scorva.io",
            "password": "AdminPassword123!",
            "redirect_url": "/admin/security",
        },
    )
    assert res_admin.status_code == 200
    # Admin is authorized for /admin/security, redirect honored
    assert res_admin.json()["default_destination"] == "/admin/security"

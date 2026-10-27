from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from apps.api.modules.audit.models import AuditEvent
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
from apps.api.tests.test_hackathons import ORIGIN_HEADER, hackathon_test_setup


@pytest.fixture
async def setup_published_hackathon(db_session, hackathon_test_setup):
    """Provisions a published hackathon for Org A."""
    fixture = hackathon_test_setup
    org_a = fixture["org_a"]
    alice = fixture["alice"]

    now = datetime.now(timezone.utc)
    hackathon = Hackathon(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title=f"AI Innovation Cup {fixture['suffix']}",
        slug=f"ai-cup-{fixture['suffix']}",
        description="University Hackathon for AI agents",
        status=HackathonStatus.PUBLISHED,
        start_date=now - timedelta(hours=2),
        submission_deadline=now + timedelta(days=2),
        end_date=now + timedelta(days=3),
        created_by_user_id=alice.id,
        settings={"max_team_size": 4},
    )
    db_session.add(hackathon)
    await db_session.commit()
    await db_session.refresh(hackathon)

    return {
        **fixture,
        "hackathon": hackathon,
    }


# =====================================================================
# Test Suite 1: Overview & Metrics
# =====================================================================

@pytest.mark.asyncio
async def test_m6_1_hackathon_overview_metrics(client: AsyncClient, setup_published_hackathon):
    env = setup_published_hackathon
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    headers = {
        "Authorization": f"Bearer {env['alice_token']}",
        **ORIGIN_HEADER,
    }

    # Initial overview: 0 teams, 0 submissions, 0 judges
    resp = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/overview",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_teams"] == 0
    assert data["total_submissions"] == 0
    assert data["total_judges"] == 0
    assert data["total_evaluations"] == 0
    assert data["status"] == "published"


@pytest.mark.asyncio
async def test_m6_1_hackathon_overview_cross_tenant_denied(client: AsyncClient, setup_published_hackathon):
    env = setup_published_hackathon
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    frank_headers = {
        "Authorization": f"Bearer {env['frank_token']}",  # Org B Owner
        **ORIGIN_HEADER,
    }

    resp = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/overview",
        headers=frank_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "TENANT_ACCESS_DENIED"


# =====================================================================
# Test Suite 2: Team Creation, Joining & Roster
# =====================================================================

@pytest.mark.asyncio
async def test_m6_1_team_registration_and_join_flow(client: AsyncClient, db_session, setup_published_hackathon):
    env = setup_published_hackathon
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id

    charlie_headers = {
        "Authorization": f"Bearer {env['charlie_token']}",
        **ORIGIN_HEADER,
    }
    dave_headers = {
        "Authorization": f"Bearer {env['dave_token']}",
        **ORIGIN_HEADER,
    }

    # 1. Charlie creates Team Neural
    resp_create = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/teams",
        headers=charlie_headers,
        json={"name": "Team Neural"},
    )
    assert resp_create.status_code == 201, resp_create.text
    team_data = resp_create.json()
    team_id = team_data["id"]
    join_code = team_data["join_code"]
    assert team_data["name"] == "Team Neural"
    assert len(join_code) == 12
    assert len(team_data["members"]) == 1
    assert team_data["members"][0]["role_in_team"] == "leader"

    # 2. Charlie attempts to create a second team in same hackathon -> 409
    resp_second = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/teams",
        headers=charlie_headers,
        json={"name": "Team Rogue"},
    )
    assert resp_second.status_code == 409
    assert resp_second.json()["code"] == "ALREADY_IN_HACKATHON_TEAM"

    # 3. Dave joins Team Neural using join_code
    resp_join = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/teams/join",
        headers=dave_headers,
        json={"join_code": join_code},
    )
    assert resp_join.status_code == 200, resp_join.text
    joined_data = resp_join.json()
    assert len(joined_data["members"]) == 2
    roles = {m["user_email"]: m["role_in_team"] for m in joined_data["members"]}
    assert roles[env["charlie"].email] == "leader"
    assert roles[env["dave"].email] == "member"

    # 4. Dave attempts to join again -> 409 ALREADY_IN_TEAM
    resp_rejoin = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/teams/join",
        headers=dave_headers,
        json={"join_code": join_code},
    )
    assert resp_rejoin.status_code == 409
    assert resp_rejoin.json()["code"] == "ALREADY_IN_TEAM"

    # 5. Invalid join code -> 404
    resp_invalid = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/teams/join",
        headers=dave_headers,
        json={"join_code": "INVALID12345"},
    )
    assert resp_invalid.status_code == 404
    assert resp_invalid.json()["code"] == "TEAM_NOT_FOUND"

    # 6. List teams shows member count 2
    resp_list = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/teams",
        headers=charlie_headers,
    )
    assert resp_list.status_code == 200
    teams_list = resp_list.json()
    assert len(teams_list) == 1
    assert teams_list[0]["member_count"] == 2

    # 7. Team detail endpoint
    resp_detail = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/teams/{team_id}",
        headers=charlie_headers,
    )
    assert resp_detail.status_code == 200
    assert len(resp_detail.json()["members"]) == 2


# =====================================================================
# Test Suite 3: Submission Workflow
# =====================================================================

@pytest.mark.asyncio
async def test_m6_1_submission_registration_and_detail(client: AsyncClient, setup_published_hackathon):
    env = setup_published_hackathon
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id

    charlie_headers = {
        "Authorization": f"Bearer {env['charlie_token']}",
        **ORIGIN_HEADER,
    }

    # 1. Register team
    resp_team = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/teams",
        headers=charlie_headers,
        json={"name": "Autonomous Agent Team"},
    )
    assert resp_team.status_code == 201
    team_id = resp_team.json()["id"]

    # 2. Charlie submits repository
    repo_url = f"https://github.com/scorva-hackathon/agent-project-{env['suffix']}"
    resp_sub = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions",
        headers=charlie_headers,
        json={
            "team_id": team_id,
            "repository_url": repo_url,
            "target_branch": "main",
            "title": "Autonomous Coding Agent",
            "description": "An autonomous coding evaluation agent built with LLMs",
        },
    )
    assert resp_sub.status_code == 201, resp_sub.text
    sub_data = resp_sub.json()
    sub_id = sub_data["id"]
    assert sub_data["status"] == "pending"
    assert sub_data["title"] == "Autonomous Coding Agent"
    assert sub_data["repository_url"] == repo_url

    # 3. Duplicate submission by same team -> 409
    resp_sub_dup = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions",
        headers=charlie_headers,
        json={
            "team_id": team_id,
            "repository_url": "https://github.com/scorva-hackathon/another-repo",
            "target_branch": "main",
            "title": "Second Submission Attempt",
        },
    )
    assert resp_sub_dup.status_code == 409
    assert resp_sub_dup.json()["code"] == "TEAM_ALREADY_SUBMITTED"

    # 4. List submissions
    resp_list = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions",
        headers=charlie_headers,
    )
    assert resp_list.status_code == 200
    subs = resp_list.json()
    assert len(subs) == 1
    assert subs[0]["id"] == sub_id

    # 5. Get submission detail
    resp_detail = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub_id}",
        headers=charlie_headers,
    )
    assert resp_detail.status_code == 200
    assert resp_detail.json()["id"] == sub_id
    assert resp_detail.json()["team_name"] == "Autonomous Agent Team"

    # 6. Verify Hackathon Overview updated counters
    alice_headers = {
        "Authorization": f"Bearer {env['alice_token']}",
        **ORIGIN_HEADER,
    }
    resp_overview = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/overview",
        headers=alice_headers,
    )
    assert resp_overview.status_code == 200
    ov_data = resp_overview.json()
    assert ov_data["total_teams"] == 1
    assert ov_data["total_submissions"] == 1


# =====================================================================
# Test Suite 4: Judge Assignment & Removal
# =====================================================================

@pytest.mark.asyncio
async def test_m6_1_judge_assignment_lifecycle(client: AsyncClient, setup_published_hackathon):
    env = setup_published_hackathon
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    alice_headers = {
        "Authorization": f"Bearer {env['alice_token']}",
        **ORIGIN_HEADER,
    }

    # 1. Assign Dave as a judge using email
    resp_assign = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/judges",
        headers=alice_headers,
        json={"email": env["dave"].email},
    )
    assert resp_assign.status_code == 201, resp_assign.text
    judge_data = resp_assign.json()
    assert judge_data["user_email"] == env["dave"].email
    assert judge_data["user_id"] == str(env["dave"].id)

    # 2. Duplicate assignment -> 409
    resp_dup = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/judges",
        headers=alice_headers,
        json={"email": env["dave"].email},
    )
    assert resp_dup.status_code == 409
    assert resp_dup.json()["code"] == "JUDGE_ALREADY_ASSIGNED"

    # 3. Assign non-existent user -> 404
    resp_none = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/judges",
        headers=alice_headers,
        json={"email": "nonexistent_judge_999@unknown.org"},
    )
    assert resp_none.status_code == 404
    assert resp_none.json()["code"] == "USER_NOT_FOUND"

    # 4. List judges
    resp_list = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/judges",
        headers=alice_headers,
    )
    assert resp_list.status_code == 200
    judges = resp_list.json()
    assert len(judges) == 1
    assert judges[0]["user_email"] == env["dave"].email

    # 5. Remove judge -> 204
    resp_remove = await client.delete(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/judges/{env['dave'].id}",
        headers=alice_headers,
    )
    assert resp_remove.status_code == 204

    # 6. List judges is now empty
    resp_list_after = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/judges",
        headers=alice_headers,
    )
    assert resp_list_after.status_code == 200
    assert len(resp_list_after.json()) == 0


# =====================================================================
# Test Suite 5: Rubric Creation, Criteria & Publishing
# =====================================================================

@pytest.mark.asyncio
async def test_m6_1_rubric_workflow_and_freezing(client: AsyncClient, setup_published_hackathon):
    env = setup_published_hackathon
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    alice_headers = {
        "Authorization": f"Bearer {env['alice_token']}",
        **ORIGIN_HEADER,
    }

    # 1. No rubric initially -> 404
    resp_none = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/rubric",
        headers=alice_headers,
    )
    assert resp_none.status_code == 404
    assert resp_none.json()["code"] == "RUBRIC_NOT_FOUND"

    # 2. Create rubric container
    resp_create = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/rubrics",
        headers=alice_headers,
        json={
            "name": "Standard AI Rubric",
            "description": "Evaluates code quality, correctness, and innovation.",
            "scoring_mode": "offset_normalized",
        },
    )
    assert resp_create.status_code == 201, resp_create.text
    rubric_data = resp_create.json()
    rubric_id = rubric_data["id"]
    assert rubric_data["name"] == "Standard AI Rubric"
    assert rubric_data["active_version"]["status"] == "draft"

    # 3. Add Criterion 1 (weight 0.60)
    resp_c1 = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/rubrics/{rubric_id}/criteria",
        headers=alice_headers,
        json={
            "title": "Technical Execution",
            "description": "Code architecture, test coverage, and documentation.",
            "weight": "0.6000",
            "min_score": "0.00",
            "max_score": "10.00",
            "evidence_requirements": "Requires README and test suites",
            "order_index": 1,
        },
    )
    assert resp_c1.status_code == 201, resp_c1.text
    assert len(resp_c1.json()["active_version"]["criteria"]) == 1

    # 4. Add Criterion 2 (weight 0.40)
    resp_c2 = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/rubrics/{rubric_id}/criteria",
        headers=alice_headers,
        json={
            "title": "Innovation & Impact",
            "description": "Creativity and practical applicability of the project.",
            "weight": "0.4000",
            "min_score": "0.00",
            "max_score": "10.00",
            "evidence_requirements": "Demonstration of novel agentic workflow",
            "order_index": 2,
        },
    )
    assert resp_c2.status_code == 201, resp_c2.text
    assert len(resp_c2.json()["active_version"]["criteria"]) == 2

    # 5. Publish rubric
    resp_pub = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/rubrics/{rubric_id}/publish",
        headers=alice_headers,
    )
    assert resp_pub.status_code == 200, resp_pub.text
    published_rubric = resp_pub.json()
    assert published_rubric["active_version"]["status"] == "published"
    assert published_rubric["active_version"]["published_at"] is not None

    # 6. Attempting to add criteria after publication is blocked -> 400
    resp_c3 = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/rubrics/{rubric_id}/criteria",
        headers=alice_headers,
        json={
            "title": "Late Criterion",
            "description": "Should be rejected because version is published.",
            "weight": "0.1000",
            "min_score": "0.00",
            "max_score": "10.00",
            "evidence_requirements": "None",
            "order_index": 3,
        },
    )
    assert resp_c3.status_code == 400
    assert resp_c3.json()["code"] == "NO_DRAFT_RUBRIC_VERSION"

    # 7. GET /rubric returns the published rubric and criteria
    resp_get = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/rubric",
        headers=alice_headers,
    )
    assert resp_get.status_code == 200
    assert resp_get.json()["active_version"]["status"] == "published"
    assert len(resp_get.json()["active_version"]["criteria"]) == 2


# =====================================================================
# Test Suite 6: Cross-Tenant Isolation & Audit Trail
# =====================================================================

@pytest.mark.asyncio
async def test_m6_1_cross_tenant_isolation_and_audit(client: AsyncClient, db_session, setup_published_hackathon):
    env = setup_published_hackathon
    org_a_id = env["org_a"].id
    hackathon_id = env["hackathon"].id

    frank_headers = {
        "Authorization": f"Bearer {env['frank_token']}",  # Org B
        **ORIGIN_HEADER,
    }

    # Frank cannot read teams of Org A
    resp_teams = await client.get(
        f"/api/v1/organizations/{org_a_id}/hackathons/{hackathon_id}/teams",
        headers=frank_headers,
    )
    assert resp_teams.status_code == 403

    # Frank cannot create a team in Org A
    resp_create = await client.post(
        f"/api/v1/organizations/{org_a_id}/hackathons/{hackathon_id}/teams",
        headers=frank_headers,
        json={"name": "Attacker Team"},
    )
    assert resp_create.status_code == 403

    # Frank cannot read submissions of Org A
    resp_subs = await client.get(
        f"/api/v1/organizations/{org_a_id}/hackathons/{hackathon_id}/submissions",
        headers=frank_headers,
    )
    assert resp_subs.status_code == 403

    # Alice creates a valid team in Org A to generate an audit event
    alice_headers = {
        "Authorization": f"Bearer {env['alice_token']}",
        **ORIGIN_HEADER,
    }
    resp_create_valid = await client.post(
        f"/api/v1/organizations/{org_a_id}/hackathons/{hackathon_id}/teams",
        headers=alice_headers,
        json={"name": "Audit Verified Team"},
    )
    assert resp_create_valid.status_code == 201

    # Verify AuditEvents exist in database for Org A
    stmt_audits = select(AuditEvent).where(AuditEvent.organization_id == org_a_id)
    audits = (await db_session.execute(stmt_audits)).scalars().all()
    assert len(audits) > 0
    actions = [a.action for a in audits]
    assert "team_created" in actions

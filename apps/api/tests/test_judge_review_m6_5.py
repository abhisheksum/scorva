from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from apps.api.modules.audit.models import AuditEvent
from apps.api.modules.evaluations.models import (
    EvaluationCriterionScore,
    EvaluationJob,
    EvaluationResult,
    HackathonJudge,
    JudgeCriterionScore,
    JudgeReview,
    Rubric,
    RubricCriterion,
    RubricVersion,
    Submission,
    SubmissionSnapshot,
    Team,
)
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.modules.organizations.models import OrganizationMembership, OrgRole
from apps.api.tests.test_hackathons import ORIGIN_HEADER, hackathon_test_setup


@pytest.fixture
async def setup_judge_review_env(db_session, hackathon_test_setup):
    """
    Provisions a comprehensive test fixture for Milestone 6.5:
    - Organization A (Alice: owner)
    - Organization B (Frank: owner)
    - Dave: assigned Judge 1 in Org A
    - Charlie: assigned Judge 2 in Org A
    - Bob: participant / non-judge in Org A
    - Published Hackathon with 2 published rubric criteria
    - 2 Submissions in Hackathon (Submission 1 with AI result, Submission 2 without AI result)
    """
    env = hackathon_test_setup
    org_a = env["org_a"]
    org_b = env["org_b"]
    alice = env["alice"]
    bob = env["bob"]
    charlie = env["charlie"]
    dave = env["dave"]
    frank = env["frank"]
    suffix = env["suffix"]

    now = datetime.now(timezone.utc)

    # 1. Published Hackathon
    hackathon = Hackathon(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title=f"Review Hackathon {suffix}",
        slug=f"rev-hack-{suffix}",
        description="Scorva Judge Review Testing Hackathon",
        status=HackathonStatus.PUBLISHED,
        start_date=now - timedelta(hours=2),
        submission_deadline=now + timedelta(days=2),
        end_date=now + timedelta(days=3),
        created_by_user_id=alice.id,
    )
    db_session.add(hackathon)
    await db_session.flush()

    # 2. Published Rubric with 2 criteria
    rubric = Rubric(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        hackathon_id=hackathon.id,
        name=f"Official Judge Rubric {suffix}",
        scoring_mode="offset_normalized",
    )
    db_session.add(rubric)
    await db_session.flush()

    rubric_version = RubricVersion(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        rubric_id=rubric.id,
        version_number=1,
        status="draft",
    )
    db_session.add(rubric_version)
    await db_session.flush()

    crit1 = RubricCriterion(
        id=uuid.uuid4(),
        rubric_version_id=rubric_version.id,
        title="Technical Complexity",
        description="Architecture, test suites, and clean implementation",
        weight=Decimal("0.4000"),
        min_score=Decimal("0.00"),
        max_score=Decimal("10.00"),
        evidence_requirements="Code quality",
        order_index=1,
    )
    crit2 = RubricCriterion(
        id=uuid.uuid4(),
        rubric_version_id=rubric_version.id,
        title="Innovation & Usability",
        description="Novel approach and intuitive interface",
        weight=Decimal("0.6000"),
        min_score=Decimal("0.00"),
        max_score=Decimal("10.00"),
        evidence_requirements="Novel UX",
        order_index=2,
    )
    db_session.add(crit1)
    db_session.add(crit2)
    await db_session.flush()

    rubric_version.status = "published"
    rubric_version.published_at = now
    await db_session.flush()

    # 3. Team & Submissions
    team = Team(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        hackathon_id=hackathon.id,
        name=f"Team Zenith {suffix}",
        join_code=f"TZ{uuid.uuid4().hex[:10].upper()}",
        created_by_user_id=alice.id,
    )
    db_session.add(team)
    await db_session.flush()

    sub1 = Submission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        hackathon_id=hackathon.id,
        team_id=team.id,
        team_name=team.name,
        repository_url="https://github.com/scorva-org/zenith-ai",
        target_branch="main",
        title="Zenith Autonomous Agent",
        description="First submission for judge evaluation",
        status="pending",
        repository_owner="scorva-org",
        repository_name="zenith-ai",
        default_branch="main",
        verified_commit_sha="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
        connection_status="verified",
        verified_at=now,
    )
    sub2 = Submission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        hackathon_id=hackathon.id,
        team_id=team.id,
        team_name=team.name,
        repository_url="https://github.com/scorva-org/zenith-docs",
        target_branch="main",
        title="Zenith Documentation Platform",
        description="Second submission without AI evaluation",
        status="pending",
        repository_owner="scorva-org",
        repository_name="zenith-docs",
        default_branch="main",
        verified_commit_sha="b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1",
        connection_status="verified",
        verified_at=now,
    )
    db_session.add(sub1)
    db_session.add(sub2)
    await db_session.flush()

    # 4. Snapshot & AI Result for Submission 1
    snap1 = SubmissionSnapshot(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        submission_id=sub1.id,
        commit_sha=sub1.verified_commit_sha,
        file_count=10,
        total_bytes=500000,
        configuration_snapshot={"model": "mock-claude"},
        metadata_={"verified": True},
        captured_at=now,
    )
    db_session.add(snap1)
    await db_session.flush()

    ai_job = EvaluationJob(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        hackathon_id=hackathon.id,
        submission_id=sub1.id,
        snapshot_id=snap1.id,
        rubric_version_id=rubric_version.id,
        status="completed",
        attempts_count=1,
        max_attempts=3,
        created_at=now - timedelta(minutes=10),
        started_at=now - timedelta(minutes=9),
        completed_at=now - timedelta(minutes=8),
    )
    db_session.add(ai_job)
    await db_session.flush()

    ai_result = EvaluationResult(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        hackathon_id=hackathon.id,
        submission_id=sub1.id,
        rubric_version_id=rubric_version.id,
        job_id=ai_job.id,
        snapshot_id=snap1.id,
        attempt_number=1,
        model_provider="anthropic",
        model_name="claude-3-5-sonnet",
        prompt_version="v2.1",
        raw_score=Decimal("9.50"),
        normalized_score=Decimal("95.00"),
        summary_assessment="High-quality submission with strong architecture and security isolation.",
        has_insufficient_evidence=False,
    )
    db_session.add(ai_result)
    await db_session.flush()

    cs1 = EvaluationCriterionScore(
        id=uuid.uuid4(),
        evaluation_result_id=ai_result.id,
        criterion_id=crit1.id,
        awarded_score=Decimal("9.50"),
        normalized_criterion_score=Decimal("0.9500"),
        confidence_score=Decimal("1.00"),
        rationale="Strong modular architecture.",
        evidence_status="verified",
    )
    cs2 = EvaluationCriterionScore(
        id=uuid.uuid4(),
        evaluation_result_id=ai_result.id,
        criterion_id=crit2.id,
        awarded_score=Decimal("9.50"),
        normalized_criterion_score=Decimal("0.9500"),
        confidence_score=Decimal("1.00"),
        rationale="Intuitive usability and strong security.",
        evidence_status="verified",
    )
    db_session.add(cs1)
    db_session.add(cs2)
    await db_session.flush()

    ai_job.current_result_id = ai_result.id
    await db_session.flush()

    # 5. Assign Dave and Charlie as HackathonJudges
    judge_dave = HackathonJudge(
        id=uuid.uuid4(),
        hackathon_id=hackathon.id,
        user_id=dave.id,
        assigned_by_user_id=alice.id,
    )
    judge_charlie = HackathonJudge(
        id=uuid.uuid4(),
        hackathon_id=hackathon.id,
        user_id=charlie.id,
        assigned_by_user_id=alice.id,
    )
    db_session.add(judge_dave)
    db_session.add(judge_charlie)
    await db_session.commit()

    return {
        **env,
        "hackathon": hackathon,
        "rubric": rubric,
        "rubric_version": rubric_version,
        "crit1": crit1,
        "crit2": crit2,
        "team": team,
        "sub1": sub1,
        "sub2": sub2,
        "ai_result": ai_result,
        "judge_dave": judge_dave,
        "judge_charlie": judge_charlie,
    }


# =====================================================================
# Test 1 & 2: Access & Assignment Authorization
# =====================================================================

@pytest.mark.asyncio
async def test_assigned_judge_can_access_and_unassigned_denied(client: AsyncClient, setup_judge_review_env):
    """
    Test 1 & 2:
    - Assigned judge (Dave) can access submission review form.
    - Unassigned user (Bob) is strictly denied access (403).
    """
    env = setup_judge_review_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    sub1_id = env["sub1"].id

    dave_headers = {"Authorization": f"Bearer {env['dave_token']}", **ORIGIN_HEADER}
    bob_headers = {"Authorization": f"Bearer {env['bob_token']}", **ORIGIN_HEADER}

    # 1. Dave (assigned judge) accesses submission review form -> 200 OK
    resp_dave = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review",
        headers=dave_headers,
    )
    assert resp_dave.status_code == 200, resp_dave.text
    data = resp_dave.json()
    assert data["submission_id"] == str(sub1_id)
    assert data["can_edit"] is True
    assert len(data["rubric_criteria"]) == 2
    assert data["ai_evaluation"] is not None
    assert data["ai_evaluation"]["normalized_score"] == "95.00"
    assert data["review"] is None  # not started yet

    # 2. Bob (not assigned as judge and role is participant) -> 403 Forbidden
    resp_bob = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review",
        headers=bob_headers,
    )
    assert resp_bob.status_code == 403
    assert resp_bob.json()["code"] == "FORBIDDEN_NOT_ASSIGNED_JUDGE"


# =====================================================================
# Test 3: Multi-Tenant Isolation
# =====================================================================

@pytest.mark.asyncio
async def test_cross_tenant_access_denied(client: AsyncClient, setup_judge_review_env):
    """
    Test 3: Cross-tenant access is strictly denied.
    Frank from Org B cannot access Org A hackathon review or queue endpoints.
    """
    env = setup_judge_review_env
    org_a_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    sub1_id = env["sub1"].id

    frank_headers = {"Authorization": f"Bearer {env['frank_token']}", **ORIGIN_HEADER}

    # Accessing Org A queue from Frank -> 403
    resp_queue = await client.get(
        f"/api/v1/organizations/{org_a_id}/hackathons/{hackathon_id}/judge/queue",
        headers=frank_headers,
    )
    assert resp_queue.status_code == 403

    # Accessing Org A review from Frank -> 403
    resp_review = await client.get(
        f"/api/v1/organizations/{org_a_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review",
        headers=frank_headers,
    )
    assert resp_review.status_code == 403


# =====================================================================
# Test 4: Save & Retrieve Draft Review
# =====================================================================

@pytest.mark.asyncio
async def test_judge_can_save_and_retrieve_draft(client: AsyncClient, setup_judge_review_env):
    """
    Test 4:
    Judge can save a draft with partial criteria scores and return later to retrieve it.
    """
    env = setup_judge_review_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    sub1_id = env["sub1"].id
    crit1_id = env["crit1"].id

    dave_headers = {"Authorization": f"Bearer {env['dave_token']}", **ORIGIN_HEADER}

    # 1. Save partial draft (scoring only criterion 1)
    draft_payload = {
        "overall_feedback": "Initial impressions look solid. Need to test security bounds.",
        "decision": "accepted",
        "criterion_scores": [
            {
                "criterion_id": str(crit1_id),
                "score": "8.50",
                "judge_notes": "Well structured modular design.",
            }
        ],
    }
    resp_save = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review",
        headers=dave_headers,
        json=draft_payload,
    )
    assert resp_save.status_code == 200, resp_save.text
    saved = resp_save.json()
    assert saved["status"] == "draft"
    assert saved["version"] == 1
    assert saved["score"] == "8.50"
    assert saved["overall_feedback"] == draft_payload["overall_feedback"]

    # 2. Retrieve review form -> reflects the draft
    resp_get = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review",
        headers=dave_headers,
    )
    assert resp_get.status_code == 200
    form_data = resp_get.json()
    assert form_data["can_edit"] is True
    assert form_data["review"] is not None
    assert form_data["review"]["status"] == "draft"
    assert form_data["review"]["version"] == 1
    # Check that criterion 1 has the saved score and criterion 2 is not yet scored
    cs1 = next(c for c in form_data["review"]["criterion_scores"] if c["criterion_id"] == str(crit1_id))
    assert cs1["score"] == "8.50"
    assert cs1["judge_notes"] == "Well structured modular design."


# =====================================================================
# Test 5: Concurrency Protection on Draft Update
# =====================================================================

@pytest.mark.asyncio
async def test_judge_concurrency_protection_on_draft_update(client: AsyncClient, setup_judge_review_env):
    """
    Test 5:
    Updating a draft checks version. If a stale version is supplied, 409 Conflict is raised.
    """
    env = setup_judge_review_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    sub1_id = env["sub1"].id
    crit1_id = env["crit1"].id

    dave_headers = {"Authorization": f"Bearer {env['dave_token']}", **ORIGIN_HEADER}

    # 1. Save initial draft -> version 1
    resp1 = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review",
        headers=dave_headers,
        json={
            "overall_feedback": "Draft version 1",
            "criterion_scores": [{"criterion_id": str(crit1_id), "score": "7.00"}],
        },
    )
    assert resp1.status_code == 200
    assert resp1.json()["version"] == 1

    # 2. Second update with version 1 -> success, version becomes 2
    resp2 = await client.put(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review",
        headers=dave_headers,
        json={
            "overall_feedback": "Draft version 2 updated",
            "criterion_scores": [{"criterion_id": str(crit1_id), "score": "8.00"}],
            "version": 1,
        },
    )
    assert resp2.status_code == 200
    assert resp2.json()["version"] == 2

    # 3. Concurrent request with stale version 1 -> 409 CONCURRENT_MODIFICATION_DETECTED
    resp_stale = await client.put(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review",
        headers=dave_headers,
        json={
            "overall_feedback": "Draft version stale update attempt",
            "criterion_scores": [{"criterion_id": str(crit1_id), "score": "9.00"}],
            "version": 1,
        },
    )
    assert resp_stale.status_code == 409
    assert resp_stale.json()["code"] == "CONCURRENT_MODIFICATION_DETECTED"


# =====================================================================
# Test 6 & 7 & 8: Scoring Validation Bounds & Rubric Integrity
# =====================================================================

@pytest.mark.asyncio
async def test_criterion_score_bounds_and_unknown_ids_rejected(client: AsyncClient, setup_judge_review_env):
    """
    Test 6, 7 & 8:
    - Score > max_score (e.g. 12.00 > 10.00) rejected with 400 SCORE_OUT_OF_BOUNDS.
    - Score < min_score rejected with 400 SCORE_OUT_OF_BOUNDS or 422.
    - Unknown criterion ID rejected with 400 UNKNOWN_CRITERION_ID.
    """
    env = setup_judge_review_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    sub1_id = env["sub1"].id
    crit1_id = env["crit1"].id

    dave_headers = {"Authorization": f"Bearer {env['dave_token']}", **ORIGIN_HEADER}

    # 1. Out of range score (15.00 > 10.00) -> 400
    resp_high = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review",
        headers=dave_headers,
        json={
            "criterion_scores": [{"criterion_id": str(crit1_id), "score": "15.00"}],
        },
    )
    assert resp_high.status_code == 400
    assert resp_high.json()["code"] == "SCORE_OUT_OF_BOUNDS"

    # 2. Unknown criterion ID -> 400
    unknown_id = str(uuid.uuid4())
    resp_unknown = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review",
        headers=dave_headers,
        json={
            "criterion_scores": [{"criterion_id": unknown_id, "score": "8.00"}],
        },
    )
    assert resp_unknown.status_code == 400
    assert resp_unknown.json()["code"] == "UNKNOWN_CRITERION_ID"


# =====================================================================
# Test 9 & 10: Atomic Final Review Submission & Weighted Scoring
# =====================================================================

@pytest.mark.asyncio
async def test_final_review_submission_enforces_criteria_and_computes_score(
    client: AsyncClient, setup_judge_review_env
):
    """
    Test 9 & 10:
    - Missing criteria at submission is rejected (400 MISSING_REQUIRED_CRITERIA).
    - Complete submission atomically calculates weighted aggregate score:
      Crit 1: weight 0.40, score 8.00 -> 3.20
      Crit 2: weight 0.60, score 6.00 -> 3.60
      Weighted sum = 6.80, total weight = 1.00 -> 6.80.
    """
    env = setup_judge_review_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    sub1_id = env["sub1"].id
    crit1_id = env["crit1"].id
    crit2_id = env["crit2"].id

    dave_headers = {"Authorization": f"Bearer {env['dave_token']}", **ORIGIN_HEADER}

    # 1. Attempt submit with missing criterion 2 -> 400
    resp_incomplete = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review/submit",
        headers=dave_headers,
        json={
            "overall_feedback": "Great submission overall.",
            "decision": "adjusted",
            "criterion_scores": [{"criterion_id": str(crit1_id), "score": "8.00"}],
        },
    )
    assert resp_incomplete.status_code == 400
    assert resp_incomplete.json()["code"] == "MISSING_REQUIRED_CRITERIA"

    # 2. Complete submit with both criteria
    resp_complete = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review/submit",
        headers=dave_headers,
        json={
            "overall_feedback": "Comprehensive technical architecture with exceptional unit tests.",
            "decision": "adjusted",
            "criterion_scores": [
                {"criterion_id": str(crit1_id), "score": "8.00", "judge_notes": "Clean modular design"},
                {"criterion_id": str(crit2_id), "score": "6.00", "judge_notes": "Solid security guards"},
            ],
        },
    )
    assert resp_complete.status_code == 200, resp_complete.text
    final_review = resp_complete.json()
    assert final_review["status"] == "submitted"
    assert final_review["score"] == "6.80"
    assert final_review["decision"] == "adjusted"
    assert final_review["submitted_at"] is not None
    assert len(final_review["criterion_scores"]) == 2


# =====================================================================
# Test 11 & 12: Submitted Reviews Cannot Be Silently Edited
# =====================================================================

@pytest.mark.asyncio
async def test_submitted_review_immutable_and_duplicate_submit_blocked(
    client: AsyncClient, setup_judge_review_env
):
    """
    Test 11 & 12:
    - Attempting to submit or edit an already submitted review is blocked (400 REVIEW_ALREADY_SUBMITTED).
    """
    env = setup_judge_review_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    sub1_id = env["sub1"].id
    crit1_id = env["crit1"].id
    crit2_id = env["crit2"].id

    dave_headers = {"Authorization": f"Bearer {env['dave_token']}", **ORIGIN_HEADER}

    # 1. Submit final review
    resp_sub = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review/submit",
        headers=dave_headers,
        json={
            "overall_feedback": "Final decision submitted.",
            "decision": "accepted",
            "criterion_scores": [
                {"criterion_id": str(crit1_id), "score": "9.00"},
                {"criterion_id": str(crit2_id), "score": "9.00"},
            ],
        },
    )
    assert resp_sub.status_code == 200

    # 2. Attempt second submit -> 400 REVIEW_ALREADY_SUBMITTED
    resp_dup = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review/submit",
        headers=dave_headers,
        json={
            "overall_feedback": "Attempt duplicate submit",
            "criterion_scores": [
                {"criterion_id": str(crit1_id), "score": "5.00"},
                {"criterion_id": str(crit2_id), "score": "5.00"},
            ],
        },
    )
    assert resp_dup.status_code == 400
    assert resp_dup.json()["code"] == "REVIEW_ALREADY_SUBMITTED"

    # 3. Attempt editing submitted review -> 400 REVIEW_ALREADY_SUBMITTED
    resp_edit = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review",
        headers=dave_headers,
        json={
            "overall_feedback": "Attempt editing submitted review",
            "criterion_scores": [{"criterion_id": str(crit1_id), "score": "1.00"}],
        },
    )
    assert resp_edit.status_code == 400
    assert resp_edit.json()["code"] == "REVIEW_ALREADY_SUBMITTED"


# =====================================================================
# Test 13: Multiple Independent Judges Per Submission
# =====================================================================

@pytest.mark.asyncio
async def test_multiple_independent_judges_per_submission(
    client: AsyncClient, setup_judge_review_env, db_session
):
    """
    Test 13:
    Judge 1 (Dave) and Judge 2 (Charlie) can independently score the same submission.
    Neither judge's scores or feedback overwrite the other.
    """
    env = setup_judge_review_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    sub1_id = env["sub1"].id
    crit1_id = env["crit1"].id
    crit2_id = env["crit2"].id

    dave_headers = {"Authorization": f"Bearer {env['dave_token']}", **ORIGIN_HEADER}
    charlie_headers = {"Authorization": f"Bearer {env['charlie_token']}", **ORIGIN_HEADER}

    # 1. Dave submits score 10.00
    await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review/submit",
        headers=dave_headers,
        json={
            "overall_feedback": "Dave evaluation: Perfect implementation.",
            "decision": "accepted",
            "criterion_scores": [
                {"criterion_id": str(crit1_id), "score": "10.00"},
                {"criterion_id": str(crit2_id), "score": "10.00"},
            ],
        },
    )

    # 2. Charlie submits score 5.00
    await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review/submit",
        headers=charlie_headers,
        json={
            "overall_feedback": "Charlie evaluation: Average work, lacks innovation.",
            "decision": "adjusted",
            "criterion_scores": [
                {"criterion_id": str(crit1_id), "score": "5.00"},
                {"criterion_id": str(crit2_id), "score": "5.00"},
            ],
        },
    )

    # 3. Verify in database that both reviews exist distinctly
    stmt = (
        select(JudgeReview)
        .where(JudgeReview.submission_id == sub1_id)
        .order_by(JudgeReview.score.desc())
    )
    reviews = (await db_session.execute(stmt)).scalars().all()
    assert len(reviews) == 2
    assert reviews[0].score == Decimal("10.00")
    assert reviews[0].judge_user_id == env["dave"].id
    assert reviews[1].score == Decimal("5.00")
    assert reviews[1].judge_user_id == env["charlie"].id


# =====================================================================
# Test 14: Removing Judge Blocks Future Operations
# =====================================================================

@pytest.mark.asyncio
async def test_removing_judge_blocks_future_review_operations(
    client: AsyncClient, setup_judge_review_env, db_session
):
    """
    Test 14:
    Removing a judge from HackathonJudges prevents future review operations,
    while preserving previously submitted reviews in the database.
    """
    env = setup_judge_review_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    sub1_id = env["sub1"].id
    sub2_id = env["sub2"].id
    crit1_id = env["crit1"].id
    crit2_id = env["crit2"].id

    alice_headers = {"Authorization": f"Bearer {env['alice_token']}", **ORIGIN_HEADER}
    dave_headers = {"Authorization": f"Bearer {env['dave_token']}", **ORIGIN_HEADER}

    # 1. Dave submits review for sub 1
    await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review/submit",
        headers=dave_headers,
        json={
            "overall_feedback": "Pre-removal review.",
            "decision": "accepted",
            "criterion_scores": [
                {"criterion_id": str(crit1_id), "score": "9.00"},
                {"criterion_id": str(crit2_id), "score": "9.00"},
            ],
        },
    )

    # 2. Alice (Organizer) removes Dave from hackathon judges
    del_resp = await client.delete(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/judges/{env['dave'].id}",
        headers=alice_headers,
    )
    assert del_resp.status_code == 204

    # 3. Dave attempts to submit review for sub 2 -> 403 FORBIDDEN_NOT_ASSIGNED_JUDGE
    resp_post = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub2_id}/review",
        headers=dave_headers,
        json={
            "overall_feedback": "Should be rejected.",
            "criterion_scores": [{"criterion_id": str(crit1_id), "score": "5.00"}],
        },
    )
    assert resp_post.status_code == 403
    assert resp_post.json()["code"] == "FORBIDDEN_NOT_ASSIGNED_JUDGE"

    # 4. Verify Dave's submitted review for sub 1 is still preserved in the database
    rev_check = (
        await db_session.execute(
            select(JudgeReview).where(
                JudgeReview.submission_id == sub1_id,
                JudgeReview.judge_user_id == env["dave"].id,
            )
        )
    ).scalar_one_or_none()
    assert rev_check is not None
    assert rev_check.status == "submitted"
    assert rev_check.score == Decimal("9.00")


# =====================================================================
# Test 15 & 16: AI & Human Decoupling Invariants
# =====================================================================

@pytest.mark.asyncio
async def test_ai_scores_and_human_scores_strictly_decoupled(
    client: AsyncClient, setup_judge_review_env, db_session
):
    """
    Test 15 & 16:
    - AI scores never overwrite human scores.
    - AI results remain 9.50 (95.00) while human judge awards 4.00.
    - Triggering re-evaluation updates AI job/results without mutating human review.
    """
    env = setup_judge_review_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    sub1_id = env["sub1"].id
    crit1_id = env["crit1"].id
    crit2_id = env["crit2"].id

    dave_headers = {"Authorization": f"Bearer {env['dave_token']}", **ORIGIN_HEADER}
    alice_headers = {"Authorization": f"Bearer {env['alice_token']}", **ORIGIN_HEADER}

    # 1. Dave submits human score 4.00 (disagreeing with AI 9.50)
    await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review/submit",
        headers=dave_headers,
        json={
            "overall_feedback": "AI was too lenient. Code is poorly tested in edge cases.",
            "decision": "adjusted",
            "criterion_scores": [
                {"criterion_id": str(crit1_id), "score": "4.00"},
                {"criterion_id": str(crit2_id), "score": "4.00"},
            ],
        },
    )

    # 2. Check that AI result and Human review are independent
    ai_res = (
        await db_session.execute(
            select(EvaluationResult).where(EvaluationResult.id == env["ai_result"].id)
        )
    ).scalar_one()
    human_rev = (
        await db_session.execute(
            select(JudgeReview).where(
                JudgeReview.submission_id == sub1_id,
                JudgeReview.judge_user_id == env["dave"].id,
            )
        )
    ).scalar_one()

    assert ai_res.raw_score == Decimal("9.50")
    assert human_rev.score == Decimal("4.00")

    # 3. Trigger new AI evaluation from dashboard
    trigger_resp = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/evaluate",
        headers=alice_headers,
    )
    assert trigger_resp.status_code == 201

    # 4. Confirm human review remains untouched
    await db_session.refresh(human_rev)
    assert human_rev.status == "submitted"
    assert human_rev.score == Decimal("4.00")
    assert human_rev.overall_feedback == "AI was too lenient. Code is poorly tested in edge cases."


# =====================================================================
# Test 17: Append-Only Audit Logging
# =====================================================================

@pytest.mark.asyncio
async def test_audit_events_recorded_for_judge_reviews(
    client: AsyncClient, setup_judge_review_env, db_session
):
    """
    Test 17:
    Saving drafts and submitting final reviews emit audit_events.
    """
    env = setup_judge_review_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    sub1_id = env["sub1"].id
    crit1_id = env["crit1"].id
    crit2_id = env["crit2"].id

    dave_headers = {"Authorization": f"Bearer {env['dave_token']}", **ORIGIN_HEADER}

    # 1. Save draft
    await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review",
        headers=dave_headers,
        json={"overall_feedback": "Draft audit check"},
    )

    # 2. Submit final review
    await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review/submit",
        headers=dave_headers,
        json={
            "overall_feedback": "Final audit check",
            "decision": "accepted",
            "criterion_scores": [
                {"criterion_id": str(crit1_id), "score": "7.00"},
                {"criterion_id": str(crit2_id), "score": "7.00"},
            ],
        },
    )

    # 3. Query audit_events
    events_stmt = (
        select(AuditEvent)
        .where(
            AuditEvent.organization_id == org_id,
            AuditEvent.resource_type == "judge_review",
        )
        .order_by(AuditEvent.timestamp.asc())
    )
    events = (await db_session.execute(events_stmt)).scalars().all()
    actions = [e.action for e in events]
    assert "judge_review_draft_saved" in actions
    assert "judge_review_submitted" in actions


# =====================================================================
# Test 18: Organizer Review Progress Dashboard
# =====================================================================

@pytest.mark.asyncio
async def test_organizer_review_progress_dashboard(
    client: AsyncClient, setup_judge_review_env
):
    """
    Test 18:
    Organizer review progress endpoint returns real, persisted counts.
    """
    env = setup_judge_review_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    sub1_id = env["sub1"].id
    crit1_id = env["crit1"].id
    crit2_id = env["crit2"].id

    alice_headers = {"Authorization": f"Bearer {env['alice_token']}", **ORIGIN_HEADER}
    dave_headers = {"Authorization": f"Bearer {env['dave_token']}", **ORIGIN_HEADER}

    # 1. Check initial progress (0 submitted, 0 drafts)
    resp_init = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/reviews/progress",
        headers=alice_headers,
    )
    assert resp_init.status_code == 200, resp_init.text
    init_data = resp_init.json()
    assert init_data["total_submissions"] == 2
    assert init_data["total_judges"] == 2
    assert init_data["submitted_reviews_count"] == 0
    assert init_data["draft_reviews_count"] == 0

    # 2. Dave submits review for sub 1
    await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review/submit",
        headers=dave_headers,
        json={
            "overall_feedback": "Review progress check",
            "decision": "accepted",
            "criterion_scores": [
                {"criterion_id": str(crit1_id), "score": "8.00"},
                {"criterion_id": str(crit2_id), "score": "8.00"},
            ],
        },
    )

    # 3. Check updated progress
    resp_updated = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/reviews/progress",
        headers=alice_headers,
    )
    assert resp_updated.status_code == 200
    up_data = resp_updated.json()
    assert up_data["submitted_reviews_count"] == 1
    assert up_data["submissions_fully_reviewed"] == 1
    assert up_data["submissions_awaiting_review"] == 1

    dave_prog = next(j for j in up_data["judge_progress"] if j["judge_user_id"] == str(env["dave"].id))
    assert dave_prog["submitted_count"] == 1
    assert dave_prog["pending_count"] == 1


# =====================================================================
# Test 19: Private Draft Visibility
# =====================================================================

@pytest.mark.asyncio
async def test_private_drafts_visible_only_to_authorized_users(
    client: AsyncClient, setup_judge_review_env
):
    """
    Test 19:
    Judge 2 (Charlie) cannot see Judge 1's (Dave) private draft.
    """
    env = setup_judge_review_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    sub1_id = env["sub1"].id
    crit1_id = env["crit1"].id

    dave_headers = {"Authorization": f"Bearer {env['dave_token']}", **ORIGIN_HEADER}
    charlie_headers = {"Authorization": f"Bearer {env['charlie_token']}", **ORIGIN_HEADER}

    # 1. Dave creates private draft
    await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review",
        headers=dave_headers,
        json={
            "overall_feedback": "Secret draft notes by Dave",
            "criterion_scores": [{"criterion_id": str(crit1_id), "score": "7.50"}],
        },
    )

    # 2. Charlie accesses review form -> receives empty review for himself, not Dave's draft
    resp_charlie = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review",
        headers=charlie_headers,
    )
    assert resp_charlie.status_code == 200
    assert resp_charlie.json()["review"] is None

    # 3. Charlie attempts to explicitly view Dave's review by passing judge_id -> 403 FORBIDDEN_PRIVATE_REVIEW
    resp_charlie_spy = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub1_id}/review?judge_id={env['dave'].id}",
        headers=charlie_headers,
    )
    assert resp_charlie_spy.status_code == 403
    assert resp_charlie_spy.json()["code"] == "FORBIDDEN_PRIVATE_REVIEW"


# =====================================================================
# Test 20: Judge Workspace Assignments Listing
# =====================================================================

@pytest.mark.asyncio
async def test_judge_workspace_assignments_listing(
    client: AsyncClient, setup_judge_review_env
):
    """
    Test 20:
    GET /api/v1/judge/assignments returns the list of assigned hackathons for the judge
    with accurate submission counts and review progress.
    """
    env = setup_judge_review_env
    hackathon_id = env["hackathon"].id
    dave_headers = {"Authorization": f"Bearer {env['dave_token']}", **ORIGIN_HEADER}

    resp = await client.get("/api/v1/judge/assignments", headers=dave_headers)
    assert resp.status_code == 200, resp.text
    assignments = resp.json()
    assert len(assignments) >= 1
    my_assignment = next(a for a in assignments if a["hackathon_id"] == str(hackathon_id))
    assert my_assignment["hackathon_title"] == env["hackathon"].title
    assert my_assignment["total_submissions"] == 2
    assert my_assignment["my_submitted_count"] == 0
    assert my_assignment["my_pending_count"] == 2

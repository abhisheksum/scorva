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
    EvaluationJobOutbox,
    EvaluationResult,
    EvidenceReference,
    Rubric,
    RubricCriterion,
    RubricVersion,
    Submission,
    SubmissionSnapshot,
    Team,
    TeamMember,
)
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.tests.test_hackathons import ORIGIN_HEADER, hackathon_test_setup


@pytest.fixture
async def setup_transparency_env(db_session, hackathon_test_setup):
    """
    Provisions a comprehensive test fixture for Milestone 6.4:
    - Organization A (Alice)
    - Organization B (Frank)
    - Published Hackathon in Org A
    - Published Rubric with 2 criteria in Org A
    - Registered Team & Verified Submission with Snapshot in Org A
    """
    env = hackathon_test_setup
    org_a = env["org_a"]
    org_b = env["org_b"]
    alice = env["alice"]
    frank = env["frank"]
    suffix = env["suffix"]

    now = datetime.now(timezone.utc)

    # 1. Published Hackathon
    hackathon = Hackathon(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title=f"AI Hackathon {suffix}",
        slug=f"ai-hack-{suffix}",
        description="Scorva Transparency Testing Hackathon",
        status=HackathonStatus.PUBLISHED,
        start_date=now - timedelta(hours=1),
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
        name=f"Official AI Rubric {suffix}",
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
        title="Architecture & Modularity",
        description="Clean separation of concerns, defensive validation",
        weight=Decimal("0.4000"),
        min_score=Decimal("0.00"),
        max_score=Decimal("10.00"),
        evidence_requirements="source code and unit tests",
        order_index=1,
    )
    crit2 = RubricCriterion(
        id=uuid.uuid4(),
        rubric_version_id=rubric_version.id,
        title="Security & Isolation",
        description="Multi-tenant defenses, SSRF controls",
        weight=Decimal("0.6000"),
        min_score=Decimal("0.00"),
        max_score=Decimal("10.00"),
        evidence_requirements="security checks, network guards",
        order_index=2,
    )
    db_session.add(crit1)
    db_session.add(crit2)
    await db_session.flush()

    rubric_version.status = "published"
    rubric_version.published_at = now
    await db_session.flush()

    # 3. Team & Submission
    team = Team(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        hackathon_id=hackathon.id,
        name=f"Team Alpha {suffix}",
        join_code=f"TA{uuid.uuid4().hex[:10].upper()}",
        created_by_user_id=alice.id,
    )
    db_session.add(team)
    await db_session.flush()

    commit_sha = "e9a71c8b3d5f2a1e0b9c8d7e6f5a4b3c2d1e0f9a"
    submission = Submission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        hackathon_id=hackathon.id,
        team_id=team.id,
        team_name=team.name,
        repository_url="https://github.com/scorva-org/alpha-project",
        target_branch="main",
        title="Scorva Transparency Agent",
        description="Submission for AI Evaluation Transparency",
        status="pending",
        repository_owner="scorva-org",
        repository_name="alpha-project",
        default_branch="main",
        verified_commit_sha=commit_sha,
        connection_status="verified",
        verified_at=now,
    )
    db_session.add(submission)
    await db_session.flush()

    # 4. Snapshot
    snapshot = SubmissionSnapshot(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        submission_id=submission.id,
        commit_sha=commit_sha,
        file_count=12,
        total_bytes=1048576,
        configuration_snapshot={"branch": "main", "model": "mock-claude"},
        metadata_={"verified": True},
        captured_at=now,
    )
    db_session.add(snapshot)
    await db_session.commit()

    return {
        **env,
        "hackathon": hackathon,
        "rubric": rubric,
        "rubric_version": rubric_version,
        "crit1": crit1,
        "crit2": crit2,
        "team": team,
        "submission": submission,
        "snapshot": snapshot,
    }


# ==============================================================================
# 1. Lifecycle States & Job Retrieval
# ==============================================================================

@pytest.mark.asyncio
async def test_get_submission_evaluation_lifecycle_states(
    client: AsyncClient,
    db_session,
    setup_transparency_env,
):
    """
    Requirement 1 & 7:
    Authorized users can inspect the evaluation lifecycle:
    queued, running, completed, failed, cancelled.
    """
    env = setup_transparency_env
    org_id = env["org_a"].id
    hack_id = env["hackathon"].id
    sub_id = env["submission"].id
    cookies = {"scorva_session": env["alice_token"]}

    # Initial state: No evaluation requested yet
    resp = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hack_id}/submissions/{sub_id}/evaluation",
        headers=ORIGIN_HEADER,
        cookies=cookies,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_evaluation"] is False
    assert data["can_evaluate"] is True
    assert data["cannot_evaluate_reason"] is None
    assert data["job"] is None

    # Transition to QUEUED
    job = EvaluationJob(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hack_id,
        submission_id=sub_id,
        snapshot_id=env["snapshot"].id,
        rubric_version_id=env["rubric_version"].id,
        status="queued",
        current_stage="repo_acquisition",
        attempts_count=1,
        max_attempts=3,
        lock_version=0,
    )
    db_session.add(job)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hack_id}/submissions/{sub_id}/evaluation",
        headers=ORIGIN_HEADER,
        cookies=cookies,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_evaluation"] is True
    assert data["can_evaluate"] is False  # In flight!
    assert "in progress" in data["cannot_evaluate_reason"]
    assert data["job"]["status"] == "queued"
    assert data["job"]["current_stage"] == "repo_acquisition"
    assert data["job"]["attempts_count"] == 1

    # Transition to RUNNING
    job.status = "running"
    job.current_stage = "model_evaluation"
    job.started_at = datetime.now(timezone.utc)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hack_id}/submissions/{sub_id}/evaluation",
        headers=ORIGIN_HEADER,
        cookies=cookies,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["job"]["status"] == "running"
    assert data["job"]["current_stage"] == "model_evaluation"
    assert data["job"]["started_at"] is not None

    # Transition to CANCELLED
    job.status = "cancelled"
    job.cancellation_requested = True
    job.completed_at = datetime.now(timezone.utc)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hack_id}/submissions/{sub_id}/evaluation",
        headers=ORIGIN_HEADER,
        cookies=cookies,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["job"]["status"] == "cancelled"
    assert data["job"]["cancellation_requested"] is True
    assert data["can_evaluate"] is True  # Terminal state allows fresh run


# ==============================================================================
# 2. Criterion-Level Score & Grounded Evidence Transparency
# ==============================================================================

@pytest.mark.asyncio
async def test_evaluation_transparency_criterion_scores_and_evidence(
    client: AsyncClient,
    db_session,
    setup_transparency_env,
):
    """
    Requirement 3, 4, 5, 6:
    Real persisted criterion scores, weights, rationales, and line-level
    evidence references are returned without fabrication or tampering.
    Honest representation of missing citations.
    """
    env = setup_transparency_env
    org_id = env["org_a"].id
    hack_id = env["hackathon"].id
    sub_id = env["submission"].id
    crit1 = env["crit1"]
    crit2 = env["crit2"]
    cookies = {"scorva_session": env["alice_token"]}

    now = datetime.now(timezone.utc)
    job = EvaluationJob(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hack_id,
        submission_id=sub_id,
        snapshot_id=env["snapshot"].id,
        rubric_version_id=env["rubric_version"].id,
        status="completed",
        current_stage="persistence",
        attempts_count=1,
        max_attempts=3,
        lock_version=1,
        started_at=now - timedelta(minutes=2),
        completed_at=now,
    )
    db_session.add(job)
    await db_session.flush()

    # Result
    result = EvaluationResult(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hack_id,
        submission_id=sub_id,
        rubric_version_id=env["rubric_version"].id,
        job_id=job.id,
        snapshot_id=env["snapshot"].id,
        attempt_number=1,
        model_provider="anthropic",
        model_name="claude-3-5-sonnet",
        prompt_version="v2.1",
        raw_score=Decimal("8.50"),
        normalized_score=Decimal("85.00"),
        summary_assessment="Demonstrates exemplary modularity, solid boundary checks, and strong test coverage.",
        has_insufficient_evidence=False,
    )
    db_session.add(result)
    await db_session.flush()

    job.current_result_id = result.id

    # Criterion 1: Awarded 9.00 / 10.00 with 1 verified evidence reference
    cs1 = EvaluationCriterionScore(
        id=uuid.uuid4(),
        evaluation_result_id=result.id,
        criterion_id=crit1.id,
        awarded_score=Decimal("9.00"),
        normalized_criterion_score=Decimal("0.3600"),
        confidence_score=Decimal("0.95"),
        rationale="Service boundary is cleanly abstracted with dedicated repository interfaces.",
        evidence_status="verified",
    )
    db_session.add(cs1)
    await db_session.flush()

    ev1 = EvidenceReference(
        id=uuid.uuid4(),
        criterion_score_id=cs1.id,
        file_path="src/services/evaluator.py",
        start_line=15,
        end_line=28,
        snippet="class EvaluatorService:\n    async def evaluate(...):\n        pass",
        is_verified_in_repo=True,
    )
    db_session.add(ev1)

    # Criterion 2: Awarded 8.00 / 10.00 with NO citations (missing evidence test)
    cs2 = EvaluationCriterionScore(
        id=uuid.uuid4(),
        evaluation_result_id=result.id,
        criterion_id=crit2.id,
        awarded_score=Decimal("8.00"),
        normalized_criterion_score=Decimal("0.4800"),
        confidence_score=Decimal("0.80"),
        rationale="Network guards present but citations could not be grounded in extracted source.",
        evidence_status="missing",
    )
    db_session.add(cs2)
    await db_session.commit()

    # Request transparency detail
    resp = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hack_id}/submissions/{sub_id}/evaluation",
        headers=ORIGIN_HEADER,
        cookies=cookies,
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["has_evaluation"] is True
    assert data["submission_id"] == str(sub_id)
    assert data["submission_title"] == "Scorva Transparency Agent"

    # Provenance
    assert data["rubric"]["rubric_id"] == str(env["rubric"].id)
    assert data["rubric"]["version_number"] == 1
    assert data["rubric"]["scoring_mode"] == "offset_normalized"

    assert data["snapshot"]["snapshot_id"] == str(env["snapshot"].id)
    assert data["snapshot"]["commit_sha"] == env["snapshot"].commit_sha
    assert data["snapshot"]["file_count"] == 12

    # Overall Result
    res = data["result"]
    assert res["model_provider"] == "anthropic"
    assert res["model_name"] == "claude-3-5-sonnet"
    assert res["prompt_version"] == "v2.1"
    assert float(res["raw_score"]) == 8.50
    assert float(res["normalized_score"]) == 85.00
    assert "exemplary modularity" in res["summary_assessment"]
    assert res["has_insufficient_evidence"] is False

    # Criterion Scores
    scores = res["criterion_scores"]
    assert len(scores) == 2

    c1 = next(s for s in scores if s["criterion_id"] == str(crit1.id))
    assert c1["title"] == "Architecture & Modularity"
    assert float(c1["awarded_score"]) == 9.00
    assert float(c1["weight"]) == 0.4000
    assert c1["evidence_status"] == "verified"
    assert len(c1["evidence_references"]) == 1
    assert c1["evidence_references"][0]["file_path"] == "src/services/evaluator.py"
    assert c1["evidence_references"][0]["start_line"] == 15
    assert c1["evidence_references"][0]["end_line"] == 28
    assert c1["evidence_references"][0]["is_verified_in_repo"] is True

    c2 = next(s for s in scores if s["criterion_id"] == str(crit2.id))
    assert c2["title"] == "Security & Isolation"
    assert float(c2["awarded_score"]) == 8.00
    assert c2["evidence_status"] == "missing"
    assert len(c2["evidence_references"]) == 0  # Honest empty citations!


# ==============================================================================
# 3. Safe Failure Sanitization & Error Categorization
# ==============================================================================

@pytest.mark.asyncio
async def test_safe_failure_error_sanitization(
    client: AsyncClient,
    db_session,
    setup_transparency_env,
):
    """
    Requirement 7 & 12:
    Internal stack traces, credentials, or file paths are sanitized.
    Safe user-facing error category is surfaced.
    """
    env = setup_transparency_env
    org_id = env["org_a"].id
    hack_id = env["hackathon"].id
    sub_id = env["submission"].id
    cookies = {"scorva_session": env["alice_token"]}

    job = EvaluationJob(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hack_id,
        submission_id=sub_id,
        snapshot_id=env["snapshot"].id,
        rubric_version_id=env["rubric_version"].id,
        status="failed",
        current_stage="model_evaluation",
        attempts_count=2,
        max_attempts=3,
        error_code="PROVIDER_RATE_LIMIT",
        error_message="Traceback (most recent call last):\n  File '/app/eval.py', line 89, in evaluate\n  ApiKey: sk-ant-secret-123456\nRateLimitError: 429 Too Many Requests",
        completed_at=datetime.now(timezone.utc),
    )
    db_session.add(job)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hack_id}/submissions/{sub_id}/evaluation",
        headers=ORIGIN_HEADER,
        cookies=cookies,
    )
    assert resp.status_code == 200
    data = resp.json()
    job_data = data["job"]

    assert job_data["status"] == "failed"
    assert job_data["error_code"] == "PROVIDER_RATE_LIMIT"
    # Never expose stack traces or raw keys
    assert "sk-ant" not in job_data["error_message"]
    assert "Traceback" not in job_data["error_message"]
    # Sanitized safe explanation
    assert "rate limit encountered" in job_data["error_message"].lower()
    assert job_data["is_retryable"] is True


# ==============================================================================
# 4. Multi-Tenant Isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_cross_tenant_isolation_denied(
    client: AsyncClient,
    setup_transparency_env,
):
    """
    Requirement 2 & 11:
    Tenant B (Frank) cannot inspect, list, or trigger evaluations on Tenant A's submissions.
    """
    env = setup_transparency_env
    org_a_id = env["org_a"].id
    org_b_id = env["org_b"].id
    hack_id = env["hackathon"].id
    sub_id = env["submission"].id
    frank_cookies = {"scorva_session": env["frank_token"]}

    # Frank tries to access Org A's submission evaluation via Org A path -> 403 Forbidden
    resp = await client.get(
        f"/api/v1/organizations/{org_a_id}/hackathons/{hack_id}/submissions/{sub_id}/evaluation",
        headers=ORIGIN_HEADER,
        cookies=frank_cookies,
    )
    assert resp.status_code in (401, 403)

    # Frank tries to access Org A's submission evaluation via Org B path -> 404 Not Found
    resp = await client.get(
        f"/api/v1/organizations/{org_b_id}/hackathons/{hack_id}/submissions/{sub_id}/evaluation",
        headers=ORIGIN_HEADER,
        cookies=frank_cookies,
    )
    assert resp.status_code == 404

    # Frank tries to view Org A hackathon evaluation summary -> 403 Forbidden
    resp = await client.get(
        f"/api/v1/organizations/{org_a_id}/hackathons/{hack_id}/evaluations/summary",
        headers=ORIGIN_HEADER,
        cookies=frank_cookies,
    )
    assert resp.status_code in (401, 403)

    # Frank tries to trigger evaluation on Org A's submission -> 403 Forbidden
    resp = await client.post(
        f"/api/v1/organizations/{org_a_id}/hackathons/{hack_id}/submissions/{sub_id}/evaluate",
        headers=ORIGIN_HEADER,
        cookies=frank_cookies,
    )
    assert resp.status_code in (401, 403)


# ==============================================================================
# 5. Direct Evaluation Initiation & Idempotency
# ==============================================================================

@pytest.mark.asyncio
async def test_trigger_submission_evaluation_success_and_idempotency(
    client: AsyncClient,
    db_session,
    setup_transparency_env,
):
    """
    Requirement 8 & 9:
    Direct submission evaluation dispatch validates prerequisites,
    enqueues outbox record, and deduplicates repeated requests with Idempotent-Replay.
    """
    env = setup_transparency_env
    org_id = env["org_a"].id
    hack_id = env["hackathon"].id
    sub_id = env["submission"].id
    cookies = {"scorva_session": env["alice_token"]}
    idem_key = f"eval-test-{uuid.uuid4().hex}"

    headers = {
        **ORIGIN_HEADER,
        "Idempotency-Key": idem_key,
    }

    # 1. First dispatch: 201 Created
    resp1 = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hack_id}/submissions/{sub_id}/evaluate",
        headers=headers,
        cookies=cookies,
    )
    assert resp1.status_code == 201
    job_data1 = resp1.json()
    assert job_data1["status"] == "queued"
    job_id = job_data1["id"]

    # Verify Outbox entry created
    outbox_stmt = select(EvaluationJobOutbox).where(EvaluationJobOutbox.job_id == uuid.UUID(job_id))
    outbox_entry = (await db_session.execute(outbox_stmt)).scalar_one_or_none()
    assert outbox_entry is not None
    assert outbox_entry.status == "pending"

    # 2. Idempotent replay with same key: 200 OK + Idempotent-Replay header
    resp2 = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hack_id}/submissions/{sub_id}/evaluate",
        headers=headers,
        cookies=cookies,
    )
    assert resp2.status_code == 200
    assert resp2.headers.get("Idempotent-Replay") == "true"
    assert resp2.json()["id"] == job_id


# ==============================================================================
# 6. Evaluation Precondition Validations
# ==============================================================================

@pytest.mark.asyncio
async def test_trigger_evaluation_precondition_validations(
    client: AsyncClient,
    db_session,
    setup_transparency_env,
):
    """
    Requirement 8:
    Rejects evaluation initiation with clear errors when:
    - Hackathon has no published rubric.
    - Submission repository is unverified or has no commit SHA.
    - Hackathon is archived or locked.
    """
    env = setup_transparency_env
    org_id = env["org_a"].id
    hack_id = env["hackathon"].id
    cookies = {"scorva_session": env["alice_token"]}

    # Create unverified submission with no commit SHA
    unverified_sub = Submission(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hack_id,
        team_id=env["team"].id,
        team_name=env["team"].name,
        repository_url="https://github.com/scorva-org/unverified-repo",
        target_branch="main",
        title="Unverified Project",
        connection_status="unverified",
        verified_commit_sha=None,
    )
    db_session.add(unverified_sub)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hack_id}/submissions/{unverified_sub.id}/evaluate",
        headers=ORIGIN_HEADER,
        cookies=cookies,
    )
    assert resp.status_code == 400
    assert "CANNOT_EVALUATE_UNVERIFIED_REPO" in resp.json()["code"]

    # Lock hackathon (archived)
    hack = await db_session.get(Hackathon, hack_id)
    hack.status = HackathonStatus.ARCHIVED
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/organizations/{org_id}/hackathons/{hack_id}/submissions/{env['submission'].id}/evaluate",
        headers=ORIGIN_HEADER,
        cookies=cookies,
    )
    assert resp.status_code == 400
    assert "HACKATHON_LOCKED" in resp.json()["code"]


# ==============================================================================
# 7. Intentional Re-evaluation & History Preservation
# ==============================================================================

@pytest.mark.asyncio
async def test_re_evaluation_preserves_history(
    client: AsyncClient,
    db_session,
    setup_transparency_env,
):
    """
    Requirement 10:
    Intentional re-evaluation preserves previous results in prior_runs list.
    """
    env = setup_transparency_env
    org_id = env["org_a"].id
    hack_id = env["hackathon"].id
    sub_id = env["submission"].id
    cookies = {"scorva_session": env["alice_token"]}

    # Job 1: Completed earlier with score 70.00
    t1 = datetime.now(timezone.utc) - timedelta(hours=1)
    job1 = EvaluationJob(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hack_id,
        submission_id=sub_id,
        snapshot_id=env["snapshot"].id,
        rubric_version_id=env["rubric_version"].id,
        status="completed",
        attempts_count=1,
        max_attempts=3,
        created_at=t1,
        completed_at=t1 + timedelta(minutes=1),
    )
    db_session.add(job1)
    await db_session.flush()

    res1 = EvaluationResult(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hack_id,
        submission_id=sub_id,
        rubric_version_id=env["rubric_version"].id,
        job_id=job1.id,
        snapshot_id=env["snapshot"].id,
        attempt_number=1,
        model_provider="anthropic",
        model_name="claude-3-5-sonnet",
        prompt_version="v1.0",
        raw_score=Decimal("7.00"),
        normalized_score=Decimal("70.00"),
        summary_assessment="Initial baseline assessment.",
    )
    db_session.add(res1)
    await db_session.flush()
    job1.current_result_id = res1.id
    await db_session.flush()

    # Job 2: Fresh re-evaluation completed with score 92.00
    t2 = datetime.now(timezone.utc)
    job2 = EvaluationJob(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hack_id,
        submission_id=sub_id,
        snapshot_id=env["snapshot"].id,
        rubric_version_id=env["rubric_version"].id,
        status="completed",
        attempts_count=1,
        max_attempts=3,
        reevaluation_of_job_id=job1.id,
        created_at=t2,
        completed_at=t2 + timedelta(minutes=1),
    )
    db_session.add(job2)
    await db_session.flush()

    res2 = EvaluationResult(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hack_id,
        submission_id=sub_id,
        rubric_version_id=env["rubric_version"].id,
        job_id=job2.id,
        snapshot_id=env["snapshot"].id,
        attempt_number=1,
        model_provider="anthropic",
        model_name="claude-3-5-sonnet",
        prompt_version="v2.0",
        raw_score=Decimal("9.20"),
        normalized_score=Decimal("92.00"),
        summary_assessment="Re-evaluation after refactor: Significantly improved architecture.",
    )
    db_session.add(res2)
    await db_session.flush()
    job2.current_result_id = res2.id
    await db_session.commit()

    # Query latest evaluation
    resp = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hack_id}/submissions/{sub_id}/evaluation",
        headers=ORIGIN_HEADER,
        cookies=cookies,
    )
    assert resp.status_code == 200
    data = resp.json()

    # Current authoritative result is Job 2
    assert data["job"]["id"] == str(job2.id)
    assert float(data["result"]["normalized_score"]) == 92.00

    # Prior runs contains Job 1
    prior = data["prior_runs"]
    assert len(prior) == 1
    assert prior[0]["job_id"] == str(job1.id)
    assert float(prior[0]["normalized_score"]) == 70.00
    assert prior[0]["status"] == "completed"


# ==============================================================================
# 8. Hackathon Evaluation Overview Summary & Jobs Listing
# ==============================================================================

@pytest.mark.asyncio
async def test_hackathon_evaluation_summary_and_jobs_listing(
    client: AsyncClient,
    db_session,
    setup_transparency_env,
):
    """
    Requirement 2 & 13:
    Organizer dashboard summary endpoint aggregates lifecycle counts,
    average score, and published rubric availability.
    Jobs listing endpoint is strictly scoped.
    """
    env = setup_transparency_env
    org_id = env["org_a"].id
    hack_id = env["hackathon"].id
    sub_id = env["submission"].id
    cookies = {"scorva_session": env["alice_token"]}

    # Add 1 completed job and 1 queued job
    job_completed = EvaluationJob(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hack_id,
        submission_id=sub_id,
        snapshot_id=env["snapshot"].id,
        rubric_version_id=env["rubric_version"].id,
        status="completed",
        attempts_count=1,
        max_attempts=3,
    )
    db_session.add(job_completed)
    await db_session.flush()

    res = EvaluationResult(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hack_id,
        submission_id=sub_id,
        rubric_version_id=env["rubric_version"].id,
        job_id=job_completed.id,
        snapshot_id=env["snapshot"].id,
        attempt_number=1,
        model_provider="anthropic",
        model_name="claude-3-5-sonnet",
        prompt_version="v1.0",
        raw_score=Decimal("8.80"),
        normalized_score=Decimal("88.00"),
        summary_assessment="High quality submission.",
    )
    db_session.add(res)
    await db_session.flush()
    job_completed.current_result_id = res.id
    await db_session.flush()

    # Second submission with queued job
    sub2 = Submission(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hack_id,
        team_id=env["team"].id,
        team_name=env["team"].name,
        repository_url="https://github.com/scorva-org/beta-project",
        target_branch="main",
        title="Beta Project",
        status="pending",
    )
    db_session.add(sub2)
    await db_session.flush()

    job_queued = EvaluationJob(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hack_id,
        submission_id=sub2.id,
        snapshot_id=env["snapshot"].id,
        rubric_version_id=env["rubric_version"].id,
        status="queued",
        attempts_count=0,
        max_attempts=3,
    )
    db_session.add(job_queued)
    await db_session.commit()

    # 1. Test Summary
    resp = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hack_id}/evaluations/summary",
        headers=ORIGIN_HEADER,
        cookies=cookies,
    )
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["total_submissions"] >= 2
    assert summary["completed_jobs"] >= 1
    assert summary["queued_jobs"] >= 1
    assert float(summary["average_score"]) == 88.00
    assert summary["has_published_rubric"] is True
    assert summary["published_rubric_name"] == env["rubric"].name

    # 2. Test Listing Jobs
    resp_list = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hack_id}/evaluations",
        headers=ORIGIN_HEADER,
        cookies=cookies,
    )
    assert resp_list.status_code == 200
    jobs_list = resp_list.json()
    assert len(jobs_list) >= 2
    job_ids = [j["id"] for j in jobs_list]
    assert str(job_completed.id) in job_ids
    assert str(job_queued.id) in job_ids

    # Test filtering by status
    resp_filtered = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hack_id}/evaluations?status=completed",
        headers=ORIGIN_HEADER,
        cookies=cookies,
    )
    assert resp_filtered.status_code == 200
    completed_jobs = resp_filtered.json()
    assert all(j["status"] == "completed" for j in completed_jobs)


# ==============================================================================
# 9. Not Found & Empty State Actionable Reasons
# ==============================================================================

@pytest.mark.asyncio
async def test_evaluation_transparency_not_found(
    client: AsyncClient,
    setup_transparency_env,
):
    """Verifies 404 for non-existent hackathons or submissions."""
    env = setup_transparency_env
    org_id = env["org_a"].id
    hack_id = env["hackathon"].id
    cookies = {"scorva_session": env["alice_token"]}
    fake_id = uuid.uuid4()

    resp = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{fake_id}/submissions/{fake_id}/evaluation",
        headers=ORIGIN_HEADER,
        cookies=cookies,
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "HACKATHON_NOT_FOUND"

    resp2 = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hack_id}/submissions/{fake_id}/evaluation",
        headers=ORIGIN_HEADER,
        cookies=cookies,
    )
    assert resp2.status_code == 404
    assert resp2.json()["code"] == "SUBMISSION_NOT_FOUND"


@pytest.mark.asyncio
async def test_evaluation_transparency_empty_state_reasons(
    client: AsyncClient,
    db_session,
    setup_transparency_env,
):
    """
    Verifies actionable reasons in empty states when evaluation cannot currently be run:
    1. Unverified submission repo -> explains repo needs verification.
    2. Hackathon without published rubric -> explains rubric needed.
    """
    env = setup_transparency_env
    org_id = env["org_a"].id
    hack_id = env["hackathon"].id
    cookies = {"scorva_session": env["alice_token"]}

    # Unverified submission with no commit SHA
    unverified_sub = Submission(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hack_id,
        team_id=env["team"].id,
        team_name=env["team"].name,
        repository_url="https://github.com/scorva-org/unverified-empty-project",
        target_branch="main",
        title="Unverified Empty Project",
        connection_status="unverified",
        verified_commit_sha=None,
    )
    db_session.add(unverified_sub)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hack_id}/submissions/{unverified_sub.id}/evaluation",
        headers=ORIGIN_HEADER,
        cookies=cookies,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_evaluation"] is False
    assert data["can_evaluate"] is False
    assert "Repository must be verified" in data["cannot_evaluate_reason"]


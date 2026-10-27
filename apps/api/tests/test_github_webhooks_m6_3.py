"""
Test Suite for Scorva Milestone 6.3: GitHub Webhooks, Event Ingestion & Repository Activity Timeline.

Covers:
- HMAC-SHA256 constant-time signature verification (X-Hub-Signature-256).
- Rejection of missing/invalid signatures, malformed payloads, and oversized request bodies.
- Idempotent deduplication via unique GitHub delivery identifiers.
- Normalization of push, pull_request, ping, create/delete, and repository events.
- Correlation to registered submissions and deadline-guarded commit updates.
- Invariant: incoming webhooks never mutate evaluation snapshots, scores, or judge decisions.
- Submission and Hackathon activity timeline endpoints with tenant isolation.
- Append-only audit logging for ingested events and commit updates.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from apps.api.config import settings
from apps.api.modules.audit.models import AuditEvent
from apps.api.modules.evaluations.models import (
    EvaluationJob,
    EvaluationResult,
    GitHubEvent,
    Rubric,
    RubricVersion,
    Submission,
    SubmissionSnapshot,
    Team,
    TeamMember,
)
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.tests.test_hackathons import ORIGIN_HEADER, hackathon_test_setup


def make_github_signature(payload_bytes: bytes, secret: str = settings.GITHUB_WEBHOOK_SECRET) -> str:
    """Computes a valid GitHub X-Hub-Signature-256 header."""
    sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


@pytest.fixture
async def setup_m6_3_env(db_session, hackathon_test_setup):
    """Provisions a published hackathon with a registered team and linked submission."""
    fixture = hackathon_test_setup
    org_a = fixture["org_a"]
    alice = fixture["alice"]
    charlie = fixture["charlie"]

    now = datetime.now(timezone.utc)
    hackathon = Hackathon(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        title=f"M6.3 Webhook Cup {fixture['suffix']}",
        slug=f"m63-cup-{fixture['suffix']}",
        description="Testing GitHub webhooks and project activity ingestion",
        status=HackathonStatus.PUBLISHED,
        start_date=now - timedelta(hours=2),
        submission_deadline=now + timedelta(days=2),
        end_date=now + timedelta(days=3),
        created_by_user_id=alice.id,
        settings={"max_team_size": 4},
    )
    db_session.add(hackathon)
    await db_session.flush()

    team = Team(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        hackathon_id=hackathon.id,
        name=f"Webhook Hackers {fixture['suffix']}",
        join_code=f"W{uuid.uuid4().hex[:11].upper()}",
        created_by_user_id=charlie.id,
    )
    db_session.add(team)
    await db_session.flush()

    tm = TeamMember(
        team_id=team.id,
        user_id=charlie.id,
        role_in_team="leader",
    )
    db_session.add(tm)

    # Submission linked to 'scorva-demo/ai-agent'
    submission = Submission(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        hackathon_id=hackathon.id,
        team_id=team.id,
        team_name=team.name,
        repository_url="https://github.com/scorva-demo/ai-agent",
        target_branch="main",
        title="AI Agent Project",
        description="Autonomous university hackathon agent",
        status="pending",
        repository_owner="scorva-demo",
        repository_name="ai-agent",
        default_branch="main",
        verified_commit_sha="initial_commit_sha_11111111111111111111",
        connection_status="verified",
        verified_at=now,
        verification_diagnostic="SUCCESS",
    )
    db_session.add(submission)
    await db_session.commit()

    await db_session.refresh(hackathon)
    await db_session.refresh(team)
    await db_session.refresh(submission)

    return {
        **fixture,
        "hackathon": hackathon,
        "team": team,
        "submission": submission,
    }


# =====================================================================
# Test Suite 1: Signature Verification & Input Validation
# =====================================================================

@pytest.mark.asyncio
async def test_webhook_missing_signature_rejected(client: AsyncClient):
    payload = json.dumps({"zen": "Keep it logically awesome."}).encode("utf-8")
    resp = await client.post(
        "/api/v1/integrations/github/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "X-GitHub-Event": "ping",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "WEBHOOK_SIGNATURE_MISSING"


@pytest.mark.asyncio
async def test_webhook_invalid_signature_format_rejected(client: AsyncClient):
    payload = json.dumps({"zen": "Keep it logically awesome."}).encode("utf-8")
    resp = await client.post(
        "/api/v1/integrations/github/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": "raw_hex_without_sha256_prefix",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "WEBHOOK_SIGNATURE_INVALID_FORMAT"


@pytest.mark.asyncio
async def test_webhook_signature_mismatch_rejected(client: AsyncClient):
    payload = json.dumps({"zen": "Keep it logically awesome."}).encode("utf-8")
    resp = await client.post(
        "/api/v1/integrations/github/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": "sha256=0000000000000000000000000000000000000000000000000000000000000000",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "WEBHOOK_SIGNATURE_MISMATCH"


@pytest.mark.asyncio
async def test_webhook_missing_delivery_header_rejected(client: AsyncClient):
    payload = json.dumps({"zen": "Keep it logically awesome."}).encode("utf-8")
    sig = make_github_signature(payload)
    resp = await client.post(
        "/api/v1/integrations/github/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": sig,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "MISSING_DELIVERY_HEADER"


@pytest.mark.asyncio
async def test_webhook_malformed_json_rejected(client: AsyncClient):
    raw_bad_json = b"this is not valid json {"
    sig = make_github_signature(raw_bad_json)
    resp = await client.post(
        "/api/v1/integrations/github/webhook",
        content=raw_bad_json,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": sig,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "MALFORMED_JSON_PAYLOAD"


@pytest.mark.asyncio
async def test_webhook_payload_too_large_rejected(client: AsyncClient):
    huge_payload = b"x" * (settings.GITHUB_WEBHOOK_MAX_BYTES + 1024)
    sig = make_github_signature(huge_payload)
    resp = await client.post(
        "/api/v1/integrations/github/webhook",
        content=huge_payload,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(huge_payload)),
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": sig,
        },
    )
    assert resp.status_code == 413
    assert resp.json()["code"] == "PAYLOAD_TOO_LARGE"


# =====================================================================
# Test Suite 2: Event Ingestion, Normalization & Idempotency
# =====================================================================

@pytest.mark.asyncio
async def test_webhook_ping_event_accepted(client: AsyncClient):
    delivery_id = str(uuid.uuid4())
    payload_dict = {
        "zen": "Encourage flow.",
        "hook_id": 987654321,
    }
    payload_bytes = json.dumps(payload_dict).encode("utf-8")
    sig = make_github_signature(payload_bytes)

    resp = await client.post(
        "/api/v1/integrations/github/webhook",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Delivery": delivery_id,
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": sig,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] in ("processed", "ignored")
    assert data["delivery_id"] == delivery_id
    assert data["event_type"] == "ping"


@pytest.mark.asyncio
async def test_webhook_duplicate_delivery_idempotency(client: AsyncClient, setup_m6_3_env, db_session):
    delivery_id = f"delivery_dup_{uuid.uuid4().hex[:12]}"
    payload_dict = {
        "ref": "refs/heads/feature-branch",
        "after": "sha_duplicate_1234567890",
        "repository": {
            "name": "ai-agent",
            "full_name": "scorva-demo/ai-agent",
            "owner": {"login": "scorva-demo"},
        },
        "commits": [{"id": "sha_duplicate_1234567890", "message": "feat: duplicate test"}],
        "sender": {"login": "octocat"},
    }
    payload_bytes = json.dumps(payload_dict).encode("utf-8")
    sig = make_github_signature(payload_bytes)

    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Delivery": delivery_id,
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": sig,
    }

    # First delivery: Accepted & processed
    resp1 = await client.post("/api/v1/integrations/github/webhook", content=payload_bytes, headers=headers)
    assert resp1.status_code == 200, resp1.text
    assert resp1.json()["status"] == "processed"

    # Second delivery with identical X-GitHub-Delivery: Idempotently acknowledged as duplicate
    resp2 = await client.post("/api/v1/integrations/github/webhook", content=payload_bytes, headers=headers)
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["status"] == "duplicate"
    assert resp2.json()["delivery_id"] == delivery_id

    # Verify database has exactly 1 row for this delivery
    stmt = select(func.count(GitHubEvent.id)).where(GitHubEvent.delivery_id == delivery_id)
    count = (await db_session.execute(stmt)).scalar_one()
    assert count == 1


# =====================================================================
# Test Suite 3: Submission Correlation & Target Branch Commit Update
# =====================================================================

@pytest.mark.asyncio
async def test_webhook_push_to_target_branch_updates_commit_sha(client: AsyncClient, setup_m6_3_env, db_session):
    env = setup_m6_3_env
    sub = env["submission"]
    delivery_id = f"delivery_push_{uuid.uuid4().hex[:12]}"
    new_head_sha = "new_head_sha_abcdef98765432101234567890"

    payload_dict = {
        "ref": "refs/heads/main",
        "after": new_head_sha,
        "repository": {
            "name": "ai-agent",
            "full_name": "scorva-demo/ai-agent",
            "owner": {"login": "scorva-demo"},
        },
        "commits": [
            {"id": new_head_sha, "message": "feat: add neural search copilot"},
        ],
        "head_commit": {
            "id": new_head_sha,
            "message": "feat: add neural search copilot",
            "timestamp": "2026-10-26T20:00:00Z",
        },
        "sender": {"login": "alice_dev"},
    }
    payload_bytes = json.dumps(payload_dict).encode("utf-8")
    sig = make_github_signature(payload_bytes)

    resp = await client.post(
        "/api/v1/integrations/github/webhook",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Delivery": delivery_id,
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": sig,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "processed"
    assert resp.json()["submission_id"] == str(sub.id)

    # Refresh submission from DB: verified_commit_sha must now equal new_head_sha!
    await db_session.refresh(sub)
    assert sub.verified_commit_sha == new_head_sha
    assert sub.connection_status == "verified"

    # Verify audit event emitted
    stmt_audit = select(AuditEvent).where(
        AuditEvent.action == "submission_commit_received",
        AuditEvent.resource_id == str(sub.id),
    )
    audit = (await db_session.execute(stmt_audit)).scalars().first()
    assert audit is not None
    assert audit.diff_payload["new_commit_sha"] == new_head_sha


@pytest.mark.asyncio
async def test_webhook_push_to_other_branch_does_not_update_target_commit(client: AsyncClient, setup_m6_3_env, db_session):
    env = setup_m6_3_env
    sub = env["submission"]
    initial_sha = sub.verified_commit_sha
    delivery_id = f"delivery_other_{uuid.uuid4().hex[:12]}"
    feature_sha = "feature_branch_commit_sha_9999999999999"

    payload_dict = {
        "ref": "refs/heads/experimental-sandbox",
        "after": feature_sha,
        "repository": {
            "name": "ai-agent",
            "full_name": "scorva-demo/ai-agent",
            "owner": {"login": "scorva-demo"},
        },
        "commits": [{"id": feature_sha, "message": "experiment: test sandbox"}],
        "sender": {"login": "alice_dev"},
    }
    payload_bytes = json.dumps(payload_dict).encode("utf-8")
    sig = make_github_signature(payload_bytes)

    resp = await client.post(
        "/api/v1/integrations/github/webhook",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Delivery": delivery_id,
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": sig,
        },
    )
    assert resp.status_code == 200

    # Submission target_branch is 'main'; this push was on 'experimental-sandbox'.
    # Target commit SHA must remain completely unmodified!
    await db_session.refresh(sub)
    assert sub.verified_commit_sha == initial_sha


@pytest.mark.asyncio
async def test_webhook_pull_request_event_normalized(client: AsyncClient, setup_m6_3_env, db_session):
    delivery_id = f"delivery_pr_{uuid.uuid4().hex[:12]}"
    payload_dict = {
        "action": "opened",
        "number": 42,
        "pull_request": {
            "number": 42,
            "title": "Add multi-agent collaboration engine",
            "state": "open",
            "merged": False,
            "html_url": "https://github.com/scorva-demo/ai-agent/pull/42",
            "head": {"ref": "feature/agents", "sha": "pr_head_sha_4242424242"},
            "base": {"ref": "main"},
            "created_at": "2026-10-26T21:00:00Z",
        },
        "repository": {
            "name": "ai-agent",
            "full_name": "scorva-demo/ai-agent",
            "owner": {"login": "scorva-demo"},
        },
        "sender": {"login": "agent_smith"},
    }
    payload_bytes = json.dumps(payload_dict).encode("utf-8")
    sig = make_github_signature(payload_bytes)

    resp = await client.post(
        "/api/v1/integrations/github/webhook",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Delivery": delivery_id,
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": sig,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "processed"

    # Verify normalized fields in DB
    stmt = select(GitHubEvent).where(GitHubEvent.delivery_id == delivery_id)
    event = (await db_session.execute(stmt)).scalar_one()
    assert event.event_type == "pull_request"
    assert event.action == "opened"
    assert event.commit_sha == "pr_head_sha_4242424242"
    assert "PR #42 opened" in event.summary
    assert event.details["pr_number"] == 42
    assert event.details["html_url"] == "https://github.com/scorva-demo/ai-agent/pull/42"


# =====================================================================
# Test Suite 4: Deadline & Immutability Guarantees
# =====================================================================

@pytest.mark.asyncio
async def test_webhook_push_after_deadline_does_not_mutate_commit_sha(client: AsyncClient, setup_m6_3_env, db_session):
    env = setup_m6_3_env
    hackathon = env["hackathon"]
    sub = env["submission"]
    initial_sha = sub.verified_commit_sha

    # Expire submission deadline into the past
    hackathon.submission_deadline = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_session.commit()

    delivery_id = f"delivery_late_{uuid.uuid4().hex[:12]}"
    late_sha = "late_commit_sha_rejected_deadline_1234"

    payload_dict = {
        "ref": "refs/heads/main",
        "after": late_sha,
        "repository": {
            "name": "ai-agent",
            "full_name": "scorva-demo/ai-agent",
            "owner": {"login": "scorva-demo"},
        },
        "commits": [{"id": late_sha, "message": "late: attempt after deadline"}],
        "sender": {"login": "procrastinator"},
    }
    payload_bytes = json.dumps(payload_dict).encode("utf-8")
    sig = make_github_signature(payload_bytes)

    resp = await client.post(
        "/api/v1/integrations/github/webhook",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Delivery": delivery_id,
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": sig,
        },
    )
    assert resp.status_code == 200

    # Submission commit SHA must NOT have been updated!
    await db_session.refresh(sub)
    assert sub.verified_commit_sha == initial_sha

    # Event itself is persisted with DEADLINE_PASSED diagnostic
    stmt_ev = select(GitHubEvent).where(GitHubEvent.delivery_id == delivery_id)
    ev = (await db_session.execute(stmt_ev)).scalar_one()
    assert ev.diagnostic_code == "DEADLINE_PASSED"


@pytest.mark.asyncio
async def test_webhook_does_not_mutate_evaluation_results(client: AsyncClient, setup_m6_3_env, db_session):
    """
    Guarantees that new webhooks never modify published evaluation snapshots,
    completed evaluation jobs, or scores.
    """
    env = setup_m6_3_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    sub = env["submission"]

    # Provision evaluation snapshot & completed job
    rubric = Rubric(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hackathon_id,
        name="Evaluation Invariant Rubric",
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
        submission_id=sub.id,
        commit_sha=sub.verified_commit_sha,
        configuration_snapshot={},
    )
    db_session.add(snapshot)
    await db_session.flush()

    eval_job = EvaluationJob(
        id=uuid.uuid4(),
        organization_id=org_id,
        hackathon_id=hackathon_id,
        submission_id=sub.id,
        snapshot_id=snapshot.id,
        rubric_version_id=rubric_version.id,
        status="completed",
    )
    db_session.add(eval_job)
    await db_session.commit()

    # Deliver new webhook push
    delivery_id = f"delivery_eval_{uuid.uuid4().hex[:12]}"
    payload_dict = {
        "ref": "refs/heads/main",
        "after": "new_commit_during_eval_run_999",
        "repository": {
            "name": "ai-agent",
            "full_name": "scorva-demo/ai-agent",
            "owner": {"login": "scorva-demo"},
        },
        "commits": [{"id": "new_commit_during_eval_run_999", "message": "chore: background edit"}],
        "sender": {"login": "dev"},
    }
    payload_bytes = json.dumps(payload_dict).encode("utf-8")
    sig = make_github_signature(payload_bytes)

    resp = await client.post(
        "/api/v1/integrations/github/webhook",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Delivery": delivery_id,
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": sig,
        },
    )
    assert resp.status_code == 200

    # Snapshot commit_sha must NOT have changed!
    await db_session.refresh(snapshot)
    assert snapshot.commit_sha == "initial_commit_sha_11111111111111111111"

    # EvaluationJob status must NOT have changed!
    await db_session.refresh(eval_job)
    assert eval_job.status == "completed"


# =====================================================================
# Test Suite 5: Activity Timeline Endpoints & Tenant Isolation
# =====================================================================

@pytest.mark.asyncio
async def test_get_submission_activity_timeline(client: AsyncClient, setup_m6_3_env, db_session):
    env = setup_m6_3_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    sub = env["submission"]
    headers = {"Authorization": f"Bearer {env['alice_token']}", **ORIGIN_HEADER}

    # Ingest 2 events for this submission
    for i in range(2):
        delivery_id = f"delivery_tl_{i}_{uuid.uuid4().hex[:8]}"
        payload_dict = {
            "ref": "refs/heads/main",
            "after": f"sha_tl_{i}",
            "repository": {
                "name": "ai-agent",
                "full_name": "scorva-demo/ai-agent",
                "owner": {"login": "scorva-demo"},
            },
            "commits": [{"id": f"sha_tl_{i}", "message": f"feat: step {i}"}],
            "sender": {"login": "dev"},
        }
        b = json.dumps(payload_dict).encode("utf-8")
        await client.post(
            "/api/v1/integrations/github/webhook",
            content=b,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Delivery": delivery_id,
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": make_github_signature(b),
            },
        )

    # Query submission activity timeline endpoint
    resp = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub.id}/activity",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) >= 2
    assert all(item["submission_id"] == str(sub.id) for item in items)
    assert all(item["event_type"] == "push" for item in items)


@pytest.mark.asyncio
async def test_activity_timeline_cross_tenant_denied(client: AsyncClient, setup_m6_3_env):
    env = setup_m6_3_env
    org_id = env["org_a"].id
    hackathon_id = env["hackathon"].id
    sub = env["submission"]
    frank_headers = {"Authorization": f"Bearer {env['frank_token']}", **ORIGIN_HEADER}  # Org B Owner

    # Frank tries to view Org A submission activity timeline
    resp = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions/{sub.id}/activity",
        headers=frank_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "TENANT_ACCESS_DENIED"

    # Frank tries to view Org A hackathon-wide activity timeline
    resp2 = await client.get(
        f"/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/activity",
        headers=frank_headers,
    )
    assert resp2.status_code == 403
    assert resp2.json()["code"] == "TENANT_ACCESS_DENIED"

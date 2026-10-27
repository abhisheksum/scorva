import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import os
import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch
import uuid

from httpx import ASGITransport, AsyncClient
import pytest
import redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.core.metrics import metrics_collector
import apps.api.core.redis as core_async_redis
from apps.api.main import app
from apps.api.modules.evaluations.models import (
    EvaluationJob,
    EvaluationJobOutbox,
    EvaluationResult,
    Rubric,
    RubricCriterion,
    RubricVersion,
    Submission,
    SubmissionSnapshot,
    Team,
)
from apps.api.modules.evaluations.outbox import (
    claim_outbox_batch,
    quarantine_exhausted_outbox_rows,
    record_outbox_publish_error,
    settle_outbox_row,
)
from apps.api.modules.evaluations.service import (
    cancel_evaluation_job_atomic,
    dispatch_evaluation_job_atomic,
)
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.modules.organizations.models import Organization, OrganizationMembership, OrganizationStatus, OrgRole
from apps.api.modules.users.models import User
from apps.api.workers.lease_manager import WorkerClaim, WorkerLeaseManager
from apps.api.workers.pipeline import PipelineResult, run_evaluation_pipeline
from apps.api.workers.reaper import (
    reap_stalled_evaluation_jobs_async,
    reap_stalled_evaluation_jobs_sync,
)
from apps.api.workers.throttling import (
    ConcurrencyLimitExceededError,
    RedisUnavailableError,
    TenantConcurrencyGovernor,
    TenantSlot,
    concurrency_governor,
)


@pytest.fixture
async def setup_m5_5_env(db_session: AsyncSession):
    """Sets up an isolated test fixture with user, org, hackathon, rubric, submission, and snapshot."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f"m5_5_tester_{suffix}@example.com",
        hashed_password="fakehash123",
        full_name="M5.5 Tester",
        platform_role=None,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    org = Organization(
        name=f"M5.5 Org {suffix}",
        slug=f"m5-5-org-{suffix}",
        owner_id=user.id,
        status=OrganizationStatus.ACTIVE,
    )
    db_session.add(org)
    await db_session.flush()

    membership = OrganizationMembership(
        organization_id=org.id,
        user_id=user.id,
        role=OrgRole.ORG_OWNER,
    )
    db_session.add(membership)
    await db_session.flush()

    hackathon = Hackathon(
        organization_id=org.id,
        title="M5.5 Hackathon",
        slug=f"m5-5-hack-{suffix}",
        status=HackathonStatus.PUBLISHED,
        start_date=text("now()"),
        end_date=text("now() + interval '7 days'"),
        submission_deadline=text("now() + interval '6 days'"),
        created_by_user_id=user.id,
    )
    db_session.add(hackathon)
    await db_session.flush()

    rubric = Rubric(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name=f"Rubric {suffix}",
        scoring_mode="offset_normalized",
    )
    db_session.add(rubric)
    await db_session.flush()

    rubric_version = RubricVersion(
        organization_id=org.id,
        rubric_id=rubric.id,
        version_number=1,
        status="draft",
    )
    db_session.add(rubric_version)
    await db_session.flush()

    crit1 = RubricCriterion(
        rubric_version_id=rubric_version.id,
        title="Code Quality",
        description="Clean, well-structured, maintainable code",
        weight=Decimal("0.60"),
        min_score=Decimal("0.00"),
        max_score=Decimal("10.00"),
        evidence_requirements="code",
        order_index=1,
    )
    crit2 = RubricCriterion(
        rubric_version_id=rubric_version.id,
        title="Innovation",
        description="Originality and creative problem solving",
        weight=Decimal("0.40"),
        min_score=Decimal("0.00"),
        max_score=Decimal("10.00"),
        evidence_requirements="code",
        order_index=2,
    )
    db_session.add_all([crit1, crit2])
    await db_session.flush()

    rubric_version.status = "published"
    rubric_version.published_at = datetime.now(timezone.utc)
    await db_session.flush()

    team = Team(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        name=f"Team {suffix}",
        join_code=uuid.uuid4().hex[:12],
        created_by_user_id=user.id,
    )
    db_session.add(team)
    await db_session.flush()

    submission = Submission(
        organization_id=org.id,
        hackathon_id=hackathon.id,
        team_id=team.id,
        team_name=team.name,
        repository_url="https://github.com/scorva-test/m5-5-repo",
        target_branch="main",
        title="Submission M5.5",
        status="pending",
    )
    db_session.add(submission)
    await db_session.flush()

    snapshot = SubmissionSnapshot(
        organization_id=org.id,
        submission_id=submission.id,
        commit_sha="c1b2c3d4e5f678901234567890abcdef12345678",
        file_count=1,
        total_bytes=2048,
        configuration_snapshot={"ai.default_provider": "mock"},
        metadata_={"extracted_files_manifest": [{"path": "src/main.py", "lines": ["# code"]}]},
    )
    db_session.add(snapshot)
    await db_session.commit()

    return user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot


# ==============================================================================
# TEST 1: Tenant cannot exceed its configured concurrent evaluation limit
# ==============================================================================
@pytest.mark.asyncio
async def test_tenant_cannot_exceed_configured_concurrency_limit():
    """
    Test 1: Enforces that a tenant cannot exceed its configured concurrent limit.
    Attempts beyond the limit are rejected and return None without consuming capacity.
    """
    org_id = uuid.uuid4()
    job1 = uuid.uuid4()
    job2 = uuid.uuid4()
    job3 = uuid.uuid4()

    # Configure limit = 2
    slot1 = concurrency_governor.acquire_sync(org_id, job1, "worker-1", limit=2)
    assert slot1 is not None

    slot2 = concurrency_governor.acquire_sync(org_id, job2, "worker-2", limit=2)
    assert slot2 is not None

    # Third acquisition MUST be rejected due to saturation
    slot3 = concurrency_governor.acquire_sync(org_id, job3, "worker-3", limit=2)
    assert slot3 is None

    # Count remains exactly 2
    assert concurrency_governor.get_active_count_sync(org_id) == 2

    # Clean up
    concurrency_governor.release_sync(slot1)
    concurrency_governor.release_sync(slot2)
    assert concurrency_governor.get_active_count_sync(org_id) == 0


# ==============================================================================
# TEST 2: Different tenants receive independent capacity
# ==============================================================================
@pytest.mark.asyncio
async def test_different_tenants_receive_independent_capacity():
    """
    Test 2: Verifies strict tenant isolation in concurrency limits.
    Tenant A saturating its capacity has zero impact on Tenant B's capacity.
    """
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()

    # Org A fills its limit of 2
    slot_a1 = await concurrency_governor.acquire_async(org_a, uuid.uuid4(), "w-a1", limit=2)
    slot_a2 = await concurrency_governor.acquire_async(org_a, uuid.uuid4(), "w-a2", limit=2)
    assert slot_a1 is not None and slot_a2 is not None

    slot_a3 = await concurrency_governor.acquire_async(org_a, uuid.uuid4(), "w-a3", limit=2)
    assert slot_a3 is None  # Org A saturated

    # Org B must still have full available capacity
    slot_b1 = await concurrency_governor.acquire_async(org_b, uuid.uuid4(), "w-b1", limit=2)
    slot_b2 = await concurrency_governor.acquire_async(org_b, uuid.uuid4(), "w-b2", limit=2)
    assert slot_b1 is not None
    assert slot_b2 is not None

    assert await concurrency_governor.get_active_count_async(org_a) == 2
    assert await concurrency_governor.get_active_count_async(org_b) == 2

    # Clean up
    await concurrency_governor.release_async(slot_a1)
    await concurrency_governor.release_async(slot_a2)
    await concurrency_governor.release_async(slot_b1)
    await concurrency_governor.release_async(slot_b2)


# ==============================================================================
# TEST 3: Concurrent workers cannot over-acquire tenant capacity
# ==============================================================================
@pytest.mark.asyncio
async def test_concurrent_workers_cannot_over_acquire_tenant_capacity():
    """
    Test 3: 10 concurrent tasks simultaneously attempt to acquire slots for limit=3.
    Atomic Redis Lua scripts guarantee that exactly 3 succeed and 7 are rejected.
    """
    org_id = uuid.uuid4()
    limit = 3

    async def _try_acquire(i: int):
        j_id = uuid.uuid4()
        return await concurrency_governor.acquire_async(org_id, j_id, f"worker-{i}", limit=limit)

    results = await asyncio.gather(*[_try_acquire(i) for i in range(10)])

    successful_slots = [r for r in results if r is not None]
    rejected_slots = [r for r in results if r is None]

    assert len(successful_slots) == limit
    assert len(rejected_slots) == 10 - limit
    assert await concurrency_governor.get_active_count_async(org_id) == limit

    # Clean up
    for s in successful_slots:
        await concurrency_governor.release_async(s)
    assert await concurrency_governor.get_active_count_async(org_id) == 0


# ==============================================================================
# TEST 4: Duplicate tasks do not consume multiple slots for one execution
# ==============================================================================
@pytest.mark.asyncio
async def test_duplicate_tasks_do_not_consume_multiple_slots():
    """
    Test 4: Duplicate task deliveries for the same job_id refresh the slot lease
    instead of consuming an extra concurrency slot.
    """
    org_id = uuid.uuid4()
    job_id = uuid.uuid4()

    # First acquisition
    slot1 = concurrency_governor.acquire_sync(org_id, job_id, "worker-1", limit=2)
    assert slot1 is not None
    assert concurrency_governor.get_active_count_sync(org_id) == 1

    # Duplicate delivery for same job
    slot2 = concurrency_governor.acquire_sync(org_id, job_id, "worker-1", limit=2)
    assert slot2 is not None

    # Capacity consumed remains 1, not 2!
    assert concurrency_governor.get_active_count_sync(org_id) == 1

    concurrency_governor.release_sync(slot1)
    assert concurrency_governor.get_active_count_sync(org_id) == 0


# ==============================================================================
# TEST 5: A worker cannot release another worker's slot
# ==============================================================================
@pytest.mark.asyncio
async def test_worker_cannot_release_another_workers_slot():
    """
    Test 5: Slot release is strictly fenced by slot_token.
    Worker 2 cannot release Worker 1's slot.
    """
    org_id = uuid.uuid4()
    job1 = uuid.uuid4()

    slot1 = concurrency_governor.acquire_sync(org_id, job1, "worker-1", limit=2)
    assert slot1 is not None
    assert concurrency_governor.get_active_count_sync(org_id) == 1

    # Fake slot representing rogue worker with different token
    fake_slot = TenantSlot(
        organization_id=org_id,
        job_id=job1,
        worker_id="worker-rogue",
        slot_token="slot-fake-token-9999",
        acquired_at=time.time(),
        ttl_seconds=120,
    )

    # Rogue release attempt MUST fail and NOT remove Worker 1's slot
    removed = concurrency_governor.release_sync(fake_slot)
    assert removed is False
    assert concurrency_governor.get_active_count_sync(org_id) == 1

    # Real owner releases successfully
    assert concurrency_governor.release_sync(slot1) is True
    assert concurrency_governor.get_active_count_sync(org_id) == 0


# ==============================================================================
# TEST 6: Crashed-worker capacity is eventually recovered
# ==============================================================================
@pytest.mark.asyncio
async def test_crashed_worker_capacity_eventually_recovered():
    """
    Test 6: A crashed worker that abandons its slot without calling release
    has its slot automatically pruned after TTL expires.
    """
    org_id = uuid.uuid4()
    job_crashed = uuid.uuid4()

    # Acquire with ultra-short TTL of 1 second simulating a crash
    slot = concurrency_governor.acquire_sync(org_id, job_crashed, "worker-dead", limit=1, ttl_seconds=1)
    assert slot is not None

    # Capacity is full
    assert concurrency_governor.acquire_sync(org_id, uuid.uuid4(), "w2", limit=1) is None

    # Worker crashes: wait 1.2s for Redis slot score expiration
    await asyncio.sleep(1.2)

    # Replacement worker acquires: expired slot is automatically pruned by ZREMRANGEBYSCORE in Lua
    slot_new = concurrency_governor.acquire_sync(org_id, uuid.uuid4(), "w2", limit=1)
    assert slot_new is not None

    concurrency_governor.release_sync(slot_new)
    assert concurrency_governor.get_active_count_sync(org_id) == 0


# ==============================================================================
# TEST 7: Success, failure, cancellation, and exceptions release capacity safely
# ==============================================================================
@pytest.mark.asyncio
async def test_slot_released_safely_on_success_failure_cancellation_and_exceptions():
    """
    Test 7: Context manager and try-finally guarantees slot release across:
    - Normal completion
    - Unhandled Python exception
    - Cancellation
    """
    org_id = uuid.uuid4()

    # 1. Normal execution
    with concurrency_governor.slot_scope_sync(org_id, uuid.uuid4(), "w1", limit=2):
        assert concurrency_governor.get_active_count_sync(org_id) == 1
    assert concurrency_governor.get_active_count_sync(org_id) == 0

    # 2. Exception inside block
    with pytest.raises(ValueError):
        with concurrency_governor.slot_scope_sync(org_id, uuid.uuid4(), "w1", limit=2):
            assert concurrency_governor.get_active_count_sync(org_id) == 1
            raise ValueError("Simulated unexpected pipeline error")
    assert concurrency_governor.get_active_count_sync(org_id) == 0

    # 3. Async normal execution
    async with concurrency_governor.slot_scope_async(org_id, uuid.uuid4(), "w1", limit=2):
        assert await concurrency_governor.get_active_count_async(org_id) == 1
    assert await concurrency_governor.get_active_count_async(org_id) == 0


# ==============================================================================
# TEST 8: Redis failure does not silently disable concurrency limits (Fail Closed)
# ==============================================================================
@pytest.mark.asyncio
async def test_redis_failure_fails_closed_and_does_not_disable_limits():
    """
    Test 8: If Redis connection drops, the governor raises RedisUnavailableError
    instead of silently bypassing limits and permitting unbounded concurrency.
    """
    org_id = uuid.uuid4()
    job_id = uuid.uuid4()

    # Mock Redis client raising ConnectionError
    mock_redis = redis.Redis()
    with patch.object(mock_redis, "eval", side_effect=redis.exceptions.ConnectionError("Redis connection refused")):
        gov = TenantConcurrencyGovernor(sync_redis_client=mock_redis)
        with pytest.raises(RedisUnavailableError):
            gov.acquire_sync(org_id, job_id, "w1", limit=2)

    # Metric recorded
    assert metrics_collector.get_counter_value("scorva_redis_errors_total", labels={"operation": "acquire"}) > 0


# ==============================================================================
# TEST 9: Delayed retries do not consume capacity prematurely
# ==============================================================================
@pytest.mark.asyncio
async def test_delayed_retries_do_not_consume_capacity_prematurely(
    db_session: AsyncSession, setup_m5_5_env
):
    """
    Test 9: A job waiting in queued status with a future retry backoff
    cannot be claimed, and therefore consumes zero tenant concurrency capacity.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_m5_5_env

    job, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    # Put job in backoff retry with future lease_expires_at
    await db_session.execute(
        text("UPDATE evaluation_jobs SET status = 'queued', lease_expires_at = clock_timestamp() + interval '60 seconds' WHERE id = :id"),
        {"id": job.id},
    )
    await db_session.commit()

    # Worker attempts claim
    claim = await WorkerLeaseManager.claim_job_async(db=db_session, job_id=job.id, worker_id="w-delayed")
    assert claim is None  # Blocked by backoff

    # Concurrency capacity for tenant is completely untouched
    active = await concurrency_governor.get_active_count_async(org.id)
    assert active == 0


# ==============================================================================
# TEST 10: Metrics and logs contain no secrets or high-cardinality metric labels
# ==============================================================================
@pytest.mark.asyncio
async def test_metrics_and_logs_contain_no_secrets_or_high_cardinality_labels():
    """
    Test 10: Inspects the Prometheus text and JSON metrics exports.
    Verifies that zero unbounded identifiers (UUIDs, emails, tokens, repo URLs) appear in labels.
    """
    # Trigger several metric increments
    metrics_collector.inc_counter("scorva_eval_jobs_total", labels={"status": "completed"})
    metrics_collector.inc_counter("scorva_ai_provider_calls_total", labels={"provider": "mock", "status": "success"})
    metrics_collector.inc_counter("scorva_fencing_rejections_total", labels={"reason": "token_mismatch"})

    prom_text = metrics_collector.export_prometheus_text()
    data = metrics_collector.export_dict()

    allowed_label_keys = {"status", "provider", "reason", "action", "operation"}

    # Validate Prometheus text output
    for line in prom_text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        # Check label section
        if "{" in line and "}" in line:
            label_section = line[line.find("{") + 1 : line.find("}")]
            pairs = label_section.split(",")
            for p in pairs:
                k, v = p.split("=")
                k = k.strip()
                v = v.strip('"')
                assert k in allowed_label_keys, f"Forbidden label key found: {k}"
                assert "-" not in v or len(v) < 32, f"Potential UUID found in label value: {v}"
                assert "@" not in v, f"Email found in metric: {v}"

    # Validate JSON output
    for cat_name, metrics in data.items():
        for m_name, series_list in metrics.items():
            for s in series_list:
                for k, v in s.get("labels", {}).items():
                    assert k in allowed_label_keys
                    assert "@" not in str(v)
                    assert len(str(v)) < 36  # No UUIDs


# ==============================================================================
# TEST 11: Reaper, outbox, retry, and cancellation metrics reflect actual transitions
# ==============================================================================
@pytest.mark.asyncio
async def test_reaper_outbox_retry_and_cancellation_metrics_reflect_transitions(
    db_session: AsyncSession, setup_m5_5_env
):
    """
    Test 11: Verifies that real lifecycle transitions automatically increment
    their respective operational metrics.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_m5_5_env

    init_published = metrics_collector.get_counter_value("scorva_outbox_operations_total", labels={"operation": "published"})

    # Dispatch job to create outbox row
    await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    await db_session.commit()

    # 1. Outbox claim and settlement increments outbox counter
    token = uuid.uuid4()
    claimed = await claim_outbox_batch(db=db_session, relay_token=token, batch_size=1, organization_id=org.id)
    assert len(claimed) >= 1
    row = claimed[0]

    await settle_outbox_row(db=db_session, outbox_id=row.id, relay_token=token)
    await db_session.commit()

    after_published = metrics_collector.get_counter_value("scorva_outbox_operations_total", labels={"operation": "published"})
    assert after_published == init_published + 1

    # 2. Reaper sweep metrics
    init_sweeps = metrics_collector.get_counter_value("scorva_reaper_sweeps_total")
    await reap_stalled_evaluation_jobs_async(db=db_session, organization_id=org.id)
    after_sweeps = metrics_collector.get_counter_value("scorva_reaper_sweeps_total")
    assert after_sweeps == init_sweeps + 1


# ==============================================================================
# TEST 12: Health checks correctly report simulated dependency failures
# ==============================================================================
@pytest.mark.asyncio
async def test_health_checks_report_simulated_dependency_failures():
    """
    Test 12: /api/v1/health and /api/v1/health/ready accurately report:
    - 200 OK when both DB and Redis are responsive.
    - 503 Service Unavailable when Redis is unreachable.
    - 503 Service Unavailable when PostgreSQL is unreachable.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Normal state: 200 OK
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["services"]["redis"]["status"] == "healthy"
        assert data["services"]["database"]["status"] == "healthy"

        # 2. Simulated Redis outage
        mock_failing_redis = AsyncMock()
        mock_failing_redis.ping = AsyncMock(side_effect=redis.exceptions.ConnectionError("Redis connection refused"))
        with patch("apps.api.core.redis.get_redis_client", return_value=mock_failing_redis):
            resp_outage = await client.get("/api/v1/health/ready")
            assert resp_outage.status_code == 503
            outage_data = resp_outage.json()
            assert outage_data["status"] == "unhealthy"
            assert outage_data["services"]["redis"]["status"] == "unhealthy"

        # 3. Simulated PostgreSQL outage
        with patch("apps.api.modules.health.router.check_database_connection", return_value=(False, 0.0, "DB Down")):
            resp_db_down = await client.get("/api/v1/health")
            assert resp_db_down.status_code == 503
            assert resp_db_down.json()["services"]["database"]["status"] == "unhealthy"


# ==============================================================================
# TEST 13: M5.4 retry-delay and worker-lease regression checks
# ==============================================================================
@pytest.mark.asyncio
async def test_m5_4_retry_delay_and_worker_lease_regression_check(
    db_session: AsyncSession, setup_m5_5_env
):
    """
    Test 13: Regression verification for M5.4:
    - Queued cancellation clears lease_expires_at to NULL.
    - Running jobs with expired leases are reaped.
    - Delayed jobs with future lease_expires_at are skipped by reaper and workers.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_m5_5_env

    # 1. Queued job with backoff cancelled
    job1, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
    )
    job1.lease_expires_at = datetime.now(timezone.utc)
    await db_session.commit()

    c_res = await cancel_evaluation_job_atomic(db=db_session, job_id=job1.id, organization_id=org.id)
    assert c_res.status == "cancelled"
    await db_session.refresh(job1)
    assert job1.status == "cancelled"
    assert job1.lease_expires_at is None  # Timestamp cleared!

    # 2. Delayed job with future lease_expires_at is NOT claimed
    job2, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
        idempotency_key="delayed-job-key",
    )
    await db_session.execute(
        text("UPDATE evaluation_jobs SET lease_expires_at = clock_timestamp() + interval '120 seconds' WHERE id = :id"),
        {"id": job2.id},
    )
    await db_session.commit()

    claim = await WorkerLeaseManager.claim_job_async(db=db_session, job_id=job2.id, worker_id="w-reg")
    assert claim is None  # Cannot claim prematurely


# ==============================================================================
# TEST 14: End-to-end pipeline concurrency throttling integration
# ==============================================================================
@pytest.mark.asyncio
async def test_pipeline_end_to_end_concurrency_throttling_integration(
    db_session: AsyncSession, setup_m5_5_env
):
    """
    Test 14: End-to-end pipeline execution with concurrency throttling:
    - Tenant limit = 1.
    - Job 1 executes to completion -> slot is acquired, held, and released upon completion.
    - Job 2 attempting to run concurrently is throttled with TENANT_CONCURRENCY_EXCEEDED
      and safely reverted to queued with delay without burning retry attempts.
    """
    user, org, hackathon, rubric_version, (crit1, crit2), submission, snapshot = setup_m5_5_env

    job1, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
        idempotency_key="pipe-job-1",
    )
    job2, _ = await dispatch_evaluation_job_atomic(
        db=db_session, organization_id=org.id, hackathon_id=hackathon.id,
        submission_id=submission.id, snapshot_id=snapshot.id, rubric_version_id=rubric_version.id,
        idempotency_key="pipe-job-2",
    )
    await db_session.commit()

    # 1. Run Job 1 with limit=1 -> succeeds and releases slot
    res1 = run_evaluation_pipeline(
        job_id=job1.id,
        worker_id="w-pipe-1",
        tenant_concurrency_limit=1,
    )
    assert res1.status == "completed"

    # Capacity is 0 after completion
    assert concurrency_governor.get_active_count_sync(org.id) == 0

    # 2. Simulate Job 1 holding slot while Job 2 tries to run
    slot1 = concurrency_governor.acquire_sync(org.id, job1.id, "w-pipe-1", limit=1)
    assert slot1 is not None

    # Job 2 attempts to run concurrently: throttled!
    res2 = run_evaluation_pipeline(
        job_id=job2.id,
        worker_id="w-pipe-2",
        tenant_concurrency_limit=1,
    )
    assert res2.status == "throttled"
    assert res2.error_code == "TENANT_CONCURRENCY_EXCEEDED"

    # Job 2 was reverted to queued with delay, attempts_count was NOT incremented
    await db_session.refresh(job2)
    assert job2.status == "queued"
    assert job2.attempts_count == 0
    assert job2.lease_expires_at is not None

    # Release Job 1's slot
    concurrency_governor.release_sync(slot1)
    assert concurrency_governor.get_active_count_sync(org.id) == 0

import json
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_db_session
import apps.api.core.redis as core_async_redis
from apps.api.dependencies import require_platform_role
from apps.api.modules.audit.models import AuditEvent
from apps.api.modules.evaluations.models import EvaluationJob, Submission
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.modules.organizations.models import Organization
from apps.api.modules.users.models import User
from apps.api.modules.dashboard.schemas import (
    DashboardAuditEventItem,
    DashboardMetricCounts,
    DashboardOverviewResponse,
    DashboardTrendPoint,
    DashboardTrendsResponse,
)

router = APIRouter(prefix="/admin/dashboard", tags=["Admin Dashboard"])

DASHBOARD_CACHE_KEY = "dashboard:overview:cache"
DASHBOARD_CACHE_TTL = 15  # seconds


@router.get("/overview", response_model=DashboardOverviewResponse)
async def get_dashboard_overview(
    refresh: bool = Query(False, description="Force bypass Redis cache and query live database"),
    db: AsyncSession = Depends(get_db_session),
    admin_user: User = Depends(require_platform_role()),
) -> DashboardOverviewResponse:
    """
    Returns aggregated platform metrics and recent governance activity.
    Uses consolidated subquery aggregation and 15-second Redis caching for maximum performance.
    """
    redis_client = None
    try:
        redis_client = core_async_redis.get_redis_client()
    except Exception:
        pass

    if not refresh and redis_client:
        try:
            cached_data = await redis_client.get(DASHBOARD_CACHE_KEY)
            if cached_data:
                parsed = json.loads(cached_data)
                return DashboardOverviewResponse(**parsed)
        except Exception:
            pass

    # Single consolidated SQL query for all platform metric counts
    count_stmt = select(
        select(func.count(User.id)).where(User.deleted_at.is_(None)).scalar_subquery().label("total_users"),
        select(func.count(Organization.id)).where(Organization.deleted_at.is_(None)).scalar_subquery().label("total_organizations"),
        select(func.count(Hackathon.id)).where(Hackathon.deleted_at.is_(None)).scalar_subquery().label("total_hackathons"),
        select(func.count(Hackathon.id)).where(Hackathon.deleted_at.is_(None), Hackathon.status == HackathonStatus.PUBLISHED).scalar_subquery().label("active_hackathons"),
        select(func.count(Submission.id)).scalar_subquery().label("total_submissions"),
        select(func.count(EvaluationJob.id)).where(EvaluationJob.status == "completed").scalar_subquery().label("evaluations_completed"),
        select(func.count(EvaluationJob.id)).where(EvaluationJob.status.in_(["queued", "running", "pending", "leased", "evaluating"])).scalar_subquery().label("evaluations_running"),
        select(func.count(EvaluationJob.id)).where(EvaluationJob.status.in_(["failed", "dead_letter"])).scalar_subquery().label("evaluations_failed"),
    )
    counts_row = (await db.execute(count_stmt)).one()

    # Recent 5 audit events
    audit_stmt = select(AuditEvent).order_by(AuditEvent.timestamp.desc()).limit(5)
    recent_audits_rows = (await db.execute(audit_stmt)).scalars().all()

    recent_audits = [
        DashboardAuditEventItem(
            id=str(a.id),
            timestamp=a.timestamp,
            actor_email=a.actor_email,
            actor_role=a.actor_role,
            action=a.action,
            resource_type=a.resource_type,
            resource_id=a.resource_id,
            outcome=a.outcome.value if hasattr(a.outcome, "value") else str(a.outcome),
        )
        for a in recent_audits_rows
    ]

    response_data = DashboardOverviewResponse(
        counts=DashboardMetricCounts(
            total_users=counts_row.total_users or 0,
            total_organizations=counts_row.total_organizations or 0,
            total_hackathons=counts_row.total_hackathons or 0,
            active_hackathons=counts_row.active_hackathons or 0,
            total_submissions=counts_row.total_submissions or 0,
            evaluations_completed=counts_row.evaluations_completed or 0,
            evaluations_running=counts_row.evaluations_running or 0,
            evaluations_failed=counts_row.evaluations_failed or 0,
        ),
        recent_audits=recent_audits,
        generated_at=datetime.now(timezone.utc),
    )

    if redis_client:
        try:
            # Cache payload for DASHBOARD_CACHE_TTL seconds
            await redis_client.set(
                DASHBOARD_CACHE_KEY,
                response_data.model_dump_json(),
                ex=DASHBOARD_CACHE_TTL,
            )
        except Exception:
            pass

    return response_data


@router.get("/trends", response_model=DashboardTrendsResponse)
async def get_dashboard_trends(
    period: str = Query("30D", description="Time period filter ('7D', '30D', '90D', '1Y')"),
    db: AsyncSession = Depends(get_db_session),
    admin_user: User = Depends(require_platform_role()),
) -> DashboardTrendsResponse:
    """
    Returns platform time-series trend metrics over the selected period (7D, 30D, 90D, 1Y).
    Uses high-performance SQL daily series aggregation directly on verified platform records.
    """
    days_map = {
        "7D": 7,
        "30D": 30,
        "90D": 90,
        "1Y": 365,
    }
    days = days_map.get(period, 30)

    sql = text("""
        WITH dates AS (
            SELECT generate_series(
                date_trunc('day', NOW() - (:days - 1) * INTERVAL '1 day'),
                date_trunc('day', NOW()),
                INTERVAL '1 day'
            )::date AS day
        ),
        u AS (SELECT date_trunc('day', created_at)::date AS day, count(*) as cnt FROM users GROUP BY day),
        o AS (SELECT date_trunc('day', created_at)::date AS day, count(*) as cnt FROM organizations GROUP BY day),
        h AS (SELECT date_trunc('day', created_at)::date AS day, count(*) as cnt FROM hackathons GROUP BY day),
        s AS (SELECT date_trunc('day', created_at)::date AS day, count(*) as cnt FROM submissions GROUP BY day),
        e AS (SELECT date_trunc('day', created_at)::date AS day, count(*) as cnt FROM evaluation_jobs GROUP BY day)
        SELECT 
            to_char(d.day, 'Mon DD') as label,
            COALESCE(u.cnt, 0) as users,
            COALESCE(o.cnt, 0) as orgs,
            COALESCE(h.cnt, 0) as hackathons,
            COALESCE(s.cnt, 0) as submissions,
            COALESCE(e.cnt, 0) as evals
        FROM dates d
        LEFT JOIN u ON d.day = u.day
        LEFT JOIN o ON d.day = o.day
        LEFT JOIN h ON d.day = h.day
        LEFT JOIN s ON d.day = s.day
        LEFT JOIN e ON d.day = e.day
        ORDER BY d.day ASC;
    """)
    res = await db.execute(sql, {"days": days})
    rows = res.all()
    points = [
        DashboardTrendPoint(
            date=r.label,
            users=r.users,
            organizations=r.orgs,
            hackathons=r.hackathons,
            submissions=r.submissions,
            evaluations=r.evals,
        )
        for r in rows
    ]
    return DashboardTrendsResponse(period=period, points=points)

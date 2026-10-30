from datetime import datetime, timezone
import pytest
from httpx import AsyncClient
from apps.api.config import settings
from apps.api.modules.users.models import PlatformRole
from apps.api.tests.test_rbac_authorization import create_authenticated_session


@pytest.mark.asyncio
async def test_admin_dashboard_overview_success(client: AsyncClient, db_session, create_user_helper):
    """Verifies that an authorized administrator receives aggregated platform metrics."""
    admin_user = await create_user_helper(
        email="dash_admin@scorva.io",
        platform_role=PlatformRole.PLATFORM_OWNER,
    )
    token = await create_authenticated_session(db_session, admin_user)

    res = await client.get(
        "/api/v1/admin/dashboard/overview?refresh=true",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res.status_code == 200
    data = res.json()

    assert "counts" in data
    assert "recent_audits" in data
    assert "generated_at" in data

    counts = data["counts"]
    assert counts["total_users"] >= 1
    assert "total_organizations" in counts
    assert "total_hackathons" in counts
    assert "active_hackathons" in counts
    assert "total_submissions" in counts
    assert "evaluations_completed" in counts
    assert "evaluations_running" in counts
    assert "evaluations_failed" in counts
    assert isinstance(data["recent_audits"], list)


@pytest.mark.asyncio
async def test_admin_dashboard_overview_caching(client: AsyncClient, db_session, create_user_helper):
    """Verifies that subsequent calls hit the cached response quickly."""
    admin_user = await create_user_helper(
        email="cache_admin@scorva.io",
        platform_role=PlatformRole.SECURITY_ADMIN,
    )
    token = await create_authenticated_session(db_session, admin_user)

    # Initial query (caches result)
    res1 = await client.get(
        "/api/v1/admin/dashboard/overview",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res1.status_code == 200

    # Second query immediately following (should read from Redis cache)
    res2 = await client.get(
        "/api/v1/admin/dashboard/overview",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res2.status_code == 200
    assert res2.json()["counts"] == res1.json()["counts"]


@pytest.mark.asyncio
async def test_admin_dashboard_overview_authorization(client: AsyncClient, db_session, create_user_helper):
    """Verifies unauthenticated and non-admin access controls."""
    # 1. Unauthenticated request
    res_unauth = await client.get("/api/v1/admin/dashboard/overview")
    assert res_unauth.status_code == 401

    # 2. Participant (non-admin) request
    part_user = await create_user_helper(
        email="dash_part@scorva.io",
        platform_role=None,
    )
    part_token = await create_authenticated_session(db_session, part_user)
    res_forbidden = await client.get(
        "/api/v1/admin/dashboard/overview",
        cookies={settings.SESSION_COOKIE_NAME: part_token},
    )
    assert res_forbidden.status_code == 403


@pytest.mark.asyncio
async def test_admin_dashboard_trends(client: AsyncClient, db_session, create_user_helper):
    """Verifies that an authorized administrator receives platform time-series trends."""
    admin_user = await create_user_helper(
        email="trends_admin@scorva.io",
        platform_role=PlatformRole.PLATFORM_OWNER,
    )
    token = await create_authenticated_session(db_session, admin_user)

    res = await client.get(
        "/api/v1/admin/dashboard/trends?period=30D",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["period"] == "30D"
    assert "points" in data
    assert len(data["points"]) == 30
    point = data["points"][-1]
    assert "date" in point
    assert "users" in point
    assert "organizations" in point
    assert "hackathons" in point
    assert "submissions" in point
    assert "evaluations" in point

import math
import uuid
import pytest
from httpx import AsyncClient
from apps.api.config import settings
from apps.api.modules.users.models import PlatformRole, User
from apps.api.tests.test_rbac_authorization import create_authenticated_session


@pytest.mark.asyncio
async def test_admin_users_pagination_defaults(client: AsyncClient, db_session, create_user_helper):
    """Verifies that GET /api/v1/admin/users returns paginated response with defaults."""
    admin_user = await create_user_helper(
        email="pag_admin@scorva.io",
        platform_role=PlatformRole.SECURITY_ADMIN,
    )
    token = await create_authenticated_session(db_session, admin_user)

    res = await client.get(
        "/api/v1/admin/users",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "limit" in data
    assert "total_pages" in data

    assert data["page"] == 1
    assert data["limit"] == 15
    assert data["total"] >= 1
    assert len(data["items"]) <= 15
    assert data["total_pages"] == math.ceil(data["total"] / 15)


@pytest.mark.asyncio
async def test_admin_users_pagination_custom_limit_and_page(client: AsyncClient, db_session, create_user_helper):
    """Verifies that custom page and limit navigate the user directory properly."""
    admin_user = await create_user_helper(
        email="pag_nav_admin@scorva.io",
        platform_role=PlatformRole.PLATFORM_OWNER,
    )
    token = await create_authenticated_session(db_session, admin_user)

    # Page 1 with limit 5
    res1 = await client.get(
        "/api/v1/admin/users?page=1&limit=5",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res1.status_code == 200
    data1 = res1.json()
    assert len(data1["items"]) == 5
    assert data1["page"] == 1
    assert data1["limit"] == 5

    # Page 2 with limit 5
    res2 = await client.get(
        "/api/v1/admin/users?page=2&limit=5",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert len(data2["items"]) == 5
    assert data2["page"] == 2

    # Verify disjoint IDs across pages
    ids_page1 = {u["id"] for u in data1["items"]}
    ids_page2 = {u["id"] for u in data2["items"]}
    assert ids_page1.isdisjoint(ids_page2)


@pytest.mark.asyncio
async def test_admin_users_search_filter(client: AsyncClient, db_session, create_user_helper):
    """Verifies search filtering by name or email."""
    suffix = uuid.uuid4().hex[:8]
    unique_email = f"searchable_{suffix}@scorva.io"
    unique_name = f"UniqueName_{suffix}"

    target_user = await create_user_helper(
        email=unique_email,
        full_name=unique_name,
        platform_role=PlatformRole.SUPPORT_ADMIN,
    )
    admin_user = await create_user_helper(
        email=f"search_tester_{suffix}@scorva.io",
        platform_role=PlatformRole.SECURITY_ADMIN,
    )
    token = await create_authenticated_session(db_session, admin_user)

    # Search by email substring
    res = await client.get(
        f"/api/v1/admin/users?search={suffix}",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    found_emails = [u["email"] for u in data["items"]]
    assert unique_email in found_emails

    # Search with no match
    res_none = await client.get(
        "/api/v1/admin/users?search=nonexistent_xyz_999999",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res_none.status_code == 200
    assert res_none.json()["total"] == 0
    assert len(res_none.json()["items"]) == 0


@pytest.mark.asyncio
async def test_admin_users_role_and_status_filter(client: AsyncClient, db_session, create_user_helper):
    """Verifies role and status filtering."""
    suffix = uuid.uuid4().hex[:8]
    sec_user = await create_user_helper(
        email=f"filter_sec_{suffix}@scorva.io",
        platform_role=PlatformRole.SECURITY_ADMIN,
        is_active=True,
    )
    suspended_user = await create_user_helper(
        email=f"filter_susp_{suffix}@scorva.io",
        platform_role=None,
        is_active=False,
    )
    token = await create_authenticated_session(db_session, sec_user)

    # Filter role: security_admin
    res_role = await client.get(
        f"/api/v1/admin/users?role=security_admin&search={suffix}",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res_role.status_code == 200
    data_role = res_role.json()
    assert data_role["total"] == 1
    assert data_role["items"][0]["email"] == sec_user.email

    # Filter status: suspended
    res_status = await client.get(
        f"/api/v1/admin/users?status=suspended&search={suffix}",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res_status.status_code == 200
    data_status = res_status.json()
    assert data_status["total"] == 1
    assert data_status["items"][0]["email"] == suspended_user.email
    assert data_status["items"][0]["is_active"] is False


@pytest.mark.asyncio
async def test_admin_users_unauthorized_blocked(client: AsyncClient, db_session, create_user_helper):
    """Verifies 401 unauthenticated and 403 non-admin access controls."""
    # 1. Unauthenticated
    res_unauth = await client.get("/api/v1/admin/users")
    assert res_unauth.status_code == 401

    # 2. Regular user (no platform role)
    reg_user = await create_user_helper(
        email="plain_viewer@scorva.io",
        platform_role=None,
    )
    reg_token = await create_authenticated_session(db_session, reg_user)
    res_forbidden = await client.get(
        "/api/v1/admin/users",
        cookies={settings.SESSION_COOKIE_NAME: reg_token},
    )
    assert res_forbidden.status_code == 403

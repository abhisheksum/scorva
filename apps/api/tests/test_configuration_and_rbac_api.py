import uuid
import pytest
from httpx import AsyncClient
from apps.api.config import settings
from apps.api.modules.rbac.models import PLATFORM_SCOPE_ID
from apps.api.modules.users.models import PlatformRole, User


@pytest.mark.asyncio
async def test_configuration_api_lifecycle(client: AsyncClient, create_user_helper, create_session_helper):
    """E2E verification of configuration listing, updating, and rolling back via HTTP endpoints."""
    admin = await create_user_helper("config_api_admin@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    token = await create_session_helper(admin)
    headers = {"Authorization": f"Bearer {token}", "Origin": "http://localhost:3000"}

    # 1. GET /api/v1/admin/configuration
    resp = await client.get("/api/v1/admin/configuration", headers=headers)
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 16
    keys = {item["key"] for item in items}
    assert "judge.min_override_rationale_length" in keys
    assert "extract.allow_symlinks" in keys

    # Find initial version for judge.min_override_rationale_length
    target_item = next(i for i in items if i["key"] == "judge.min_override_rationale_length")
    initial_ver = target_item["version"]

    # 2. PUT /api/v1/admin/configuration/{key} (successful update)
    update_resp = await client.put(
        "/api/v1/admin/configuration/judge.min_override_rationale_length",
        headers=headers,
        json={"value": "35", "expected_version": initial_ver, "change_reason": "API test update"},
    )
    assert update_resp.status_code == 200
    updated_data = update_resp.json()
    assert updated_data["current_value"] == "35"
    assert updated_data["version"] == initial_ver + 1

    # 3. PUT with optimistic concurrency conflict (stale expected_version)
    conflict_resp = await client.put(
        "/api/v1/admin/configuration/judge.min_override_rationale_length",
        headers=headers,
        json={"value": "40", "expected_version": initial_ver, "change_reason": "Stale update"},
    )
    assert conflict_resp.status_code == 409
    assert conflict_resp.json()["code"] == "OPTIMISTIC_CONCURRENCY_CONFLICT"

    # 4. PUT attempting to alter Tier 5 immutable invariant (extract.allow_symlinks)
    symlink_item = next(i for i in items if i["key"] == "extract.allow_symlinks")
    immut_resp = await client.put(
        "/api/v1/admin/configuration/extract.allow_symlinks",
        headers=headers,
        json={"value": "true", "expected_version": symlink_item["version"]},
    )
    assert immut_resp.status_code == 403
    assert immut_resp.json()["code"] == "SECURITY_INVARIANT_IMMUTABLE"

    # 5. POST /api/v1/admin/configuration/{key}/rollback
    rollback_resp = await client.post(
        "/api/v1/admin/configuration/judge.min_override_rationale_length/rollback",
        headers=headers,
        json={"target_version": initial_ver, "expected_version": updated_data["version"]},
    )
    assert rollback_resp.status_code == 200
    rolled_data = rollback_resp.json()
    assert rolled_data["version"] == updated_data["version"] + 1

    # 6. GET /api/v1/admin/configuration/effective
    eff_resp = await client.get("/api/v1/admin/configuration/effective", headers=headers)
    assert eff_resp.status_code == 200
    eff_data = eff_resp.json()
    assert "extract_max_compressed_bytes" in eff_data
    assert eff_data["extract_allow_symlinks"] is False


@pytest.mark.asyncio
async def test_roles_and_permissions_api_lifecycle(client: AsyncClient, create_user_helper, create_session_helper):
    """E2E verification of permissions listing, role creation, permission modification, and user assignment."""
    owner = await create_user_helper("role_api_owner@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    token = await create_session_helper(owner)
    headers = {"Authorization": f"Bearer {token}", "Origin": "http://localhost:3000"}

    # 1. GET /api/v1/admin/permissions
    perm_resp = await client.get("/api/v1/admin/permissions", headers=headers)
    assert perm_resp.status_code == 200
    perms = perm_resp.json()
    assert len(perms) >= 50
    perm_ids = {p["id"] for p in perms}
    assert "platform.settings.read" in perm_ids
    assert "platform.roles.manage" in perm_ids

    # 2. GET /api/v1/admin/roles
    roles_resp = await client.get("/api/v1/admin/roles", headers=headers)
    assert roles_resp.status_code == 200
    roles = roles_resp.json()
    assert len(roles) >= 9
    role_names = {r["name"] for r in roles}
    assert "platform_owner" in role_names
    assert "platform_ops_admin" in role_names

    # 3. POST /api/v1/admin/roles (create dynamic role)
    custom_role_name = f"custom_reviewer_{uuid.uuid4().hex[:6]}"
    create_resp = await client.post(
        "/api/v1/admin/roles",
        headers=headers,
        json={
            "name": custom_role_name,
            "display_name": "Custom Reviewer Role",
            "scope_type": "platform",
            "permissions": ["evaluation.view", "judge.review"],
        },
    )
    assert create_resp.status_code == 201
    created_role = create_resp.json()
    role_id = created_role["id"]
    assert created_role["name"] == custom_role_name
    assert "judge.review" in created_role["permissions"]

    # 4. PUT /api/v1/admin/roles/{role_id}/permissions
    put_resp = await client.put(
        f"/api/v1/admin/roles/{role_id}/permissions",
        headers=headers,
        json={"permissions": ["evaluation.view", "judge.review", "rubric.view"]},
    )
    assert put_resp.status_code == 200
    updated_role = put_resp.json()
    assert "rubric.view" in updated_role["permissions"]

    # 5. POST /api/v1/admin/users/{user_id}/roles
    target_user = await create_user_helper("target_user_api@scorva.io", platform_role=PlatformRole.SUPPORT_ADMIN)
    assign_resp = await client.post(
        f"/api/v1/admin/users/{target_user.id}/roles",
        headers=headers,
        json={"role_id": role_id, "scope_type": "platform"},
    )
    assert assign_resp.status_code == 201
    assignment = assign_resp.json()
    assignment_id = assignment["id"]
    assert assignment["user_id"] == str(target_user.id)
    assert assignment["role_id"] == role_id

    # 6. DELETE /api/v1/admin/users/{user_id}/roles/{assignment_id}
    del_resp = await client.delete(
        f"/api/v1/admin/users/{target_user.id}/roles/{assignment_id}",
        headers=headers,
    )
    assert del_resp.status_code == 204

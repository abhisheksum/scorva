import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from apps.api.config import settings
from apps.api.modules.audit.models import AuditEvent
from apps.api.modules.organizations.models import (
    MembershipStatus,
    OrgRole,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
)
from apps.api.modules.users.models import PlatformRole, User

ORIGIN_HEADER = {"Origin": "http://testserver"}


# =====================================================================
# Group 2: Organization Management Unit & Integration Tests (ORG-01..08)
# =====================================================================

@pytest.mark.asyncio
async def test_org_01_platform_admin_creates_organization(
    client: AsyncClient, db_session, create_user_helper, create_session_helper
):
    """ORG-01: Platform ops admin creates organization; owner assigned ORG_OWNER; audit event recorded."""
    suffix = uuid.uuid4().hex[:6]
    admin = await create_user_helper(
        email=f"ops_admin_{suffix}@scorva.io",
        platform_role=PlatformRole.PLATFORM_OPS_ADMIN,
    )
    admin_token = await create_session_helper(admin)

    owner = await create_user_helper(
        email=f"owner_{suffix}@scorva.io",
        platform_role=None,
    )

    slug = f"alpha-corp-{suffix}"
    res = await client.post(
        "/api/v1/admin/organizations",
        json={
            "name": "Alpha Corporation",
            "slug": slug,
            "owner_email": owner.email,
            "settings": {"max_hackathons": 5, "timezone": "America/New_York"},
        },
        cookies={settings.SESSION_COOKIE_NAME: admin_token},
        headers=ORIGIN_HEADER,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Alpha Corporation"
    assert data["slug"] == slug
    assert data["owner_id"] == str(owner.id)
    assert data["status"] == "active"
    assert data["member_count"] == 1

    org_id = uuid.UUID(data["id"])

    # Verify membership in DB
    mem_stmt = select(OrganizationMembership).where(
        OrganizationMembership.organization_id == org_id,
        OrganizationMembership.user_id == owner.id,
    )
    mem = (await db_session.execute(mem_stmt)).scalar_one_or_none()
    assert mem is not None
    assert mem.role == OrgRole.ORG_OWNER
    assert mem.status == MembershipStatus.ACTIVE

    # Verify audit event
    audit_stmt = select(AuditEvent).where(
        AuditEvent.organization_id == org_id,
        AuditEvent.action == "organization_created",
    )
    audit = (await db_session.execute(audit_stmt)).scalar_one_or_none()
    assert audit is not None
    assert audit.actor_user_id == admin.id
    assert audit.actor_role == "platform_ops_admin"
    assert audit.organization_id == org_id


@pytest.mark.asyncio
async def test_org_02_non_admin_blocked_from_creating_organization(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """ORG-02: Non-admin user blocked from creating org via admin API with 403 FORBIDDEN_NOT_ADMIN."""
    suffix = uuid.uuid4().hex[:6]
    user = await create_user_helper(
        email=f"regular_user_{suffix}@scorva.io",
        platform_role=None,
    )
    token = await create_session_helper(user)

    res = await client.post(
        "/api/v1/admin/organizations",
        json={
            "name": "Unauthorized Org",
            "slug": f"unauthorized-{suffix}",
            "owner_email": user.email,
        },
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN_NOT_ADMIN"


@pytest.mark.asyncio
async def test_org_03_reject_duplicate_organization_slug(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """ORG-03: Reject duplicate organization slug with 409 Conflict (ORGANIZATION_SLUG_TAKEN)."""
    suffix = uuid.uuid4().hex[:6]
    admin = await create_user_helper(
        email=f"admin_{suffix}@scorva.io",
        platform_role=PlatformRole.PLATFORM_OWNER,
    )
    token = await create_session_helper(admin)

    owner = await create_user_helper(
        email=f"owner_{suffix}@scorva.io",
        platform_role=None,
    )

    slug = f"unique-slug-{suffix}"
    res1 = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "First Org", "slug": slug, "owner_email": owner.email},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    assert res1.status_code == 201

    # Attempt duplicate slug
    res2 = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Second Org", "slug": slug, "owner_email": owner.email},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    assert res2.status_code == 409
    assert res2.json()["code"] == "ORGANIZATION_SLUG_TAKEN"


@pytest.mark.asyncio
async def test_org_04_retrieve_organization_details(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """ORG-04: Retrieve organization details via admin API."""
    suffix = uuid.uuid4().hex[:6]
    admin = await create_user_helper(
        email=f"admin_{suffix}@scorva.io",
        platform_role=PlatformRole.PLATFORM_OPS_ADMIN,
    )
    token = await create_session_helper(admin)

    owner = await create_user_helper(
        email=f"owner_{suffix}@scorva.io",
        platform_role=None,
    )

    slug = f"details-slug-{suffix}"
    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Details Org", "slug": slug, "owner_email": owner.email},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    assert create_res.status_code == 201
    org_id = create_res.json()["id"]

    res = await client.get(
        f"/api/v1/admin/organizations/{org_id}",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == org_id
    assert data["name"] == "Details Org"
    assert data["owner"]["email"] == owner.email
    assert data["member_count"] == 1


@pytest.mark.asyncio
async def test_org_05_suspend_organization_workflow(
    client: AsyncClient, db_session, create_user_helper, create_session_helper
):
    """ORG-05: Suspend organization workflow via platform admin with mandatory audit logging."""
    suffix = uuid.uuid4().hex[:6]
    admin = await create_user_helper(
        email=f"admin_{suffix}@scorva.io",
        platform_role=PlatformRole.PLATFORM_OPS_ADMIN,
    )
    token = await create_session_helper(admin)

    owner = await create_user_helper(
        email=f"owner_{suffix}@scorva.io",
        platform_role=None,
    )

    slug = f"status-slug-{suffix}"
    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Suspend Org", "slug": slug, "owner_email": owner.email},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    # Suspend organization
    suspend_res = await client.post(
        f"/api/v1/admin/organizations/{org_id}/status",
        json={"is_active": False, "reason": "Billing delinquency"},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    assert suspend_res.status_code == 200
    assert suspend_res.json()["status"] == "suspended"

    # Verify audit event for suspension
    audit_stmt = select(AuditEvent).where(
        AuditEvent.organization_id == uuid.UUID(org_id),
        AuditEvent.action == "organization_status_changed",
    )
    audits = (await db_session.execute(audit_stmt)).scalars().all()
    assert len(audits) >= 1
    assert any(a.reason == "Billing delinquency" for a in audits)


@pytest.mark.asyncio
async def test_org_06_reactivate_suspended_organization(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """ORG-06: Reactivate suspended organization via platform admin."""
    suffix = uuid.uuid4().hex[:6]
    admin = await create_user_helper(
        email=f"admin_{suffix}@scorva.io",
        platform_role=PlatformRole.PLATFORM_OPS_ADMIN,
    )
    token = await create_session_helper(admin)

    owner = await create_user_helper(
        email=f"owner_{suffix}@scorva.io",
        platform_role=None,
    )

    slug = f"reactivate-slug-{suffix}"
    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Reactivate Org", "slug": slug, "owner_email": owner.email},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    # Suspend
    await client.post(
        f"/api/v1/admin/organizations/{org_id}/status",
        json={"is_active": False, "reason": "Administrative hold"},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )

    # Reactivate
    reactivate_res = await client.post(
        f"/api/v1/admin/organizations/{org_id}/status",
        json={"is_active": True},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    assert reactivate_res.status_code == 200
    assert reactivate_res.json()["status"] == "active"


@pytest.mark.asyncio
async def test_org_07_transfer_organization_ownership(
    client: AsyncClient, db_session, create_user_helper, create_session_helper
):
    """
    ORG-07: Transfer ownership targeting active member Bob using Platform Owner.
    Bob becomes owner and ORG_OWNER; Alice demoted to ORG_ADMIN.
    """
    suffix = uuid.uuid4().hex[:6]
    platform_owner = await create_user_helper(
        email=f"platform_owner_{suffix}@scorva.io",
        platform_role=PlatformRole.PLATFORM_OWNER,
    )
    token = await create_session_helper(platform_owner)

    alice = await create_user_helper(
        email=f"alice_{suffix}@scorva.io",
        platform_role=None,
    )
    bob = await create_user_helper(
        email=f"bob_{suffix}@scorva.io",
        platform_role=None,
    )

    slug = f"transfer-slug-{suffix}"
    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Transfer Org", "slug": slug, "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    # Add Bob as a member first
    add_bob_res = await client.post(
        f"/api/v1/admin/organizations/{org_id}/members",
        json={"user_id": str(bob.id), "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    assert add_bob_res.status_code == 201

    # Transfer ownership to Bob
    transfer_res = await client.post(
        f"/api/v1/admin/organizations/{org_id}/transfer-ownership",
        json={"new_owner_user_id": str(bob.id), "reason": "Leadership succession"},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    assert transfer_res.status_code == 200
    data = transfer_res.json()
    assert data["owner_id"] == str(bob.id)

    # Verify memberships in DB
    alice_mem = (await db_session.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == uuid.UUID(org_id),
            OrganizationMembership.user_id == alice.id,
        )
    )).scalar_one()
    bob_mem = (await db_session.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == uuid.UUID(org_id),
            OrganizationMembership.user_id == bob.id,
        )
    )).scalar_one()

    assert bob_mem.role == OrgRole.ORG_OWNER
    assert alice_mem.role == OrgRole.ORG_ADMIN


@pytest.mark.asyncio
async def test_org_08_transfer_ownership_to_non_member_blocked(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """ORG-08: Transfer ownership targeting unaffiliated Dave blocked with 400 TARGET_USER_NOT_MEMBER."""
    suffix = uuid.uuid4().hex[:6]
    platform_owner = await create_user_helper(
        email=f"admin_{suffix}@scorva.io",
        platform_role=PlatformRole.PLATFORM_OWNER,
    )
    token = await create_session_helper(platform_owner)

    alice = await create_user_helper(
        email=f"alice_{suffix}@scorva.io",
        platform_role=None,
    )
    dave = await create_user_helper(
        email=f"dave_{suffix}@scorva.io",
        platform_role=None,
    )

    slug = f"transfer-blocked-{suffix}"
    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Blocked Transfer Org", "slug": slug, "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    res = await client.post(
        f"/api/v1/admin/organizations/{org_id}/transfer-ownership",
        json={"new_owner_user_id": str(dave.id)},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    assert res.status_code == 400
    assert res.json()["code"] == "TARGET_USER_NOT_MEMBER"


# =====================================================================
# Group 3: Organization Membership & Role Matrix Tests (MEM-01..08)
# =====================================================================

@pytest.mark.asyncio
async def test_mem_01_org_admin_adds_member(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """MEM-01: Org Admin adds member Dave with role 'organizer' (201 Created)."""
    suffix = uuid.uuid4().hex[:6]
    p_admin = await create_user_helper(email=f"p_admin_{suffix}@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    p_token = await create_session_helper(p_admin)

    alice = await create_user_helper(email=f"alice_{suffix}@scorva.io", platform_role=None)
    bob = await create_user_helper(email=f"bob_{suffix}@scorva.io", platform_role=None)
    dave = await create_user_helper(email=f"dave_{suffix}@scorva.io", platform_role=None)

    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Mem01 Org", "slug": f"mem01-{suffix}", "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: p_token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    alice_token = await create_session_helper(alice)
    await client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": bob.email, "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )
    await client.patch(
        f"/api/v1/organizations/{org_id}/members/{bob.id}",
        json={"role": "org_admin"},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )

    # Bob (ORG_ADMIN) adds Dave with role organizer
    bob_token = await create_session_helper(bob)
    add_dave = await client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": dave.email, "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: bob_token},
        headers=ORIGIN_HEADER,
    )
    assert add_dave.status_code == 201
    assert add_dave.json()["email"] == dave.email
    assert add_dave.json()["role"] == "organizer"


@pytest.mark.asyncio
async def test_mem_02_organizer_forbidden_from_adding_members(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """MEM-02: Organizer forbidden from adding members (403 FORBIDDEN_INSUFFICIENT_ORG_ROLE)."""
    suffix = uuid.uuid4().hex[:6]
    p_admin = await create_user_helper(email=f"p_admin_{suffix}@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    p_token = await create_session_helper(p_admin)

    alice = await create_user_helper(email=f"alice_{suffix}@scorva.io", platform_role=None)
    dave = await create_user_helper(email=f"dave_{suffix}@scorva.io", platform_role=None)
    eve = await create_user_helper(email=f"eve_{suffix}@scorva.io", platform_role=None)

    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Mem02 Org", "slug": f"mem02-{suffix}", "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: p_token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    alice_token = await create_session_helper(alice)
    await client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": dave.email, "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )

    # Dave (ORGANIZER) forbidden from adding Eve
    dave_token = await create_session_helper(dave)
    forbidden_add = await client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": eve.email, "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: dave_token},
        headers=ORIGIN_HEADER,
    )
    assert forbidden_add.status_code == 403
    assert forbidden_add.json()["code"] == "FORBIDDEN_INSUFFICIENT_ORG_ROLE"


@pytest.mark.asyncio
async def test_mem_03_duplicate_membership_rejected(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """MEM-03: Duplicate membership rejected (409 MEMBERSHIP_ALREADY_EXISTS)."""
    suffix = uuid.uuid4().hex[:6]
    p_admin = await create_user_helper(email=f"p_admin_{suffix}@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    p_token = await create_session_helper(p_admin)

    alice = await create_user_helper(email=f"alice_{suffix}@scorva.io", platform_role=None)
    dave = await create_user_helper(email=f"dave_{suffix}@scorva.io", platform_role=None)

    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Mem03 Org", "slug": f"mem03-{suffix}", "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: p_token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    alice_token = await create_session_helper(alice)
    add_first = await client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": dave.email, "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )
    assert add_first.status_code == 201

    duplicate_res = await client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": dave.email, "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )
    assert duplicate_res.status_code == 409
    assert duplicate_res.json()["code"] == "MEMBERSHIP_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_mem_04_org_owner_promotes_member_to_admin(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """MEM-04: Org Owner promotes member to org_admin (200 OK)."""
    suffix = uuid.uuid4().hex[:6]
    platform_admin = await create_user_helper(email=f"p_admin_{suffix}@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    p_token = await create_session_helper(platform_admin)

    alice = await create_user_helper(email=f"alice_{suffix}@scorva.io", platform_role=None)
    bob = await create_user_helper(email=f"bob_{suffix}@scorva.io", platform_role=None)

    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Mem04 Org", "slug": f"mem04-{suffix}", "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: p_token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    alice_token = await create_session_helper(alice)
    await client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": bob.email, "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )

    # Alice (ORG_OWNER) promotes Bob to org_admin
    promote_res = await client.patch(
        f"/api/v1/organizations/{org_id}/members/{bob.id}",
        json={"role": "org_admin"},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )
    assert promote_res.status_code == 200
    assert promote_res.json()["role"] == "org_admin"


@pytest.mark.asyncio
async def test_mem_05_org_admin_cannot_promote_to_owner(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """MEM-05: Org Admin cannot promote to org_owner (403 FORBIDDEN_INSUFFICIENT_ORG_ROLE)."""
    suffix = uuid.uuid4().hex[:6]
    platform_admin = await create_user_helper(email=f"p_admin_{suffix}@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    p_token = await create_session_helper(platform_admin)

    alice = await create_user_helper(email=f"alice_{suffix}@scorva.io", platform_role=None)
    bob = await create_user_helper(email=f"bob_{suffix}@scorva.io", platform_role=None)
    charlie = await create_user_helper(email=f"charlie_{suffix}@scorva.io", platform_role=None)

    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Mem05 Org", "slug": f"mem05-{suffix}", "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: p_token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    alice_token = await create_session_helper(alice)
    await client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": bob.email, "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )
    await client.patch(
        f"/api/v1/organizations/{org_id}/members/{bob.id}",
        json={"role": "org_admin"},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )
    await client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": charlie.email, "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )

    # Bob (ORG_ADMIN) attempts to promote Charlie to org_owner -> 403 FORBIDDEN_INSUFFICIENT_ORG_ROLE
    bob_token = await create_session_helper(bob)
    admin_promote = await client.patch(
        f"/api/v1/organizations/{org_id}/members/{charlie.id}",
        json={"role": "org_owner"},
        cookies={settings.SESSION_COOKIE_NAME: bob_token},
        headers=ORIGIN_HEADER,
    )
    assert admin_promote.status_code == 403
    assert admin_promote.json()["code"] == "FORBIDDEN_INSUFFICIENT_ORG_ROLE"


@pytest.mark.asyncio
async def test_mem_06_org_admin_removes_member(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """MEM-06: Org Admin removes an organizer (200 OK)."""
    suffix = uuid.uuid4().hex[:6]
    p_admin = await create_user_helper(email=f"p_admin_{suffix}@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    p_token = await create_session_helper(p_admin)

    alice = await create_user_helper(email=f"alice_{suffix}@scorva.io", platform_role=None)
    bob = await create_user_helper(email=f"bob_{suffix}@scorva.io", platform_role=None)
    dave = await create_user_helper(email=f"dave_{suffix}@scorva.io", platform_role=None)

    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Mem06 Org", "slug": f"mem06-{suffix}", "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: p_token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    alice_token = await create_session_helper(alice)
    await client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": bob.email, "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )
    await client.patch(
        f"/api/v1/organizations/{org_id}/members/{bob.id}",
        json={"role": "org_admin"},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )
    await client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": dave.email, "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )

    # Bob (ORG_ADMIN) removes Dave (ORGANIZER) -> 200 OK
    bob_token = await create_session_helper(bob)
    remove_dave = await client.delete(
        f"/api/v1/organizations/{org_id}/members/{dave.id}",
        cookies={settings.SESSION_COOKIE_NAME: bob_token},
        headers=ORIGIN_HEADER,
    )
    assert remove_dave.status_code == 200
    assert remove_dave.json()["status"] == "success"


@pytest.mark.asyncio
async def test_mem_07_org_admin_cannot_remove_org_owner(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """MEM-07: Org Admin cannot remove Org Owner (403 CANNOT_REMOVE_OWNER)."""
    suffix = uuid.uuid4().hex[:6]
    p_admin = await create_user_helper(email=f"p_admin_{suffix}@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    p_token = await create_session_helper(p_admin)

    alice = await create_user_helper(email=f"alice_{suffix}@scorva.io", platform_role=None)
    bob = await create_user_helper(email=f"bob_{suffix}@scorva.io", platform_role=None)

    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Mem07 Org", "slug": f"mem07-{suffix}", "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: p_token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    alice_token = await create_session_helper(alice)
    await client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": bob.email, "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )
    await client.patch(
        f"/api/v1/organizations/{org_id}/members/{bob.id}",
        json={"role": "org_admin"},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )

    # Bob (ORG_ADMIN) attempts to remove Alice (ORG_OWNER) -> 403 CANNOT_REMOVE_OWNER
    bob_token = await create_session_helper(bob)
    remove_owner = await client.delete(
        f"/api/v1/organizations/{org_id}/members/{alice.id}",
        cookies={settings.SESSION_COOKIE_NAME: bob_token},
        headers=ORIGIN_HEADER,
    )
    assert remove_owner.status_code == 403
    assert remove_owner.json()["code"] == "CANNOT_REMOVE_OWNER"


@pytest.mark.asyncio
async def test_mem_08_cannot_remove_last_org_owner(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """MEM-08: Cannot remove last Org Owner (400 CANNOT_REMOVE_LAST_OWNER)."""
    suffix = uuid.uuid4().hex[:6]
    p_admin = await create_user_helper(email=f"p_admin_{suffix}@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    p_token = await create_session_helper(p_admin)

    alice = await create_user_helper(email=f"alice_{suffix}@scorva.io", platform_role=None)

    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Mem08 Org", "slug": f"mem08-{suffix}", "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: p_token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    # Alice (ORG_OWNER) attempts to remove herself -> 400 CANNOT_REMOVE_LAST_OWNER
    alice_token = await create_session_helper(alice)
    remove_self = await client.delete(
        f"/api/v1/organizations/{org_id}/members/{alice.id}",
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )
    assert remove_self.status_code == 400
    assert remove_self.json()["code"] == "CANNOT_REMOVE_LAST_OWNER"


# =====================================================================
# Additional Directory & Tenant Profile Tests
# =====================================================================

@pytest.mark.asyncio
async def test_admin_organizations_directory_pagination_and_search(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """Tests directory search, filtering, and pagination for platform admin."""
    suffix = uuid.uuid4().hex[:6]
    admin = await create_user_helper(
        email=f"admin_dir_{suffix}@scorva.io",
        platform_role=PlatformRole.PLATFORM_OWNER,
    )
    token = await create_session_helper(admin)

    owner = await create_user_helper(
        email=f"dir_owner_{suffix}@scorva.io",
        platform_role=None,
    )

    slug1 = f"acme-widgets-{suffix}"
    slug2 = f"zenith-labs-{suffix}"

    await client.post(
        "/api/v1/admin/organizations",
        json={"name": f"Acme Widgets Inc {suffix}", "slug": slug1, "owner_email": owner.email},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    await client.post(
        "/api/v1/admin/organizations",
        json={"name": f"Zenith Laboratories {suffix}", "slug": slug2, "owner_email": owner.email},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )

    # Search for Acme
    res_search = await client.get(
        f"/api/v1/admin/organizations?search=Acme+Widgets+Inc+{suffix}",
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    assert res_search.status_code == 200
    search_data = res_search.json()
    assert search_data["total"] >= 1
    assert any(suffix in item["slug"] for item in search_data["items"])


@pytest.mark.asyncio
async def test_tenant_profile_read_and_update(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """Tests tenant plane profile retrieval and update with role checking."""
    suffix = uuid.uuid4().hex[:6]
    p_admin = await create_user_helper(email=f"p_admin_{suffix}@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    p_token = await create_session_helper(p_admin)

    alice = await create_user_helper(email=f"alice_{suffix}@scorva.io", platform_role=None)
    bob = await create_user_helper(email=f"bob_{suffix}@scorva.io", platform_role=None)

    slug = f"profile-test-{suffix}"
    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Initial Org Name", "slug": slug, "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: p_token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    alice_token = await create_session_helper(alice)
    await client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": bob.email, "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )

    # Bob (Organizer) can read profile
    bob_token = await create_session_helper(bob)
    read_res = await client.get(
        f"/api/v1/organizations/{org_id}",
        cookies={settings.SESSION_COOKIE_NAME: bob_token},
    )
    assert read_res.status_code == 200
    assert read_res.json()["name"] == "Initial Org Name"
    assert read_res.json()["current_user_role"] == "organizer"

    # Bob (Organizer) cannot update profile -> 403
    patch_fail = await client.patch(
        f"/api/v1/organizations/{org_id}",
        json={"name": "Hacked Org Name"},
        cookies={settings.SESSION_COOKIE_NAME: bob_token},
        headers=ORIGIN_HEADER,
    )
    assert patch_fail.status_code == 403
    assert patch_fail.json()["code"] == "FORBIDDEN_INSUFFICIENT_ORG_ROLE"

    # Alice (Owner) can update profile -> 200
    patch_ok = await client.patch(
        f"/api/v1/organizations/{org_id}",
        json={"name": "Updated Org Name", "settings": {"timezone": "Europe/London"}},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )
    assert patch_ok.status_code == 200
    assert patch_ok.json()["name"] == "Updated Org Name"
    assert patch_ok.json()["settings"]["timezone"] == "Europe/London"


@pytest.mark.asyncio
async def test_organization_settings_rejects_raw_credentials(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """SEC-M3-05 Regression: Organization settings reject raw credentials and tokens across admin and tenant routes."""
    suffix = uuid.uuid4().hex[:8]
    alice = await create_user_helper(email=f"alice_{suffix}@scorva.io", platform_role=None)
    alice_token = await create_session_helper(alice)

    # Create Org
    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Sec Org", "slug": f"sec-org-{suffix}", "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )
    # If alice is not platform admin, use superadmin to create org
    admin = await create_user_helper(email=f"admin_{suffix}@scorva.io", platform_role=PlatformRole.PLATFORM_OWNER)
    admin_token = await create_session_helper(admin)
    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Sec Org", "slug": f"sec-org-{suffix}", "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: admin_token},
        headers=ORIGIN_HEADER,
    )
    assert create_res.status_code == 201
    org_id = create_res.json()["id"]

    # 1. Tenant route: Attempt to save GitHub token key
    res_pat_key = await client.patch(
        f"/api/v1/organizations/{org_id}",
        json={"settings": {"github_token": "ghp_RealLookingToken1234567890abcdef"}},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )
    assert res_pat_key.status_code == 400
    assert res_pat_key.json()["code"] == "CREDENTIAL_IN_SETTINGS_FORBIDDEN"
    assert "ghp_RealLookingToken" not in res_pat_key.text

    # 2. Tenant route: Attempt to save raw token prefix in value
    res_raw_token = await client.patch(
        f"/api/v1/organizations/{org_id}",
        json={"settings": {"custom_auth": "ghp_1234567890abcdef1234567890abcdef"}},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )
    assert res_raw_token.status_code == 400
    assert res_raw_token.json()["code"] == "PLAINTEXT_TOKEN_IN_SETTINGS_FORBIDDEN"
    assert "ghp_123456" not in res_raw_token.text

    # 3. Tenant route: Attempt to save raw token in a list
    res_list = await client.patch(
        f"/api/v1/organizations/{org_id}",
        json={"settings": {"allowed_tokens": ["ghp_1234567890abcdef1234567890abcdef"]}},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )
    assert res_list.status_code == 400
    assert res_list.json()["code"] in ("CREDENTIAL_IN_SETTINGS_FORBIDDEN", "PLAINTEXT_TOKEN_IN_SETTINGS_FORBIDDEN")

    # 4. Admin route: Attempt to save API key in admin update
    res_admin_bad = await client.patch(
        f"/api/v1/admin/organizations/{org_id}",
        json={"settings": {"api_key": "some_secret_api_key_123"}},
        cookies={settings.SESSION_COOKIE_NAME: admin_token},
        headers=ORIGIN_HEADER,
    )
    assert res_admin_bad.status_code == 400
    assert res_admin_bad.json()["code"] == "CREDENTIAL_IN_SETTINGS_FORBIDDEN"

    # 5. Legitimate non-secret settings must succeed
    res_ok = await client.patch(
        f"/api/v1/organizations/{org_id}",
        json={"settings": {"theme": "dark", "locale": "en_US", "display_limit": 50}},
        cookies={settings.SESSION_COOKIE_NAME: alice_token},
        headers=ORIGIN_HEADER,
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["settings"]["theme"] == "dark"
    assert res_ok.json()["settings"]["locale"] == "en_US"
    assert res_ok.json()["settings"]["display_limit"] == 50



# =====================================================================
# Milestone 2 Security Audit Negative Tests (Least Privilege & Integrity)
# =====================================================================

@pytest.mark.asyncio
async def test_platform_ops_admin_forbidden_from_transferring_ownership(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """
    Table 5.2 Least Privilege: PLATFORM_OPS_ADMIN cannot transfer organization ownership.
    Must be rejected with 403 FORBIDDEN_INSUFFICIENT_ROLE.
    """
    suffix = uuid.uuid4().hex[:6]
    ops_admin = await create_user_helper(
        email=f"ops_{suffix}@scorva.io",
        platform_role=PlatformRole.PLATFORM_OPS_ADMIN,
    )
    ops_token = await create_session_helper(ops_admin)

    p_owner = await create_user_helper(
        email=f"powner_{suffix}@scorva.io",
        platform_role=PlatformRole.PLATFORM_OWNER,
    )
    owner_token = await create_session_helper(p_owner)

    alice = await create_user_helper(email=f"alice_{suffix}@scorva.io", platform_role=None)
    bob = await create_user_helper(email=f"bob_{suffix}@scorva.io", platform_role=None)

    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Transfer Restrict Org", "slug": f"transfer-res-{suffix}", "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: owner_token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    await client.post(
        f"/api/v1/admin/organizations/{org_id}/members",
        json={"user_id": str(bob.id), "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: owner_token},
        headers=ORIGIN_HEADER,
    )

    # PLATFORM_OPS_ADMIN attempts to transfer ownership -> 403 FORBIDDEN_INSUFFICIENT_ROLE
    res = await client.post(
        f"/api/v1/admin/organizations/{org_id}/transfer-ownership",
        json={"new_owner_user_id": str(bob.id), "reason": "Ops admin transfer"},
        cookies={settings.SESSION_COOKIE_NAME: ops_token},
        headers=ORIGIN_HEADER,
    )
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN_INSUFFICIENT_ROLE"


@pytest.mark.asyncio
async def test_platform_ops_admin_forbidden_from_archiving_organization(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """
    Table 5.2 Least Privilege: PLATFORM_OPS_ADMIN cannot archive an organization.
    Must be rejected with 403 FORBIDDEN_INSUFFICIENT_ROLE.
    """
    suffix = uuid.uuid4().hex[:6]
    ops_admin = await create_user_helper(
        email=f"ops_{suffix}@scorva.io",
        platform_role=PlatformRole.PLATFORM_OPS_ADMIN,
    )
    ops_token = await create_session_helper(ops_admin)

    alice = await create_user_helper(email=f"alice_{suffix}@scorva.io", platform_role=None)

    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Archive Restrict Org", "slug": f"archive-res-{suffix}", "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: ops_token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    # PLATFORM_OPS_ADMIN attempts to archive -> 403 FORBIDDEN_INSUFFICIENT_ROLE
    res = await client.post(
        f"/api/v1/admin/organizations/{org_id}/status",
        json={"status": "archived", "reason": "Unauthorized archival attempt"},
        cookies={settings.SESSION_COOKIE_NAME: ops_token},
        headers=ORIGIN_HEADER,
    )
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN_INSUFFICIENT_ROLE"


@pytest.mark.asyncio
async def test_platform_ops_admin_forbidden_from_promoting_to_org_admin(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """
    Table 5.2 Least Privilege: PLATFORM_OPS_ADMIN cannot promote a member to org_admin.
    Must be rejected with 403 FORBIDDEN_INSUFFICIENT_ROLE.
    """
    suffix = uuid.uuid4().hex[:6]
    ops_admin = await create_user_helper(
        email=f"ops_{suffix}@scorva.io",
        platform_role=PlatformRole.PLATFORM_OPS_ADMIN,
    )
    ops_token = await create_session_helper(ops_admin)

    alice = await create_user_helper(email=f"alice_{suffix}@scorva.io", platform_role=None)
    bob = await create_user_helper(email=f"bob_{suffix}@scorva.io", platform_role=None)

    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Promo Restrict Org", "slug": f"promo-res-{suffix}", "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: ops_token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    await client.post(
        f"/api/v1/admin/organizations/{org_id}/members",
        json={"user_id": str(bob.id), "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: ops_token},
        headers=ORIGIN_HEADER,
    )

    # PLATFORM_OPS_ADMIN attempts to promote Bob to org_admin -> 403 FORBIDDEN_INSUFFICIENT_ROLE
    res = await client.patch(
        f"/api/v1/admin/organizations/{org_id}/members/{bob.id}",
        json={"role": "org_admin"},
        cookies={settings.SESSION_COOKIE_NAME: ops_token},
        headers=ORIGIN_HEADER,
    )
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN_INSUFFICIENT_ROLE"


@pytest.mark.asyncio
async def test_unprivileged_platform_roles_denied_admin_organizations(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """
    Verifies that unprivileged platform roles (SECURITY_ADMIN, BILLING_ADMIN)
    are denied access to /api/v1/admin/organizations with 403 FORBIDDEN_INSUFFICIENT_ROLE.
    """
    suffix = uuid.uuid4().hex[:6]
    sec_admin = await create_user_helper(
        email=f"sec_{suffix}@scorva.io",
        platform_role=PlatformRole.SECURITY_ADMIN,
    )
    sec_token = await create_session_helper(sec_admin)

    billing_admin = await create_user_helper(
        email=f"bill_{suffix}@scorva.io",
        platform_role=PlatformRole.BILLING_ADMIN,
    )
    billing_token = await create_session_helper(billing_admin)

    res1 = await client.get(
        "/api/v1/admin/organizations",
        cookies={settings.SESSION_COOKIE_NAME: sec_token},
    )
    assert res1.status_code == 403
    assert res1.json()["code"] == "FORBIDDEN_INSUFFICIENT_ROLE"

    res2 = await client.get(
        "/api/v1/admin/organizations",
        cookies={settings.SESSION_COOKIE_NAME: billing_token},
    )
    assert res2.status_code == 403
    assert res2.json()["code"] == "FORBIDDEN_INSUFFICIENT_ROLE"


@pytest.mark.asyncio
async def test_suspend_without_reason_or_whitespace_reason_rejected(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """
    Mandatory Audit Integrity: Suspending an organization without a reason or
    with only whitespace is strictly rejected.
    """
    suffix = uuid.uuid4().hex[:6]
    admin = await create_user_helper(
        email=f"admin_{suffix}@scorva.io",
        platform_role=PlatformRole.PLATFORM_OPS_ADMIN,
    )
    token = await create_session_helper(admin)

    alice = await create_user_helper(email=f"alice_{suffix}@scorva.io", platform_role=None)
    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Reason Org", "slug": f"reason-org-{suffix}", "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    # 1. Missing reason
    res1 = await client.post(
        f"/api/v1/admin/organizations/{org_id}/status",
        json={"is_active": False},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    assert res1.status_code == 400
    assert res1.json()["code"] == "REASON_REQUIRED"

    # 2. Whitespace-only reason
    res2 = await client.post(
        f"/api/v1/admin/organizations/{org_id}/status",
        json={"is_active": False, "reason": "   "},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    assert res2.status_code == 422  # Pydantic field_validator rejects empty/whitespace


@pytest.mark.asyncio
async def test_transfer_ownership_to_current_owner_rejected(
    client: AsyncClient, create_user_helper, create_session_helper
):
    """
    Ownership Transfer Integrity: Transferring ownership to the user who is already
    the current owner is rejected with 400 ALREADY_OWNER.
    """
    suffix = uuid.uuid4().hex[:6]
    platform_owner = await create_user_helper(
        email=f"admin_{suffix}@scorva.io",
        platform_role=PlatformRole.PLATFORM_OWNER,
    )
    token = await create_session_helper(platform_owner)

    alice = await create_user_helper(email=f"alice_{suffix}@scorva.io", platform_role=None)

    create_res = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Self Transfer Org", "slug": f"self-transfer-{suffix}", "owner_email": alice.email},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    org_id = create_res.json()["id"]

    res = await client.post(
        f"/api/v1/admin/organizations/{org_id}/transfer-ownership",
        json={"new_owner_user_id": str(alice.id), "reason": "Transfer to current owner"},
        cookies={settings.SESSION_COOKIE_NAME: token},
        headers=ORIGIN_HEADER,
    )
    assert res.status_code == 400
    assert res.json()["code"] == "ALREADY_OWNER"

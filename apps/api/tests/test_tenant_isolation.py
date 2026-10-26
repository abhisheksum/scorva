import asyncio
from datetime import datetime, timedelta, timezone
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from apps.api.config import settings
from apps.api.modules.audit.models import AuditEvent
from apps.api.modules.hackathons.models import Hackathon, HackathonStatus
from apps.api.modules.organizations.models import (
    MembershipStatus,
    OrgRole,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
)
from apps.api.modules.users.models import PlatformRole, User

ORIGIN_HEADER = {"Origin": "http://testserver"}


@pytest.fixture
async def multi_tenant_fixture(db_session, create_user_helper, create_session_helper):
    """
    Sets up a complete multi-tenant test harness with two distinct organizations:
    Org A (Alpha Corp) owned by Alice, with Bob as Admin.
    Org B (Beta Labs) owned by Charlie.
    Dave: Unaffiliated user.
    Super Admin: Platform Owner.
    Ops Admin: Platform Ops Admin.
    """
    # 1. Platform Administrators
    super_admin = await create_user_helper(
        email=f"super_admin_{uuid.uuid4().hex[:6]}@scorva.io",
        platform_role=PlatformRole.PLATFORM_OWNER,
    )
    super_admin_token = await create_session_helper(super_admin)

    ops_admin = await create_user_helper(
        email=f"ops_admin_{uuid.uuid4().hex[:6]}@scorva.io",
        platform_role=PlatformRole.PLATFORM_OPS_ADMIN,
    )
    ops_admin_token = await create_session_helper(ops_admin)

    # 2. Org A Users
    alice = await create_user_helper(
        email=f"alice_{uuid.uuid4().hex[:6]}@alpha.io",
        platform_role=None,
    )
    alice_token = await create_session_helper(alice)

    bob = await create_user_helper(
        email=f"bob_{uuid.uuid4().hex[:6]}@alpha.io",
        platform_role=None,
    )
    bob_token = await create_session_helper(bob)

    # 3. Org B Users
    charlie = await create_user_helper(
        email=f"charlie_{uuid.uuid4().hex[:6]}@beta.io",
        platform_role=None,
    )
    charlie_token = await create_session_helper(charlie)

    # 4. Unaffiliated User
    dave = await create_user_helper(
        email=f"dave_{uuid.uuid4().hex[:6]}@unaffiliated.io",
        platform_role=None,
    )
    dave_token = await create_session_helper(dave)

    # 5. Organizations
    org_a = Organization(
        id=uuid.uuid4(),
        name="Alpha Corporation",
        slug=f"alpha-corp-{uuid.uuid4().hex[:6]}",
        owner_id=alice.id,
        status=OrganizationStatus.ACTIVE,
        settings={"max_hackathons": 10, "timezone": "UTC"},
    )
    org_b = Organization(
        id=uuid.uuid4(),
        name="Beta Laboratories",
        slug=f"beta-labs-{uuid.uuid4().hex[:6]}",
        owner_id=charlie.id,
        status=OrganizationStatus.ACTIVE,
        settings={"max_hackathons": 5, "timezone": "America/New_York"},
    )
    db_session.add_all([org_a, org_b])

    # 6. Memberships
    # Org A: Alice (Owner), Bob (Admin)
    mem_alice = OrganizationMembership(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        user_id=alice.id,
        role=OrgRole.ORG_OWNER,
        status=MembershipStatus.ACTIVE,
    )
    mem_bob = OrganizationMembership(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        user_id=bob.id,
        role=OrgRole.ORG_ADMIN,
        status=MembershipStatus.ACTIVE,
    )
    # Org B: Charlie (Owner)
    mem_charlie = OrganizationMembership(
        id=uuid.uuid4(),
        organization_id=org_b.id,
        user_id=charlie.id,
        role=OrgRole.ORG_OWNER,
        status=MembershipStatus.ACTIVE,
    )
    db_session.add_all([mem_alice, mem_bob, mem_charlie])
    await db_session.commit()

    return {
        "super_admin": super_admin,
        "super_admin_token": super_admin_token,
        "ops_admin": ops_admin,
        "ops_admin_token": ops_admin_token,
        "alice": alice,
        "alice_token": alice_token,
        "bob": bob,
        "bob_token": bob_token,
        "charlie": charlie,
        "charlie_token": charlie_token,
        "dave": dave,
        "dave_token": dave_token,
        "org_a": org_a,
        "org_b": org_b,
    }


@pytest.mark.asyncio
async def test_cross_tenant_read_via_organization_id_blocked(client: AsyncClient, multi_tenant_fixture):
    """
    ISO-01: Cross-Tenant Read via Organization ID.
    Alice (Org A Owner) attempts to read Org B profile.
    Expected: 403 Forbidden (TENANT_ACCESS_DENIED). Alice has no membership in Org B.
    """
    f = multi_tenant_fixture
    res = await client.get(
        f"/api/v1/organizations/{f['org_b'].id}",
        cookies={settings.SESSION_COOKIE_NAME: f["alice_token"]},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "TENANT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_cross_tenant_member_list_read_blocked(client: AsyncClient, multi_tenant_fixture):
    """Alice (Org A Owner) attempts to read Org B member roster."""
    f = multi_tenant_fixture
    res = await client.get(
        f"/api/v1/organizations/{f['org_b'].id}/members",
        cookies={settings.SESSION_COOKIE_NAME: f["alice_token"]},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "TENANT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_cross_tenant_member_add_blocked(client: AsyncClient, multi_tenant_fixture):
    """Alice (Org A Owner) attempts to add a member to Org B."""
    f = multi_tenant_fixture
    res = await client.post(
        f"/api/v1/organizations/{f['org_b'].id}/members",
        json={"email": f["dave"].email, "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: f["alice_token"]},
        headers=ORIGIN_HEADER,
    )
    assert res.status_code == 403
    assert res.json()["code"] == "TENANT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_cross_tenant_profile_modification_blocked(client: AsyncClient, multi_tenant_fixture):
    """
    ISO-04: Cross-Tenant Modification Attempt.
    Bob (Org A Admin) attempts to update Org B profile.
    Expected: 403 Forbidden (TENANT_ACCESS_DENIED).
    """
    f = multi_tenant_fixture
    res = await client.patch(
        f"/api/v1/organizations/{f['org_b'].id}",
        json={"name": "Hacked Beta Labs"},
        cookies={settings.SESSION_COOKIE_NAME: f["bob_token"]},
        headers=ORIGIN_HEADER,
    )
    assert res.status_code == 403
    assert res.json()["code"] == "TENANT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_cross_tenant_delete_member_blocked(client: AsyncClient, multi_tenant_fixture):
    """
    ISO-05: Cross-Tenant Delete Attempt.
    Alice (Org A Owner) attempts to delete Charlie from Org B.
    Expected: 403 Forbidden (TENANT_ACCESS_DENIED).
    """
    f = multi_tenant_fixture
    res = await client.delete(
        f"/api/v1/organizations/{f['org_b'].id}/members/{f['charlie'].id}",
        cookies={settings.SESSION_COOKIE_NAME: f["alice_token"]},
        headers=ORIGIN_HEADER,
    )
    assert res.status_code == 403
    assert res.json()["code"] == "TENANT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_request_body_tenant_id_injection_blocked(client: AsyncClient, multi_tenant_fixture):
    """
    ISO-06: Request Body Tenant ID Injection Attack.
    Alice sends a body payload attempting to inject organization_id or owner_id.
    Schema validation with extra='forbid' strictly rejects with 422 Unprocessable Entity.
    """
    f = multi_tenant_fixture
    res = await client.patch(
        f"/api/v1/organizations/{f['org_a'].id}",
        json={
            "name": "Alpha Corp New Name",
            "organization_id": str(f["org_b"].id),
            "owner_id": str(f["charlie"].id),
        },
        cookies={settings.SESSION_COOKIE_NAME: f["alice_token"]},
        headers=ORIGIN_HEADER,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_suspended_organization_read_allowed_mutation_blocked(client: AsyncClient, db_session, multi_tenant_fixture):
    """
    ISO-07: Charlie (Org B Owner) reads Org B metadata after suspension (200 OK, read-only).
    ISO-08: Charlie attempts to modify Org B after suspension (403 ORGANIZATION_SUSPENDED).
    """
    f = multi_tenant_fixture

    # Suspend Org B
    f["org_b"].status = OrganizationStatus.SUSPENDED
    await db_session.commit()

    # ISO-07: Safe read allowed for active member
    read_res = await client.get(
        f"/api/v1/organizations/{f['org_b'].id}",
        cookies={settings.SESSION_COOKIE_NAME: f["charlie_token"]},
    )
    assert read_res.status_code == 200
    assert read_res.json()["status"] == "suspended"

    # ISO-08: State-modifying PATCH blocked
    patch_res = await client.patch(
        f"/api/v1/organizations/{f['org_b'].id}",
        json={"name": "Mutated Beta Labs"},
        cookies={settings.SESSION_COOKIE_NAME: f["charlie_token"]},
        headers=ORIGIN_HEADER,
    )
    assert patch_res.status_code == 403
    assert patch_res.json()["code"] == "ORGANIZATION_SUSPENDED"

    # State-modifying POST blocked
    post_res = await client.post(
        f"/api/v1/organizations/{f['org_b'].id}/members",
        json={"email": f["dave"].email, "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: f["charlie_token"]},
        headers=ORIGIN_HEADER,
    )
    assert post_res.status_code == 403
    assert post_res.json()["code"] == "ORGANIZATION_SUSPENDED"


@pytest.mark.asyncio
async def test_archived_organization_access_blocked(client: AsyncClient, db_session, multi_tenant_fixture):
    """Archived organizations deny all member access with 403 ORGANIZATION_ARCHIVED."""
    f = multi_tenant_fixture
    f["org_b"].status = OrganizationStatus.ARCHIVED
    await db_session.commit()

    res = await client.get(
        f"/api/v1/organizations/{f['org_b'].id}",
        cookies={settings.SESSION_COOKIE_NAME: f["charlie_token"]},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "ORGANIZATION_ARCHIVED"


@pytest.mark.asyncio
async def test_suspended_membership_access_blocked(client: AsyncClient, db_session, multi_tenant_fixture):
    """Active organization, but member's membership is suspended: blocked with 403 MEMBERSHIP_SUSPENDED."""
    f = multi_tenant_fixture

    # Suspend Bob's membership in Org A
    bob_mem = (await db_session.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == f["org_a"].id,
            OrganizationMembership.user_id == f["bob"].id,
        )
    )).scalar_one()
    bob_mem.status = MembershipStatus.SUSPENDED
    await db_session.commit()

    res = await client.get(
        f"/api/v1/organizations/{f['org_a'].id}",
        cookies={settings.SESSION_COOKIE_NAME: f["bob_token"]},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "MEMBERSHIP_SUSPENDED"


@pytest.mark.asyncio
async def test_removed_member_immediate_revocation(client: AsyncClient, db_session, multi_tenant_fixture):
    """
    ISO-09: Removed Member Immediate Revocation.
    Dave is added to Org A. Dave has an active session.
    Dave is removed from Org A.
    Dave immediately calls GET /api/v1/organizations/{org_a_id} using existing session.
    Expected: 403 Forbidden (TENANT_ACCESS_DENIED). Membership check evaluates current DB state.
    """
    f = multi_tenant_fixture

    # Add Dave to Org A
    add_res = await client.post(
        f"/api/v1/organizations/{f['org_a'].id}/members",
        json={"email": f["dave"].email, "role": "organizer"},
        cookies={settings.SESSION_COOKIE_NAME: f["alice_token"]},
        headers=ORIGIN_HEADER,
    )
    assert add_res.status_code == 201

    # Dave can read Org A
    read_ok = await client.get(
        f"/api/v1/organizations/{f['org_a'].id}",
        cookies={settings.SESSION_COOKIE_NAME: f["dave_token"]},
    )
    assert read_ok.status_code == 200

    # Alice removes Dave from Org A
    del_res = await client.delete(
        f"/api/v1/organizations/{f['org_a'].id}/members/{f['dave'].id}",
        cookies={settings.SESSION_COOKIE_NAME: f["alice_token"]},
        headers=ORIGIN_HEADER,
    )
    assert del_res.status_code == 200

    # Dave immediately rejected on subsequent request
    read_revoked = await client.get(
        f"/api/v1/organizations/{f['org_a'].id}",
        cookies={settings.SESSION_COOKIE_NAME: f["dave_token"]},
    )
    assert read_revoked.status_code == 403
    assert read_revoked.json()["code"] == "TENANT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_suspended_user_access_across_all_tenants(client: AsyncClient, db_session, multi_tenant_fixture):
    """
    ISO-10: Suspended User Access Across All Tenants.
    User Alice is suspended globally.
    Alice calls GET /api/v1/organizations/{org_a_id}.
    Expected: 401 Unauthorized (ACCOUNT_SUSPENDED).
    """
    f = multi_tenant_fixture

    # Suspend Alice globally
    f["alice"].is_active = False
    await db_session.commit()

    res = await client.get(
        f"/api/v1/organizations/{f['org_a'].id}",
        cookies={settings.SESSION_COOKIE_NAME: f["alice_token"]},
    )
    assert res.status_code == 401
    assert res.json()["code"] == "ACCOUNT_SUSPENDED"


@pytest.mark.asyncio
async def test_guessed_uuid_fails_closed(client: AsyncClient, multi_tenant_fixture):
    """Guessed non-existent organization UUID returns 404 Not Found without leaking information."""
    f = multi_tenant_fixture
    random_id = uuid.uuid4()
    res = await client.get(
        f"/api/v1/organizations/{random_id}",
        cookies={settings.SESSION_COOKIE_NAME: f["alice_token"]},
    )
    assert res.status_code == 404
    assert res.json()["code"] == "ORGANIZATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_unauthenticated_request_fails_closed(client: AsyncClient, multi_tenant_fixture):
    """Request without session cookie rejected with 401 Unauthorized."""
    f = multi_tenant_fixture
    res = await client.get(f"/api/v1/organizations/{f['org_a'].id}")
    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_platform_admin_denied_from_tenant_plane_without_membership(client: AsyncClient, multi_tenant_fixture):
    """
    DUAL-02: Platform Ops Admin without org membership cannot directly access tenant route.
    Must use designated /api/v1/admin/... endpoints for auditable intervention.
    """
    f = multi_tenant_fixture
    res = await client.get(
        f"/api/v1/organizations/{f['org_a'].id}",
        cookies={settings.SESSION_COOKIE_NAME: f["ops_admin_token"]},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "TENANT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_platform_intervention_generates_immutable_audit_record(client: AsyncClient, db_session, multi_tenant_fixture):
    """
    DUAL-03: Platform admin updates organization settings via admin plane.
    Action succeeds, records audit event with organization_id.
    PostgreSQL trigger prevents UPDATE or DELETE of this audit event.
    """
    f = multi_tenant_fixture
    res = await client.patch(
        f"/api/v1/admin/organizations/{f['org_a'].id}",
        json={"name": "Alpha Corp Rebranded", "settings": {"max_hackathons": 25}},
        cookies={settings.SESSION_COOKIE_NAME: f["ops_admin_token"]},
        headers=ORIGIN_HEADER,
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Alpha Corp Rebranded"

    # Query audit event
    audit_stmt = select(AuditEvent).where(
        AuditEvent.organization_id == f["org_a"].id,
        AuditEvent.action == "organization_updated",
    )
    audit = (await db_session.execute(audit_stmt)).scalars().first()
    assert audit is not None
    assert audit.actor_user_id == f["ops_admin"].id
    assert audit.actor_role == "platform_ops_admin"
    assert audit.organization_id == f["org_a"].id
    audit_id = audit.id

    # Verify immutability: PostgreSQL trigger trg_audit_events_immutable blocks UPDATE
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text(f"UPDATE audit_events SET reason = 'Tampered' WHERE id = '{audit_id}'")
        )
        await db_session.commit()
    await db_session.rollback()

    # Verify immutability: PostgreSQL trigger trg_audit_events_immutable blocks DELETE
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text(f"DELETE FROM audit_events WHERE id = '{audit_id}'")
        )
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_concurrent_ownership_transfers_safely_serialize(client: AsyncClient, db_session, multi_tenant_fixture):
    """
    Ownership Transfer Concurrency Verification:
    Concurrent transfer requests are serialized via row-level locks (.with_for_update()).
    One request succeeds, and the duplicate request is safely rejected with 400 ALREADY_OWNER
    without corrupting the organization's owner_id or membership state.
    """
    f = multi_tenant_fixture

    org_id = f["org_a"].id
    bob_id = f["bob"].id
    alice_id = f["alice"].id

    # Concurrently execute two transfer requests to Bob
    req1 = client.post(
        f"/api/v1/organizations/{org_id}/transfer-ownership",
        json={"new_owner_user_id": str(bob_id), "reason": "Concurrent transfer 1"},
        cookies={settings.SESSION_COOKIE_NAME: f["alice_token"]},
        headers=ORIGIN_HEADER,
    )
    req2 = client.post(
        f"/api/v1/organizations/{org_id}/transfer-ownership",
        json={"new_owner_user_id": str(bob_id), "reason": "Concurrent transfer 2"},
        cookies={settings.SESSION_COOKIE_NAME: f["alice_token"]},
        headers=ORIGIN_HEADER,
    )

    res1, res2 = await asyncio.gather(req1, req2)
    statuses = [res1.status_code, res2.status_code]

    # Exactly one must succeed (200 OK); the duplicate is rejected (400 ALREADY_OWNER or 403 FORBIDDEN if role changed)
    assert 200 in statuses
    assert (400 in statuses or 403 in statuses)

    # Verify database consistency: org owner is Bob and Alice is org_admin
    await db_session.rollback()
    org_stmt = (
        select(Organization)
        .where(Organization.id == org_id)
        .execution_options(populate_existing=True)
    )
    org = (await db_session.execute(org_stmt)).scalar_one()
    assert org.owner_id == bob_id

    alice_mem = (await db_session.execute(
        select(OrganizationMembership)
        .where(
            OrganizationMembership.organization_id == org_id,
            OrganizationMembership.user_id == alice_id,
        )
        .execution_options(populate_existing=True)
    )).scalar_one()
    bob_mem = (await db_session.execute(
        select(OrganizationMembership)
        .where(
            OrganizationMembership.organization_id == org_id,
            OrganizationMembership.user_id == bob_id,
        )
        .execution_options(populate_existing=True)
    )).scalar_one()

    assert alice_mem.role == OrgRole.ORG_ADMIN
    assert bob_mem.role == OrgRole.ORG_OWNER


@pytest.mark.asyncio
async def test_iso_02_cross_tenant_read_hackathon_by_guessed_uuid_blocked(client: AsyncClient, db_session, multi_tenant_fixture):
    """
    ISO-02: Cross-Tenant Read Hackathon by Guessed UUID.
    Alice (Org A Owner) attempts to query Org B's hackathon under Org A's URL:
    GET /api/v1/organizations/{org_a_id}/hackathons/{hackathon_b_id}
    Expected: 404 Not Found (HACKATHON_NOT_FOUND).
    Backend scopes query by org_a_id; does not leak that hackathon_b_id exists in Org B.
    """
    f = multi_tenant_fixture
    now = datetime.now(timezone.utc)
    hackathon_b = Hackathon(
        id=uuid.uuid4(),
        organization_id=f["org_b"].id,
        title="Beta Secret Hackathon",
        slug=f"beta-secret-{uuid.uuid4().hex[:6]}",
        status=HackathonStatus.DRAFT,
        start_date=now + timedelta(days=1),
        submission_deadline=now + timedelta(days=3),
        end_date=now + timedelta(days=5),
        created_by_user_id=f["charlie"].id,
        settings={},
    )
    db_session.add(hackathon_b)
    await db_session.commit()

    res = await client.get(
        f"/api/v1/organizations/{f['org_a'].id}/hackathons/{hackathon_b.id}",
        cookies={settings.SESSION_COOKIE_NAME: f["alice_token"]},
    )
    assert res.status_code == 404
    assert res.json()["code"] == "HACKATHON_NOT_FOUND"


@pytest.mark.asyncio
async def test_iso_03_direct_path_traversal_into_other_tenant_hackathon_blocked(client: AsyncClient, db_session, multi_tenant_fixture):
    """
    ISO-03: Direct Path Traversal into Other Tenant's Hackathon.
    Bob (Org A Admin) attempts to access Org B's hackathon directly:
    GET /api/v1/organizations/{org_b_id}/hackathons/{hackathon_b_id}
    Expected: 403 Forbidden (TENANT_ACCESS_DENIED). Bob is not a member of Org B.
    """
    f = multi_tenant_fixture
    now = datetime.now(timezone.utc)
    hackathon_b = Hackathon(
        id=uuid.uuid4(),
        organization_id=f["org_b"].id,
        title="Beta Hackathon",
        slug=f"beta-hackathon-{uuid.uuid4().hex[:6]}",
        status=HackathonStatus.DRAFT,
        start_date=now + timedelta(days=1),
        submission_deadline=now + timedelta(days=3),
        end_date=now + timedelta(days=5),
        created_by_user_id=f["charlie"].id,
        settings={},
    )
    db_session.add(hackathon_b)
    await db_session.commit()

    res = await client.get(
        f"/api/v1/organizations/{f['org_b'].id}/hackathons/{hackathon_b.id}",
        cookies={settings.SESSION_COOKIE_NAME: f["bob_token"]},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "TENANT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_iso_04_cross_tenant_hackathon_modification_blocked(client: AsyncClient, db_session, multi_tenant_fixture):
    """
    ISO-04: Cross-Tenant Hackathon Modification Attempt.
    Bob (Org A Admin) attempts to PATCH Org B's hackathon.
    Expected: 403 Forbidden (TENANT_ACCESS_DENIED).
    """
    f = multi_tenant_fixture
    now = datetime.now(timezone.utc)
    hackathon_b = Hackathon(
        id=uuid.uuid4(),
        organization_id=f["org_b"].id,
        title="Beta Hackathon 2",
        slug=f"beta-hack-2-{uuid.uuid4().hex[:6]}",
        status=HackathonStatus.DRAFT,
        start_date=now + timedelta(days=1),
        submission_deadline=now + timedelta(days=3),
        end_date=now + timedelta(days=5),
        created_by_user_id=f["charlie"].id,
        settings={},
    )
    db_session.add(hackathon_b)
    await db_session.commit()

    res = await client.patch(
        f"/api/v1/organizations/{f['org_b'].id}/hackathons/{hackathon_b.id}",
        json={"title": "Hacked Title"},
        cookies={settings.SESSION_COOKIE_NAME: f["bob_token"]},
        headers=ORIGIN_HEADER,
    )
    assert res.status_code == 403
    assert res.json()["code"] == "TENANT_ACCESS_DENIED"



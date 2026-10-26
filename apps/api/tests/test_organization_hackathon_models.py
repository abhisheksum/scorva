from datetime import datetime, timedelta, timezone
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError

from apps.api.modules.audit.models import AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.organizations.models import (
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
    OrgRole,
)
from apps.api.modules.hackathons.models import (
    Hackathon,
    HackathonStatus,
)
from apps.api.modules.users.models import PlatformRole, User


@pytest.fixture
async def create_org_helper(db_session, create_user_helper):
    """Fixture assisting in creating clean test organizations and owners."""
    async def _create_org(
        name: str = "Acme Hackathons",
        slug: str = None,
        owner: User = None,
        status: OrganizationStatus = OrganizationStatus.ACTIVE,
        settings: dict = None,
    ) -> Organization:
        if not owner:
            owner = await create_user_helper(
                email=f"owner_{uuid.uuid4().hex[:8]}@example.com",
                full_name="Org Owner",
            )
        if not slug:
            slug = f"org-{uuid.uuid4().hex[:8]}"

        org = Organization(
            id=uuid.uuid4(),
            name=name,
            slug=slug,
            owner_id=owner.id,
            status=status,
            settings=settings or {"max_hackathons": 5, "timezone": "UTC"},
        )
        db_session.add(org)
        await db_session.commit()
        await db_session.refresh(org)
        return org

    return _create_org


@pytest.mark.asyncio
async def test_organization_creation_and_unique_slug(db_session, create_org_helper, create_user_helper):
    """
    Verifies successful creation of an Organization and database-level unique constraint on slug.
    """
    unique_slug = f"uniq-slug-{uuid.uuid4().hex[:8]}"
    org1 = await create_org_helper(name="First Org", slug=unique_slug)
    assert org1.id is not None
    assert org1.name == "First Org"
    assert org1.slug == unique_slug
    assert org1.status == OrganizationStatus.ACTIVE
    assert org1.settings["max_hackathons"] == 5

    # Attempt to create duplicate slug
    owner2 = await create_user_helper(email=f"owner2_{uuid.uuid4().hex[:8]}@example.com")
    owner2_id = owner2.id
    duplicate_org = Organization(
        id=uuid.uuid4(),
        name="Second Org Duplicate",
        slug=unique_slug,
        owner_id=owner2_id,
        status=OrganizationStatus.ACTIVE,
        settings={},
    )
    db_session.add(duplicate_org)
    with pytest.raises(IntegrityError) as exc_info:
        await db_session.commit()
    await db_session.rollback()
    assert "slug" in str(exc_info.value).lower() or "unique" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_organization_owner_fk_restrict(db_session, create_org_helper, create_user_helper):
    """
    Verifies that deleting a user who owns an organization is restricted at the database level.
    """
    owner = await create_user_helper(email=f"protected_owner_{uuid.uuid4().hex[:8]}@example.com")
    owner_id = owner.id
    org = await create_org_helper(owner=owner)
    org_id = org.id

    # Attempt to delete owner directly
    await db_session.delete(owner)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # Verify owner still exists using preserved owner_id
    surviving_owner = (await db_session.execute(select(User).where(User.id == owner_id))).scalar_one_or_none()
    assert surviving_owner is not None

    # Clean up org then owner so database remains tidy
    surviving_org = (await db_session.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if surviving_org:
        await db_session.delete(surviving_org)
        await db_session.commit()
    surviving_owner = (await db_session.execute(select(User).where(User.id == owner_id))).scalar_one_or_none()
    if surviving_owner:
        await db_session.delete(surviving_owner)
        await db_session.commit()


@pytest.mark.asyncio
async def test_membership_creation_and_uniqueness(db_session, create_org_helper, create_user_helper):
    """
    Verifies that organization memberships can be created, and unique constraint uq_organization_user is enforced.
    """
    org = await create_org_helper()
    org_id = org.id
    member_user = await create_user_helper(email=f"member_{uuid.uuid4().hex[:8]}@example.com", platform_role=None)
    member_user_id = member_user.id

    membership = OrganizationMembership(
        id=uuid.uuid4(),
        organization_id=org_id,
        user_id=member_user_id,
        role=OrgRole.ORGANIZER,
        status=MembershipStatus.ACTIVE,
    )
    db_session.add(membership)
    await db_session.commit()
    await db_session.refresh(membership)

    assert membership.role == OrgRole.ORGANIZER
    assert membership.status == MembershipStatus.ACTIVE

    # Attempt to insert duplicate membership for same user in same organization
    duplicate_membership = OrganizationMembership(
        id=uuid.uuid4(),
        organization_id=org_id,
        user_id=member_user_id,
        role=OrgRole.ORG_ADMIN,
        status=MembershipStatus.ACTIVE,
    )
    db_session.add(duplicate_membership)
    with pytest.raises(IntegrityError) as exc_info:
        await db_session.commit()
    await db_session.rollback()
    assert "uq_organization_user" in str(exc_info.value).lower() or "unique" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_membership_cascade_deletion(db_session, create_org_helper, create_user_helper):
    """
    Verifies that deleting an organization cascade-deletes its memberships cleanly.
    """
    org = await create_org_helper()
    member = await create_user_helper(email=f"cascade_member_{uuid.uuid4().hex[:8]}@example.com")
    member_id = member.id

    membership = OrganizationMembership(
        id=uuid.uuid4(),
        organization_id=org.id,
        user_id=member_id,
        role=OrgRole.ORGANIZER,
        status=MembershipStatus.ACTIVE,
    )
    db_session.add(membership)
    await db_session.commit()
    membership_id = membership.id

    # Delete organization
    await db_session.delete(org)
    await db_session.commit()

    # Verify membership was cascade deleted
    surviving_membership = (
        await db_session.execute(
            select(OrganizationMembership).where(OrganizationMembership.id == membership_id)
        )
    ).scalar_one_or_none()
    assert surviving_membership is None

    # Verify user itself is preserved
    surviving_user = (await db_session.execute(select(User).where(User.id == member_id))).scalar_one_or_none()
    assert surviving_user is not None


@pytest.mark.asyncio
async def test_separation_of_platform_roles_and_organization_roles(db_session, create_org_helper, create_user_helper):
    """
    Verifies that platform roles (PlatformRole) and organization-scoped roles (OrgRole)
    remain completely independent at schema and model levels.
    """
    # User has no platform role (standard end-user)
    user = await create_user_helper(email=f"multi_role_{uuid.uuid4().hex[:8]}@example.com", platform_role=None)
    user_id = user.id
    assert user.platform_role is None

    org_a = await create_org_helper(name="Org Alpha", slug=f"org-alpha-{uuid.uuid4().hex[:8]}")
    org_b = await create_org_helper(name="Org Beta", slug=f"org-beta-{uuid.uuid4().hex[:8]}")

    # User is ORG_OWNER in Org A
    mem_a = OrganizationMembership(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        user_id=user_id,
        role=OrgRole.ORG_OWNER,
        status=MembershipStatus.ACTIVE,
    )
    # User is ORGANIZER in Org B
    mem_b = OrganizationMembership(
        id=uuid.uuid4(),
        organization_id=org_b.id,
        user_id=user_id,
        role=OrgRole.ORGANIZER,
        status=MembershipStatus.ACTIVE,
    )
    db_session.add_all([mem_a, mem_b])
    await db_session.commit()

    # Verify dual roles
    assert mem_a.role == OrgRole.ORG_OWNER
    assert mem_b.role == OrgRole.ORGANIZER
    assert user.platform_role is None

    # Promoting user to a platform role does not mutate their organization roles
    user.platform_role = PlatformRole.SECURITY_ADMIN
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(mem_a)
    await db_session.refresh(mem_b)

    assert user.platform_role == PlatformRole.SECURITY_ADMIN
    assert mem_a.role == OrgRole.ORG_OWNER
    assert mem_b.role == OrgRole.ORGANIZER


@pytest.mark.asyncio
async def test_hackathon_creation_and_tenant_scoped_slug(db_session, create_org_helper, create_user_helper):
    """
    Verifies:
    1. Valid hackathon creation.
    2. Tenant-scoped slug uniqueness: same slug in same org is rejected.
    3. Identical slug across DIFFERENT orgs is allowed.
    """
    org1 = await create_org_helper(name="Org One", slug=f"org-one-{uuid.uuid4().hex[:8]}")
    org1_id = org1.id
    org2 = await create_org_helper(name="Org Two", slug=f"org-two-{uuid.uuid4().hex[:8]}")
    org2_id = org2.id
    organizer = await create_user_helper(email=f"organizer_{uuid.uuid4().hex[:8]}@example.com")
    organizer_id = organizer.id

    now = datetime.now(timezone.utc)
    shared_slug = f"ai-challenge-{uuid.uuid4().hex[:8]}"

    h1 = Hackathon(
        id=uuid.uuid4(),
        organization_id=org1_id,
        title="AI Challenge 2026",
        slug=shared_slug,
        description="Global AI Competition",
        status=HackathonStatus.DRAFT,
        start_date=now + timedelta(days=1),
        submission_deadline=now + timedelta(days=5),
        end_date=now + timedelta(days=7),
        created_by_user_id=organizer_id,
        settings={"max_team_size": 4},
    )
    db_session.add(h1)
    await db_session.commit()
    await db_session.refresh(h1)

    assert h1.status == HackathonStatus.DRAFT
    assert h1.slug == shared_slug

    # Attempt to create duplicate slug in Org 1 -> must fail
    h1_duplicate = Hackathon(
        id=uuid.uuid4(),
        organization_id=org1_id,
        title="Duplicate AI Challenge",
        slug=shared_slug,
        status=HackathonStatus.DRAFT,
        start_date=now + timedelta(days=2),
        submission_deadline=now + timedelta(days=6),
        end_date=now + timedelta(days=8),
        created_by_user_id=organizer_id,
        settings={},
    )
    db_session.add(h1_duplicate)
    with pytest.raises(IntegrityError) as exc_info:
        await db_session.commit()
    await db_session.rollback()
    assert "uq_hackathons_org_slug" in str(exc_info.value).lower() or "unique" in str(exc_info.value).lower()

    # Create same slug in Org 2 -> MUST SUCCEED (tenant-scoped uniqueness)
    h2_different_org = Hackathon(
        id=uuid.uuid4(),
        organization_id=org2_id,
        title="Org Two AI Challenge",
        slug=shared_slug,
        status=HackathonStatus.DRAFT,
        start_date=now + timedelta(days=1),
        submission_deadline=now + timedelta(days=5),
        end_date=now + timedelta(days=7),
        created_by_user_id=organizer_id,
        settings={},
    )
    db_session.add(h2_different_org)
    await db_session.commit()
    await db_session.refresh(h2_different_org)
    assert h2_different_org.slug == shared_slug
    assert h2_different_org.organization_id == org2_id


@pytest.mark.asyncio
async def test_hackathon_timeline_check_constraint(db_session, create_org_helper, create_user_helper):
    """
    Verifies that the database check constraint chk_hackathon_timeline strictly rejects invalid date orderings:
    Requires: start_date < submission_deadline AND submission_deadline <= end_date
    """
    org = await create_org_helper()
    org_id = org.id
    organizer = await create_user_helper(email=f"timeline_{uuid.uuid4().hex[:8]}@example.com")
    organizer_id = organizer.id
    now = datetime.now(timezone.utc)

    # Invalid Case 1: start_date >= submission_deadline
    bad_h1 = Hackathon(
        id=uuid.uuid4(),
        organization_id=org_id,
        title="Bad Timeline 1",
        slug=f"bad-timeline-1-{uuid.uuid4().hex[:8]}",
        status=HackathonStatus.DRAFT,
        start_date=now + timedelta(days=5),
        submission_deadline=now + timedelta(days=2),  # Invalid: deadline before start!
        end_date=now + timedelta(days=7),
        created_by_user_id=organizer_id,
        settings={},
    )
    db_session.add(bad_h1)
    with pytest.raises(IntegrityError) as exc_info1:
        await db_session.commit()
    await db_session.rollback()
    assert "chk_hackathon_timeline" in str(exc_info1.value).lower() or "check" in str(exc_info1.value).lower()

    # Invalid Case 2: submission_deadline > end_date
    bad_h2 = Hackathon(
        id=uuid.uuid4(),
        organization_id=org_id,
        title="Bad Timeline 2",
        slug=f"bad-timeline-2-{uuid.uuid4().hex[:8]}",
        status=HackathonStatus.DRAFT,
        start_date=now + timedelta(days=1),
        submission_deadline=now + timedelta(days=10),  # Invalid: deadline after end date!
        end_date=now + timedelta(days=7),
        created_by_user_id=organizer_id,
        settings={},
    )
    db_session.add(bad_h2)
    with pytest.raises(IntegrityError) as exc_info2:
        await db_session.commit()
    await db_session.rollback()
    assert "chk_hackathon_timeline" in str(exc_info2.value).lower() or "check" in str(exc_info2.value).lower()


@pytest.mark.asyncio
async def test_hackathon_foreign_key_deletions_restricted(db_session, create_org_helper, create_user_helper):
    """
    Verifies that deleting an organization or creator with active hackathons is restricted.
    """
    org = await create_org_helper()
    org_id = org.id
    creator = await create_user_helper(email=f"creator_{uuid.uuid4().hex[:8]}@example.com")
    creator_id = creator.id
    now = datetime.now(timezone.utc)

    hackathon = Hackathon(
        id=uuid.uuid4(),
        organization_id=org_id,
        title="Protected Hackathon",
        slug=f"protected-hack-{uuid.uuid4().hex[:8]}",
        status=HackathonStatus.PUBLISHED,
        start_date=now + timedelta(days=1),
        submission_deadline=now + timedelta(days=3),
        end_date=now + timedelta(days=4),
        created_by_user_id=creator_id,
        settings={},
    )
    db_session.add(hackathon)
    await db_session.commit()
    hackathon_id = hackathon.id

    # Attempt to delete organization -> must fail with RESTRICT
    await db_session.delete(org)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # Attempt to delete creator user -> must fail with RESTRICT
    await db_session.delete(creator)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # Clean up hackathon, org, and creator
    surviving_h = (await db_session.execute(select(Hackathon).where(Hackathon.id == hackathon_id))).scalar_one_or_none()
    if surviving_h:
        await db_session.delete(surviving_h)
        await db_session.commit()
    surviving_org = (await db_session.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if surviving_org:
        await db_session.delete(surviving_org)
        await db_session.commit()
    surviving_user = (await db_session.execute(select(User).where(User.id == creator_id))).scalar_one_or_none()
    if surviving_user:
        await db_session.delete(surviving_user)
        await db_session.commit()


@pytest.mark.asyncio
async def test_audit_event_organization_compatibility(db_session, create_org_helper):
    """
    Verifies that recording an audit event with organization_id succeeds,
    and the immutability trigger blocks mutations on audit records.
    """
    org = await create_org_helper(name="Audited Org", slug=f"audited-org-{uuid.uuid4().hex[:8]}")
    org_id = org.id

    event = await record_audit_event(
        db=db_session,
        action="organization_created",
        resource_type="organization",
        resource_id=str(org_id),
        outcome=AuditOutcome.SUCCESS,
        actor_email=f"admin_{uuid.uuid4().hex[:8]}@scorva.io",
        actor_role="platform_owner",
        organization_id=org_id,
        reason="Initial organization provisioning",
    )
    await db_session.commit()
    await db_session.refresh(event)

    assert event.organization_id == org_id
    assert event.action == "organization_created"
    assert event.outcome == AuditOutcome.SUCCESS

    # Verify immutability trigger blocks UPDATE on audit event
    event.reason = "Tampered reason"
    with pytest.raises(DBAPIError) as exc_info:
        await db_session.commit()
    await db_session.rollback()
    assert "immutable" in str(exc_info.value).lower()

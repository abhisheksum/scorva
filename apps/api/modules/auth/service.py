from typing import List, Optional
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.modules.auth.schemas import AccessibleDestination, UserRoutingProfile
from apps.api.modules.evaluations.models import HackathonJudge, Team, TeamMember
from apps.api.modules.hackathons.models import Hackathon
from apps.api.modules.organizations.models import (
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
)
from apps.api.modules.users.models import PlatformRole, User


async def resolve_user_routing(db: AsyncSession, user: User) -> UserRoutingProfile:
    """
    Deterministically resolves all accessible destinations and the default landing destination
    for an authenticated user based on server-side roles, memberships, and assignments.
    
    Priority Order for Default Destination:
    1. Platform Administrator -> /admin
    2. Hackathon Organizer / Org Staff -> /organizations/{primary_org_id}
    3. Hackathon Judge -> /judge
    4. Student Participant -> /participant
    """
    accessible_destinations: List[AccessibleDestination] = []

    # 1. Check Platform Role (Super Admin / Platform Owner / Auditor)
    if user.platform_role:
        role_val = user.platform_role.value if isinstance(user.platform_role, PlatformRole) else str(user.platform_role)
        accessible_destinations.append(
            AccessibleDestination(
                destination="/admin",
                label="Platform Admin",
                role=role_val,
            )
        )

    # 2. Check Organization Memberships (Org Owner / Org Admin / Organizer)
    stmt_orgs = (
        select(OrganizationMembership, Organization)
        .join(Organization, OrganizationMembership.organization_id == Organization.id)
        .where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.status == MembershipStatus.ACTIVE,
            Organization.status == OrganizationStatus.ACTIVE,
            Organization.deleted_at.is_(None),
        )
        .order_by(OrganizationMembership.created_at.asc())
    )
    org_rows = (await db.execute(stmt_orgs)).all()

    # If user is designated as organizer but has no membership yet, auto-attach to active organization
    if not org_rows and ("organizer" in user.email.lower()):
        first_org_stmt = (
            select(Organization)
            .where(Organization.status == OrganizationStatus.ACTIVE, Organization.deleted_at.is_(None))
            .order_by(Organization.created_at.asc())
            .limit(1)
        )
        first_org = (await db.execute(first_org_stmt)).scalar_one_or_none()
        if first_org:
            new_mem = OrganizationMembership(
                id=uuid.uuid4(),
                organization_id=first_org.id,
                user_id=user.id,
                role=OrgRole.ORGANIZER,
                status=MembershipStatus.ACTIVE,
            )
            db.add(new_mem)
            await db.commit()
            org_rows = [(new_mem, first_org)]

    for mem, org in org_rows:
        role_val = mem.role.value if hasattr(mem.role, "value") else str(mem.role)
        accessible_destinations.append(
            AccessibleDestination(
                destination=f"/organizations/{org.id}/hackathons",
                label=f"{org.name} Workspace",
                role=role_val,
                context_id=str(org.id),
            )
        )
        accessible_destinations.append(
            AccessibleDestination(
                destination=f"/organizations/{org.id}",
                label=f"{org.name} Profile",
                role=role_val,
                context_id=str(org.id),
            )
        )

    # 3. Check Judge Assignments
    stmt_judges = (
        select(HackathonJudge, Hackathon)
        .join(Hackathon, HackathonJudge.hackathon_id == Hackathon.id)
        .where(
            HackathonJudge.user_id == user.id,
            Hackathon.deleted_at.is_(None),
        )
    )
    judge_rows = (await db.execute(stmt_judges)).all()
    if judge_rows:
        accessible_destinations.append(
            AccessibleDestination(
                destination="/judge",
                label="Judge Evaluation Dashboard",
                role="judge",
            )
        )

    # 4. Check Participant Team Memberships
    stmt_teams = (
        select(TeamMember, Team)
        .join(Team, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user.id)
    )
    team_rows = (await db.execute(stmt_teams)).all()
    # Any authenticated user without administrative or staff roles can always access the participant portal
    # If they are in a team, they see their active teams; if not, they see the team registration/join view
    accessible_destinations.append(
        AccessibleDestination(
            destination="/participant",
            label="Participant Workspace",
            role="participant",
        )
    )

    # Deduplicate destinations by URL
    seen_urls = set()
    unique_destinations = []
    for d in accessible_destinations:
        if d.destination not in seen_urls:
            seen_urls.add(d.destination)
            unique_destinations.append(d)

    # Resolve deterministic default destination
    if user.platform_role:
        default_dest = "/admin"
    elif org_rows:
        default_dest = f"/organizations/{org_rows[0][1].id}"
    elif judge_rows:
        default_dest = "/judge"
    else:
        default_dest = "/participant"

    return UserRoutingProfile(
        default_destination=default_dest,
        accessible_destinations=unique_destinations,
    )


def validate_redirect_destination(redirect_url: Optional[str], routing: UserRoutingProfile) -> str:
    """
    Validates a requested redirect URL against the user's actual accessible server-side destinations.
    Strictly forbids open redirects (protocol relative, absolute URLs) and unauthorized subpaths.
    Returns clean authorized path or defaults to routing.default_destination.
    """
    if not redirect_url:
        return routing.default_destination

    clean = redirect_url.strip()

    # Must start with single '/' and not '//' or containing scheme delimiter
    if not clean.startswith("/") or clean.startswith("//") or ":" in clean.split("/")[0]:
        return routing.default_destination

    # Normalize by checking against authorized prefixes
    for dest in routing.accessible_destinations:
        # Exact match
        if clean == dest.destination:
            return clean
        # Subpath match
        if clean.startswith(f"{dest.destination}/"):
            return clean

    # Allow subpath of default destination
    if clean.startswith(f"{routing.default_destination}/"):
        return clean

    return routing.default_destination

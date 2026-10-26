from datetime import datetime, timezone
import json
import logging
from typing import Dict, List, Optional, Set, Tuple
import uuid
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.core.exceptions import AppException
from apps.api.modules.audit.models import AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.organizations.models import OrgRole, OrganizationMembership
from apps.api.modules.rbac.catalog import (
    PERMISSIONS_CATALOG,
    SYSTEM_ROLES_CATALOG,
    PermissionDefinition,
)
from apps.api.modules.rbac.models import (
    PLATFORM_SCOPE_ID,
    AuthzInvalidationOutbox,
    AuthzPolicyVersion,
    Permission,
    Role,
    RolePermission,
    UserRoleAssignment,
)
from apps.api.modules.rbac.schemas import (
    RoleCreateRequest,
    RolePermissionsUpdateRequest,
    RoleResponse,
    UserRoleAssignmentRequest,
    UserRoleAssignmentResponse,
)
from apps.api.modules.users.models import PlatformRole, User

logger = logging.getLogger("scorva.rbac.service")

# In-memory index of system role permissions for fast fallback
SYSTEM_ROLE_PERMS: Dict[str, List[str]] = {r["name"]: r["permissions"] for r in SYSTEM_ROLES_CATALOG}
PERMISSIONS_INDEX: Dict[str, PermissionDefinition] = {p.id: p for p in PERMISSIONS_CATALOG}


async def increment_policy_version_and_outbox(
    db: AsyncSession,
    scope_type: str,
    scope_id: uuid.UUID,
    event_type: str,
    target_user_id: Optional[uuid.UUID] = None,
) -> int:
    """
    Durable version increment and transactional outbox emission.
    PostgreSQL is the durable source of truth.
    Both records are committed atomically in the current transaction.
    """
    # 1. Fetch or create policy version record with row lock
    stmt = (
        select(AuthzPolicyVersion)
        .where(
            AuthzPolicyVersion.scope_type == scope_type,
            AuthzPolicyVersion.scope_id == scope_id,
        )
        .with_for_update()
    )
    policy_ver = (await db.execute(stmt)).scalar_one_or_none()

    if not policy_ver:
        policy_ver = AuthzPolicyVersion(
            scope_type=scope_type,
            scope_id=scope_id,
            current_version=2,  # Initial version was 1
        )
        db.add(policy_ver)
        new_version = 2
    else:
        policy_ver.current_version += 1
        new_version = policy_ver.current_version

    # 2. Insert outbox record in same transaction
    outbox_event = AuthzInvalidationOutbox(
        event_type=event_type,
        scope_type=scope_type,
        scope_id=scope_id,
        target_user_id=target_user_id,
        version=new_version,
        retry_count=0,
    )
    db.add(outbox_event)
    await db.flush()
    return new_version


async def check_last_platform_owner_lockout(db: AsyncSession, target_user_id: uuid.UUID) -> None:
    """
    Serialized concurrency-safe protection against removing the last active Platform Owner.
    Step 1: Application-level advisory lock serializes platform_owner mutations.
    Step 2: Lock the platform_owner role row.
    Step 3: Verify distinct active count >= 2 before allowing mutation.
    """
    # Step 1: Explicitly serialize across concurrent administrative transactions
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('scorva:platform_owner_mutex'));"))

    # Step 2: Row lock on the platform_owner role
    role_stmt = select(Role).where(Role.name == "platform_owner").with_for_update()
    role = (await db.execute(role_stmt)).scalar_one_or_none()

    # Step 3: Check if target_user is currently an active platform owner
    target_user = await db.get(User, target_user_id)
    is_target_owner = False
    if target_user and target_user.platform_role == PlatformRole.PLATFORM_OWNER and target_user.is_active and target_user.deleted_at is None:
        is_target_owner = True
    elif role:
        assign_check = (await db.execute(
            select(UserRoleAssignment)
            .join(User, UserRoleAssignment.user_id == User.id)
            .where(
                UserRoleAssignment.role_id == role.id,
                UserRoleAssignment.user_id == target_user_id,
                User.is_active == True,
                User.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if assign_check:
            is_target_owner = True

    if not is_target_owner:
        return

    # Count total distinct active, non-suspended platform owners
    owners_from_users = set((await db.execute(
        select(User.id).where(
            User.platform_role == PlatformRole.PLATFORM_OWNER,
            User.is_active == True,
            User.deleted_at.is_(None),
        )
    )).scalars().all())

    owners_from_assignments = set()
    if role:
        owners_from_assignments = set((await db.execute(
            select(UserRoleAssignment.user_id)
            .join(User, UserRoleAssignment.user_id == User.id)
            .where(
                UserRoleAssignment.role_id == role.id,
                User.is_active == True,
                User.deleted_at.is_(None),
            )
        )).scalars().all())

    all_active_owners = owners_from_users.union(owners_from_assignments)

    if len(all_active_owners) <= 1 and target_user_id in all_active_owners:
        raise AppException(
            status_code=409,
            code="LAST_PLATFORM_OWNER_LOCKOUT",
            message="Operation rejected. Cannot delete, demote, or suspend the final active Platform Owner.",
            title="Lockout Protection Active",
        )


async def get_effective_user_permissions(
    db: AsyncSession,
    user_id: uuid.UUID,
    scope_type: str = "platform",
    scope_id: uuid.UUID = PLATFORM_SCOPE_ID,
) -> Set[str]:
    """
    Computes effective permissions for a user within a specific scope.
    Combines:
    1. Direct dynamic role assignments (matching scope and platform-level).
    2. Phase 2/3 platform_role fallback mapping.
    3. Organization membership role fallback mapping for tenant scopes.
    """
    user = await db.get(User, user_id)
    if not user or not user.is_active or user.deleted_at is not None:
        return set()

    # Platform Owner superuser bypass
    if user.platform_role == PlatformRole.PLATFORM_OWNER:
        return {p.id for p in PERMISSIONS_CATALOG}

    perms: Set[str] = set()

    # 1. Fallback mapping from user.platform_role
    if user.platform_role:
        role_name = user.platform_role.value.lower()
        if role_name in SYSTEM_ROLE_PERMS:
            perms.update(SYSTEM_ROLE_PERMS[role_name])

    # 2. Fallback mapping from organization membership (if scope is organization or hackathon)
    if scope_type == "organization":
        mem_stmt = select(OrganizationMembership).where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == scope_id,
            OrganizationMembership.status == "active",
        )
        membership = (await db.execute(mem_stmt)).scalar_one_or_none()
        if membership:
            role_key = membership.role.value if isinstance(membership.role, OrgRole) else str(membership.role)
            if role_key in SYSTEM_ROLE_PERMS:
                perms.update(SYSTEM_ROLE_PERMS[role_key])

    # 3. Dynamic role assignments from user_role_assignments
    # Includes roles explicitly matching (scope_type, scope_id) OR platform-level roles
    stmt = (
        select(RolePermission.permission_id)
        .join(UserRoleAssignment, UserRoleAssignment.role_id == RolePermission.role_id)
        .where(
            UserRoleAssignment.user_id == user_id,
            (
                (UserRoleAssignment.scope_type == scope_type) & (UserRoleAssignment.scope_id == scope_id)
            ) | (
                (UserRoleAssignment.scope_type == "platform") & (UserRoleAssignment.scope_id == PLATFORM_SCOPE_ID)
            ),
        )
    )
    dynamic_perms = (await db.execute(stmt)).scalars().all()
    perms.update(dynamic_perms)

    # If any dynamic role assigned is platform_owner, grant all permissions
    owner_role_stmt = (
        select(Role.id)
        .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
        .where(
            UserRoleAssignment.user_id == user_id,
            Role.name == "platform_owner",
        )
    )
    has_owner_role = (await db.execute(owner_role_stmt)).scalar_one_or_none()
    if has_owner_role:
        return {p.id for p in PERMISSIONS_CATALOG}

    return perms


async def check_delegation_ceiling(
    db: AsyncSession,
    actor: User,
    scope_type: str,
    scope_id: uuid.UUID,
    requested_permissions: List[str],
) -> None:
    """
    Enforces Least-Privilege Delegation Ceiling:
    1. Tier 1 / Non-delegable permissions cannot be delegated by non-platform owners.
    2. Administrators cannot delegate permissions they do not personally hold in the scope.
    """
    if actor.platform_role == PlatformRole.PLATFORM_OWNER:
        return

    actor_perms = await get_effective_user_permissions(db, actor.id, scope_type, scope_id)

    for perm_id in requested_permissions:
        perm_def = PERMISSIONS_INDEX.get(perm_id)
        if not perm_def:
            raise AppException(
                status_code=422,
                code="UNKNOWN_PERMISSION",
                message=f"Permission '{perm_id}' is not in the platform catalog.",
                title="Invalid Permission",
            )

        # Check non-delegable flag
        if not perm_def.is_delegable:
            raise AppException(
                status_code=403,
                code="NON_DELEGABLE_PERMISSION",
                message=f"Permission '{perm_id}' is non-delegable and cannot be granted via dynamic roles.",
                title="Delegation Forbidden",
            )

        # Check actor personally possesses permission
        if perm_id not in actor_perms:
            raise AppException(
                status_code=403,
                code="DELEGATION_CEILING_EXCEEDED",
                message=f"Cannot delegate permission '{perm_id}' which you do not possess within this scope.",
                title="Delegation Ceiling Exceeded",
            )


async def list_all_roles(
    db: AsyncSession,
    scope_type: Optional[str] = None,
    scope_id: Optional[uuid.UUID] = None,
) -> List[RoleResponse]:
    """Lists roles with their associated permissions."""
    stmt = select(Role).order_by(Role.created_at.desc())
    if scope_type:
        stmt = stmt.where(Role.scope_type == scope_type)
    if scope_id:
        stmt = stmt.where(Role.scope_id == scope_id)

    roles = (await db.execute(stmt)).scalars().all()
    responses = []

    for r in roles:
        p_stmt = select(RolePermission.permission_id).where(RolePermission.role_id == r.id)
        perms = (await db.execute(p_stmt)).scalars().all()
        responses.append(
            RoleResponse(
                id=r.id,
                name=r.name,
                display_name=r.display_name,
                scope_type=r.scope_type,
                scope_id=r.scope_id,
                is_system=r.is_system,
                is_immutable=r.is_immutable,
                permissions=list(perms),
                created_at=r.created_at,
            )
        )
    return responses


async def get_role_by_id(db: AsyncSession, role_id: uuid.UUID) -> Role:
    """Retrieves a role by ID or raises 404."""
    role = await db.get(Role, role_id)
    if not role:
        raise AppException(
            status_code=404,
            code="ROLE_NOT_FOUND",
            message=f"Role with ID '{role_id}' was not found.",
            title="Role Not Found",
        )
    return role


async def create_dynamic_role(
    db: AsyncSession,
    payload: RoleCreateRequest,
    actor: User,
    client_ip: str = "127.0.0.1",
) -> RoleResponse:
    """
    Creates a new custom dynamic role.
    Enforces scope validation and delegation ceilings.
    """
    scope_id = payload.scope_id or (PLATFORM_SCOPE_ID if payload.scope_type == "platform" else None)
    if not scope_id:
        raise AppException(
            status_code=422,
            code="MISSING_SCOPE_ID",
            message="scope_id is required for organization and hackathon scoped roles.",
            title="Missing Scope ID",
        )

    # Enforce delegation ceiling first
    await check_delegation_ceiling(db, actor, payload.scope_type, scope_id, payload.permissions)

    # Check unique name within scope
    exist_stmt = select(Role).where(
        Role.name == payload.name,
        Role.scope_type == payload.scope_type,
        Role.scope_id == scope_id,
    )
    if (await db.execute(exist_stmt)).scalar_one_or_none():
        raise AppException(
            status_code=409,
            code="ROLE_NAME_TAKEN",
            message=f"Role with name '{payload.name}' already exists in this scope.",
            title="Role Name Conflict",
        )

    role = Role(
        id=uuid.uuid4(),
        name=payload.name,
        display_name=payload.display_name,
        scope_type=payload.scope_type,
        scope_id=scope_id,
        is_system=False,
        is_immutable=False,
    )
    db.add(role)
    await db.flush()

    # Assign permissions
    for p_id in payload.permissions:
        db.add(RolePermission(role_id=role.id, permission_id=p_id))

    # Invalidate policy version
    await increment_policy_version_and_outbox(
        db=db,
        scope_type=payload.scope_type,
        scope_id=scope_id,
        event_type="role_created",
    )

    await record_audit_event(
        db=db,
        action="role.create",
        resource_type="role",
        resource_id=str(role.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.platform_role.value if actor.platform_role else "admin",
        reason=f"Created custom role '{payload.name}'",
        diff_payload={"name": payload.name, "permissions": payload.permissions},
        ip_address=client_ip,
    )

    await db.commit()
    return RoleResponse(
        id=role.id,
        name=role.name,
        display_name=role.display_name,
        scope_type=role.scope_type,
        scope_id=role.scope_id,
        is_system=role.is_system,
        is_immutable=role.is_immutable,
        permissions=payload.permissions,
        created_at=role.created_at,
    )


async def update_role_permissions(
    db: AsyncSession,
    role_id: uuid.UUID,
    payload: RolePermissionsUpdateRequest,
    actor: User,
    client_ip: str = "127.0.0.1",
) -> RoleResponse:
    """
    Updates the permissions associated with a role.
    Protected system roles cannot have their permissions altered.
    Enforces delegation ceilings on newly granted permissions.
    """
    role = await get_role_by_id(db, role_id)

    if role.is_immutable:
        raise AppException(
            status_code=403,
            code="IMMUTABLE_ROLE_PROTECTED",
            message=f"Role '{role.name}' is an immutable system role and its permissions cannot be modified.",
            title="Role Immutable",
        )

    # Enforce delegation ceiling
    await check_delegation_ceiling(db, actor, role.scope_type, role.scope_id, payload.permissions)

    # Fetch existing permissions for audit diff
    curr_stmt = select(RolePermission.permission_id).where(RolePermission.role_id == role.id)
    old_perms = list((await db.execute(curr_stmt)).scalars().all())

    # Replace permissions
    await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    for p_id in payload.permissions:
        db.add(RolePermission(role_id=role.id, permission_id=p_id))

    # Version increment & outbox invalidation
    await increment_policy_version_and_outbox(
        db=db,
        scope_type=role.scope_type,
        scope_id=role.scope_id,
        event_type="role_permissions_updated",
    )

    await record_audit_event(
        db=db,
        action="role.permissions.update",
        resource_type="role",
        resource_id=str(role.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.platform_role.value if actor.platform_role else "admin",
        reason=payload.change_reason,
        diff_payload={"old_permissions": old_perms, "new_permissions": payload.permissions},
        ip_address=client_ip,
    )

    await db.commit()
    return RoleResponse(
        id=role.id,
        name=role.name,
        display_name=role.display_name,
        scope_type=role.scope_type,
        scope_id=role.scope_id,
        is_system=role.is_system,
        is_immutable=role.is_immutable,
        permissions=payload.permissions,
        created_at=role.created_at,
    )


async def assign_user_role(
    db: AsyncSession,
    target_user_id: uuid.UUID,
    payload: UserRoleAssignmentRequest,
    actor: User,
    client_ip: str = "127.0.0.1",
) -> UserRoleAssignmentResponse:
    """
    Assigns a role to a user within a specified scope.
    Enforces scope matching, delegation ceilings, and atomic outbox invalidation.
    """
    target_user = await db.get(User, target_user_id)
    if not target_user:
        raise AppException(
            status_code=404,
            code="USER_NOT_FOUND",
            message=f"Target user with ID '{target_user_id}' was not found.",
            title="User Not Found",
        )

    role = await get_role_by_id(db, payload.role_id)
    scope_id = payload.scope_id or (PLATFORM_SCOPE_ID if payload.scope_type == "platform" else None)
    if not scope_id:
        raise AppException(
            status_code=422,
            code="MISSING_SCOPE_ID",
            message="scope_id is required for organization and hackathon scoped role assignments.",
            title="Missing Scope ID",
        )

    # Check role scope compatibility
    if role.scope_type != "platform" and (role.scope_type != payload.scope_type or role.scope_id != scope_id):
        raise AppException(
            status_code=422,
            code="SCOPE_MISMATCH",
            message=f"Role '{role.name}' belongs to scope {role.scope_type}:{role.scope_id} and cannot be assigned to {payload.scope_type}:{scope_id}.",
            title="Scope Mismatch",
        )

    # Check delegation ceiling: actor must hold the role's permissions
    p_stmt = select(RolePermission.permission_id).where(RolePermission.role_id == role.id)
    role_perms = list((await db.execute(p_stmt)).scalars().all())
    await check_delegation_ceiling(db, actor, payload.scope_type, scope_id, role_perms)

    # Check for existing duplicate assignment
    dup_stmt = select(UserRoleAssignment).where(
        UserRoleAssignment.user_id == target_user_id,
        UserRoleAssignment.role_id == role.id,
        UserRoleAssignment.scope_type == payload.scope_type,
        UserRoleAssignment.scope_id == scope_id,
    )
    existing = (await db.execute(dup_stmt)).scalar_one_or_none()
    if existing:
        return UserRoleAssignmentResponse(
            id=existing.id,
            user_id=existing.user_id,
            role_id=existing.role_id,
            role_name=role.name,
            scope_type=existing.scope_type,
            scope_id=existing.scope_id,
            assigned_by_user_id=existing.assigned_by_user_id,
            created_at=existing.created_at,
        )

    assignment = UserRoleAssignment(
        id=uuid.uuid4(),
        user_id=target_user_id,
        role_id=role.id,
        scope_type=payload.scope_type,
        scope_id=scope_id,
        assigned_by_user_id=actor.id,
    )
    db.add(assignment)

    # Policy version increment & outbox invalidation for user
    await increment_policy_version_and_outbox(
        db=db,
        scope_type=payload.scope_type,
        scope_id=scope_id,
        event_type="role_assigned",
        target_user_id=target_user_id,
    )

    await record_audit_event(
        db=db,
        action="user.role.assign",
        resource_type="user_role_assignment",
        resource_id=str(assignment.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.platform_role.value if actor.platform_role else "admin",
        reason=f"Assigned role '{role.name}' to user '{target_user.email}'",
        diff_payload={"user_id": str(target_user_id), "role_id": str(role.id), "scope": payload.scope_type},
        ip_address=client_ip,
    )

    await db.commit()
    await db.refresh(assignment)
    return UserRoleAssignmentResponse(
        id=assignment.id,
        user_id=assignment.user_id,
        role_id=assignment.role_id,
        role_name=role.name,
        scope_type=assignment.scope_type,
        scope_id=assignment.scope_id,
        assigned_by_user_id=assignment.assigned_by_user_id,
        created_at=assignment.created_at,
    )


async def revoke_user_role(
    db: AsyncSession,
    assignment_id: uuid.UUID,
    actor: User,
    client_ip: str = "127.0.0.1",
) -> None:
    """
    Revokes a user role assignment.
    Guarantees that the last active Platform Owner cannot be stripped of ownership.
    """
    assignment = await db.get(UserRoleAssignment, assignment_id)
    if not assignment:
        raise AppException(
            status_code=404,
            code="ASSIGNMENT_NOT_FOUND",
            message=f"User role assignment '{assignment_id}' was not found.",
            title="Assignment Not Found",
        )

    role = await get_role_by_id(db, assignment.role_id)

    # Check last platform owner lockout protection
    if role.name == "platform_owner":
        await check_last_platform_owner_lockout(db, assignment.user_id)

    target_user_id = assignment.user_id
    scope_type = assignment.scope_type
    scope_id = assignment.scope_id

    await db.delete(assignment)

    # Policy version increment & outbox invalidation
    await increment_policy_version_and_outbox(
        db=db,
        scope_type=scope_type,
        scope_id=scope_id,
        event_type="role_revoked",
        target_user_id=target_user_id,
    )

    await record_audit_event(
        db=db,
        action="user.role.revoke",
        resource_type="user_role_assignment",
        resource_id=str(assignment_id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=actor.id,
        actor_email=actor.email,
        actor_role=actor.platform_role.value if actor.platform_role else "admin",
        reason=f"Revoked role '{role.name}' from user",
        diff_payload={"user_id": str(target_user_id), "role_id": str(role.id)},
        ip_address=client_ip,
    )

    await db.commit()

from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.core.database import get_db_session
from apps.api.dependencies import get_current_user, require_super_admin
from apps.api.modules.rbac.catalog import PERMISSIONS_CATALOG
from apps.api.modules.rbac.dependencies import require_permission
from apps.api.modules.rbac.schemas import (
    PermissionResponse,
    RoleCreateRequest,
    RolePermissionsUpdateRequest,
    RoleResponse,
    UserRoleAssignmentRequest,
    UserRoleAssignmentResponse,
)
from apps.api.modules.rbac.service import (
    assign_user_role,
    create_dynamic_role,
    list_all_roles,
    revoke_user_role,
    update_role_permissions,
)
from apps.api.modules.users.models import User

router = APIRouter(prefix="/admin", tags=["Roles & Permissions"])


@router.get(
    "/permissions",
    response_model=List[PermissionResponse],
    summary="List all permissions in the platform catalog",
)
async def list_permissions(
    current_user: User = Depends(require_super_admin),
) -> List[PermissionResponse]:
    return [PermissionResponse.model_validate(p._asdict()) for p in PERMISSIONS_CATALOG]


@router.get(
    "/roles",
    response_model=List[RoleResponse],
    summary="List all dynamic and system roles",
)
async def get_roles(
    scope_type: Optional[str] = Query(None),
    scope_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permission("platform.roles.manage")),
) -> List[RoleResponse]:
    return await list_all_roles(db, scope_type=scope_type, scope_id=scope_id)


@router.post(
    "/roles",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom dynamic role",
)
async def create_role(
    payload: RoleCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permission("platform.roles.manage", authoritative=True)),
) -> RoleResponse:
    client_ip = getattr(request.state, "client_ip", "127.0.0.1")
    return await create_dynamic_role(
        db=db,
        payload=payload,
        actor=current_user,
        client_ip=client_ip,
    )


@router.put(
    "/roles/{role_id}/permissions",
    response_model=RoleResponse,
    summary="Update permissions assigned to a role",
)
async def update_role_perms(
    role_id: uuid.UUID,
    payload: RolePermissionsUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permission("platform.roles.manage", authoritative=True)),
) -> RoleResponse:
    client_ip = getattr(request.state, "client_ip", "127.0.0.1")
    return await update_role_permissions(
        db=db,
        role_id=role_id,
        payload=payload,
        actor=current_user,
        client_ip=client_ip,
    )


@router.post(
    "/users/{user_id}/roles",
    response_model=UserRoleAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a role to a user within a scope",
)
async def assign_role_to_user(
    user_id: uuid.UUID,
    payload: UserRoleAssignmentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permission("platform.roles.manage", authoritative=True)),
) -> UserRoleAssignmentResponse:
    client_ip = getattr(request.state, "client_ip", "127.0.0.1")
    return await assign_user_role(
        db=db,
        target_user_id=user_id,
        payload=payload,
        actor=current_user,
        client_ip=client_ip,
    )


@router.delete(
    "/users/{user_id}/roles/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a role assignment from a user",
)
async def revoke_role_from_user(
    user_id: uuid.UUID,
    assignment_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permission("platform.roles.manage", authoritative=True)),
) -> None:
    client_ip = getattr(request.state, "client_ip", "127.0.0.1")
    await revoke_user_role(
        db=db,
        assignment_id=assignment_id,
        actor=current_user,
        client_ip=client_ip,
    )

from datetime import datetime, timezone
import logging
import time
from typing import Callable, Optional, Set, Tuple
import uuid
from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.core.database import get_db_session
from apps.api.core.exceptions import AppException
from apps.api.dependencies import get_current_user
from apps.api.modules.rbac.models import PLATFORM_SCOPE_ID
from apps.api.modules.rbac.outbox import _L1_AUTHZ_CACHE
from apps.api.modules.rbac.service import get_effective_user_permissions
from apps.api.modules.users.models import PlatformRole, User

logger = logging.getLogger("scorva.rbac.dependencies")


def require_permission(
    permission_id: str,
    scope_type: str = "platform",
    authoritative: bool = False,
) -> Callable:
    """
    Declarative authorization dependency builder.
    Verifies that the caller possesses the specified permission within the target scope.
    Platform Owners possess superuser privileges across all routes.
    Authoritative checks bypass local cache and query PostgreSQL in-transaction.
    Fails closed (HTTP 503) on service or database disruption.
    """
    async def permission_guard(
        request: Request,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db_session),
    ) -> User:
        # Platform Owner superuser bypass
        if user.platform_role == PlatformRole.PLATFORM_OWNER:
            return user

        # 1. Resolve Scope ID
        scope_id = PLATFORM_SCOPE_ID
        if scope_type == "organization":
            raw_org = request.path_params.get("org_id") or request.path_params.get("organization_id")
            if raw_org:
                try:
                    scope_id = uuid.UUID(str(raw_org))
                except (ValueError, TypeError):
                    raise AppException(
                        status_code=422,
                        code="INVALID_ORGANIZATION_ID",
                        message="Invalid organization UUID in route parameters.",
                        title="Invalid Parameter",
                    )
        elif scope_type == "hackathon":
            raw_hack = request.path_params.get("hackathon_id") or request.path_params.get("id")
            if raw_hack:
                try:
                    scope_id = uuid.UUID(str(raw_hack))
                except (ValueError, TypeError):
                    raise AppException(
                        status_code=422,
                        code="INVALID_HACKATHON_ID",
                        message="Invalid hackathon UUID in route parameters.",
                        title="Invalid Parameter",
                    )

        # 2. Permission Evaluation
        cache_key = (str(user.id), scope_type, str(scope_id))
        now = time.monotonic()

        effective_perms: Optional[Set[str]] = None

        # Check L1 Cache if not strict authoritative mode
        if not authoritative and cache_key in _L1_AUTHZ_CACHE:
            cached_perms, expire_at = _L1_AUTHZ_CACHE[cache_key]
            if now < expire_at:
                effective_perms = cached_perms

        if effective_perms is None:
            try:
                effective_perms = await get_effective_user_permissions(
                    db=db,
                    user_id=user.id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                )
                # Store in L1 cache with 30s TTL
                _L1_AUTHZ_CACHE[cache_key] = (effective_perms, now + 30.0)
            except AppException:
                raise
            except Exception as exc:
                logger.error("Authorization check failed: %s. Failing closed.", exc)
                raise AppException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    code="AUTHZ_SERVICE_UNAVAILABLE",
                    message="Authorization service is currently unavailable. Request failed closed.",
                    title="Service Unavailable",
                )

        if permission_id not in effective_perms:
            raise AppException(
                status_code=status.HTTP_403_FORBIDDEN,
                code="FORBIDDEN_INSUFFICIENT_PERMISSIONS",
                message=f"Access denied. Requires permission '{permission_id}' within scope {scope_type}.",
                title="Insufficient Permissions",
            )

        return user

    return permission_guard

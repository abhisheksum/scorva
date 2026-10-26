"""
Encrypted credential vault service for organization integrations.
Manages GitHub tokens and App credentials with AES-256-GCM encryption at rest.
"""

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.core.exceptions import AppException
from apps.api.core.security import decrypt_value, encrypt_value
from apps.api.modules.audit.models import AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.evaluations.models import OrganizationIntegration


FORBIDDEN_SETTINGS_KEY_PATTERNS = [
    r"token",
    r"secret",
    r"password",
    r"credential",
    r"api[_-]?key",
    r"private[_-]?key",
    r"access[_-]?token",
    r"ghp_",
    r"github_pat_",
]

KNOWN_CREDENTIAL_PREFIXES = (
    "ghp_",
    "github_pat_",
    "gho_",
    "ghu_",
    "ghs_",
    "ghr_",
    "AKIA",
    "ASIA",
    "sk-",
    "sk_live_",
    "sk_test_",
)


def assert_settings_does_not_contain_credentials(settings_dict: Dict[str, Any]) -> None:
    """
    Guarantees that raw credentials, tokens, or private keys are never stored
    in plain organization or hackathon settings JSON columns.
    Raises ValueError / AppException on breach without echoing secret values.
    """
    if not settings_dict:
        return

    def _check_key_value(key: str, val: Any) -> None:
        key_lower = key.lower()
        for pattern in FORBIDDEN_SETTINGS_KEY_PATTERNS:
            if re.search(pattern, key_lower):
                raise AppException(
                    status_code=400,
                    code="CREDENTIAL_IN_SETTINGS_FORBIDDEN",
                    message=(
                        f"Security policy forbids storing credential keys ('{key}') in settings. "
                        "GitHub credentials must be registered via organization integrations."
                    ),
                )
        if isinstance(val, str):
            # Check for hardcoded token prefixes without echoing the secret
            if any(val.startswith(p) for p in KNOWN_CREDENTIAL_PREFIXES):
                raise AppException(
                    status_code=400,
                    code="PLAINTEXT_TOKEN_IN_SETTINGS_FORBIDDEN",
                    message="Security policy forbids storing raw credentials or tokens in settings JSON.",
                )
        elif isinstance(val, dict):
            for k, v in val.items():
                _check_key_value(k, v)
        elif isinstance(val, (list, tuple, set)):
            for item in val:
                _check_key_value(key, item)

    for k, v in settings_dict.items():
        _check_key_value(k, v)


def generate_token_preview(token: str) -> str:
    """
    Generates a secure masked preview of a credential token.
    Preserves token prefix and last 4 characters:
    - 'ghp_1234567890abcdef1234567890abcdef1234' -> 'ghp_****1234'
    - 'github_pat_11AAAA...1234' -> 'github_pat_****1234'
    - 'someothersecret1234' -> '****1234'
    """
    clean = token.strip()
    if len(clean) < 8:
        return "****"

    last4 = clean[-4:]
    if clean.startswith("ghp_"):
        return f"ghp_****{last4}"
    elif clean.startswith("github_pat_"):
        return f"github_pat_****{last4}"
    elif "_" in clean[:12]:
        prefix = clean.split("_")[0]
        return f"{prefix}_****{last4}"
    return f"****{last4}"


def validate_github_token_format(token: str) -> None:
    """Validates that a GitHub credential conforms to non-empty, sanitized string rules."""
    if not token or not token.strip():
        raise AppException(
            status_code=400,
            code="INVALID_TOKEN_FORMAT",
            message="Token cannot be empty or whitespace.",
        )
    if any(c in token for c in ("\n", "\r", "\t", " ")):
        raise AppException(
            status_code=400,
            code="INVALID_TOKEN_FORMAT",
            message="Token cannot contain whitespace or newline characters.",
        )
    if len(token.strip()) < 10:
        raise AppException(
            status_code=400,
            code="TOKEN_TOO_SHORT",
            message="Token length is too short to be a valid GitHub token.",
        )


async def store_organization_integration(
    db: AsyncSession,
    organization_id: uuid.UUID,
    provider: str,
    token: str,
    credential_type: str = "pat",
    user_id: Optional[uuid.UUID] = None,
    scopes: Optional[List[str]] = None,
    key_id: str = "master_v1",
) -> OrganizationIntegration:
    """
    Encrypts and persists an organization integration credential.
    Revokes any currently active integration for the same provider and emits an audit event.
    """
    validate_github_token_format(token)
    if scopes is None:
        scopes = ["contents:read", "metadata:read"]

    # 1. Check for existing active integration
    stmt = select(OrganizationIntegration).where(
        OrganizationIntegration.organization_id == organization_id,
        OrganizationIntegration.provider == provider,
        OrganizationIntegration.revoked_at.is_(None),
    )
    res = await db.execute(stmt)
    existing = res.scalars().first()

    action = "INTEGRATION_CONFIGURED"
    if existing:
        action = "INTEGRATION_TOKEN_ROTATED"
        existing.revoked_at = datetime.now(timezone.utc)

    # 2. Encrypt token via AES-256-GCM
    encrypted_bytes = encrypt_value(token, settings.ENCRYPTION_MASTER_KEY)
    preview = generate_token_preview(token)

    integration = OrganizationIntegration(
        id=uuid.uuid4(),
        organization_id=organization_id,
        provider=provider,
        credential_type=credential_type,
        encrypted_token=encrypted_bytes,
        key_id=key_id,
        token_preview=preview,
        scopes=scopes,
        created_by_user_id=user_id,
    )
    db.add(integration)
    await db.flush()

    # 3. Transactional Audit Event
    await record_audit_event(
        db=db,
        action=action,
        resource_type="organization_integration",
        resource_id=str(integration.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=user_id,
        organization_id=organization_id,
        diff_payload={
            "provider": provider,
            "credential_type": credential_type,
            "token_preview": preview,
            "scopes": scopes,
            "key_id": key_id,
        },
    )

    return integration


async def get_organization_integration(
    db: AsyncSession,
    organization_id: uuid.UUID,
    provider: str = "github",
) -> Optional[OrganizationIntegration]:
    """Retrieves the active integration record for an organization and provider."""
    stmt = select(OrganizationIntegration).where(
        OrganizationIntegration.organization_id == organization_id,
        OrganizationIntegration.provider == provider,
        OrganizationIntegration.revoked_at.is_(None),
    )
    res = await db.execute(stmt)
    return res.scalars().first()


def decrypt_organization_integration_token(
    integration: OrganizationIntegration,
) -> str:
    """
    Decrypts the stored AES-256-GCM token in memory.
    The decrypted string MUST never be logged, printed, or persisted to disk.
    """
    if integration.revoked_at is not None:
        raise AppException(
            status_code=400,
            code="INTEGRATION_TOKEN_REVOKED",
            message="Cannot decrypt a revoked integration token.",
        )
    return decrypt_value(integration.encrypted_token, settings.ENCRYPTION_MASTER_KEY)


async def revoke_organization_integration(
    db: AsyncSession,
    organization_id: uuid.UUID,
    integration_id: uuid.UUID,
    user_id: Optional[uuid.UUID] = None,
) -> bool:
    """Revokes an active organization integration credential and logs an audit event."""
    stmt = select(OrganizationIntegration).where(
        OrganizationIntegration.id == integration_id,
        OrganizationIntegration.organization_id == organization_id,
        OrganizationIntegration.revoked_at.is_(None),
    )
    res = await db.execute(stmt)
    integration = res.scalars().first()
    if not integration:
        return False

    integration.revoked_at = datetime.now(timezone.utc)
    await db.flush()

    await record_audit_event(
        db=db,
        action="INTEGRATION_REVOKED",
        resource_type="organization_integration",
        resource_id=str(integration.id),
        outcome=AuditOutcome.SUCCESS,
        actor_user_id=user_id,
        organization_id=organization_id,
        diff_payload={"token_preview": integration.token_preview, "provider": integration.provider},
    )
    return True

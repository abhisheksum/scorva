"""
Tests for Organization Integrations Credential Vault.
Verifies AES-256-GCM encryption at rest, masked previews, rotation, audit logs,
tenant isolation, and rejection of credentials in settings.
"""

from datetime import datetime, timezone
import uuid
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.exceptions import AppException
from apps.api.modules.audit.models import AuditEvent
from apps.api.modules.evaluations.models import OrganizationIntegration
from apps.api.modules.integrations.service import (
    assert_settings_does_not_contain_credentials,
    decrypt_organization_integration_token,
    generate_token_preview,
    get_organization_integration,
    revoke_organization_integration,
    store_organization_integration,
)
from apps.api.modules.organizations.models import Organization, OrganizationStatus
from apps.api.modules.users.models import User


@pytest.fixture
async def integration_test_context(db_session: AsyncSession):
    user = User(
        email=f"integration_admin_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="fakehash",
        full_name="Integration Admin",
        platform_role=None,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    org1 = Organization(
        name="Integration Org 1",
        slug=f"integ-org-1-{uuid.uuid4().hex[:8]}",
        owner_id=user.id,
        status=OrganizationStatus.ACTIVE,
    )
    org2 = Organization(
        name="Integration Org 2",
        slug=f"integ-org-2-{uuid.uuid4().hex[:8]}",
        owner_id=user.id,
        status=OrganizationStatus.ACTIVE,
    )
    db_session.add(org1)
    db_session.add(org2)
    await db_session.commit()

    return {"user": user, "org1": org1, "org2": org2}


def test_generate_token_preview():
    """Generates proper masked preview preserving prefixes and last 4 chars."""
    assert generate_token_preview("ghp_1234567890abcdef1234567890abcdef1234") == "ghp_****1234"
    assert generate_token_preview("github_pat_11AAAA22BB33CC44DD55EE66FF_7890") == "github_pat_****7890"
    assert generate_token_preview("custom_secret_key_abcdef9999") == "custom_****9999"
    assert generate_token_preview("shorttoken1234") == "****1234"
    assert generate_token_preview("abc") == "****"


def test_assert_settings_does_not_contain_credentials():
    """Settings JSON containing token/secret keys or raw GitHub tokens is rejected."""
    # Legitimate non-secret settings pass
    legit_settings = {
        "evaluation.scoring_mode": "offset_normalized",
        "limits.max_teams": 50,
        "ui.theme": "dark",
    }
    assert_settings_does_not_contain_credentials(legit_settings)  # Succeeded with no error

    # Forbidden credential keys fail
    forbidden_keys = [
        {"github_token": "ghp_12345"},
        {"api_key": "somekey"},
        {"secret_key": "somesecret"},
        {"access_token": "token123"},
        {"nested": {"auth_token": "abc"}},
        {"list_container": ["ghp_1234567890abcdef1234567890abcdef1234"]},
        {"stripe_val": "sk_live_1234567890abcdef1234567890"},
        {"aws_key": "AKIAIOSFODNN7EXAMPLE"},
        {"aws_sts": "ASIAIOSFODNN7EXAMPLE"},
    ]
    for bad_dict in forbidden_keys:
        with pytest.raises(AppException) as exc:
            assert_settings_does_not_contain_credentials(bad_dict)
        assert exc.value.code in (
            "CREDENTIAL_IN_SETTINGS_FORBIDDEN",
            "PLAINTEXT_TOKEN_IN_SETTINGS_FORBIDDEN",
        )
        # Ensure error message does NOT echo the secret value
        err_msg = str(exc.value)
        assert "ghp_12345" not in err_msg
        assert "AKIAIOSFODNN7EXAMPLE" not in err_msg
        assert "ASIAIOSFODNN7EXAMPLE" not in err_msg
        assert "sk_live_" not in err_msg


@pytest.mark.asyncio
async def test_store_and_decrypt_organization_integration(
    db_session: AsyncSession, integration_test_context
):
    """Stores credential encrypted with AES-256-GCM and decrypts accurately in memory."""
    ctx = integration_test_context
    raw_token = "ghp_RealTestTokenForGitHubIngestion123456"

    # Store integration
    integration = await store_organization_integration(
        db=db_session,
        organization_id=ctx["org1"].id,
        provider="github",
        token=raw_token,
        user_id=ctx["user"].id,
    )
    await db_session.commit()

    assert integration.id is not None
    assert integration.token_preview == "ghp_****3456"
    assert integration.encrypted_token != raw_token.encode("utf-8")
    assert len(integration.encrypted_token) >= 28  # Nonce (12) + Ciphertext + Tag (16)

    # Verify audit event emitted
    stmt = select(AuditEvent).where(AuditEvent.resource_id == str(integration.id))
    audit = (await db_session.execute(stmt)).scalars().first()
    assert audit is not None
    assert audit.action == "INTEGRATION_CONFIGURED"

    # Decrypt in memory
    decrypted = decrypt_organization_integration_token(integration)
    assert decrypted == raw_token


@pytest.mark.asyncio
async def test_integration_token_rotation_and_revocation(
    db_session: AsyncSession, integration_test_context
):
    """Rotating a token revokes the previous token and creates a new active record."""
    ctx = integration_test_context
    token_v1 = "ghp_FirstVersionOfGitHubCredential1111"
    token_v2 = "ghp_SecondVersionOfGitHubCredential2222"

    # 1. Store v1
    int1 = await store_organization_integration(
        db=db_session,
        organization_id=ctx["org1"].id,
        provider="github",
        token=token_v1,
        user_id=ctx["user"].id,
    )
    await db_session.commit()
    int1_id = int1.id

    # 2. Store v2 (Rotation)
    int2 = await store_organization_integration(
        db=db_session,
        organization_id=ctx["org1"].id,
        provider="github",
        token=token_v2,
        user_id=ctx["user"].id,
    )
    await db_session.commit()
    int2_id = int2.id

    # Refresh v1
    v1_refreshed = await db_session.get(OrganizationIntegration, int1_id)
    assert v1_refreshed.revoked_at is not None

    # Decrypting revoked token must fail
    with pytest.raises(AppException) as exc_revoked:
        decrypt_organization_integration_token(v1_refreshed)
    assert exc_revoked.value.code == "INTEGRATION_TOKEN_REVOKED"

    # Active integration resolves to v2
    active = await get_organization_integration(db_session, ctx["org1"].id, "github")
    assert active is not None
    assert active.id == int2_id
    assert decrypt_organization_integration_token(active) == token_v2

    # 3. Explicit revocation
    revoked = await revoke_organization_integration(
        db_session, ctx["org1"].id, int2_id, user_id=ctx["user"].id
    )
    await db_session.commit()
    assert revoked is True

    active_now = await get_organization_integration(db_session, ctx["org1"].id, "github")
    assert active_now is None


@pytest.mark.asyncio
async def test_integration_tenant_isolation(
    db_session: AsyncSession, integration_test_context
):
    """Credentials of Org 1 cannot be resolved or revoked by Org 2."""
    ctx = integration_test_context
    token = "ghp_OrgOnePrivateSecretGitHubToken9999"

    int1 = await store_organization_integration(
        db=db_session,
        organization_id=ctx["org1"].id,
        provider="github",
        token=token,
    )
    await db_session.commit()

    # Querying under Org 2 yields None
    org2_integ = await get_organization_integration(db_session, ctx["org2"].id, "github")
    assert org2_integ is None

    # Revoking under Org 2 returns False
    did_revoke = await revoke_organization_integration(
        db_session, ctx["org2"].id, int1.id
    )
    await db_session.commit()
    assert did_revoke is False

    # Int1 remains active under Org 1
    org1_integ = await get_organization_integration(db_session, ctx["org1"].id, "github")
    assert org1_integ is not None
    assert org1_integ.id == int1.id

import pytest
import pyotp
from httpx import AsyncClient
from apps.api.config import settings
from apps.api.modules.users.models import PlatformRole


@pytest.mark.asyncio
async def test_unknown_account_login_error_generic(client: AsyncClient):
    """Verifies that nonexistent accounts yield generic 401 without revealing account existence."""
    response = await client.post(
        "/api/v1/admin/auth/login",
        json={"email": "nonexistent@scorva.io", "password": "AnyPassword123!"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["code"] == "INVALID_CREDENTIALS"
    assert data["detail"] == "Invalid email or password."


@pytest.mark.asyncio
async def test_wrong_password_login_error_identical(client: AsyncClient, create_user_helper):
    """Verifies that wrong password yields identical 401 message as nonexistent account."""
    user = await create_user_helper(email="admin_test1@scorva.io", password="RealPassword123!")
    response = await client.post(
        "/api/v1/admin/auth/login",
        json={"email": "admin_test1@scorva.io", "password": "WrongPassword123!"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["code"] == "INVALID_CREDENTIALS"
    assert data["detail"] == "Invalid email or password."


@pytest.mark.asyncio
async def test_non_admin_user_login_forbidden(client: AsyncClient, create_user_helper):
    """Verifies that a user without platform_role is forbidden from admin login."""
    await create_user_helper(
        email="participant@scorva.io",
        password="PassWord123!",
        platform_role=None,
    )
    response = await client.post(
        "/api/v1/admin/auth/login",
        json={"email": "participant@scorva.io", "password": "PassWord123!"},
    )
    assert response.status_code == 403
    data = response.json()
    assert data["code"] == "FORBIDDEN_NOT_ADMIN"


@pytest.mark.asyncio
async def test_suspended_user_login_denied(client: AsyncClient, create_user_helper):
    """Verifies that suspended users cannot log in."""
    await create_user_helper(
        email="suspended@scorva.io",
        password="PassWord123!",
        is_active=False,
    )
    response = await client.post(
        "/api/v1/admin/auth/login",
        json={"email": "suspended@scorva.io", "password": "PassWord123!"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_mfa_enrollment_full_flow(client: AsyncClient, create_user_helper):
    """
    Verifies full enrollment lifecycle:
    1. Login returns enrollment_token
    2. /mfa/setup returns secret & QR code uri
    3. /mfa/verify with wrong code fails
    4. /mfa/verify with real TOTP code succeeds and sets session cookie
    5. /me endpoint accessible using session cookie
    """
    user = await create_user_helper(
        email="new_admin@scorva.io",
        password="ValidPassword123!",
        mfa_enabled=False,
    )

    # 1. Login
    login_res = await client.post(
        "/api/v1/admin/auth/login",
        json={"email": "new_admin@scorva.io", "password": "ValidPassword123!"},
    )
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert login_data["mfa_required"] is True
    assert login_data["enrolled"] is False
    enrollment_token = login_data["enrollment_token"]
    assert enrollment_token is not None

    # 2. MFA Setup
    setup_res = await client.post(
        "/api/v1/admin/auth/mfa/setup",
        json={"enrollment_token": enrollment_token},
    )
    assert setup_res.status_code == 200
    setup_data = setup_res.json()
    assert "secret" in setup_data
    assert "qr_code_uri" in setup_data
    secret = setup_data["secret"]

    # 3. Invalid code rejected
    bad_verify_res = await client.post(
        "/api/v1/admin/auth/mfa/verify",
        json={"token": enrollment_token, "totp_code": "000000"},
    )
    assert bad_verify_res.status_code == 401

    # 4. Valid code verification
    totp = pyotp.TOTP(secret)
    code = totp.now()

    good_verify_res = await client.post(
        "/api/v1/admin/auth/mfa/verify",
        json={"token": enrollment_token, "totp_code": code},
    )
    assert good_verify_res.status_code == 200
    verify_data = good_verify_res.json()
    assert verify_data["user"]["email"] == "new_admin@scorva.io"
    assert verify_data["user"]["mfa_enabled"] is True

    # Verify session cookie was set
    assert settings.SESSION_COOKIE_NAME in good_verify_res.cookies
    session_cookie = good_verify_res.cookies[settings.SESSION_COOKIE_NAME]

    # 5. Access /me endpoint with session cookie
    me_res = await client.get(
        "/api/v1/admin/auth/me",
        cookies={settings.SESSION_COOKIE_NAME: session_cookie},
    )
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["email"] == "new_admin@scorva.io"
    assert me_data["platform_role"] == "platform_owner"


@pytest.mark.asyncio
async def test_mfa_challenge_existing_user_and_replay_protection(client: AsyncClient, create_user_helper):
    """
    Verifies MFA challenge flow for already-enrolled user and TOTP replay protection.
    """
    totp_secret = pyotp.random_base32()
    user = await create_user_helper(
        email="existing_mfa_admin@scorva.io",
        password="ValidPassword123!",
        mfa_enabled=True,
        totp_secret=totp_secret,
    )

    # 1. Login returns challenge_token
    login_res = await client.post(
        "/api/v1/admin/auth/login",
        json={"email": "existing_mfa_admin@scorva.io", "password": "ValidPassword123!"},
    )
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert login_data["mfa_required"] is True
    assert login_data["enrolled"] is True
    challenge_token = login_data["challenge_token"]

    # 2. Verify with valid TOTP code
    totp = pyotp.TOTP(totp_secret)
    code = totp.now()

    verify_res = await client.post(
        "/api/v1/admin/auth/mfa/verify",
        json={"token": challenge_token, "totp_code": code},
    )
    assert verify_res.status_code == 200
    assert settings.SESSION_COOKIE_NAME in verify_res.cookies

    # 3. Test replay protection: Attempting to verify the exact same code with a new token must be rejected
    login_res_2 = await client.post(
        "/api/v1/admin/auth/login",
        json={"email": "existing_mfa_admin@scorva.io", "password": "ValidPassword123!"},
    )
    assert login_res_2.status_code == 200, f"Login 2 failed: {login_res_2.json()}"
    token_2 = login_res_2.json()["challenge_token"]

    replay_res = await client.post(
        "/api/v1/admin/auth/mfa/verify",
        json={"token": token_2, "totp_code": code},
    )
    assert replay_res.status_code == 401
    assert replay_res.json()["code"] == "MFA_CODE_REPLAYED"


@pytest.mark.asyncio
async def test_logout_workflow_and_session_invalidation(client: AsyncClient, create_user_helper):
    """
    Verifies that calling logout revokes session server-side and removes cookie.
    """
    totp_secret = pyotp.random_base32()
    user = await create_user_helper(
        email="logout_admin@scorva.io",
        password="ValidPassword123!",
        mfa_enabled=True,
        totp_secret=totp_secret,
    )

    # Login and verify
    login_res = await client.post(
        "/api/v1/admin/auth/login",
        json={"email": "logout_admin@scorva.io", "password": "ValidPassword123!"},
    )
    challenge_token = login_res.json()["challenge_token"]
    verify_res = await client.post(
        "/api/v1/admin/auth/mfa/verify",
        json={"token": challenge_token, "totp_code": pyotp.TOTP(totp_secret).now()},
    )
    session_cookie = verify_res.cookies[settings.SESSION_COOKIE_NAME]

    # Verify session is operational
    me_res = await client.get(
        "/api/v1/admin/auth/me",
        cookies={settings.SESSION_COOKIE_NAME: session_cookie},
    )
    assert me_res.status_code == 200

    # Call Logout
    logout_res = await client.post(
        "/api/v1/admin/auth/logout",
        cookies={settings.SESSION_COOKIE_NAME: session_cookie},
        headers={"Origin": "http://testserver"},
    )
    assert logout_res.status_code == 200

    # Calling /me again must now be rejected (401 Session Revoked)
    me_after_res = await client.get(
        "/api/v1/admin/auth/me",
        cookies={settings.SESSION_COOKIE_NAME: session_cookie},
    )
    assert me_after_res.status_code == 401
    assert me_after_res.json()["code"] == "SESSION_REVOKED"

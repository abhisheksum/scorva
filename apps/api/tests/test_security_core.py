import pytest
import pyotp
from apps.api.core.security import (
    decrypt_totp_secret,
    dummy_verify_password,
    encrypt_totp_secret,
    generate_secure_token,
    generate_totp_secret,
    get_totp_provisioning_uri,
    hash_password,
    hash_session_token,
    verify_password,
    verify_totp_code,
)

MASTER_KEY = "test_encryption_master_key_32_bytes_long!!"


def test_argon2id_password_hashing():
    pw = "SuperSecurePassword987!"
    hashed = hash_password(pw)
    assert hashed.startswith("$argon2id$")
    assert verify_password(pw, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False
    assert verify_password("", hashed) is False


def test_dummy_verify_password_timing_safety():
    # Must execute without error
    dummy_verify_password()


def test_session_token_hashing():
    token_plain = generate_secure_token(32)
    assert len(token_plain) > 32
    token_hash = hash_session_token(token_plain)
    assert len(token_hash) == 64  # SHA-256 hex string
    # Deterministic hashing
    assert hash_session_token(token_plain) == token_hash
    # Independent tokens produce distinct hashes
    token_plain_2 = generate_secure_token(32)
    assert hash_session_token(token_plain_2) != token_hash


def test_aes256_gcm_totp_secret_encryption():
    secret = generate_totp_secret()
    encrypted = encrypt_totp_secret(secret, MASTER_KEY)
    assert encrypted != secret
    decrypted = decrypt_totp_secret(encrypted, MASTER_KEY)
    assert decrypted == secret


def test_aes256_gcm_tamper_rejection():
    secret = generate_totp_secret()
    encrypted = encrypt_totp_secret(secret, MASTER_KEY)
    import base64
    raw = bytearray(base64.b64decode(encrypted))
    raw[-1] ^= 0x01  # Tamper with the authentication tag
    tampered_b64 = base64.b64encode(raw).decode("utf-8")
    with pytest.raises(Exception):
        decrypt_totp_secret(tampered_b64, MASTER_KEY)


def test_totp_generation_and_verification():
    secret = generate_totp_secret()
    uri = get_totp_provisioning_uri(secret, "admin@scorva.local")
    assert "otpauth://totp/Scorva:" in uri
    assert "secret=" in uri
    assert "issuer=Scorva" in uri

    # Generate current code
    totp = pyotp.TOTP(secret)
    current_code = totp.now()

    assert verify_totp_code(secret, current_code) is True
    assert verify_totp_code(secret, "000000") is False
    assert verify_totp_code(secret, "invalid") is False
    assert verify_totp_code(secret, "") is False

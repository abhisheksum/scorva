import base64
import hashlib
import os
import secrets
from typing import Optional
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pyotp

# Recommended OWASP parameters for Argon2id
_ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

# Precomputed dummy hash for constant-time comparison against nonexistent accounts
_DUMMY_HASH = _ph.hash("dummy_constant_time_precomputed_password_check")


def hash_password(password: str) -> str:
    """Hashes a password using Argon2id with OWASP recommended cost parameters."""
    return _ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against an Argon2id hash."""
    try:
        return _ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def dummy_verify_password() -> None:
    """Executes a constant-time dummy verification to protect against account enumeration."""
    try:
        _ph.verify(_DUMMY_HASH, "incorrect_dummy_attempt")
    except Exception:
        pass


def generate_secure_token(nbytes: int = 32) -> str:
    """Generates a cryptographically secure random URL-safe token (default 256 bits)."""
    return secrets.token_urlsafe(nbytes)


def hash_session_token(token_plain: str) -> str:
    """Computes SHA-256 hexadecimal digest of a plaintext session token."""
    return hashlib.sha256(token_plain.encode("utf-8")).hexdigest()


def derive_aes_key(key_material: str) -> bytes:
    """Derives a deterministic 32-byte (256-bit) AES key from key material via SHA-256."""
    return hashlib.sha256(key_material.encode("utf-8")).digest()


def encrypt_value(plain_text: str, master_key: str) -> bytes:
    """
    Encrypts a plaintext string using AES-256-GCM with a 12-byte random nonce.
    Returns binary nonce || ciphertext || tag.
    """
    key_bytes = derive_aes_key(master_key)
    aesgcm = AESGCM(key_bytes)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plain_text.encode("utf-8"), None)
    return nonce + ciphertext


def decrypt_value(encrypted_bytes: bytes, master_key: str) -> str:
    """
    Decrypts an AES-256-GCM encrypted binary payload (nonce || ciphertext || tag).
    Extracts 12-byte nonce and validates integrity tag.
    """
    key_bytes = derive_aes_key(master_key)
    if len(encrypted_bytes) < 28:  # 12-byte nonce + 16-byte tag minimum
        raise ValueError("Invalid encrypted ciphertext length: payload too short")
    nonce = encrypted_bytes[:12]
    ciphertext = encrypted_bytes[12:]
    aesgcm = AESGCM(key_bytes)
    decrypted = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted.decode("utf-8")


def encrypt_totp_secret(plain_secret: str, master_key: str) -> str:
    """
    Encrypts a plaintext TOTP base32 secret using AES-256-GCM with a 12-byte random nonce.
    Returns standard Base64 representation of nonce || ciphertext || tag.
    """
    raw = encrypt_value(plain_secret, master_key)
    return base64.b64encode(raw).decode("utf-8")


def decrypt_totp_secret(encrypted_b64: str, master_key: str) -> str:
    """
    Decrypts an AES-256-GCM encrypted TOTP secret.
    Extracts 12-byte nonce and validates integrity tag.
    """
    data = base64.b64decode(encrypted_b64.encode("utf-8"))
    return decrypt_value(data, master_key)


def generate_totp_secret() -> str:
    """Generates a random Base32 TOTP secret."""
    return pyotp.random_base32()


def get_totp_provisioning_uri(secret: str, email: str, issuer: str = "Scorva") -> str:
    """Generates standard otpauth:// provisioning URI for QR code generation."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=issuer)


def verify_totp_code(secret: str, code: str, window: int = 1) -> bool:
    """
    Verifies a 6-digit TOTP code against a secret with specified time-step window.
    window=1 allows current step and ±1 step (30 seconds drift).
    """
    if not code or not code.strip().isdigit() or len(code.strip()) != 6:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code.strip(), valid_window=window)

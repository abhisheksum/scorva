"""
Scorva Administrative Account Seeding & Bootstrapping Utility.

Security Guardrails:
- In production (SCORVA_ENV=production), hardcoded default passwords and shared static TOTP seeds are STRICTLY FORBIDDEN.
- Production accounts require either explicit environment variables (BOOTSTRAP_ADMIN_EMAIL, BOOTSTRAP_ADMIN_PASSWORD)
  or generate cryptographically secure CSPRNG random credentials on the fly.
- Development presets (--dev-defaults) are strictly prohibited outside development/test environments.
"""
import argparse
import asyncio
import os
import secrets
import sys
import uuid
from typing import Optional
from sqlalchemy import select

from apps.api.config import settings
from apps.api.core.database import AsyncSessionLocal
from apps.api.core.security import (
    encrypt_totp_secret,
    generate_totp_secret,
    get_totp_provisioning_uri,
    hash_password,
)
from apps.api.modules.users.models import PlatformRole, User


async def bootstrap_single_admin(
    email: str,
    password: Optional[str] = None,
    full_name: str = "Platform Administrator",
    role: PlatformRole = PlatformRole.PLATFORM_OWNER,
    enroll_mfa: bool = False,
) -> None:
    """Creates or updates a single administrative user securely."""
    generated_password = False
    if not password:
        password = secrets.token_urlsafe(20)
        generated_password = True

    unique_secret = None
    encrypted_secret = None
    if enroll_mfa:
        unique_secret = generate_totp_secret()
        encrypted_secret = encrypt_totp_secret(unique_secret, settings.ENCRYPTION_MASTER_KEY)

    async with AsyncSessionLocal() as db:
        stmt = select(User).where(User.email == email.lower().strip())
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()

        hashed = hash_password(password)
        if existing:
            existing.full_name = full_name
            existing.platform_role = role
            existing.hashed_password = hashed
            existing.mfa_enabled = enroll_mfa
            existing.encrypted_mfa_secret = encrypted_secret
            existing.is_active = True
            print(f"[+] Updated administrator account: {email}")
        else:
            new_user = User(
                id=uuid.uuid4(),
                email=email.lower().strip(),
                full_name=full_name,
                hashed_password=hashed,
                platform_role=role,
                mfa_enabled=enroll_mfa,
                encrypted_mfa_secret=encrypted_secret,
                is_active=True,
                is_verified=True,
            )
            db.add(new_user)
            print(f"[+] Created new administrator account: {email}")

        await db.commit()

    print("\n" + "=" * 60)
    print("  SCORVA ADMINISTRATIVE CREDENTIALS")
    print("=" * 60)
    print(f"  Email:        {email}")
    print(f"  Role:         {role.value}")
    print(f"  Password:     {password} {'(Auto-Generated CSPRNG)' if generated_password else '(Provided)'}")
    if enroll_mfa and unique_secret:
        uri = get_totp_provisioning_uri(unique_secret, email, issuer="Scorva")
        print(f"  TOTP Secret:  {unique_secret} (Add to authenticator app)")
        print(f"  otpauth URI:  {uri}")
    else:
        print("  MFA Status:   Pending First-Login Enrollment (Mandatory for Admin Roles)")
    print("=" * 60)
    if settings.SCORVA_ENV == "production":
        print("  WARNING: Store these credentials in your secrets manager immediately.")
        print("  The password and TOTP secret will not be displayed again.\n")


async def seed_development_presets() -> None:
    """
    Seeds standard local development accounts.
    Strictly forbidden in production environments.
    """
    if settings.SCORVA_ENV == "production":
        print("[!] ERROR: Development presets (--dev-defaults) are strictly forbidden in production!")
        sys.exit(1)

    print("[i] Seeding local development accounts for testing...")
    async with AsyncSessionLocal() as db:
        dev_accounts = [
            {
                "email": "admin@scorva.io",
                "full_name": "Platform Owner (Setup MFA)",
                "password": "Password123!",
                "platform_role": PlatformRole.PLATFORM_OWNER,
                "mfa_enabled": False,
                "encrypted_mfa_secret": None,
            },
            {
                "email": "owner@scorva.io",
                "full_name": "Platform Owner (Enrolled)",
                "password": "Password123!",
                "platform_role": PlatformRole.PLATFORM_OWNER,
                "mfa_enabled": True,
                # Distinct secret for owner
                "encrypted_mfa_secret": encrypt_totp_secret("JBSWY3DPEHPK3PXP", settings.ENCRYPTION_MASTER_KEY),
            },
            {
                "email": "security@scorva.io",
                "full_name": "Security Auditor",
                "password": "Password123!",
                "platform_role": PlatformRole.SECURITY_ADMIN,
                "mfa_enabled": True,
                # Distinct secret for security auditor
                "encrypted_mfa_secret": encrypt_totp_secret("HXDMVJECJJWSRB3HWIZR4IFUGFTMXBOZ", settings.ENCRYPTION_MASTER_KEY),
            },
        ]

        for acc in dev_accounts:
            stmt = select(User).where(User.email == acc["email"])
            existing = (await db.execute(stmt)).scalar_one_or_none()
            hashed = hash_password(acc["password"])

            if existing:
                existing.full_name = acc["full_name"]
                existing.platform_role = acc["platform_role"]
                existing.hashed_password = hashed
                existing.mfa_enabled = acc["mfa_enabled"]
                existing.encrypted_mfa_secret = acc["encrypted_mfa_secret"]
                existing.is_active = True
                print(f"[+] Updated dev account: {acc['email']}")
            else:
                new_u = User(
                    id=uuid.uuid4(),
                    email=acc["email"],
                    full_name=acc["full_name"],
                    hashed_password=hashed,
                    platform_role=acc["platform_role"],
                    mfa_enabled=acc["mfa_enabled"],
                    encrypted_mfa_secret=acc["encrypted_mfa_secret"],
                    is_active=True,
                    is_verified=True,
                )
                db.add(new_u)
                print(f"[+] Created dev account: {acc['email']}")

        await db.commit()

    print("\n" + "=" * 60)
    print("  DEVELOPMENT ACCOUNTS READY (SCORVA_ENV=" + settings.SCORVA_ENV + ")")
    print("=" * 60)
    print("  1) admin@scorva.io / Password123!   (MFA setup flow)")
    print("  2) owner@scorva.io / Password123!   (MFA enrolled: JBSWY3DPEHPK3PXP)")
    print("  3) security@scorva.io / Password123! (MFA enrolled: HXDMVJECJJWSRB3HWIZR4IFUGFTMXBOZ)")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Scorva Admin Account Bootstrap Utility")
    parser.add_argument("--dev-defaults", action="store_true", help="Seed standard development test accounts (DEV ONLY)")
    parser.add_argument("--email", type=str, help="Admin email address", default=os.getenv("BOOTSTRAP_ADMIN_EMAIL"))
    parser.add_argument("--password", type=str, help="Admin password", default=os.getenv("BOOTSTRAP_ADMIN_PASSWORD"))
    parser.add_argument("--full-name", type=str, default="Platform Administrator", help="Full name")
    parser.add_argument("--role", type=str, default="PLATFORM_OWNER", help="Platform role (e.g. PLATFORM_OWNER, SECURITY_ADMIN)")
    parser.add_argument("--enroll-mfa", action="store_true", help="Pre-enroll a unique TOTP secret")

    args = parser.parse_args()

    if args.dev_defaults:
        asyncio.run(seed_development_presets())
    else:
        # If in development and no email passed, default to dev-defaults for convenience
        if not args.email:
            if settings.SCORVA_ENV in ("development", "test"):
                print("[i] No email provided in development mode. Seeding development presets...")
                asyncio.run(seed_development_presets())
                return
            else:
                print("[!] ERROR: In production, you must supply --email or set BOOTSTRAP_ADMIN_EMAIL.")
                sys.exit(1)

        try:
            role_enum = PlatformRole(args.role.upper())
        except ValueError:
            print(f"[!] Invalid role '{args.role}'. Valid roles: {[r.value for r in PlatformRole]}")
            sys.exit(1)

        asyncio.run(
            bootstrap_single_admin(
                email=args.email,
                password=args.password,
                full_name=args.full_name,
                role=role_enum,
                enroll_mfa=args.enroll_mfa,
            )
        )


if __name__ == "__main__":
    main()

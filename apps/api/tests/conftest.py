from datetime import datetime, timedelta, timezone
import os
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

# Set test environment
os.environ["SCORVA_ENV"] = "test"
os.environ["DEBUG"] = "false"

from apps.api.main import create_app
from apps.api.config import settings
from apps.api.core.database import AsyncSessionLocal
from apps.api.core.redis import flush_test_redis
from apps.api.core.security import encrypt_totp_secret, generate_secure_token, hash_password, hash_session_token
from apps.api.modules.hackathons.models import Hackathon
from apps.api.modules.organizations.models import Organization, OrganizationMembership
from apps.api.modules.users.models import PlatformRole, User, UserSession


@pytest.fixture(autouse=True)
async def cleanup_test_redis():
    await flush_test_redis()
    yield
    await flush_test_redis()


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
async def create_user_helper(db_session):
    async def _create(
        email: str,
        password: str = "CorrectPassword123!",
        full_name: str = "Test Administrator",
        platform_role: PlatformRole = PlatformRole.PLATFORM_OWNER,
        mfa_enabled: bool = False,
        is_active: bool = True,
        totp_secret: str = None,
    ) -> User:
        # Clean up any previous test artifacts with same email (delete children first)
        existing_ids = (await db_session.execute(
            select(User.id).where(User.email == email)
        )).scalars().all()
        if existing_ids:
            # Delete memberships
            await db_session.execute(delete(OrganizationMembership).where(OrganizationMembership.user_id.in_(existing_ids)))
            # Delete any organizations owned by user (with their hackathons & memberships)
            owned_org_ids = (await db_session.execute(
                select(Organization.id).where(Organization.owner_id.in_(existing_ids))
            )).scalars().all()
            if owned_org_ids:
                await db_session.execute(delete(Hackathon).where(Hackathon.organization_id.in_(owned_org_ids)))
                await db_session.execute(delete(OrganizationMembership).where(OrganizationMembership.organization_id.in_(owned_org_ids)))
                await db_session.execute(delete(Organization).where(Organization.id.in_(owned_org_ids)))
            await db_session.execute(delete(UserSession).where(UserSession.user_id.in_(existing_ids)))
            await db_session.execute(delete(User).where(User.id.in_(existing_ids)))
            await db_session.commit()

        encrypted_secret = None
        if totp_secret:
            encrypted_secret = encrypt_totp_secret(totp_secret, settings.ENCRYPTION_MASTER_KEY)

        user = User(
            id=uuid.uuid4(),
            email=email,
            full_name=full_name,
            hashed_password=hash_password(password),
            platform_role=platform_role,
            is_active=is_active,
            is_verified=True,
            mfa_enabled=mfa_enabled,
            encrypted_mfa_secret=encrypted_secret,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    return _create


@pytest.fixture
async def create_session_helper(db_session):
    async def _create(user: User) -> str:
        token_plain = generate_secure_token(32)
        token_hash = hash_session_token(token_plain)
        session = UserSession(
            id=uuid.uuid4(),
            user_id=user.id,
            session_token_hash=token_hash,
            ip_address="127.0.0.1",
            user_agent="TestRunner/1.0",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
            created_at=datetime.now(timezone.utc),
            last_active_at=datetime.now(timezone.utc),
            is_revoked=False,
        )
        db_session.add(session)
        await db_session.commit()
        return token_plain

    return _create


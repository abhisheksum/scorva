import os
import pytest
from httpx import ASGITransport, AsyncClient

# Set test environment
os.environ["SCORVA_ENV"] = "test"
os.environ["DEBUG"] = "false"

from apps.api.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

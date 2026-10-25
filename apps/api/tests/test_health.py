import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Scorva Platform API"
    assert data["version"] == "0.1.0"
    assert data["status"] == "operational"
    assert "X-Correlation-ID" in response.headers


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app_name"] == "Scorva API"
    assert data["environment"] == "test"
    assert "api" in data["services"]
    assert data["services"]["api"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_liveness_endpoint(client: AsyncClient):
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_readiness_endpoint(client: AsyncClient):
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"

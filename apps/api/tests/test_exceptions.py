import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_404_not_found_standard_error(client: AsyncClient):
    response = await client.get("/api/v1/non-existent-route")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"
    assert "request_id" in data["error"]
    assert "timestamp" in data["error"]

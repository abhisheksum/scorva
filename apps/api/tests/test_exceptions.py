import pytest
from httpx import AsyncClient
from apps.api.core.exceptions import AppException, format_error_response


@pytest.mark.asyncio
async def test_404_not_found_standard_error(client: AsyncClient):
    response = await client.get("/api/v1/non-existent-route")
    assert response.status_code == 404
    assert "application/problem+json" in response.headers.get("content-type", "")

    data = response.json()
    # RFC 7807 / RFC 9457 Top-Level Problem Details fields
    assert data["type"] == "https://api.scorva.io/errors/not-found"
    assert data["title"] == "Resource Not Found"
    assert data["status"] == 404
    assert data["code"] == "NOT_FOUND"
    assert "Not Found" in data["detail"]
    assert "request_id" in data
    assert "timestamp" in data
    assert data["instance"] == "/api/v1/non-existent-route"

    # Backwards compatibility nested error envelope
    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"
    assert data["error"]["request_id"] == data["request_id"]


def test_format_error_response_rfc7807():
    response = format_error_response(
        code="ORGANIZATION_SUSPENDED",
        message="Organization has been suspended.",
        status_code=403,
        instance="/api/v1/admin/organizations/123/status",
        invalid_params=[{"field": "status", "reason": "Already suspended"}],
    )
    assert response.status_code == 403
    assert response.media_type == "application/problem+json"

    import json
    data = json.loads(response.body.decode("utf-8"))
    assert data["type"] == "https://api.scorva.io/errors/organization-suspended"
    assert data["title"] == "Organization Suspended"
    assert data["status"] == 403
    assert data["code"] == "ORGANIZATION_SUSPENDED"
    assert data["detail"] == "Organization has been suspended."
    assert data["instance"] == "/api/v1/admin/organizations/123/status"
    assert len(data["invalid_params"]) == 1
    assert data["invalid_params"][0]["field"] == "status"
    assert "error" in data


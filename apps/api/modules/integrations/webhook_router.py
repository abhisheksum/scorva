"""
GitHub Webhook HTTP Ingestion Endpoint.

Verifies X-Hub-Signature-256 using HMAC-SHA256, enforces size quotas,
parses payloads defensively, and stores normalized event records idempotently.
"""

import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.core.database import get_db_session
from apps.api.core.exceptions import AppException
from apps.api.modules.evaluations.webhook_service import (
    ingest_github_webhook,
    verify_github_webhook_signature,
)
from apps.api.modules.hackathons.subresources_schemas import WebhookIngestResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["GitHub Webhooks"])


@router.post(
    "/integrations/github/webhook",
    response_model=WebhookIngestResponse,
    status_code=status.HTTP_200_OK,
    summary="GitHub Webhook Ingestion Receiver",
)
@router.post(
    "/webhooks/github",
    response_model=WebhookIngestResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def handle_github_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    x_github_delivery: Optional[str] = Header(None, alias="X-GitHub-Delivery"),
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
):
    """
    Ingests and acknowledges GitHub webhook deliveries.
    Enforces payload size bounds, constant-time HMAC-SHA256 verification, and strict schema normalization.
    """
    # 1. Enforce payload size limit
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.GITHUB_WEBHOOK_MAX_BYTES:
        raise AppException(
            status_code=413,
            code="PAYLOAD_TOO_LARGE",
            message=f"Webhook payload exceeds maximum allowed size of {settings.GITHUB_WEBHOOK_MAX_BYTES} bytes.",
        )

    # 2. Validate mandatory GitHub headers
    if not x_github_delivery:
        raise AppException(
            status_code=400,
            code="MISSING_DELIVERY_HEADER",
            message="Missing required 'X-GitHub-Delivery' header.",
        )

    if not x_github_event:
        raise AppException(
            status_code=400,
            code="MISSING_EVENT_HEADER",
            message="Missing required 'X-GitHub-Event' header.",
        )

    # 3. Read body bytes and enforce limit in-memory
    raw_body = await request.body()
    if len(raw_body) > settings.GITHUB_WEBHOOK_MAX_BYTES:
        raise AppException(
            status_code=413,
            code="PAYLOAD_TOO_LARGE",
            message=f"Webhook payload exceeds maximum allowed size of {settings.GITHUB_WEBHOOK_MAX_BYTES} bytes.",
        )

    # 4. Cryptographic signature check (constant-time comparison)
    verify_github_webhook_signature(
        raw_body=raw_body,
        signature_header=x_hub_signature_256,
        secret=settings.GITHUB_WEBHOOK_SECRET,
    )

    # 5. Strictly parse JSON payload
    try:
        payload = json.loads(raw_body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a JSON object")
    except Exception as exc:
        raise AppException(
            status_code=400,
            code="MALFORMED_JSON_PAYLOAD",
            message="Invalid or non-JSON webhook payload.",
        ) from exc

    # 6. Ingest and persist event idempotently
    result = await ingest_github_webhook(
        db=db,
        delivery_id=x_github_delivery,
        event_type=x_github_event,
        payload=payload,
    )

    return WebhookIngestResponse(**result)

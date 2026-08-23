"""Best-effort delivery of tutor observations to the learning system."""

from __future__ import annotations

import hashlib
import hmac
import logging

import httpx

from app.schemas.tutor import LearningWebhookEnvelope


logger = logging.getLogger(__name__)


def webhook_signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def publish_learning_events(
    envelope: LearningWebhookEnvelope,
    *,
    webhook_url: str,
    webhook_secret: str | None,
    timeout_seconds: float = 5,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Deliver once; callers retain the response copy when delivery fails."""

    body = envelope.model_dump_json().encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Mentora-Event-Version": envelope.schema_version,
    }
    if webhook_secret:
        headers["X-Mentora-Signature"] = webhook_signature(body, webhook_secret)

    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=timeout_seconds)
    try:
        response = await http_client.post(webhook_url, content=body, headers=headers)
        response.raise_for_status()
        return True
    except (httpx.HTTPError, ValueError):
        logger.warning(
            "Learning metrics webhook delivery failed",
            extra={
                "interaction_id": envelope.interaction_id,
                "event_count": len(envelope.events),
            },
        )
        return False
    finally:
        if owns_client:
            await http_client.aclose()

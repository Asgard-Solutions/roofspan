"""ABC Supply Notification API (verified: /api/notification/v2/webhooks).

Manages ONE integration-level webhook (type ORDER; events ORDER_UPDATE, ORDER_INVOICED) using the
application Client Credentials token (scopes notification.read/write) — NOT a customer user token.
ABC allows max 5 webhooks/app; we reconcile to a single active registration.

Auth of INCOMING events lives in routers/abc_webhooks.py. The registration secret returned by ABC is
stored encrypted and never logged.
"""
from __future__ import annotations

from .client import AbcClient
from .config import NOTIFICATION_PREFIX

WEBHOOK_NAME = "RoofSpan ABC Supply Orders"
WEBHOOK_TYPE = "ORDER"
WEBHOOK_EVENTS = ["ORDER_UPDATE", "ORDER_INVOICED"]


async def list_webhooks(client: AbcClient) -> list[dict]:
    data = await client.get_json(f"{NOTIFICATION_PREFIX}/webhooks")
    return (data.get("webhooks") if isinstance(data, dict) else data) or []


async def get_webhook(client: AbcClient, webhook_id: str) -> dict:
    return await client.get_json(f"{NOTIFICATION_PREFIX}/webhooks/{webhook_id}")  # type: ignore[return-value]


async def register_webhook(client: AbcClient, *, url: str, name: str = WEBHOOK_NAME) -> dict:
    body = {"name": name, "type": WEBHOOK_TYPE, "events": WEBHOOK_EVENTS, "url": url}
    return await client.post_json(f"{NOTIFICATION_PREFIX}/webhooks", json=body)  # type: ignore[return-value]


async def patch_webhook(client: AbcClient, webhook_id: str, *, url: str, name: str = WEBHOOK_NAME) -> dict:
    body = {"name": name, "type": WEBHOOK_TYPE, "events": WEBHOOK_EVENTS, "url": url}
    resp = await client.request("PATCH", f"{NOTIFICATION_PREFIX}/webhooks/{webhook_id}", json=body, allow_retry=False)
    return AbcClient._json_or_raise(resp)  # type: ignore[return-value]


async def delete_webhook(client: AbcClient, webhook_id: str) -> None:
    await client.request("DELETE", f"{NOTIFICATION_PREFIX}/webhooks/{webhook_id}", allow_retry=False)

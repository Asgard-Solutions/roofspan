"""ABC Supply Notifications — Phase 4 (RoofSpan Office / Desktop).

Two surfaces:
  * PUBLIC Relay ingress: POST /api/webhooks/abc/orders  (ABC calls this; authenticated by webhook secret;
    durably queued; routed to the owning installation; ACKed once safely accepted).
  * ADMIN/local: /api/integrations/abc/notifications/*  (register/reconcile, status, event history, reconnect).

The registration secret and queued payloads are AES-GCM encrypted and never logged. Webhook processing is
idempotent (unique event_key) and never auto-receives inventory. In this single-process desktop build the
Relay ingress and the local Office processor coexist; the durable queue + installation online flag model the
"Office offline → reconnect → deliver once" behaviour.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import (User, PurchaseOrder, AbcWebhookRegistration, AbcOrderRoute, AbcWebhookDelivery,
                    AbcNotificationEvent, AbcInvoiceEvent)
from core import require_roles, SENSITIVE_ROLES, MANAGE_ROLES, encrypt_secret, decrypt_secret, log_action
from integrations.abc_supply import config as abc_config
from integrations.abc_supply import auth as abc_auth
from integrations.abc_supply import notifications as abc_notify
from integrations.abc_supply.client import AbcClient
from integrations.abc_supply.exceptions import AbcError

log = logging.getLogger("roofspan.abc")

# Public Relay ingress (no JWT; authenticated by the ABC webhook secret).
public_router = APIRouter(prefix="/api/webhooks/abc", tags=["abc-webhooks"])
# Admin/local management.
admin_router = APIRouter(prefix="/api/integrations/abc/notifications", tags=["abc-notifications"])

# Per-install online flag (models a customer PC being on/off). In-memory is sufficient for the desktop mock.
_ONLINE: dict[str, bool] = {}


def _installation_id() -> str:
    return os.environ.get("ABC_INSTALLATION_ID", "install-local")


def _is_online(iid: str) -> bool:
    return _ONLINE.get(iid, True)


# ---------------- helpers ----------------
async def _get_reg(db: AsyncSession) -> AbcWebhookRegistration:
    row = (await db.execute(select(AbcWebhookRegistration))).scalars().first()
    if not row:
        row = AbcWebhookRegistration(environment=abc_config.DEFAULT_ENVIRONMENT, status="not_registered")
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


def _event_type(payload: dict, header_type: str | None) -> str:
    t = (header_type or payload.get("eventType") or payload.get("event") or "").upper()
    if "INVOIC" in t or payload.get("invoiceNumber") or (payload.get("data") or {}).get("invoiceNumber"):
        return "ORDER_INVOICED"
    return "ORDER_UPDATE"


def _event_key(payload: dict, etype: str) -> str:
    eid = payload.get("eventId") or payload.get("id")
    if eid:
        return f"{etype}:{eid}"
    data = payload.get("data") or payload
    basis = json.dumps({"t": etype, "o": data.get("orderNumber"), "c": data.get("confirmationNumber"),
                        "s": data.get("status"), "i": data.get("invoiceNumber"), "ts": data.get("updatedAt") or data.get("eventTime")},
                       sort_keys=True)
    return f"{etype}:" + hashlib.sha256(basis.encode()).hexdigest()[:40]


def verify_order_update_event(authorization: str | None, secret: str) -> bool:
    if not authorization or not secret:
        return False
    supplied = authorization.strip()
    if supplied.lower().startswith("bearer "):
        supplied = supplied.split(" ", 1)[1].strip()
    return hmac.compare_digest(supplied, secret)


def verify_order_invoiced_event(authorization: str | None, api_key: str | None, secret: str) -> bool:
    # NEEDS ABC SANDBOX VERIFICATION: ORDER_INVOICED secret transport (docs show Authorization header AND
    # webhookDetails[].apiKey). We accept EITHER but only when it matches the registered secret (constant-time).
    if not secret:
        return False
    for cand in ((authorization or "").strip(), (api_key or "").strip()):
        if cand.lower().startswith("bearer "):
            cand = cand.split(" ", 1)[1].strip()
        if cand and hmac.compare_digest(cand, secret):
            return True
    return False


async def _process_delivery(db: AsyncSession, delivery: AbcWebhookDelivery) -> None:
    """Local Office processor: idempotent, updates PO status / stores invoice metadata. No inventory changes."""
    payload = json.loads(decrypt_secret(delivery.payload_ciphertext)) if delivery.payload_ciphertext else {}
    data = payload.get("data") or payload
    # local idempotency
    existing = (await db.execute(select(AbcNotificationEvent).where(AbcNotificationEvent.event_key == delivery.event_key))).scalars().first()
    if existing and existing.status == "processed":
        delivery.status = "delivered"
        delivery.delivered_at = datetime.now(timezone.utc)
        await db.commit()
        return
    po = None
    route_po_id = None
    from sqlalchemy import or_ as _or
    _conds = []
    if delivery.abc_order_number:
        _conds.append(AbcOrderRoute.abc_order_number == delivery.abc_order_number)
    if delivery.abc_confirmation_number:
        _conds.append(AbcOrderRoute.abc_confirmation_number == delivery.abc_confirmation_number)
    if delivery.roofspan_po_number:
        _conds.append(AbcOrderRoute.roofspan_po_number == delivery.roofspan_po_number)
    route = (await db.execute(select(AbcOrderRoute).where(_or(*_conds)))).scalars().first() if _conds else None
    if route:
        route_po_id = route.purchase_order_id
    if route_po_id:
        po = await db.get(PurchaseOrder, route_po_id)

    ev = existing or AbcNotificationEvent(event_type=delivery.event_type, event_key=delivery.event_key,
                                          abc_order_number=delivery.abc_order_number,
                                          abc_confirmation_number=delivery.abc_confirmation_number,
                                          purchase_order_id=(po.id if po else None))
    if not existing:
        db.add(ev)

    now = datetime.now(timezone.utc)
    if delivery.event_type == "ORDER_UPDATE" and po:
        new_status = data.get("status")
        # out-of-order guard: skip if this event is older than the last sync we applied
        ev_ts = data.get("updatedAt") or data.get("eventTime")
        stale = False
        if ev_ts and po.abc_last_sync_at:
            try:
                stale = datetime.fromisoformat(ev_ts.replace("Z", "+00:00")) < po.abc_last_sync_at
            except ValueError:
                stale = False
        if not stale:
            from integrations.abc_supply import orders as abc_orders
            if new_status:
                po.abc_order_status = new_status
                po.abc_normalized_status = abc_orders.normalize_status(new_status)
            if data.get("orderNumber"):
                po.external_order_number = data.get("orderNumber")
            if data.get("trackingId"):
                po.external_tracking_id = data.get("trackingId")
            po.abc_last_sync_at = now
        ev.abc_status = new_status
    elif delivery.event_type == "ORDER_INVOICED":
        db.add(AbcInvoiceEvent(purchase_order_id=(po.id if po else None),
                               abc_invoice_number=data.get("invoiceNumber"), abc_invoice_date=data.get("invoiceDate"),
                               abc_order_number=data.get("orderNumber"), abc_purchase_order_number=data.get("purchaseOrderNumber"),
                               is_credit_memo=bool(data.get("isCreditMemo")), is_rebill=bool(data.get("isRebill")),
                               payload_fingerprint=delivery.event_key))
    ev.status = "processed"
    ev.processed_at = now
    delivery.status = "delivered"
    delivery.delivered_at = now
    await db.commit()


# ---------------- PUBLIC ingress ----------------
@public_router.post("/orders")
async def abc_order_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    reg = await _get_reg(db)
    secret = None
    try:
        secret = decrypt_secret(reg.secret_ciphertext) if reg.secret_ciphertext else None
    except Exception:
        secret = None
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook not registered")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed payload")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Malformed payload")

    authz = request.headers.get("Authorization")
    etype = _event_type(payload, request.headers.get("X-Abc-Event-Type"))
    data = payload.get("data") or payload
    api_key = data.get("apiKey") or (data.get("webhookDetails") or [{}])[0].get("apiKey") if isinstance(data.get("webhookDetails"), list) else data.get("apiKey")
    ok = verify_order_update_event(authz, secret) if etype == "ORDER_UPDATE" else verify_order_invoiced_event(authz, api_key, secret)
    if not ok:
        await log_action(db, user=None, action="abc.notification.rejected", entity_type="abc_webhook", entity_id=None,
                         detail={"event_type": etype, "reason": "auth"}, request=request)
        raise HTTPException(status_code=401, detail="Invalid webhook authentication")

    ekey = _event_key(payload, etype)
    order_no = data.get("orderNumber")
    conf_no = data.get("confirmationNumber")
    po_no = data.get("purchaseOrderNumber") or data.get("purchaseOrder")

    # transport idempotency
    dup = (await db.execute(select(AbcWebhookDelivery).where(AbcWebhookDelivery.event_key == ekey))).scalars().first()
    if dup:
        return {"status": "accepted", "duplicate": True}

    # routing — only match on identifiers actually present (avoid NULL==NULL false matches)
    from sqlalchemy import or_
    conds = []
    if order_no:
        conds.append(AbcOrderRoute.abc_order_number == order_no)
    if conf_no:
        conds.append(AbcOrderRoute.abc_confirmation_number == conf_no)
    if po_no:
        conds.append(AbcOrderRoute.roofspan_po_number == po_no)
    route = None
    if conds:
        route = (await db.execute(select(AbcOrderRoute).where(or_(*conds)))).scalars().first()
    iid = route.installation_id if route else None
    delivery = AbcWebhookDelivery(event_key=ekey, event_type=etype, installation_id=iid,
                                  abc_order_number=order_no, abc_confirmation_number=conf_no, roofspan_po_number=po_no,
                                  payload_ciphertext=encrypt_secret(json.dumps(payload)),
                                  status="queued", routing_status=("matched" if route else "unmatched"))
    db.add(delivery)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return {"status": "accepted", "duplicate": True}
    await db.commit()
    await log_action(db, user=None, action="abc.notification.received", entity_type="abc_webhook", entity_id=None,
                     detail={"event_type": etype, "routing": delivery.routing_status}, request=request)

    if route and _is_online(iid):
        try:
            await _process_delivery(db, delivery)
            await log_action(db, user=None, action=("abc.invoice.webhook_received" if etype == "ORDER_INVOICED" else "abc.order.webhook_update"),
                             entity_type="purchase_order", entity_id=route.purchase_order_id, request=request)
        except Exception as e:  # keep it queued for retry; still ACK ABC
            delivery.status = "failed"
            delivery.attempts += 1
            delivery.last_error = str(e)[:300]
            await db.commit()
    elif not route:
        await log_action(db, user=None, action="abc.notification.unmatched", entity_type="abc_webhook", entity_id=None, request=request)
    return {"status": "accepted", "event_type": etype, "routing": delivery.routing_status}


# ---------------- ADMIN / local ----------------
async def _cc_client(db: AsyncSession):
    from routers import abc_supply as abc_router
    row = await abc_router._get_or_create(db)
    cfg = abc_router._build_cfg(row)
    tok = await abc_auth.client_credentials_token(cfg, scope=abc_config.CLIENT_CREDENTIAL_SCOPES)
    return AbcClient(cfg, access_token=tok.get("access_token")), cfg


@admin_router.get("/status")
async def notif_status(user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    reg = await _get_reg(db)
    queued = (await db.execute(select(AbcWebhookDelivery).where(AbcWebhookDelivery.status.in_(["queued", "failed"])))).scalars().all()
    delivered = (await db.execute(select(AbcWebhookDelivery).where(AbcWebhookDelivery.status == "delivered"))).scalars().all()
    return {"status": reg.status, "webhook_id": reg.webhook_id, "name": reg.name, "events": reg.events, "url": reg.url,
            "registered_at": reg.registered_at, "has_secret": bool(reg.secret_ciphertext),
            "installation_id": _installation_id(), "online": _is_online(_installation_id()),
            "queued_count": len(queued), "delivered_count": len(delivered),
            "oldest_queued_at": min([d.received_at for d in queued], default=None)}


@admin_router.post("/register")
async def register(request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    from routers import abc_supply as abc_router
    row = await abc_router._get_or_create(db)
    reg = await _get_reg(db)
    public_url = row.webhook_public_url or f"{abc_router._public_base(request)}/api/webhooks/abc/orders"
    try:
        client, cfg = await _cc_client(db)
        existing = await abc_notify.list_webhooks(client)
        mine = next((w for w in existing if w.get("name") == abc_notify.WEBHOOK_NAME), None)
        if mine:
            wid = mine.get("id") or mine.get("webhookId")
            if mine.get("url") != public_url:
                mine = await abc_notify.patch_webhook(client, wid, url=public_url)
            result = mine
        else:
            result = await abc_notify.register_webhook(client, url=public_url)
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)
    reg.webhook_id = result.get("id") or result.get("webhookId")
    reg.name = result.get("name") or abc_notify.WEBHOOK_NAME
    reg.status = (result.get("status") or "REGISTERED")
    reg.events = result.get("events") or abc_notify.WEBHOOK_EVENTS
    reg.url = public_url
    reg.environment = row.environment
    if result.get("secret"):
        reg.secret_ciphertext = encrypt_secret(result["secret"])
    reg.registered_at = datetime.now(timezone.utc)
    await db.commit()
    await log_action(db, user=user, action="abc.notification.register", entity_type="abc_webhook", entity_id=None,
                     detail={"webhook_id": reg.webhook_id, "status": reg.status}, request=request)
    return {"status": reg.status, "webhook_id": reg.webhook_id, "url": reg.url, "events": reg.events, "has_secret": bool(reg.secret_ciphertext)}


@admin_router.post("/simulate-offline")
async def set_offline(online: bool = True, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    _ONLINE[_installation_id()] = online
    return {"installation_id": _installation_id(), "online": online}


@admin_router.post("/reconnect")
async def reconnect(request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    """Office comes back online: flush queued/failed deliveries (bounded) for this installation, once each."""
    iid = _installation_id()
    _ONLINE[iid] = True
    pending = (await db.execute(select(AbcWebhookDelivery).where(
        AbcWebhookDelivery.installation_id == iid,
        AbcWebhookDelivery.status.in_(["queued", "failed"])).order_by(AbcWebhookDelivery.received_at))).scalars().all()
    delivered = 0
    for d in pending:
        if d.attempts >= 8:
            d.status = "dead_letter"
            await db.commit()
            continue
        try:
            await _process_delivery(db, d)
            delivered += 1
        except Exception as e:
            d.status = "failed"
            d.attempts += 1
            d.last_error = str(e)[:300]
            await db.commit()
    return {"delivered": delivered, "remaining": len(pending) - delivered}


@admin_router.get("/events/{po_id}")
async def po_events(po_id: str, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    evs = (await db.execute(select(AbcNotificationEvent).where(AbcNotificationEvent.purchase_order_id == po_id).order_by(AbcNotificationEvent.received_at.desc()))).scalars().all()
    invs = (await db.execute(select(AbcInvoiceEvent).where(AbcInvoiceEvent.purchase_order_id == po_id).order_by(AbcInvoiceEvent.event_received_at.desc()))).scalars().all()
    return {
        "events": [{"event_type": e.event_type, "abc_status": e.abc_status, "received_at": e.received_at} for e in evs],
        "invoices": [{"invoice_number": i.abc_invoice_number, "invoice_date": i.abc_invoice_date,
                      "is_credit_memo": i.is_credit_memo, "is_rebill": i.is_rebill, "received_at": i.event_received_at} for i in invs],
    }

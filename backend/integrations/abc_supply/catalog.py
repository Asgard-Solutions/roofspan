"""ABC Supply vendor-catalog sync + mapping (RoofSpan-local cache).

Maps raw ABC product items to the local `abc_catalog_items` cache, upserts by ABC item number, and
runs full / incremental synchronizations. This layer is deliberately pure of HTTP concerns beyond the
injected AbcClient so it is unit-testable. Availability is derived from the item's branch list — ABC
does NOT expose physical quantity-on-hand, so nothing here ever produces a stock number.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import AbcCatalogItem, AbcCatalogSync
from .client import AbcClient
from . import products as abc_products

log = logging.getLogger("roofspan.abc.catalog")

_SYNC_PAGE_SIZE = 100
_MAX_SYNC_PAGES = 500  # hard safety bound so a runaway catalog can never loop forever


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        s = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _branch_numbers(item: dict) -> list[str]:
    branches = item.get("branches")
    if isinstance(branches, list) and branches:
        return [str(b.get("number")) for b in branches if b.get("number") is not None]
    raw = item.get("branchNumbers")
    if isinstance(raw, list):
        return [str(n) for n in raw]
    return []


def map_catalog_fields(item: dict) -> dict:
    """Translate one raw ABC product item into local `abc_catalog_items` column values."""
    hier = item.get("hierarchy") or {}
    pg = hier.get("productGroup") or {}
    cat = pg.get("category")
    category = cat.get("label") if isinstance(cat, dict) else (cat if isinstance(cat, str) else pg.get("label"))
    uoms = item.get("uoms") or []
    stocking = next((u for u in uoms if (u.get("description") or "").lower() == "stocking"), None)
    default_uom = (stocking or (uoms[0] if uoms else {})).get("code")
    status_raw = (item.get("status") or "Active")
    status = "inactive" if str(status_raw).strip().lower() in ("inactive", "discontinued", "retired") else "active"
    return {
        "abc_item_number": str(item.get("itemNumber") or ""),
        "description": item.get("itemDescription"),
        "manufacturer": item.get("manufacturer"),
        "brand": item.get("brand") or item.get("manufacturer"),
        "category": category,
        "family_id": item.get("familyId"),
        "family_name": item.get("familyName"),
        "unit_of_measure": default_uom,
        "uoms": uoms,
        "status": status,
        "image_url": abc_products.primary_image_href(item),
        "is_dimensional": bool(item.get("isDimensional")),
        "branch_numbers": _branch_numbers(item),
        "abc_last_modified_at": _parse_dt(item.get("lastModifiedDateTime") or item.get("modifiedDate")),
        "raw_data": item,
    }


async def upsert_catalog_item(db: AsyncSession, item: dict) -> tuple[AbcCatalogItem, bool]:
    """Upsert one raw ABC item by ABC item number. Returns (row, created)."""
    fields = map_catalog_fields(item)
    num = fields["abc_item_number"]
    if not num:
        raise ValueError("ABC item has no itemNumber")
    row = (await db.execute(select(AbcCatalogItem).where(AbcCatalogItem.abc_item_number == num))).scalars().first()
    created = row is None
    if created:
        row = AbcCatalogItem(**fields)
        db.add(row)
    else:
        for k, v in fields.items():
            if k == "abc_item_number":
                continue
            setattr(row, k, v)
    row.synced_at = datetime.now(timezone.utc)
    return row, created


async def get_sync_row(db: AsyncSession) -> AbcCatalogSync:
    row = (await db.execute(select(AbcCatalogSync))).scalars().first()
    if not row:
        row = AbcCatalogSync(status="never_synced")
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def run_sync(db: AsyncSession, client: AbcClient, *, full: bool, started_by: str | None = None) -> AbcCatalogSync:
    """Paginate ABC's full-catalog endpoint and upsert into the local cache.

    full=True ignores the last-sync watermark (initial sync). full=False uses `sinceLastModifiedDateTime`
    from the last successful sync (incremental). Inactive items are marked inactive locally and NEVER
    deleted (existing RoofSpan inventory referencing them must remain intact). Bounded + batched commits.
    """
    sync = await get_sync_row(db)
    since = None if full else (sync.last_synced_at.astimezone(timezone.utc).isoformat() if sync.last_synced_at else None)
    sync.status = "syncing"
    sync.started_at = datetime.now(timezone.utc)
    sync.started_by = started_by
    sync.last_error = None
    sync.items_synced = 0
    await db.commit()

    processed = 0
    try:
        page = 1
        while page <= _MAX_SYNC_PAGES:
            data = await abc_products.list_items(client, page_number=page, items_per_page=_SYNC_PAGE_SIZE, since=since)
            items = data.get("items") or []
            if not items:
                break
            for it in items:
                try:
                    await upsert_catalog_item(db, it)
                    processed += 1
                except ValueError:
                    continue
            await db.commit()  # commit per page (batched transaction)
            pagination = data.get("pagination") or {}
            total_pages = pagination.get("totalPages")
            if total_pages is not None and page >= int(total_pages):
                break
            if len(items) < _SYNC_PAGE_SIZE and total_pages is None:
                break
            page += 1
        now = datetime.now(timezone.utc)
        total = (await db.execute(select(func.count(AbcCatalogItem.id)))).scalar() or 0
        sync.status = "completed"
        sync.items_synced = processed
        sync.total_items = int(total)
        sync.last_synced_at = now
        if full:
            sync.last_full_sync_at = now
        await db.commit()
        await db.refresh(sync)
        return sync
    except Exception as exc:  # noqa: BLE001 — surface failure cleanly, allow retry
        log.warning("ABC catalog sync failed: %s", exc)
        sync.status = "failed"
        sync.last_error = str(exc)[:480]
        await db.commit()
        await db.refresh(sync)
        return sync

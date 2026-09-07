"""ABC Supply Product API (source: https://apidocs.abcsupply.com/search-items/).

Endpoints used:
  POST {PRODUCT_PREFIX}/search/items        (filters: contains itemDescription/itemNumber; equals itemNumber/branchNumber/productFamilyId; embed:["branches"]; ?familyItems=true)
  GET  {PRODUCT_PREFIX}/items/{assetId}/images   (image asset; "Image URLs available in a future release" per docs)

Branch availability is derived from the embedded `branches[]` on each item (item is available to PURCHASE
from a branch when that branch appears). ABC does NOT expose physical quantity-on-hand here, so callers must
present availability as "Available at Branch" / "Not Available at Branch" — never a stock number.
"""
from __future__ import annotations

from .client import AbcClient
from .config import PRODUCT_PREFIX

SEARCHABLE_KEYS = {"itemDescription", "itemNumber"}  # condition=contains


async def search_items(client: AbcClient, *, query: str | None = None, by: str = "itemDescription",
                       item_number: str | None = None, family_id: str | None = None,
                       branch_number: str | None = None, embed_branches: bool = True,
                       family_items: bool = False, items_per_page: int = 25, page_number: int = 1) -> dict:
    filters: list[dict] = []
    if item_number:
        filters.append({"key": "itemNumber", "condition": "equals", "values": [item_number], "joinCondition": None})
    elif family_id:
        filters.append({"key": "productFamilyId", "condition": "equals", "values": [family_id], "joinCondition": None})
    elif query:
        key = by if by in SEARCHABLE_KEYS else "itemDescription"
        filters.append({"key": key, "condition": "contains", "values": [query], "joinCondition": None})
    if branch_number:
        filters.append({"key": "branchNumber", "condition": "equals", "values": [branch_number], "joinCondition": "and"})
    body: dict = {"filters": filters, "pagination": {"itemsPerPage": items_per_page, "pageNumber": page_number}}
    if embed_branches:
        body["embed"] = ["branches"]
    path = f"{PRODUCT_PREFIX}/search/items" + ("?familyItems=true" if family_items else "")
    data = await client.post_json(path, json=body)
    return data if isinstance(data, dict) else {"items": []}


async def get_item(client: AbcClient, item_number: str) -> dict | None:
    data = await search_items(client, item_number=item_number, embed_branches=True, family_items=True, items_per_page=1)
    items = data.get("items") or []
    return items[0] if items else None


async def list_items(client: AbcClient, *, page_number: int = 1, items_per_page: int = 100,
                     since: str | None = None) -> dict:
    """Full-catalog retrieval for synchronization (GET {PRODUCT_PREFIX}/items).

    Paginate by passing page_number. `since` (ISO-8601) uses ABC's documented
    `sinceLastModifiedDateTime` filter to fetch only products changed since the last successful sync.
    Returns the raw ABC page dict: {"items": [...], "pagination": {...}}.
    """
    params: dict = {"itemsPerPage": items_per_page, "pageNumber": page_number, "embed": "branches"}
    if since:
        params["sinceLastModifiedDateTime"] = since
    data = await client.get_json(f"{PRODUCT_PREFIX}/items", params=params)
    return data if isinstance(data, dict) else {"items": []}


def item_available_at_branch(item: dict, branch_number: str | None) -> bool:
    if not branch_number:
        return False
    branches = item.get("branches") or []
    return any(str(b.get("number")) == str(branch_number) for b in branches)


# --- Product Availability API (source: https://apidocs.abcsupply.com/get-item-availability/) ---
# CRITICAL: availability is SEPARATE from pricing. ABC's Price Items docs state a price does NOT prove
# the item is currently available at the branch. Real-time orderability + dimensional variations come
# from this API. Endpoint: GET {PRODUCT_PREFIX}/availability/items/{itemNumber}/branches ->
#   {"branches": [{"number", "isDimensional", "variations": [{"length": {"value","uom",...}}]}]}
async def get_item_availability(client: AbcClient, item_number: str) -> dict:
    data = await client.get_json(f"{PRODUCT_PREFIX}/availability/items/{item_number}/branches")
    return data if isinstance(data, dict) else {"branches": []}


def availability_branch(availability: dict, branch_number: str | None) -> dict | None:
    """Return the availability entry for the selected branch, or None if the item is not orderable there."""
    if not branch_number:
        return None
    for b in availability.get("branches") or []:
        if str(b.get("number")) == str(branch_number):
            return b
    return None


def length_available(branch_entry: dict, length_value) -> bool:
    """True if the branch offers the requested dimensional length. Never silently substitutes a length:
    the requested value must match an available variation (string or numeric compare)."""
    if length_value is None or str(length_value).strip() == "":
        return True
    want = str(length_value).strip()
    for v in branch_entry.get("variations") or []:
        lv = (v.get("length") or {}).get("value")
        if lv is None:
            continue
        if str(lv).strip() == want:
            return True
        try:
            if float(lv) == float(length_value):
                return True
        except (TypeError, ValueError):
            pass
    return False


def primary_image_href(item: dict) -> str | None:
    for img in item.get("images") or []:
        if img.get("type") == "PrimaryProductImage" and img.get("href"):
            return img["href"]
    for img in item.get("images") or []:
        if img.get("href"):
            return img["href"]
    return None

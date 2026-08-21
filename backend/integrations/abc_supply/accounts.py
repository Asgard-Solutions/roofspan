"""ABC Supply Account API (source: https://apidocs.abcsupply.com/search-accounts/).

Endpoints:
  POST {ACCOUNT_PREFIX}/search/accounts
  GET  {ACCOUNT_PREFIX}/soldtos/{soldToNumber}
  GET  {ACCOUNT_PREFIX}/billtos/{billToNumber}
  GET  {ACCOUNT_PREFIX}/shiptos/{shipToNumber}
  GET  {ACCOUNT_PREFIX}/shiptos/{shipToNumber}/contacts

Per ABC guidance, Ship-To accounts with an empty `branches[]` array are retired ERP records
and are filtered out of user-facing results.
"""
from __future__ import annotations

from .client import AbcClient
from .config import ACCOUNT_PREFIX


def _filter_active_shiptos(ship_tos: list[dict]) -> list[dict]:
    out = []
    for st in ship_tos or []:
        if isinstance(st, dict) and st.get("branches"):
            out.append(st)
    return out


async def search_accounts(client: AbcClient, *, filters: list[dict] | None = None,
                          items_per_page: int = 50, page_number: int = 1) -> dict:
    body = {
        "filters": filters or [{"key": "storefront", "condition": "equals", "values": ["abc"]}],
        "pagination": {"itemsPerPage": items_per_page, "pageNumber": page_number},
    }
    data = await client.post_json(f"{ACCOUNT_PREFIX}/search/accounts", json=body)
    return data if isinstance(data, dict) else {}


async def list_ship_to_accounts(client: AbcClient, *, items_per_page: int = 50, page_number: int = 1) -> list[dict]:
    """Return only non-retired Ship-To accounts (branches[] non-empty)."""
    data = await search_accounts(
        client,
        filters=[
            {"key": "accountType", "condition": "equals", "values": ["Ship-to"], "joinCondition": "and"},
            {"key": "storefront", "condition": "equals", "values": ["abc"]},
        ],
        items_per_page=items_per_page,
        page_number=page_number,
    )
    return _filter_active_shiptos(data.get("shipTos") or [])


async def get_sold_to(client: AbcClient, number: str) -> dict:
    return await client.get_json(f"{ACCOUNT_PREFIX}/soldtos/{number}")  # type: ignore[return-value]


async def get_bill_to(client: AbcClient, number: str) -> dict:
    return await client.get_json(f"{ACCOUNT_PREFIX}/billtos/{number}")  # type: ignore[return-value]


async def get_ship_to(client: AbcClient, number: str) -> dict:
    return await client.get_json(f"{ACCOUNT_PREFIX}/shiptos/{number}")  # type: ignore[return-value]


async def get_ship_to_contacts(client: AbcClient, number: str) -> object:
    return await client.get_json(f"{ACCOUNT_PREFIX}/shiptos/{number}/contacts")

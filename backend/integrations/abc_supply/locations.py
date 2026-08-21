"""ABC Supply Location API (source: https://apidocs.abcsupply.com/search-branches/).

Endpoints:
  GET {LOCATION_PREFIX}/branches           (query by state OR lat/long/distance)
  GET {LOCATION_PREFIX}/branches/{branchNumber}
"""
from __future__ import annotations

from .client import AbcClient
from .config import LOCATION_PREFIX


async def search_branches(client: AbcClient, *, state: str | None = None,
                          lat: float | None = None, long: float | None = None,
                          distance: int | None = None) -> list[dict]:
    params: dict = {}
    if state:
        params["state"] = state
    if lat is not None and long is not None:
        params["lat"] = lat
        params["long"] = long
        if distance is not None:
            params["distance"] = distance
    data = await client.get_json(f"{LOCATION_PREFIX}/branches", params=params)
    return data if isinstance(data, list) else []


async def get_branch(client: AbcClient, branch_number: str) -> dict:
    data = await client.get_json(f"{LOCATION_PREFIX}/branches/{branch_number}")
    return data if isinstance(data, dict) else {}

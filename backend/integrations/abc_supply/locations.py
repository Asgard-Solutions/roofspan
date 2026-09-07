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


# Map ABC Get-Branch free-text service names -> RoofSpan deliveryService codes. ABC's Get Branch
# `services[].value` entries are marketing text (e.g. "Express Pickup"), not the order enum codes, so
# this best-effort mapping is used when an explicit code list is not present. (source: get-branch)
_SERVICE_TEXT_TO_CODE = [
    ("express pickup", "EXP"), ("customer pickup", "CPU"), ("will call", "CPU"), ("will-call", "CPU"),
    ("rooftop", "OTR"), ("roof top", "OTR"), ("roof delivery", "OTR"), ("our truck - roof", "OTR"),
    ("window", "OTW"), ("ground", "OTG"), ("our truck - ground", "OTG"),
    ("common carrier", "COM"), ("third-party", "TPC"), ("third party", "TPC"),
]


def branch_delivery_service_codes(branch_detail: dict) -> set[str] | None:
    """Resolve the set of RoofSpan deliveryService CODES currently offered by a branch from its Get-Branch
    detail. Returns None when it cannot be determined (caller MUST fail closed, never assume the global enum).
    Prefers an explicit `branch.deliveryServices` code list; otherwise best-effort maps `services[].value` text."""
    if not isinstance(branch_detail, dict):
        return None
    branch = branch_detail.get("branch") or {}
    explicit = branch.get("deliveryServices")
    if isinstance(explicit, list):
        codes = {str(c).strip().upper() for c in explicit if str(c).strip()}
        return codes or None
    text_blobs: list[str] = []
    for grp in branch_detail.get("services") or []:
        for v in (grp.get("value") or []):
            text_blobs.append(str(v).lower())
    if not text_blobs:
        return None
    joined = " | ".join(text_blobs)
    derived = {code for kw, code in _SERVICE_TEXT_TO_CODE if kw in joined}
    return derived or None

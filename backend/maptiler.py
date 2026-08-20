"""MapTiler geocoding helpers used by RoofSpan property imports.

The MapTiler key remains server-side in IntegrationSetting. Property imports use
forward address geocoding only as a location resolver; RentCast remains the
source for property/ownership attributes.
"""
from __future__ import annotations

import math
from urllib.parse import quote

import httpx

MAPTILER_GEOCODING_BASE = "https://api.maptiler.com/geocoding"
MAPTILER_BATCH_SIZE = 50


def _valid_coordinate_pair(coords) -> bool:
    return (
        isinstance(coords, (list, tuple))
        and len(coords) >= 2
        and isinstance(coords[0], (int, float))
        and isinstance(coords[1], (int, float))
        and math.isfinite(coords[0])
        and math.isfinite(coords[1])
        and -180 <= coords[0] <= 180
        and -90 <= coords[1] <= 90
    )


def best_address_feature(result: dict | None, min_relevance: float = 0.80) -> dict | None:
    """Return a high-confidence, house-number-level address feature.

    MapTiler documents the ``address`` field as the address number when applicable.
    Requiring it keeps RoofSpan from replacing a RentCast coordinate with a broader
    residential-street match that MapTiler also classifies as type ``address``.
    """
    if not isinstance(result, dict):
        return None
    features = result.get("features") or []
    if not features:
        return None
    feature = features[0]
    if not isinstance(feature, dict):
        return None
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates")
    if geometry.get("type") != "Point" or not _valid_coordinate_pair(coords):
        return None

    place_types = feature.get("place_type") or []
    if isinstance(place_types, str):
        place_types = [place_types]
    if "address" not in place_types:
        return None
    if not str(feature.get("address") or "").strip():
        return None

    relevance = feature.get("relevance")
    if relevance is not None:
        try:
            if float(relevance) < min_relevance:
                return None
        except (TypeError, ValueError):
            return None
    return feature


async def geocode_addresses_batch(
    key: str,
    addresses: list[str],
    *,
    bbox: tuple[float, float, float, float] | list[float] | None = None,
    country: str = "us",
    min_relevance: float = 0.80,
) -> list[dict | None]:
    """Forward-geocode addresses with MapTiler in batches of at most 50.

    Returns one accepted feature (or None) for every input address, preserving
    input order. Provider/network failures fail open so the import can retain
    the original RentCast coordinate instead of failing the whole job.
    """
    if not addresses:
        return []

    resolved: list[dict | None] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for start in range(0, len(addresses), MAPTILER_BATCH_SIZE):
            chunk = addresses[start:start + MAPTILER_BATCH_SIZE]
            encoded_queries = ";".join(quote(address, safe=",") for address in chunk)
            url = f"{MAPTILER_GEOCODING_BASE}/{encoded_queries}.json"
            params = {
                "key": key,
                "types": "address",
                "limit": 1,
                "country": country,
                "autocomplete": "false",
            }
            if bbox:
                params["bbox"] = ",".join(str(v) for v in bbox)
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
                # Batch requests return one GeoJSON search-result object per query.
                # A one-item request may be returned as a single object.
                batch_results = payload if isinstance(payload, list) else [payload]
                if len(batch_results) != len(chunk):
                    resolved.extend([None] * len(chunk))
                    continue
                resolved.extend(best_address_feature(item, min_relevance) for item in batch_results)
            except (httpx.HTTPError, ValueError, TypeError):
                resolved.extend([None] * len(chunk))
    return resolved

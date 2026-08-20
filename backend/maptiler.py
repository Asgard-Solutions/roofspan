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


def evaluate_address_result(result: dict | None, min_relevance: float = 0.80) -> dict:
    """Evaluate one MapTiler result and return safe diagnostics plus accepted feature."""
    diagnostic = {
        "status": "rejected",
        "reason": "no_result",
        "feature": None,
        "returned_address": None,
        "relevance": None,
        "place_type": None,
        "latitude": None,
        "longitude": None,
        "feature_id": None,
    }
    if not isinstance(result, dict):
        diagnostic["reason"] = "invalid_response"
        return diagnostic

    features = result.get("features") or []
    if not features:
        diagnostic["reason"] = "no_result"
        return diagnostic

    feature = features[0]
    if not isinstance(feature, dict):
        diagnostic["reason"] = "invalid_feature"
        return diagnostic

    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates")
    place_types = feature.get("place_type") or []
    if isinstance(place_types, str):
        place_types = [place_types]
    relevance = feature.get("relevance")
    returned_address = str(feature.get("address") or "").strip() or None

    diagnostic.update({
        "returned_address": returned_address,
        "relevance": relevance,
        "place_type": place_types,
        "feature_id": feature.get("id"),
    })
    if _valid_coordinate_pair(coords):
        diagnostic["longitude"] = coords[0]
        diagnostic["latitude"] = coords[1]

    if geometry.get("type") != "Point" or not _valid_coordinate_pair(coords):
        diagnostic["reason"] = "invalid_coordinates"
        return diagnostic
    if "address" not in place_types:
        diagnostic["reason"] = "not_address_result"
        return diagnostic
    if not returned_address:
        diagnostic["reason"] = "no_house_number"
        return diagnostic
    if relevance is not None:
        try:
            if float(relevance) < min_relevance:
                diagnostic["reason"] = "low_relevance"
                return diagnostic
        except (TypeError, ValueError):
            diagnostic["reason"] = "invalid_relevance"
            return diagnostic

    diagnostic["status"] = "accepted"
    diagnostic["reason"] = "accepted"
    diagnostic["feature"] = feature
    return diagnostic


def best_address_feature(result: dict | None, min_relevance: float = 0.80) -> dict | None:
    """Backward-compatible helper returning only the accepted address feature."""
    return evaluate_address_result(result, min_relevance).get("feature")


async def geocode_addresses_batch(
    key: str,
    addresses: list[str],
    *,
    bbox: tuple[float, float, float, float] | list[float] | None = None,
    country: str = "us",
    min_relevance: float = 0.80,
) -> list[dict]:
    """Forward-geocode addresses and return one diagnostic record per input address.

    Provider/network failures fail open so imports can retain RentCast coordinates,
    while recording why MapTiler was not used.
    """
    if not addresses:
        return []

    resolved: list[dict] = []
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
                http_status = response.status_code
                response.raise_for_status()
                payload = response.json()
                batch_results = payload if isinstance(payload, list) else [payload]
                if len(batch_results) != len(chunk):
                    resolved.extend([
                        {
                            "status": "error",
                            "reason": "batch_result_count_mismatch",
                            "http_status": http_status,
                            "feature": None,
                            "returned_address": None,
                            "relevance": None,
                            "place_type": None,
                            "latitude": None,
                            "longitude": None,
                            "feature_id": None,
                        }
                        for _ in chunk
                    ])
                    continue
                for item in batch_results:
                    diagnostic = evaluate_address_result(item, min_relevance)
                    diagnostic["http_status"] = http_status
                    resolved.append(diagnostic)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else None
                resolved.extend([
                    {
                        "status": "error",
                        "reason": "provider_http_error",
                        "http_status": status,
                        "feature": None,
                        "returned_address": None,
                        "relevance": None,
                        "place_type": None,
                        "latitude": None,
                        "longitude": None,
                        "feature_id": None,
                    }
                    for _ in chunk
                ])
            except (httpx.HTTPError, ValueError, TypeError):
                resolved.extend([
                    {
                        "status": "error",
                        "reason": "provider_request_error",
                        "http_status": None,
                        "feature": None,
                        "returned_address": None,
                        "relevance": None,
                        "place_type": None,
                        "latitude": None,
                        "longitude": None,
                        "feature_id": None,
                    }
                    for _ in chunk
                ])
    return resolved

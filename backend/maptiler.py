"""MapTiler geocoding helpers used by RoofSpan property imports.

The MapTiler key remains server-side in IntegrationSetting. Property imports use
forward address geocoding only as a location resolver; RentCast remains the
source for property/ownership attributes.
"""
from __future__ import annotations

import math
import re
from urllib.parse import quote

import httpx

MAPTILER_GEOCODING_BASE = "https://api.maptiler.com/geocoding"
MAPTILER_BATCH_SIZE = 50

_STREET_SUFFIXES = {
    "avenue": "ave", "ave": "ave", "av": "ave",
    "street": "st", "st": "st",
    "road": "rd", "rd": "rd",
    "drive": "dr", "dr": "dr",
    "lane": "ln", "ln": "ln",
    "court": "ct", "ct": "ct",
    "circle": "cir", "cir": "cir",
    "boulevard": "blvd", "blvd": "blvd",
    "highway": "hwy", "hwy": "hwy",
    "parkway": "pkwy", "pkwy": "pkwy",
    "place": "pl", "pl": "pl",
    "terrace": "ter", "ter": "ter",
    "trail": "trl", "trl": "trl",
    "way": "way",
}
_DIRECTIONALS = {
    "north": "n", "n": "n",
    "south": "s", "s": "s",
    "east": "e", "e": "e",
    "west": "w", "w": "w",
    "northeast": "ne", "ne": "ne",
    "northwest": "nw", "nw": "nw",
    "southeast": "se", "se": "se",
    "southwest": "sw", "sw": "sw",
}
_STATE_CODES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "florida": "fl", "georgia": "ga", "hawaii": "hi", "idaho": "id",
    "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms",
    "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "new hampshire": "nh", "new jersey": "nj", "new mexico": "nm", "new york": "ny",
    "north carolina": "nc", "north dakota": "nd", "ohio": "oh", "oklahoma": "ok",
    "oregon": "or", "pennsylvania": "pa", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa", "west virginia": "wv",
    "wisconsin": "wi", "wyoming": "wy", "district of columbia": "dc",
}
_STATE_CODES.update({code: code for code in _STATE_CODES.values()})


def _clean(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _normalize_street(value: str | None) -> str:
    tokens = _clean(value).split()
    normalized = []
    for token in tokens:
        token = _DIRECTIONALS.get(token, token)
        token = _STREET_SUFFIXES.get(token, token)
        normalized.append(token)
    return " ".join(normalized)


def _normalize_state(value: str | None) -> str:
    cleaned = _clean(value)
    return _STATE_CODES.get(cleaned, cleaned)


def _normalize_zip(value: str | None) -> str:
    match = re.search(r"\b(\d{5})(?:-\d{4})?\b", str(value or ""))
    return match.group(1) if match else ""


def _parse_query_address(query: str) -> dict:
    """Parse RoofSpan's formatted US property address into identity components."""
    parts = [part.strip() for part in str(query or "").split(",")]
    line1 = parts[0] if parts else ""
    city = parts[1] if len(parts) > 1 else ""
    state_zip = parts[2] if len(parts) > 2 else ""

    line_match = re.match(r"^\s*([0-9]+[A-Za-z]?(?:-[0-9A-Za-z]+)?)\s+(.+?)\s*$", line1)
    house_number = _clean(line_match.group(1)) if line_match else ""
    street = _normalize_street(line_match.group(2)) if line_match else ""

    state_match = re.match(r"^\s*([A-Za-z .]+?)\s+(\d{5}(?:-\d{4})?)\s*$", state_zip)
    state = _normalize_state(state_match.group(1)) if state_match else ""
    zip_code = _normalize_zip(state_match.group(2)) if state_match else _normalize_zip(state_zip)

    return {
        "house_number": house_number,
        "street": street,
        "city": _clean(city),
        "state": state,
        "zip_code": zip_code,
    }


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


def _context_values(feature: dict) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for item in feature.get("context") or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        kind = item_id.split(".", 1)[0] if "." in item_id else str(item.get("place_type") or "")
        values.setdefault(kind, []).extend(
            str(v) for v in (item.get("text"), item.get("matching_text")) if v
        )
        if item.get("country_code"):
            values.setdefault("country_code", []).append(str(item["country_code"]))
    return values


def _first_context(values: dict[str, list[str]], kinds: tuple[str, ...]) -> str:
    for kind in kinds:
        for value in values.get(kind, []):
            if value:
                return value
    return ""


def _feature_identity(feature: dict) -> dict:
    context = _context_values(feature)
    return {
        "house_number": _clean(feature.get("address")),
        "street": _normalize_street(feature.get("text") or feature.get("matching_text")),
        "city": _clean(_first_context(context, (
            "municipality", "locality", "place", "joint_municipality", "municipal_district"
        ))),
        "state": _normalize_state(_first_context(context, ("region", "subregion"))),
        "zip_code": _normalize_zip(_first_context(context, ("postal_code",))),
        "country": _clean(_first_context(context, ("country_code", "country"))),
    }


def _identity_match(expected: dict, actual: dict) -> tuple[bool, str, dict]:
    checks = {
        "house_number": bool(expected["house_number"] and actual["house_number"] == expected["house_number"]),
        "street": bool(expected["street"] and actual["street"] == expected["street"]),
        "city": bool(expected["city"] and actual["city"] == expected["city"]),
        "state": bool(expected["state"] and actual["state"] == expected["state"]),
        "zip_code": bool(expected["zip_code"] and actual["zip_code"] == expected["zip_code"]),
    }
    if not expected["house_number"] or not expected["street"] or not expected["state"] or not expected["zip_code"]:
        return False, "query_identity_incomplete", checks
    if not actual["house_number"]:
        return False, "no_house_number", checks
    if not checks["house_number"]:
        return False, "house_number_mismatch", checks
    if not actual["street"]:
        return False, "returned_street_missing", checks
    if not checks["street"]:
        return False, "street_mismatch", checks
    if not actual["zip_code"]:
        return False, "returned_zip_missing", checks
    if not checks["zip_code"]:
        return False, "zip_mismatch", checks
    if not actual["state"]:
        return False, "returned_state_missing", checks
    if not checks["state"]:
        return False, "state_mismatch", checks
    if expected["city"]:
        if not actual["city"]:
            return False, "returned_city_missing", checks
        if not checks["city"]:
            return False, "city_mismatch", checks
    return True, "exact_address_identity", checks


def _empty_diagnostic(status="rejected", reason="no_result") -> dict:
    return {
        "status": status,
        "reason": reason,
        "feature": None,
        "returned_address": None,
        "returned_label": None,
        "relevance": None,
        "place_type": None,
        "latitude": None,
        "longitude": None,
        "feature_id": None,
        "http_status": None,
        "identity_expected": None,
        "identity_returned": None,
        "identity_checks": None,
    }


def evaluate_address_result(result: dict | None, min_relevance: float = 0.80, query_address: str | None = None) -> dict:
    """Evaluate MapTiler candidates and accept only an exact property-address identity match."""
    diagnostic = _empty_diagnostic()
    if not isinstance(result, dict):
        diagnostic["reason"] = "invalid_response"
        return diagnostic

    features = result.get("features") or []
    if not features:
        return diagnostic

    expected = _parse_query_address(query_address or "") if query_address else None
    best_rejection = None

    for feature in features:
        candidate = _empty_diagnostic()
        if not isinstance(feature, dict):
            candidate["reason"] = "invalid_feature"
            best_rejection = best_rejection or candidate
            continue

        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates")
        place_types = feature.get("place_type") or []
        if isinstance(place_types, str):
            place_types = [place_types]
        relevance = feature.get("relevance")
        returned_address = str(feature.get("address") or "").strip() or None
        returned_label = feature.get("place_name") or feature.get("matching_place_name") or feature.get("text")
        actual = _feature_identity(feature)

        candidate.update({
            "returned_address": returned_address,
            "returned_label": returned_label,
            "relevance": relevance,
            "place_type": place_types,
            "feature_id": feature.get("id"),
            "identity_expected": expected,
            "identity_returned": actual,
        })
        if _valid_coordinate_pair(coords):
            candidate["longitude"] = coords[0]
            candidate["latitude"] = coords[1]

        if geometry.get("type") != "Point" or not _valid_coordinate_pair(coords):
            candidate["reason"] = "invalid_coordinates"
            best_rejection = best_rejection or candidate
            continue
        if "address" not in place_types:
            candidate["reason"] = "not_address_result"
            best_rejection = best_rejection or candidate
            continue
        if relevance is not None:
            try:
                if float(relevance) < min_relevance:
                    candidate["reason"] = "low_relevance"
                    best_rejection = best_rejection or candidate
                    continue
            except (TypeError, ValueError):
                candidate["reason"] = "invalid_relevance"
                best_rejection = best_rejection or candidate
                continue

        if expected is not None:
            matched, reason, checks = _identity_match(expected, actual)
            candidate["identity_checks"] = checks
            if not matched:
                candidate["reason"] = reason
                # Prefer the most relevant rejected candidate for diagnostics.
                if best_rejection is None or float(relevance or 0) > float(best_rejection.get("relevance") or 0):
                    best_rejection = candidate
                continue
        elif not returned_address:
            candidate["reason"] = "no_house_number"
            best_rejection = best_rejection or candidate
            continue

        candidate["status"] = "accepted"
        candidate["reason"] = "exact_address_identity" if expected is not None else "accepted"
        candidate["feature"] = feature
        return candidate

    return best_rejection or diagnostic


def best_address_feature(result: dict | None, min_relevance: float = 0.80, query_address: str | None = None) -> dict | None:
    """Backward-compatible helper returning only the accepted address feature."""
    return evaluate_address_result(result, min_relevance, query_address).get("feature")


async def geocode_addresses_batch(
    key: str,
    addresses: list[str],
    *,
    bbox: tuple[float, float, float, float] | list[float] | None = None,
    country: str = "us",
    min_relevance: float = 0.80,
) -> list[dict]:
    """Forward-geocode addresses and return one strict diagnostic record per input address."""
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
                "limit": 5,
                "country": country,
                "autocomplete": "false",
                "fuzzyMatch": "false",
                "worldview": "us",
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
                    for _ in chunk:
                        diagnostic = _empty_diagnostic("error", "batch_result_count_mismatch")
                        diagnostic["http_status"] = http_status
                        resolved.append(diagnostic)
                    continue
                for query_address, item in zip(chunk, batch_results):
                    diagnostic = evaluate_address_result(item, min_relevance, query_address=query_address)
                    diagnostic["http_status"] = http_status
                    resolved.append(diagnostic)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else None
                for _ in chunk:
                    diagnostic = _empty_diagnostic("error", "provider_http_error")
                    diagnostic["http_status"] = status
                    resolved.append(diagnostic)
            except (httpx.HTTPError, ValueError, TypeError):
                for _ in chunk:
                    resolved.append(_empty_diagnostic("error", "provider_request_error"))
    return resolved

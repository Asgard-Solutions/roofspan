"""Mapbox Geocoding v6 permanent geocoding for RoofSpan property pin placement.

RentCast remains authoritative for property/address attributes. Mapbox is used only to turn the
known stored address into a better coordinate. RoofSpan calls the v6 batch endpoint with
permanent=true so completed results may be stored in the local PostgreSQL database and reused
without repeated geocoding requests.
"""
from __future__ import annotations

import math
import re
from typing import Any

import httpx

MAPBOX_BATCH_URL = "https://api.mapbox.com/search/geocode/v6/batch"
MAPBOX_BATCH_SIZE = 1000
USABLE_ACCURACY = {"rooftop", "parcel", "point", "interpolated"}
HIGH_ACCURACY = {"rooftop", "parcel", "point"}

_DIRECTIONALS = {
    "north": "n", "n": "n", "south": "s", "s": "s", "east": "e", "e": "e", "west": "w", "w": "w",
    "northeast": "ne", "ne": "ne", "northwest": "nw", "nw": "nw",
    "southeast": "se", "se": "se", "southwest": "sw", "sw": "sw",
}
_SUFFIXES = {
    "avenue": "ave", "ave": "ave", "av": "ave", "street": "st", "st": "st",
    "road": "rd", "rd": "rd", "drive": "dr", "dr": "dr", "lane": "ln", "ln": "ln",
    "court": "ct", "ct": "ct", "circle": "cir", "cir": "cir", "boulevard": "blvd", "blvd": "blvd",
    "highway": "hwy", "hwy": "hwy", "parkway": "pkwy", "pkwy": "pkwy", "place": "pl", "pl": "pl",
    "terrace": "ter", "ter": "ter", "trail": "trl", "trl": "trl", "way": "way",
}


def _clean(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _normalize_street(value: Any) -> str:
    tokens = []
    for token in _clean(value).split():
        token = _DIRECTIONALS.get(token, token)
        token = _SUFFIXES.get(token, token)
        tokens.append(token)
    return " ".join(tokens)


def _normalize_zip(value: Any) -> str:
    match = re.search(r"\b(\d{5})(?:-\d{4})?\b", str(value or ""))
    return match.group(1) if match else ""


def _split_street_line(value: str) -> tuple[str, str]:
    match = re.match(r"^\s*([0-9]+[A-Za-z]?(?:-[0-9A-Za-z]+)?)\s+(.+?)\s*$", str(value or ""))
    if not match:
        return "", _normalize_street(value)
    return _clean(match.group(1)), _normalize_street(match.group(2))


def _empty(status: str = "rejected", reason: str = "no_result") -> dict:
    return {
        "status": status,
        "reason": reason,
        "http_status": None,
        "latitude": None,
        "longitude": None,
        "formatted_address": None,
        "accuracy": None,
        "confidence": None,
        "mapbox_id": None,
        "match_code": None,
        "location_quality": None,
        "routable_points": None,
    }


def _candidate_identity(feature: dict) -> dict:
    props = feature.get("properties") or {}
    context = props.get("context") or {}
    address = context.get("address") or {}
    street = context.get("street") or {}
    place = context.get("place") or {}
    region = context.get("region") or {}
    postcode = context.get("postcode") or {}
    return {
        "house_number": _clean(address.get("address_number")),
        "street": _normalize_street(address.get("street_name") or street.get("name")),
        "city": _clean(place.get("name")),
        "state": _clean(region.get("region_code") or region.get("name")),
        "zip_code": _normalize_zip(postcode.get("name")),
    }


def _expected_identity(record: dict) -> dict:
    number, street = _split_street_line(record.get("address_line1") or "")
    return {
        "house_number": number,
        "street": street,
        "city": _clean(record.get("city")),
        "state": _clean(record.get("state")),
        "zip_code": _normalize_zip(record.get("zip_code")),
    }


def _critical_match_ok(match_code: dict, accuracy: str) -> tuple[bool, str]:
    house = str(match_code.get("address_number") or "").lower()
    street = str(match_code.get("street") or "").lower()
    postcode = str(match_code.get("postcode") or "").lower()
    place = str(match_code.get("place") or "").lower()
    region = str(match_code.get("region") or "").lower()
    confidence = str(match_code.get("confidence") or "").lower()

    if house not in ({"matched", "plausible"} if accuracy == "interpolated" else {"matched"}):
        return False, "house_number_mismatch"
    if street != "matched":
        return False, "street_mismatch"
    if postcode not in {"matched", "not_applicable"}:
        return False, "zip_mismatch"
    if place not in {"matched", "not_applicable"}:
        return False, "city_mismatch"
    if region not in {"matched", "not_applicable"}:
        return False, "state_mismatch"
    if confidence not in {"exact", "high", "medium"}:
        return False, "low_confidence"
    return True, "known_address_match"


def evaluate_mapbox_result(result: dict | None, record: dict) -> dict:
    """Select a property-level Mapbox result for the authoritative RentCast address."""
    if not isinstance(result, dict):
        return _empty("error", "invalid_response")
    features = result.get("features") or []
    if not isinstance(features, list) or not features:
        return _empty()

    expected = _expected_identity(record)
    best_rejection = None

    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        if props.get("feature_type") != "address":
            continue
        coords_obj = props.get("coordinates") or {}
        lat = coords_obj.get("latitude")
        lng = coords_obj.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)) or not math.isfinite(lat) or not math.isfinite(lng):
            continue

        accuracy = str(coords_obj.get("accuracy") or "").lower()
        match_code = props.get("match_code") or {}
        confidence = str(match_code.get("confidence") or "").lower() or None
        diagnostic = _empty()
        diagnostic.update({
            "latitude": float(lat),
            "longitude": float(lng),
            "formatted_address": props.get("full_address") or " ".join(v for v in (props.get("name"), props.get("place_formatted")) if v),
            "accuracy": accuracy or None,
            "confidence": confidence,
            "mapbox_id": props.get("mapbox_id") or feature.get("id"),
            "match_code": match_code,
            "routable_points": coords_obj.get("routable_points"),
            "identity_returned": _candidate_identity(feature),
            "identity_expected": expected,
        })

        if accuracy not in USABLE_ACCURACY:
            diagnostic["reason"] = "insufficient_precision"
            best_rejection = best_rejection or diagnostic
            continue

        ok, reason = _critical_match_ok(match_code, accuracy)
        if not ok:
            diagnostic["reason"] = reason
            best_rejection = best_rejection or diagnostic
            continue

        diagnostic["status"] = "located"
        diagnostic["reason"] = "known_address_located"
        diagnostic["location_quality"] = "high" if accuracy in HIGH_ACCURACY else "approximate"
        return diagnostic

    return best_rejection or _empty()


def make_query(record: dict, bbox: list[float] | tuple[float, float, float, float] | None = None) -> dict:
    number, street = _split_street_line(record.get("address_line1") or "")
    query = {
        "types": ["address"],
        "country": "us",
        "address_number": number,
        "street": street,
        "place": record.get("city") or "",
        "region": record.get("state") or "",
        "postcode": record.get("zip_code") or "",
        "autocomplete": False,
        "limit": 5,
    }
    lat = record.get("rentcast_latitude")
    lng = record.get("rentcast_longitude")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        query["proximity"] = [lng, lat]
    if bbox:
        query["bbox"] = list(bbox)
    return query


async def geocode_batch(
    access_token: str,
    records: list[dict],
    *,
    bbox: list[float] | tuple[float, float, float, float] | None = None,
) -> dict[str, dict]:
    """Run Mapbox v6 permanent batch geocoding and return diagnostics keyed by RoofSpan property id."""
    if not records:
        return {}

    output: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=90) as client:
        for start in range(0, len(records), MAPBOX_BATCH_SIZE):
            chunk = records[start:start + MAPBOX_BATCH_SIZE]
            body = [make_query(record, bbox=bbox) for record in chunk]
            try:
                response = await client.post(
                    MAPBOX_BATCH_URL,
                    params={"access_token": access_token, "permanent": "true"},
                    json=body,
                )
                http_status = response.status_code
                response.raise_for_status()
                payload = response.json()
                batch = payload.get("batch") if isinstance(payload, dict) else None
                if not isinstance(batch, list) or len(batch) != len(chunk):
                    for record in chunk:
                        diagnostic = _empty("error", "batch_result_count_mismatch")
                        diagnostic["http_status"] = http_status
                        output[str(record["id"])] = diagnostic
                    continue
                for record, item in zip(chunk, batch):
                    diagnostic = evaluate_mapbox_result(item, record)
                    diagnostic["http_status"] = http_status
                    output[str(record["id"])] = diagnostic
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else None
                for record in chunk:
                    diagnostic = _empty("error", "provider_http_error")
                    diagnostic["http_status"] = status
                    output[str(record["id"])] = diagnostic
            except (httpx.HTTPError, ValueError, TypeError):
                for record in chunk:
                    output[str(record["id"])] = _empty("error", "provider_request_error")
    return output

"""Geocodio forward-geocoding helpers for RoofSpan property pin placement.

RentCast remains authoritative for property/address attributes. Geocodio is used only to turn the
known stored address into a more accurate coordinate. Only a small, safe diagnostic subset is
returned so the caller can persist the permanent geocode locally without keeping raw provider data.
"""
from __future__ import annotations

import math
import re
from typing import Any

import httpx

GEOCODIO_GEOCODE_URL = "https://api.geocod.io/v2/geocode"
GEOCODIO_BATCH_SIZE = 100
MIN_ACCURACY = 0.80

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
USABLE_ACCURACY_TYPES = {"rooftop", "point", "range_interpolation"}


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
        "accuracy_type": None,
        "match_type": None,
        "source": None,
        "stable_address_key": None,
        "address_components": None,
        "identity_checks": None,
        "location_quality": None,
    }


def _identity_checks(candidate: dict, expected: dict) -> tuple[bool, str, dict]:
    components = candidate.get("address_components") or {}
    returned_number = _clean(components.get("number"))
    returned_street = _normalize_street(components.get("formatted_street") or " ".join(
        str(v) for v in (
            components.get("predirectional"), components.get("street"), components.get("suffix"), components.get("postdirectional")
        ) if v
    ))
    checks = {
        "house_number": bool(expected.get("house_number") and returned_number == expected.get("house_number")),
        "street": bool(expected.get("street") and returned_street == expected.get("street")),
        "city": bool(expected.get("city") and _clean(components.get("city")) == expected.get("city")),
        "state": bool(expected.get("state") and _clean(components.get("state_province")) == expected.get("state")),
        "zip_code": bool(expected.get("zip_code") and _normalize_zip(components.get("postal_code")) == expected.get("zip_code")),
    }
    for key, reason in (
        ("house_number", "house_number_mismatch"),
        ("street", "street_mismatch"),
        ("city", "city_mismatch"),
        ("state", "state_mismatch"),
        ("zip_code", "zip_mismatch"),
    ):
        if expected.get(key) and not checks[key]:
            return False, reason, checks
    return True, "known_address_match", checks


def evaluate_geocodio_results(results: list[dict] | None, expected: dict) -> dict:
    """Select the most precise result that still matches the authoritative RentCast address."""
    if not isinstance(results, list) or not results:
        return _empty()

    ranked: list[tuple[int, float, dict]] = []
    rank = {"rooftop": 3, "point": 2, "range_interpolation": 1}
    best_rejection = None

    for candidate in results:
        if not isinstance(candidate, dict):
            continue
        loc = candidate.get("location") or {}
        lat, lng = loc.get("lat"), loc.get("lng")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)) or not math.isfinite(lat) or not math.isfinite(lng):
            continue
        accuracy_type = str(candidate.get("accuracy_type") or "").lower()
        try:
            accuracy = float(candidate.get("accuracy"))
        except (TypeError, ValueError):
            accuracy = 0.0

        matched, reason, checks = _identity_checks(candidate, expected)
        diagnostic = _empty()
        diagnostic.update({
            "reason": reason,
            "latitude": float(lat),
            "longitude": float(lng),
            "formatted_address": candidate.get("formatted_address"),
            "accuracy": accuracy,
            "accuracy_type": accuracy_type or None,
            "match_type": candidate.get("match_type"),
            "source": candidate.get("source"),
            "stable_address_key": candidate.get("stable_address_key"),
            "address_components": candidate.get("address_components"),
            "identity_checks": checks,
        })

        if not matched:
            if best_rejection is None or accuracy > float(best_rejection.get("accuracy") or 0):
                best_rejection = diagnostic
            continue
        if accuracy < MIN_ACCURACY:
            diagnostic["reason"] = "low_accuracy"
            best_rejection = diagnostic if best_rejection is None or accuracy > float(best_rejection.get("accuracy") or 0) else best_rejection
            continue
        if accuracy_type not in USABLE_ACCURACY_TYPES:
            diagnostic["reason"] = "insufficient_precision"
            best_rejection = diagnostic if best_rejection is None or accuracy > float(best_rejection.get("accuracy") or 0) else best_rejection
            continue
        ranked.append((rank.get(accuracy_type, 0), accuracy, diagnostic))

    if not ranked:
        return best_rejection or _empty()

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    chosen = ranked[0][2]
    chosen["status"] = "located"
    chosen["reason"] = "known_address_located"
    chosen["location_quality"] = "high" if chosen.get("accuracy_type") in {"rooftop", "point"} else "approximate"
    return chosen


def make_query(record: dict) -> tuple[dict, dict]:
    """Build structured Geocodio input plus the identity used to validate the returned point."""
    street_line = str(record.get("address_line1") or "").strip()
    number, street = _split_street_line(street_line)
    expected = {
        "house_number": number,
        "street": street,
        "city": _clean(record.get("city")),
        "state": _clean(record.get("state")),
        "zip_code": _normalize_zip(record.get("zip_code")),
    }
    query = {
        "street": street_line,
        "city": record.get("city") or "",
        "state_province": record.get("state") or "",
        "postal_code": record.get("zip_code") or "",
        "country": "US",
    }
    return query, expected


async def geocode_batch(api_key: str, records: list[dict]) -> dict[str, dict]:
    """Geocode records in provider-supported batches while preserving caller IDs."""
    if not records:
        return {}

    output: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=90) as client:
        for start in range(0, len(records), GEOCODIO_BATCH_SIZE):
            chunk = records[start:start + GEOCODIO_BATCH_SIZE]
            body = {}
            expected_by_id = {}
            for record in chunk:
                rid = str(record["id"])
                query, expected = make_query(record)
                body[rid] = query
                expected_by_id[rid] = expected

            try:
                response = await client.post(
                    GEOCODIO_GEOCODE_URL,
                    params={"api_key": api_key, "limit": 5},
                    json=body,
                )
                http_status = response.status_code
                response.raise_for_status()
                payload = response.json()
                wrapped = payload.get("results") if isinstance(payload, dict) else None
                wrapped = wrapped if isinstance(wrapped, dict) else {}
                for rid in body:
                    entry = wrapped.get(rid) or {}
                    results = ((entry.get("response") or {}).get("results")) if isinstance(entry, dict) else None
                    diagnostic = evaluate_geocodio_results(results, expected_by_id[rid])
                    diagnostic["http_status"] = http_status
                    output[rid] = diagnostic
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else None
                for rid in body:
                    diagnostic = _empty("error", "provider_http_error")
                    diagnostic["http_status"] = status
                    output[rid] = diagnostic
            except (httpx.HTTPError, ValueError, TypeError):
                for rid in body:
                    output[rid] = _empty("error", "provider_request_error")
    return output

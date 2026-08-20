"""MapTiler location helpers used by RoofSpan property imports.

RentCast remains the source for property and ownership attributes. MapTiler is
used to resolve the RentCast address, and when possible RoofSpan then refines
that accepted address to the matching MapTiler building-number/building feature.
All provider credentials stay server-side.
"""
from __future__ import annotations

import math
import re
from urllib.parse import quote

import httpx
from mapbox_vector_tile import decode as decode_vector_tile
from shapely.geometry import Point, shape

MAPTILER_GEOCODING_BASE = "https://api.maptiler.com/geocoding"
MAPTILER_TILES_BASE = "https://api.maptiler.com/tiles"
MAPTILER_BATCH_SIZE = 50
MAPTILER_BUILDING_ZOOM = 15
MAPTILER_BUILDING_SEARCH_FEET = 2000.0
MAPTILER_BUILDING_AMBIGUITY_FEET = 150.0

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
        "building_status": "not_attempted",
        "building_reason": "not_attempted",
        "building_number": None,
        "building_number_latitude": None,
        "building_number_longitude": None,
        "building_distance_feet": None,
        "building_class": None,
        "building_subclass": None,
        "building_feature_id": None,
        "building_latitude": None,
        "building_longitude": None,
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


def _tile_xy(lng: float, lat: float, z: int) -> tuple[int, int]:
    n = 2 ** z
    x = int((lng + 180.0) / 360.0 * n)
    lat_rad = math.radians(max(min(lat, 85.05112878), -85.05112878))
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def _tile_neighborhood(lng: float, lat: float, z: int) -> list[tuple[int, int]]:
    x, y = _tile_xy(lng, lat, z)
    n = 2 ** z
    return [
        (tx, ty)
        for tx in range(max(0, x - 1), min(n - 1, x + 1) + 1)
        for ty in range(max(0, y - 1), min(n - 1, y + 1) + 1)
    ]


def _tile_coord_to_lonlat(px: float, py: float, *, z: int, x: int, y: int, extent: int) -> tuple[float, float]:
    n = 2 ** z
    gx = x + (px / extent)
    gy = y + (1.0 - (py / extent))
    lng = gx / n * 360.0 - 180.0
    merc_y = math.pi * (1.0 - 2.0 * gy / n)
    lat = math.degrees(math.atan(math.sinh(merc_y)))
    return lng, lat


def _transform_geometry_coordinates(value, *, z: int, x: int, y: int, extent: int):
    if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(v, (int, float)) for v in value[:2]):
        lng, lat = _tile_coord_to_lonlat(value[0], value[1], z=z, x=x, y=y, extent=extent)
        if len(value) > 2:
            return [lng, lat, *value[2:]]
        return [lng, lat]
    if isinstance(value, (list, tuple)):
        return [_transform_geometry_coordinates(v, z=z, x=x, y=y, extent=extent) for v in value]
    return value


def _decode_layer(raw: bytes, layer_name: str, *, z: int, x: int, y: int) -> list[dict]:
    decoded = decode_vector_tile(raw, default_options={"geojson": True})
    layer = decoded.get(layer_name) or {}
    extent = int(layer.get("extent") or 4096)
    features = []
    for feature in layer.get("features") or []:
        if not isinstance(feature, dict):
            continue
        copied = dict(feature)
        geometry = dict(copied.get("geometry") or {})
        geometry["coordinates"] = _transform_geometry_coordinates(
            geometry.get("coordinates"), z=z, x=x, y=y, extent=extent
        )
        copied["geometry"] = geometry
        features.append(copied)
    return features


async def _tile_layer_features(
    client: httpx.AsyncClient,
    key: str,
    tileset: str,
    layer: str,
    z: int,
    tiles: list[tuple[int, int]],
    cache: dict,
) -> list[dict]:
    collected: list[dict] = []
    for x, y in tiles:
        cache_key = (tileset, layer, z, x, y)
        if cache_key in cache:
            collected.extend(cache[cache_key])
            continue
        url = f"{MAPTILER_TILES_BASE}/{tileset}/{z}/{x}/{y}"
        try:
            response = await client.get(url, params={"key": key})
            if response.status_code == 204:
                features = []
            else:
                response.raise_for_status()
                features = _decode_layer(response.content, layer, z=z, x=x, y=y)
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            features = []
        cache[cache_key] = features
        collected.extend(features)
    return collected


def _distance_feet(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    radius_miles = 3958.7613
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    miles = 2 * radius_miles * math.asin(min(1.0, math.sqrt(a)))
    return miles * 5280.0


def _number_point(feature: dict) -> tuple[float, float] | None:
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates")
    if geometry.get("type") != "Point" or not _valid_coordinate_pair(coords):
        return None
    return float(coords[0]), float(coords[1])


def _choose_number_feature(features: list[dict], house_number: str, geocode_lng: float, geocode_lat: float) -> tuple[dict | None, float | None, str]:
    matches = []
    expected = _clean(house_number)
    for feature in features:
        props = feature.get("properties") or {}
        if _clean(props.get("number")) != expected:
            continue
        point = _number_point(feature)
        if not point:
            continue
        lng, lat = point
        distance = _distance_feet(geocode_lng, geocode_lat, lng, lat)
        if distance <= MAPTILER_BUILDING_SEARCH_FEET:
            matches.append((distance, feature))

    if not matches:
        return None, None, "building_number_not_found"
    matches.sort(key=lambda item: item[0])
    if len(matches) > 1:
        nearest, second = matches[0][0], matches[1][0]
        if nearest > 750.0 or (second - nearest) < MAPTILER_BUILDING_AMBIGUITY_FEET:
            return None, nearest, "building_number_ambiguous"
    return matches[0][1], matches[0][0], "building_number_matched"


def _choose_building_polygon(features: list[dict], point_lng: float, point_lat: float) -> tuple[dict | None, object | None]:
    point = Point(point_lng, point_lat)
    containing = []
    nearby = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        try:
            polygon = shape(geometry)
            if polygon.is_empty:
                continue
        except Exception:
            continue
        props = feature.get("properties") or {}
        residential = props.get("class") == "residential" or props.get("subclass") in {
            "house", "detached", "dwelling_house", "bungalow", "residential", "semi", "semidetached_house"
        }
        if polygon.contains(point) or polygon.touches(point):
            containing.append((0 if residential else 1, polygon.area, feature, polygon))
        else:
            centroid = polygon.centroid
            distance = _distance_feet(point_lng, point_lat, centroid.x, centroid.y)
            if distance <= 100.0:
                nearby.append((distance, 0 if residential else 1, feature, polygon))

    if containing:
        containing.sort(key=lambda item: (item[0], item[1]))
        return containing[0][2], containing[0][3]
    if nearby:
        nearby.sort(key=lambda item: (item[0], item[1]))
        return nearby[0][2], nearby[0][3]
    return None, None


async def _refine_to_numbered_building(
    client: httpx.AsyncClient,
    key: str,
    query_address: str,
    diagnostic: dict,
    tile_cache: dict,
) -> dict:
    """Move an exact geocoder match onto the matching mapped building when safely identifiable."""
    if diagnostic.get("status") != "accepted":
        return diagnostic
    geocode_lng = diagnostic.get("longitude")
    geocode_lat = diagnostic.get("latitude")
    if geocode_lng is None or geocode_lat is None:
        return diagnostic

    expected = _parse_query_address(query_address)
    house_number = expected.get("house_number")
    if not house_number:
        diagnostic["building_status"] = "rejected"
        diagnostic["building_reason"] = "query_house_number_missing"
        return diagnostic

    tiles = _tile_neighborhood(geocode_lng, geocode_lat, MAPTILER_BUILDING_ZOOM)
    number_features = await _tile_layer_features(
        client, key, "v4", "building_number", MAPTILER_BUILDING_ZOOM, tiles, tile_cache
    )
    number_feature, number_distance, number_reason = _choose_number_feature(
        number_features, house_number, geocode_lng, geocode_lat
    )
    diagnostic["building_reason"] = number_reason
    diagnostic["building_distance_feet"] = round(number_distance, 1) if number_distance is not None else None
    if not number_feature:
        diagnostic["building_status"] = "unresolved"
        return diagnostic

    number_lng, number_lat = _number_point(number_feature)
    diagnostic.update({
        "building_status": "matched_number",
        "building_number": (number_feature.get("properties") or {}).get("number"),
        "building_number_latitude": number_lat,
        "building_number_longitude": number_lng,
    })

    building_tiles = _tile_neighborhood(number_lng, number_lat, MAPTILER_BUILDING_ZOOM)
    building_features = await _tile_layer_features(
        client, key, "buildings", "building", MAPTILER_BUILDING_ZOOM, building_tiles, tile_cache
    )
    building_feature, polygon = _choose_building_polygon(building_features, number_lng, number_lat)

    # Buildings is an enhanced add-on. If it is unavailable/empty at this location,
    # fall back to Planet v4's ordinary building footprints before using the number point itself.
    if not building_feature:
        v4_buildings = await _tile_layer_features(
            client, key, "v4", "building", MAPTILER_BUILDING_ZOOM, building_tiles, tile_cache
        )
        building_feature, polygon = _choose_building_polygon(v4_buildings, number_lng, number_lat)

    if building_feature and polygon is not None:
        centroid = polygon.representative_point()
        props = building_feature.get("properties") or {}
        diagnostic.update({
            "latitude": float(centroid.y),
            "longitude": float(centroid.x),
            "building_status": "resolved",
            "building_reason": "numbered_building_footprint",
            "building_class": props.get("class"),
            "building_subclass": props.get("subclass"),
            "building_feature_id": building_feature.get("id"),
            "building_latitude": float(centroid.y),
            "building_longitude": float(centroid.x),
        })
    else:
        diagnostic.update({
            "latitude": number_lat,
            "longitude": number_lng,
            "building_status": "resolved",
            "building_reason": "building_number_point",
            "building_latitude": number_lat,
            "building_longitude": number_lng,
        })
    return diagnostic


async def geocode_addresses_batch(
    key: str,
    addresses: list[str],
    *,
    bbox: tuple[float, float, float, float] | list[float] | None = None,
    country: str = "us",
    min_relevance: float = 0.80,
) -> list[dict]:
    """Resolve addresses and, when safe, refine them to numbered MapTiler buildings."""
    if not addresses:
        return []

    resolved: list[dict] = []
    tile_cache: dict = {}
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
                    if diagnostic.get("status") == "accepted":
                        try:
                            diagnostic = await _refine_to_numbered_building(
                                client, key, query_address, diagnostic, tile_cache
                            )
                        except Exception:
                            # Building refinement is a confidence enhancer, never a reason to fail imports.
                            diagnostic["building_status"] = "error"
                            diagnostic["building_reason"] = "building_resolution_error"
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

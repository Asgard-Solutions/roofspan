"""Simple GeoJSON helpers. No PostGIS — plain Python math per RoofSpan K.I.S.S."""
import math


def _ring(geometry: dict):
    return geometry["coordinates"][0]


def point_in_polygon(lng: float, lat: float, geometry: dict) -> bool:
    ring = _ring(geometry)
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi):
            inside = not inside
        j = i
    return inside


def bbox(geometry: dict):
    ring = _ring(geometry)
    lngs = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return min(lngs), min(lats), max(lngs), max(lats)


def centroid(geometry: dict):
    minlng, minlat, maxlng, maxlat = bbox(geometry)
    return (minlng + maxlng) / 2.0, (minlat + maxlat) / 2.0


def haversine_miles(lng1, lat1, lng2, lat2) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def enclosing_radius_miles(geometry: dict) -> float:
    clng, clat = centroid(geometry)
    minlng, minlat, maxlng, maxlat = bbox(geometry)
    corners = [(minlng, minlat), (minlng, maxlat), (maxlng, minlat), (maxlng, maxlat)]
    return min(100.0, max(haversine_miles(clng, clat, cx, cy) for cx, cy in corners) or 0.5)


def unique_ring_points(geometry: dict) -> int:
    """Count distinct vertices in the polygon's outer ring (ignoring the closing duplicate)."""
    ring = _ring(geometry)
    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    return len({(round(p[0], 9), round(p[1], 9)) for p in pts})


def is_valid_polygon(geometry: dict) -> bool:
    """Structural GeoJSON Polygon validation with at least three unique points."""
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        return False
    coords = geometry.get("coordinates")
    if not coords or not isinstance(coords, list) or not coords[0] or not isinstance(coords[0], list):
        return False
    ring = coords[0]
    if len(ring) < 4:
        return False
    try:
        if not all(len(p) >= 2 and all(isinstance(c, (int, float)) for c in p[:2]) for p in ring):
            return False
    except TypeError:
        return False
    return unique_ring_points(geometry) >= 3


def polygon_fully_contained(inner: dict, outer: dict) -> bool:
    """True when every vertex of `inner`'s outer ring lies inside `outer` (point-in-polygon)."""
    ring = _ring(inner)
    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    return all(point_in_polygon(p[0], p[1], outer) for p in pts)

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

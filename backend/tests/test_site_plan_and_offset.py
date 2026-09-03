"""Tests for position_offset_ft on facets and site_plan on revision (Jan 2026)."""
import os
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
EMAIL = "pjacobsen@asgardsolution.io"
PASSWORD = "RoofSpan#Owner2026"
REV_ID = "b5a05924-6028-4421-bc22-09c88d944790"  # L-Roof, 4 facets
REV_MULTI = "422ea69c-f870-4c5c-877f-706ce9b632bd"  # 3 structures


@pytest.fixture(scope="module")
def h():
    r = requests.post(f"{BASE}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "Content-Type": "application/json"}


def _get(rev_id, h):
    r = requests.get(f"{BASE}/api/measurements/{rev_id}", headers=h, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _build_payload(doc, override_site_plan=..., patch_facet=None):
    """Convert a GET doc into a PUT payload (ref-based)."""
    struct_id_to_ref = {s["id"]: s["id"] for s in doc.get("structures", [])}
    facet_id_to_ref = {f["id"]: f["id"] for f in doc.get("facets", [])}

    def facet_dict(f):
        d = {
            "ref": f["id"],
            "structure_ref": f.get("structure_id"),
            "facet_label": f.get("facet_label"),
            "pitch_rise": f.get("pitch_rise"),
            "area_sqft": f.get("area_sqft") or 0,
            "width_ft": f.get("width_ft"),
            "length_ft": f.get("length_ft"),
            "position_offset_ft": f.get("position_offset_ft"),
            "orientation_azimuth": f.get("orientation_azimuth"),
            "roof_material": f.get("roof_material"),
            "notes": f.get("notes"),
            "geometry": f.get("geometry"),
            "sort": f.get("sort", 0),
        }
        if patch_facet and f["id"] == patch_facet[0]:
            d.update(patch_facet[1])
        return d

    def edge_dict(e):
        return {
            "ref": e["id"],
            "edge_type": e["edge_type"],
            "length_ft": e.get("length_ft") or 0,
            "facet_ref": e.get("facet_id"),
            "facet_ref_secondary": e.get("facet_id_secondary"),
            "label": e.get("label"),
            "notes": e.get("notes"),
            "sort": e.get("sort", 0),
        }

    def pen_dict(p):
        return {
            "ref": p["id"],
            "pen_type": p["pen_type"],
            "quantity": p.get("quantity", 1),
            "facet_ref": p.get("facet_id"),
            "width_in": p.get("width_in"),
            "length_in": p.get("length_in"),
            "diameter_in": p.get("diameter_in"),
            "notes": p.get("notes"),
            "sort": p.get("sort", 0),
        }

    payload = {
        "lead_id": doc.get("lead_id"),
        "property_id": doc.get("property_id"),
        "inspection_id": doc.get("inspection_id"),
        "source": doc.get("source") or "office",
        "provider": doc.get("provider"),
        "report_id": doc.get("report_id"),
        "reported_area_sqft": doc.get("reported_area_sqft"),
        "notes": doc.get("notes"),
        "site_plan": doc.get("site_plan") if override_site_plan is ... else override_site_plan,
        "structures": [
            {
                "ref": s["id"],
                "name": s.get("name", ""),
                "structure_type": s.get("structure_type", "main_house"),
                "included_in_scope": s.get("included_in_scope", True),
                "stories": s.get("stories"),
                "approx_height_ft": s.get("approx_height_ft"),
                "attachment": s.get("attachment"),
                "notes": s.get("notes"),
                "sort": s.get("sort", 0),
            }
            for s in doc.get("structures", [])
        ],
        "facets": [facet_dict(f) for f in doc.get("facets", [])],
        "edges": [edge_dict(e) for e in doc.get("edges", [])],
        "penetrations": [pen_dict(p) for p in doc.get("penetrations", [])],
        "summary": doc.get("summary") or {},
    }
    return payload


def _put(rev_id, doc, h, override_site_plan=..., patch_facet=None):
    payload = _build_payload(doc, override_site_plan=override_site_plan, patch_facet=patch_facet)
    put_h = {**h, "If-Match": str(doc["updated_at"])}
    return requests.put(f"{BASE}/api/measurements/{rev_id}", headers=put_h, json=payload, timeout=30)


def test_get_returns_position_offset_ft_and_site_plan(h):
    data = _get(REV_ID, h)
    assert "site_plan" in data
    assert len(data.get("facets", [])) > 0
    for f in data["facets"]:
        assert "position_offset_ft" in f


def test_multi_structure_revision_has_fields(h):
    data = _get(REV_MULTI, h)
    assert "site_plan" in data
    assert len(data.get("structures", [])) >= 2
    for f in data.get("facets", []):
        assert "position_offset_ft" in f


def test_roundtrip_offset_and_site_plan(h):
    doc = _get(REV_ID, h)
    facet = doc["facets"][0]
    struct_id = facet["structure_id"]
    r = _put(
        REV_ID, doc, h,
        override_site_plan={"offsets": {struct_id: {"dx": 12.5, "dy": -3.25}}},
        patch_facet=(facet["id"], {"position_offset_ft": 7.5}),
    )
    assert r.status_code == 200, r.text

    doc2 = _get(REV_ID, h)
    assert doc2["site_plan"]["offsets"][struct_id] == {"dx": 12.5, "dy": -3.25}
    matched = next(f for f in doc2["facets"] if f["id"] == facet["id"])
    assert matched["position_offset_ft"] == 7.5


def test_null_site_plan_preserves_previous(h):
    """PUT with site_plan=None (Field-style) must NOT wipe previously saved site_plan."""
    doc = _get(REV_ID, h)
    prev = doc.get("site_plan")
    assert prev and prev.get("offsets"), "precondition failure — run roundtrip test first"

    r = _put(REV_ID, doc, h, override_site_plan=None)
    assert r.status_code == 200, r.text

    doc2 = _get(REV_ID, h)
    assert doc2["site_plan"] == prev, f"site_plan wiped! before={prev} after={doc2.get('site_plan')}"


def test_explicit_site_plan_overwrite(h):
    doc = _get(REV_ID, h)
    struct_id = doc["structures"][0]["id"]
    r = _put(REV_ID, doc, h, override_site_plan={"offsets": {struct_id: {"dx": 1.0, "dy": 2.0}}})
    assert r.status_code == 200, r.text
    doc2 = _get(REV_ID, h)
    assert doc2["site_plan"]["offsets"][struct_id] == {"dx": 1.0, "dy": 2.0}

"""RoofSpan — cross-app Measurement Revision parity / no-erasure (live API).

Proves the whole-document save preserves every persisted field a surface does not edit, and that
changing one value changes only that value. Mirrors the fixed client passthrough contract.
Run against a live seeded server: API=http://localhost:8001 EMAIL=... PW=...
"""
import os, uuid, requests

API = os.environ.get("API", "http://localhost:8001")
EMAIL = os.environ.get("EMAIL", "pjacobsen@asgardsolution.io")
PW = os.environ.get("PW", "RoofSpan#Owner2026")


def _tok():
    r = requests.post(f"{API}/api/auth/login", json={"email": EMAIL, "password": PW}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _passthrough_update(full, change=None):
    """Build a whole-document update the way the FIXED clients do: round-trip every persisted value,
    keying existing children by ref=id, and apply an optional single change."""
    body = {
        "source": full.get("source") or "field",
        "provider": full.get("provider"),
        "report_id": full.get("report_id"),
        "reported_area_sqft": full.get("reported_area_sqft"),
        "notes": full.get("notes"),
        "structures": [{
            "ref": s["id"], "name": s.get("name") or "", "structure_type": s.get("structure_type") or "main_house",
            "included_in_scope": s.get("included_in_scope", True), "stories": s.get("stories"),
            "approx_height_ft": s.get("approx_height_ft"), "attachment": s.get("attachment"), "notes": s.get("notes"), "sort": i,
        } for i, s in enumerate(full.get("structures", []))],
        "facets": [{
            "ref": f["id"], "structure_ref": f.get("structure_id"), "facet_label": f.get("facet_label") or "",
            "pitch_rise": f.get("pitch_rise"), "area_sqft": f.get("area_sqft") or 0, "width_ft": f.get("width_ft"),
            "length_ft": f.get("length_ft"), "orientation_azimuth": f.get("orientation_azimuth"),
            "roof_material": f.get("roof_material"), "notes": f.get("notes"), "geometry": f.get("geometry"), "sort": i,
        } for i, f in enumerate(full.get("facets", []))],
        "edges": [{
            "ref": e["id"], "edge_type": e.get("edge_type") or "eave", "length_ft": e.get("length_ft") or 0,
            "facet_ref": e.get("facet_id"), "facet_ref_secondary": e.get("facet_id_secondary"),
            "label": e.get("label"), "notes": e.get("notes"), "sort": i,
        } for i, e in enumerate(full.get("edges", []))],
        "penetrations": [{
            "ref": p["id"], "pen_type": p.get("pen_type"), "quantity": p.get("quantity") or 1, "facet_ref": p.get("facet_id"),
            "diameter_in": p.get("diameter_in"), "width_in": p.get("width_in"), "length_in": p.get("length_in"),
            "notes": p.get("notes"), "sort": i,
        } for i, p in enumerate(full.get("penetrations", []))],
        "summary": full.get("summary") or {},
    }
    if change:
        change(body)
    return body


def test_cross_app_no_erasure_round_trip():
    h = {"Authorization": f"Bearer {_tok()}"}
    # need a property
    props = requests.get(f"{API}/api/properties", params={"limit": 1}, headers=h, timeout=30).json()
    if not props:
        requests.post(f"{API}/api/properties", headers=h, json={"address_line1": "9 Parity Rd", "city": "T", "state": "TX", "postal_code": "75001"}, timeout=30)
        props = requests.get(f"{API}/api/properties", params={"limit": 1}, headers=h, timeout=30).json()
    pid = props[0]["id"]

    tagn = uuid.uuid4().hex[:6]
    create = {
        "property_id": pid, "source": "field", "provider": "eagleview", "report_id": f"RPT-{tagn}",
        "reported_area_sqft": 3210.5, "notes": f"import note {tagn}",
        "structures": [{"ref": "s1", "name": "Main House", "structure_type": "main_house", "stories": 2, "approx_height_ft": 22}],
        "facets": [
            {"ref": "f1", "structure_ref": "s1", "facet_label": "F1", "pitch_rise": 6, "area_sqft": 400,
             "orientation_azimuth": 180.0, "geometry": {"poly": [[0, 0], [10, 0], [10, 8]]}},
            {"ref": "f2", "structure_ref": "s1", "facet_label": "F2", "pitch_rise": 8, "area_sqft": 250, "orientation_azimuth": 90.0},
        ],
        "edges": [
            {"ref": "e1", "edge_type": "valley", "length_ft": 42.5, "facet_ref": "f1", "facet_ref_secondary": "f2", "label": "V1"},
            {"ref": "e2", "edge_type": "eave", "length_ft": 20.0, "facet_ref": "f1"},
        ],
        "penetrations": [{"ref": "p1", "pen_type": "pipe_boot", "quantity": 3, "facet_ref": "f1"}],
        "summary": {"existing_covering_type": "architectural shingle", "deck_type": "OSB", "deck_thickness_in": 0.5,
                     "drip_edge_lf": 130.0, "ridge_vent_lf": 40.0, "intake_soffit_vent_lf": 55.0, "gutter_lf": 120.0,
                     "full_redeck": True, "steep_access": True, "conditions_notes": "two story"},
    }
    r = requests.post(f"{API}/api/mobile/measurements", headers=h, json=create, timeout=30)
    assert r.status_code in (200, 201), (r.status_code, r.text)
    rid = r.json()["id"]

    full = requests.get(f"{API}/api/mobile/measurements/{rid}", headers=h, timeout=30).json()
    # capture originals
    o_provider, o_report, o_reported, o_notes = full["provider"], full["report_id"], full["reported_area_sqft"], full["notes"]
    f1 = next(f for f in full["facets"] if f["facet_label"] == "F1")
    e1 = next(e for e in full["edges"] if e["label"] == "V1")
    assert f1["orientation_azimuth"] == 180.0 and f1["geometry"] is not None
    assert e1["facet_id_secondary"] is not None
    e2_id = next(e for e in full["edges"] if e["edge_type"] == "eave")["id"]

    # FIELD-style save that changes ONLY one roof-line length (e2 20 -> 25) via full passthrough
    def change_one(body):
        for ed in body["edges"]:
            if ed["ref"] == e2_id:
                ed["length_ft"] = 25.0
    upd = _passthrough_update(full, change_one)
    r2 = requests.put(f"{API}/api/mobile/measurements/{rid}", headers={**h, "If-Match": full["updated_at"]}, json=upd, timeout=30)
    assert r2.status_code == 200, (r2.status_code, r2.text)

    after = requests.get(f"{API}/api/mobile/measurements/{rid}", headers=h, timeout=30).json()
    # the intended change happened
    assert next(e for e in after["edges"] if e["id"] == e2_id)["length_ft"] == 25.0
    # NOTHING ELSE erased
    assert after["provider"] == o_provider == "eagleview", "provider must survive a Field save"
    assert after["report_id"] == o_report
    assert after["reported_area_sqft"] == o_reported
    assert after["notes"] == o_notes
    af1 = next(f for f in after["facets"] if f["facet_label"] == "F1")
    assert af1["orientation_azimuth"] == 180.0, "facet orientation must survive"
    assert af1["geometry"] is not None, "facet geometry must survive"
    ae1 = next(e for e in after["edges"] if e["label"] == "V1")
    assert ae1["facet_id_secondary"] is not None, "secondary plane association must survive"
    assert ae1["length_ft"] == 42.5, "unrelated edge unchanged"
    assert after["summary"]["gutter_lf"] == 120.0 and after["summary"]["intake_soffit_vent_lf"] == 55.0, "summary fields survive"
    assert after["summary"]["deck_thickness_in"] == 0.5

    # BLANK/CLEAR is honored when the surface intentionally clears a value
    def clear_notes(body):
        body["notes"] = None
        body["summary"] = {**body["summary"], "conditions_notes": None}
    upd2 = _passthrough_update(after, clear_notes)
    r3 = requests.put(f"{API}/api/mobile/measurements/{rid}", headers={**h, "If-Match": after["updated_at"]}, json=upd2, timeout=30)
    assert r3.status_code == 200, (r3.status_code, r3.text)
    after2 = requests.get(f"{API}/api/mobile/measurements/{rid}", headers=h, timeout=30).json()
    assert after2["notes"] is None, "an intentional clear must clear"
    assert after2["summary"].get("conditions_notes") in (None, ""), "intentional summary clear must clear"
    assert after2["provider"] == "eagleview", "clearing one field never erases others"


if __name__ == "__main__":
    test_cross_app_no_erasure_round_trip()
    print("CROSS-APP MEASUREMENT PARITY / NO-ERASURE: PASS")

import os, json, requests

API = os.environ.get("API", "http://localhost:8001")
EMAIL = os.environ.get("EMAIL", "pjacobsen@asgardsolution.io")
PW = os.environ.get("PW", "RoofSpan#Owner2026")


def _login():
    r = requests.post(f"{API}/api/auth/login", json={"email": EMAIL, "password": PW})
    r.raise_for_status()
    return r.json()["access_token"]


def _prop(h):
    r = requests.get(f"{API}/api/properties?limit=1", headers=h)
    items = r.json()
    items = items if isinstance(items, list) else (items.get("items") or items.get("properties"))
    return items[0]["id"]


def main():
    tok = _login()
    h = {"Authorization": f"Bearer {tok}"}
    pid = _prop(h)
    print("property", pid)

    payload = {
        "property_id": pid, "source": "field", "reported_area_sqft": 2912,
        "structures": [
            {"ref": "s1", "name": "Main House", "structure_type": "main_house", "stories": 2},
            {"ref": "s2", "name": "Detached Garage", "structure_type": "detached_garage", "stories": 1},
        ],
        "facets": [
            {"ref": "F1", "structure_ref": "s1", "facet_label": "F1", "pitch_rise": 6, "area_sqft": 1200},
            {"ref": "F2", "structure_ref": "s1", "facet_label": "F2", "pitch_rise": 6, "area_sqft": 1000},
            {"ref": "F3", "structure_ref": "s1", "facet_label": "F3", "pitch_rise": 4.5, "area_sqft": 400},
            {"ref": "F4", "structure_ref": "s2", "facet_label": "F4", "pitch_rise": 4, "area_sqft": 246},
        ],
        "edges": [
            {"edge_type": "eave", "length_ft": 120, "facet_ref": "F1"},
            {"edge_type": "rake", "length_ft": 80, "facet_ref": "F1"},
            {"edge_type": "ridge", "length_ft": 60},
            {"edge_type": "valley", "length_ft": 24, "facet_ref": "F1", "facet_ref_secondary": "F2"},
            {"edge_type": "hip", "length_ft": 18},
        ],
        "penetrations": [
            {"pen_type": "pipe_boot", "quantity": 3, "diameter_in": 3, "facet_ref": "F1"},
            {"pen_type": "skylight", "quantity": 1, "facet_ref": "F2"},
            {"pen_type": "chimney", "quantity": 1, "width_in": 24, "length_in": 36},
        ],
        "summary": {"existing_covering_type": "3-tab asphalt", "existing_layers": 2, "full_redeck": False,
                    "ridge_vent_lf": 40, "damaged_deck_sf": 64, "replacement_sheets": 2, "steep_access": True},
    }
    r = requests.post(f"{API}/api/measurements", headers=h, json=payload)
    assert r.status_code == 201, (r.status_code, r.text)
    rev = r.json()
    rid = rev["id"]
    t = rev["totals"]
    print("created rev", rev["revision_number"], "status", rev["status"], "editable", rev["editable"])
    assert abs(t["total_area_sqft"] - 2846) < 0.01, t["total_area_sqft"]
    assert abs(t["total_squares"] - 28.46) < 0.01, t["total_squares"]
    assert t["facet_count"] == 4 and t["structure_count"] == 2
    assert t["predominant_pitch"] == 6, t["predominant_pitch"]
    assert t["edge_totals"]["eave_lf"] == 120 and t["edge_totals"]["valley_lf"] == 24
    assert t["penetration_total"] == 5, t["penetration_counts"]
    assert t["reported_area_delta_sqft"] == round(2846 - 2912, 2), t["reported_area_delta_sqft"]
    # area by pitch: 6/12 -> 2200, 4.5 -> 400, 4 -> 246
    byp = {p["pitch"]: p["area_sqft"] for p in t["area_by_pitch"]}
    assert byp.get(6) == 2200 and byp.get(4.5) == 400 and byp.get(4) == 246, byp
    # facets link to structures
    assert any(f["structure_id"] for f in rev["facets"]), "facet->structure link missing"
    print("TOTALS OK:", json.dumps(t, default=str)[:300])

    # GET
    g = requests.get(f"{API}/api/measurements/{rid}", headers=h)
    assert g.status_code == 200 and g.json()["totals"]["total_squares"] == 28.46

    # LIST
    lst = requests.get(f"{API}/api/measurements?property_id={pid}", headers=h).json()
    assert any(x["id"] == rid for x in lst), "revision not in list"
    print("LIST ok:", len(lst), "revision(s)")

    # PUT replace (draft editable) — change a facet area
    payload["facets"][0]["area_sqft"] = 1300
    p = requests.put(f"{API}/api/measurements/{rid}", headers=h, json=payload)
    assert p.status_code == 200, p.text
    assert abs(p.json()["totals"]["total_area_sqft"] - 2946) < 0.01, p.json()["totals"]["total_area_sqft"]
    print("PUT replace ok -> area", p.json()["totals"]["total_area_sqft"])

    # STATUS: field_complete -> office_verified -> locked
    for to, ok_status in [("field_complete", "field_complete"), ("office_verified", "office_verified"), ("locked", "locked")]:
        s = requests.post(f"{API}/api/measurements/{rid}/status", headers=h, json={"to": to})
        assert s.status_code == 200, (to, s.text)
        assert s.json()["status"] == ok_status
    locked = requests.get(f"{API}/api/measurements/{rid}", headers=h).json()
    assert locked["is_immutable"] is True and locked["editable"] is False
    print("STATUS transitions ok; locked & immutable")

    # editing a locked revision must be rejected
    bad = requests.put(f"{API}/api/measurements/{rid}", headers=h, json=payload)
    assert bad.status_code == 409, ("expected 409 editing locked", bad.status_code)
    print("edit-locked correctly rejected (409)")

    # NEW REVISION clone from locked
    nr = requests.post(f"{API}/api/measurements/{rid}/new-revision", headers=h)
    assert nr.status_code == 201, nr.text
    nrev = nr.json()
    assert nrev["revision_number"] > rev["revision_number"]
    assert nrev["status"] == "draft" and nrev["supersedes_revision_id"] == rid
    assert nrev["totals"]["facet_count"] == 4, "clone did not deep-copy facets"
    assert nrev["editable"] is True
    print("NEW REVISION clone ok: rev", nrev["revision_number"], "supersedes", rev["revision_number"])

    # MOBILE create + idempotent replay + field-complete
    ik = "meas-mobile-test-key-001"
    mh = {**h, "Idempotency-Key": ik}
    m1 = requests.post(f"{API}/api/mobile/measurements", headers=mh, json={"property_id": pid, "facets": [{"ref": "F1", "facet_label": "F1", "pitch_rise": 5, "area_sqft": 500}]})
    assert m1.status_code == 201, m1.text
    m1id = m1.json()["id"]
    m2 = requests.post(f"{API}/api/mobile/measurements", headers=mh, json={"property_id": pid})
    assert m2.status_code in (200, 201) and m2.json()["id"] == m1id and m2.json().get("replayed") is True, "idempotent replay failed"
    fc = requests.post(f"{API}/api/mobile/measurements/{m1id}/field-complete", headers=h)
    assert fc.status_code == 200 and fc.json()["status"] == "field_complete"
    print("MOBILE create+idempotent+field-complete ok")

    # cleanup mobile draft revisions created for this test (leave nothing behind)
    for x in [m1id]:
        requests.delete(f"{API}/api/measurements/{x}", headers=h)
    print("\nALL MEASUREMENT LIFECYCLE TESTS PASSED")


if __name__ == "__main__":
    main()

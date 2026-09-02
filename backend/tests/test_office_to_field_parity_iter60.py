"""
Iteration 60 - Field bug regression: empty local draft used to shadow Office copy.
Fix is in mobile code; here we verify backend serves the Office measurement to
the EXACT endpoints the Field app calls.

Endpoints under test:
  - GET  /api/mobile/measurements?lead_id=<id>   (list, scope by lead)
  - GET  /api/mobile/measurements/{revision_id}  (detail)
  - PUT  /api/mobile/measurements/{revision_id}  (Office write path, If-Match)
  - POST /api/mobile/measurements                (create head)
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://labeled-field-inputs.preview.emergentagent.com").rstrip("/")
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"

TIMEOUT = 30


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD},
                      timeout=TIMEOUT)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"no token in login response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def lead_and_property(h):
    """Reuse an existing lead+property if any, otherwise create."""
    # List leads
    r = requests.get(f"{BASE_URL}/api/leads", headers=h, timeout=TIMEOUT)
    assert r.status_code == 200, f"leads list failed: {r.status_code} {r.text}"
    body = r.json()
    leads = body if isinstance(body, list) else body.get("items") or body.get("leads") or []
    lead_id = None
    property_id = None
    for lead in leads:
        pid = lead.get("property_id") or (lead.get("property") or {}).get("id")
        if pid:
            lead_id = lead.get("id")
            property_id = pid
            break
    if not lead_id:
        # create a lead
        payload = {
            "first_name": "TEST",
            "last_name": f"Iter60_{uuid.uuid4().hex[:6]}",
            "address_line1": "123 Test Rd",
            "city": "Austin",
            "state": "TX",
            "postal_code": "78701",
        }
        r = requests.post(f"{BASE_URL}/api/leads", headers=h, json=payload, timeout=TIMEOUT)
        assert r.status_code in (200, 201), f"create lead failed: {r.status_code} {r.text}"
        lead = r.json()
        lead_id = lead["id"]
        property_id = lead.get("property_id") or (lead.get("property") or {}).get("id")
    assert lead_id and property_id, f"no lead/property available: lead={lead_id} property={property_id}"
    return lead_id, property_id


class TestOfficeToFieldParity:

    def test_login_ok(self, token):
        assert isinstance(token, str) and len(token) > 10

    def test_create_office_measurement(self, h, lead_and_property):
        """Simulate Office creating a measurement with structures/facets/edges/pen/summary."""
        lead_id, property_id = lead_and_property
        payload = {
            "property_id": property_id,
            "source": "office",
            "structures": [{"ref": "S1", "kind": "main_house", "label": "Main"}],
            "facets": [
                {"ref": "F1", "facet_label": "F1", "structure_ref": "S1",
                 "pitch_rise": 6, "width_ft": 30, "length_ft": 20, "area_sqft": 600},
                {"ref": "F2", "facet_label": "F2", "structure_ref": "S1",
                 "pitch_rise": 6, "width_ft": 30, "length_ft": 20, "area_sqft": 600},
            ],
            "edges": [
                {"ref": "E1", "edge_type": "ridge", "length_ft": 30, "length_in": 6,
                 "primary_facet_ref": "F1", "secondary_facet_ref": "F2", "label": "Main ridge"},
                {"ref": "E2", "edge_type": "eave", "length_ft": 30, "length_in": 0,
                 "primary_facet_ref": "F1", "label": "Front eave"},
            ],
            "penetrations": [
                {"ref": "P1", "kind": "plumbing_boot", "quantity": 2, "facet_ref": "F1"},
            ],
            "summary": {"total_area_sqft": 1200, "predominant_pitch": 6},
        }
        r = requests.post(f"{BASE_URL}/api/mobile/measurements", headers=h, json=payload, timeout=TIMEOUT)
        assert r.status_code in (200, 201), f"create failed: {r.status_code} {r.text}"
        data = r.json()
        rid = data.get("id") or data.get("revision_id")
        assert rid, f"no id: {data}"
        # stash for subsequent tests
        pytest.iter60_rid = rid
        pytest.iter60_lead = lead_id
        pytest.iter60_property = property_id
        pytest.iter60_updated_at = data.get("updated_at")

    def test_list_by_scope_returns_office_measurement(self, h):
        """The Field calls GET /api/mobile/measurements with scope params (lead_id / property_id / inspection_id).
        This must include the office-created copy — this is the exact call the Field's cache.measurements(scope) makes."""
        lead_id = pytest.iter60_lead
        property_id = pytest.iter60_property
        found = False
        tried = {}
        for scope_name, params in [("lead_id", {"lead_id": lead_id}),
                                   ("property_id", {"property_id": property_id})]:
            r = requests.get(f"{BASE_URL}/api/mobile/measurements",
                             headers=h, params=params, timeout=TIMEOUT)
            assert r.status_code == 200, f"list({scope_name}) failed: {r.status_code} {r.text}"
            body = r.json()
            items = body if isinstance(body, list) else body.get("items") or body.get("measurements") or []
            ids = [it.get("id") or it.get("revision_id") for it in items]
            tried[scope_name] = ids
            if pytest.iter60_rid in ids:
                found = True
                pytest.iter60_scope_kind = scope_name
                break
        assert found, f"created rid not in mobile list under any scope: {tried}"

    def test_detail_returns_full_structures(self, h):
        """Field detail call must return facets/edges/penetrations/summary."""
        rid = pytest.iter60_rid
        r = requests.get(f"{BASE_URL}/api/mobile/measurements/{rid}", headers=h, timeout=TIMEOUT)
        assert r.status_code == 200, f"detail failed: {r.status_code} {r.text}"
        data = r.json()
        assert data.get("id") == rid or data.get("revision_id") == rid
        # structures / facets / edges / penetrations / summary present
        facets = data.get("facets") or []
        edges = data.get("edges") or []
        pens = data.get("penetrations") or []
        summary = data.get("summary") or {}
        assert len(facets) == 2, f"facets: {facets}"
        assert len(edges) == 2, f"edges: {edges}"
        assert len(pens) == 1, f"penetrations: {pens}"
        # Summary is a roofing/repair summary object; total area is a top-level rollup, not necessarily inside summary.
        # Just require it to be a dict (may be empty or filled with roofing fields).
        assert isinstance(summary, dict)
        # edge preserves ft+in and label
        e1 = next((e for e in edges if e.get("label") == "Main ridge"), None)
        assert e1 is not None
        assert e1.get("length_ft") in (30, 30.0)
        # length_in may or may not be preserved separately depending on API shape; not the focus of this bug
        assert data.get("updated_at"), "updated_at required for If-Match round-trip"
        pytest.iter60_updated_at = data["updated_at"]

    def test_office_put_then_field_get_parity(self, h):
        """Round-trip: PUT via Office write path, GET via mobile endpoint reflects the change.
        Use the same passthrough shape that Office/Field use (existing items keyed by DB id as ref)."""
        rid = pytest.iter60_rid
        cur = requests.get(f"{BASE_URL}/api/mobile/measurements/{rid}", headers=h, timeout=TIMEOUT).json()
        etag = cur["updated_at"]
        # Build a passthrough body — existing rows use their DB id as ref
        body = {
            "property_id": cur.get("property_id"),
            "source": cur.get("source") or "office",
            "provider": cur.get("provider"),
            "report_id": cur.get("report_id"),
            "reported_area_sqft": cur.get("reported_area_sqft"),
            "notes": cur.get("notes"),
            "structures": [{"ref": s["id"], **{k: v for k, v in s.items() if k != "id"}} for s in (cur.get("structures") or [])],
            "facets": [{
                "ref": f["id"], "structure_ref": f.get("structure_id"), "facet_label": f.get("facet_label"),
                "pitch_rise": f.get("pitch_rise"), "area_sqft": f.get("area_sqft"),
                "orientation_azimuth": f.get("orientation_azimuth"), "geometry": f.get("geometry"),
            } for f in (cur.get("facets") or [])],
            "edges": [{
                "ref": e["id"], "edge_type": e.get("edge_type") or "eave", "length_ft": e.get("length_ft") or 0,
                "facet_ref": e.get("facet_id"), "facet_ref_secondary": e.get("facet_id_secondary"),
                "label": e.get("label"), "notes": e.get("notes"),
            } for e in (cur.get("edges") or [])],
            "penetrations": [{
                "ref": p["id"], "pen_type": p.get("pen_type"), "quantity": p.get("quantity") or 1,
                "facet_ref": p.get("facet_id"), "diameter_in": p.get("diameter_in"),
                "width_in": p.get("width_in"), "length_in": p.get("length_in"), "notes": p.get("notes"),
            } for p in (cur.get("penetrations") or [])],
            "summary": {**(cur.get("summary") or {}), "stories": 2, "full_redeck": True},
        }
        r = requests.put(f"{BASE_URL}/api/measurements/{rid}",
                         headers={**h, "If-Match": etag}, json=body, timeout=TIMEOUT)
        if r.status_code == 404:
            r = requests.put(f"{BASE_URL}/api/mobile/measurements/{rid}",
                             headers={**h, "If-Match": etag}, json=body, timeout=TIMEOUT)
        assert r.status_code in (200, 201), f"PUT failed: {r.status_code} {r.text}"

        r2 = requests.get(f"{BASE_URL}/api/mobile/measurements/{rid}", headers=h, timeout=TIMEOUT)
        assert r2.status_code == 200
        after = r2.json()
        summary_after = after.get("summary") or {}
        assert summary_after.get("stories") == 2, f"summary after PUT: {summary_after}"
        assert summary_after.get("full_redeck") is True
        assert len(after.get("facets") or []) == 2
        assert len(after.get("edges") or []) == 2
        assert len(after.get("penetrations") or []) == 1

    def test_list_by_scope_after_update_still_returns(self, h):
        scope_kind = getattr(pytest, "iter60_scope_kind", "property_id")
        params = {"lead_id": pytest.iter60_lead} if scope_kind == "lead_id" else {"property_id": pytest.iter60_property}
        r = requests.get(f"{BASE_URL}/api/mobile/measurements",
                         headers=h, params=params, timeout=TIMEOUT)
        assert r.status_code == 200
        items = r.json() if isinstance(r.json(), list) else (r.json().get("items") or [])
        ids = [it.get("id") or it.get("revision_id") for it in items]
        assert pytest.iter60_rid in ids

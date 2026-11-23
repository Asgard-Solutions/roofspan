# Round 3 E2E setup: TEST lead + verified measurement (lead_id primary) + empty estimate. Writes ids to /tmp/r3.json
import json, uuid, requests
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _test_data_cleanup import manual_begin; manual_begin()  # data stays for UI checks; clean with: python tests/_test_data_cleanup.py end
B = open('/app/frontend/.env').read().split('REACT_APP_BACKEND_URL=')[1].split()[0].rstrip('/') + '/api'
s = requests.Session()
s.headers["Authorization"] = "Bearer " + s.post(f"{B}/auth/login", json={"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}).json()["access_token"]
out = {}
r = s.post(f"{B}/mobile/leads", json={"name": f"TEST_R3_{uuid.uuid4().hex[:6]}", "address": "1 Test St", "phone": "555-000-0000", "email": "test@example.com"})
assert r.status_code in (200, 201), r.text
lid = out["lead"] = r.json()["id"]
assert s.post(f"{B}/customers/from-lead/{lid}").status_code in (200, 201)
lead = s.get(f"{B}/leads/{lid}").json()
out["customer"] = lead["customer_id"]
payload = {"lead_id": lid, "source": "office",
           "structures": [{"ref": "s1", "name": "Main House", "structure_type": "main_house", "stories": 1}],
           "facets": [{"ref": "F1", "structure_ref": "s1", "facet_label": "F1", "pitch_rise": 6, "area_sqft": 1200},
                      {"ref": "F2", "structure_ref": "s1", "facet_label": "F2", "pitch_rise": 6, "area_sqft": 1000}],
           "edges": [{"edge_type": "eave", "length_ft": 120, "facet_ref": "F1"}, {"edge_type": "rake", "length_ft": 80, "facet_ref": "F1"}, {"edge_type": "ridge", "length_ft": 60}],
           "summary": {"existing_layers": 1}}
r = s.post(f"{B}/measurements", json=payload)
assert r.status_code == 201, r.text
rid = out["rev"] = r.json()["id"]
for to in ("field_complete", "office_verified"):
    x = s.post(f"{B}/measurements/{rid}/status", json={"to": to}); assert x.status_code == 200, x.text
r = s.post(f"{B}/estimates", json={"lead_id": lid, "customer_id": out["customer"], "tax_rate": 0, "items": []})
assert r.status_code in (200, 201), r.text
out["estimate"] = r.json()["id"]
print(json.dumps(out)); json.dump(out, open("/tmp/r3.json", "w"))
print("revs", [(m["revision_number"], m["status"], m["total_squares"]) for m in s.get(f"{B}/measurements", params={"lead_id": lid}).json()])
print("templates", [(t["name"], t["latest_revision"]["id"] if t.get("latest_revision") else None) for t in s.get(f"{B}/takeoff/templates", params={"active": True}).json()])

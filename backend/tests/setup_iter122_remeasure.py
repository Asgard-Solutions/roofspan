# Helper (not a test): builds a TEST_ lead with rev1 applied + verified rev2 (bigger area, same waste) for UI checks; prints ids as JSON
import os, uuid, json, requests
B = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
s = requests.Session()
s.headers["Authorization"] = "Bearer " + s.post(f"{B}/api/auth/login", json={"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}).json()["access_token"]
tpl = [t for t in s.get(f"{B}/api/takeoff/templates", params={"active": True}).json() if t.get("latest_revision")][0]
lid = s.post(f"{B}/api/mobile/leads", json={"name": f"TEST_R3i122_UI_{uuid.uuid4().hex[:6]}", "address": "1 Test St", "phone": "555-000-0000", "email": "test@example.com"}).json()["id"]
s.post(f"{B}/api/customers/from-lead/{lid}")
cust = s.get(f"{B}/api/leads/{lid}").json()["customer_id"]

def rev(area):
    r = s.post(f"{B}/api/measurements", json={"lead_id": lid, "source": "office", "structures": [{"ref": "s1", "name": "Main", "structure_type": "main_house", "stories": 1}],
        "facets": [{"ref": "F1", "structure_ref": "s1", "facet_label": "F1", "pitch_rise": 6, "area_sqft": area}],
        "edges": [{"edge_type": "eave", "length_ft": 100, "facet_ref": "F1"}], "summary": {}}).json()["id"]
    for to in ("field_complete", "office_verified"):
        s.post(f"{B}/api/measurements/{r}/status", json={"to": to})
    return r

r1 = rev(2000)
eid = s.post(f"{B}/api/estimates", json={"lead_id": lid, "customer_id": cust, "tax_rate": 0, "items": []}).json()["id"]
body = {"measurement_revision_id": r1, "template_revision_id": tpl["latest_revision"]["id"], "estimate_waste_override": None, "drip_edge_override_lf": None, "structure_waste_overrides": {}, "replace_modified_generated": False}
ap = s.post(f"{B}/api/takeoff/estimates/{eid}/apply", json=body)
r2 = rev(2600)
st = s.get(f"{B}/api/takeoff/estimates/{eid}/status").json()
pv = s.post(f"{B}/api/takeoff/estimates/{eid}/preview", json={**body, "measurement_revision_id": r2}).json()
print(json.dumps({"lead": lid, "est": eid, "r1": r1, "r2": r2, "apply": ap.status_code, "changed_metrics": st.get("changed_metrics"), "waste_change": pv.get("waste_change")}, default=str))

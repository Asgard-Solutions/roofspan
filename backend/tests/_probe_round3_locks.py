# Round 3 probe: takeoff apply on an estimate whose proposal is accepted (PUT is 409-locked) + line duplication after editor save
import json, requests
B = open('/app/frontend/.env').read().split('REACT_APP_BACKEND_URL=')[1].split()[0].rstrip('/') + '/api'
ids = json.load(open("/tmp/r3.json"))
s = requests.Session()
s.headers["Authorization"] = "Bearer " + s.post(f"{B}/auth/login", json={"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}).json()["access_token"]
eid = ids["estimate"]
e = s.get(f"{B}/estimates/{eid}").json()
print("status", e["status"], "lines", [(i["description"], i["measured_quantity"]) for i in e["items"]])
st = s.get(f"{B}/takeoff/estimates/{eid}/status").json()
body = {"measurement_revision_id": ids["rev"], "template_revision_id": st["template_revision_id"], "estimate_waste_override": None,
        "drip_edge_override_lf": None, "structure_waste_overrides": {}, "replace_modified_generated": False}
p = s.post(f"{B}/takeoff/estimates/{eid}/preview", json=body)
print("preview", p.status_code, "to_replace", p.json().get("generated_line_ids_to_replace"), "review", p.json().get("review_required"))
put = s.put(f"{B}/estimates/{eid}", json={"lead_id": e["lead_id"], "customer_id": e["customer_id"], "tax_rate": 5, "items": []}, headers={"If-Match": str(e["version"])})
print("PUT on accepted", put.status_code)
a = s.post(f"{B}/takeoff/estimates/{eid}/apply", json=body)
print("APPLY on accepted", a.status_code, a.text[:200])
e2 = s.get(f"{B}/estimates/{eid}").json()
print("lines after", len(e2["items"]), [(i["description"], i["measured_quantity"]) for i in e2["items"]])

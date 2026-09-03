import os, json, urllib.request

BASE = "http://localhost:8001"
LEAD = "e7b41ad7-cc50-4a56-ae70-30558c974c4a"

def req(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token: r.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(r) as resp:
        return json.loads(resp.read().decode())

tok = req("POST", "/api/auth/login", {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"})["access_token"]

# Revision A (draft): NeedsReview (valley pair) + Insufficient (bare facet) + Rect (HC)
revA = req("POST", "/api/measurements", {
    "lead_id": LEAD, "source": "field",
    "structures": [
        {"ref": "nr", "name": "GenNeedsReview", "structure_type": "main_house", "sort": 0},
        {"ref": "ins", "name": "GenInsufficient", "structure_type": "detached_garage", "sort": 1},
        {"ref": "rect", "name": "GenRectHC", "structure_type": "shed", "sort": 2},
    ],
    "facets": [
        {"ref": "f1", "structure_ref": "nr", "facet_label": "F1", "pitch_rise": 6, "area_sqft": 400, "width_ft": 20, "length_ft": 20, "sort": 0},
        {"ref": "f2", "structure_ref": "nr", "facet_label": "F2", "pitch_rise": 6, "area_sqft": 400, "width_ft": 20, "length_ft": 20, "sort": 1},
        {"ref": "fi", "structure_ref": "ins", "facet_label": "FI", "area_sqft": 0, "sort": 0},
        {"ref": "fr", "structure_ref": "rect", "facet_label": "FR", "pitch_rise": 4, "area_sqft": 800, "width_ft": 20, "length_ft": 40, "sort": 0},
    ],
    "edges": [
        {"edge_type": "valley", "length_ft": 28, "facet_ref": "f1", "facet_ref_secondary": "f2", "sort": 0},
        {"edge_type": "eave", "length_ft": 20, "facet_ref": "f1", "sort": 1},
        {"edge_type": "eave", "length_ft": 20, "facet_ref": "f2", "sort": 2},
        {"edge_type": "eave", "length_ft": 40, "facet_ref": "fr", "sort": 3},
    ],
}, tok)

# Revision B (to be locked): rectangle
revB = req("POST", "/api/measurements", {
    "lead_id": LEAD, "source": "field",
    "structures": [{"ref": "lk", "name": "GenLocked", "structure_type": "main_house", "sort": 0}],
    "facets": [{"ref": "fl", "structure_ref": "lk", "facet_label": "FL", "pitch_rise": 6, "area_sqft": 400, "width_ft": 20, "length_ft": 20, "sort": 0}],
}, tok)

# lock revB (walk the status ladder)
for st in ["field_complete", "office_verified", "locked"]:
    try:
        revB = req("POST", f"/api/measurements/{revB['id']}/status", {"to": st}, tok)
    except Exception as e:
        print("status transition", st, "->", e)

def structs(rev):
    return {s["name"]: s["id"] for s in rev["structures"]}

print(json.dumps({
    "lead_id": LEAD,
    "revA_id": revA["id"], "revA_status": revA["status"], "revA_structures": structs(revA),
    "revB_id": revB["id"], "revB_status": revB["status"], "revB_structures": structs(revB),
}, indent=2))

import os, json, sys, urllib.request

API = "https://hip-valley-fix.preview.emergentagent.com"
LEAD = "e7b41ad7-cc50-4a56-ae70-30558c974c4a"


def req(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(API + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    r.add_header("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


st, out = req("POST", "/api/auth/login", body={"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"})
assert st == 200, (st, out)
token = out.get("token") or out.get("access_token")
print("login ok")

payload = {
    "lead_id": LEAD,
    "source": "office",
    "notes": "L-roof framing-solver E2E fixture",
    "structures": [{"ref": "s1", "name": "L-Roof House", "structure_type": "main_house", "sort": 0}],
    "facets": [
        {"ref": "F1", "structure_ref": "s1", "facet_label": "F1", "pitch_rise": 6, "width_ft": 11.18, "length_ft": 40, "area_sqft": 300, "sort": 1},
        {"ref": "F2", "structure_ref": "s1", "facet_label": "F2", "pitch_rise": 6, "width_ft": 11.18, "length_ft": 40, "area_sqft": 200, "sort": 2},
        {"ref": "F3", "structure_ref": "s1", "facet_label": "F3", "pitch_rise": 6, "width_ft": 11.18, "length_ft": 30, "area_sqft": 250, "sort": 3},
        {"ref": "F4", "structure_ref": "s1", "facet_label": "F4", "pitch_rise": 6, "width_ft": 11.18, "length_ft": 30, "area_sqft": 150, "sort": 4},
    ],
    "edges": [
        {"ref": "RH", "edge_type": "ridge", "length_ft": 30, "facet_ref": "F1", "facet_ref_secondary": "F2", "sort": 1},
        {"ref": "RV", "edge_type": "ridge", "length_ft": 20, "facet_ref": "F3", "facet_ref_secondary": "F4", "sort": 2},
        {"ref": "HIP", "edge_type": "hip", "length_ft": 14, "facet_ref": "F1", "facet_ref_secondary": "F3", "sort": 3},
        {"ref": "VAL", "edge_type": "valley", "length_ft": 14, "facet_ref": "F2", "facet_ref_secondary": "F4", "sort": 4},
        {"ref": "E1", "edge_type": "eave", "length_ft": 40, "facet_ref": "F1", "sort": 5},
        {"ref": "E2", "edge_type": "eave", "length_ft": 20, "facet_ref": "F2", "sort": 6},
        {"ref": "E3", "edge_type": "eave", "length_ft": 30, "facet_ref": "F3", "sort": 7},
        {"ref": "E4", "edge_type": "eave", "length_ft": 10, "facet_ref": "F4", "sort": 8},
    ],
    "penetrations": [],
}

st, out = req("POST", "/api/measurements", token=token, body=payload)
print("create revision:", st)
if st not in (200, 201):
    print(out); sys.exit(1)
rev_id = out["id"]
structs = out.get("structures", [])
print("revision_id:", rev_id)
print("structure_id:", structs[0]["id"] if structs else None)
print("facets:", [(f.get("facet_label"), f["id"]) for f in out.get("facets", [])])
print("edges:", [(e.get("edge_type"), e["id"]) for e in out.get("edges", [])])

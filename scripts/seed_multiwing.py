import json, sys, urllib.request, urllib.error

API = "https://hip-valley-fix.preview.emergentagent.com"
LEAD = "e7b41ad7-cc50-4a56-ae70-30558c974c4a"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def req(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(API + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    r.add_header("User-Agent", UA)
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

payload = {
    "lead_id": LEAD, "source": "office", "notes": "Multi-wing (unequal width) framing-solver E2E fixture",
    "structures": [{"ref": "s1", "name": "Multi-Wing House", "structure_type": "main_house", "sort": 0}],
    "facets": [
        {"ref": "M1", "structure_ref": "s1", "facet_label": "M1", "pitch_rise": 6, "width_ft": 11.18, "length_ft": 60, "area_sqft": 700, "sort": 1},
        {"ref": "M2", "structure_ref": "s1", "facet_label": "M2", "pitch_rise": 6, "width_ft": 11.18, "length_ft": 60, "area_sqft": 700, "sort": 2},
        {"ref": "A1", "structure_ref": "s1", "facet_label": "A1", "pitch_rise": 6, "width_ft": 10.06, "length_ft": 18, "area_sqft": 180, "sort": 3},
        {"ref": "A2", "structure_ref": "s1", "facet_label": "A2", "pitch_rise": 6, "width_ft": 10.06, "length_ft": 18, "area_sqft": 180, "sort": 4},
        {"ref": "B1", "structure_ref": "s1", "facet_label": "B1", "pitch_rise": 6, "width_ft": 6.7, "length_ft": 14, "area_sqft": 95, "sort": 5},
        {"ref": "B2", "structure_ref": "s1", "facet_label": "B2", "pitch_rise": 6, "width_ft": 6.7, "length_ft": 14, "area_sqft": 95, "sort": 6},
    ],
    "edges": [
        {"ref": "RM", "edge_type": "ridge", "length_ft": 60, "facet_ref": "M1", "facet_ref_secondary": "M2", "sort": 1},
        {"ref": "RA", "edge_type": "ridge", "length_ft": 18, "facet_ref": "A1", "facet_ref_secondary": "A2", "sort": 2},
        {"ref": "RB", "edge_type": "ridge", "length_ft": 14, "facet_ref": "B1", "facet_ref_secondary": "B2", "sort": 3},
        {"ref": "VA1", "edge_type": "valley", "length_ft": 13, "facet_ref": "M1", "facet_ref_secondary": "A1", "sort": 4},
        {"ref": "VA2", "edge_type": "valley", "length_ft": 13, "facet_ref": "M1", "facet_ref_secondary": "A2", "sort": 5},
        {"ref": "VB1", "edge_type": "valley", "length_ft": 9, "facet_ref": "M1", "facet_ref_secondary": "B1", "sort": 6},
        {"ref": "VB2", "edge_type": "valley", "length_ft": 9, "facet_ref": "M1", "facet_ref_secondary": "B2", "sort": 7},
        {"ref": "EM1", "edge_type": "eave", "length_ft": 60, "facet_ref": "M1", "sort": 8},
        {"ref": "EM2", "edge_type": "eave", "length_ft": 60, "facet_ref": "M2", "sort": 9},
        {"ref": "EA1", "edge_type": "eave", "length_ft": 18, "facet_ref": "A1", "sort": 10},
        {"ref": "EA2", "edge_type": "eave", "length_ft": 18, "facet_ref": "A2", "sort": 11},
        {"ref": "EB1", "edge_type": "eave", "length_ft": 14, "facet_ref": "B1", "sort": 12},
        {"ref": "EB2", "edge_type": "eave", "length_ft": 14, "facet_ref": "B2", "sort": 13},
    ],
    "penetrations": [{"ref": "P1", "pen_type": "pipe_boot", "quantity": 1, "facet_ref": "M2"}],
}

st, out = req("POST", "/api/measurements", token=token, body=payload)
print("create revision:", st)
if st not in (200, 201):
    print(out); sys.exit(1)
print("revision_id:", out["id"])
print("structure_id:", (out.get("structures") or [{}])[0].get("id"))

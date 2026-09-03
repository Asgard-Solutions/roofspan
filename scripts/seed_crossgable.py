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
    "lead_id": LEAD, "source": "office", "notes": "Cross-gable framing-solver E2E fixture",
    "structures": [{"ref": "s1", "name": "Cross-Gable House", "structure_type": "main_house", "sort": 0}],
    "facets": [
        {"ref": "M1", "structure_ref": "s1", "facet_label": "M1", "pitch_rise": 6, "width_ft": 11.18, "length_ft": 48, "area_sqft": 500, "sort": 1},
        {"ref": "M2", "structure_ref": "s1", "facet_label": "M2", "pitch_rise": 6, "width_ft": 11.18, "length_ft": 48, "area_sqft": 500, "sort": 2},
        {"ref": "G1", "structure_ref": "s1", "facet_label": "G1", "pitch_rise": 6, "width_ft": 10.06, "length_ft": 16, "area_sqft": 160, "sort": 3},
        {"ref": "G2", "structure_ref": "s1", "facet_label": "G2", "pitch_rise": 6, "width_ft": 10.06, "length_ft": 16, "area_sqft": 160, "sort": 4},
    ],
    "edges": [
        {"ref": "RM", "edge_type": "ridge", "length_ft": 48, "facet_ref": "M1", "facet_ref_secondary": "M2", "sort": 1},
        {"ref": "RG", "edge_type": "ridge", "length_ft": 16, "facet_ref": "G1", "facet_ref_secondary": "G2", "sort": 2},
        {"ref": "VL", "edge_type": "valley", "length_ft": 13, "facet_ref": "M1", "facet_ref_secondary": "G1", "sort": 3},
        {"ref": "VR", "edge_type": "valley", "length_ft": 13, "facet_ref": "M1", "facet_ref_secondary": "G2", "sort": 4},
        {"ref": "EM1", "edge_type": "eave", "length_ft": 48, "facet_ref": "M1", "sort": 5},
        {"ref": "EM2", "edge_type": "eave", "length_ft": 48, "facet_ref": "M2", "sort": 6},
        {"ref": "EG1", "edge_type": "eave", "length_ft": 16, "facet_ref": "G1", "sort": 7},
        {"ref": "EG2", "edge_type": "eave", "length_ft": 16, "facet_ref": "G2", "sort": 8},
    ],
    "penetrations": [{"ref": "P1", "pen_type": "pipe_boot", "quantity": 2, "facet_ref": "M2"}],
}

st, out = req("POST", "/api/measurements", token=token, body=payload)
print("create revision:", st)
if st not in (200, 201):
    print(out); sys.exit(1)
print("revision_id:", out["id"])
print("structure_id:", (out.get("structures") or [{}])[0].get("id"))

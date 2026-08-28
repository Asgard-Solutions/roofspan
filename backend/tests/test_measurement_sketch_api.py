import os, requests
API = os.environ.get("API", "http://localhost:8001")
EMAIL, PW = "pjacobsen@asgardsolution.io", "RoofSpan#Owner2026"


def main():
    h = {"Authorization": f"Bearer {requests.post(f'{API}/api/auth/login', json={'email': EMAIL, 'password': PW}).json()['access_token']}"}
    pid = (lambda d: (d if isinstance(d, list) else (d.get('items') or d.get('properties')))[0]['id'])(requests.get(f"{API}/api/properties?limit=1", headers=h).json())

    rev = requests.post(f"{API}/api/measurements", headers=h, json={"property_id": pid, "structures": [
        {"ref": "s1", "name": "Main House", "structure_type": "main_house"},
        {"ref": "s2", "name": "Garage", "structure_type": "detached_garage"}], "facets": []}).json()
    rid = rev["id"]
    s1, s2 = rev["structures"][0]["id"], rev["structures"][1]["id"]
    doc = {"schema_version": 1, "edit_mode": "connected_graph", "vertices": [{"id": "v1", "x": 0, "y": 0}], "edges": [], "facets": []}

    # create -> v1
    r = requests.put(f"{API}/api/measurements/{rid}/sketches/{s1}", headers=h, json={"schema_version": 1, "edit_mode": "connected_graph", "document": doc, "expected_version": None})
    assert r.status_code == 200 and r.json()["document_version"] == 1, (r.status_code, r.text)
    print("Office PUT create -> v1 OK")

    # update with token -> v2
    r = requests.put(f"{API}/api/measurements/{rid}/sketches/{s1}", headers=h, json={"schema_version": 1, "edit_mode": "connected_graph", "document": doc, "expected_version": 1})
    assert r.status_code == 200 and r.json()["document_version"] == 2
    print("Office PUT update -> v2 OK")

    # stale -> 409 with server payload
    r = requests.put(f"{API}/api/measurements/{rid}/sketches/{s1}", headers=h, json={"schema_version": 1, "edit_mode": "connected_graph", "document": doc, "expected_version": 1})
    assert r.status_code == 409, (r.status_code, r.text)
    body = r.json()["detail"]
    assert body["server"]["document_version"] == 2, body
    print("Office PUT stale -> 409 with server sketch OK")

    # GET one + list
    assert requests.get(f"{API}/api/measurements/{rid}/sketches/{s1}", headers=h).json()["document_version"] == 2
    # different structure independent
    r = requests.put(f"{API}/api/measurements/{rid}/sketches/{s2}", headers=h, json={"schema_version": 1, "edit_mode": "manual_polygon", "document": doc, "expected_version": None})
    assert r.status_code == 200 and r.json()["document_version"] == 1
    lst = requests.get(f"{API}/api/measurements/{rid}/sketches", headers=h).json()
    assert len(lst) == 2
    print("Office GET one/list + independent structure OK")

    # Field mirror endpoints (owner also passes scope)
    fr = requests.get(f"{API}/api/mobile/measurements/{rid}/sketches", headers=h)
    assert fr.status_code == 200 and len(fr.json()) == 2
    fp = requests.put(f"{API}/api/mobile/measurements/{rid}/sketches/{s1}", headers=h, json={"schema_version": 1, "edit_mode": "connected_graph", "document": doc, "expected_version": 2})
    assert fp.status_code == 200 and fp.json()["document_version"] == 3
    print("Field mirror list + PUT OK (shared service)")

    # lock revision -> PUT rejected 409
    for to in ["field_complete", "office_verified", "locked"]:
        assert requests.post(f"{API}/api/measurements/{rid}/status", headers=h, json={"to": to}).status_code == 200, to
    r = requests.put(f"{API}/api/measurements/{rid}/sketches/{s1}", headers=h, json={"schema_version": 1, "edit_mode": "connected_graph", "document": doc, "expected_version": 3})
    assert r.status_code == 409 and "locked" in r.json()["detail"].lower(), (r.status_code, r.text)
    print("locked revision rejects sketch PUT (409) OK")

    # cleanup handled by DB reset script below
    print("\nSKETCH API TESTS PASSED")


if __name__ == "__main__":
    main()

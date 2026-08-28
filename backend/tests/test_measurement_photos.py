import os, io, struct, zlib, requests

API = os.environ.get("API", "http://localhost:8001")
EMAIL, PW = "pjacobsen@asgardsolution.io", "RoofSpan#Owner2026"


def _png():
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\x00\x00"
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def main():
    h = {"Authorization": f"Bearer {requests.post(f'{API}/api/auth/login', json={'email': EMAIL, 'password': PW}).json()['access_token']}"}
    pid = (lambda d: (d if isinstance(d, list) else (d.get('items') or d.get('properties')))[0]['id'])(requests.get(f"{API}/api/properties?limit=1", headers=h).json())

    # create a revision with a facet + a penetration
    body = {"property_id": pid, "facets": [{"ref": "F1", "facet_label": "F1", "pitch_rise": 6, "area_sqft": 1000}],
            "penetrations": [{"pen_type": "chimney", "quantity": 1}]}
    rev = requests.post(f"{API}/api/measurements", headers=h, json=body).json()
    rid = rev["id"]; fid = rev["facets"][0]["id"]; penid = rev["penetrations"][0]["id"]
    png = _png()

    def upload(rtype, rid_):
        r = requests.post(f"{API}/api/mobile/photos", headers=h,
                          files={"file": ("m.png", io.BytesIO(png), "image/png")},
                          data={"record_type": rtype, "record_id": rid_, "category": "Measurement"})
        assert r.status_code == 201, (rtype, r.status_code, r.text)
        return r.json()["id"]

    p_rev = upload("measurement_revision", rid)
    p_facet = upload("measurement_facet", fid)
    p_pen = upload("measurement_penetration", penid)
    print("uploaded 3 measurement photos (revision, facet, penetration)")

    # aggregate 'all measurement photos' returns all three
    allp = requests.get(f"{API}/api/mobile/photos/measurement/{rid}", headers=h).json()
    assert len(allp) == 3, ("aggregate count", len(allp))
    types = sorted(set(p["record_type"] for p in allp))
    assert types == ["measurement_facet", "measurement_penetration", "measurement_revision"], types
    print("aggregate 'all measurement photos' OK:", len(allp))

    # per-facet list
    fl = requests.get(f"{API}/api/mobile/photos", headers=h, params={"record_type": "measurement_facet", "record_id": fid}).json()
    assert len(fl) == 1 and fl[0]["id"] == p_facet
    print("per-facet photo list OK")

    # lock the revision
    for to in ["field_complete", "office_verified", "locked"]:
        assert requests.post(f"{API}/api/measurements/{rid}/status", headers=h, json={"to": to}).status_code == 200, to
    # deleting a locked revision's photo must be rejected (409)
    d = requests.delete(f"{API}/api/mobile/photos/{p_facet}", headers=h)
    assert d.status_code == 409, ("expected 409 deleting locked photo", d.status_code, d.text)
    # uploading to a locked revision must be rejected (409)
    up = requests.post(f"{API}/api/mobile/photos", headers=h, files={"file": ("m.png", io.BytesIO(png), "image/png")},
                       data={"record_type": "measurement_facet", "record_id": fid})
    assert up.status_code == 409, ("expected 409 upload to locked", up.status_code)
    print("locked revision protects its photos (delete + upload -> 409)")

    # clone -> photos preserved and remapped to NEW child ids
    nr = requests.post(f"{API}/api/measurements/{rid}/new-revision", headers=h).json()
    nrid = nr["id"]; nfid = nr["facets"][0]["id"]; npenid = nr["penetrations"][0]["id"]
    assert nfid != fid and npenid != penid
    nall = requests.get(f"{API}/api/mobile/photos/measurement/{nrid}", headers=h).json()
    assert len(nall) == 3, ("cloned aggregate", len(nall))
    nfl = requests.get(f"{API}/api/mobile/photos", headers=h, params={"record_type": "measurement_facet", "record_id": nfid}).json()
    assert len(nfl) == 1, "facet photo not remapped on clone"
    print("clone preserved & remapped photos to new revision/facet/penetration ids")

    # the cloned draft is editable -> its photo CAN be deleted
    del_id = nfl[0]["id"]
    assert requests.delete(f"{API}/api/mobile/photos/{del_id}", headers=h).status_code == 200
    print("draft-clone photo deletable OK")

    print("\nALL MEASUREMENT PHOTO TESTS PASSED")


if __name__ == "__main__":
    main()

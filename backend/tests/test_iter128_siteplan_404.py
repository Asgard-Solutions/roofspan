# Iter128: site-plan file-missing -> 404 (not 500), proposal PDF through gzip, PO/materials list sanity
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
MSG = "The saved site plan file is missing. Regenerate the site plan."
REV_A = "8fa662ee-cc1b-4472-8002-dfa33ed8abdc"   # history 2,3
REV_B = "7d466513-14c9-442c-b9a8-eade57e53987"   # history 1,2,3
REV_C = "422ea69c-f870-4c5c-877f-706ce9b632bd"   # pdf_key, no history
LEAD_A = "e7b41ad7-cc50-4a56-ae70-30558c974c4a"
LEAD_C = "d0df5baa-ed39-4ac9-ae6d-45e82bab5086"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    r = sess.post(f"{BASE_URL}/api/auth/login", json={"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"})
    if r.status_code != 200:
        pytest.skip("owner login failed")
    sess.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return sess


def _check(resp):
    # either the file exists (200 with real bytes) or 404 with the friendly message; never 500
    assert resp.status_code in (200, 404), f"{resp.status_code} {resp.text[:200]}"
    if resp.status_code == 404:
        assert resp.json().get("detail") == MSG, resp.text
    return resp.status_code


# Site plan PDF per revision
@pytest.mark.parametrize("rev", [REV_A, REV_B, REV_C])
def test_revision_site_plan_pdf(s, rev):
    r = s.get(f"{BASE_URL}/api/measurements/{rev}/site-plan.pdf")
    if _check(r) == 200:
        assert r.content[:4] == b"%PDF"


# Site plan version PDF / PNG
@pytest.mark.parametrize("rev,ver", [(REV_A, 2), (REV_A, 3), (REV_B, 1), (REV_B, 3)])
def test_revision_site_plan_version_pdf_png(s, rev, ver):
    _check(s.get(f"{BASE_URL}/api/measurements/{rev}/site-plan-v/{ver}.pdf"))
    _check(s.get(f"{BASE_URL}/api/measurements/{rev}/site-plan-v/{ver}.png"))


def test_unknown_version_still_404_no_saved(s):
    r = s.get(f"{BASE_URL}/api/measurements/{REV_A}/site-plan-v/99.pdf")
    assert r.status_code == 404
    assert "No saved site plan" in r.json()["detail"]


# Lead-level site plan PDF
@pytest.mark.parametrize("lead", [LEAD_A, LEAD_C])
def test_lead_site_plan_pdf(s, lead):
    meta = s.get(f"{BASE_URL}/api/measurements/lead/{lead}/site-plan")
    assert meta.status_code == 200
    r = s.get(f"{BASE_URL}/api/measurements/lead/{lead}/site-plan.pdf")
    _check(r)


# Proposal PDF still downloads through gzip
def test_proposal_pdf_gzip(s):
    qs = s.get(f"{BASE_URL}/api/quotes").json()
    items = qs if isinstance(qs, list) else qs.get("items", [])
    assert items
    for q in items[:20]:
        r = s.get(f"{BASE_URL}/api/quotes/{q['id']}/proposal.pdf", headers={"Accept-Encoding": "gzip"})
        if r.status_code == 200:
            assert r.content[:4] == b"%PDF"
            return
    pytest.fail("no proposal PDF downloaded for first 20 quotes")


# Lists still gzip
def test_materials_and_pos_lists(s):
    m = s.get(f"{BASE_URL}/api/materials", headers={"Accept-Encoding": "gzip"})
    p = s.get(f"{BASE_URL}/api/purchase-orders", headers={"Accept-Encoding": "gzip"})
    assert m.status_code == 200 and p.status_code == 200
    assert m.headers.get("content-encoding") == "gzip"
    assert len(m.json()) > 100 and len(p.json()) > 100

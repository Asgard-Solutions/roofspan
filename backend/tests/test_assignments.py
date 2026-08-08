"""My Assignments: office assignment (RBAC + audit), strict sales visibility."""
import os
import uuid
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_sales(owner_headers):
    email = f"assign_sales_{uuid.uuid4().hex[:6]}@example.com"
    pw = "SalesField#2026"
    r = requests.post(f"{API}/users", json={"email": email, "full_name": "Assign Sales", "password": pw, "role": "sales"}, headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    return r.json(), _login(email, pw)


def _make_lead(owner_headers, name="Assign Lead"):
    r = requests.post(f"{API}/properties", json={"address_line1": "1 Assign St", "city": "Austin", "state": "TX", "zip_code": "78701", "latitude": 30.2, "longitude": -97.7}, headers=owner_headers, timeout=15)
    pid = r.json()["id"]
    r = requests.post(f"{API}/properties/{pid}/convert-to-lead", json={"name": name}, headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    return r.json()


def test_assignable_users_rbac():
    owner = _login(OWNER_EMAIL, OWNER_PASSWORD)
    _sales_user, sales = _make_sales(owner)
    # owner (MANAGE) can list assignable users
    r = requests.get(f"{API}/users/assignable", headers=owner, timeout=15)
    assert r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) >= 1
    # sales (field) cannot
    r = requests.get(f"{API}/users/assignable", headers=sales, timeout=15)
    assert r.status_code == 403


def test_lead_assignment_and_strict_sales_visibility():
    owner = _login(OWNER_EMAIL, OWNER_PASSWORD)
    sales_user, sales = _make_sales(owner)
    lead = _make_lead(owner)

    # Before assignment: sales cannot see the lead (strict) in list or detail
    listed = requests.get(f"{API}/leads", headers=sales, timeout=15).json()
    assert all(l["id"] != lead["id"] for l in listed)
    assert requests.get(f"{API}/leads/{lead['id']}", headers=sales, timeout=15).status_code == 403

    # Sales cannot assign (403)
    assert requests.put(f"{API}/leads/{lead['id']}/assign", json={"user_id": sales_user["id"]}, headers=sales, timeout=15).status_code == 403

    # Owner assigns lead to sales user
    r = requests.put(f"{API}/leads/{lead['id']}/assign", json={"user_id": sales_user["id"]}, headers=owner, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["assigned_user_id"] == sales_user["id"]
    assert r.json()["assigned_user_name"]

    # Now sales sees it in list and detail
    listed = requests.get(f"{API}/leads", headers=sales, timeout=15).json()
    assert any(l["id"] == lead["id"] for l in listed)
    assert requests.get(f"{API}/leads/{lead['id']}", headers=sales, timeout=15).status_code == 200

    # Assigning a non-existent user -> 422
    assert requests.put(f"{API}/leads/{lead['id']}/assign", json={"user_id": str(uuid.uuid4())}, headers=owner, timeout=15).status_code == 422

    # Unassign (null) works and audit recorded
    r = requests.put(f"{API}/leads/{lead['id']}/assign", json={"user_id": None}, headers=owner, timeout=15)
    assert r.status_code == 200 and r.json()["assigned_user_id"] is None
    audit = requests.get(f"{API}/audit", headers=owner, timeout=15).json()
    rows = audit if isinstance(audit, list) else audit.get("items", [])
    assert any(a["action"] == "lead.assign" for a in rows)


def test_job_assignment_strict_visibility():
    owner = _login(OWNER_EMAIL, OWNER_PASSWORD)
    sales_user, sales = _make_sales(owner)
    # Build an accepted quote -> job
    lead = _make_lead(owner, name="Job Assign Lead")
    cust = requests.post(f"{API}/customers/from-lead/{lead['id']}", headers=owner, timeout=15).json()
    est = requests.post(f"{API}/estimates", json={"lead_id": lead["id"], "customer_id": cust["id"], "tax_rate": 0, "items": [{"description": "Roof", "quantity": 1, "unit": "ea", "unit_price": 100}]}, headers=owner, timeout=15).json()
    quo = requests.post(f"{API}/quotes", json={"estimate_id": est["id"]}, headers=owner, timeout=15).json()
    acc = requests.post(f"{API}/quotes/{quo['id']}/accept", json={"acceptance_name": "Cust"}, headers=owner, timeout=15).json()
    job_id = acc["job_id"]

    # Sales cannot see unassigned job
    listed = requests.get(f"{API}/jobs", headers=sales, timeout=15).json()
    assert all(j["id"] != job_id for j in listed)
    assert requests.get(f"{API}/jobs/{job_id}", headers=sales, timeout=15).status_code == 403

    # Owner assigns job to sales
    r = requests.put(f"{API}/jobs/{job_id}/assign", json={"user_id": sales_user["id"]}, headers=owner, timeout=15)
    assert r.status_code == 200 and r.json()["assigned_user_id"] == sales_user["id"]

    # Sales now sees the job
    listed = requests.get(f"{API}/jobs", headers=sales, timeout=15).json()
    assert any(j["id"] == job_id for j in listed)
    assert requests.get(f"{API}/jobs/{job_id}", headers=sales, timeout=15).status_code == 200

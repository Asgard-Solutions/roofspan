#!/usr/bin/env python3
"""
RoofSpan Backend Regression Test - Mobile Native Production-Readiness
Tests backend APIs after PostgreSQL persistent volume reconfiguration
"""
import requests
import json
import uuid
import io
from typing import Dict, Any, Optional
from PIL import Image

# Base URL from frontend/.env REACT_APP_BACKEND_URL
BASE_URL = "https://unified-mono-deploy.preview.emergentagent.com/api"

# Test credentials from /app/memory/test_credentials.md
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"
SALES1_EMAIL = "sales1_38f545f9@example.com"
SALES1_PASSWORD = "Sales1#2026"
SALES2_EMAIL = "sales2_7ad4f5cd@example.com"
SALES2_PASSWORD = "Sales2#2026"

# Known seeded lead ID with 4 photos
LEAD_ID_WITH_PHOTOS = "b749dfa4-70dd-4dc5-8a4b-043452677893"

# Test results tracking
test_results = []
test_count = 0
passed_count = 0


def log_test(name: str, passed: bool, message: str = ""):
    """Log test result"""
    global test_count, passed_count
    test_count += 1
    if passed:
        passed_count += 1
    status = "✅ PASS" if passed else "❌ FAIL"
    test_results.append({"name": name, "passed": passed, "message": message})
    print(f"{status}: {name}")
    if message:
        print(f"  → {message}")


def login(email: str, password: str) -> Optional[str]:
    """Login and return access token"""
    try:
        response = requests.post(
            f"{BASE_URL}/auth/login",
            json={"email": email, "password": password},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("access_token")
        return None
    except Exception as e:
        print(f"Login error: {e}")
        return None


def create_test_image() -> bytes:
    """Create a small test image"""
    img = Image.new('RGB', (100, 100), color='red')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    return buf.getvalue()


# ===== TEST SECTION 1: AUTH / SecureStore Backend Contract =====

def test_auth_owner_login():
    """1.1: POST /api/auth/login for owner returns 200 + token"""
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD},
        timeout=10
    )
    
    success = response.status_code == 200
    has_token = False
    if success:
        data = response.json()
        has_token = "access_token" in data and len(data["access_token"]) > 0
    
    log_test(
        "AUTH - Owner login returns 200 + token",
        success and has_token,
        f"Status: {response.status_code}, has_token: {has_token}"
    )
    return response.json().get("access_token") if success else None


def test_auth_sales1_login():
    """1.2: POST /api/auth/login for sales1 returns 200 + token"""
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": SALES1_EMAIL, "password": SALES1_PASSWORD},
        timeout=10
    )
    
    success = response.status_code == 200
    has_token = False
    if success:
        data = response.json()
        has_token = "access_token" in data and len(data["access_token"]) > 0
    
    log_test(
        "AUTH - Sales1 login returns 200 + token",
        success and has_token,
        f"Status: {response.status_code}, has_token: {has_token}"
    )
    return response.json().get("access_token") if success else None


def test_auth_wrong_password():
    """1.3: POST /api/auth/login with wrong password returns 401"""
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": OWNER_EMAIL, "password": "WrongPassword123!"},
        timeout=10
    )
    
    log_test(
        "AUTH - Wrong password returns 401",
        response.status_code == 401,
        f"Status: {response.status_code}"
    )


def test_auth_me_with_token(token: str):
    """1.4: GET /api/auth/me with token returns user"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{BASE_URL}/auth/me", headers=headers, timeout=10)
    
    success = response.status_code == 200
    has_user = False
    if success:
        data = response.json()
        has_user = "email" in data and "role" in data
    
    log_test(
        "AUTH - GET /api/auth/me with token returns user",
        success and has_user,
        f"Status: {response.status_code}, has_user: {has_user}"
    )


def test_auth_me_without_token():
    """1.5: GET /api/auth/me without token returns 401"""
    response = requests.get(f"{BASE_URL}/auth/me", timeout=10)
    
    log_test(
        "AUTH - GET /api/auth/me without token returns 401",
        response.status_code == 401,
        f"Status: {response.status_code}"
    )


# ===== TEST SECTION 2: RBAC / Strict Assignment Visibility =====

def test_rbac_sales1_sees_only_assigned_leads(sales1_token: str, owner_token: str):
    """2.1: Sales1 sees only their assigned leads"""
    # First, get a lead and assign it to sales1
    headers_owner = {"Authorization": f"Bearer {owner_token}"}
    
    # Get all leads as owner
    response = requests.get(f"{BASE_URL}/leads", headers=headers_owner, timeout=10)
    if response.status_code != 200 or not response.json():
        log_test("RBAC - Sales1 sees only assigned leads", False, "No leads available for testing")
        return None
    
    leads = response.json()
    test_lead_id = leads[0]["id"]
    
    # Get sales1 user ID
    headers_sales1 = {"Authorization": f"Bearer {sales1_token}"}
    me_response = requests.get(f"{BASE_URL}/auth/me", headers=headers_sales1, timeout=10)
    sales1_user_id = me_response.json()["id"]
    
    # Assign lead to sales1
    assign_response = requests.put(
        f"{BASE_URL}/leads/{test_lead_id}/assign",
        json={"user_id": sales1_user_id},
        headers=headers_owner,
        timeout=10
    )
    
    if assign_response.status_code != 200:
        log_test("RBAC - Sales1 sees only assigned leads", False, f"Failed to assign lead: {assign_response.status_code}")
        return None
    
    # Now check that sales1 can see this lead
    sales1_leads_response = requests.get(f"{BASE_URL}/mobile/leads", headers=headers_sales1, timeout=10)
    
    success = sales1_leads_response.status_code == 200
    if success:
        sales1_leads = sales1_leads_response.json()
        # All leads should be assigned to sales1
        all_assigned = all(lead.get("assigned_user_id") == sales1_user_id for lead in sales1_leads)
        log_test(
            "RBAC - Sales1 sees only assigned leads",
            all_assigned,
            f"Sales1 has {len(sales1_leads)} leads, all assigned: {all_assigned}"
        )
    else:
        log_test("RBAC - Sales1 sees only assigned leads", False, f"Status: {sales1_leads_response.status_code}")
    
    return test_lead_id


def test_rbac_sales1_sees_only_assigned_jobs(sales1_token: str, owner_token: str):
    """2.2: Sales1 sees only their assigned jobs"""
    headers_owner = {"Authorization": f"Bearer {owner_token}"}
    headers_sales1 = {"Authorization": f"Bearer {sales1_token}"}
    
    # Get sales1 user ID
    me_response = requests.get(f"{BASE_URL}/auth/me", headers=headers_sales1, timeout=10)
    sales1_user_id = me_response.json()["id"]
    
    # Get all jobs as owner
    response = requests.get(f"{BASE_URL}/jobs", headers=headers_owner, timeout=10)
    if response.status_code != 200 or not response.json():
        log_test("RBAC - Sales1 sees only assigned jobs", False, "No jobs available for testing")
        return None
    
    jobs = response.json()
    test_job_id = jobs[0]["id"]
    
    # Assign job to sales1
    assign_response = requests.put(
        f"{BASE_URL}/jobs/{test_job_id}/assign",
        json={"user_id": sales1_user_id},
        headers=headers_owner,
        timeout=10
    )
    
    if assign_response.status_code != 200:
        log_test("RBAC - Sales1 sees only assigned jobs", False, f"Failed to assign job: {assign_response.status_code}")
        return None
    
    # Now check that sales1 can see this job
    sales1_jobs_response = requests.get(f"{BASE_URL}/mobile/jobs", headers=headers_sales1, timeout=10)
    
    success = sales1_jobs_response.status_code == 200
    if success:
        sales1_jobs = sales1_jobs_response.json()
        # All jobs should be assigned to sales1
        all_assigned = all(job.get("assigned_user_id") == sales1_user_id for job in sales1_jobs)
        log_test(
            "RBAC - Sales1 sees only assigned jobs",
            all_assigned,
            f"Sales1 has {len(sales1_jobs)} jobs, all assigned: {all_assigned}"
        )
    else:
        log_test("RBAC - Sales1 sees only assigned jobs", False, f"Status: {sales1_jobs_response.status_code}")
    
    return test_job_id


def test_rbac_sales2_cannot_access_sales1_lead(sales2_token: str, sales1_lead_id: str):
    """2.3: Sales2 cannot access Sales1's assigned lead"""
    if not sales1_lead_id:
        log_test("RBAC - Sales2 cannot access Sales1's lead", False, "No sales1 lead available")
        return
    
    headers_sales2 = {"Authorization": f"Bearer {sales2_token}"}
    
    # Try to get the lead directly
    response = requests.get(f"{BASE_URL}/leads/{sales1_lead_id}", headers=headers_sales2, timeout=10)
    
    # Should be 403 or 404 (not visible)
    log_test(
        "RBAC - Sales2 cannot access Sales1's lead (403/404)",
        response.status_code in [403, 404],
        f"Status: {response.status_code}"
    )


def test_rbac_sales2_cannot_access_sales1_job(sales2_token: str, sales1_job_id: str):
    """2.4: Sales2 cannot access Sales1's assigned job"""
    if not sales1_job_id:
        log_test("RBAC - Sales2 cannot access Sales1's job", False, "No sales1 job available")
        return
    
    headers_sales2 = {"Authorization": f"Bearer {sales2_token}"}
    
    # Try to get the job directly
    response = requests.get(f"{BASE_URL}/jobs/{sales1_job_id}", headers=headers_sales2, timeout=10)
    
    # Should be 403 or 404 (not visible)
    log_test(
        "RBAC - Sales2 cannot access Sales1's job (403/404)",
        response.status_code in [403, 404],
        f"Status: {response.status_code}"
    )


def test_rbac_sales1_cannot_assign(sales1_token: str, sales1_lead_id: str):
    """2.5: Sales1 cannot call assign endpoints (403)"""
    if not sales1_lead_id:
        log_test("RBAC - Sales1 cannot assign leads", False, "No lead available")
        return
    
    headers_sales1 = {"Authorization": f"Bearer {sales1_token}"}
    
    # Try to assign the lead
    response = requests.put(
        f"{BASE_URL}/leads/{sales1_lead_id}/assign",
        json={"user_id": None},
        headers=headers_sales1,
        timeout=10
    )
    
    log_test(
        "RBAC - Sales1 cannot assign leads (403)",
        response.status_code == 403,
        f"Status: {response.status_code}"
    )


# ===== TEST SECTION 3: PHOTOS =====

def test_photos_upload(owner_token: str):
    """3.1: Owner can upload photo to lead"""
    headers = {"Authorization": f"Bearer {owner_token}"}
    
    # Create test image
    image_data = create_test_image()
    
    files = {
        'file': ('test.jpg', image_data, 'image/jpeg')
    }
    data = {
        'record_type': 'lead',
        'record_id': LEAD_ID_WITH_PHOTOS,
        'category': 'Overview',
        'description': 'Regression test photo'
    }
    
    response = requests.post(
        f"{BASE_URL}/mobile/photos",
        files=files,
        data=data,
        headers=headers,
        timeout=10
    )
    
    success = response.status_code == 201
    photo_id = None
    if success:
        photo_data = response.json()
        photo_id = photo_data.get("id")
    
    log_test(
        "PHOTOS - Owner can upload photo",
        success and photo_id is not None,
        f"Status: {response.status_code}, photo_id: {photo_id}"
    )
    
    return photo_id


def test_photos_list(owner_token: str):
    """3.2: GET /api/mobile/photos returns list"""
    headers = {"Authorization": f"Bearer {owner_token}"}
    
    response = requests.get(
        f"{BASE_URL}/mobile/photos",
        params={"record_type": "lead", "record_id": LEAD_ID_WITH_PHOTOS},
        headers=headers,
        timeout=10
    )
    
    success = response.status_code == 200
    photo_count = 0
    if success:
        photos = response.json()
        photo_count = len(photos) if isinstance(photos, list) else 0
    
    log_test(
        "PHOTOS - List photos returns data",
        success and photo_count >= 4,
        f"Status: {response.status_code}, photo_count: {photo_count} (expected >=4)"
    )


def test_photos_content(owner_token: str, photo_id: str):
    """3.3: GET /api/mobile/photos/{id}/content returns image"""
    if not photo_id:
        log_test("PHOTOS - Content retrieval", False, "No photo_id available")
        return
    
    headers = {"Authorization": f"Bearer {owner_token}"}
    
    response = requests.get(
        f"{BASE_URL}/mobile/photos/{photo_id}/content",
        headers=headers,
        timeout=10
    )
    
    success = response.status_code == 200
    has_content = len(response.content) > 0 if success else False
    
    log_test(
        "PHOTOS - Content retrieval returns image bytes",
        success and has_content,
        f"Status: {response.status_code}, content_length: {len(response.content) if success else 0}"
    )


def test_photos_idempotency(owner_token: str):
    """3.4: Same Idempotency-Key prevents duplicate"""
    headers = {"Authorization": f"Bearer {owner_token}"}
    idempotency_key = f"test-{uuid.uuid4()}"
    headers["Idempotency-Key"] = idempotency_key
    
    # Create test image
    image_data = create_test_image()
    
    files = {
        'file': ('test.jpg', image_data, 'image/jpeg')
    }
    data = {
        'record_type': 'lead',
        'record_id': LEAD_ID_WITH_PHOTOS,
        'category': 'Other',
        'description': 'Idempotency test'
    }
    
    # First upload
    response1 = requests.post(
        f"{BASE_URL}/mobile/photos",
        files=files,
        data=data,
        headers=headers,
        timeout=10
    )
    
    if response1.status_code != 201:
        log_test("PHOTOS - Idempotency", False, f"First upload failed: {response1.status_code}")
        return
    
    photo1 = response1.json()
    photo1_id = photo1.get("id")
    
    # Second upload with same key
    files2 = {
        'file': ('test2.jpg', image_data, 'image/jpeg')
    }
    response2 = requests.post(
        f"{BASE_URL}/mobile/photos",
        files=files2,
        data=data,
        headers=headers,
        timeout=10
    )
    
    if response2.status_code != 201:
        log_test("PHOTOS - Idempotency", False, f"Second upload failed: {response2.status_code}")
        return
    
    photo2 = response2.json()
    photo2_id = photo2.get("id")
    replayed = photo2.get("replayed", False)
    
    log_test(
        "PHOTOS - Idempotency prevents duplicate",
        photo1_id == photo2_id and replayed,
        f"Same ID: {photo1_id == photo2_id}, replayed: {replayed}"
    )


def test_photos_invalid_record_type(owner_token: str):
    """3.5: Invalid record_type returns 422"""
    headers = {"Authorization": f"Bearer {owner_token}"}
    
    image_data = create_test_image()
    files = {
        'file': ('test.jpg', image_data, 'image/jpeg')
    }
    data = {
        'record_type': 'invalid_type',
        'record_id': LEAD_ID_WITH_PHOTOS,
        'category': 'Overview'
    }
    
    response = requests.post(
        f"{BASE_URL}/mobile/photos",
        files=files,
        data=data,
        headers=headers,
        timeout=10
    )
    
    log_test(
        "PHOTOS - Invalid record_type returns 422",
        response.status_code == 422,
        f"Status: {response.status_code}"
    )


def test_photos_invalid_category(owner_token: str):
    """3.6: Invalid category returns 422"""
    headers = {"Authorization": f"Bearer {owner_token}"}
    
    image_data = create_test_image()
    files = {
        'file': ('test.jpg', image_data, 'image/jpeg')
    }
    data = {
        'record_type': 'lead',
        'record_id': LEAD_ID_WITH_PHOTOS,
        'category': 'InvalidCategory'
    }
    
    response = requests.post(
        f"{BASE_URL}/mobile/photos",
        files=files,
        data=data,
        headers=headers,
        timeout=10
    )
    
    log_test(
        "PHOTOS - Invalid category returns 422",
        response.status_code == 422,
        f"Status: {response.status_code}"
    )


def test_photos_unsupported_content_type(owner_token: str):
    """3.7: Unsupported content-type returns 422"""
    headers = {"Authorization": f"Bearer {owner_token}"}
    
    files = {
        'file': ('test.txt', b'not an image', 'text/plain')
    }
    data = {
        'record_type': 'lead',
        'record_id': LEAD_ID_WITH_PHOTOS,
        'category': 'Overview'
    }
    
    response = requests.post(
        f"{BASE_URL}/mobile/photos",
        files=files,
        data=data,
        headers=headers,
        timeout=10
    )
    
    log_test(
        "PHOTOS - Unsupported content-type returns 422",
        response.status_code == 422,
        f"Status: {response.status_code}"
    )


def test_photos_unauthenticated():
    """3.8: Unauthenticated photo upload returns 401"""
    image_data = create_test_image()
    files = {
        'file': ('test.jpg', image_data, 'image/jpeg')
    }
    data = {
        'record_type': 'lead',
        'record_id': LEAD_ID_WITH_PHOTOS,
        'category': 'Overview'
    }
    
    response = requests.post(
        f"{BASE_URL}/mobile/photos",
        files=files,
        data=data,
        timeout=10
    )
    
    log_test(
        "PHOTOS - Unauthenticated upload returns 401",
        response.status_code == 401,
        f"Status: {response.status_code}"
    )


def test_photos_persistence():
    """3.9: Previously seeded photos still persist (lead b749dfa4 should have >=4)"""
    # This is already tested in test_photos_list, but we'll verify again
    owner_token = login(OWNER_EMAIL, OWNER_PASSWORD)
    if not owner_token:
        log_test("PHOTOS - Persistence check", False, "Could not login")
        return
    
    headers = {"Authorization": f"Bearer {owner_token}"}
    response = requests.get(
        f"{BASE_URL}/mobile/photos",
        params={"record_type": "lead", "record_id": LEAD_ID_WITH_PHOTOS},
        headers=headers,
        timeout=10
    )
    
    success = response.status_code == 200
    photo_count = 0
    if success:
        photos = response.json()
        photo_count = len(photos) if isinstance(photos, list) else 0
    
    log_test(
        "PHOTOS - Persistence (>=4 photos for lead b749dfa4)",
        success and photo_count >= 4,
        f"Status: {response.status_code}, photo_count: {photo_count}"
    )


# ===== TEST SECTION 4: MAP CONFIG =====

def test_map_config_auth():
    """4.1: GET /api/map-config requires auth (401 without token)"""
    response = requests.get(f"{BASE_URL}/map-config", timeout=10)
    
    log_test(
        "MAP CONFIG - Requires auth (401 without token)",
        response.status_code == 401,
        f"Status: {response.status_code}"
    )


def test_map_config_structure(owner_token: str):
    """4.2: GET /api/map-config returns valid structure"""
    headers = {"Authorization": f"Bearer {owner_token}"}
    response = requests.get(f"{BASE_URL}/map-config", headers=headers, timeout=10)
    
    if response.status_code != 200:
        log_test("MAP CONFIG - Valid structure", False, f"Status: {response.status_code}")
        return
    
    config = response.json()
    
    # Check osm_tile_url
    osm_url = config.get("osm_tile_url", "")
    has_placeholders = "{z}" in osm_url and "{x}" in osm_url and "{y}" in osm_url
    is_http = osm_url.startswith("http://") or osm_url.startswith("https://")
    
    # Check default_center
    default_center = config.get("default_center", [])
    is_valid_center = (
        isinstance(default_center, list) and 
        len(default_center) == 2 and
        isinstance(default_center[0], (int, float)) and
        isinstance(default_center[1], (int, float)) and
        -180 <= default_center[0] <= 180 and
        -90 <= default_center[1] <= 90
    )
    
    # Check default_zoom
    default_zoom = config.get("default_zoom")
    is_valid_zoom = isinstance(default_zoom, (int, float)) and 0 <= default_zoom <= 24
    
    all_valid = has_placeholders and is_http and is_valid_center and is_valid_zoom
    
    log_test(
        "MAP CONFIG - Valid structure (osm_tile_url, default_center, default_zoom)",
        all_valid,
        f"osm_url valid: {has_placeholders and is_http}, center valid: {is_valid_center}, zoom valid: {is_valid_zoom}"
    )


# ===== TEST SECTION 5: Office<->Mobile Consistency =====

def test_office_mobile_consistency_visit(owner_token: str):
    """5.1: Visit created via mobile endpoint visible via standard endpoint"""
    headers = {"Authorization": f"Bearer {owner_token}"}
    
    # Get a property ID
    props_response = requests.get(f"{BASE_URL}/properties", headers=headers, timeout=10)
    if props_response.status_code != 200 or not props_response.json():
        log_test("CONSISTENCY - Visit visibility", False, "No properties available")
        return
    
    properties = props_response.json()
    property_id = properties[0]["id"]
    
    # Create visit via mobile endpoint
    idempotency_key = f"test-visit-{uuid.uuid4()}"
    headers_with_idem = headers.copy()
    headers_with_idem["Idempotency-Key"] = idempotency_key
    
    visit_data = {
        "property_id": property_id,
        "outcome": "no_answer",
        "notes": "Regression test visit"
    }
    
    mobile_response = requests.post(
        f"{BASE_URL}/mobile/visits",
        json=visit_data,
        headers=headers_with_idem,
        timeout=10
    )
    
    if mobile_response.status_code != 201:
        log_test("CONSISTENCY - Visit visibility", False, f"Mobile visit creation failed: {mobile_response.status_code}")
        return
    
    visit = mobile_response.json()
    visit_id = visit.get("id")
    
    # Check if visible via standard property endpoint
    property_response = requests.get(f"{BASE_URL}/properties/{property_id}", headers=headers, timeout=10)
    
    if property_response.status_code != 200:
        log_test("CONSISTENCY - Visit visibility", False, f"Property fetch failed: {property_response.status_code}")
        return
    
    property_data = property_response.json()
    visits = property_data.get("visits", [])
    visit_ids = [v.get("id") for v in visits]
    
    log_test(
        "CONSISTENCY - Visit created via mobile visible via standard endpoint",
        visit_id in visit_ids,
        f"Visit {visit_id} found in property visits: {visit_id in visit_ids}"
    )


def test_office_mobile_consistency_photo(owner_token: str):
    """5.2: Photo created via mobile endpoint visible via standard endpoint"""
    headers = {"Authorization": f"Bearer {owner_token}"}
    
    # Upload photo via mobile endpoint
    idempotency_key = f"test-photo-{uuid.uuid4()}"
    headers_with_idem = headers.copy()
    headers_with_idem["Idempotency-Key"] = idempotency_key
    
    image_data = create_test_image()
    files = {
        'file': ('test.jpg', image_data, 'image/jpeg')
    }
    data = {
        'record_type': 'lead',
        'record_id': LEAD_ID_WITH_PHOTOS,
        'category': 'Overview',
        'description': 'Consistency test photo'
    }
    
    mobile_response = requests.post(
        f"{BASE_URL}/mobile/photos",
        files=files,
        data=data,
        headers=headers_with_idem,
        timeout=10
    )
    
    if mobile_response.status_code != 201:
        log_test("CONSISTENCY - Photo visibility", False, f"Mobile photo upload failed: {mobile_response.status_code}")
        return
    
    photo = mobile_response.json()
    photo_id = photo.get("id")
    
    # Check if visible via mobile photos list (which is the standard endpoint for photos)
    list_response = requests.get(
        f"{BASE_URL}/mobile/photos",
        params={"record_type": "lead", "record_id": LEAD_ID_WITH_PHOTOS},
        headers=headers,
        timeout=10
    )
    
    if list_response.status_code != 200:
        log_test("CONSISTENCY - Photo visibility", False, f"Photo list fetch failed: {list_response.status_code}")
        return
    
    photos = list_response.json()
    photo_ids = [p.get("id") for p in photos]
    
    log_test(
        "CONSISTENCY - Photo created via mobile visible via list endpoint",
        photo_id in photo_ids,
        f"Photo {photo_id} found in photos list: {photo_id in photo_ids}"
    )


# ===== TEST SECTION 6: Idempotency for Visits =====

def test_visit_idempotency(owner_token: str):
    """6.1: POST /api/mobile/visits with same Idempotency-Key creates only one visit"""
    headers = {"Authorization": f"Bearer {owner_token}"}
    
    # Get a property ID
    props_response = requests.get(f"{BASE_URL}/properties", headers=headers, timeout=10)
    if props_response.status_code != 200 or not props_response.json():
        log_test("IDEMPOTENCY - Visit no-duplicate", False, "No properties available")
        return
    
    properties = props_response.json()
    property_id = properties[0]["id"]
    
    # Create visit with idempotency key
    idempotency_key = f"test-idem-{uuid.uuid4()}"
    headers_with_idem = headers.copy()
    headers_with_idem["Idempotency-Key"] = idempotency_key
    
    visit_data = {
        "property_id": property_id,
        "outcome": "no_answer",
        "notes": "Idempotency test visit"
    }
    
    # First request
    response1 = requests.post(
        f"{BASE_URL}/mobile/visits",
        json=visit_data,
        headers=headers_with_idem,
        timeout=10
    )
    
    if response1.status_code != 201:
        log_test("IDEMPOTENCY - Visit no-duplicate", False, f"First visit creation failed: {response1.status_code}")
        return
    
    visit1 = response1.json()
    visit1_id = visit1.get("id")
    
    # Second request with same idempotency key
    response2 = requests.post(
        f"{BASE_URL}/mobile/visits",
        json=visit_data,
        headers=headers_with_idem,
        timeout=10
    )
    
    if response2.status_code != 201:
        log_test("IDEMPOTENCY - Visit no-duplicate", False, f"Second visit request failed: {response2.status_code}")
        return
    
    visit2 = response2.json()
    visit2_id = visit2.get("id")
    replayed = visit2.get("replayed", False)
    
    log_test(
        "IDEMPOTENCY - Visit with same Idempotency-Key creates only one visit",
        visit1_id == visit2_id and replayed,
        f"Same ID: {visit1_id == visit2_id}, replayed: {replayed}"
    )


# ===== MAIN TEST RUNNER =====

def main():
    """Run all regression tests"""
    print("=" * 80)
    print("RoofSpan Backend Regression Test - Mobile Native Production-Readiness")
    print("=" * 80)
    print()
    
    try:
        # Section 1: AUTH / SecureStore Backend Contract
        print("=" * 80)
        print("SECTION 1: AUTH / SecureStore Backend Contract")
        print("=" * 80)
        owner_token = test_auth_owner_login()
        sales1_token = test_auth_sales1_login()
        test_auth_wrong_password()
        if owner_token:
            test_auth_me_with_token(owner_token)
        test_auth_me_without_token()
        
        # Section 2: RBAC / Strict Assignment Visibility
        print("\n" + "=" * 80)
        print("SECTION 2: RBAC / Strict Assignment Visibility")
        print("=" * 80)
        sales2_token = login(SALES2_EMAIL, SALES2_PASSWORD)
        
        sales1_lead_id = None
        sales1_job_id = None
        if sales1_token and owner_token:
            sales1_lead_id = test_rbac_sales1_sees_only_assigned_leads(sales1_token, owner_token)
            sales1_job_id = test_rbac_sales1_sees_only_assigned_jobs(sales1_token, owner_token)
        
        if sales2_token and sales1_lead_id:
            test_rbac_sales2_cannot_access_sales1_lead(sales2_token, sales1_lead_id)
        
        if sales2_token and sales1_job_id:
            test_rbac_sales2_cannot_access_sales1_job(sales2_token, sales1_job_id)
        
        if sales1_token and sales1_lead_id:
            test_rbac_sales1_cannot_assign(sales1_token, sales1_lead_id)
        
        # Section 3: PHOTOS
        print("\n" + "=" * 80)
        print("SECTION 3: PHOTOS")
        print("=" * 80)
        photo_id = None
        if owner_token:
            photo_id = test_photos_upload(owner_token)
            test_photos_list(owner_token)
            if photo_id:
                test_photos_content(owner_token, photo_id)
            test_photos_idempotency(owner_token)
            test_photos_invalid_record_type(owner_token)
            test_photos_invalid_category(owner_token)
            test_photos_unsupported_content_type(owner_token)
        test_photos_unauthenticated()
        test_photos_persistence()
        
        # Section 4: MAP CONFIG
        print("\n" + "=" * 80)
        print("SECTION 4: MAP CONFIG")
        print("=" * 80)
        test_map_config_auth()
        if owner_token:
            test_map_config_structure(owner_token)
        
        # Section 5: Office<->Mobile Consistency
        print("\n" + "=" * 80)
        print("SECTION 5: Office<->Mobile Consistency")
        print("=" * 80)
        if owner_token:
            test_office_mobile_consistency_visit(owner_token)
            test_office_mobile_consistency_photo(owner_token)
        
        # Section 6: Idempotency for Visits
        print("\n" + "=" * 80)
        print("SECTION 6: Idempotency / No-Duplicate")
        print("=" * 80)
        if owner_token:
            test_visit_idempotency(owner_token)
        
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    print(f"\nTotal: {passed_count}/{test_count} tests passed")
    
    if passed_count < test_count:
        print("\n❌ FAILED TESTS:")
        for t in test_results:
            if not t["passed"]:
                print(f"  - {t['name']}")
                if t["message"]:
                    print(f"    {t['message']}")
    else:
        print("\n✅ ALL TESTS PASSED!")
    
    print("\n" + "=" * 80)
    
    # Exit with appropriate code
    exit(0 if passed_count == test_count else 1)


if __name__ == "__main__":
    main()

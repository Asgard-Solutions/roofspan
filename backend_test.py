#!/usr/bin/env python3
"""Backend API tests for RoofSpan - Map Configuration API Contract Verification"""
import requests
import json
import re
from typing import Dict, Any

# Base URL from frontend/.env REACT_APP_BACKEND_URL
BASE_URL = "https://unified-mono-deploy.preview.emergentagent.com/api"

# Test credentials from /app/memory/test_credentials.md
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"

# Known seeded lead ID with 4 photos
LEAD_ID_WITH_PHOTOS = "b749dfa4-70dd-4dc5-8a4b-043452677893"

# Test results tracking
test_results = []


def log_test(name: str, passed: bool, message: str = ""):
    """Log test result"""
    status = "✅ PASS" if passed else "❌ FAIL"
    test_results.append({"name": name, "passed": passed, "message": message})
    print(f"{status}: {name}")
    if message:
        print(f"  → {message}")


def login_as_owner() -> str:
    """Login as owner and return access token"""
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD},
        timeout=10
    )
    if response.status_code != 200:
        raise Exception(f"Login failed: {response.status_code} - {response.text}")
    data = response.json()
    return data["access_token"]


def test_map_config_auth():
    """Test 1: Map config requires authentication (401 without token)"""
    response = requests.get(f"{BASE_URL}/map-config", timeout=10)
    log_test(
        "Map config - 401 without auth token",
        response.status_code == 401,
        f"Expected 401, got {response.status_code}"
    )


def test_map_config_with_auth(token: str) -> Dict[str, Any]:
    """Test 2: Map config returns 200 with valid token"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{BASE_URL}/map-config", headers=headers, timeout=10)
    
    log_test(
        "Map config - 200 with valid token",
        response.status_code == 200,
        f"Expected 200, got {response.status_code}"
    )
    
    if response.status_code != 200:
        return {}
    
    return response.json()


def test_map_config_response_shape(config: Dict[str, Any]):
    """Test 3-9: Validate map config response shape and field requirements"""
    
    # Test 3: osm_tile_url is a string
    osm_url = config.get("osm_tile_url", "")
    log_test(
        "Map config - osm_tile_url is string",
        isinstance(osm_url, str) and len(osm_url) > 0,
        f"osm_tile_url: {osm_url}"
    )
    
    # Test 4: osm_tile_url is http(s) URL
    is_http_url = osm_url.startswith("http://") or osm_url.startswith("https://")
    log_test(
        "Map config - osm_tile_url is http(s) URL",
        is_http_url,
        f"URL starts with http(s): {osm_url[:50]}"
    )
    
    # Test 5: osm_tile_url contains {z}, {x}, {y} placeholders (CRITICAL for mobile)
    has_z = "{z}" in osm_url
    has_x = "{x}" in osm_url
    has_y = "{y}" in osm_url
    has_all_placeholders = has_z and has_x and has_y
    log_test(
        "Map config - osm_tile_url contains {z}, {x}, {y} placeholders",
        has_all_placeholders,
        f"Has {{z}}: {has_z}, {{x}}: {has_x}, {{y}}: {has_y} | URL: {osm_url}"
    )
    
    # Test 6: default_center is a 2-element array
    default_center = config.get("default_center", [])
    is_two_element_array = isinstance(default_center, list) and len(default_center) == 2
    log_test(
        "Map config - default_center is 2-element array",
        is_two_element_array,
        f"default_center: {default_center}"
    )
    
    # Test 7: default_center values are valid [lng, lat]
    if is_two_element_array:
        lng, lat = default_center[0], default_center[1]
        lng_valid = isinstance(lng, (int, float)) and -180 <= lng <= 180
        lat_valid = isinstance(lat, (int, float)) and -90 <= lat <= 90
        log_test(
            "Map config - default_center [lng, lat] in valid ranges",
            lng_valid and lat_valid,
            f"lng={lng} (valid: {lng_valid}), lat={lat} (valid: {lat_valid})"
        )
    else:
        log_test(
            "Map config - default_center [lng, lat] in valid ranges",
            False,
            "Cannot validate: default_center is not a 2-element array"
        )
    
    # Test 8: default_zoom is a number in [0, 24]
    default_zoom = config.get("default_zoom")
    zoom_valid = isinstance(default_zoom, (int, float)) and 0 <= default_zoom <= 24
    log_test(
        "Map config - default_zoom is number in [0, 24]",
        zoom_valid,
        f"default_zoom: {default_zoom} (type: {type(default_zoom).__name__})"
    )
    
    # Test 9: satellite_enabled is boolean
    satellite_enabled = config.get("satellite_enabled")
    log_test(
        "Map config - satellite_enabled is boolean",
        isinstance(satellite_enabled, bool),
        f"satellite_enabled: {satellite_enabled} (type: {type(satellite_enabled).__name__})"
    )
    
    # Test 10: maptiler_configured is boolean
    maptiler_configured = config.get("maptiler_configured")
    log_test(
        "Map config - maptiler_configured is boolean",
        isinstance(maptiler_configured, bool),
        f"maptiler_configured: {maptiler_configured} (type: {type(maptiler_configured).__name__})"
    )
    
    # Test 11: When maptiler not configured, satellite_enabled must be false
    if not maptiler_configured:
        log_test(
            "Map config - satellite_enabled is false when maptiler not configured",
            satellite_enabled is False,
            f"maptiler_configured={maptiler_configured}, satellite_enabled={satellite_enabled}"
        )
    else:
        log_test(
            "Map config - satellite_enabled logic (maptiler IS configured)",
            True,
            f"maptiler_configured={maptiler_configured}, satellite_enabled={satellite_enabled} (no constraint)"
        )
    
    # Test 12: attribution is a non-empty string
    attribution = config.get("attribution", "")
    log_test(
        "Map config - attribution is non-empty string",
        isinstance(attribution, str) and len(attribution) > 0,
        f"attribution: {attribution[:50]}..."
    )


def test_map_config_idempotency(token: str):
    """Test 13: Map config is idempotent (stable across repeated calls)"""
    headers = {"Authorization": f"Bearer {token}"}
    
    # Make 3 consecutive calls
    responses = []
    for i in range(3):
        response = requests.get(f"{BASE_URL}/map-config", headers=headers, timeout=10)
        if response.status_code == 200:
            responses.append(response.json())
    
    # All responses should be identical
    if len(responses) == 3:
        all_identical = responses[0] == responses[1] == responses[2]
        log_test(
            "Map config - idempotent GET (stable across repeated calls)",
            all_identical,
            f"Made 3 calls, all identical: {all_identical}"
        )
    else:
        log_test(
            "Map config - idempotent GET (stable across repeated calls)",
            False,
            f"Could not make 3 successful calls (got {len(responses)})"
        )


def test_map_config_valid_json(token: str):
    """Test 14: Map config returns valid JSON"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{BASE_URL}/map-config", headers=headers, timeout=10)
    
    try:
        data = response.json()
        is_dict = isinstance(data, dict)
        log_test(
            "Map config - returns valid JSON object",
            is_dict,
            f"Response is dict: {is_dict}"
        )
    except json.JSONDecodeError as e:
        log_test(
            "Map config - returns valid JSON object",
            False,
            f"JSON decode error: {e}"
        )


# ===== REGRESSION TESTS =====

def test_regression_login():
    """Regression Test 1: POST /api/auth/login (owner) returns 200 with token"""
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
        "Regression - POST /api/auth/login returns 200 with token",
        success and has_token,
        f"Status: {response.status_code}, has_token: {has_token}"
    )


def test_regression_photos(token: str):
    """Regression Test 2: GET /api/mobile/photos returns previously seeded photos"""
    headers = {"Authorization": f"Bearer {token}"}
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
    
    # Should have 4 photos from previous testing
    log_test(
        "Regression - GET /api/mobile/photos returns seeded photos (4 expected)",
        success and photo_count == 4,
        f"Status: {response.status_code}, photo_count: {photo_count}"
    )


def test_regression_audit(token: str):
    """Regression Test 3: GET /api/audit returns 200"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{BASE_URL}/audit", headers=headers, timeout=10)
    
    log_test(
        "Regression - GET /api/audit returns 200",
        response.status_code == 200,
        f"Status: {response.status_code}"
    )


def main():
    """Run all tests"""
    print("=" * 80)
    print("RoofSpan Backend API Tests - Map Configuration Contract Verification")
    print("=" * 80)
    print()
    
    try:
        # Test 1: Auth required
        print("--- Map Config API Contract Tests ---")
        test_map_config_auth()
        
        # Login to get token
        print("\n--- Authenticating as owner ---")
        token = login_as_owner()
        print(f"✅ Logged in successfully")
        print()
        
        # Test 2: With auth
        print("--- Map Config Response Tests ---")
        config = test_map_config_with_auth(token)
        
        if config:
            # Tests 3-12: Response shape validation
            test_map_config_response_shape(config)
            
            # Test 13: Idempotency
            test_map_config_idempotency(token)
            
            # Test 14: Valid JSON
            test_map_config_valid_json(token)
        
        # Regression tests
        print("\n--- Regression Tests (PostgreSQL persistence verification) ---")
        test_regression_login()
        test_regression_photos(token)
        test_regression_audit(token)
        
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for t in test_results if t["passed"])
    total = len(test_results)
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed < total:
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
    exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()

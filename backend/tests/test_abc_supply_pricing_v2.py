"""ABC Supply Price Items — enhancement coverage (purpose validation, 50-line batching + id mapping,
integer quantity, currency, $0-OK=unavailable, mixed success on HTTP 200, dimensional length rules).
Provider-level tests run against the mock ASGI app; HTTP tests exercise the RoofSpan endpoints + PO bulk refresh.
"""
import asyncio
import os
import uuid

import httpx
import pytest
import requests

from integrations.abc_supply.config import AbcConfig
from integrations.abc_supply import auth as abc_auth
from integrations.abc_supply import pricing as abc_pricing
from integrations.abc_supply.client import AbcClient
from integrations.abc_supply.mock_server import mock_app


def _transport():
    return httpx.ASGITransport(app=mock_app)


def _cfg():
    return AbcConfig(environment="sandbox", client_id="test-client", client_secret="test-secret",
                     redirect_uri="http://127.0.0.1:8001/api/integrations/abc/callback", webhook_public_url=None,
                     oauth_base="http://abc-mock/oauth2", api_base="http://abc-mock", is_mock=True)


def _run(coro):
    return asyncio.run(coro)


def _client():
    cfg = _cfg()

    async def tok():
        verifier, challenge = abc_auth.generate_pkce()
        params = abc_auth.build_authorize_params(client_id=cfg.client_id, redirect_uri=cfg.redirect_uri, state="s",
                                                 code_challenge=challenge, scope="product.read pricing.read offline_access")
        async with httpx.AsyncClient(transport=_transport(), base_url="http://abc-mock", follow_redirects=False) as c:
            r = await c.get("/oauth2/v1/authorize", params=params)
        code = r.headers["location"].split("code=")[1].split("&")[0]
        t = await abc_auth.exchange_code(cfg, code=code, code_verifier=verifier, transport=_transport())
        return t["access_token"]

    return AbcClient(cfg, access_token=_run(tok()), transport=_transport())


# -------------------- purpose validation --------------------
def test_purpose_valid_values():
    for p in ("estimating", "quoting", "ordering"):
        assert abc_pricing.validate_purpose(p) == p
    assert abc_pricing.validate_purpose("ORDERING") == "ordering"


def test_purpose_invalid_rejected():
    for bad in ("purchasing", "", "order", None):
        with pytest.raises(ValueError):
            abc_pricing.validate_purpose(bad)


def test_price_items_rejects_invalid_purpose():
    c = _client()
    lines = [abc_pricing.build_line(line_id="a", item_number="MOCK-SHINGLE-ARCH-WW", quantity=1, uom="SQ")]
    with pytest.raises(ValueError):
        _run(abc_pricing.price_items(c, ship_to_number="1163698", branch_number="18", lines=lines, purpose="invalid"))


# -------------------- integer quantity --------------------
def test_build_line_coerces_whole_float_to_int():
    ln = abc_pricing.build_line(line_id="x", item_number="I", quantity=2.0, uom="EA")
    assert ln["quantity"] == 2 and isinstance(ln["quantity"], int)


def test_build_line_rejects_fractional_quantity():
    with pytest.raises(ValueError):
        abc_pricing.build_line(line_id="x", item_number="I", quantity=2.5, uom="EA")


def test_build_line_rejects_nonpositive_quantity():
    for q in (0, -1):
        with pytest.raises(ValueError):
            abc_pricing.build_line(line_id="x", item_number="I", quantity=q)


# -------------------- non-dimensional does not send length --------------------
def test_build_line_omits_length_for_nondimensional():
    ln = abc_pricing.build_line(line_id="x", item_number="I", quantity=1, uom="EA")
    assert "length" not in ln


def test_build_line_includes_length_for_dimensional():
    ln = abc_pricing.build_line(line_id="x", item_number="MOCK-DRIP-EDGE-DIM", quantity=1, uom="PC",
                                length_value=4, length_uom="in")
    assert ln["length"] == {"value": 4, "uom": "in"}


# -------------------- pricing outcomes --------------------
def test_single_line_priced_with_currency():
    c = _client()
    lines = [abc_pricing.build_line(line_id="l1", item_number="MOCK-SHINGLE-ARCH-WW", quantity=10, uom="SQ")]
    res = _run(abc_pricing.price_items(c, ship_to_number="1163698", branch_number="18", lines=lines, purpose="ordering"))
    assert len(res) == 1
    r = res[0]
    assert r["price_status"] == "priced" and r["unit_price"] == 135.36
    assert r["currency"] == "USD" and r["currency_symbol"] == "$"


def test_zero_price_ok_is_unavailable_not_free():
    c = _client()
    lines = [abc_pricing.build_line(line_id="l1", item_number="MOCK-RIDGE-CAP-NOPRICE", quantity=5, uom="BD")]
    res = _run(abc_pricing.price_items(c, ship_to_number="1163698", branch_number="18", lines=lines, purpose="ordering"))
    r = res[0]
    assert r["status_code"] == "OK"  # ABC returned OK...
    assert r["price_status"] == "unavailable"  # ...but $0 = branch has not entered pricing (NOT free)
    assert r["unit_price"] == 0.0


def test_mixed_success_on_http_200():
    c = _client()
    lines = [
        abc_pricing.build_line(line_id="ok", item_number="MOCK-SHINGLE-ARCH-WW", quantity=1, uom="SQ"),
        abc_pricing.build_line(line_id="bad", item_number="DOES-NOT-EXIST", quantity=1, uom="EA"),
        abc_pricing.build_line(line_id="zero", item_number="MOCK-RIDGE-CAP-NOPRICE", quantity=1, uom="BD"),
    ]
    res = _run(abc_pricing.price_items(c, ship_to_number="1163698", branch_number="18", lines=lines, purpose="estimating"))
    by = {r["id"]: r for r in res}
    assert by["ok"]["price_status"] == "priced"
    assert by["bad"]["price_status"] == "unavailable"
    assert by["zero"]["price_status"] == "unavailable"


def test_dimensional_requires_length():
    c = _client()
    missing = [abc_pricing.build_line(line_id="d", item_number="MOCK-DRIP-EDGE-DIM", quantity=1, uom="PC")]
    r = _run(abc_pricing.price_items(c, ship_to_number="1163698", branch_number="18", lines=missing, purpose="ordering"))[0]
    assert r["price_status"] == "unavailable"
    ok = [abc_pricing.build_line(line_id="d", item_number="MOCK-DRIP-EDGE-DIM", quantity=1, uom="PC", length_value=4, length_uom="in")]
    r2 = _run(abc_pricing.price_items(c, ship_to_number="1163698", branch_number="18", lines=ok, purpose="ordering"))[0]
    assert r2["price_status"] == "priced" and r2["unit_price"] == 26.0


def test_invalid_dimensional_variation():
    c = _client()
    bad = [abc_pricing.build_line(line_id="d", item_number="MOCK-DRIP-EDGE-DIM", quantity=1, uom="PC", length_value=4, length_uom="cubits")]
    r = _run(abc_pricing.price_items(c, ship_to_number="1163698", branch_number="18", lines=bad, purpose="ordering"))[0]
    assert r["price_status"] == "unavailable"


# -------------------- 50-line batching + id mapping --------------------
def test_exactly_50_lines_single_batch():
    c = _client()
    lines = [abc_pricing.build_line(line_id=f"L{i}", item_number="MOCK-SHINGLE-ARCH-WW", quantity=1, uom="SQ") for i in range(50)]
    res = _run(abc_pricing.price_items(c, ship_to_number="1163698", branch_number="18", lines=lines, purpose="ordering"))
    assert len(res) == 50
    assert [r["id"] for r in res] == [f"L{i}" for i in range(50)]
    assert all(r["price_status"] == "priced" for r in res)


def test_over_50_lines_batched_and_reconciled_by_id():
    c = _client()
    # 120 lines mixing priced + unavailable, interleaved, to prove id-based reconciliation across batches
    lines = []
    for i in range(120):
        item = "MOCK-SHINGLE-ARCH-WW" if i % 2 == 0 else "MOCK-RIDGE-CAP-NOPRICE"
        lines.append(abc_pricing.build_line(line_id=f"L{i}", item_number=item, quantity=1,
                                            uom="SQ" if i % 2 == 0 else "BD"))
    res = _run(abc_pricing.price_items(c, ship_to_number="1163698", branch_number="18", lines=lines, purpose="quoting", request_id="EST-999"))
    assert len(res) == 120
    assert [r["id"] for r in res] == [f"L{i}" for i in range(120)]  # order preserved by id
    for i, r in enumerate(res):
        if i % 2 == 0:
            assert r["price_status"] == "priced", (i, r)
        else:
            assert r["price_status"] == "unavailable", (i, r)  # a bad batch never hides good prices


# ==================== HTTP endpoint coverage ====================
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
CLIENT_ID = "mock-client-id-123456"
CLIENT_SECRET = "mock-secret-abcdef"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def owner_headers():
    return {"Authorization": f"Bearer {_login(*OWNER)}"}


@pytest.fixture(scope="module", autouse=True)
def _ensure_connected(owner_headers):
    requests.put(f"{BASE_URL}/api/integrations/abc/config", headers=owner_headers,
                 json={"environment": "sandbox", "client_id": CLIENT_ID}, timeout=30)
    requests.put(f"{BASE_URL}/api/integrations/abc/config/secret", headers=owner_headers,
                 json={"client_secret": CLIENT_SECRET}, timeout=30)
    st = requests.get(f"{BASE_URL}/api/integrations/abc/status", headers=owner_headers, timeout=30).json()
    if st.get("status") != "connected":
        requests.post(f"{BASE_URL}/api/integrations/abc/disconnect", headers=owner_headers, timeout=30)
        r = requests.post(f"{BASE_URL}/api/integrations/abc/connect", headers=owner_headers, timeout=30)
        s = requests.Session()
        r1 = s.get(r.json()["authorize_url"], allow_redirects=False, timeout=30)
        cb = r1.headers["location"]
        if cb.startswith("/"):
            cb = BASE_URL + cb
        s.get(cb, allow_redirects=False, timeout=30)
    requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=owner_headers,
                 json={"default_ship_to_number": "1163698", "default_branch_number": "18"}, timeout=30)
    yield


def test_http_pricing_rejects_invalid_purpose(owner_headers):
    r = requests.post(f"{BASE_URL}/api/integrations/abc/pricing", headers=owner_headers, json={
        "ship_to_number": "1163698", "branch_number": "18", "purpose": "purchasing",
        "lines": [{"id": "a", "item_number": "MOCK-SHINGLE-ARCH-WW", "quantity": 1, "uom": "SQ"}]}, timeout=30)
    assert r.status_code == 422, r.text[:300]


def test_http_pricing_all_three_purposes(owner_headers):
    for purpose in ("estimating", "quoting", "ordering"):
        r = requests.post(f"{BASE_URL}/api/integrations/abc/pricing", headers=owner_headers, json={
            "ship_to_number": "1163698", "branch_number": "18", "purpose": purpose, "request_id": f"T-{purpose}",
            "lines": [{"id": "a", "item_number": "MOCK-SHINGLE-ARCH-WW", "quantity": 2, "uom": "SQ"}]}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        line = r.json()["lines"][0]
        assert line["price_status"] == "priced" and line["currency_symbol"] == "$"


def test_http_pricing_rejects_fractional_quantity(owner_headers):
    r = requests.post(f"{BASE_URL}/api/integrations/abc/pricing", headers=owner_headers, json={
        "ship_to_number": "1163698", "branch_number": "18", "purpose": "ordering",
        "lines": [{"id": "a", "item_number": "MOCK-SHINGLE-ARCH-WW", "quantity": 2.5, "uom": "SQ"}]}, timeout=30)
    assert r.status_code == 400, r.text[:300]


def _create_abc_po(headers, items):
    payload = {"supplier_name": "ABC Supply", "integration_provider": "abc_supply",
               "abc_ship_to_number": "1163698", "abc_branch_number": "18", "items": items}
    r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=headers, json=payload, timeout=30)
    assert r.status_code in (200, 201), r.text[:300]
    return r.json()


def _abc_line(item, qty, cost, uom="SQ", desc="Mock item"):
    return {"description": desc, "quantity": qty, "unit": uom, "unit_cost": cost,
            "integration_provider": "abc_supply", "abc_item_number": item, "abc_branch_number": "18",
            "abc_ship_to_number": "1163698", "abc_uom": uom, "abc_price": cost,
            "abc_price_status": "priced" if cost > 0 else "unavailable", "pricing_source": "abc"}


def test_po_bulk_refresh_all_prices(owner_headers):
    po = _create_abc_po(owner_headers, [
        _abc_line("MOCK-SHINGLE-ARCH-WW", 3, 100.0, desc="Shingle"),
        _abc_line("MOCK-UNDERLAYMENT-30", 2, 50.0, uom="RL", desc="Underlayment"),
    ])
    r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-refresh-all-prices",
                      headers=owner_headers, json={"apply_price_changes": True}, timeout=60)
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert d["ok"] is True and len(d["lines"]) == 2
    assert all(l["price_status"] == "priced" for l in d["lines"]), d["lines"]
    assert "prices_verified_at" in d

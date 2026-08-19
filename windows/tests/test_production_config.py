"""P1-4a: production packaged-config readiness (static; in-container)."""
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # windows/
APP = os.path.dirname(HERE)
TEMPLATE = os.path.join(HERE, "winbuild", "config", "roofspan.env.template")
WXS = os.path.join(HERE, "installer", "RoofSpan.wxs")


def _read(p):
    with open(p) as f:
        return f.read()


def test_template_uses_production_modes():
    t = _read(TEMPLATE)
    assert "LICENSING_MODE=http" in t          # real CP client, NOT dev / no 1000-seat auto-issue
    # Billing is CENTRAL ONLY: the customer PC must NOT be a Stripe billing authority.
    assert "BILLING_MODE=stripe" not in t
    assert "STRIPE_SECRET_KEY" not in t and "STRIPE_WEBHOOK_SECRET" not in t
    # Licensing/billing Control Plane API base (public URL, includes API prefix, not localhost).
    assert "LICENSING_CONTROL_PLANE_URL=https://cp.roofspan.io/api/control-plane" in t
    assert "LICENSING_CONTROL_PLANE_URL=http://127.0.0.1" not in t
    assert "LICENSING_CONTROL_PLANE_URL=http://localhost" not in t


def test_template_local_runtime_targets():
    t = _read(TEMPLATE)
    assert "ROOFSPAN_LOCAL_API_URL=http://127.0.0.1:8001" in t
    assert "127.0.0.1:5442/roofspan" in t      # dedicated RoofSpan-managed local PostgreSQL port
    assert "__GENERATED_AT_FIRST_RUN__" in t   # DB password not shipped


def test_template_central_service_urls():
    t = _read(TEMPLATE)
    assert "CONTROL_PLANE_BASE_URL=https://cp.roofspan.io" in t
    assert "RELAY_WSS_URL=wss://relay.roofspan.io" in t
    assert "ROOFSPAN_WINDOWS_UPDATE_MANIFEST_URL=https://downloads.roofspan.io/update/windows/latest.json" in t


def test_template_contains_no_secrets():
    t = _read(TEMPLATE)
    for bad in ("JWT_SECRET=", "SECRETS_ENCRYPTION_KEY=", "STRIPE_SECRET_KEY=", "sk_live", "sk_test",
                "PRIVATE KEY", "STRIPE_WEBHOOK_SECRET="):
        assert bad not in t, f"template must not ship secret: {bad}"
    # only the PUBLIC update-verification key ships (no private signing material / PEM private headers)
    assert "update_public_key.pem" in t
    assert "PRIVATE KEY" not in t and "private_key" not in t


def test_no_preview_hostname_in_packaged_config():
    for p in (TEMPLATE, WXS):
        assert "preview.emergentagent.com" not in _read(p)
        assert "emergentagent" not in _read(p)


def test_frontend_api_base_falls_back_to_same_origin():
    api = _read(os.path.join(APP, "frontend", "src", "lib", "api.js"))
    # packaged build (no REACT_APP_BACKEND_URL) -> relative same-origin "/api"
    assert 'process.env.REACT_APP_BACKEND_URL || ""' in api

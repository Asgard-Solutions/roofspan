"""Static security-boundary tests for the Vercel operator (Cognito) auth module.

Run: cd /app && python -m pytest backend/tests/test_operator_auth_vercel.py -o addopts='' -q
"""
import glob
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # /app
VC = os.path.join(REPO, "deploy", "vercel")


def _read(p):
    with open(p) as f:
        return f.read()


def _all_client_side():
    # Browser-served assets (must contain NO secrets and NO token storage).
    files = glob.glob(os.path.join(VC, "public", "**", "*.*"), recursive=True)
    return "\n".join(_read(f) for f in files)


def test_callback_route_exists_and_maps_to_operator_callback():
    assert os.path.isfile(os.path.join(VC, "api", "operator", "callback.js"))
    vj = _read(os.path.join(VC, "vercel.json"))
    assert '"source": "/operator/callback"' in vj
    assert '"destination": "/api/operator/callback"' in vj
    assert '"source": "/operator/login"' in vj


def test_state_and_code_validation_present():
    lib = _read(os.path.join(VC, "api", "operator", "_lib.js"))
    # rejects missing/mismatched state and missing code
    assert "query.state !== cookies.op_state" in lib
    assert "Invalid or expired sign-in state." in lib
    assert "Missing authorization code." in lib
    assert "code_verifier" in lib and "code_challenge_method" in _read(os.path.join(VC, "api", "operator", "login.js"))


def test_token_stored_in_httponly_cookie_not_localstorage():
    server = "\n".join(_read(p) for p in glob.glob(os.path.join(VC, "api", "operator", "*.js")))
    assert "HttpOnly" in server and "SameSite=Lax" in server and "Secure" in server
    # never any localStorage/sessionStorage anywhere (client or server)
    everything = server + "\n" + _all_client_side()
    assert "localStorage" not in everything
    assert "sessionStorage" not in everything


def test_no_cognito_client_secret_shipped_to_browser():
    client = _all_client_side()
    assert "COGNITO_CLIENT_SECRET" not in client
    assert "client_secret" not in client.lower()
    # The secret is referenced ONLY server-side and only for the optional confidential-client Basic header.
    lib = _read(os.path.join(VC, "api", "operator", "_lib.js"))
    assert "process.env.COGNITO_CLIENT_SECRET" in lib


def test_production_callback_url_exact():
    lib = _read(os.path.join(VC, "api", "operator", "_lib.js"))
    assert "https://roofspan.io/operator/callback" in lib


def test_bearer_is_id_token_and_hits_control_plane_operator_endpoint():
    cb = _read(os.path.join(VC, "api", "operator", "callback.js"))
    assert "tokens.id_token" in cb          # id_token (aud=client_id) is the CP bearer, not the access token
    who = _read(os.path.join(VC, "api", "operator", "whoami.js"))
    assert "/api/control-plane/operator/me" in who
    assert "Authorization" in who and "Bearer ${token}" in who


def test_callback_errors_are_safe():
    cb = _read(os.path.join(VC, "api", "operator", "callback.js"))
    # generic user-facing messages; no token/secret/stack leakage
    assert "Operator sign-in failed. Please try again." in cb
    assert "stack" not in cb.lower()

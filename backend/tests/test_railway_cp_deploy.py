"""Railway Control Plane deployment-boundary tests (static + unit; no cloud/network).

Proves the Railway image serves ONLY the central Control Plane, binds via $PORT, fails closed in
production, keeps Stripe/DB config central, and ships no Windows packaging deps.

Run: cd /app/backend && python -m pytest tests/test_railway_cp_deploy.py -o addopts='' -q
"""
import os
import re

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # backend/
REPO = os.path.dirname(BACKEND)


def _read(p):
    with open(p) as f:
        return f.read()


def test_cp_asgi_exposes_only_control_plane_and_health():
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:y@127.0.0.1:5432/z")
    os.environ.setdefault("CONTROL_PLANE_DATABASE_URL", "postgresql+asyncpg://x:y@127.0.0.1:5432/z_cp")
    import cp_asgi
    paths = {getattr(r, "path", "") for r in cp_asgi.app.routes}
    assert "/health" in paths
    assert any(p.startswith("/api/control-plane") for p in paths), "must expose the Control Plane API"
    # Must NOT mount the RoofSpan Office customer surface.
    for office in ("/api/leads", "/api/jobs", "/api/inventory", "/api/customers", "/api/invoices"):
        assert office not in paths, f"Control Plane image must not expose {office}"
    # Central Stripe boundary routes preserved.
    assert "/api/control-plane/billing/stripe/webhook" in paths
    assert "/api/control-plane/billing/stripe/initial-checkout" in paths


def test_start_command_binds_via_railway_port_no_hardcoded_port():
    import json
    rj_text = _read(os.path.join(REPO, "railway.json"))
    rj = json.loads(rj_text)
    # Railway must NOT define a deploy.startCommand: it is executed WITHOUT a shell, so "$PORT" would be
    # passed literally to uvicorn ("Invalid value for '--port': '$PORT'"). The Dockerfile CMD (sh -c) is
    # the single source of truth for process startup and expands $PORT correctly.
    assert "startCommand" not in rj.get("deploy", {}), "railway.json must not define deploy.startCommand"
    assert rj["deploy"]["healthcheckPath"] == "/health"        # healthcheck preserved
    # The shell-expanding startup lives in the Dockerfile and honours Railway's $PORT with no hardcoded port.
    df = _read(os.path.join(REPO, "deploy", "railway", "Dockerfile"))
    assert "sh" in df and "-c" in df                           # shell-based CMD
    assert "${PORT:-8080}" in df                               # expands $PORT (fallback for local runs)
    assert "uvicorn cp_asgi:app" in df and "--host 0.0.0.0" in df
    assert "--port 8000" not in df and "--port 8001" not in df


def test_production_config_fails_closed(monkeypatch):
    import control_plane.config as cfg
    monkeypatch.setattr(cfg, "CP_ENV", "production")
    monkeypatch.setattr(cfg, "BILLING_MODE", "stripe")
    monkeypatch.setattr(cfg, "STRIPE_SECRET_KEY", "")          # missing -> must fail
    monkeypatch.setattr(cfg, "STRIPE_WEBHOOK_SECRET", "")
    monkeypatch.setattr(cfg, "CONTROL_PLANE_DATABASE_URL", "postgresql+asyncpg://u:p@db.railway.internal:5432/cp")
    monkeypatch.setattr(cfg, "ENTITLEMENT_SIGNER", "kms")
    monkeypatch.setattr(cfg, "CP_KMS_SIGNING_KEY_ID", "")
    monkeypatch.setattr(cfg, "CP_OPERATOR_ISSUER", "")
    monkeypatch.setattr(cfg, "CP_OPERATOR_AUDIENCE", "")
    with pytest.raises(RuntimeError) as e:
        cfg.require_production_config()
    msg = str(e.value)
    assert "Stripe" in msg and "KMS" in msg and "operator" in msg


def test_production_requires_control_plane_db_and_rejects_localhost(monkeypatch):
    import control_plane.config as cfg
    for k, v in {"CP_ENV": "production", "BILLING_MODE": "stripe", "STRIPE_SECRET_KEY": "sk",
                 "STRIPE_WEBHOOK_SECRET": "wh", "ENTITLEMENT_SIGNER": "kms",
                 "CP_KMS_SIGNING_KEY_ID": "kid", "CP_OPERATOR_ISSUER": "iss",
                 "CP_OPERATOR_AUDIENCE": "aud"}.items():
        monkeypatch.setattr(cfg, k, v)
    # missing DB url
    monkeypatch.setattr(cfg, "CONTROL_PLANE_DATABASE_URL", "")
    with pytest.raises(RuntimeError, match="CONTROL_PLANE_DATABASE_URL"):
        cfg.require_production_config()
    # localhost DB url rejected in production
    monkeypatch.setattr(cfg, "CONTROL_PLANE_DATABASE_URL", "postgresql+asyncpg://u:p@127.0.0.1:5432/cp")
    with pytest.raises(RuntimeError, match="localhost"):
        cfg.require_production_config()
    # a proper private Railway URL passes
    monkeypatch.setattr(cfg, "CONTROL_PLANE_DATABASE_URL", "postgresql+asyncpg://u:p@postgres.railway.internal:5432/railway")
    cfg.require_production_config()  # no raise


def test_railway_url_normalized_to_async_driver():
    import control_plane.config as cfg
    assert cfg._normalize_async("postgresql://u:p@h:5432/db") == "postgresql+asyncpg://u:p@h:5432/db"
    assert cfg._normalize_async("postgres://u:p@h:5432/db") == "postgresql+asyncpg://u:p@h:5432/db"
    assert cfg._normalize_async("postgresql+asyncpg://u:p@h:5432/db") == "postgresql+asyncpg://u:p@h:5432/db"


def test_railway_image_has_no_windows_or_frontend_deps():
    df = _read(os.path.join(REPO, "deploy", "railway", "Dockerfile"))
    low = df.lower()
    for bad in ("pywin32", "pyinstaller", "wix", "webview2", "requirements-windows", "npm ", "yarn ", "dotnet"):
        assert bad not in low, f"Railway image must not include {bad}"
    assert "backend/requirements.txt" in df   # reuse the Linux-safe backend deps
    # And backend/requirements.txt itself is Linux/cloud-safe.
    reqs = _read(os.path.join(BACKEND, "requirements.txt")).lower()
    assert "pywin32" not in reqs and "pyinstaller" not in reqs


def test_docs_and_secret_hygiene():
    readme = _read(os.path.join(REPO, "deploy", "railway", "README.md"))
    assert "cp.roofspan.io" in readme
    assert "${{Postgres.DATABASE_URL}}" in readme
    assert "/api/control-plane/billing/stripe/webhook" in readme
    # No real secret values committed.
    assert not re.search(r"sk_live_[A-Za-z0-9]{6,}", readme)
    assert not re.search(r"whsec_[A-Za-z0-9]{6,}", readme)

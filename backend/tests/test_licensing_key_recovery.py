"""P0 upgrade-hardening: trusted Control Plane key persistence + automatic safe recovery.

Covers the real production upgrade failure: an MSI major upgrade replaced Program Files and deleted
the cached CP public verification key, so a valid ACTIVE signed entitlement in the DB could no longer
be verified and the installation wrongly fell to SUSPENDED.

These are pure-logic tests: the cache row, activation flag, and Control Plane client are stubbed via
monkeypatch so no live DB/CP is required. The trusted-key directory is redirected to a tmp dir.
"""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from licensing import service, keys, config
from licensing import entitlement as ent
from licensing import control_plane
from licensing.entitlement import ACTIVE, SUSPENDED

run = asyncio.run


def _keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")
    return priv, pub


def _sign(priv, kid, *, state=ACTIVE, seats=5, grace_days=7, issued=None):
    now = issued or datetime.now(timezone.utc)
    claims = {
        "installation_id": "inst-1", "company_id": "co-1", "license_id": "lic-1",
        "subscription_state": state, "seats_licensed": seats, "product": "roofspan-office",
        "min_supported_version": "1.0.0", "issued_at": now,
        "refresh_at": now + timedelta(hours=12), "grace_until": now + timedelta(days=grace_days),
        "nonce": uuid.uuid4().hex,
    }
    return ent.sign_entitlement(private_key=priv, kid=kid, claims=claims)


class _Row:
    def __init__(self, jws, kid):
        self.entitlement_jws = jws
        self.kid = kid


class _FakeClient:
    def __init__(self, pubs=None, *, unavailable=False):
        self._pubs = pubs or {}
        self.unavailable = unavailable
        self.calls = 0

    async def fetch_public_signing_keys(self):
        self.calls += 1
        if self.unavailable:
            raise control_plane.ControlPlaneUnavailable("Control Plane down")
        return self._pubs


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Redirect trusted-keys dir to a clean tmp dir, activated http mode, throttle reset."""
    monkeypatch.setattr(config, "TRUSTED_KEYS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "LICENSING_MODE", "http")

    async def _activated(_db):
        return True
    monkeypatch.setattr(service, "is_activated", _activated)
    service.reset_recovery_throttle()
    return tmp_path


def _set_row(monkeypatch, row):
    async def _get(_db):
        return row
    monkeypatch.setattr(service, "_get_cache_row", _get)


def _set_client(monkeypatch, client):
    monkeypatch.setattr(control_plane, "get_client", lambda: client)


# ----------------------------------------------------------------------------------------------
# A. Cached CP key present -> verifies with no recovery needed.
# ----------------------------------------------------------------------------------------------
def test_verifies_when_trusted_key_present(env, monkeypatch):
    priv, pub = _keypair()
    kid = "cp-2026-aaaa"
    keys.cache_trusted_cp_keys({kid: pub})
    _set_row(monkeypatch, _Row(_sign(priv, kid, seats=5), kid))
    client = _FakeClient({kid: pub})
    _set_client(monkeypatch, client)

    e = run(service.load_cached_entitlement(db=None))
    assert e is not None and e.subscription_state == ACTIVE and e.seats_licensed == 5
    assert client.calls == 0  # no recovery attempted


# ----------------------------------------------------------------------------------------------
# C. Broken-machine recovery: trusted key missing, valid entitlement, CP returns the public key.
# ----------------------------------------------------------------------------------------------
def test_recovers_missing_key_and_reverifies(env, monkeypatch):
    priv, pub = _keypair()
    kid = "cp-2026-bbbb"
    # trusted dir intentionally EMPTY (upgrade removed it)
    _set_row(monkeypatch, _Row(_sign(priv, kid, seats=5), kid))
    client = _FakeClient({kid: pub})
    _set_client(monkeypatch, client)

    e = run(service.load_cached_entitlement(db=None))
    assert e is not None and e.subscription_state == ACTIVE and e.seats_licensed == 5
    assert client.calls == 1
    # key was persisted under the (ProgramData-style) trusted dir for offline use next start
    assert (env / f"{kid}.public.pem").is_file()
    assert kid in keys.load_trusted_cp_keys()


# ----------------------------------------------------------------------------------------------
# E. CP unavailable AND trusted key missing -> fail closed, no invented trust, no mutation.
# ----------------------------------------------------------------------------------------------
def test_cp_unavailable_and_key_missing_fails_closed(env, monkeypatch):
    priv, _pub = _keypair()
    kid = "cp-2026-cccc"
    _set_row(monkeypatch, _Row(_sign(priv, kid), kid))
    client = _FakeClient(unavailable=True)
    _set_client(monkeypatch, client)

    e = run(service.load_cached_entitlement(db=None))
    assert e is None  # fail closed
    assert client.calls == 1
    assert list(env.glob("*.public.pem")) == []  # nothing written


# ----------------------------------------------------------------------------------------------
# F. Tampered entitlement: recovering the genuine public key must NOT validate a tampered token.
# ----------------------------------------------------------------------------------------------
def test_tampered_entitlement_not_saved_by_recovery(env, monkeypatch):
    priv, pub = _keypair()
    kid = "cp-2026-dddd"
    token = _sign(priv, kid)
    head, payload, sig = token.split(".")
    tampered = f"{head}.{payload[:-2] + ('AA' if payload[-2:] != 'AA' else 'BB')}.{sig}"
    _set_row(monkeypatch, _Row(tampered, kid))
    client = _FakeClient({kid: pub})
    _set_client(monkeypatch, client)

    e = run(service.load_cached_entitlement(db=None))
    assert e is None  # bad signature -> never honored (recovery ran once, re-verify still fails)


# ----------------------------------------------------------------------------------------------
# Expired entitlement (offline grace exhausted) -> None, no recovery attempted.
# ----------------------------------------------------------------------------------------------
def test_expired_entitlement_fails_closed(env, monkeypatch):
    priv, pub = _keypair()
    kid = "cp-2026-eeee"
    keys.cache_trusted_cp_keys({kid: pub})
    old = datetime.now(timezone.utc) - timedelta(days=10)
    _set_row(monkeypatch, _Row(_sign(priv, kid, issued=old, grace_days=7), kid))
    client = _FakeClient({kid: pub})
    _set_client(monkeypatch, client)

    e = run(service.load_cached_entitlement(db=None))
    assert e is None
    assert client.calls == 0  # expiry is not a recoverable-key situation


# ----------------------------------------------------------------------------------------------
# G. Signing-key rotation: old still-trusted kid and a new kid both verify (merge, not clobber).
# ----------------------------------------------------------------------------------------------
def test_rotation_old_and_new_keys_both_verify(env, monkeypatch):
    priv_old, pub_old = _keypair()
    priv_new, pub_new = _keypair()
    kid_old, kid_new = "cp-2026-old0", "cp-2026-new0"
    keys.cache_trusted_cp_keys({kid_old: pub_old})
    # rotation caches the new key WITHOUT deleting the old one
    keys.cache_trusted_cp_keys({kid_new: pub_new})
    client = _FakeClient()
    _set_client(monkeypatch, client)

    _set_row(monkeypatch, _Row(_sign(priv_old, kid_old), kid_old))
    e_old = run(service.load_cached_entitlement(db=None))
    _set_row(monkeypatch, _Row(_sign(priv_new, kid_new), kid_new))
    e_new = run(service.load_cached_entitlement(db=None))
    assert e_old is not None and e_new is not None
    assert client.calls == 0
    assert {kid_old, kid_new}.issubset(set(keys.load_trusted_cp_keys().keys()))


# ----------------------------------------------------------------------------------------------
# Recovery is throttled: a persistent CP outage does not hammer the network.
# ----------------------------------------------------------------------------------------------
def test_recovery_is_throttled_on_repeated_failure(env, monkeypatch):
    priv, _pub = _keypair()
    kid = "cp-2026-ffff"
    _set_row(monkeypatch, _Row(_sign(priv, kid), kid))
    client = _FakeClient(unavailable=True)
    _set_client(monkeypatch, client)

    assert run(service.load_cached_entitlement(db=None)) is None
    assert run(service.load_cached_entitlement(db=None)) is None
    assert client.calls == 1  # second attempt throttled


# ----------------------------------------------------------------------------------------------
# Recovery is skipped for a non-activated installation and in dev mode (no invented trust).
# ----------------------------------------------------------------------------------------------
def test_recovery_skipped_when_not_activated(env, monkeypatch):
    async def _not_activated(_db):
        return False
    monkeypatch.setattr(service, "is_activated", _not_activated)
    priv, pub = _keypair()
    kid = "cp-2026-gggg"
    _set_row(monkeypatch, _Row(_sign(priv, kid), kid))
    client = _FakeClient({kid: pub})
    _set_client(monkeypatch, client)

    assert run(service.load_cached_entitlement(db=None)) is None
    assert client.calls == 0


def test_recovery_skipped_in_dev_mode(env, monkeypatch):
    monkeypatch.setattr(config, "LICENSING_MODE", "dev")
    priv, pub = _keypair()
    kid = "cp-2026-hhhh"
    _set_row(monkeypatch, _Row(_sign(priv, kid), kid))
    client = _FakeClient({kid: pub})
    _set_client(monkeypatch, client)

    assert run(service.load_cached_entitlement(db=None)) is None
    assert client.calls == 0


# ----------------------------------------------------------------------------------------------
# cache_trusted_cp_keys hardening: merge (never clobber) + reject invalid PEM + skip bad files.
# ----------------------------------------------------------------------------------------------
def test_cache_merges_and_rejects_invalid(env):
    _p1, pub1 = _keypair()
    _p2, pub2 = _keypair()
    assert keys.cache_trusted_cp_keys({"k1": pub1}) == 1
    assert keys.cache_trusted_cp_keys({"k2": pub2}) == 1  # merge, does not remove k1
    loaded = keys.load_trusted_cp_keys()
    assert {"k1", "k2"}.issubset(loaded.keys())
    # invalid PEM is refused (not written) and a malformed file on disk is skipped on load
    assert keys.cache_trusted_cp_keys({"bad": "not-a-pem"}) == 0
    (env / "junk.public.pem").write_text("garbage")
    reloaded = keys.load_trusted_cp_keys()
    assert "junk" not in reloaded and {"k1", "k2"}.issubset(reloaded.keys())


# ----------------------------------------------------------------------------------------------
# state.evaluate: a verified entitlement is ACTIVE; None (unverifiable) is SUSPENDED (fail closed).
# ----------------------------------------------------------------------------------------------
def test_effective_state_active_after_recovery_none_is_suspended(env, monkeypatch):
    from licensing import state as state_mod
    priv, pub = _keypair()
    kid = "cp-2026-iiii"
    _set_row(monkeypatch, _Row(_sign(priv, kid, seats=5), kid))
    _set_client(monkeypatch, _FakeClient({kid: pub}))
    e = run(service.load_cached_entitlement(db=None))
    assert state_mod.evaluate(e).effective_state == ACTIVE
    assert state_mod.evaluate(None).effective_state == SUSPENDED

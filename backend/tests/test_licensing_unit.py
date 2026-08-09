"""Phase C0 unit tests: entitlement sign/verify (crypto) + state-machine evaluation.

Pure-function tests — no server or database required.
"""
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from licensing import keys
from licensing import entitlement as ent
from licensing import state as state_mod
from licensing.entitlement import ACTIVE, GRACE, SUSPENDED, CANCELLED


def _claims(installation_id="inst-1", company_id="co-1", state=ACTIVE, seats=10,
            issued=None, grace_days=7, refresh_hours=12):
    now = issued or datetime.now(timezone.utc)
    return {
        "installation_id": installation_id,
        "company_id": company_id,
        "license_id": "lic-1",
        "subscription_state": state,
        "seats_licensed": seats,
        "product": "roofspan-office",
        "min_supported_version": "1.0.0",
        "issued_at": now,
        "refresh_at": now + timedelta(hours=refresh_hours),
        "grace_until": now + timedelta(days=grace_days),
        "nonce": uuid.uuid4().hex,
    }


def _sign(claims):
    kid, priv = keys.get_dev_signing_key()
    return ent.sign_entitlement(private_key=priv, kid=kid, claims=claims)


def test_sign_and_verify_roundtrip():
    token = _sign(_claims(state=ACTIVE, seats=15))
    e = ent.verify_entitlement(token, keys.get_trusted_verify_keys())
    assert e.subscription_state == ACTIVE
    assert e.seats_licensed == 15
    assert e.installation_id == "inst-1"
    assert e.product == "roofspan-office"
    assert e.kid == keys.get_dev_signing_key()[0]


def test_tampered_token_rejected():
    token = _sign(_claims())
    # flip a character in the payload segment
    head, payload, sig = token.split(".")
    bad_payload = payload[:-2] + ("AA" if payload[-2:] != "AA" else "BB")
    tampered = f"{head}.{bad_payload}.{sig}"
    with pytest.raises(ent.EntitlementError):
        ent.verify_entitlement(tampered, keys.get_trusted_verify_keys())


def test_unknown_kid_rejected():
    token = _sign(_claims())
    with pytest.raises(ent.EntitlementError):
        ent.verify_entitlement(token, {})  # no trusted keys


def test_expired_entitlement_rejected():
    # issued 10 days ago with a 7-day grace -> exp (=grace_until) is in the past
    old = datetime.now(timezone.utc) - timedelta(days=10)
    token = _sign(_claims(issued=old, grace_days=7))
    with pytest.raises(ent.EntitlementError):
        ent.verify_entitlement(token, keys.get_trusted_verify_keys())


def _entitlement(state=ACTIVE, grace_days=7, issued=None):
    now = issued or datetime.now(timezone.utc)
    return ent.Entitlement(
        kid="k", installation_id="i", company_id="c", license_id="l",
        subscription_state=state, seats_licensed=10, product="roofspan-office",
        min_supported_version="1.0.0", issued_at=now,
        refresh_at=now + timedelta(hours=12), grace_until=now + timedelta(days=grace_days),
        nonce="n",
    )


def test_state_active_allows_business():
    s = state_mod.evaluate(_entitlement(ACTIVE))
    assert s.effective_state == ACTIVE and s.business_access is True and s.within_offline_grace is True


def test_state_grace_allows_business():
    s = state_mod.evaluate(_entitlement(GRACE))
    assert s.effective_state == GRACE and s.reported_state == GRACE and s.business_access is True


def test_state_suspended_blocks_immediately():
    s = state_mod.evaluate(_entitlement(SUSPENDED))
    assert s.effective_state == SUSPENDED and s.business_access is False


def test_state_cancelled_blocks():
    s = state_mod.evaluate(_entitlement(CANCELLED))
    assert s.effective_state == CANCELLED and s.business_access is False


def test_state_none_is_suspended():
    s = state_mod.evaluate(None)
    assert s.effective_state == SUSPENDED and s.reported_state == "UNLICENSED"


def test_offline_grace_exhausted_fails_closed():
    # ACTIVE entitlement whose grace_until is already in the past -> fail closed to SUSPENDED,
    # but reported_state still reflects the last-known ACTIVE (distinguishes outage from suspension).
    old = datetime.now(timezone.utc) - timedelta(days=10)
    s = state_mod.evaluate(_entitlement(ACTIVE, grace_days=7, issued=old))
    assert s.effective_state == SUSPENDED
    assert s.reported_state == ACTIVE
    assert s.within_offline_grace is False

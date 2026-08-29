"""Office/Field Property parity + canonical visit outcomes + Sales authorization (IDOR) hardening.

Runnable: PYTHONPATH=backend pytest -q backend/tests/test_property_parity.py

Proves:
  1. GET /api/properties/{id} (Office) and GET /api/mobile/properties/{id} (Field) build IDENTICAL
     canonical Property detail from the SAME builder — every attribute, contacts[], visits[], lead_id,
     location_diagnostics, created_at/updated_at.
  2. The three temporary Field compat aliases (owner_name/owner_phone/existing_lead_id) are derived
     directly from the canonical values (owner contact / lead_id).
  3. Canonical lead_id = most-recent NON-archived lead; a newer ARCHIVED lead never wins, archived-only
     yields null.
  4. All six canonical visit outcomes validate; an unsupported outcome is rejected (Office + Field schemas).
  5. An authorized salesperson can read the property (canvass scope); an unauthorized rep is 403 on BOTH
     the mobile route AND the Office route (direct-UUID IDOR blocked server-side).
"""
import sys
import uuid as _uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "backend")

import pytest  # noqa: F401  (kept: pytest test discovery)
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete

from db import SessionLocal
from models import (
    Property, PropertyContact, Visit, Lead, Territory, CanvassSection, CanvassSectionProperty,
)
from schemas_phase2 import VisitIn
from routers.properties import get_property as office_get_property
from routers.mobile import get_property as mobile_get_property, MobileVisitIn
from visit_outcomes import VALID_VISIT_OUTCOMES

from _sketch_fixtures import FakeUser, seed_user, run_isolated

CANONICAL_KEYS = [
    "id", "external_id", "source", "territory_id", "formatted_address", "address_line1", "city",
    "state", "zip_code", "latitude", "longitude", "property_type", "bedrooms", "bathrooms",
    "square_footage", "year_built", "owner_occupied", "do_not_knock", "do_not_knock_reason", "notes",
    "contacts", "visits", "lead_id", "location_diagnostics", "created_at", "updated_at",
]


async def _run():
    db = SessionLocal()
    made = {"territory": None, "property": None, "section": None, "leads": [], "users": []}
    try:
        # --- Users: an authorized rep (assigned canvass section) + an unauthorized rep ---
        rep = await seed_user(db, role="sales", label="RS Rep A"); made["users"].append(rep.id)
        rep_other = await seed_user(db, role="sales", label="RS Rep B"); made["users"].append(rep_other.id)
        owner = await seed_user(db, role="owner", label="RS Owner"); made["users"].append(owner.id)

        # --- A richly populated Property (every canonical attribute + location diagnostics) ---
        p = Property(
            id=_uuid.uuid4(), external_id="RS-PARITY-EXT-1", source="rentcast",
            formatted_address="742 Evergreen Terrace, Springfield, OR 97403",
            address_line1="742 Evergreen Terrace", address_line2="Unit B",
            city="Springfield", state="OR", zip_code="97403",
            latitude=44.045, longitude=-123.071, property_type="single_family",
            bedrooms=4, bathrooms=2.5, square_footage=2450, year_built=1998, owner_occupied=True,
            do_not_knock=True, do_not_knock_reason="Requested no contact", notes="Corner lot, big roof",
            raw={"roofspan_location": {"confidence": "high", "geocoder": "test", "parcel": "12-345"}},
        )
        db.add(p); made["property"] = p.id
        await db.flush()

        db.add_all([
            PropertyContact(id=_uuid.uuid4(), property_id=p.id, kind="owner", name="Homer S",
                            contact_type="Individual", mailing_address="PO Box 1, Springfield OR",
                            phone="555-0100", email="homer@example.com"),
            PropertyContact(id=_uuid.uuid4(), property_id=p.id, kind="renter", name="Ned F",
                            contact_type="Individual", phone="555-0199", email="ned@example.com"),
        ])
        now = datetime.now(timezone.utc)
        db.add_all([
            Visit(id=_uuid.uuid4(), property_id=p.id, user_id=rep.id, user_email=rep.email,
                  visited_at=now - timedelta(days=2), outcome="no_answer", notes="nobody home"),
            Visit(id=_uuid.uuid4(), property_id=p.id, user_id=rep.id, user_email=rep.email,
                  visited_at=now - timedelta(hours=3), outcome="interested", notes="wants a quote"),
        ])

        # Leads: an OLDER active lead, a NEWER ARCHIVED lead (must NOT win as canonical lead_id).
        active_lead = Lead(id=_uuid.uuid4(), property_id=p.id, assigned_user_id=rep.id,
                           name="Active lead", status="new", created_at=now - timedelta(days=5))
        archived_newer = Lead(id=_uuid.uuid4(), property_id=p.id, assigned_user_id=rep.id,
                              name="Archived newer", status="archived", created_at=now - timedelta(days=1))
        db.add_all([active_lead, archived_newer])
        made["leads"] = [active_lead.id, archived_newer.id]

        # Canvass section assigned to rep, containing the property -> rep is authorized.
        terr = Territory(id=_uuid.uuid4(), name="RS Parity Territory",
                         geometry={"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]})
        db.add(terr); made["territory"] = terr.id
        await db.flush()
        section = CanvassSection(id=_uuid.uuid4(), territory_id=terr.id, name="Sec A",
                                 geometry={"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
                                 assigned_user_id=rep.id, active=True)
        db.add(section); made["section"] = section.id
        await db.flush()
        db.add(CanvassSectionProperty(id=_uuid.uuid4(), section_id=section.id, property_id=p.id))
        await db.commit()

        owner_u = FakeUser(owner.id, role="owner", email=owner.email)
        rep_u = FakeUser(rep.id, role="sales", email=rep.email)
        rep_other_u = FakeUser(rep_other.id, role="sales", email=rep_other.email)

        # ---- 1 & 3. Parity: Office and Field build the SAME canonical detail ----
        office = (await office_get_property(str(p.id), user=owner_u, db=db)).model_dump()
        mobile = await mobile_get_property(str(p.id), user=rep_u, db=db)
        for k in CANONICAL_KEYS:
            assert office[k] == mobile[k], f"canonical field '{k}' differs: office={office[k]!r} mobile={mobile[k]!r}"
        # every canonical attribute is present and correct
        assert office["external_id"] == "RS-PARITY-EXT-1"
        assert office["bedrooms"] == 4 and office["bathrooms"] == 2.5 and office["square_footage"] == 2450
        assert office["year_built"] == 1998 and office["owner_occupied"] is True
        assert office["latitude"] == 44.045 and office["longitude"] == -123.071
        assert office["do_not_knock"] is True and office["do_not_knock_reason"] == "Requested no contact"
        assert office["location_diagnostics"] == {"confidence": "high", "geocoder": "test", "parcel": "12-345"}
        assert len(office["contacts"]) == 2 and len(office["visits"]) == 2
        assert office["updated_at"] is not None
        # canonical lead_id = most-recent NON-archived lead (archived newer must NOT win)
        assert office["lead_id"] == str(active_lead.id), "archived newer lead must not become canonical lead_id"
        print("PASS: Office/Field canonical parity + all attributes + non-archived lead_id selection")

        # ---- 2. Field compat aliases derived from canonical values ----
        owner_contact = next(c for c in mobile["contacts"] if c["kind"] == "owner")
        assert mobile["owner_name"] == owner_contact["name"] == "Homer S"
        assert mobile["owner_phone"] == owner_contact["phone"] == "555-0100"
        assert mobile["existing_lead_id"] == mobile["lead_id"] == str(active_lead.id)
        print("PASS: temporary Field aliases (owner_name/owner_phone/existing_lead_id) match canonical values")

        # ---- 3b. Archived-only leads -> lead_id null (deterministic) ----
        p2 = Property(id=_uuid.uuid4(), source="test", formatted_address="Archived-only home")
        db.add(p2); await db.flush()
        db.add(Lead(id=_uuid.uuid4(), property_id=p2.id, assigned_user_id=rep.id, name="only archived",
                    status="archived", created_at=now))
        await db.commit()
        made["property2"] = p2.id
        office2 = (await office_get_property(str(p2.id), user=owner_u, db=db)).model_dump()
        assert office2["lead_id"] is None, "archived-only property must have lead_id = null"
        print("PASS: archived-only leads yield lead_id = null")

        # ---- 4. Canonical visit outcomes: all six valid, invalid rejected (Office + Field schemas) ----
        for oc in VALID_VISIT_OUTCOMES:
            assert VisitIn(outcome=oc).outcome == oc
            assert MobileVisitIn(property_id=str(p.id), outcome=oc).outcome == oc
        assert set(VALID_VISIT_OUTCOMES) == {"no_answer", "not_interested", "interested", "callback", "appointment", "do_not_knock"}
        for bad in ("sold", "maybe", "", "DO_NOT_KNOCK"):
            try:
                VisitIn(outcome=bad); assert False, f"Office accepted invalid outcome {bad!r}"
            except ValidationError:
                pass
            try:
                MobileVisitIn(property_id=str(p.id), outcome=bad); assert False, f"Field accepted invalid outcome {bad!r}"
            except ValidationError:
                pass
        print("PASS: all 6 canonical outcomes validate; unsupported outcomes rejected on both schemas")

        # ---- 5. Authorization: authorized rep OK; unauthorized rep 403 on BOTH routes ----
        assert (await mobile_get_property(str(p.id), user=rep_u, db=db))["id"] == str(p.id)
        assert (await office_get_property(str(p.id), user=rep_u, db=db)).id == str(p.id)
        for route, label in ((mobile_get_property, "mobile"), (office_get_property, "office")):
            try:
                await route(str(p.id), user=rep_other_u, db=db)
                assert False, f"unauthorized rep reached the property via the {label} route (IDOR)"
            except HTTPException as e:
                assert e.status_code == 403, f"{label}: expected 403, got {e.status_code}"
        print("PASS: authorized rep allowed; unauthorized direct-UUID access blocked (403) on mobile AND office")

    finally:
        await db.rollback()
        # explicit teardown (dependency order): leads -> properties (cascade contacts/visits/join) ->
        # section -> territory -> users
        for lid in made.get("leads", []):
            await db.execute(delete(Lead).where(Lead.id == lid))
        await db.execute(delete(Lead).where(Lead.property_id == made.get("property2")))
        for pid in (made.get("property"), made.get("property2")):
            if pid:
                await db.execute(delete(Property).where(Property.id == pid))
        if made.get("section"):
            await db.execute(delete(CanvassSection).where(CanvassSection.id == made["section"]))
        if made.get("territory"):
            await db.execute(delete(Territory).where(Territory.id == made["territory"]))
        from models import User
        for uid in made.get("users", []):
            await db.execute(delete(User).where(User.id == uid))
        await db.commit()
        await db.close()


def test_property_parity_outcomes_and_authz():
    run_isolated(_run)

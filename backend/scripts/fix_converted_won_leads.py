"""One-off, idempotent data correction (2026-06, approved by the owner).

1) The Converted->Won migration also marked leads Won that only had a customer record (Converted used to be set when a
   customer was created). The 122 identified leads (frozen list in scripts/data/converted_won_correction_ids.txt, all
   test data, none with an accepted proposal) go back to Contacted. Leads with an accepted proposal stay Won.
2) Won/Lost leads with outstanding (open) sales follow-ups get them cancelled with "Lead marked Won/Lost".
Nothing is deleted; every change is written to the audit history. Running it again changes nothing.

Usage: cd /app/backend && python -m scripts.fix_converted_won_leads [--dry-run]
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from sqlalchemy import select, exists  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession  # noqa: E402

from models import Lead, Quote, LeadFollowUp  # noqa: E402
from core import log_action  # noqa: E402
from services import follow_ups as fu  # noqa: E402

IDS_FILE = Path(__file__).resolve().parent / "data" / "converted_won_correction_ids.txt"
REASON = "Status correction: migrated Converted->Won without an accepted proposal (customer record only)"


async def run(dry: bool) -> dict:
    ids = [uuid.UUID(x.strip()) for x in IDS_FILE.read_text().splitlines() if x.strip()]
    eng = create_async_engine(os.environ["DATABASE_URL"])
    S = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    out = {"listed": len(ids), "corrected": 0, "already_corrected_or_changed": 0, "skipped_has_accepted_proposal": 0,
           "follow_up_leads_swept": 0, "follow_ups_cancelled": 0}
    try:
        async with S() as db:
            for lid in ids:
                lead = await db.get(Lead, lid)
                if not lead or lead.status != "won":
                    out["already_corrected_or_changed"] += 1
                    continue
                accepted = (await db.execute(select(exists().where(Quote.lead_id == lid, Quote.status == "accepted")))).scalar()
                if accepted:
                    out["skipped_has_accepted_proposal"] += 1
                    continue
                out["corrected"] += 1
                if not dry:
                    lead.status = "contacted"
                    await db.commit()
                    await log_action(db, user=None, action="lead.status_correction", entity_type="lead", entity_id=lead.id,
                                     detail={"from": "won", "to": "contacted", "reason": REASON, "script": "fix_converted_won_leads"})
            closed = (await db.execute(select(Lead).where(Lead.status.in_(fu.CLOSED_LEAD_STATUSES), exists().where(
                LeadFollowUp.lead_id == Lead.id, LeadFollowUp.status == "open")))).scalars().all()
            for lead in closed:
                out["follow_up_leads_swept"] += 1
                if dry:
                    out["follow_ups_cancelled"] += len((await db.execute(select(LeadFollowUp.id).where(LeadFollowUp.lead_id == lead.id, LeadFollowUp.status == "open"))).all())
                    continue
                cancelled = await fu.cancel_on_close(db, lead, None, "system")
                await db.commit()
                out["follow_ups_cancelled"] += len(cancelled)
                await fu.log_auto_cancel(db, lead, cancelled, None)
    finally:
        await eng.dispose()
    return out


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    print(("DRY RUN " if dry else "") + str(asyncio.run(run(dry))))

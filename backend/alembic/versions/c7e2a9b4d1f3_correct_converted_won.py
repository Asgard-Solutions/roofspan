"""Correct leads wrongly set to Won by the ORIGINAL b1f0c2d3e4a5 (every Converted -> Won).

The corrected b1f0c2d3e4a5 never re-runs on installs already at that revision, so this repairs them.
A Won lead is reset to Contacted only with positive evidence that the old migration made it Won:
a legacy conversion (customer.from_lead audit), no accepted proposal (now or ever), no job for the
lead's customer/quotes, no audited manual status edit since the conversion, and no earlier correction.
Anything else that is Won without an accepted proposal is left unchanged and flagged for review.
Every change/flag is written to audit_logs; nothing is deleted. Re-running makes no further changes.

Revision ID: c7e2a9b4d1f3
Revises: b1f0c2d3e4a5
"""
import json
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "c7e2a9b4d1f3"
down_revision = "b1f0c2d3e4a5"
branch_labels = None
depends_on = None

SYSTEM_EMAIL = "system@roofspan"

SUSPECTS = """
SELECT l.id, l.customer_id,
  (SELECT max(a.timestamp) FROM audit_logs a
    WHERE a.action = 'customer.from_lead' AND a.detail->>'lead_id' = l.id::text) AS converted_at,
  EXISTS (SELECT 1 FROM audit_logs a WHERE a.entity_type = 'lead' AND a.entity_id = l.id::text
    AND a.action = 'lead.status_correction') AS corrected_before,
  EXISTS (SELECT 1 FROM audit_logs a WHERE a.entity_type = 'lead' AND a.entity_id = l.id::text
    AND a.action = 'lead.status_review_needed' AND a.detail->>'migration' = :rev) AS flagged_before,
  EXISTS (SELECT 1 FROM jobs j WHERE (l.customer_id IS NOT NULL AND j.customer_id = l.customer_id)
    OR j.quote_id IN (SELECT q.id FROM quotes q WHERE q.lead_id = l.id)) AS has_job
FROM leads l
WHERE l.status = 'won'
  AND NOT EXISTS (SELECT 1 FROM quotes q WHERE q.lead_id = l.id
                  AND (q.status = 'accepted' OR q.accepted_at IS NOT NULL))
ORDER BY l.id
"""

# Audited manual status edits after the conversion. Office records [old, new]; Field records only the
# changed field names, so any Field status edit counts. Office edits back to 'converted' cannot make Won.
MANUAL_EDIT = """
SELECT EXISTS (SELECT 1 FROM audit_logs a
  WHERE a.entity_type = 'lead' AND a.entity_id = :lid AND a.action = 'lead.update' AND a.timestamp >= :since
    AND ((a.detail ? 'status' AND coalesce(a.detail->'status'->>1, '') <> 'converted')
         OR (jsonb_typeof(a.detail->'fields') = 'array' AND a.detail->'fields' ? 'status')))
"""


def _audit(conn, lead_id: str, action: str, detail: dict) -> None:
    conn.execute(
        sa.text("INSERT INTO audit_logs (id, timestamp, user_email, action, entity_type, entity_id, detail) "
                "VALUES (:id, :ts, :email, :action, 'lead', :lid, CAST(:detail AS jsonb))"),
        {"id": str(uuid.uuid4()), "ts": datetime.now(timezone.utc), "email": SYSTEM_EMAIL,
         "action": action, "lid": lead_id, "detail": json.dumps(detail)},
    )


def upgrade() -> None:
    conn = op.get_bind()
    corrected = flagged = 0
    for r in conn.execute(sa.text(SUSPECTS), {"rev": revision}).mappings().all():
        lid = str(r["id"])
        reasons = []
        if r["customer_id"] is None or r["converted_at"] is None:
            reasons.append("no record of a legacy Converted (customer created from lead)")
        elif conn.execute(sa.text(MANUAL_EDIT), {"lid": lid, "since": r["converted_at"]}).scalar():
            reasons.append("status was edited by a user after conversion")
        if r["has_job"]:
            reasons.append("a job exists for this lead's customer or proposals")
        if r["corrected_before"]:
            reasons.append("already corrected once and set to Won again")
        if not reasons:
            conn.execute(sa.text("UPDATE leads SET status = 'contacted' WHERE id = :lid AND status = 'won'"), {"lid": lid})
            _audit(conn, lid, "lead.status_correction", {
                "from": "won", "to": "contacted", "migration": revision,
                "reason": "Status correction: an earlier upgrade marked a Converted lead Won without an accepted proposal",
            })
            corrected += 1
        elif not r["flagged_before"]:
            _audit(conn, lid, "lead.status_review_needed", {
                "status": "won", "migration": revision, "reasons": reasons,
                "note": "Won without an accepted proposal; left unchanged for manual review",
            })
            flagged += 1
    print(f"[c7e2a9b4d1f3] Won->Contacted corrected: {corrected}; left unchanged for manual review: {flagged}")


def downgrade() -> None:
    pass  # data correction only; corrected leads stay Contacted (audit history records the change)

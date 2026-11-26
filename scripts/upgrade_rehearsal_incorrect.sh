#!/usr/bin/env bash
# Rehearsal for installations that ALREADY applied the original (incorrect) b1f0c2d3e4a5 migration
# (git f240635: every Converted -> Won). Runs on a COPY of the working database; the working DB is never modified.
# 1) clone, roll back to a9c8e7d6f5b4, restore legacy statuses, drop the preview-only one-off correction audit
# 2) apply the INCORRECT migration from git history  3) simulate legitimate post-upgrade activity
# 4) run the CURRENT release's `alembic upgrade head` (corrective c7e2a9b4d1f3)  5) re-run it (idempotency)
set -euo pipefail
cd /app/backend
set -a; . ./.env; set +a
SRC="$(echo "$DATABASE_URL" | sed 's/+asyncpg//')"
BASE="${SRC%/*}"
COPY=rs_upgrade_rehearsal_b
psql "$BASE/postgres" -qc "DROP DATABASE IF EXISTS $COPY" -c "CREATE DATABASE $COPY"
pg_dump --no-owner "$SRC" | psql -q "$BASE/$COPY" > /dev/null
export DATABASE_URL="${DATABASE_URL%/*}/$COPY"
C="$BASE/$COPY"
q() { psql "$C" -Atc "$1"; }
NOACC="NOT EXISTS (SELECT 1 FROM quotes q WHERE q.lead_id=l.id AND (q.status='accepted' OR q.accepted_at IS NOT NULL))"
alembic downgrade a9c8e7d6f5b4 > /dev/null 2>&1
psql "$C" -qc "UPDATE leads SET status='converted' WHERE status IN ('won','contacted') AND customer_id IS NOT NULL" \
          -c "UPDATE leads SET status='working' WHERE id IN (SELECT id FROM leads WHERE status='new' ORDER BY created_at LIMIT 5)" \
          -c "UPDATE leads SET status='interested' WHERE id IN (SELECT id FROM leads WHERE status='new' ORDER BY created_at LIMIT 3)" \
          -c "DELETE FROM audit_logs WHERE action IN ('lead.status_correction','lead.status_review_needed')"
LEGIT=$(q "SELECT count(*) FROM leads l WHERE status='converted' AND NOT ($NOACC)")
TMP=$(mktemp -d); cp -r alembic "$TMP/alembic"; rm -rf "$TMP/alembic/versions/__pycache__" "$TMP/alembic/versions/c7e2a9b4d1f3_correct_converted_won.py"
git -C /app show f240635:backend/alembic/versions/b1f0c2d3e4a5_lead_follow_ups.py > "$TMP/alembic/versions/b1f0c2d3e4a5_lead_follow_ups.py"
sed "s#^script_location = alembic#script_location = $TMP/alembic#" alembic.ini > "$TMP/alembic.ini"
alembic -c "$TMP/alembic.ini" upgrade head > /dev/null 2>&1
echo "== after INCORRECT migration: $(q "SELECT string_agg(status||':'||c, ',' ORDER BY status) FROM (SELECT status, count(*) c FROM leads GROUP BY 1) x")  (legit Won with accepted proposal: $LEGIT)"
echo "   wrongly Won (no accepted proposal): $(q "SELECT count(*) FROM leads l WHERE status='won' AND $NOACC")"
# 3) legitimate post-upgrade activity on wrongly-Won leads:
#    L1 Office user re-sets Won (audited [old,new]); L2 Field user edits status (audited 'fields');
#    L3 Office user moves one to Qualified (no longer Won -> must not be touched).
read L1 L2 L3 < <(q "SELECT string_agg(id::text,' ') FROM (SELECT id FROM leads l WHERE status='won' AND $NOACC ORDER BY id LIMIT 3) x")
psql "$C" -q -c "INSERT INTO audit_logs (id,timestamp,user_email,action,entity_type,entity_id,detail) VALUES
  ('$(python3 -c 'import uuid;print(uuid.uuid4())')', now(), 'owner@rehearsal', 'lead.update', 'lead', '$L1', '{\"fields\":[\"status\"],\"status\":[\"contacted\",\"won\"]}'),
  ('$(python3 -c 'import uuid;print(uuid.uuid4())')', now(), 'rep@rehearsal',   'lead.update', 'lead', '$L2', '{\"via\":\"mobile\",\"fields\":[\"status\"]}'),
  ('$(python3 -c 'import uuid;print(uuid.uuid4())')', now(), 'owner@rehearsal', 'lead.update', 'lead', '$L3', '{\"fields\":[\"status\"],\"status\":[\"won\",\"qualified\"]}')" \
  -c "UPDATE leads SET status='qualified' WHERE id='$L3'"
SNAP="SELECT (SELECT count(*) FROM leads)||'|'||(SELECT count(*) FROM customers)||'|'||(SELECT count(*) FROM quotes)||'|'||(SELECT count(*) FROM jobs)||'|'||(SELECT count(*) FROM lead_follow_ups)"
BEFORE=$(q "$SNAP"); AUD0=$(q "SELECT count(*) FROM audit_logs")
echo "== current release upgrade: $(alembic upgrade head 2>&1 | grep -E 'c7e2a9b4d1f3\]' || echo 'no corrective output')"
echo "   head=$(q "SELECT version_num FROM alembic_version")  statuses: $(q "SELECT string_agg(status||':'||c, ',' ORDER BY status) FROM (SELECT status, count(*) c FROM leads GROUP BY 1) x")"
echo "   correction audit rows: $(q "SELECT count(*) FROM audit_logs WHERE action='lead.status_correction' AND detail->>'migration'='c7e2a9b4d1f3'")  review flags: $(q "SELECT count(*) FROM audit_logs WHERE action='lead.status_review_needed'")"
echo "   still Won without accepted proposal: $(q "SELECT count(*) FROM leads l WHERE status='won' AND $NOACC")"
echo "   legit Won (accepted proposal) still Won: $(q "SELECT count(*) FROM leads l WHERE status='won' AND NOT ($NOACC)") of $LEGIT"
echo "   L1 (Office re-set Won): $(q "SELECT status FROM leads WHERE id='$L1'")  flagged: $(q "SELECT count(*) FROM audit_logs WHERE action='lead.status_review_needed' AND entity_id='$L1'")"
echo "   L2 (Field status edit): $(q "SELECT status FROM leads WHERE id='$L2'")  flagged: $(q "SELECT count(*) FROM audit_logs WHERE action='lead.status_review_needed' AND entity_id='$L2'")"
echo "   L3 (moved to Qualified): $(q "SELECT status FROM leads WHERE id='$L3'")"
echo "   review reasons: $(q "SELECT string_agg(DISTINCT r, ' / ') FROM audit_logs a, jsonb_array_elements_text(a.detail->'reasons') r WHERE action='lead.status_review_needed'")"
echo "   rows leads|customers|quotes|jobs|follow-ups before=$BEFORE after=$(q "$SNAP")  audit rows added: $(( $(q "SELECT count(*) FROM audit_logs") - AUD0 ))"
# 5) re-run the corrective migration
alembic downgrade b1f0c2d3e4a5 > /dev/null 2>&1
echo "== re-run: $(alembic upgrade head 2>&1 | grep -E 'c7e2a9b4d1f3\]' || echo 'no corrective output')"
psql "$BASE/postgres" -qc "DROP DATABASE $COPY"
rm -rf "$TMP"

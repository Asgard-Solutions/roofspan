#!/usr/bin/env bash
# Rehearsal for installations that ALREADY applied the original (incorrect) b1f0c2d3e4a5 migration
# (git f240635: every Converted -> Won). Runs on a COPY of the working database; the working DB is never modified.
# 1) clone, roll back to a9c8e7d6f5b4, restore legacy statuses  2) apply the INCORRECT migration from git history
# 3) simulate legitimate post-upgrade activity  4) run the CURRENT code's `alembic upgrade head`
# 5) evaluate (read-only) the proposed corrective rule.
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
alembic downgrade a9c8e7d6f5b4 > /dev/null 2>&1
psql "$C" -qc "UPDATE leads SET status='converted' WHERE status IN ('won','contacted') AND customer_id IS NOT NULL" \
          -c "UPDATE leads SET status='working' WHERE id IN (SELECT id FROM leads WHERE status='new' ORDER BY created_at LIMIT 5)" \
          -c "UPDATE leads SET status='interested' WHERE id IN (SELECT id FROM leads WHERE status='new' ORDER BY created_at LIMIT 3)"
CONV=$(psql "$C" -Atc "SELECT count(*) FROM leads WHERE status='converted'")
CONV_ACC=$(psql "$C" -Atc "SELECT count(*) FROM leads l WHERE status='converted' AND EXISTS (SELECT 1 FROM quotes q WHERE q.lead_id=l.id AND q.status='accepted')")
# 2) the incorrect migration, exactly as it shipped in f240635
TMP=$(mktemp -d); cp -r alembic "$TMP/alembic"; rm -rf "$TMP/alembic/versions/__pycache__"
git -C /app show f240635:backend/alembic/versions/b1f0c2d3e4a5_lead_follow_ups.py > "$TMP/alembic/versions/b1f0c2d3e4a5_lead_follow_ups.py"
sed "s#^script_location = alembic#script_location = $TMP/alembic#" alembic.ini > "$TMP/alembic.ini"
alembic -c "$TMP/alembic.ini" upgrade head 2>&1 | grep -E "Running upgrade" || true
echo "== after INCORRECT migration: $(psql "$C" -Atc "SELECT string_agg(status||':'||c, ',' ORDER BY status) FROM (SELECT status, count(*) c FROM leads GROUP BY 1) x")"
echo "   (legacy converted=$CONV, of which with accepted proposal=$CONV_ACC)"
# 3) legitimate post-upgrade activity on wrongly-Won leads (no accepted proposal):
#    L1: Office user sets Won->Contacted->Won (audited with status values);  L2: Field user edits status (audited 'fields');
#    L3: Office user moves a wrongly-Won lead to Qualified (must NOT be touched: it is no longer Won).
read L1 L2 L3 < <(psql "$C" -At -F' ' -c "SELECT string_agg(id::text,' ') FROM (SELECT id FROM leads l WHERE status='won' AND NOT EXISTS (SELECT 1 FROM quotes q WHERE q.lead_id=l.id AND q.status='accepted') ORDER BY id LIMIT 3) x")
psql "$C" -q -c "INSERT INTO audit_logs (id,timestamp,user_email,action,entity_type,entity_id,detail) VALUES
  (gen_random_uuid(), now(), 'owner@rehearsal', 'lead.update', 'lead', '$L1', '{\"fields\":[\"status\"],\"status\":[\"contacted\",\"won\"]}'),
  (gen_random_uuid(), now(), 'rep@rehearsal',   'lead.update', 'lead', '$L2', '{\"via\":\"mobile\",\"fields\":[\"status\"]}'),
  (gen_random_uuid(), now(), 'owner@rehearsal', 'lead.update', 'lead', '$L3', '{\"fields\":[\"status\"],\"status\":[\"won\",\"qualified\"]}')" \
  -c "UPDATE leads SET status='qualified' WHERE id='$L3'"
# 4) the current release's upgrade on this database
OUT=$(alembic upgrade head 2>&1 | grep -E "Running upgrade" || true)
echo "== current-code 'alembic upgrade head' ran: ${OUT:-nothing (already at head)}; head=$(psql "$C" -Atc "SELECT version_num FROM alembic_version")"
WRONG=$(psql "$C" -Atc "SELECT count(*) FROM leads l WHERE status='won' AND NOT EXISTS (SELECT 1 FROM quotes q WHERE q.lead_id=l.id AND q.status='accepted')")
echo "== still Won without an accepted proposal after current upgrade: $WRONG"
# 5) proposed corrective rule (evaluated read-only)
RULE="status='won' AND NOT EXISTS (SELECT 1 FROM quotes q WHERE q.lead_id=l.id AND q.status='accepted')
      AND NOT EXISTS (SELECT 1 FROM audit_logs a WHERE a.entity_type='lead' AND a.entity_id=l.id::text AND a.action='lead.update'
                      AND (a.detail->'status'->>1='won' OR a.detail->'fields' ? 'status'))"
echo "== proposed rule would set to Contacted: $(psql "$C" -Atc "SELECT count(*) FROM leads l WHERE $RULE")"
echo "== left Won for manual review (explicit user status edit, no accepted proposal): $(psql "$C" -Atc "SELECT count(*) FROM leads l WHERE status='won' AND NOT EXISTS (SELECT 1 FROM quotes q WHERE q.lead_id=l.id AND q.status='accepted') AND NOT ($RULE)")"
echo "== rule touches L1 (Office re-set Won): $(psql "$C" -Atc "SELECT count(*) FROM leads l WHERE id='$L1' AND $RULE")  L2 (Field status edit): $(psql "$C" -Atc "SELECT count(*) FROM leads l WHERE id='$L2' AND $RULE")  L3 (now Qualified): $(psql "$C" -Atc "SELECT count(*) FROM leads l WHERE id='$L3' AND $RULE")"
echo "== rule touches leads with accepted proposal: $(psql "$C" -Atc "SELECT count(*) FROM leads l WHERE $RULE AND EXISTS (SELECT 1 FROM quotes q WHERE q.lead_id=l.id AND q.status='accepted')")"
psql "$BASE/postgres" -qc "DROP DATABASE $COPY"
rm -rf "$TMP"

#!/usr/bin/env bash
# Upgrade rehearsal on a COPY of the working database (the working database is never modified).
# 1) clone -> 2) roll the copy back to the pre-redesign schema (e7f8a9b0c1d2) and put legacy lead statuses back
# 3) snapshot every table's row count + settings 4) alembic upgrade head 5) compare.
set -euo pipefail
cd /app/backend
set -a; . ./.env; set +a
SRC="$(echo "$DATABASE_URL" | sed 's/+asyncpg//')"
BASE="${SRC%/*}"
COPY=rs_upgrade_rehearsal
psql "$BASE/postgres" -qc "DROP DATABASE IF EXISTS $COPY" -c "CREATE DATABASE $COPY"
pg_dump --no-owner "$SRC" | psql -q "$BASE/$COPY" > /dev/null
export DATABASE_URL="${DATABASE_URL%/*}/$COPY"
C="$BASE/$COPY"
alembic downgrade e7f8a9b0c1d2 > /dev/null 2>&1
# legacy statuses as an old install would have them
psql "$C" -qc "UPDATE leads SET status='converted' WHERE status IN ('won','contacted') AND customer_id IS NOT NULL" \
          -c "UPDATE leads SET status='working' WHERE id IN (SELECT id FROM leads WHERE status='new' ORDER BY created_at LIMIT 5)" \
          -c "UPDATE leads SET status='interested' WHERE id IN (SELECT id FROM leads WHERE status='new' ORDER BY created_at LIMIT 3)"
snap() {
  psql "$C" -At -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' AND table_name NOT IN ('alembic_version') ORDER BY 1" |
    while read t; do echo "$t $(psql "$C" -Atc "SELECT count(*) FROM \"$t\"")"; done
}
snap > /app/memory/_upg_before.txt
psql "$C" -Atc "SELECT md5(string_agg(t::text, '|' ORDER BY t::text)) FROM (SELECT * FROM app_config) t"  > /app/memory/_upg_settings_before.txt; psql "$C" -Atc "SELECT md5(string_agg(t::text, '|' ORDER BY t::text)) FROM integration_settings t" >> /app/memory/_upg_settings_before.txt
psql "$C" -Atc "SELECT md5(string_agg(id::text||coalesce(assigned_to,'')||coalesce(assigned_user_id::text,''), '|' ORDER BY id)) FROM jobs" > /app/memory/_upg_jobs_before.txt
EXP_WON=$(psql "$C" -Atc "SELECT count(*) FROM leads l WHERE status='converted' AND EXISTS (SELECT 1 FROM quotes q WHERE q.lead_id=l.id AND q.status='accepted')")
EXP_CONT=$(psql "$C" -Atc "SELECT count(*) FROM leads WHERE status IN ('converted','working')")
EXP_CONT=$((EXP_CONT - EXP_WON))
alembic upgrade head 2>&1 | grep -E "Running upgrade|c7e2a9b4d1f3\]" || true
snap > /app/memory/_upg_after.txt
echo "== row-count differences (before -> after) =="
diff /app/memory/_upg_before.txt /app/memory/_upg_after.txt || true
echo "== settings unchanged: $( [ "$(cat /app/memory/_upg_settings_before.txt)" = "$(psql "$C" -Atc "SELECT md5(string_agg(t::text, '|' ORDER BY t::text)) FROM (SELECT * FROM app_config) t"; psql "$C" -Atc "SELECT md5(string_agg(t::text, '|' ORDER BY t::text)) FROM integration_settings t")" ] && echo yes || echo NO)"
echo "== job assignments unchanged: $( [ "$(cat /app/memory/_upg_jobs_before.txt)" = "$(psql "$C" -Atc "SELECT md5(string_agg(id::text||coalesce(assigned_to,'')||coalesce(assigned_user_id::text,''), '|' ORDER BY id)) FROM jobs")" ] && echo yes || echo NO)"
echo "== statuses after: $(psql "$C" -Atc "SELECT string_agg(status||':'||c, ',' ORDER BY status) FROM (SELECT status, count(*) c FROM leads GROUP BY 1) x")"
echo "== expected won=$EXP_WON contacted(from converted+working)=$EXP_CONT; won without accepted proposal: $(psql "$C" -Atc "SELECT count(*) FROM leads l WHERE status='won' AND NOT EXISTS (SELECT 1 FROM quotes q WHERE q.lead_id=l.id AND q.status='accepted')")"
echo "== legacy statuses left: $(psql "$C" -Atc "SELECT count(*) FROM leads WHERE status IN ('converted','working','interested')")"
echo "== crews created from free-text: $(psql "$C" -Atc "SELECT count(*) FROM crews"); jobs with text crew but no crew_id: $(psql "$C" -Atc "SELECT count(*) FROM jobs WHERE coalesce(trim(assigned_to),'')<>'' AND crew_id IS NULL")"
echo "== inspections all completed: $(psql "$C" -Atc "SELECT string_agg(status||':'||c, ',') FROM (SELECT status, count(*) c FROM inspections GROUP BY 1) x")"
echo "== head: $(psql "$C" -Atc "SELECT version_num FROM alembic_version")"
psql "$BASE/postgres" -qc "DROP DATABASE $COPY"
rm -f /app/memory/_upg_*.txt

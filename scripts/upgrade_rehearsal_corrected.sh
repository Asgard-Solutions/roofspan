#!/usr/bin/env bash
# Rehearsal for an already-corrected database (the preview working DB, corrected by the approved one-off script):
# copy at b1f0c2d3e4a5 -> current head. Expect zero corrections, zero review flags, no row changes.
set -euo pipefail
cd /app/backend
set -a; . ./.env; set +a
SRC="$(echo "$DATABASE_URL" | sed 's/+asyncpg//')"; BASE="${SRC%/*}"; COPY=rs_upgrade_rehearsal_c
psql "$BASE/postgres" -qc "DROP DATABASE IF EXISTS $COPY" -c "CREATE DATABASE $COPY"
pg_dump --no-owner "$SRC" | psql -q "$BASE/$COPY" > /dev/null
export DATABASE_URL="${DATABASE_URL%/*}/$COPY"; C="$BASE/$COPY"
q() { psql "$C" -Atc "$1"; }
SNAP="SELECT (SELECT string_agg(status||':'||c, ',' ORDER BY status) FROM (SELECT status, count(*) c FROM leads GROUP BY 1) x)||'|'||(SELECT count(*) FROM audit_logs)||'|'||(SELECT count(*) FROM customers)||'|'||(SELECT count(*) FROM jobs)"
[ "$(q "SELECT version_num FROM alembic_version")" = "c7e2a9b4d1f3" ] && alembic downgrade b1f0c2d3e4a5 > /dev/null 2>&1
echo "== start revision: $(q "SELECT version_num FROM alembic_version")  before: $(q "$SNAP")"
echo "== upgrade: $(alembic upgrade head 2>&1 | grep -E 'c7e2a9b4d1f3\]' || echo 'no corrective output')"
echo "== head: $(q "SELECT version_num FROM alembic_version")  after: $(q "$SNAP")"
psql "$BASE/postgres" -qc "DROP DATABASE $COPY"

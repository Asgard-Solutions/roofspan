#!/usr/bin/env bash
# RoofSpan restore-verification drill (operational safety tool — NOT product UI).
# Restores a backup into an ISOLATED test database, runs integrity checks, prints PASS/FAIL,
# then drops the test database. It NEVER touches the production database.
#
# Usage:
#   bash backend/scripts/restore_drill.sh                # uses the latest backup
#   bash backend/scripts/restore_drill.sh /path/to.dump  # uses a specific backup
set -uo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DB_URL="$(grep -E '^DATABASE_URL=' "$BACKEND_DIR/.env" | cut -d= -f2- | tr -d '"')"

rest="${DB_URL#*://}"
creds="${rest%@*}"; hostpart="${rest#*@}"
DB_USER="${creds%%:*}"; DB_PASS="${creds#*:}"
hostport="${hostpart%%/*}"; DB_NAME="${hostpart##*/}"
DB_HOST="${hostport%%:*}"; DB_PORT="${hostport#*:}"; [ "$DB_PORT" = "$DB_HOST" ] && DB_PORT=5432

BACKUP_DIR="${ROOFSPAN_BACKUP_DIR:-/data/db/roofspan_backups}"
DRILL_DB="roofspan_restore_drill"
export PGPASSWORD="$DB_PASS"
PSQL="psql -h $DB_HOST -p $DB_PORT -U $DB_USER -tAc"

# Safety: never operate on the production database.
if [ "$DRILL_DB" = "$DB_NAME" ]; then echo "FAIL: drill DB name equals production DB name"; exit 1; fi

BACKUP="${1:-$(ls -1t "$BACKUP_DIR"/roofspan_*.dump 2>/dev/null | head -1)}"
if [ -z "$BACKUP" ] || [ ! -f "$BACKUP" ]; then echo "FAIL: no backup file found in $BACKUP_DIR"; exit 1; fi
echo "Restore drill using backup: $BACKUP"

$PSQL "SELECT 1" -d postgres >/dev/null 2>&1 || { echo "FAIL: cannot reach PostgreSQL server"; exit 1; }
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS $DRILL_DB;" >/dev/null 2>&1
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -c "CREATE DATABASE $DRILL_DB;" >/dev/null 2>&1 || { echo "FAIL: could not create isolated drill DB"; exit 1; }

# pg_restore may emit non-fatal warnings; capture but don't abort solely on them.
pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DRILL_DB" "$BACKUP" > /tmp/restore_drill.log 2>&1 || true

TABLES=$($PSQL "SELECT count(*) FROM pg_tables WHERE schemaname='public';" -d "$DRILL_DB" 2>/dev/null || echo 0)
USERS=$($PSQL "SELECT count(*) FROM users;" -d "$DRILL_DB" 2>/dev/null || echo 0)
ALEMBIC=$($PSQL "SELECT version_num FROM alembic_version;" -d "$DRILL_DB" 2>/dev/null || echo "")
MISSING=$($PSQL "SELECT COALESCE(string_agg(t,','),'') FROM (VALUES ('users'),('customers'),('jobs'),('materials'),('purchase_orders'),('invoices'),('alembic_version')) v(t) WHERE to_regclass('public.'||t) IS NULL;" -d "$DRILL_DB" 2>/dev/null || echo "query-error")

echo "  tables=$TABLES  users=$USERS  alembic=$ALEMBIC  missing_key_tables='${MISSING}'"

STATUS="PASS"
[ "$TABLES" -ge 29 ] 2>/dev/null || STATUS="FAIL"
[ "$USERS" -ge 1 ] 2>/dev/null || STATUS="FAIL"
[ -n "$ALEMBIC" ] || STATUS="FAIL"
[ -z "$MISSING" ] || STATUS="FAIL"

# Cleanup the isolated drill DB (leave production untouched).
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS $DRILL_DB;" >/dev/null 2>&1

if [ "$STATUS" = "PASS" ]; then
  echo "RESTORE DRILL: PASS — backup is restorable and readable."
  exit 0
else
  echo "RESTORE DRILL: FAILURE — see /tmp/restore_drill.log"
  exit 1
fi

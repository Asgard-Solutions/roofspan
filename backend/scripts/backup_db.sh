#!/usr/bin/env bash
# RoofSpan PostgreSQL backup: pg_dump custom format -> persistent volume, timestamped,
# atomic (write .partial then mv), retention-pruned, logged, with failure detection.
# Safe to run manually or from the nightly platform cron (/api/cron/backup).
set -uo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DB_URL="$(grep -E '^DATABASE_URL=' "$BACKEND_DIR/.env" | cut -d= -f2- | tr -d '"')"

rest="${DB_URL#*://}"
creds="${rest%@*}"; hostpart="${rest#*@}"
DB_USER="${creds%%:*}"; DB_PASS="${creds#*:}"
hostport="${hostpart%%/*}"; DB_NAME="${hostpart##*/}"
DB_HOST="${hostport%%:*}"; DB_PORT="${hostport#*:}"; [ "$DB_PORT" = "$DB_HOST" ] && DB_PORT=5432

BACKUP_DIR="${ROOFSPAN_BACKUP_DIR:-/data/db/roofspan_backups}"
RETENTION="${ROOFSPAN_BACKUP_RETENTION:-14}"
mkdir -p "$BACKUP_DIR"
LOG="$BACKUP_DIR/backup.log"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$BACKUP_DIR/roofspan_${TS}.dump"
TMP="$OUT.partial"

log() { echo "$(date -u +%FT%TZ) $1" | tee -a "$LOG"; }
export PGPASSWORD="$DB_PASS"

log "START backup db=$DB_NAME host=$DB_HOST:$DB_PORT -> $OUT"
if pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -Fc -f "$TMP" 2>>"$LOG"; then
  mv "$TMP" "$OUT"
  SIZE="$(du -h "$OUT" | cut -f1)"
  log "SUCCESS $OUT ($SIZE)"
  # Retention: keep the newest $RETENTION successful dumps, prune older ones.
  ls -1t "$BACKUP_DIR"/roofspan_*.dump 2>/dev/null | tail -n +"$((RETENTION + 1))" | while read -r f; do
    rm -f "$f" && log "PRUNED $f"
  done
  echo "OK $TS $OUT" > "$BACKUP_DIR/LAST_BACKUP_STATUS"
  exit 0
else
  rc=$?
  rm -f "$TMP"   # never leave a corrupt partial; existing good backups are untouched
  log "FAILURE pg_dump exited rc=$rc — existing backups preserved, no overwrite"
  echo "FAIL $TS rc=$rc" > "$BACKUP_DIR/LAST_BACKUP_STATUS"
  exit 1
fi

#!/usr/bin/env bash
# One-time PostgreSQL bootstrap for a fresh RoofSpan install.
# Creates the application role (with CREATEDB) using the credentials from backend/.env.
# The database itself is created automatically by the backend at startup (see migrations_runner.ensure_database),
# so this script only needs to guarantee the ROLE exists (which requires a superuser).
#
# Usage (run once as a user that can sudo to the postgres superuser):
#   bash /app/backend/scripts/bootstrap_postgres.sh
set -euo pipefail

ENV_FILE="$(dirname "$0")/../.env"
DB_URL="$(grep -E '^DATABASE_URL=' "$ENV_FILE" | cut -d= -f2- | tr -d '"')"

# postgresql+asyncpg://USER:PASS@HOST:PORT/DBNAME
USER_PASS="${DB_URL#*://}"; USER_PASS="${USER_PASS%@*}"
ROLE="${USER_PASS%%:*}"
PWD="${USER_PASS#*:}"

echo "Ensuring PostgreSQL role '${ROLE}' exists (with CREATEDB)..."
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${ROLE}') THEN
    CREATE ROLE ${ROLE} LOGIN PASSWORD '${PWD}' CREATEDB;
  ELSE
    ALTER ROLE ${ROLE} WITH LOGIN PASSWORD '${PWD}' CREATEDB;
  END IF;
END
\$\$;
SQL

echo "Done. Start the backend; it will auto-create the database and run migrations."

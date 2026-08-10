#!/usr/bin/env bash
# Repeatable REAL-Valkey relay integration run (development/integration only — NEVER production).
# Requires Docker; if Docker is unavailable, run the suite against any reachable Valkey/Redis by
# exporting RELAY_VALKEY_URL yourself, e.g.:
#     redis-server --port 6390 &                         # or: valkey-server --port 6390 &
#     RELAY_VALKEY_URL=redis://127.0.0.1:6390 pytest -m integration backend/tests/integration
#
# This script uses the Docker Compose Valkey container and runs the integration suite (which launches
# its own two real relay processes on the host against that Valkey).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE="$HERE/docker-compose.yml"
export RELAY_VALKEY_URL="${RELAY_VALKEY_URL:-redis://127.0.0.1:6390}"

echo "==> starting Valkey via docker compose"
docker compose -f "$COMPOSE" up -d valkey

echo "==> waiting for Valkey"
for i in $(seq 1 30); do
  if docker compose -f "$COMPOSE" exec -T valkey valkey-cli ping >/dev/null 2>&1; then break; fi
  sleep 1
done

echo "==> running integration suite (real Valkey Pub/Sub + Lua + TTL + two relay processes)"
set +e
pytest -m integration -q "$HERE/../../../backend/tests/integration"
RC=$?
set -e

echo "==> tearing down"
docker compose -f "$COMPOSE" down -v
exit $RC

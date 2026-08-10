#!/usr/bin/env bash
# Control Plane container entrypoint: migrate (single runner via Postgres advisory lock) then serve.
set -euo pipefail

# Build CONTROL_PLANE_DATABASE_URL from the RDS master secret if not explicitly provided.
python - <<'PY'
import json, os
sec = os.environ.get("RDS_MASTER_SECRET")
if sec and not os.environ.get("CONTROL_PLANE_DATABASE_URL"):
    d = json.loads(sec)
    host = os.environ.get("RDS_HOST", d.get("host", ""))
    db = os.environ.get("RDS_DB", "roofspan_control_plane")
    url = f"postgresql+asyncpg://{d['username']}:{d['password']}@{host}:5432/{db}"
    with open("/tmp/cp_db_url", "w") as f:
        f.write(url)
PY
if [ -f /tmp/cp_db_url ]; then export CONTROL_PLANE_DATABASE_URL="$(cat /tmp/cp_db_url)"; rm -f /tmp/cp_db_url; fi

# Single-runner migration: take a session advisory lock so concurrent ECS tasks never race Alembic.
python - <<'PY'
import asyncio, os, subprocess, asyncpg
url = os.environ["CONTROL_PLANE_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
LOCK = 0x524F4F46  # "ROOF"
async def main():
    conn = await asyncpg.connect(url)
    try:
        await conn.execute("SELECT pg_advisory_lock($1)", LOCK)
        subprocess.check_call(["alembic", "-c", "control_plane/alembic.ini", "upgrade", "head"])
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", LOCK)
        await conn.close()
asyncio.run(main())
PY

exec uvicorn cp_app:app --host 0.0.0.0 --port 8080 --workers 2

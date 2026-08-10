# Relay ↔ Valkey local integration harness (DEV / INTEGRATION ONLY)

Exercises the **real** multi-node Secure Relay path against a **real** Valkey/Redis server:
`ValkeyRegistry` (atomic Lua ownership), `ValkeyTransport` (real Pub/Sub), TTL liveness, heartbeat
re-claim, reconnect after a Valkey bounce, and a genuine **two-process** cross-node request/response.
The in-process fake bus is **not** used here.

> ⚠️ Local Valkey/Redis here runs **without TLS**. This validates protocol / Pub/Sub / Lua / TTL /
> reconnect only. **Real AWS ElastiCache Valkey TLS connectivity remains HUMAN REQUIRED** at deploy time.
> No production credentials belong in this harness — local/test values only.

## What it launches
- `docker-compose.yml` — one Valkey (`valkey/valkey:8.0`) + two relay containers (`node-a`, `node-b`)
  built from `infra/docker/relay/Dockerfile`. Ports `6390` (Valkey), `9101`/`9102` (relay A/B).
- The pytest suite (`backend/tests/integration/test_relay_valkey.py`) can run against the Compose
  Valkey **or** manage its own local `valkey-server`/`redis-server` — it also launches its own two
  real relay processes for the end-to-end cross-node test.

## Run it

### Option A — Docker (recommended, closest to prod)
```bash
bash infra/dev/relay-valkey/run_integration.sh
# = docker compose up valkey  →  pytest -m integration  →  docker compose down -v
```

### Option B — no Docker (uses a local valkey-server/redis-server binary)
```bash
cd backend
RELAY_RUN_INTEGRATION=1 pytest -m integration -p no:xdist -o addopts="" tests/integration
```
The suite auto-starts a local server if `RELAY_VALKEY_URL` is unset and a binary is present; otherwise
point it at any reachable server:
```bash
RELAY_VALKEY_URL=redis://127.0.0.1:6390 RELAY_RUN_INTEGRATION=1 \
  pytest -m integration -p no:xdist -o addopts="" backend/tests/integration
```

## Gating / CI classification
- The suite is **skipped** in the fast unit run (it is marked `integration` and gated by
  `RELAY_RUN_INTEGRATION=1`). Run it explicitly and **serially** (`-p no:xdist`) — it manages
  server processes and shared Valkey state, so it must not run under xdist parallelism.

## Coverage (all against real Valkey)
cross-node request/response · registration key + TTL · heartbeat extends TTL · stale expiry ·
atomic Lua ownership (newest-wins + owner-safe unregister/heartbeat) · duplicate/reconnect ·
node-death TTL cleanup + recovery · pending-request timeout cleanup · payload/envelope bound
(reject before publish) · malformed Pub/Sub survived · **Valkey restart reconnect recovery** ·
readiness reflects Valkey health (503 when down) · production startup fail-fast (real subprocess) ·
**two real relay processes** full cross-node E2E (Office tunnel → node A → Valkey → node B → Mobile).

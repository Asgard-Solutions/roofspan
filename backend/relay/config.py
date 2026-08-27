"""Centralized Secure Relay configuration + production fail-fast.

Single source of truth for relay limits, timeouts, node identity and registry/transport selection.
Do NOT scatter these values across relay modules — import from here.

Environments:
  RELAY_ENV = "dev" (default; memory registry ok, single-node) | "production" (Valkey required).

Node identity (RELAY_NODE_ID):
  * Production REQUIRES a unique per-task/per-replica node id. It is resolved in this order:
      1. RELAY_NODE_ID env (authoritative override; source="env")
      2. Railway replica id (RAILWAY_REPLICA_ID; source="railway")
      3. ECS Task metadata (ECS_CONTAINER_METADATA_URI_V4 -> TaskARN task id; source="ecs")
      4. dev/test process-stable uuid fallback (source="random")
  * A random fallback is NEVER acceptable in production — startup fails clearly if a unique
    identity cannot be established (see require_production_config).
"""
from __future__ import annotations

import os
import uuid

RELAY_ENV = os.environ.get("RELAY_ENV", "dev").strip().lower()

# Registry / transport selection.
RELAY_REGISTRY = os.environ.get("RELAY_REGISTRY", "memory").strip().lower()  # "memory" | "valkey"
RELAY_VALKEY_URL = os.environ.get("RELAY_VALKEY_URL", "").strip() or None

# Routing bounds & timing (seconds / bytes).
REQUEST_TIMEOUT = float(os.environ.get("RELAY_REQUEST_TIMEOUT", "30"))
MAX_JSON_BYTES = int(os.environ.get("RELAY_MAX_JSON_BYTES", str(2 * 1024 * 1024)))        # 2 MB JSON body
MAX_UPLOAD_BYTES = int(os.environ.get("RELAY_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))   # 20 MB file
# Cross-node Pub/Sub envelope ceiling. A 20MB binary base64-encodes to ~26.7MB; +JSON envelope
# overhead fits under 28MB (validated by tests/test_relay_multinode.py::test_max_upload_envelope_fits).
MAX_ENVELOPE_BYTES = int(os.environ.get("RELAY_MAX_ENVELOPE_BYTES", str(28 * 1024 * 1024)))

REGISTRY_TTL_SECONDS = int(os.environ.get("RELAY_REGISTRY_TTL", "45"))   # ownership key TTL
HEARTBEAT_INTERVAL = float(os.environ.get("RELAY_HEARTBEAT_INTERVAL", "15"))  # renew well within TTL


def _resolve_node_id() -> tuple[str, str]:
    explicit = os.environ.get("RELAY_NODE_ID", "").strip()
    if explicit:
        return explicit, "env"

    railway_replica = os.environ.get("RAILWAY_REPLICA_ID", "").strip()
    if railway_replica:
        return f"railway-{railway_replica}", "railway"

    meta = os.environ.get("ECS_CONTAINER_METADATA_URI_V4", "").strip()
    if meta:
        try:  # pragma: no cover - requires the live ECS metadata endpoint
            import json
            import urllib.request

            with urllib.request.urlopen(meta + "/task", timeout=2) as r:
                task = json.loads(r.read().decode())
            task_id = (task.get("TaskARN") or "").rsplit("/", 1)[-1]
            if task_id:
                return f"ecs-{task_id}", "ecs"
        except Exception:  # noqa: BLE001
            pass
    # Dev/test fallback — stable for the life of this process.
    return f"node-{uuid.uuid4().hex[:12]}", "random"


NODE_ID, NODE_ID_SOURCE = _resolve_node_id()


def require_production_config() -> None:
    """Fail CLEARLY at relay startup in production. Production must NOT silently run memory mode."""
    if RELAY_ENV != "production":
        return
    missing = []
    if RELAY_REGISTRY != "valkey":
        missing.append("RELAY_REGISTRY=valkey")
    if not RELAY_VALKEY_URL:
        missing.append("RELAY_VALKEY_URL")
    if NODE_ID_SOURCE == "random":
        missing.append(
            "RELAY_NODE_ID, RAILWAY_REPLICA_ID, or ECS task metadata for a unique per-task node id"
        )
    if missing:
        raise RuntimeError("RoofSpan Secure Relay production config missing: " + "; ".join(missing))

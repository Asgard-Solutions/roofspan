// Pure, storage-agnostic offline mutation queue + sync core.
// No Expo/React imports so it is unit-testable in Node against the live backend.
// CommonJS so it runs in both Metro (RN) and plain Node.

const STATES = { PENDING: "pending", SYNCED: "synced", FAILED: "failed", CONFLICT: "conflict" };

function uuidv4() {
  // RFC4122-ish v4; adequate for client-generated stable IDs / idempotency keys.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// Build a durable mutation. The client_id IS the Idempotency-Key and never changes on retry.
function makeMutation({ kind, method, path, body, ifMatch = null, label = "" }) {
  const id = uuidv4();
  return {
    client_id: id,
    idempotency_key: id,
    kind,
    method,
    path,
    body: body || {},
    ifMatch,
    label,
    state: STATES.PENDING,
    server_id: null,
    serverValue: null,
    error: null,
    attempts: 0,
    created_at: new Date().toISOString(),
  };
}

// send(mutation) -> Promise<{status, data}>. Throws on network failure (offline).
async function processMutation(m, send) {
  const attempts = (m.attempts || 0) + 1;
  try {
    const res = await send(m);
    const s = res.status;
    if (s === 200 || s === 201) {
      return { ...m, state: STATES.SYNCED, server_id: (res.data && res.data.id) || m.server_id, error: null, attempts };
    }
    if (s === 409) {
      const detail = res.data && res.data.detail;
      const msg = (detail && detail.message) || "Changed on server — needs your attention";
      const serverValue = (detail && detail.server) || null;
      return { ...m, state: STATES.CONFLICT, error: msg, serverValue, attempts };
    }
    if (s >= 400 && s < 500) {
      return { ...m, state: STATES.FAILED, error: `HTTP ${s}`, attempts };
    }
    // 5xx: transient, keep pending for later retry (same idempotency key).
    return { ...m, state: STATES.PENDING, error: `HTTP ${s}`, attempts };
  } catch (e) {
    // Network/offline: keep pending. Never mark synced, never delete.
    return { ...m, state: STATES.PENDING, error: "offline", attempts };
  }
}

// Process all not-yet-synced items in order. Retries reuse the SAME idempotency key.
async function processQueue(items, send) {
  const out = [];
  for (const m of items) {
    if (m.state === STATES.PENDING || m.state === STATES.FAILED) {
      out.push(await processMutation(m, send));
    } else {
      out.push(m);
    }
  }
  return out;
}

module.exports = { STATES, uuidv4, makeMutation, processMutation, processQueue };

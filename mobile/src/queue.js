// Pure, storage-agnostic offline mutation queue + sync core.
// No Expo/React imports so it is unit-testable in Node against the live backend.
// CommonJS so it runs in both Metro (RN) and plain Node.

const STATES = { PENDING: "pending", SYNCED: "synced", FAILED: "failed", CONFLICT: "conflict" };

// Formats the Office /api/mobile/photos endpoint accepts. Reject others locally instead of queuing
// an item the backend will 4xx.
const SUPPORTED_PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"];

function uuidv4() {
  // RFC4122-ish v4; adequate for client-generated stable IDs / idempotency keys.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// Build a durable mutation. The client_id IS the Idempotency-Key and never changes on retry.
// `photo` (uri/name/type) is persisted so it survives SQLite serialization + app restart + retry.
function makeMutation({ kind, method, path, body, ifMatch = null, label = "", scope = null, photo = null }) {
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
    scope,
    photo,
    state: STATES.PENDING,
    server_id: null,
    serverValue: null,
    error: null,
    errorCode: null,
    attempts: 0,
    created_at: new Date().toISOString(),
  };
}

// ---- Photo helpers (pure; safe to run in Node unit tests) ----
function isPhotoMutation(m) {
  return !!(m && (m.kind === "photo" || m.photo));
}

// Validate the durable photo metadata BEFORE any network attempt. Returns {ok} or {ok:false, code, message}.
function validatePhotoMeta(photo) {
  if (!photo || typeof photo !== "object" || !photo.uri || !photo.name || !photo.type) {
    return { ok: false, code: "photo_file_missing", message: "Photo file unavailable" };
  }
  if (!SUPPORTED_PHOTO_TYPES.includes(photo.type)) {
    return { ok: false, code: "photo_unsupported_type", message: "Unsupported photo type" };
  }
  return { ok: true };
}

// Decide how a mutation must be transported. A photo mutation NEVER falls through to JSON: if its
// metadata is invalid it produces a deterministic local failure the queue surfaces to the user.
function buildSendPlan(m) {
  if (isPhotoMutation(m)) {
    const v = validatePhotoMeta(m.photo);
    if (!v.ok) return { transport: "local_failure", status: 422, code: v.code, message: v.message };
    return { transport: "multipart" };
  }
  return { transport: "json" };
}

// Salesperson-facing label for a photo failure (no stack traces / low-level detail).
function photoErrorLabel(codeOrStatus) {
  const map = {
    photo_file_missing: "Photo file unavailable",
    photo_unreadable: "Photo could not be read",
    photo_unsupported_type: "Unsupported photo type",
    413: "Photo is too large",
    415: "Unsupported photo type",
    422: "Photo upload rejected",
  };
  return map[codeOrStatus] || `Upload failed (${codeOrStatus})`;
}

// A permanent failure needs user action (Replace/Remove) and must NOT be auto-retried. Everything
// else that failed transiently is safe for gentle background auto-retry with backoff.
const PERMANENT_PHOTO_CODES = ["photo_file_missing", "photo_unreadable", "photo_unsupported_type", "http_413", "http_415"];
function isPermanentFailure(m) {
  if (!m || m.state !== "failed") return false;
  if (isPhotoMutation(m)) return PERMANENT_PHOTO_CODES.includes(m.errorCode);
  return true; // non-photo failed mutations are left as-is (no behavior change)
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
      const detail = res.data && res.data.detail;
      const code = (detail && detail.code) || `http_${s}`;
      const message = (detail && detail.message) || (isPhotoMutation(m) ? photoErrorLabel(s) : `HTTP ${s}`);
      return { ...m, state: STATES.FAILED, error: message, errorCode: code, attempts };
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

module.exports = {
  STATES, uuidv4, makeMutation, processMutation, processQueue,
  SUPPORTED_PHOTO_TYPES, isPhotoMutation, validatePhotoMeta, buildSendPlan, photoErrorLabel, isPermanentFailure,
};

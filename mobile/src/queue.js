// Pure, storage-agnostic offline mutation queue + sync core.
// No Expo/React imports so it is unit-testable in Node against the live backend.
// CommonJS so it runs in both Metro (RN) and plain Node.

const STATES = { PENDING: "pending", SYNCED: "synced", FAILED: "failed", CONFLICT: "conflict" };

// Formats the Office /api/mobile/photos endpoint accepts. Reject others locally instead of queuing
// an item the backend will 4xx.
const SUPPORTED_PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"];
// Relay photos are base64-encoded into a single WebSocket frame. Keep the raw file comfortably below
// the 16 MiB WebSocket message ceiling after base64 expansion + JSON framing.
const MAX_RELAY_PHOTO_BYTES = 8 * 1024 * 1024;

function uuidv4() {
  // RFC4122-ish v4; adequate for client-generated stable IDs / idempotency keys.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function _measurementUpdateId(kind, path) {
  if (!path) return null;
  const parts = String(path).split("/").filter(Boolean);
  // Roof sketch update: /mobile/measurements/{revision}/sketches/{structure}
  if (kind === "measurement_sketch_update") {
    const si = parts.indexOf("sketches");
    if (si > 0 && parts[si + 1] && parts[si - 2] === "measurements") {
      const revisionId = parts[si - 1];
      const structureId = parts[si + 1];
      return `measurement-sketch-update:${revisionId}:${structureId}`;
    }
    return null;
  }
  if (kind !== "measurement_update") return null;
  const revisionId = parts[parts.length - 1];
  return revisionId ? `measurement-update:${revisionId}` : null;
}

// Build a durable mutation. The client_id IS the Idempotency-Key and never changes on retry.
// A caller may provide clientId when one logical offline draft must replace its own queued mutation.
// Existing roof-measurement PUTs automatically get a revision-stable id so repeated offline edits
// replace the same SQLite row instead of later conflicting with one another on a stale If-Match.
function makeMutation({ kind, method, path, body, ifMatch = null, label = "", scope = null, photo = null, clientId = null }) {
  const id = clientId || _measurementUpdateId(kind, path) || uuidv4();
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

function validatePhotoMeta(photo) {
  if (!photo || typeof photo !== "object" || !photo.uri || !photo.name || !photo.type) {
    return { ok: false, code: "photo_file_missing", message: "Photo file unavailable" };
  }
  if (!SUPPORTED_PHOTO_TYPES.includes(photo.type)) {
    return { ok: false, code: "photo_unsupported_type", message: "Unsupported photo type" };
  }
  return { ok: true };
}

function validateLocalPhotoInfo(info) {
  if (!info || !info.exists) {
    return { ok: false, status: 422, code: "photo_file_missing", message: "Photo file unavailable" };
  }
  if (info.size === 0) {
    return { ok: false, status: 422, code: "photo_unreadable", message: "Photo could not be read" };
  }
  if (typeof info.size === "number" && info.size > MAX_RELAY_PHOTO_BYTES) {
    return { ok: false, status: 413, code: "http_413", message: "Photo is too large" };
  }
  return { ok: true };
}

function buildSendPlan(m) {
  if (isPhotoMutation(m)) {
    const v = validatePhotoMeta(m.photo);
    if (!v.ok) return { transport: "local_failure", status: 422, code: v.code, message: v.message };
    return { transport: "multipart" };
  }
  return { transport: "json" };
}

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

const PERMANENT_PHOTO_CODES = ["photo_file_missing", "photo_unreadable", "photo_unsupported_type", "http_413", "http_415"];
function isPermanentFailure(m) {
  if (!m || m.state !== "failed") return false;
  if (isPhotoMutation(m)) return PERMANENT_PHOTO_CODES.includes(m.errorCode);
  return true;
}

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
    return { ...m, state: STATES.PENDING, error: isPhotoMutation(m) ? "Office server error — will retry" : `HTTP ${s}`, errorCode: `http_${s}`, attempts };
  } catch (e) {
    return { ...m, state: STATES.PENDING, error: isPhotoMutation(m) ? "Waiting for Office — will upload when reachable" : "Waiting for Office (not reachable)", errorCode: "offline", attempts };
  }
}

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
  SUPPORTED_PHOTO_TYPES, MAX_RELAY_PHOTO_BYTES, isPhotoMutation, validatePhotoMeta, validateLocalPhotoInfo,
  buildSendPlan, photoErrorLabel, isPermanentFailure,
};

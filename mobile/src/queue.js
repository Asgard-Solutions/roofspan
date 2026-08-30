// Pure, storage-agnostic offline mutation queue + sync core.
// No Expo/React imports so it is unit-testable in Node against the live backend.
// CommonJS so it runs in both Metro (RN) and plain Node.

const STATES = { PENDING: "pending", SYNCED: "synced", FAILED: "failed", CONFLICT: "conflict", LOCKED: "locked" };

// B3D: precise, SCOPED classification of a Roof Sketch 409. The sketch PUT route emits EXACTLY two
// 409s: (a) a version conflict, whose detail is an OBJECT carrying the authoritative `server` sketch,
// and (b) an immutable/locked-revision refusal, whose detail is a plain STRING ("...revision is locked
// ... Create a new revision..."). We treat the absence of a `server` object on a measurement_sketch_update
// 409 as the locked case — never a broad global substring rule, so unrelated mutations are unaffected.
function isSketchRevisionLocked(mutation, detail) {
  if (!mutation || mutation.kind !== "measurement_sketch_update") return false;
  const hasServer = detail && typeof detail === "object" && detail.server != null;
  return !hasServer;   // sketch conflicts always carry `server`; the only other sketch 409 is the lock
}

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
function makeMutation({ kind, method, path, body, ifMatch = null, label = "", scope = null, photo = null, clientId = null, mutationGeneration = 1, localEditGeneration = null }) {
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
    mutation_generation: mutationGeneration,
    // Local-only metadata (B3A): the Field edit_generation that produced this staged snapshot. Never
    // part of the backend request body; used for coordinator/debug traceability only.
    local_edit_generation: localEditGeneration,
    state: STATES.PENDING,
    server_id: null,
    serverValue: null,
    error: null,
    errorCode: null,
    attempts: 0,
    created_at: new Date().toISOString(),
  };
}

// --- Supersession helpers (pure; durable at the storage boundary uses these) ---
// The generation a NEW logical enqueue should carry given whatever row (if any) it replaces.
function nextGeneration(existingRow) {
  const g = existingRow && Number(existingRow.mutation_generation);
  return Number.isFinite(g) && g > 0 ? g + 1 : 1;
}
// Apply a network result ONLY when the currently-stored row for this client_id is the SAME generation
// that was sent. If the row was superseded (newer generation) or removed, the old result is discarded.
function shouldApplyResult(storedRow, sentRow) {
  if (!storedRow) return false;                 // row removed (e.g. conflict resolved by "Use Server")
  return Number(storedRow.mutation_generation) === Number(sentRow.mutation_generation);
}
function stampGeneration(m, gen) { return { ...m, mutation_generation: gen }; }

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
      // Retain the authoritative server response (document_version, document) for B3B reconciliation.
      const serverValue = (res.data && typeof res.data === "object") ? res.data : null;
      return { ...m, state: STATES.SYNCED, server_id: (res.data && res.data.id) || m.server_id, serverValue, error: null, attempts };
    }
    if (s === 409) {
      const detail = res.data && res.data.detail;
      // B3D: an immutable/locked measurement revision is a DURABLE terminal state — the salesperson's
      // unsynced document (m.body.document + local_edit_generation) is preserved verbatim and NEVER
      // auto-retried (processQueue only reprocesses pending/failed). Scoped strictly to sketch PUTs.
      if (isSketchRevisionLocked(m, detail)) {
        const message = (typeof detail === "string" && detail)
          || (detail && detail.message)
          || "This measurement revision is locked. Create a new revision to edit its sketch.";
        return { ...m, state: STATES.LOCKED, error: message, errorCode: "revision_locked", attempts };
      }
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
  nextGeneration, shouldApplyResult, stampGeneration,
  SUPPORTED_PHOTO_TYPES, MAX_RELAY_PHOTO_BYTES, isPhotoMutation, validatePhotoMeta, validateLocalPhotoInfo,
  buildSendPlan, photoErrorLabel, isPermanentFailure, isSketchRevisionLocked,
};

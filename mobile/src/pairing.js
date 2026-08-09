// Pure pairing helpers (CommonJS: runs in Metro/RN and plain Node). No Expo/React imports.
// Validates RoofSpan pairing payloads and normalizes the 6-digit fallback code.

const RELAY_PROTOCOL_VERSION = "1";

function normalizeNumericCode(s) {
  return String(s || "").replace(/\D/g, "").slice(0, 6);
}

function isValidNumericCode(s) {
  return /^\d{6}$/.test(normalizeNumericCode(s));
}

// Display grouped as "728 419" while input is normalized internally.
function formatNumericCode(s) {
  const n = normalizeNumericCode(s);
  return n.length > 3 ? `${n.slice(0, 3)} ${n.slice(3)}` : n;
}

// Validate a scanned/typed RoofSpan pairing payload BEFORE sending to the backend.
// Returns {ok:true, payload} or {ok:false, reason:'invalid'|'protocol'|'expired'}.
function parseQrPayload(raw) {
  let obj = raw;
  if (typeof raw === "string") {
    try { obj = JSON.parse(raw); } catch (e) { return { ok: false, reason: "invalid" }; }
  }
  if (!obj || typeof obj !== "object") return { ok: false, reason: "invalid" };
  if (!obj.installation_id || !obj.token) return { ok: false, reason: "invalid" };
  if (String(obj.v) !== RELAY_PROTOCOL_VERSION) return { ok: false, reason: "protocol" };
  if (obj.expires_at && Date.now() / 1000 > Number(obj.expires_at)) return { ok: false, reason: "expired" };
  return { ok: true, payload: { installation_id: obj.installation_id, token: obj.token, relay: obj.relay || null } };
}

module.exports = { RELAY_PROTOCOL_VERSION, normalizeNumericCode, isValidNumericCode, formatNumericCode, parseQrPayload };

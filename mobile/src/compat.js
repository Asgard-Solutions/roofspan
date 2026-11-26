// Office <-> Field compatibility gate (CommonJS, pure; node-testable).
// Field 1.1.0 needs Office 0.5.0+ (follow-ups, shared lead statuses). Office rejects too-old Field with 426.
// A block never touches pairing, cache or the offline queue — it only stops syncing until the update.
const { compareVersions } = require("./version");

const MIN_OFFICE_VERSION = "0.5.0";

let _blocked = null;        // null | { app: "office", officeVersion } | { app: "field", minField }
let _verified = false;      // Office version checked OK this session
const _subs = new Set();

function _set(b) {
  _blocked = b;
  for (const fn of _subs) { try { fn(b); } catch (e) { /* ignore */ } }
}

function officeTooOld(officeVersion) {
  return !officeVersion || compareVersions(officeVersion, MIN_OFFICE_VERSION) < 0;
}

// fetchVersion() -> { status, data } from Office GET /api/version. Returns true (ok), false (blocked),
// or null (Office unreachable — not a compatibility decision; caller retries later).
async function ensureCompatible(fetchVersion) {
  if (_blocked) return false;
  if (_verified) return true;
  let r;
  try { r = await fetchVersion(); } catch (e) { return null; }
  if (!r || !r.status || r.status >= 500) return null;
  const v = r.status === 200 && r.data ? r.data.version : null;
  if (officeTooOld(v)) { _set({ app: "office", officeVersion: v || "unknown" }); return false; }
  _verified = true;
  return true;
}

function reportFieldTooOld(detail) {
  _set({ app: "field", minField: (detail && detail.min_supported) || null });
}

// Retry: forget the decision so the next check asks Office again (e.g. after Office was updated).
function reset() { _verified = false; _set(null); }

module.exports = {
  MIN_OFFICE_VERSION, officeTooOld, ensureCompatible, reportFieldTooOld, reset,
  getBlocked: () => _blocked,
  onBlocked: (fn) => { _subs.add(fn); return () => _subs.delete(fn); },
};

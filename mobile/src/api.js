// Mobile networking facade. Delegates to the active MobileApiTransport (Relay in production,
// DirectHttp in dev). Screens keep using api.get(...); the queue keeps using send(...).
import { getTransport } from "./transport";
import { getToken } from "./auth";

async function authHeaders(extra) {
  const t = await getToken();
  const h = { ...(extra || {}) };
  if (t) h.Authorization = `Bearer ${t}`;
  return h;
}

function _throwOn4xx(r) {
  if (r.status >= 400) {
    const e = new Error("http_" + r.status);
    e.response = { status: r.status, data: r.data };
    throw e;
  }
  return r;
}

export const api = {
  async get(url, cfg = {}) {
    return _throwOn4xx(await getTransport().request({ method: "GET", path: url, params: cfg.params, headers: await authHeaders(cfg.headers) }));
  },
  async request({ url, method = "GET", params, data, headers } = {}) {
    return _throwOn4xx(await getTransport().request({ method, path: url, params, data, headers: await authHeaders(headers) }));
  },
};

// Offline-queue adapter: applies Idempotency-Key + If-Match, NEVER throws on status (the queue
// interprets status codes). Photo mutations transport as multipart through the same transport, and
// never silently fall through to the JSON path (queue.buildSendPlan enforces this).
import queue from "./queue";

// Optional Expo FileSystem (only present in the RN runtime). In plain Node it is unavailable and the
// on-disk check is skipped — the pure metadata validation in buildSendPlan still applies.
let _fsChecked = false;
let _fs = null;
function fsMod() {
  if (!_fsChecked) {
    _fsChecked = true;
    try { _fs = require("expo-file-system/legacy"); } catch (e) { _fs = null; }
  }
  return _fs;
}

async function localFileOk(uri) {
  const fs = fsMod();
  if (!fs) return { ok: true }; // cannot verify outside RN → let the upload proceed
  try {
    const info = await fs.getInfoAsync(uri, { size: true });
    if (!info || !info.exists) return { ok: false, code: "photo_file_missing", message: "Photo file unavailable" };
    if (info.size === 0) return { ok: false, code: "photo_unreadable", message: "Photo could not be read" };
    return { ok: true };
  } catch (e) {
    return { ok: false, code: "photo_unreadable", message: "Photo could not be read" };
  }
}

export async function send(m) {
  const headers = { "Idempotency-Key": m.idempotency_key };
  if (m.ifMatch) headers["If-Match"] = m.ifMatch;
  const h = await authHeaders(headers);

  const plan = queue.buildSendPlan(m);
  // Deterministic local failure — do NOT hit the network with a broken photo item.
  if (plan.transport === "local_failure") {
    return { status: plan.status, data: { detail: { code: plan.code, message: plan.message } } };
  }

  try {
    if (plan.transport === "multipart") {
      const chk = await localFileOk(m.photo.uri);
      if (!chk.ok) return { status: 422, data: { detail: { code: chk.code, message: chk.message } } };
      const b = m.body || {};
      const data = { record_type: b.record_type, record_id: b.record_id };
      if (b.category) data.category = b.category;
      if (b.description) data.description = b.description;
      const multipart = { data, file: { field: "file", name: m.photo.name, type: m.photo.type, uri: m.photo.uri } };
      return await getTransport().request({ method: m.method, path: m.path, headers: h, multipart });
    }
    return await getTransport().request({ method: m.method, path: m.path, headers: h, data: m.body });
  } catch (e) {
    // Network/relay failure behaves like a temporary outage — item stays pending, never dropped.
    if (e && e.response) return { status: e.response.status, data: e.response.data };
    return { status: 0, data: null };
  }
}

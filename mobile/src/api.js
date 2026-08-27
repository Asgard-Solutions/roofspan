// Mobile networking facade. Delegates to the active MobileApiTransport (Relay in production,
// DirectHttp in dev). Screens keep using api.get(...); the queue keeps using send(...).
//
// Silent session renewal: any authenticated request that comes back 401 triggers a single, shared
// refresh of the access token (using the long-lived refresh token) and is then retried once. If the
// refresh itself fails, the session is truly over — tokens are cleared and the app is signalled to
// return to sign-in. Pending offline work is never dropped.
import { getTransport } from "./transport";
import { getToken, getRefreshToken, saveTokens, clearTokens, notifySessionExpired } from "./auth";

async function authHeaders(extra) {
  const t = await getToken();
  const h = { ...(extra || {}) };
  if (t) h.Authorization = `Bearer ${t}`;
  return h;
}

// ---- Silent access-token refresh (single-flight) ---------------------------------------------
let _refreshPromise = null;

async function _doRefresh() {
  const rt = await getRefreshToken();
  if (!rt) return false;
  let r;
  try {
    r = await getTransport().request({ method: "POST", path: "/auth/refresh", data: { refresh_token: rt }, headers: {} });
  } catch (e) {
    return false; // network/relay hiccup — leave tokens as-is and retry later
  }
  if (r && r.status === 200 && r.data && r.data.access_token) {
    await saveTokens({ access_token: r.data.access_token, refresh_token: r.data.refresh_token });
    return true;
  }
  if (r && r.status === 401) {
    // Refresh token rejected (expired / revoked / reuse) → session is genuinely over.
    await clearTokens();
    notifySessionExpired();
    return false;
  }
  return false; // 5xx / offline — transient, keep tokens for a later attempt
}

export async function refreshAccessToken() {
  if (!_refreshPromise) _refreshPromise = _doRefresh().finally(() => { _refreshPromise = null; });
  return _refreshPromise;
}

// Run an authenticated request; on 401, refresh once and retry with the new token.
async function _authedRequest(base) {
  let r = await getTransport().request({ ...base, headers: await authHeaders(base.headers) });
  if (r && r.status === 401 && (await refreshAccessToken())) {
    r = await getTransport().request({ ...base, headers: await authHeaders(base.headers) });
  }
  return r;
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
    return _throwOn4xx(await _authedRequest({ method: "GET", path: url, params: cfg.params, headers: cfg.headers }));
  },
  async request({ url, method = "GET", params, data, headers } = {}) {
    return _throwOn4xx(await _authedRequest({ method, path: url, params, data, headers }));
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
    return queue.validateLocalPhotoInfo(info);
  } catch (e) {
    return { ok: false, status: 422, code: "photo_unreadable", message: "Photo could not be read" };
  }
}

// One network attempt for a queued mutation with the CURRENT access token.
async function _sendOnce(m) {
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
      if (!chk.ok) return { status: chk.status || 422, data: { detail: { code: chk.code, message: chk.message } } };
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

export async function send(m) {
  let res = await _sendOnce(m);
  // Expired access token → silently renew and retry once (same idempotency key = safe).
  if (res && res.status === 401 && (await refreshAccessToken())) {
    res = await _sendOnce(m);
  }
  return res;
}

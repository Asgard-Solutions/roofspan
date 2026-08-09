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
// interprets status codes). Photo mutations transport as multipart through the same transport.
export async function send(m) {
  const headers = { "Idempotency-Key": m.idempotency_key };
  if (m.ifMatch) headers["If-Match"] = m.ifMatch;
  const h = await authHeaders(headers);
  try {
    if (m.photo) {
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

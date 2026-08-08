import axios from "axios";
import { API } from "./config";
import { getToken } from "./auth";

export const api = axios.create({ baseURL: API, timeout: 20000 });

api.interceptors.request.use(async (config) => {
  const t = await getToken();
  if (t) config.headers.Authorization = `Bearer ${t}`;
  return config;
});

// send() adapter for the offline queue: applies Idempotency-Key + If-Match, never throws on 4xx/5xx.
// Photo mutations (m.photo present) are sent as multipart/form-data with the locally-persisted file.
export async function send(m) {
  const headers = { "Idempotency-Key": m.idempotency_key };
  if (m.ifMatch) headers["If-Match"] = m.ifMatch;

  if (m.photo) {
    const fd = new FormData();
    fd.append("file", { uri: m.photo.uri, name: m.photo.name, type: m.photo.type });
    const b = m.body || {};
    fd.append("record_type", b.record_type);
    fd.append("record_id", b.record_id);
    if (b.category) fd.append("category", b.category);
    if (b.description) fd.append("description", b.description);
    return api.request({ url: m.path, method: m.method, data: fd, headers, validateStatus: () => true });
  }

  return api.request({
    url: m.path,
    method: m.method,
    data: m.body,
    headers,
    validateStatus: () => true, // let the queue interpret status codes
  });
}

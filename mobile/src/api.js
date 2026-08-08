import axios from "axios";
import { API } from "./config";
import { getToken } from "./auth";

export const api = axios.create({ baseURL: API, timeout: 15000 });

api.interceptors.request.use(async (config) => {
  const t = await getToken();
  if (t) config.headers.Authorization = `Bearer ${t}`;
  return config;
});

// send() adapter for the offline queue: applies Idempotency-Key + If-Match, never throws on 4xx/5xx.
export async function send(m) {
  const headers = { "Idempotency-Key": m.idempotency_key };
  if (m.ifMatch) headers["If-Match"] = m.ifMatch;
  return api.request({
    url: m.path,
    method: m.method,
    data: m.body,
    headers,
    validateStatus: () => true, // let the queue interpret status codes
  });
}

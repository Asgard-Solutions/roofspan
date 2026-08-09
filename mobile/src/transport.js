// Mobile API transport boundary. Business screens/services call this abstraction — they never
// build backend URLs or WebSocket frames. RelayTransport is the production/remote path
// (Mobile -> Relay -> installation tunnel -> local FastAPI); DirectHttpTransport is dev/local only.
import axios from "axios";
import * as FileSystem from "expo-file-system";
import { API, API_BASE } from "./config";
import { RELAY_PROTOCOL_VERSION } from "./pairing";
import { buildRequestFrame, parseResponseFrame } from "./transportCore";

let _activePairing = null;
let _relay = null;
let _direct = null;

// pairingContext calls this so transport selection follows pairing state (no per-call SecureStore).
export function setActivePairing(p) {
  _activePairing = p || null;
  if (_relay) { _relay.close(); _relay = null; }
}

class DirectHttpTransport {
  async request({ method, path, params, headers, data, multipart }) {
    if (multipart) {
      const fd = new FormData();
      const d = multipart.data || {};
      for (const k of Object.keys(d)) fd.append(k, d[k]);
      const f = multipart.file || {};
      fd.append(f.field || "file", { uri: f.uri, name: f.name, type: f.type });
      const r = await axios.request({ baseURL: API, url: path, method, params, headers, data: fd, validateStatus: () => true });
      return { status: r.status, headers: r.headers, data: r.data };
    }
    const r = await axios.request({ baseURL: API, url: path, method, params, headers, data, validateStatus: () => true });
    return { status: r.status, headers: r.headers, data: r.data };
  }
}

class RelayTransport {
  constructor(pairing) {
    this.p = pairing;
    this.ws = null;
    this.pending = new Map();
    this._connecting = null;
  }
  _url() { return API_BASE.replace(/^http/, "ws") + "/api/relay/mobile"; }
  close() { try { this.ws && this.ws.close(); } catch (e) {} this.ws = null; this._rejectAll(_netErr("relay_closed")); }
  _rejectAll(err) { for (const { reject, timer } of this.pending.values()) { clearTimeout(timer); reject(err); } this.pending.clear(); }
  _onMessage(ev) {
    let f; try { f = JSON.parse(ev.data); } catch (e) { return; }
    const rid = f.request_id;
    const p = rid && this.pending.get(rid);
    if (!p) return;
    clearTimeout(p.timer);
    this.pending.delete(rid);
    if (f.type === "response") p.resolve(parseResponseFrame(f));
    else if (f.type === "error") p.reject(_netErr("relay_request_error", f.code));
  }
  _connect() {
    if (this.ws && this.ws.readyState === 1) return Promise.resolve(this.ws);
    if (this._connecting) return this._connecting;
    this._connecting = new Promise((resolve, reject) => {
      let ws;
      try { ws = new WebSocket(this._url()); } catch (e) { return reject(_netErr("relay_error")); }
      const to = setTimeout(() => { try { ws.close(); } catch (e) {} reject(_netErr("relay_timeout")); }, 12000);
      ws.onopen = () => ws.send(JSON.stringify({
        type: "hello", installation_id: this.p.installation_id, device_id: this.p.device_id,
        device_credential: this.p.device_credential, protocol: RELAY_PROTOCOL_VERSION,
      }));
      ws.onmessage = (ev) => {
        let f; try { f = JSON.parse(ev.data); } catch (e) { return; }
        if (f.type === "ready") {
          clearTimeout(to);
          this.ws = ws;
          ws.onmessage = (e2) => this._onMessage(e2);
          ws.onclose = () => { this.ws = null; this._rejectAll(_netErr("relay_disconnected")); };
          ws.onerror = () => {};
          resolve(ws);
        } else if (f.type === "error") {
          clearTimeout(to); try { ws.close(); } catch (e) {} reject(_netErr("relay_rejected", f.code));
        }
      };
      ws.onerror = () => { clearTimeout(to); reject(_netErr("relay_error")); };
      ws.onclose = () => { clearTimeout(to); };
    }).finally(() => { this._connecting = null; });
    return this._connecting;
  }
  async request({ method, path, params, headers, data, multipart }) {
    // File reading stays in the transport layer (never spread through screens).
    if (multipart && multipart.file && multipart.file.uri && !multipart.file.b64) {
      const enc = (FileSystem.EncodingType && FileSystem.EncodingType.Base64) || "base64";
      const b64 = await FileSystem.readAsStringAsync(multipart.file.uri, { encoding: enc });
      const file = { ...multipart.file, b64 }; delete file.uri;
      multipart = { ...multipart, file };
    }
    await this._connect();
    const rid = Math.random().toString(36).slice(2);
    const frame = buildRequestFrame({ rid, method, path: "/api" + path, params, headers, data, multipart });
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(rid); reject(_netErr("relay_request_timeout", "request_timeout")); }, 30000);
      this.pending.set(rid, { resolve, reject, timer });
      try { this.ws.send(JSON.stringify(frame)); }
      catch (e) { clearTimeout(timer); this.pending.delete(rid); reject(_netErr("relay_send_failed")); }
    });
  }
}

function _netErr(message, code) { const e = new Error(message); e.code = code || message; e.isNetwork = true; return e; }

export function getTransport() {
  if (_activePairing) {
    if (!_relay) _relay = new RelayTransport(_activePairing);
    return _relay;
  }
  if (!_direct) _direct = new DirectHttpTransport();
  return _direct;
}

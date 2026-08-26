// Mobile relay client: resolve pairing, probe connection state, and sign in THROUGH the relay.
// The relay is transient transport; the LOCAL FastAPI remains the auth/RBAC authority.
import axios from "axios";
import { API, relayWsUrl } from "./config";
import { RELAY_PROTOCOL_VERSION } from "./pairing";

const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
function b64encode(str) {
  let out = "";
  for (let i = 0; i < str.length; i += 3) {
    const a = str.charCodeAt(i), b = str.charCodeAt(i + 1), c = str.charCodeAt(i + 2);
    out += B64[a >> 2] + B64[((a & 3) << 4) | (b >> 4)] +
      (isNaN(b) ? "=" : B64[((b & 15) << 2) | (c >> 6)]) + (isNaN(c) ? "=" : B64[c & 63]);
  }
  return out;
}
function b64decode(s) {
  s = String(s || "").replace(/=+$/, "");
  let out = "";
  let bits = 0, val = 0;
  for (const ch of s) {
    const idx = B64.indexOf(ch);
    if (idx < 0) continue;
    val = (val << 6) | idx; bits += 6;
    if (bits >= 8) { bits -= 8; out += String.fromCharCode((val >> bits) & 0xff); }
  }
  return out;
}

// Off-network pairing resolve (unauthenticated by design). HTTP failures are returned to the caller;
// network/DNS/TLS failures use status 0 so the UI can distinguish unreachable from an invalid code.
export async function resolvePairing({ token, numeric_code, label }) {
  try {
    return await axios.post(
      `${API}/control-plane/pairing/resolve`,
      { token: token || null, numeric_code: numeric_code || null, label: label || "RoofSpan Mobile" },
      { validateStatus: () => true, timeout: 20000 }
    );
  } catch (e) {
    return { status: 0, data: { code: "control_plane_unreachable" } };
  }
}

// Control Plane version_policy is the single source of truth for Mobile version policy.
export async function checkVersion(appVersion) {
  try {
    const r = await axios.post(
      `${API}/control-plane/mobile/version-check`,
      { app_version: appVersion },
      { validateStatus: () => true, timeout: 12000 }
    );
    if (r.status === 200) return r.data;
  } catch (e) { /* offline / unreachable */ }
  return null;
}

// Open a Relay session. A pairing-provided endpoint is authoritative; the configured public Relay is
// the fallback. Resolves {ok:true} on ready, or {ok:false, code} on error/timeout.
function openSession(pairing, onReady) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (v) => { if (!settled) { settled = true; resolve(v); } };
    let ws;
    try {
      ws = new WebSocket(relayWsUrl(pairing && pairing.relay_endpoint));
    } catch (e) {
      return done({ ok: false, code: "tunnel_unavailable" });
    }
    const timer = setTimeout(() => {
      try { ws && ws.close(); } catch (e) {}
      done({ ok: false, code: "request_timeout" });
    }, 12000);
    ws.onopen = () => ws.send(JSON.stringify({
      type: "hello",
      installation_id: pairing.installation_id,
      device_id: pairing.device_id,
      device_credential: pairing.device_credential,
      protocol: pairing.protocol_version || RELAY_PROTOCOL_VERSION,
    }));
    ws.onmessage = (ev) => {
      let f;
      try { f = JSON.parse(ev.data); } catch (e) { return; }
      if (f.type === "ready") {
        clearTimeout(timer);
        if (onReady) onReady(ws, done, timer);
        else {
          try { ws.close(); } catch (e) {}
          done({ ok: true });
        }
      } else if (f.type === "error") {
        clearTimeout(timer);
        try { ws.close(); } catch (e) {}
        done({ ok: false, code: f.code });
      }
    };
    ws.onerror = () => { clearTimeout(timer); done({ ok: false, code: "tunnel_unavailable" }); };
    ws.onclose = () => { clearTimeout(timer); done({ ok: false, code: "tunnel_unavailable" }); };
  });
}

export async function probeConnection(pairing) {
  return openSession(pairing);
}

// Route POST /api/auth/login through the Relay to the local FastAPI.
export async function signInThroughRelay(pairing, email, password) {
  return openSession(pairing, (ws, done) => {
    const rid = Math.random().toString(36).slice(2);
    const body = b64encode(JSON.stringify({ email, password }));
    const t = setTimeout(() => {
      try { ws.close(); } catch (e) {}
      done({ ok: false, code: "request_timeout" });
    }, 15000);
    ws.onmessage = (ev) => {
      let f;
      try { f = JSON.parse(ev.data); } catch (e) { return; }
      if (f.type === "response" && f.request_id === rid) {
        clearTimeout(t);
        try { ws.close(); } catch (e) {}
        let data = null;
        try { data = JSON.parse(b64decode(f.body || "")); } catch (e) {}
        done({ ok: f.status >= 200 && f.status < 300, status: f.status, data });
      } else if (f.type === "error") {
        clearTimeout(t);
        try { ws.close(); } catch (e) {}
        done({ ok: false, code: f.code });
      }
    };
    ws.send(JSON.stringify({
      type: "request",
      request_id: rid,
      method: "POST",
      path: "/api/auth/login",
      headers: { "content-type": "application/json" },
      body,
    }));
  });
}

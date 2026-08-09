// Pure Relay transport framing (CommonJS: RN + Node, no axios/WS/expo imports).
// Builds relay request frames and parses response frames; used by RelayTransport and Node tests.

const HOP_BY_HOP = ["host", "content-length", "connection", "keep-alive", "transfer-encoding", "upgrade", "proxy-authorization", "proxy-authenticate"];

// Drop hop-by-hop / infrastructure headers so only meaningful app headers cross the relay.
function sanitizeHeaders(headers) {
  const out = {};
  for (const k of Object.keys(headers || {})) {
    if (!HOP_BY_HOP.includes(String(k).toLowerCase())) out[k] = headers[k];
  }
  return out;
}

function toQuery(params) {
  if (!params) return "";
  if (typeof params === "string") return params.replace(/^\?/, "");
  return Object.keys(params)
    .filter((k) => params[k] !== undefined && params[k] !== null)
    .map((k) => encodeURIComponent(k) + "=" + encodeURIComponent(params[k]))
    .join("&");
}

const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
function _b64(bytestr) {
  let out = "";
  for (let i = 0; i < bytestr.length; i += 3) {
    const a = bytestr.charCodeAt(i), b = bytestr.charCodeAt(i + 1), c = bytestr.charCodeAt(i + 2);
    out += B64[a >> 2] + B64[((a & 3) << 4) | (b >> 4)] +
      (isNaN(b) ? "=" : B64[((b & 15) << 2) | (c >> 6)]) + (isNaN(c) ? "=" : B64[c & 63]);
  }
  return out;
}
function _unb64(s) {
  s = String(s || "").replace(/[^A-Za-z0-9+/]/g, "");
  let out = "", bits = 0, val = 0;
  for (const ch of s) {
    val = (val << 6) | B64.indexOf(ch); bits += 6;
    if (bits >= 8) { bits -= 8; out += String.fromCharCode((val >> bits) & 0xff); }
  }
  return out;
}
// UTF-8 safe base64 (handles unicode in JSON, e.g. names/notes).
function b64encodeUtf8(str) { return _b64(unescape(encodeURIComponent(String(str)))); }
function b64decodeUtf8(s) { try { return decodeURIComponent(escape(_unb64(s))); } catch (e) { return _unb64(s); } }

function buildRequestFrame({ rid, method, path, params, headers, data, multipart }) {
  const frame = {
    type: "request", request_id: rid, method: String(method || "GET").toUpperCase(),
    path: path, query: toQuery(params), headers: sanitizeHeaders(headers),
  };
  if (multipart) {
    frame.multipart = multipart; // { data:{...}, file:{ field,name,type,b64 } }
    frame.body = "";
  } else if (data !== undefined && data !== null) {
    if (!frame.headers["content-type"] && !frame.headers["Content-Type"]) frame.headers["content-type"] = "application/json";
    frame.body = b64encodeUtf8(typeof data === "string" ? data : JSON.stringify(data));
  } else {
    frame.body = "";
  }
  return frame;
}

function parseResponseFrame(frame) {
  const ct = (frame.headers && (frame.headers["content-type"] || frame.headers["Content-Type"])) || "";
  const raw = b64decodeUtf8(frame.body || "");
  let data = raw;
  if (String(ct).includes("application/json")) { try { data = JSON.parse(raw); } catch (e) { data = raw; } }
  return { status: frame.status, headers: frame.headers || {}, data };
}

module.exports = { HOP_BY_HOP, sanitizeHeaders, toQuery, buildRequestFrame, parseResponseFrame, b64encodeUtf8, b64decodeUtf8 };

import Constants from "expo-constants";

const extra = (Constants.expoConfig && Constants.expoConfig.extra) || {};

function cleanBase(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

// One authoritative hosted Control Plane. The canonical EXPO_PUBLIC variable and app.json value take
// precedence over the legacy generic API variable so a stale preview URL cannot silently receive a
// production pairing code.
export const API_BASE = cleanBase(
  process.env.EXPO_PUBLIC_CONTROL_PLANE_BASE_URL ||
  extra.controlPlaneBase ||
  process.env.EXPO_PUBLIC_API_BASE ||
  extra.apiBase ||
  "https://cp.roofspan.io"
);

export const API = `${API_BASE}/api`;

// Relay is a separate public service. A resolved pairing may provide the endpoint; the build-time
// value remains the fallback. Both an origin and a full /api/relay/mobile URL are accepted.
const RELAY_WSS_BASE = cleanBase(
  process.env.EXPO_PUBLIC_RELAY_WSS_URL || extra.relayWss || "wss://relay.roofspan.io"
);

export function relayWsUrl(pairingEndpoint = "") {
  let origin = cleanBase(pairingEndpoint) || RELAY_WSS_BASE;
  if (/\/api\/relay\/mobile$/i.test(origin)) return origin;
  if (/\/api\/relay\/tunnel$/i.test(origin)) {
    return origin.replace(/\/api\/relay\/tunnel$/i, "/api/relay/mobile");
  }
  return `${origin}/api/relay/mobile`;
}

// HTTPS origin of the same Relay service, used for the native map-tile passthrough
// (MapLibre native fetches tiles over HTTPS; it cannot use the Relay WebSocket).
export function relayHttpBase(pairingEndpoint = "") {
  let origin = cleanBase(pairingEndpoint) || RELAY_WSS_BASE;
  origin = origin.replace(/\/api\/relay\/(mobile|tunnel|installation)$/i, "");
  return origin.replace(/^wss:/i, "https:").replace(/^ws:/i, "http:");
}

// RoofSpan web application (billing/account management lives on the web, never in-app purchasing).
export const WEB_APP_URL = cleanBase(
  process.env.EXPO_PUBLIC_WEB_APP_URL || extra.webAppUrl || "https://roofspan.io"
);

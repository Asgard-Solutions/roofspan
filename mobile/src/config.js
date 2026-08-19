import Constants from "expo-constants";

const extra = (Constants.expoConfig && Constants.expoConfig.extra) || {};

// Control Plane / API base. Production: https://cp.roofspan.io (set via EXPO_PUBLIC_* at build time).
// EXPO_PUBLIC_CONTROL_PLANE_BASE_URL is the canonical production var (see
// infra/config/production.endpoints.env.example); EXPO_PUBLIC_API_BASE kept for backwards compat.
export const API_BASE =
  process.env.EXPO_PUBLIC_API_BASE ||
  process.env.EXPO_PUBLIC_CONTROL_PLANE_BASE_URL ||
  extra.apiBase ||
  "https://unified-mono-deploy.preview.emergentagent.com";

export const API = `${API_BASE}/api`;

// Secure Relay WSS host. Production is a SEPARATE host from the Control Plane and is NOT derived
// from it (wss://relay.roofspan.io). Set EXPO_PUBLIC_RELAY_WSS_URL (or app.json extra.relayWss) in
// production builds. In dev/preview (no override) the relay is served by the same backend, so we
// derive the ws:// origin from API_BASE. The relay mobile route is always /api/relay/mobile.
const RELAY_WSS_BASE =
  process.env.EXPO_PUBLIC_RELAY_WSS_URL || extra.relayWss || "";

export function relayWsUrl() {
  const origin = RELAY_WSS_BASE || API_BASE.replace(/^http/, "ws");
  return origin.replace(/\/+$/, "") + "/api/relay/mobile";
}

// ARCHITECTURE (LOCKED): There is NO centrally hosted RoofSpan customer/billing web app.
// Subscription, seats, and billing are managed only inside RoofSpan Office (the local
// Windows-installed application). Mobile is a free companion app and never sells or manages
// subscriptions. Do NOT reintroduce a WEB_APP_URL / EXPO_PUBLIC_WEB_APP_URL billing target.


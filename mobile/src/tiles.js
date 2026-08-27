// Map-tile helpers for the RoofSpan Field map.
//
// Auth for satellite/building tiles uses a short-lived, opaque TICKET carried in a request header
// (never in the URL). This keeps device credentials + the user token out of tile URLs/logs AND keeps
// tile URLs STABLE, which is what lets MapLibre's ambient cache serve recently viewed tiles offline.
import axios from "axios";
import { relayHttpBase } from "./config";

export const TILE_TICKET_HEADER = "X-RoofSpan-Tile-Ticket";

// Exchange device credentials for a short-lived tile ticket (credentials travel in the POST body
// only). Imagery is org-level, so the user token is optional. Returns { ticket, status, detail } so
// callers can surface the real reason (device auth, control plane, offline) instead of a blank fail.
export async function mintTileTicket(pairing, token) {
  if (!pairing) return { ticket: null, status: 0, detail: "not_paired" };
  try {
    const body = {
      installation_id: pairing.installation_id,
      device_id: pairing.device_id,
      device_credential: pairing.device_credential,
    };
    if (token) body.token = token;
    const r = await axios.post(
      `${relayHttpBase(pairing.relay_endpoint)}/api/relay/tile-ticket`,
      body,
      { timeout: 15000, validateStatus: () => true }
    );
    if (r.status === 200 && r.data && r.data.ticket) return { ticket: r.data.ticket, status: 200, detail: null };
    const detail = (r.data && (r.data.detail || r.data.message)) || `HTTP ${r.status}`;
    return { ticket: null, status: r.status, detail: String(detail) };
  } catch (e) {
    return { ticket: null, status: 0, detail: "relay_unreachable" };
  }
}

// Stable tile URL template; MapLibre substitutes {z}/{x}/{y}. The short-lived ticket is carried as a
// query param (`t`) because MapLibre-native raster/vector sources do not reliably send custom headers
// on tile requests. The relay tile endpoint accepts the ticket via `t` as well as the header.
export function tileTemplate(pairing, kind, ticket) {
  if (!pairing || !ticket) return null;
  return `${relayHttpBase(pairing.relay_endpoint)}/api/relay/tiles/${kind}/{z}/{x}/{y}?t=${encodeURIComponent(ticket)}`;
}

// Map-tile helpers for the RoofSpan Field map.
//
// Auth for satellite/building tiles uses a short-lived, opaque TICKET carried in a request header
// (never in the URL). This keeps device credentials + the user token out of tile URLs/logs AND keeps
// tile URLs STABLE, which is what lets MapLibre's ambient cache serve recently viewed tiles offline.
import axios from "axios";
import { relayHttpBase } from "./config";

export const TILE_TICKET_HEADER = "X-RoofSpan-Tile-Ticket";

// Exchange device credentials + user token for a short-lived tile ticket (credentials travel in the
// POST body only). Returns the ticket string, or null when unavailable/offline.
export async function mintTileTicket(pairing, token) {
  if (!pairing || !token) return null;
  try {
    const r = await axios.post(
      `${relayHttpBase(pairing.relay_endpoint)}/api/relay/tile-ticket`,
      {
        installation_id: pairing.installation_id,
        device_id: pairing.device_id,
        device_credential: pairing.device_credential,
        token,
      },
      { timeout: 15000, validateStatus: () => true }
    );
    if (r.status === 200 && r.data && r.data.ticket) return r.data.ticket;
  } catch (e) {
    /* offline / relay unreachable — caller falls back to cached tiles */
  }
  return null;
}

// Stable tile URL template; MapLibre substitutes {z}/{x}/{y}. The short-lived ticket is carried as a
// query param (`t`) because MapLibre-native raster/vector sources do not reliably send custom headers
// on tile requests. The relay tile endpoint accepts the ticket via `t` as well as the header.
export function tileTemplate(pairing, kind, ticket) {
  if (!pairing || !ticket) return null;
  return `${relayHttpBase(pairing.relay_endpoint)}/api/relay/tiles/${kind}/{z}/{x}/{y}?t=${encodeURIComponent(ticket)}`;
}

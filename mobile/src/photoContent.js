import axios from "axios";
import { API_BASE, relayHttpBase } from "./config";

export const PHOTO_TICKET_HEADER = "X-RoofSpan-Photo-Ticket";

// Mint a short-lived Relay ticket. Durable pairing credentials and the user JWT are sent only in
// this POST body; they are never embedded in an image URL.
export async function mintPhotoTicket(pairing, token) {
  if (!pairing || !pairing.installation_id || !pairing.device_id || !pairing.device_credential || !token) {
    return { ticket: null, status: 0, detail: "photo_auth_unavailable" };
  }
  try {
    const response = await axios.post(
      `${relayHttpBase(pairing.relay_endpoint)}/api/relay/photo-ticket`,
      {
        installation_id: pairing.installation_id,
        device_id: pairing.device_id,
        device_credential: pairing.device_credential,
        token,
      },
      { timeout: 15000, validateStatus: () => true }
    );
    if (response.status >= 200 && response.status < 300 && response.data && response.data.ticket) {
      return { ticket: response.data.ticket, status: response.status, expiresIn: response.data.expires_in || 0 };
    }
    return {
      ticket: null,
      status: response.status,
      detail: response.data && response.data.detail ? response.data.detail : "photo_ticket_failed",
    };
  } catch (e) {
    return { ticket: null, status: 0, detail: "relay_unreachable" };
  }
}

// React Native Image can fetch HTTPS with custom headers. Paired production devices always use the
// Relay binary passthrough; direct API_BASE access is retained only for unpaired/local development.
export function photoContentSource(pairing, photo, ticket, token) {
  if (!photo || !photo.id) return null;

  if (pairing) {
    if (!ticket) return null;
    return {
      uri: `${relayHttpBase(pairing.relay_endpoint)}/api/relay/photos/${encodeURIComponent(photo.id)}`,
      headers: { [PHOTO_TICKET_HEADER]: ticket },
    };
  }

  const contentUrl = photo.content_url || `/api/mobile/photos/${encodeURIComponent(photo.id)}/content`;
  return {
    uri: `${API_BASE}${contentUrl}`,
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  };
}

// Pure mapping of relay/network outcomes -> user-facing connection states + RoofSpan copy (CommonJS).
// Never surfaces internal terms (tunnel, pub/sub, reqsig, websocket codes, Control Plane).

const STATES = {
  CONNECTING: "connecting",
  CONNECTED: "connected",
  RECONNECTING: "reconnecting",
  SERVER_UNAVAILABLE: "server_unavailable",
  OFFLINE: "offline",
  DEVICE_REVOKED: "device_revoked",
  SUBSCRIPTION_INACTIVE: "subscription_inactive",
  UPDATE_REQUIRED: "update_required",
  AUTH_REQUIRED: "auth_required",
};

function mapRelayError(code) {
  switch (code) {
    case "subscription_inactive":
      return STATES.SUBSCRIPTION_INACTIVE;
    case "device_not_paired":
    case "device_auth_failed":
    case "unknown_or_revoked_installation":
      return STATES.DEVICE_REVOKED;
    case "protocol_mismatch":
      return STATES.UPDATE_REQUIRED;
    case "tunnel_unavailable":
    case "request_timeout":
      return STATES.SERVER_UNAVAILABLE;
    default:
      return STATES.SERVER_UNAVAILABLE;
  }
}

const COPY = {
  [STATES.CONNECTING]: { title: "Connecting…", message: "Reaching your company's RoofSpan system." },
  [STATES.CONNECTED]: { title: "Connected", message: "" },
  [STATES.RECONNECTING]: { title: "Reconnecting…", message: "Re-establishing the connection to your company's RoofSpan system." },
  [STATES.SERVER_UNAVAILABLE]: { title: "Company RoofSpan server unavailable", message: "RoofSpan can't currently reach your company's Office system. Check your connection or try again shortly." },
  [STATES.OFFLINE]: { title: "No internet connection", message: "You're offline. Your work is saved and will sync when you're back online." },
  [STATES.DEVICE_REVOKED]: { title: "Device disconnected", message: "This device is no longer paired. Please ask your RoofSpan administrator to pair it again." },
  [STATES.SUBSCRIPTION_INACTIVE]: { title: "RoofSpan subscription inactive", message: "Your company's RoofSpan subscription needs to be updated before Mobile can be used. Please contact your RoofSpan administrator." },
  [STATES.UPDATE_REQUIRED]: { title: "RoofSpan must be updated", message: "A newer version is required to connect to your company's RoofSpan system." },
  [STATES.AUTH_REQUIRED]: { title: "Please sign in", message: "Sign in with your RoofSpan account to continue." },
};

module.exports = { STATES, mapRelayError, COPY };

"use strict";
/*
 * RoofSpan Field — MAP diagnostics (pure; no RN/IO). Builds a redacted, operational-only snapshot of a
 * native map-initialization failure so an engineer can tell WHY the My Area map fell back, instead of the
 * old `componentDidCatch(){}` that silently swallowed the error.
 *
 * PRIVACY (hard rule): this record carries ONLY booleans + short operational strings. It NEVER contains
 * access/refresh tokens, pairing secrets, API keys, the MapTiler key, a raw tile ticket, or authorization
 * headers. Callers pass BOOLEANS for "present" flags (e.g. tile_ticket_present) — never the secret itself.
 * Any error message/stack is additionally scrubbed for token-shaped substrings as defense in depth.
 */

const MAP_DIAG_CACHE_KEY = "map_diag_last";
const _MAX_MSG = 500;
const _MAX_STACK = 1500;

// Best-effort scrub of secret-shaped substrings from free text (message/stack).
function scrubSecrets(str) {
  if (str == null) return null;
  let s = String(str);
  s = s.replace(/Bearer\s+[A-Za-z0-9._\-]+/gi, "Bearer [REDACTED]");
  s = s.replace(/eyJ[A-Za-z0-9._\-]{10,}/g, "[REDACTED_JWT]"); // JWT-shaped
  s = s.replace(/\b(access_token|refresh_token|api[_-]?key|ticket|token|key)=[^&\s"']+/gi, "$1=[REDACTED]");
  return s;
}

function _bool(v) { return v === true; }

// Build a redacted map diagnostic. `fields` are operational flags/strings gathered at failure time.
function buildMapDiagnostic(fields = {}, now = () => new Date().toISOString()) {
  const {
    appVersion, executionEnvironment, reactNativeVersion,
    maplibreJsLoaded, maplibreNativeAvailable, mapStyleBuilt,
    mapConfigLoaded, propertiesLoaded, canvassLoaded,
    activeBaseLayer, maptilerConfigured, tileTicketPresent,
    error,
  } = fields;
  let name = null, message = null, stack = null;
  if (error && typeof error === "object") {
    name = error.name ? String(error.name).slice(0, 120) : null;
    message = error.message ? scrubSecrets(String(error.message)).slice(0, _MAX_MSG) : null;
    stack = error.stack ? scrubSecrets(String(error.stack)).slice(0, _MAX_STACK) : null;
  } else if (typeof error === "string") {
    message = scrubSecrets(error).slice(0, _MAX_MSG);
  }
  return {
    app_version: appVersion != null ? String(appVersion) : null,
    execution_environment: executionEnvironment != null ? String(executionEnvironment) : null,
    react_native_version: reactNativeVersion != null ? String(reactNativeVersion) : null,
    maplibre_js_loaded: _bool(maplibreJsLoaded),
    maplibre_native_available: _bool(maplibreNativeAvailable),
    map_style_built: _bool(mapStyleBuilt),
    map_config_loaded: _bool(mapConfigLoaded),
    properties_loaded: _bool(propertiesLoaded),
    canvass_loaded: _bool(canvassLoaded),
    active_base_layer: activeBaseLayer != null ? String(activeBaseLayer) : null,
    maptiler_configured: _bool(maptilerConfigured),
    tile_ticket_present: _bool(tileTicketPresent), // BOOLEAN only — never the raw ticket
    error_name: name,
    error_message: message,
    error_stack: stack,
    at: now(),
  };
}

module.exports = { MAP_DIAG_CACHE_KEY, scrubSecrets, buildMapDiagnostic };

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
const MAP_LOAD_DIAG_CACHE_KEY = "map_diag_load";  // updated on EVERY My Area load (success or partial)
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

module.exports = { MAP_DIAG_CACHE_KEY, MAP_LOAD_DIAG_CACHE_KEY, scrubSecrets, buildMapDiagnostic, buildMapLoadDiagnostic };

// Success/partial-load snapshot recorded on EVERY My Area load so a "200 with zero records" is clearly
// distinguishable from an API failure, and cached counts from live counts. No secrets — counts + IDs only.
function buildMapLoadDiagnostic(f = {}, now = () => new Date().toISOString()) {
  const arr = (x) => (Array.isArray(x) ? x : []);
  const propFeats = arr(f.propertyFeatures);
  const cachedProps = arr(f.cachedPropertyFeatures);
  const sections = arr(f.sections);
  const sampleProps = propFeats.slice(0, 3).map((ft) => ({
    id: ft && ft.properties ? String(ft.properties.id) : null,
    valid_point: !!(ft && ft.geometry && ft.geometry.type === "Point"
      && Array.isArray(ft.geometry.coordinates) && ft.geometry.coordinates.length === 2
      && typeof ft.geometry.coordinates[0] === "number" && typeof ft.geometry.coordinates[1] === "number"),
  }));
  const sampleSecs = sections.slice(0, 3).map((s) => ({
    id: s ? String(s.id) : null, name: s ? String(s.name || "") : null,
    geometry_present: !!(s && s.geometry), geometry_type: s && s.geometry ? s.geometry.type : null,
    property_count: s && typeof s.property_count === "number" ? s.property_count : null,
  }));
  return {
    user_id: f.userId != null ? String(f.userId) : null,
    user_email: f.userEmail != null ? String(f.userEmail) : null,
    user_role: f.userRole != null ? String(f.userRole) : null,
    map_properties_status: f.propertiesOk ? "ok" : "failed",
    feature_collection_valid: !!f.propertiesOk,
    property_feature_count: propFeats.length,
    cached_property_feature_count: cachedProps.length,
    sample_property_ids: sampleProps,
    canvass_status: f.canvassOk ? "ok" : "failed",
    section_count: sections.length,
    cached_section_count: f.cachedSectionCount != null ? Number(f.cachedSectionCount) : null,
    selected_section_id: f.selectedSectionId != null ? String(f.selectedSectionId) : null,
    sample_sections: sampleSecs,
    map_config_status: f.mapConfigOk ? "ok" : "failed",
    map_style_loaded: f.mapStyleBuilt === true,
    maplibre_version: f.maplibreVersion != null ? String(f.maplibreVersion) : null,
    react_native_version: f.reactNativeVersion != null ? String(f.reactNativeVersion) : null,
    source_api: f.sourceApi != null ? String(f.sourceApi) : null,
    property_source_feature_count: propFeats.length,
    canvass_source_feature_count: sections.filter((s) => s && s.geometry).length,
    at: now(),
  };
}

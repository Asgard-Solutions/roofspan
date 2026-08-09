/*
 * Pure map-config helpers (Node-testable; no React/native imports).
 * The Mobile app receives map configuration from the RoofSpan API (server-managed).
 * These helpers guarantee we NEVER hand missing/invalid/malformed config to native
 * MapLibre (which crashes hard on a null/invalid style). No provider URLs or keys are
 * hardcoded here — everything comes from the server-provided config object.
 */

const DEFAULT_CENTER = [-97.7431, 30.2672]; // [lng, lat] — matches server default; used only as a safe render value
const DEFAULT_ZOOM = 11;

// A usable XYZ raster tile template must be an http(s) URL containing {z}/{x}/{y} placeholders.
function isValidTileUrl(url) {
  return (
    typeof url === "string" &&
    /^https?:\/\//i.test(url) &&
    url.includes("{z}") &&
    url.includes("{x}") &&
    url.includes("{y}")
  );
}

// Config is renderable only if it carries a valid tile URL. Everything else has safe fallbacks.
function isValidMapConfig(cfg) {
  return !!cfg && typeof cfg === "object" && isValidTileUrl(cfg.osm_tile_url);
}

// Validate/normalize the map center. Returns a safe [lng, lat] within valid ranges.
function safeCenter(cfg) {
  const c = cfg && cfg.default_center;
  if (Array.isArray(c) && c.length === 2) {
    const lng = Number(c[0]);
    const lat = Number(c[1]);
    if (Number.isFinite(lng) && Number.isFinite(lat) && lng >= -180 && lng <= 180 && lat >= -90 && lat <= 90) {
      return [lng, lat];
    }
  }
  return DEFAULT_CENTER.slice();
}

// Validate/normalize zoom. Returns a safe number in [0, 24].
function safeZoom(cfg) {
  const raw = cfg && typeof cfg === "object" ? cfg.default_zoom : undefined;
  if (raw === null || raw === undefined || raw === "") return DEFAULT_ZOOM;
  const z = Number(raw);
  if (Number.isFinite(z) && z >= 0 && z <= 24) return z;
  return DEFAULT_ZOOM;
}

/*
 * Build a MapLibre style-spec JSON from server config. Returning a concrete style object
 * (instead of letting MapView default to a null style URL) is what prevents the native crash.
 * Returns null when config is not renderable — callers must then show the fallback UI.
 */
function buildMapStyle(cfg) {
  if (!isValidMapConfig(cfg)) return null;
  return {
    version: 8,
    sources: {
      osm: {
        type: "raster",
        tiles: [cfg.osm_tile_url],
        tileSize: 256,
        attribution: typeof cfg.attribution === "string" ? cfg.attribution : "",
      },
    },
    layers: [{ id: "osm", type: "raster", source: "osm", minzoom: 0, maxzoom: 22 }],
  };
}

/*
 * Whether the native MapLibre module can actually be used.
 * Expo Go (Constants.executionEnvironment === "storeClient") does NOT bundle custom native
 * modules like MapLibre, so importing the JS succeeds but rendering native components crashes.
 * In that case we must show the fallback list. Dev-client / standalone / bare builds include it.
 */
function isNativeMapAvailable(executionEnvironment) {
  if (executionEnvironment === "storeClient") return false; // Expo Go
  return true;
}

module.exports = {
  DEFAULT_CENTER,
  DEFAULT_ZOOM,
  isValidTileUrl,
  isValidMapConfig,
  isNativeMapAvailable,
  safeCenter,
  safeZoom,
  buildMapStyle,
};

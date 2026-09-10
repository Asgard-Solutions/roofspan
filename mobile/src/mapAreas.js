"use strict";
/*
 * RoofSpan Field — unified area-selector pure helpers (Node-testable; no React/native imports).
 * Areas come from GET /api/mobile/map/areas and are server-authorized. Two kinds:
 *   - "canvass_section": real stored polygon geometry + bounds (assigned to the user)
 *   - "zip": Office-loaded ZIP property dataset; NO polygon — bounds derived from member properties
 * The mobile client NEVER invents boundaries: it only fits the camera to server-provided bounds and,
 * for a ZIP, scopes pins by the property's own zip_code. Selection carries an explicit `type` so the
 * UI knows whether it has a real polygon (draw it) or only property-derived bounds (camera only).
 */

function normalizeAreas(raw) {
  const list = raw && Array.isArray(raw.areas) ? raw.areas : Array.isArray(raw) ? raw : [];
  return list
    .filter((a) => a && a.id && a.type)
    .map((a) => ({
      id: String(a.id),
      type: a.type,
      name: a.name != null ? String(a.name) : String(a.id),
      color: a.color || null,
      zip_code: a.zip_code != null ? String(a.zip_code) : null,
      territory_id: a.territory_id != null ? String(a.territory_id) : null,
      geometry: a.type === "zip" ? null : a.geometry || null, // ZIP has no polygon, ever
      property_count: typeof a.property_count === "number" ? a.property_count : null,
      bounds: isValidBounds(a.bounds) ? a.bounds : null,
    }));
}

// bounds contract: [[minLng, minLat], [maxLng, maxLat]] (sw, ne).
function isValidBounds(b) {
  return (
    Array.isArray(b) && b.length === 2 &&
    Array.isArray(b[0]) && Array.isArray(b[1]) &&
    b[0].length === 2 && b[1].length === 2 &&
    b.every((p) => p.every((n) => typeof n === "number" && Number.isFinite(n)))
  );
}

// Default selection PRIORITY (matches the server area order):
//   1) assigned canvass_section  2) territory  3) zip  4) none.
// A ZIP must NEVER override a valid Territory as the normal fallback.
function pickDefaultArea(areas) {
  if (!Array.isArray(areas) || areas.length === 0) return null;
  const sec = areas.find((a) => a.type === "canvass_section");
  if (sec) return sec.id;
  const terr = areas.find((a) => a.type === "territory");
  if (terr) return terr.id;
  const zip = areas.find((a) => a.type === "zip");
  if (zip) return zip.id;
  return null;
}

function findArea(areas, id) {
  return (Array.isArray(areas) ? areas : []).find((a) => a.id === id) || null;
}

// Turn server bounds into a MapLibre Camera bounds prop with sensible padding. Null when not fittable.
function boundsToCamera(bounds, padding = 48) {
  if (!isValidBounds(bounds)) return null;
  const [sw, ne] = bounds;
  // A single-point ZIP (sw === ne) still fits — MapLibre clamps to a reasonable zoom.
  return {
    ne: [ne[0], ne[1]],
    sw: [sw[0], sw[1]],
    paddingTop: padding, paddingBottom: padding, paddingLeft: padding, paddingRight: padding,
  };
}

function _within(coord, bounds) {
  if (!Array.isArray(coord) || coord.length < 2 || !isValidBounds(bounds)) return false;
  const [lng, lat] = coord;
  const [sw, ne] = bounds;
  return lng >= sw[0] && lng <= ne[0] && lat >= sw[1] && lat <= ne[1];
}

// Which pins belong to the selected area. Properties are now SERVER-SCOPED to the selected area
// (Territory / canvass section / ZIP loaded from a scoped endpoint), so this is a light guard:
//   - no area selected → NEVER all properties (returns []); the UI shows a "no area" state instead
//   - ZIP → defensively keep only features whose property zip_code matches
//   - canvass_section / territory → already server-scoped, returned as-is
function filterFeaturesForArea(features, area) {
  const list = Array.isArray(features) ? features : [];
  if (!area) return [];
  if (area.type === "zip") {
    if (!area.zip_code) return list;
    return list.filter((f) => f && f.properties && String(f.properties.zip_code || "") === area.zip_code);
  }
  return list;
}

// Fallback bounds when a selected area has none (should be rare): compute from the given point features.
function boundsFromFeatures(features) {
  const pts = (Array.isArray(features) ? features : [])
    .map((f) => f && f.geometry && f.geometry.coordinates)
    .filter((c) => Array.isArray(c) && c.length >= 2 && typeof c[0] === "number" && typeof c[1] === "number");
  if (pts.length === 0) return null;
  const lngs = pts.map((c) => c[0]);
  const lats = pts.map((c) => c[1]);
  return [[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]];
}

module.exports = {
  normalizeAreas,
  isValidBounds,
  pickDefaultArea,
  findArea,
  boundsToCamera,
  filterFeaturesForArea,
  boundsFromFeatures,
};

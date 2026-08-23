/*
 * RoofSpan Mobile — Canvass Section pure helpers (no device deps, testable in Node).
 * Server is authoritative for WHICH sections a sales user may see; these helpers only shape
 * already-authorized data for rendering + offline caching.
 */
const CACHE_SECTIONS = "canvass_sections";

function propsCacheKey(id) {
  return `canvass_props_${id}`;
}

function pickDefaultSection(sections) {
  return sections && sections.length ? sections[0].id : null;
}

// GeoJSON FeatureCollection for the selected section polygon (empty when none/invalid).
function buildSectionPolygonFC(section) {
  if (!section || !section.geometry) return { type: "FeatureCollection", features: [] };
  return { type: "FeatureCollection", features: [{ type: "Feature", geometry: section.geometry, properties: {} }] };
}

// Pin color contract: Do Not Knock is always the DNK color; otherwise the normal property color.
function pinColor(doNotKnock, brandColor, dnkColor) {
  return doNotKnock ? dnkColor : brandColor;
}

module.exports = { CACHE_SECTIONS, propsCacheKey, pickDefaultSection, buildSectionPolygonFC, pinColor };

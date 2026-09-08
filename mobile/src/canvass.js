/*
 * RoofSpan Mobile — Canvass Section pure helpers (no device deps, testable in Node).
 * Server is authoritative for WHICH sections a sales user may see; these helpers only shape
 * already-authorized data for rendering + offline caching.
 */
const CACHE_SECTIONS = "canvass_sections";
const CACHE_MAP_PROPS = "map_props_full";  // last good FULL authorized property dataset (not section-keyed)
const CACHE_MAP_CFG = "mapcfg";            // last good map configuration

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

// GeoJSON FeatureCollection for ALL assigned sections (each carries safe render props). The selected
// section is flagged so the layer can emphasize it; changing selection never drops the other polygons.
function buildAllSectionsFC(sections, selectedId) {
  const feats = (sections || [])
    .filter((s) => s && s.geometry)
    .map((s) => ({
      type: "Feature",
      geometry: JSON.parse(JSON.stringify(s.geometry)),
      properties: { section_id: s.id, name: s.name || "", color: s.color || null, selected: s.id === selectedId },
    }));
  return { type: "FeatureCollection", features: feats };
}

// Pin color contract: Do Not Knock is always the DNK color; otherwise the normal property color.
function pinColor(doNotKnock, brandColor, dnkColor) {
  return doNotKnock ? dnkColor : brandColor;
}

module.exports = { CACHE_SECTIONS, CACHE_MAP_PROPS, CACHE_MAP_CFG, propsCacheKey, pickDefaultSection, buildSectionPolygonFC, buildAllSectionsFC, pinColor };

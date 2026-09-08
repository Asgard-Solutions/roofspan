"use strict";
// Pure Node tests for RoofSpan Field MAP diagnostics: capture the right operational fields and NEVER leak
// secrets. Run directly: `node src/tests/map_diagnostics.node.test.js`.
const assert = require("assert");
const { buildMapDiagnostic, buildMapLoadDiagnostic, scrubSecrets, MAP_DIAG_CACHE_KEY, MAP_LOAD_DIAG_CACHE_KEY } = require("../mapDiagnostics");

let n = 0;
function ok(label, cond) { n++; assert.ok(cond, label); }

// 1. Captures the required operational fields as booleans/strings.
const d = buildMapDiagnostic({
  appVersion: "1.4.2", executionEnvironment: "standalone", reactNativeVersion: "0.86.3",
  maplibreJsLoaded: true, maplibreNativeAvailable: true, mapStyleBuilt: true,
  mapConfigLoaded: true, propertiesLoaded: false, canvassLoaded: true,
  activeBaseLayer: "street", maptilerConfigured: true, tileTicketPresent: true,
  error: new Error("boom"),
}, () => "2026-06-01T00:00:00Z");
ok("app version", d.app_version === "1.4.2");
ok("exec env", d.execution_environment === "standalone");
ok("rn version", d.react_native_version === "0.86.3");
ok("js loaded bool", d.maplibre_js_loaded === true);
ok("native available bool", d.maplibre_native_available === true);
ok("style built bool", d.map_style_built === true);
ok("config loaded", d.map_config_loaded === true);
ok("properties NOT loaded distinguished", d.properties_loaded === false);
ok("canvass loaded", d.canvass_loaded === true);
ok("base layer", d.active_base_layer === "street");
ok("maptiler configured", d.maptiler_configured === true);
ok("ticket present is boolean", d.tile_ticket_present === true && typeof d.tile_ticket_present === "boolean");
ok("error name", d.error_name === "Error");
ok("error message", d.error_message === "boom");
ok("timestamp", d.at === "2026-06-01T00:00:00Z");

// 2. Missing/loose flags coerce to false (never undefined) so a data failure is not misread.
const d2 = buildMapDiagnostic({ error: "plain string failure" });
ok("defaults false", d2.maplibre_native_available === false && d2.map_style_built === false && d2.canvass_loaded === false);
ok("string error captured", d2.error_message === "plain string failure");
ok("ticket default false", d2.tile_ticket_present === false);

// 3. Secrets must be scrubbed from message/stack (defense in depth), and never accepted as raw fields.
const leaky = new Error("failed with Authorization: Bearer abc.def.ghi and ?tile ticket token=SUPERSECRET123 and key=MTKEYXYZ");
leaky.stack = "at boot eyJhbGciOiJIUzI1NiJ9.payloadpayloadpayload.sigsigsig\n  ?access_token=REALTOKENVALUE";
const d3 = buildMapDiagnostic({ error: leaky, tileTicketPresent: true });
ok("no Bearer token in message", !/abc\.def\.ghi/.test(d3.error_message) && /Bearer \[REDACTED\]/.test(d3.error_message));
ok("token= redacted", !/SUPERSECRET123/.test(d3.error_message) && /token=\[REDACTED\]/.test(d3.error_message));
ok("key= redacted", !/MTKEYXYZ/.test(d3.error_message));
ok("JWT scrubbed from stack", !/payloadpayload/.test(d3.error_stack) && /\[REDACTED_JWT\]/.test(d3.error_stack));
ok("access_token scrubbed from stack", !/REALTOKENVALUE/.test(d3.error_stack));

// 4. The record must not contain any obviously secret key names.
const serialized = JSON.stringify(d3);
["access_token", "refresh_token", "authorization", "api_key", "maptiler_key", "pairing_secret", "raw_ticket"].forEach((k) => {
  ok(`no ${k} field`, !Object.prototype.hasOwnProperty.call(d3, k));
});
ok("no literal SUPERSECRET anywhere", !/SUPERSECRET123|REALTOKENVALUE|MTKEYXYZ/.test(serialized));

// 5. scrubSecrets handles null.
ok("scrub null", scrubSecrets(null) === null);
ok("cache key stable", MAP_DIAG_CACHE_KEY === "map_diag_last");

// ==============================================================================
// Phase 1 — buildMapLoadDiagnostic: written on EVERY My Area load. Distinguishes
// a 200-with-zero-records ("ok"/count=0) from an API failure ("failed"). NO secrets.
// ==============================================================================
ok("MAP_LOAD_DIAG_CACHE_KEY stable", MAP_LOAD_DIAG_CACHE_KEY === "map_diag_load");

// 1. Happy path: sales user, 2 property features, 2 sections (one with geometry).
const feats = [
  { type: "Feature", geometry: { type: "Point", coordinates: [1.1, 2.2] }, properties: { id: "p1" } },
  { type: "Feature", geometry: { type: "Point", coordinates: [3.3, 4.4] }, properties: { id: "p2" } },
];
const sections = [
  { id: "sA", name: "Alpha", geometry: { type: "Polygon", coordinates: [] }, property_count: 12 },
  { id: "sB", name: "Beta",  geometry: null, property_count: 0 },
];
const load = buildMapLoadDiagnostic({
  userId: "u-123", userEmail: "rep@t.io", userRole: "sales",
  propertiesOk: true, propertyFeatures: feats,
  cachedPropertyFeatures: [feats[0]],
  canvassOk: true, sections, cachedSectionCount: 1, selectedSectionId: "sA",
  mapConfigOk: true, mapStyleBuilt: true, maplibreVersion: "10.0.1",
  reactNativeVersion: "0.86.3", sourceApi: "/api/mobile/map/properties",
}, () => "2026-06-01T00:00:00Z");

ok("load: user id captured", load.user_id === "u-123");
ok("load: user email captured", load.user_email === "rep@t.io");
ok("load: user role captured", load.user_role === "sales");
ok("load: property_feature_count = 2", load.property_feature_count === 2);
ok("load: cached_property_feature_count = 1 (distinct from live)", load.cached_property_feature_count === 1);
ok("load: section_count = 2", load.section_count === 2);
ok("load: cached_section_count = 1", load.cached_section_count === 1);
ok("load: selected_section_id", load.selected_section_id === "sA");
ok("load: map_properties_status ok", load.map_properties_status === "ok");
ok("load: canvass_status ok", load.canvass_status === "ok");
ok("load: map_config_status ok", load.map_config_status === "ok");
ok("load: map_style_loaded true", load.map_style_loaded === true);
ok("load: maplibre_version", load.maplibre_version === "10.0.1");
ok("load: react_native_version", load.react_native_version === "0.86.3");
ok("load: source_api", load.source_api === "/api/mobile/map/properties");
ok("load: timestamp", load.at === "2026-06-01T00:00:00Z");

// Sample per-property valid_point booleans + first-3 IDs only.
ok("load: sample_property_ids array of first-3", Array.isArray(load.sample_property_ids) && load.sample_property_ids.length === 2);
ok("load: sample property has id", load.sample_property_ids[0].id === "p1");
ok("load: sample valid_point true for well-formed Point", load.sample_property_ids[0].valid_point === true);

// Per-section geometry_present/geometry_type/property_count.
ok("load: sample_sections length", load.sample_sections.length === 2);
ok("load: section geometry_present true for sA", load.sample_sections[0].geometry_present === true);
ok("load: section geometry_type Polygon", load.sample_sections[0].geometry_type === "Polygon");
ok("load: section property_count preserved", load.sample_sections[0].property_count === 12);
ok("load: section geometry_present false for sB", load.sample_sections[1].geometry_present === false);
ok("load: section geometry_type null when missing", load.sample_sections[1].geometry_type === null);
ok("load: canvass_source_feature_count = 1 (only geom-present)", load.canvass_source_feature_count === 1);

// 2. Distinguish 200+zero-records from failure: propertiesOk=true, empty array => ok + count 0.
const zero = buildMapLoadDiagnostic({
  userId: "u-zero", userEmail: "z@t.io", userRole: "sales",
  propertiesOk: true, propertyFeatures: [], canvassOk: true, sections: [],
  mapConfigOk: true, mapStyleBuilt: true,
});
ok("zero: status ok (not failed)", zero.map_properties_status === "ok");
ok("zero: property_feature_count = 0", zero.property_feature_count === 0);
ok("zero: feature_collection_valid true", zero.feature_collection_valid === true);
ok("zero: section_count = 0", zero.section_count === 0);

// 3. Failure path: propertiesOk=false => status 'failed'; feature_collection_valid=false.
const fail = buildMapLoadDiagnostic({
  userId: "u-f", userEmail: "f@t.io", userRole: "sales",
  propertiesOk: false, propertyFeatures: [], canvassOk: false, sections: [],
  mapConfigOk: false,
});
ok("fail: map_properties_status failed", fail.map_properties_status === "failed");
ok("fail: feature_collection_valid false", fail.feature_collection_valid === false);
ok("fail: canvass_status failed", fail.canvass_status === "failed");
ok("fail: map_config_status failed", fail.map_config_status === "failed");

// 4. Invalid point coordinates => valid_point false (distinguishes shape errors).
const bad = buildMapLoadDiagnostic({
  propertiesOk: true,
  propertyFeatures: [
    { type: "Feature", geometry: { type: "Point", coordinates: [1] }, properties: { id: "bad1" } },
    { type: "Feature", geometry: { type: "LineString", coordinates: [[1, 2], [3, 4]] }, properties: { id: "bad2" } },
    { type: "Feature", geometry: null, properties: { id: "bad3" } },
  ],
  canvassOk: true, sections: [],
});
ok("bad points: all valid_point=false", bad.sample_property_ids.every((s) => s.valid_point === false));
ok("bad points: ids still captured", bad.sample_property_ids.map((s) => s.id).join(",") === "bad1,bad2,bad3");

// 5. NO tokens/keys/tickets/headers ever appear in the load diagnostic.
const serializedLoad = JSON.stringify(load);
["access_token", "refresh_token", "authorization", "Authorization", "api_key",
 "maptiler_key", "pairing_secret", "raw_ticket", "ticket", "bearer", "Bearer"].forEach((k) => {
  ok(`load: no '${k}' in serialized output`, !serializedLoad.includes(k));
});
["access_token", "refresh_token", "authorization", "api_key", "maptiler_key",
 "pairing_secret", "raw_ticket", "ticket"].forEach((k) => {
  ok(`load: no top-level '${k}' key`, !Object.prototype.hasOwnProperty.call(load, k));
});

// 6. Cached-vs-live counts must remain distinct fields (bug: mixing them hides "loaded from cache").
ok("cached-vs-live distinct fields",
   Object.prototype.hasOwnProperty.call(load, "property_feature_count") &&
   Object.prototype.hasOwnProperty.call(load, "cached_property_feature_count") &&
   Object.prototype.hasOwnProperty.call(load, "section_count") &&
   Object.prototype.hasOwnProperty.call(load, "cached_section_count"));

// 7. Only first-3 property IDs sampled (never leaks the whole dataset).
const many = buildMapLoadDiagnostic({
  propertiesOk: true,
  propertyFeatures: Array.from({ length: 25 }, (_, i) => ({
    type: "Feature", geometry: { type: "Point", coordinates: [i, i] }, properties: { id: `id-${i}` },
  })),
  canvassOk: true, sections: [],
});
ok("first-3 property ids only", many.sample_property_ids.length === 3);
ok("full count still reported", many.property_feature_count === 25);


console.log(`map_diagnostics.node.test.js: ${n} assertions passed`);

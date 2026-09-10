"use strict";
/* RoofSpan Field — "My Area" MAP regression coverage (pure Node).
 * Locks in the P0 fix: My Area is a MAP, never a property directory; load states are independent so one
 * slow/failed request can't strand the map; the unified area selector (ZIP + assigned canvass) drives
 * fitBounds + pin scope; diagnostics expose mount/area/native state. */
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const A = require("../mapAreas");
const { buildMapLoadDiagnostic, buildMapDiagnostic } = require("../mapDiagnostics");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

const feat = (id, lng, lat, zip, occ) => ({ type: "Feature", geometry: { type: "Point", coordinates: [lng, lat] }, properties: { id, zip_code: zip, owner_occupied: occ } });
const FEATURES = [
  feat("p1", 2, 2, "73010", true),
  feat("p2", 3, 3, "73010", false),
  feat("p3", 25, 25, "73065", null),
  feat("p4", 26, 24, "73065", true),
];
const AREAS_RAW = { areas: [
  { type: "canvass_section", id: "sec-1", name: "North Blanchard", color: "#2563EB", territory_id: "t1",
    geometry: { type: "Polygon", coordinates: [[[1, 1], [1, 4], [4, 4], [4, 1], [1, 1]]] }, property_count: 2, bounds: [[1, 1], [4, 4]] },
  { type: "zip", id: "zip:73065", name: "73065 - Newcastle", zip_code: "73065", geometry: { type: "Polygon", coordinates: [] }, property_count: 2, bounds: [[24, 23], [27, 26]] },
  { type: "zip", id: "zip:bad", name: "bad", zip_code: "00000", bounds: [[1]] }, // invalid bounds → dropped to null
  { id: "no-type" }, // dropped (no type)
] };

// ---- normalizeAreas: ZIP never carries a polygon; invalid bounds nulled; malformed dropped ----------
{
  const areas = A.normalizeAreas(AREAS_RAW);
  assert.strictEqual(areas.length, 3, "malformed area (no type) is dropped");
  const zip = areas.find((a) => a.id === "zip:73065");
  assert.strictEqual(zip.geometry, null, "a ZIP area NEVER carries a polygon (bounds-only)");
  assert.deepStrictEqual(zip.bounds, [[24, 23], [27, 26]], "valid ZIP bounds retained");
  const bad = areas.find((a) => a.id === "zip:bad");
  assert.strictEqual(bad.bounds, null, "invalid bounds are nulled (never fabricated)");
  const sec = areas.find((a) => a.id === "sec-1");
  assert.ok(sec.geometry && sec.geometry.type === "Polygon", "canvass_section keeps its real polygon");
  ok("normalizeAreas: ZIP has no polygon, invalid bounds nulled, malformed dropped, polygons kept");
}

// ---- pickDefaultArea PRIORITY: canvass_section > territory > zip > none --------------------------
{
  const areas = A.normalizeAreas(AREAS_RAW);
  assert.strictEqual(A.pickDefaultArea(areas), "sec-1", "default selects the assigned canvass area");
  const terrAndZip = [
    { id: "zip:1", type: "zip", zip_code: "1" },
    { id: "territory:t1", type: "territory", territory_id: "t1", geometry: { type: "Polygon", coordinates: [] } },
  ];
  assert.strictEqual(A.pickDefaultArea(terrAndZip), "territory:t1", "Territory outranks ZIP as the fallback default");
  assert.strictEqual(A.pickDefaultArea([{ id: "zip:1", type: "zip", zip_code: "1" }]), "zip:1", "ZIP-only → ZIP is default");
  assert.strictEqual(A.pickDefaultArea([]), null, "no areas → no default");
  ok("pickDefaultArea: canvass > territory > zip > none (ZIP never overrides a Territory)");
}

// ---- Territory area: keeps its real polygon + bounds; carries territory_id --------------------------
{
  const raw = { areas: [
    { type: "territory", id: "territory:t1", name: "73010", color: "#16A34A", territory_id: "t1",
      geometry: { type: "Polygon", coordinates: [[[1, 1], [1, 4], [4, 4], [4, 1], [1, 1]]] },
      property_count: 8029, bounds: [[1, 1], [4, 4]] },
  ] };
  const areas = A.normalizeAreas(raw);
  const t = areas.find((a) => a.id === "territory:t1");
  assert.ok(t && t.type === "territory", "territory area normalized");
  assert.ok(t.geometry && t.geometry.type === "Polygon", "territory keeps its real GeoJSON polygon");
  assert.strictEqual(t.territory_id, "t1", "territory carries territory_id for scoped property loading");
  assert.deepStrictEqual(t.bounds, [[1, 1], [4, 4]], "territory bounds retained for fitBounds");
  assert.strictEqual(t.property_count, 8029, "territory property_count surfaced (scoped, not whole DB)");
  ok("normalizeAreas: territory keeps polygon + bounds + territory_id + scoped count");
}

// ---- MapScreen wiring: properties are loaded SCOPED per selected area (never the whole DB) ---------
{
  const src = fs.readFileSync(path.join(__dirname, "..", "screens", "MapScreen.js"), "utf8");
  assert.ok(/canvass-sections\/\$\{area\.id\}\/properties/.test(src), "canvass section → its own scoped properties endpoint");
  assert.ok(/map\/properties\?territory_id=/.test(src), "territory → /mobile/map/properties?territory_id= (scoped)");
  assert.ok(/map\/properties\?zip=/.test(src), "zip → /mobile/map/properties?zip= (scoped)");
  assert.ok(/loadPropsForArea/.test(src), "properties load via per-area loader (loadPropsForArea)");
  assert.ok(/map-no-area/.test(src), "compact 'no area' state exists (never dumps every property)");
  assert.ok(!/No area assigned yet — showing your full property map/.test(src), "the old 'showing your full property map' fallback is gone");
  ok("MapScreen: per-area scoped property loading + no-area compact state; full-map fallback removed");
}
{
  const cam = A.boundsToCamera([[1, 1], [4, 5]], 40);
  assert.deepStrictEqual([cam.sw, cam.ne], [[1, 1], [4, 5]], "camera fits the full bounding box (sw/ne)");
  assert.strictEqual(cam.paddingTop, 40, "padding applied so irregular areas are fully visible");
  assert.strictEqual(A.boundsToCamera(null), null, "no bounds → no camera fit");
  assert.strictEqual(A.boundsToCamera([[1]]), null, "invalid bounds → no camera fit");
  // A single-point ZIP still fits.
  const one = A.boundsToCamera([[5, 5], [5, 5]]);
  assert.deepStrictEqual([one.sw, one.ne], [[5, 5], [5, 5]], "single-point area still fits");
  ok("boundsToCamera: fitBounds with padding (never coordinates[0][0]); single-point safe");
}

// ---- filterFeaturesForArea: server-scoped datasets; ZIP by zip_code; NO area → NEVER all ----------
{
  const areas = A.normalizeAreas(AREAS_RAW);
  const zip = areas.find((a) => a.id === "zip:73065");
  const sec = areas.find((a) => a.id === "sec-1");
  const byZip = A.filterFeaturesForArea(FEATURES, zip).map((f) => f.properties.id);
  assert.deepStrictEqual(byZip.sort(), ["p3", "p4"], "ZIP scope filters pins by property zip_code");
  // Canvass/territory datasets are already scoped by the server → returned as-is (no client bbox drop).
  const bySec = A.filterFeaturesForArea(FEATURES, sec).map((f) => f.properties.id);
  assert.deepStrictEqual(bySec.sort(), ["p1", "p2", "p3", "p4"], "canvass/territory: server-scoped, returned as-is");
  assert.strictEqual(A.filterFeaturesForArea(FEATURES, null).length, 0, "no area → NEVER the full property map (empty)");
  ok("filterFeaturesForArea: ZIP→zip_code; canvass/territory server-scoped; none→empty (never all)");
}

// ---- boundsFromFeatures: fallback bbox from point features ----------------------------------------
{
  assert.deepStrictEqual(A.boundsFromFeatures(FEATURES), [[2, 2], [26, 25]], "bbox spans all point features");
  assert.strictEqual(A.boundsFromFeatures([]), null, "no features → null");
  ok("boundsFromFeatures: correct bbox fallback");
}

// ---- Camera precedence: a selected area's bounds ALWAYS win over map-config default_center --------
// (Regression for the Austin/wrong-center defect. FIXTURES ONLY — no production coords in prod logic.)
{
  const territory = {
    type: "territory", id: "territory:t-far", territory_id: "t-far",
    geometry: { type: "Polygon", coordinates: [[[-97.6, 35.1], [-97.6, 35.4], [-97.2, 35.4], [-97.2, 35.1], [-97.6, 35.1]]] },
    bounds: [[-97.6, 35.1], [-97.2, 35.4]],
  };
  const cam = A.boundsToCamera(territory.bounds);
  assert.ok(cam, "a territory with bounds yields a camera fit");
  assert.deepStrictEqual([cam.sw, cam.ne], [[-97.6, 35.1], [-97.2, 35.4]], "camera fits the territory bounds exactly");
  // An UNRELATED default-center fixture must be OUTSIDE the fitted bounds → no default-center fallback.
  const defaultCenterFixture = [-97.74, 30.27];
  const inside = defaultCenterFixture[0] >= cam.sw[0] && defaultCenterFixture[0] <= cam.ne[0] &&
                 defaultCenterFixture[1] >= cam.sw[1] && defaultCenterFixture[1] <= cam.ne[1];
  assert.ok(!inside, "the unrelated default center is NOT inside the fitted territory bounds");
  // Static wiring: MapScreen prefers area bounds over safeCenter(cfg); safeCenter is ONLY the no-area fallback.
  const src = fs.readFileSync(path.join(__dirname, "..", "screens", "MapScreen.js"), "utf8").replace(/\s+/g, " ");
  assert.ok(/camBounds \? \{ bounds: camBounds \} : \{ zoomLevel: safeZoom\(cfg\), centerCoordinate: safeCenter\(cfg\) \}/.test(src),
    "Camera uses area bounds when present; safeCenter(cfg) is ONLY the no-area fallback");
  assert.ok(/const camBounds = selectedArea \? boundsToCamera\(selectedArea\.bounds/.test(src),
    "camBounds derives from the selected area's stored bounds first");
  ok("camera precedence: selected-area bounds override map-config default_center (fixtures only)");
}

// ---- Diagnostics expose the required decoupled-state fields ---------------------------------------
{
  const load = buildMapLoadDiagnostic({
    propertiesOk: true, propertyFeatures: FEATURES, canvassOk: false, sections: [],
    mapConfigOk: false, areaCount: 3, selectedAreaId: "sec-1",
    nativeAvailable: true, executionEnvironment: "standalone",
    mapMountAttempted: true, mapMountSucceeded: false,
  });
  assert.strictEqual(load.property_status, "ok", "property_status present");
  assert.strictEqual(load.canvass_status, "failed", "an independent canvass failure is reported, not fatal");
  assert.strictEqual(load.map_config_status, "failed", "an independent config failure is reported, not fatal");
  assert.strictEqual(load.property_feature_count, 4, "property_feature_count present");
  assert.strictEqual(load.area_count, 3, "area_count present");
  assert.strictEqual(load.selected_area_id, "sec-1", "selected_area_id present");
  assert.strictEqual(load.native_available, true, "native_available present");
  assert.strictEqual(load.execution_environment, "standalone", "execution_environment present");
  assert.strictEqual(load.map_mount_attempted, true, "map_mount_attempted present");
  assert.strictEqual(load.map_mount_succeeded, false, "map_mount_succeeded present");

  const err = buildMapDiagnostic({ mapMountAttempted: true, mapMountSucceeded: false, areaCount: 3, selectedAreaId: "sec-1",
    error: { name: "MapError", message: "native init failed" } });
  assert.strictEqual(err.map_mount_attempted, true, "renderer diag records mount attempted");
  assert.strictEqual(err.map_mount_succeeded, false, "renderer diag records mount succeeded");
  assert.strictEqual(err.error_name, "MapError", "renderer diag captures the native error name");
  ok("diagnostics: property/canvass/config statuses independent; mount + area + native fields recorded");
}

// ---- PRODUCT GUARD: My Area is a MAP, not a property directory (FlatList fallback removed) ---------
{
  const src = fs.readFileSync(path.join(__dirname, "..", "screens", "MapScreen.js"), "utf8");
  assert.ok(!/FlatList/.test(src), "MapScreen must NOT use a FlatList (no property directory fallback)");
  assert.ok(!/renderFallback/.test(src), "the old renderFallback property-list must be gone");
  assert.ok(/onDidFinishRenderingMapFully/.test(src), "map mount success is tracked");
  assert.ok(/map-native-unavailable/.test(src) && /map-init-error/.test(src) && /map-retry-button/.test(src), "compact map states + retry exist");
  assert.ok(/boundsToCamera/.test(src), "camera uses fitBounds via boundsToCamera");
  assert.ok(!/coordinates\?\.\[0\]\?\.\[0\]/.test(src), "camera no longer derives center from coordinates[0][0]");
  ok("PRODUCT GUARD: FlatList/renderFallback removed; compact map states + fitBounds + mount tracking present");
}

console.log("\nMY AREA MAP: all " + n + " assertions passed");

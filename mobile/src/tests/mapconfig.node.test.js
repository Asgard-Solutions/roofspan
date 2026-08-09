/*
 * RoofSpan Mobile — map configuration safety test (pure Node, no device).
 * Proves the crash-guard contract:
 *   - valid config  -> renderable style JSON is produced (map initializes)
 *   - missing/invalid/malformed config -> buildMapStyle returns null (app shows fallback, no crash)
 *   - center/zoom are always sanitized to safe values (never crash native)
 *
 * Run: node src/tests/mapconfig.node.test.js
 */
const mc = require("../mapConfig");

let failures = 0;
function ok(cond, msg) {
  if (cond) { console.log("  \u2713", msg); }
  else { console.error("  \u2717 FAIL:", msg); failures++; }
}
// Ensure a call never throws (missing/invalid config must be handled, not crash).
function noThrow(fn, msg) {
  try { fn(); ok(true, msg); } catch (e) { ok(false, `${msg} (threw: ${e.message})`); }
}

const VALID = {
  osm_tile_url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  default_center: [-97.7431, 30.2672],
  default_zoom: 11.0,
  attribution: "\u00a9 OpenStreetMap contributors",
};

// 1) Valid config -> renderable style
const style = mc.buildMapStyle(VALID);
ok(mc.isValidMapConfig(VALID) === true, "valid config recognized as valid");
ok(style && typeof style === "object", "valid config produces a style object");
ok(!!style && style.version === 8, "style has version 8");
ok(!!style && Array.isArray(style.sources.osm.tiles) && style.sources.osm.tiles[0] === VALID.osm_tile_url, "style raster source uses server tile URL");
ok(!!style && Array.isArray(style.layers) && style.layers.length >= 1, "style has at least one layer");

// 2) Missing / invalid / malformed configs -> null (fallback), and never throw
const badConfigs = [
  ["null", null],
  ["undefined", undefined],
  ["empty object", {}],
  ["empty tile url", { osm_tile_url: "" }],
  ["non-string tile url", { osm_tile_url: 12345 }],
  ["no scheme", { osm_tile_url: "tile.openstreetmap.org/{z}/{x}/{y}.png" }],
  ["missing placeholders", { osm_tile_url: "https://tile.openstreetmap.org/tiles.png" }],
  ["partial placeholders", { osm_tile_url: "https://tile.example.com/{z}/{x}.png" }],
  ["object as url", { osm_tile_url: { a: 1 } }],
];
for (const [name, cfg] of badConfigs) {
  noThrow(() => mc.isValidMapConfig(cfg), `isValidMapConfig handles ${name} without throwing`);
  ok(mc.isValidMapConfig(cfg) === false, `${name} => invalid`);
  ok(mc.buildMapStyle(cfg) === null, `${name} => buildMapStyle returns null (fallback)`);
}

// 3) Center/zoom sanitization always returns safe values
ok(JSON.stringify(mc.safeCenter(VALID)) === JSON.stringify([-97.7431, 30.2672]), "valid center passed through");
ok(JSON.stringify(mc.safeCenter({ default_center: [999, 999] })) === JSON.stringify(mc.DEFAULT_CENTER), "out-of-range center -> default");
ok(JSON.stringify(mc.safeCenter({ default_center: "nope" })) === JSON.stringify(mc.DEFAULT_CENTER), "malformed center -> default");
ok(JSON.stringify(mc.safeCenter(null)) === JSON.stringify(mc.DEFAULT_CENTER), "null cfg center -> default");
ok(mc.safeZoom(VALID) === 11, "valid zoom passed through");
ok(mc.safeZoom({ default_zoom: 999 }) === mc.DEFAULT_ZOOM, "out-of-range zoom -> default");
ok(mc.safeZoom({ default_zoom: "x" }) === mc.DEFAULT_ZOOM, "malformed zoom -> default");
ok(mc.safeZoom(null) === mc.DEFAULT_ZOOM, "null cfg zoom -> default");

// 4) Native availability gate (Expo Go cannot load MapLibre's native module)
ok(mc.isNativeMapAvailable("storeClient") === false, "Expo Go (storeClient) => native map NOT available (use fallback)");
ok(mc.isNativeMapAvailable("bare") === true, "dev/bare build => native map available");
ok(mc.isNativeMapAvailable("standalone") === true, "standalone build => native map available");
noThrow(() => mc.isNativeMapAvailable(undefined), "isNativeMapAvailable handles undefined without throwing");

if (failures) { console.error(`\nMAP CONFIG TEST: ${failures} FAILURE(S)`); process.exit(1); }
console.log("\nMAP CONFIG TEST: PASS");
process.exit(0);

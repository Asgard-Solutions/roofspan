"use strict";
// Pure Node tests for RoofSpan Field MAP diagnostics: capture the right operational fields and NEVER leak
// secrets. Run directly: `node src/tests/map_diagnostics.node.test.js`.
const assert = require("assert");
const { buildMapDiagnostic, scrubSecrets, MAP_DIAG_CACHE_KEY } = require("../mapDiagnostics");

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

console.log(`map_diagnostics.node.test.js: ${n} assertions passed`);

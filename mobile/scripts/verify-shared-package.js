"use strict";
// B3C build-blocker regression guard. Babel parsing a source file does NOT prove Metro can resolve its
// imports, and a dirty node_modules can mask a broken workspace. This asserts, from whatever node_modules
// the CI just produced with a CLEAN install, that:
//   1. require.resolve("@roofspan/roof-sketch-core") succeeds, and
//   2. it resolves to the shared workspace package at packages/roof-sketch-core (NOT a copy inside mobile).
// The companion CI step additionally runs a real `expo export` so a broken workspace/lockfile/Metro
// config/EAS inclusion fails the build here instead of on EAS.
const path = require("path");

let resolved;
try {
  resolved = require.resolve("@roofspan/roof-sketch-core");
} catch (e) {
  console.error("FAIL: cannot resolve @roofspan/roof-sketch-core:", e.message);
  process.exit(1);
}

const real = require("fs").realpathSync(resolved);
const expectedDir = path.resolve(__dirname, "..", "..", "packages", "roof-sketch-core");
if (!real.startsWith(expectedDir)) {
  console.error("FAIL: @roofspan/roof-sketch-core resolved OUTSIDE the shared workspace package.");
  console.error("  resolved:", real);
  console.error("  expected under:", expectedDir);
  process.exit(1);
}

console.log("OK: @roofspan/roof-sketch-core ->", real);
console.log("OK: shared workspace package is the single Roof Sketch engine (no mobile copy).");

"use strict";
// Pure tests for the roof-sketch refresh decision (Office↔Field convergence hardening).
const assert = require("assert");
const { sketchRefreshDecision } = require("../sketchRefreshDecision");

let n = 0;
function ok(msg) { n += 1; console.log(`  ok ${n} - ${msg}`); }

// THE reported bug: Field has no sketch, Office created the first one → must PULL (row flips to "Edit").
assert.strictEqual(sketchRefreshDecision({ officeVersion: 3, localVersion: null }), "pull");
ok("missing local sketch + Office version>0 → pull (fixes 'Sketch Roof' stuck row)");

// Missing local + Office also has none → nothing to do.
assert.strictEqual(sketchRefreshDecision({ officeVersion: 0, localVersion: null }), "none");
ok("missing local sketch + Office has none → none");

// Missing local BUT the rep has a local draft or an active mutation → keep their unsynced work first.
assert.strictEqual(sketchRefreshDecision({ officeVersion: 3, localVersion: null, hasDraft: true }), "none");
assert.strictEqual(sketchRefreshDecision({ officeVersion: 3, localVersion: null, hasActiveMutation: true }), "none");
ok("missing local sketch but a local draft / active mutation exists → none (rep's work stays authoritative)");

// Versions differ → raise CAS floor AND pull the newer Office sketch.
assert.strictEqual(sketchRefreshDecision({ officeVersion: 5, localVersion: 4 }), "floor_and_pull");
ok("Office version > local version → floor_and_pull");

// An active mutation blocks any pull even when versions differ (don't clobber in-flight local work).
assert.strictEqual(sketchRefreshDecision({ officeVersion: 5, localVersion: 4, hasActiveMutation: true }), "none");
ok("active mutation blocks pull even when versions differ");

// Same version, divergent local draft, NO active mutation → explicit review (not silent local-wins).
assert.strictEqual(sketchRefreshDecision({ officeVersion: 4, localVersion: 4, hasDraft: true, contentDiffers: true }), "review");
ok("same version + divergent draft + no active mutation → review");

// Same version, draft matches content → nothing to do.
assert.strictEqual(sketchRefreshDecision({ officeVersion: 4, localVersion: 4, hasDraft: true, contentDiffers: false }), "none");
// Same version, no draft → nothing to do.
assert.strictEqual(sketchRefreshDecision({ officeVersion: 4, localVersion: 4 }), "none");
ok("same version + matching/no draft → none");

console.log(`\nsketch_refresh_decision.node.test.js: ${n} checks passed`);

"use strict";
// Phase B1B delegation / parity contract (Node, no React). Proves the five Office roof-sketch files are
// now THIN COMPATIBILITY WRAPPERS that delegate to @roofspan/roof-sketch-core: reference-preserving
// export identity + complete export surface + no retained local algorithm. This does NOT retest
// geometry (that is covered by the shared editor_engine suite + the Office behavior suites).
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const Module = require("module");
const babel = require("@babel/core");

// Load an ESM Office wrapper by transforming import/export -> CommonJS, with real node_modules
// resolution so `@roofspan/roof-sketch-core` resolves from the frontend package.
function load(rel) {
  const file = path.resolve(__dirname, rel);
  const { code } = babel.transformFileSync(file, { plugins: ["@babel/plugin-transform-modules-commonjs"] });
  const m = new Module(file, module);
  m.filename = file;
  m.paths = Module._nodeModulePaths(path.dirname(file));
  m._compile(code, file);
  return m.exports;
}
function src(rel) { return fs.readFileSync(path.resolve(__dirname, rel), "utf8"); }

const RS = require("@roofspan/roof-sketch-core");
const Commands = load("../commands.js");
const Snapping = load("../snapping.js");
const Dimensions = load("../edgeDimensions.js");
const Gestures = load("../gestures.js");
const History = load("../historyCore.js");

let n = 0;
function ok(name) { n++; console.log("  \u2713 " + name); }
function ident(obj, key, rsKey, label) {
  assert.strictEqual(typeof RS[rsKey], obj[key] === RS[rsKey] ? typeof RS[rsKey] : "function", "shared export missing: " + rsKey);
  assert.strictEqual(obj[key], RS[rsKey], (label || key) + " must be the SAME reference as shared " + rsKey);
  ok((label || key) + " === shared." + rsKey);
}

// ---- 16/11 complete command export surface + function identity ----
const COMMAND_NAMES = [
  "nid", "vById", "eById", "fById",
  "addVertex", "moveVertex", "moveVertexFinal", "deleteVertex",
  "addEdge", "setEdgeType", "deleteEdge",
  "splitEdge", "splitEdgeSafe",
  "createFacet", "createManualFacet", "deleteFacet",
  "setFacetPitch", "setFacetOrientation", "setFacetLabel",
  "setScale",
  "setConfirmedEdgeLength", "lockEdge", "unlockEdge",
  "placePenetration", "movePenetration", "setPenetrationType", "deletePenetration",
  "setProposalDecision", "setDecisions", "decisionFor",
  "isMeasurementFacetTaken", "setFacetMeasurementLink",
  "isMeasurementEdgeTaken", "setEdgeMeasurementLink",
  "setEditMode",
  "edgeIsProtected", "validateMutation",
  "mergeVertices", "insertExistingVertexIntoEdge", "joinEdges",
];
for (const name of COMMAND_NAMES) {
  assert.strictEqual(typeof Commands[name], "function", "Office commands missing export: " + name);
  assert.strictEqual(Commands[name], RS[name], "commands." + name + " must delegate (identity) to shared");
}
ok("complete Office command surface (" + COMMAND_NAMES.length + " names) present + identical to shared");

// ---- 12 snapping identity ----
ident(Snapping, "modelTolerance", "modelTolerance");
ident(Snapping, "snapTarget", "snapTarget");
assert.deepStrictEqual(Object.keys(Snapping).sort(), ["modelTolerance", "snapTarget"], "snapping wrapper exposes exactly the snap surface");
ok("snapping wrapper surface exact");

// ---- 13 dimension identity ----
ident(Dimensions, "edgeDimension", "edgeDimension");
ident(Dimensions, "formatFeet", "formatFeet");
assert.deepStrictEqual(Object.keys(Dimensions).sort(), ["edgeDimension", "formatFeet"], "dimensions wrapper exposes exactly the dimension surface");
ok("dimensions wrapper surface exact");

// ---- 14 gesture identity ----
ident(Gestures, "candidateFor", "candidateFor");
ident(Gestures, "drawSnap", "drawSnap");
ident(Gestures, "dragSnap", "dragSnap");
ident(Gestures, "applyDrawPoint", "applyDrawPoint");
ident(Gestures, "applyVertexDrop", "applyVertexDrop");

// ---- 15 history alias identity (legacy Office names -> shared history* names) ----
ident(History, "MAX_HISTORY", "MAX_HISTORY", "history.MAX_HISTORY");
ident(History, "makeHistory", "makeHistory", "history.makeHistory");
ident(History, "push", "historyPush", "history.push");
ident(History, "pushFrom", "historyPushFrom", "history.pushFrom");
ident(History, "undo", "historyUndo", "history.undo");
ident(History, "redo", "historyRedo", "history.redo");
ident(History, "canUndo", "historyCanUndo", "history.canUndo");
ident(History, "canRedo", "historyCanRedo", "history.canRedo");
assert.strictEqual(History.MAX_HISTORY, 100, "MAX_HISTORY preserved (100)");
ok("history legacy contract preserved (8 names, MAX_HISTORY=100)");

// ---- 17 no-local-algorithm static check ----
// A wrapper must reference the shared package and must NOT declare local functions or arrow logic.
function stripComments(s) {
  return s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^[ \t]*\/\/.*$/gm, "");
}
const WRAPPERS = ["../commands.js", "../snapping.js", "../edgeDimensions.js", "../gestures.js", "../historyCore.js"];
const FORBIDDEN = [/\bfunction\b/, /=>/, /\bfunction\s+clone\b/, /\bpairKey\b/];
for (const rel of WRAPPERS) {
  const raw = src(rel);
  assert.ok(/@roofspan\/roof-sketch-core/.test(raw), rel + " must import from the shared package");
  const code = stripComments(raw);
  for (const re of FORBIDDEN) {
    assert.ok(!re.test(code), rel + " must not contain a local implementation marker: " + re);
  }
}
ok("all five wrappers are re-export-only (no local algorithm) + reference the shared package");

console.log("\nSHARED DELEGATION / PARITY: all " + n + " assertions passed");

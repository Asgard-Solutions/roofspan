"use strict";
// Generation-based save/dirty + async save-race contracts (Node, no React).
const assert = require("assert");
const path = require("path");
const Module = require("module");
const babel = require("@babel/core");

function load(rel) {
  const file = path.resolve(__dirname, rel);
  const { code } = babel.transformFileSync(file, { plugins: ["@babel/plugin-transform-modules-commonjs"] });
  const m = new Module(file, module);
  m.filename = file; m.paths = Module._nodeModulePaths(path.dirname(file));
  m._compile(code, file);
  return m.exports;
}
const L = load("../saveLifecycle.js");

let n = 0;
const ok = (name) => { n++; console.log("  \u2713 " + name); };

// deferred promise so we can interleave an edit while a "save" is pending
function deferred() { let resolve, reject; const p = new Promise((res, rej) => { resolve = res; reject = rej; }); return { p, resolve, reject }; }

// ---- THE SAVE RACE: edit during in-flight save must NOT be lost ----
(async () => {
  let st = L.initSaveState(3);            // server sketch at version 3
  st = L.markEdited(st);                  // Edit A -> generation 1
  assert.strictEqual(st.editGeneration, 1);
  assert.strictEqual(L.isDirty(st), true); ok("edit makes state dirty");

  const b = L.beginSave(st); st = b.next;  // Save clicked -> freeze generation 1 + expectedVersion 3
  assert.strictEqual(b.snapshotGeneration, 1);
  assert.strictEqual(b.expectedVersion, 3); ok("beginSave freezes snapshot generation + CAS version");

  const req = deferred();                  // request is in flight
  st = L.markEdited(st);                   // Edit B WHILE saving -> generation 2
  assert.strictEqual(st.editGeneration, 2); ok("edit during in-flight save advances generation");

  await Promise.resolve(req.resolve({ document_version: 4 }));
  const server = await req.p;
  st = L.resolveSaveSuccess(st, b.snapshotGeneration, server.document_version);
  assert.strictEqual(st.serverVersion, 4); ok("save success advances server CAS version");
  assert.strictEqual(st.lastPersistedGeneration, 1);
  assert.strictEqual(st.editGeneration, 2);
  assert.strictEqual(L.isDirty(st), true); ok("editor STAYS dirty — Edit B is not masked by Save(A)");
  assert.strictEqual(st.phase, "unsaved"); ok("phase remains unsaved after racing save resolves");
})();

// ---- clean save with no in-flight edit ----
{
  let st = L.initSaveState(1);
  st = L.markEdited(st); st = L.markEdited(st);   // generation 2
  const b = L.beginSave(st); st = b.next;
  st = L.resolveSaveSuccess(st, b.snapshotGeneration, 2);
  assert.strictEqual(L.isDirty(st), false); ok("save with no concurrent edit becomes clean");
  assert.strictEqual(st.phase, "saved"); ok("clean save -> phase saved");
  assert.strictEqual(st.serverVersion, 2); ok("new server version retained for the next save");
}

// ---- failures preserve dirty state (409 / 422 / generic) ----
for (const kind of ["conflict", "validation", "error"]) {
  let st = L.initSaveState(5);
  st = L.markEdited(st);
  const b = L.beginSave(st); st = b.next;
  st = L.resolveSaveFailure(st, kind);
  assert.strictEqual(L.isDirty(st), true, `${kind} stays dirty`);
  assert.strictEqual(st.serverVersion, 5, `${kind} keeps CAS version`);
  const expected = kind === "error" ? "error" : kind;
  assert.strictEqual(st.phase, expected);
  ok(`${kind} failure preserves local (dirty + version), phase=${expected}`);
}

// ---- reload server version adopts clean baseline ----
{
  let st = L.initSaveState(2);
  st = L.markEdited(st);
  st = L.adoptServerVersion(st, 9);
  assert.ok(!L.isDirty(st) && st.serverVersion === 9 && st.phase === "saved"); ok("adoptServerVersion resets to a clean baseline at the server version");
}

console.log("\nROOF SKETCH SAVE LIFECYCLE: all " + n + " assertions passed");

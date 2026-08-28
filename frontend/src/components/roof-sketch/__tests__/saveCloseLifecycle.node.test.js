"use strict";
// Save/close race + true-modal keyboard-gate contracts (Node, no React). Models the editor's authoritative
// ref-backed save controller (exactly what RoofSketchEditor.doSave()/saveAndClose() do synchronously).
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
const K = load("../keyboardGate.js");

let n = 0;
const ok = (name) => { n++; console.log("  \u2713 " + name); };

// Authoritative ref-backed controller mirroring the editor's synchronous save-state control.
function makeController(version) {
  const ref = { s: L.initSaveState(version) };
  const prepared = [];
  return {
    state: () => ref.s,
    edit: () => { ref.s = L.markEdited(ref.s); },
    begin: () => {
      if (!L.canBeginSave(ref.s)) return { ok: false, reason: "already_saving" };  // HARD guard
      const prep = L.prepareSketchSave(ref.s, { edit_mode: "connected_graph" });
      prepared.push(prep);
      ref.s = prep.nextSaveState;                                                    // saving=true SYNC
      return { ok: true, prep };
    },
    resolve: (prep, newVersion) => { ref.s = L.resolveSaveSuccess(ref.s, prep.snapshotGeneration, newVersion); return { ok: true, clean: L.isCleanState(ref.s) }; },
    fail: (prep, kind) => { ref.s = L.resolveSaveFailure(ref.s, kind); return { ok: false, clean: false }; },
    preparedCount: () => prepared.length,
    versions: () => prepared.map((p) => p.expectedVersion),
  };
}

// ---- HARD in-flight guard: second concurrent save impossible ----
{
  const c = makeController(7);
  c.edit();
  const a = c.begin();
  assert.ok(a.ok); ok("first save begins");
  assert.strictEqual(c.state().saving, true); ok("saveRef.current.saving === true SYNCHRONOUSLY after begin");
  const b = c.begin();
  assert.deepStrictEqual(b, { ok: false, reason: "already_saving" }); ok("second save while saving is rejected (already_saving)");
  assert.strictEqual(c.preparedCount(), 1); ok("second save does NOT prepare another request");
  assert.deepStrictEqual(c.versions(), [7]); ok("the CAS version (7) is captured exactly once — never reused concurrently");
  const r = c.resolve(a.prep, 8);
  assert.strictEqual(c.state().saving, false); ok("saveRef resolves to not-saving SYNCHRONOUSLY after success");
  assert.ok(r.clean); ok("clean save with no concurrent edit -> clean=true (safe to close)");
}

// ---- Save(A) + Edit(B): must NOT close; stays dirty ----
{
  const c = makeController(8);
  // seed: editGeneration 4, lastPersisted 3 (one prior clean save)
  c.edit(); c.edit(); c.edit(); const seed = c.begin(); c.resolve(seed.prep, 8); // gen3 persisted, version 8
  c.edit(); // editGeneration 4
  const a = c.begin();
  assert.strictEqual(a.prep.snapshotGeneration, 4); assert.strictEqual(a.prep.expectedVersion, 8); ok("Save(A) freezes snapshotGeneration=4, expectedVersion=8");
  c.edit(); // Edit B -> editGeneration 5 while Save(A) pending
  const res = c.resolve(a.prep, 9);
  const st = c.state();
  assert.strictEqual(st.serverVersion, 9); ok("server document_version advances to 9");
  assert.strictEqual(st.lastPersistedGeneration, 4); ok("lastPersistedGeneration remains generation A (4)");
  assert.strictEqual(st.editGeneration, 5); ok("editGeneration reflects A+B (5)");
  assert.ok(L.isDirty(st)); ok("editor remains dirty after racing save resolves");
  assert.strictEqual(st.phase, "unsaved"); ok("phase = unsaved");
  assert.strictEqual(res.clean, false); ok("doSave returns clean=false -> Save & Close must NOT close");
  const wouldClose = res.ok && res.clean;
  assert.strictEqual(wouldClose, false); ok("Save & Close keeps the editor open (Edit B preserved)");
}

// ---- clean Save & Close ----
{
  const c = makeController(1);
  c.edit();
  const a = c.begin();
  const res = c.resolve(a.prep, 2);
  assert.ok(!L.isDirty(c.state())); ok("clean Save & Close: dirty becomes false");
  assert.strictEqual(res.clean, true); ok("clean Save & Close: doSave returns clean=true (editor may close)");
}

// ---- failures stay dirty and resolve saveRef synchronously ----
for (const kind of ["conflict", "validation", "error"]) {
  const c = makeController(5);
  c.edit();
  const a = c.begin();
  const r = c.fail(a.prep, kind);
  assert.strictEqual(c.state().saving, false); // synchronous
  assert.ok(L.isDirty(c.state()));
  assert.strictEqual(r.clean, false);
  ok(`${kind}: saveRef resolves not-saving synchronously, stays dirty, clean=false`);
}

// ---- close blocked while a normal save is active ----
{
  const c = makeController(3);
  c.edit();
  c.begin();
  assert.strictEqual(L.canBeginSave(c.state()), false); ok("Close/Save & Close cannot start a save while one is active (canBeginSave=false)");
}

// ---- TRUE modal: keyboard gate ----
{
  const meta = (key, shift = false, extra = {}) => K.resolveKey({ closeConfirm: false, closing: false, ctrlOrMeta: true, key, shift, ...extra });
  assert.strictEqual(meta("z"), "undo");
  assert.strictEqual(meta("y"), "redo");
  assert.strictEqual(meta("z", true), "redo");
  assert.strictEqual(K.resolveKey({ ctrlOrMeta: false, key: "Delete" }), "delete");
  assert.strictEqual(K.resolveKey({ ctrlOrMeta: false, key: "Backspace" }), "delete"); ok("normal shortcuts map to undo/redo/delete when no modal");

  const modal = (key, shift = false, closing = false) => K.resolveKey({ closeConfirm: true, closing, ctrlOrMeta: true, key, shift });
  assert.strictEqual(modal("z"), "none"); ok("modal blocks Ctrl+Z mutation");
  assert.strictEqual(modal("y"), "none"); ok("modal blocks Ctrl+Y mutation");
  assert.strictEqual(modal("z", true), "none"); ok("modal blocks Ctrl+Shift+Z mutation");
  assert.strictEqual(K.resolveKey({ closeConfirm: true, closing: false, ctrlOrMeta: false, key: "Delete" }), "none"); ok("modal blocks Delete mutation");
  assert.strictEqual(K.resolveKey({ closeConfirm: true, closing: false, ctrlOrMeta: false, key: "Backspace" }), "none"); ok("modal blocks Backspace mutation");
  assert.strictEqual(K.resolveKey({ closeConfirm: true, closing: false, key: "Escape" }), "dismiss-modal"); ok("Escape dismisses the modal (no geometry mutation)");
  assert.strictEqual(K.resolveKey({ closeConfirm: true, closing: true, key: "Escape" }), "none"); ok("Escape ignored while Save & Close is running");
}

console.log("\nROOF SKETCH SAVE/CLOSE RACE: all " + n + " assertions passed");

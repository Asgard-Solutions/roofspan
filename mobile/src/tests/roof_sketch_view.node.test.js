"use strict";
// Pure viewport contracts (Node). Viewport transforms must never mutate the sketch document JSON.
const assert = require("assert");
const V = require("../roofSketchView");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

// round trip screen<->model
{
  const view = { scale: 2, tx: 30, ty: -10 };
  const model = [4, 7];
  const screen = V.modelToScreen(model, view);
  assert.deepStrictEqual(screen, [4 * 2 + 30, 7 * 2 - 10]); ok("modelToScreen applies scale + translate");
  const back = V.screenToModel(screen, view);
  assert.ok(Math.abs(back[0] - 4) < 1e-9 && Math.abs(back[1] - 7) < 1e-9); ok("screen->model->screen round trip is stable");
}

// zoom around focal keeps the focal model point fixed on screen
{
  const view = { scale: 1, tx: 0, ty: 0 };
  const focal = [100, 100];
  const before = V.screenToModel(focal, view);
  const zoomed = V.zoomAround(view, focal, 2);
  assert.strictEqual(zoomed.scale, 2); ok("zoomAround multiplies scale by factor");
  const afterScreen = V.modelToScreen(before, zoomed);
  assert.ok(Math.abs(afterScreen[0] - focal[0]) < 1e-6 && Math.abs(afterScreen[1] - focal[1]) < 1e-6); ok("zoomAround keeps the focal model point fixed on screen");
}

// pan
{
  const view = { scale: 1.5, tx: 5, ty: 5 };
  const p = V.pan(view, 10, -4);
  assert.deepStrictEqual([p.scale, p.tx, p.ty], [1.5, 15, 1]); ok("pan translates the view, scale unchanged");
}

// clamp zoom
{
  assert.strictEqual(V.clampScale(1000, 0.05, 40), 40); ok("zoom clamped to max");
  assert.strictEqual(V.clampScale(0.0001, 0.05, 40), 0.05); ok("zoom clamped to min");
  const z = V.zoomAround({ scale: 30, tx: 0, ty: 0 }, [0, 0], 5, { min: 0.05, max: 40 });
  assert.strictEqual(z.scale, 40); ok("zoomAround respects the clamp");
}

// two-touch helpers
{
  assert.deepStrictEqual(V.touchMidpoint([0, 0], [10, 20]), [5, 10]); ok("touchMidpoint averages two touches");
  assert.strictEqual(V.touchDistance([0, 0], [3, 4]), 5); ok("touchDistance 3-4-5 = 5");
}

// fit to viewport
{
  const pts = [[0, 0], [100, 0], [100, 50], [0, 50]];
  const fit = V.fitToViewport(pts, { width: 300, height: 300, padding: 20 });
  // every point must land inside the canvas with padding
  for (const p of pts) {
    const s = V.modelToScreen(p, fit);
    assert.ok(s[0] >= 20 - 1e-6 && s[0] <= 300 - 20 + 1e-6, "x within padded canvas");
    assert.ok(s[1] >= 20 - 1e-6 && s[1] <= 300 - 20 + 1e-6, "y within padded canvas");
  }
  ok("fitToViewport fits all points inside the padded canvas");
  const empty = V.fitToViewport([], { width: 200, height: 120 });
  assert.deepStrictEqual([empty.scale, empty.tx, empty.ty], [1, 100, 60]); ok("empty document => centered default view");
}

// viewport actions never touch the document JSON
{
  const doc = { vertices: [{ id: "v1", x: 3, y: 4 }], edges: [], facets: [] };
  const snapshot = JSON.stringify(doc);
  let view = { scale: 1, tx: 0, ty: 0 };
  view = V.pan(view, 5, 5);
  view = V.zoomAround(view, [10, 10], 2);
  V.modelToScreen([3, 4], view);
  V.screenToModel([10, 10], view);
  assert.strictEqual(JSON.stringify(doc), snapshot); ok("pan/zoom/convert leave the sketch document JSON unchanged");
}

console.log("\nFIELD ROOF SKETCH VIEWPORT: all " + n + " assertions passed");

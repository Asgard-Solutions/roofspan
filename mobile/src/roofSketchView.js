"use strict";
// Pure viewport math for the Field canvas (Node-testable; NO React/RN). Keeps pan/zoom OUT of the
// sketch document — a view transform never mutates canonical model coordinates.
//   view = { scale, tx, ty };  screen = model * scale + t ;  model = (screen - t) / scale

function clampScale(scale, min = 0.05, max = 40) {
  const s = Number(scale) || 0;
  return Math.max(min, Math.min(max, s));
}

function modelToScreen(pt, view) {
  return [pt[0] * view.scale + view.tx, pt[1] * view.scale + view.ty];
}

function screenToModel(pt, view) {
  return [(pt[0] - view.tx) / view.scale, (pt[1] - view.ty) / view.scale];
}

function pan(view, dxScreen, dyScreen) {
  return { scale: view.scale, tx: view.tx + dxScreen, ty: view.ty + dyScreen };
}

// Zoom by `factor` while keeping the model point under `focalScreen` fixed on screen.
function zoomAround(view, focalScreen, factor, { min = 0.05, max = 40 } = {}) {
  const ns = clampScale(view.scale * factor, min, max);
  const r = ns / view.scale;
  return {
    scale: ns,
    tx: focalScreen[0] - (focalScreen[0] - view.tx) * r,
    ty: focalScreen[1] - (focalScreen[1] - view.ty) * r,
  };
}

function touchMidpoint(t1, t2) {
  return [(t1[0] + t2[0]) / 2, (t1[1] + t2[1]) / 2];
}

function touchDistance(t1, t2) {
  return Math.hypot(t1[0] - t2[0], t1[1] - t2[1]);
}

// Fit the model-space points into the canvas with padding. Empty => a sensible centered view.
function fitToViewport(points, { width, height, padding = 24, min = 0.05, max = 40 } = {}) {
  const pts = (points || []).filter((p) => p && isFinite(p[0]) && isFinite(p[1]));
  if (pts.length === 0) return { scale: 1, tx: width / 2, ty: height / 2 };
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of pts) { minX = Math.min(minX, p[0]); minY = Math.min(minY, p[1]); maxX = Math.max(maxX, p[0]); maxY = Math.max(maxY, p[1]); }
  const w = Math.max(maxX - minX, 1e-6), h = Math.max(maxY - minY, 1e-6);
  const scale = clampScale(Math.min((width - 2 * padding) / w, (height - 2 * padding) / h), min, max);
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  return { scale, tx: width / 2 - cx * scale, ty: height / 2 - cy * scale };
}

// All model vertex points of a document (used to fit the view).
function documentPoints(doc) {
  return (doc && doc.vertices ? doc.vertices : []).map((v) => [Number(v.x), Number(v.y)]);
}

module.exports = {
  clampScale, modelToScreen, screenToModel, pan, zoomAround,
  touchMidpoint, touchDistance, fitToViewport, documentPoints,
};

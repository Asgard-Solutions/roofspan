"use strict";
// Pure geometry math. No I/O. Shared identically by Office and Field.

function distance(a, b) {
  const dx = Number(a[0]) - Number(b[0]);
  const dy = Number(a[1]) - Number(b[1]);
  return Math.sqrt(dx * dx + dy * dy);
}

// Shoelace polygon area (absolute). Points: [[x,y], ...] in order.
function polygonArea(points) {
  if (!Array.isArray(points) || points.length < 3) return 0;
  let sum = 0;
  for (let i = 0; i < points.length; i++) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % points.length];
    sum += Number(x1) * Number(y2) - Number(x2) * Number(y1);
  }
  return Math.abs(sum) / 2;
}

// True sloped roof area from a plan (footprint) area and pitch rise over a fixed run of 12.
function pitchAdjustedArea(planArea, pitchRise) {
  const rise = Number(pitchRise) || 0;
  return Number(planArea) * Math.sqrt(1 + Math.pow(rise / 12, 2));
}

// Establish drawing scale from a known real-world dimension on the canvas.
function calibrateScale({ canvasDistance, realFeet, method } = {}) {
  const cd = Number(canvasDistance);
  const rf = Number(realFeet);
  if (!(cd > 0) || !(rf > 0)) {
    return { resolved: false, feetPerUnit: null, feet_per_unit: null, method: method || "structure_calibration" };
  }
  const feetPerUnit = rf / cd;
  return { resolved: true, feetPerUnit, feet_per_unit: feetPerUnit, method: method || "structure_calibration" };
}

// Do open segments (p1,p2) and (p3,p4) properly cross (excluding shared endpoints)?
function segmentsCross(p1, p2, p3, p4) {
  function orient(a, b, c) {
    const val = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1]);
    if (Math.abs(val) < 1e-9) return 0;
    return val > 0 ? 1 : 2;
  }
  const same = (a, b) => Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9;
  if (same(p1, p3) || same(p1, p4) || same(p2, p3) || same(p2, p4)) return false; // shared vertex, not a crossing
  const o1 = orient(p1, p2, p3), o2 = orient(p1, p2, p4), o3 = orient(p3, p4, p1), o4 = orient(p3, p4, p2);
  return o1 !== o2 && o3 !== o4;
}

// Project point p onto segment a-b. Returns the clamped point, parametric t in [0,1] and the distance.
// t=0 => endpoint a, t=1 => endpoint b, 0<t<1 => interior. Zero-length segments are handled safely.
function projectPointToSegment(p, a, b) {
  const ax = a[0], ay = a[1], bx = b[0], by = b[1];
  const dx = bx - ax, dy = by - ay;
  const len2 = dx * dx + dy * dy;
  let t = len2 === 0 ? 0 : ((p[0] - ax) * dx + (p[1] - ay) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  const px = ax + t * dx, py = ay + t * dy;
  const ddx = p[0] - px, ddy = p[1] - py;
  return { point: [px, py], t, distance: Math.sqrt(ddx * ddx + ddy * ddy) };
}

// Single source of truth for a graph edge's real-world length. null when scale is unresolved. Both
// dimension labels and deriveProposals must derive edge LF from THIS so the two can never disagree.
function edgeGeometryLengthFeet(doc, edge) {
  if (!doc || !edge || !doc.scale || doc.scale.resolved !== true || doc.scale.feetPerUnit == null) return null;
  const vs = doc.vertices || [];
  const a = vs.find((v) => v.id === edge.v1);
  const b = vs.find((v) => v.id === edge.v2);
  if (!a || !b) return null;
  return distance([a.x, a.y], [b.x, b.y]) * Number(doc.scale.feetPerUnit);
}

module.exports = { distance, polygonArea, pitchAdjustedArea, calibrateScale, segmentsCross, projectPointToSegment, edgeGeometryLengthFeet };

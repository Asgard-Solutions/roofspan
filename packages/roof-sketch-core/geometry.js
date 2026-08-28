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

module.exports = { distance, polygonArea, pitchAdjustedArea, calibrateScale, segmentsCross };

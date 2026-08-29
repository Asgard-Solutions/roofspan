"use strict";
// Pure snap-target selection for the Roof Sketch canvas (Node-testable, CommonJS). Tolerance is
// SCREEN-space and converted to model units by the caller (modelTol = snapPixels / view.k) so the
// effective snap zone is the same on screen at every zoom. Deterministic priority:
// existing vertex/endpoint > edge interior > free point. Never snaps to infinite-line extensions
// (projection stays on the actual segment). Ported verbatim from the approved Office snapping.js.
const { projectPointToSegment } = require("./geometry");

function modelTolerance(snapPixels, viewK) {
  return snapPixels / (viewK || 1);
}

function snapTarget(doc, point, modelTol, { excludeVertexId = null, eligibleEdge = () => true } = {}) {
  const vs = doc.vertices || [];
  // 1) nearest vertex within tolerance
  let bestV = null;
  for (const v of vs) {
    if (v.id === excludeVertexId) continue;
    const dd = Math.hypot(point[0] - v.x, point[1] - v.y);
    if (dd <= modelTol && (!bestV || dd < bestV.distance)) bestV = { type: "vertex", vertexId: v.id, point: [v.x, v.y], distance: dd };
  }
  if (bestV) return bestV;
  // 2) nearest eligible edge-interior projection within tolerance
  let bestE = null;
  for (const e of doc.edges || []) {
    if (!eligibleEdge(e)) continue;
    const a = vs.find((v) => v.id === e.v1), b = vs.find((v) => v.id === e.v2);
    if (!a || !b) continue;
    const pr = projectPointToSegment(point, [a.x, a.y], [b.x, b.y]);
    if (pr.distance <= modelTol && (!bestE || pr.distance < bestE.distance)) bestE = { type: "edge", edgeId: e.id, point: pr.point, t: pr.t, distance: pr.distance };
  }
  if (bestE) return bestE;
  // 3) free point
  return { type: "free", point: [point[0], point[1]], distance: 0 };
}

module.exports = { modelTolerance, snapTarget };

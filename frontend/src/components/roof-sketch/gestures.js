// Pure gesture resolution for the live canvas (Node-testable). The React canvas only coordinates DOM
// pointer events and rendering; ALL topology math lives here (delegating to snapping.js + commands.js).
// A gesture is resolved to a single candidate, then applied as ONE atomic document mutation so the
// caller performs exactly one history/edit commit per pointer gesture.
import { snapTarget } from "./snapping";
import { edgeIsProtected, splitEdgeSafe, mergeVertices, moveVertex, moveVertexFinal, addVertex, addEdge, insertExistingVertexIntoEdge, eById } from "./commands";

// Classify a raw snapTarget result. A protected edge in proximity becomes a BLOCKED candidate (it never
// silently falls through to a free-point placement that would leave coincident, unconnected geometry).
export function candidateFor(doc, snap) {
  if (snap.type === "edge") {
    const e = eById(doc, snap.edgeId);
    if (edgeIsProtected(e)) return { type: "blocked", edgeId: snap.edgeId, point: snap.point };
  }
  return snap;
}

// Snap for the Draw tool. In manual_polygon we snap to vertices/free only (never split an edge).
export function drawSnap(doc, point, modelTol, { manual = false } = {}) {
  const snap = snapTarget(doc, point, modelTol, { eligibleEdge: manual ? () => false : () => true });
  return candidateFor(doc, snap);
}

// Snap for dragging an existing vertex: never snap to itself, and its own incident edges are not
// eligible split targets.
export function dragSnap(doc, draggedVertexId, point, modelTol) {
  const snap = snapTarget(doc, point, modelTol, {
    excludeVertexId: draggedVertexId,
    eligibleEdge: (e) => e.v1 !== draggedVertexId && e.v2 !== draggedVertexId,
  });
  return candidateFor(doc, snap);
}

// Apply a connected-graph Draw point. Returns { ok, doc, vertexId, reason? }. Chains an edge from the
// previous draw vertex when present. Blocked (protected-edge) candidates make no change.
export function applyDrawPoint(doc, candidate, prevVertexId) {
  if (candidate.type === "blocked") return { ok: false, reason: "edge_protected", doc };
  let nd = doc, vid;
  if (candidate.type === "vertex") {
    vid = candidate.vertexId;
  } else if (candidate.type === "edge") {
    const r = splitEdgeSafe(doc, candidate.edgeId, candidate.point[0], candidate.point[1]);
    if (!r.ok) return { ok: false, reason: r.reason, doc };
    nd = r.doc; vid = r.vertexId;
  } else {
    const a = addVertex(nd, candidate.point[0], candidate.point[1]); nd = a.doc; vid = a.vertexId;
  }
  if (prevVertexId && prevVertexId !== vid) { const b = addEdge(nd, prevVertexId, vid); if (b.doc) nd = b.doc; }
  return { ok: true, doc: nd, vertexId: vid };
}

// Apply a vertex-drop gesture at pointer-up. Returns { ok, doc, reason? } from a SINGLE command:
//   vertex candidate  -> mergeVertices (drag onto another vertex)
//   edge candidate    -> insertExistingVertexIntoEdge (split + insert, reusing the dragged vertex)
//   blocked candidate -> refused (protected edge)
//   free candidate    -> plain moveVertex reposition
// A failed topology op returns the ORIGINAL doc unchanged.
export function applyVertexDrop(doc, draggedVertexId, candidate) {
  if (candidate.type === "vertex") return mergeVertices(doc, draggedVertexId, candidate.vertexId);
  if (candidate.type === "edge") return insertExistingVertexIntoEdge(doc, draggedVertexId, candidate.edgeId, candidate.point[0], candidate.point[1]);
  if (candidate.type === "blocked") return { ok: false, reason: "edge_protected", doc };
  return { ok: true, doc: moveVertexFinal(doc, draggedVertexId, candidate.point[0], candidate.point[1]) };
}

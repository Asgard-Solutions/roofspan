"use strict";
// Phase B1A direct shared editor-engine contracts. Imports ONLY from the package public entry point
// (require("..")) — never the Office source modules — proving the future Field editor can consume the
// shared engine. Deterministic, no React/DOM/RN.
const assert = require("assert");
const RS = require("..");

const counts = {};
let section = "";
function begin(name) { section = name; counts[section] = counts[section] || { passed: 0, failed: 0 }; }
function ok(name) { counts[section].passed++; console.log("  \u2713 [" + section + "] " + name); }
function check(cond, name) { if (cond) ok(name); else { counts[section].failed++; console.log("  \u2717 [" + section + "] " + name); throw new Error("FAILED: " + name); } }

// ---- builders ----
function rect() {
  // single connected facet: rectangle 10 x 8
  const d = RS.createSketchDocument({ structureId: "s1" });
  d.vertices = [
    { id: "v1", x: 0, y: 0 }, { id: "v2", x: 10, y: 0 },
    { id: "v3", x: 10, y: 8 }, { id: "v4", x: 0, y: 8 },
  ];
  d.edges = [
    { id: "e1", v1: "v1", v2: "v2", type: "eave" },
    { id: "e2", v1: "v2", v2: "v3", type: "rake" },
    { id: "e3", v1: "v3", v2: "v4", type: "eave" },
    { id: "e4", v1: "v4", v2: "v1", type: "rake" },
  ];
  d.facets = [{ id: "f1", label: "F1", edgeIds: ["e1", "e2", "e3", "e4"], vertexIds: [], pitch_rise: 6 }];
  return d;
}
function triangle() {
  const d = RS.createSketchDocument({ structureId: "s1" });
  d.vertices = [{ id: "v1", x: 0, y: 0 }, { id: "v2", x: 10, y: 0 }, { id: "v3", x: 5, y: 8 }];
  d.edges = [
    { id: "t1", v1: "v1", v2: "v2", type: "unclassified" },
    { id: "t2", v1: "v2", v2: "v3", type: "unclassified" },
    { id: "t3", v1: "v3", v2: "v1", type: "unclassified" },
  ];
  d.facets = [{ id: "f1", label: "F1", edgeIds: ["t1", "t2", "t3"], vertexIds: [], pitch_rise: 0 }];
  return d;
}

// ==================== 16 — EDITOR COMMAND CONTRACTS ====================
begin("editor-command");
{
  const empty = RS.createSketchDocument({ structureId: "s1" });
  const a = RS.addVertex(empty, 3, 4);
  check(a.doc.vertices.length === 1 && a.vertexId, "addVertex adds a vertex and returns id");
  check(empty.vertices.length === 0, "addVertex does not mutate input (pure)");

  const mv = RS.moveVertex(a.doc, a.vertexId, 7, 9);
  check(RS.vById(mv, a.vertexId).x === 7 && RS.vById(mv, a.vertexId).y === 9, "moveVertex repositions");

  const d0 = rect();
  d0.proposal_decisions = [{ target_type: "edge", target_id: "e1", metric: "length_ft" }];
  const mvf = RS.moveVertexFinal(d0, "v1", 1, 1);
  check(RS.vById(mvf, "v1").x === 1, "moveVertexFinal repositions");
  check(!mvf.proposal_decisions.some((x) => x.target_id === "e1"), "moveVertexFinal drops decisions for incident edges");

  const ae = RS.addEdge(rect(), "v1", "v3", "ridge");
  check(ae.doc && ae.edgeId, "addEdge creates an edge");
  const dup = RS.addEdge(rect(), "v1", "v2", "ridge");
  check(dup === rect().length || dup.edges === undefined || !dup.edgeId, "addEdge refuses an existing unordered duplicate (no-op)");

  const st = RS.setEdgeType(rect(), "e1", "ridge");
  check(RS.eById(st, "e1").type === "ridge", "setEdgeType updates type");

  const cf = RS.createFacet(rect(), ["e1", "e2"]);
  check(cf.facetId && cf.doc.facets.length === 2, "createFacet appends a facet");
  const cmf = RS.createManualFacet(rect(), ["v1", "v2", "v3"]);
  check(cmf.doc.facets[cmf.doc.facets.length - 1].vertexIds.length === 3, "createManualFacet stores vertexIds");

  const sp = RS.setFacetPitch(rect(), "f1", 8);
  check(RS.fById(sp, "f1").pitch_rise === 8, "setFacetPitch updates rise");
  const so = RS.setFacetOrientation(rect(), "f1", "N");
  check(RS.fById(so, "f1").orientation === "N", "setFacetOrientation updates");
  const sl = RS.setFacetLabel(rect(), "f1", "Main");
  check(RS.fById(sl, "f1").label === "Main", "setFacetLabel updates");

  const sc = RS.setScale(rect(), { edgeId: "e1", realFeet: 20 });
  check(sc.scale.resolved === true && sc.scale.feetPerUnit === 2, "setScale calibrates from edge (20ft / 10u = 2)");

  const cel = RS.setConfirmedEdgeLength(rect(), "e1", 42);
  check(RS.eById(cel, "e1").confirmed_length_ft === 42, "setConfirmedEdgeLength sets value");
  const cel0 = RS.setConfirmedEdgeLength(cel, "e1", "");
  check(RS.eById(cel0, "e1").confirmed_length_ft === null, "setConfirmedEdgeLength clears on empty");

  const lk = RS.lockEdge(rect(), "e1");
  check(RS.eById(lk, "e1").locked === true, "lockEdge sets locked");
  const ulk = RS.unlockEdge(lk, "e1");
  check(RS.eById(ulk, "e1").locked === false, "unlockEdge clears locked");

  const pp = RS.placePenetration(rect(), 5, 5);
  check(pp.penetrationId && pp.doc.penetrations.length === 1, "placePenetration adds one");
  const mp = RS.movePenetration(pp.doc, pp.penetrationId, 6, 7);
  check(mp.penetrations[0].x === 6 && mp.penetrations[0].y === 7, "movePenetration repositions");
  const spt = RS.setPenetrationType(pp.doc, pp.penetrationId, "skylight");
  check(spt.penetrations[0].pen_type === "skylight", "setPenetrationType updates");
  const dp = RS.deletePenetration(pp.doc, pp.penetrationId);
  check(dp.penetrations.length === 0, "deletePenetration removes");

  const em = RS.setEditMode(rect(), "manual_polygon");
  check(em.edit_mode === "manual_polygon", "setEditMode switches mode (normalized)");

  const dv = RS.deleteVertex(rect(), "v1");
  check(!RS.vById(dv, "v1") && !dv.edges.some((e) => e.v1 === "v1" || e.v2 === "v1"), "deleteVertex removes vertex + incident edges");
  const de = RS.deleteEdge(rect(), "e1");
  check(!RS.eById(de, "e1") && !de.facets.some((f) => (f.edgeIds || []).includes("e1")), "deleteEdge removes edge + drops facet ref");
}

// ---- proposal decision commands ----
begin("proposal-decisions");
{
  const d1 = RS.setProposalDecision(rect(), { targetType: "facet", targetId: "f1", metric: "area_sqft", decision: "pending_accept", value: 100 });
  const dec = RS.decisionFor(d1, "facet", "f1", "area_sqft");
  check(dec && dec.decision === "pending_accept" && dec.value === 100, "setProposalDecision + decisionFor round-trip");
  const d2 = RS.setDecisions(rect(), [{ target_type: "edge", target_id: "e1", metric: "length_ft", decision: "keep_current" }]);
  check(d2.proposal_decisions.length === 1, "setDecisions replaces the array");
}

// ==================== 17 — MAPPING COMMAND CONTRACTS ====================
begin("mapping-command");
{
  const twoFacets = rect();
  twoFacets.facets = [
    { id: "f1", edgeIds: ["e1", "e2", "e3", "e4"], vertexIds: [] },
    { id: "f2", edgeIds: ["e1", "e2", "e3", "e4"], vertexIds: [] },
  ];
  const m1 = RS.setFacetMeasurementLink(twoFacets, "f1", "MF1");
  check(RS.fById(m1, "f1").measurement_facet_id === "MF1", "setFacetMeasurementLink links facet");
  const taken = RS.isMeasurementFacetTaken(m1, "MF1");
  check(taken === true, "isMeasurementFacetTaken detects usage");
  const m2 = RS.setFacetMeasurementLink(m1, "f2", "MF1");
  check(RS.fById(m2, "f2").measurement_facet_id == null && m2 === m1, "facet one-to-one: linking a used MF is refused (no-op)");
  const m3 = RS.setFacetMeasurementLink(m1, "f1", null);
  check(RS.fById(m3, "f1").measurement_facet_id === null, "unlinking a facet is always allowed");

  const em1 = RS.setEdgeMeasurementLink(rect(), "e1", "ME1");
  check(RS.eById(em1, "e1").measurement_edge_id === "ME1" && RS.eById(em1, "e1").relational_edge_id === "ME1", "setEdgeMeasurementLink keeps measurement_edge_id + relational_edge_id coherent");
  check(RS.isMeasurementEdgeTaken(em1, "ME1") === true, "isMeasurementEdgeTaken detects usage");
  const em2 = RS.setEdgeMeasurementLink(em1, "e2", "ME1");
  check(RS.eById(em2, "e2").measurement_edge_id == null && em2 === em1, "edge one-to-one: linking a used ME is refused (no-op)");
}

// ==================== 18 — SAFE SPLIT CONTRACTS ====================
begin("safe-split");
{
  const r = RS.splitEdgeSafe(rect(), "e1", 5, 3);
  check(r.ok, "splitEdgeSafe succeeds on a plain edge");
  check(!RS.eById(r.doc, "e1"), "original edge removed");
  check(r.edgeIds.length === 2 && r.edgeIds.every((id) => RS.eById(r.doc, id)), "two child edges created");
  const nv = RS.vById(r.doc, r.vertexId);
  check(Math.abs(nv.y - 0) < 1e-9 && nv.x === 5, "split point projected onto the segment (y clamped to 0)");
  const f = RS.fById(r.doc, "f1");
  check(f.edgeIds.length === 5 && f.edgeIds.includes(r.edgeIds[0]) && f.edgeIds.includes(r.edgeIds[1]), "facet boundary updated with both children");

  const prot = RS.lockEdge(rect(), "e1");
  const rp = RS.splitEdgeSafe(prot, "e1", 5, 3);
  check(!rp.ok && rp.reason === "edge_protected" && rp.doc === prot, "protected (locked) edge rejected, original returned");

  const rn = RS.splitEdgeSafe(rect(), "e1", 0, 0);
  check(!rn.ok && rn.reason === "endpoint_reuse" && rn.vertexId === "v1", "near-endpoint click reuses the endpoint instead of a zero-length child");

  const manual = RS.setEditMode(rect(), "manual_polygon");
  const rm = RS.splitEdgeSafe(manual, "e1", 5, 3);
  check(!rm.ok && rm.reason === "connected_graph_required", "manual_polygon rejected");
}

// shared-facet split
begin("safe-split-shared");
{
  // two facets sharing ridge e3
  const d = RS.createSketchDocument({ structureId: "s1" });
  d.vertices = [
    { id: "v1", x: 0, y: 0 }, { id: "v2", x: 10, y: 0 }, { id: "v3", x: 10, y: 8 }, { id: "v4", x: 0, y: 8 },
    { id: "v5", x: 0, y: 16 }, { id: "v6", x: 10, y: 16 },
  ];
  d.edges = [
    { id: "e1", v1: "v1", v2: "v2", type: "eave" }, { id: "e2", v1: "v2", v2: "v3", type: "rake" },
    { id: "e3", v1: "v3", v2: "v4", type: "ridge" }, { id: "e4", v1: "v4", v2: "v1", type: "rake" },
    { id: "e5", v1: "v4", v2: "v5", type: "rake" }, { id: "e6", v1: "v5", v2: "v6", type: "eave" },
    { id: "e7", v1: "v6", v2: "v3", type: "rake" },
  ];
  d.facets = [
    { id: "f1", edgeIds: ["e1", "e2", "e3", "e4"], vertexIds: [] },
    { id: "f2", edgeIds: ["e3", "e5", "e6", "e7"], vertexIds: [] },
  ];
  const r = RS.splitEdgeSafe(d, "e3", 5, 8);
  check(r.ok, "shared edge split succeeds");
  check(RS.fById(r.doc, "f1").edgeIds.length === 5 && RS.fById(r.doc, "f2").edgeIds.length === 5, "BOTH shared facets' boundaries updated");
  check(RS.validateSketch(r.doc).valid, "result validates");
}

// ==================== 19 — MERGE CONTRACTS ====================
begin("merge");
{
  // rectangle: merge v4 onto v1 -> triangle (e4 self-loop dropped)
  const d0 = rect();
  d0.proposal_decisions = [
    { target_type: "edge", target_id: "e4", metric: "length_ft" }, // removed edge
    { target_type: "edge", target_id: "e3", metric: "length_ft" }, // rewired (incident to v4)
    { target_type: "edge", target_id: "e2", metric: "length_ft" }, // untouched
    { target_type: "facet", target_id: "f1", metric: "area_sqft" }, // relational-ish, preserved
  ];
  const r = RS.mergeVertices(d0, "v4", "v1");
  check(r.ok, "adjacent rectangle merge is valid (produces a triangle)");
  check(!RS.vById(r.doc, "v4"), "moving vertex removed");
  check(!r.doc.edges.some((e) => e.v1 === e.v2), "self-loop edge removed");
  check(!RS.fById(r.doc, "f1").edgeIds.some((id) => id === "e4"), "self-loop removed from facet.edgeIds");
  check(RS.fById(r.doc, "f1").edgeIds.length === 3, "facet is now a triangle (3 edges)");
  check(RS.fById(r.doc, "f1").vertexIds.length === 0, "facet vertexIds cleared");
  check(!r.doc.proposal_decisions.some((x) => x.target_id === "e4"), "removed-edge decision cleared");
  check(!r.doc.proposal_decisions.some((x) => x.target_id === "e3"), "rewired-edge decision cleared");
  check(r.doc.proposal_decisions.some((x) => x.target_id === "e2"), "non-incident edge decision preserved");
  check(r.doc.proposal_decisions.some((x) => x.target_id === "f1"), "relational facet decision preserved");
  check(RS.validateSketch(r.doc).valid, "merged triangle validates");

  // protected self-loop rejected — all four protection kinds on e4 (v4-v1 collapses when v4->v1)
  const kinds = [
    ["locked", (d) => RS.lockEdge(d, "e4")],
    ["confirmed", (d) => RS.setConfirmedEdgeLength(d, "e4", 12)],
    ["mapped", (d) => RS.setEdgeMeasurementLink(d, "e4", "ME9")],
    ["relational", (d) => { const c = JSON.parse(JSON.stringify(rect())); c.edges = c.edges.map((e) => e.id === "e4" ? { ...e, relational_edge_id: "RE9" } : e); return c; }],
  ];
  for (const [label, mut] of kinds) {
    const dd = mut(rect());
    const rr = RS.mergeVertices(dd, "v4", "v1");
    check(!rr.ok && rr.reason === "protected_edge_collapse" && rr.doc === dd, "protected self-loop rejected (" + label + ")");
  }

  // triangle degeneracy rejected via the mutation gate (merge collapses to <3 edges)
  const tri = triangle();
  const rt = RS.mergeVertices(tri, "v2", "v1");
  check(!rt.ok && rt.doc === tri, "degenerate triangle merge rejected, original document returned");

  const same = RS.mergeVertices(rect(), "v1", "v1");
  check(!same.ok && same.reason === "same_vertex", "merging a vertex onto itself rejected");
  const manual = RS.setEditMode(rect(), "manual_polygon");
  const rmm = RS.mergeVertices(manual, "v4", "v1");
  check(!rmm.ok && rmm.reason === "connected_graph_required", "merge rejected in manual_polygon");
}

// ==================== 20 — INSERT CONTRACTS ====================
begin("insert");
{
  // rectangle + free vertex v5 to insert into edge e1
  function withFree() { const d = rect(); d.vertices = [...d.vertices, { id: "v5", x: 5, y: 3 }]; return d; }
  const base = withFree();
  base.proposal_decisions = [
    { target_type: "edge", target_id: "e1", metric: "length_ft" },
    { target_type: "edge", target_id: "e2", metric: "length_ft" },
  ];
  const r = RS.insertExistingVertexIntoEdge(base, "v5", "e1", 5, 3);
  check(r.ok, "existing vertex inserted into edge");
  check(r.vertexId === "v5", "same dragged vertex id reused");
  const v5 = RS.vById(r.doc, "v5");
  check(v5.x === 5 && Math.abs(v5.y) < 1e-9, "vertex projected onto the target segment");
  check(!RS.eById(r.doc, "e1") && r.edgeIds.length === 2, "target edge replaced with two child edges");
  check(RS.fById(r.doc, "f1").edgeIds.length === 5, "affected facet loop rewritten");
  check(!r.doc.proposal_decisions.some((x) => x.target_id === "e1"), "incident/target graph decision invalidated");
  check(r.doc.proposal_decisions.some((x) => x.target_id === "e2"), "unrelated decision preserved");
  check(RS.validateSketch(r.doc).valid, "insert result validates");

  // protected target rejected
  const prot = RS.lockEdge(withFree(), "e1");
  const rp = RS.insertExistingVertexIntoEdge(prot, "v5", "e1", 5, 3);
  check(!rp.ok && rp.reason === "edge_protected" && rp.doc === prot, "protected target rejected, original returned");

  // duplicate A-V rejected
  const dupA = withFree(); dupA.edges = [...dupA.edges, { id: "ex", v1: "v1", v2: "v5", type: "unclassified" }];
  const rda = RS.insertExistingVertexIntoEdge(dupA, "v5", "e1", 5, 3);
  check(!rda.ok && rda.reason === "duplicate_edge_creation", "existing A-V duplicate rejected");
  // duplicate V-B rejected
  const dupB = withFree(); dupB.edges = [...dupB.edges, { id: "ex", v1: "v5", v2: "v2", type: "unclassified" }];
  const rdb = RS.insertExistingVertexIntoEdge(dupB, "v5", "e1", 5, 3);
  check(!rdb.ok && rdb.reason === "duplicate_edge_creation", "existing V-B duplicate rejected");

  // vertex already on the edge rejected
  const ve = RS.insertExistingVertexIntoEdge(withFree(), "v1", "e1", 5, 3);
  check(!ve.ok && ve.reason === "vertex_on_edge", "a vertex already on the edge is rejected");
}

// ==================== 21 — JOIN CONTRACTS ====================
begin("join");
{
  // split e1 into e1a (v1-mid) + e1b (mid-v2), then rejoin
  function split1(typeA, typeB) {
    const d = rect();
    const mid = { id: "vm", x: 5, y: 0 };
    d.vertices = [...d.vertices, mid];
    d.edges = d.edges.filter((e) => e.id !== "e1").concat([
      { id: "e1a", v1: "v1", v2: "vm", type: typeA },
      { id: "e1b", v1: "vm", v2: "v2", type: typeB },
    ]);
    d.facets = [{ id: "f1", edgeIds: ["e1a", "e1b", "e2", "e3", "e4"], vertexIds: [] }];
    return d;
  }
  const r = RS.joinEdges(split1("eave", "eave"), "e1a", "e1b");
  check(r.ok, "normal join succeeds");
  check(!RS.vById(r.doc, "vm"), "middle vertex removed");
  check(RS.fById(r.doc, "f1").edgeIds.length === 4, "facet boundary collapses back to 4 edges");
  check(RS.eById(r.doc, r.edgeId).type === "eave", "same type inherits");
  check(RS.validateSketch(r.doc).valid, "join result validates");

  const rc = RS.joinEdges(split1("unclassified", "eave"), "e1a", "e1b");
  check(rc.ok && RS.eById(rc.doc, rc.edgeId).type === "eave", "classified + unclassified inherits classified");

  const rconf = RS.joinEdges(split1("eave", "rake"), "e1a", "e1b");
  check(!rconf.ok && rconf.reason === "type_conflict", "two classified types require explicit resultType");
  const rres = RS.joinEdges(split1("eave", "rake"), "e1a", "e1b", { resultType: "hip" });
  check(rres.ok && RS.eById(rres.doc, rres.edgeId).type === "hip", "explicit resultType resolves a type conflict");

  // source decisions invalidated
  const dd = split1("eave", "eave");
  dd.proposal_decisions = [{ target_type: "edge", target_id: "e1a", metric: "length_ft" }, { target_type: "edge", target_id: "e1b", metric: "length_ft" }];
  const rsd = RS.joinEdges(dd, "e1a", "e1b");
  check(!rsd.doc.proposal_decisions.some((x) => x.target_id === "e1a" || x.target_id === "e1b"), "both source-edge decisions invalidated");

  // middle vertex branch rejected
  const branch = split1("eave", "eave");
  branch.vertices = [...branch.vertices, { id: "vx", x: 5, y: 5 }];
  branch.edges = [...branch.edges, { id: "ebr", v1: "vm", v2: "vx", type: "unclassified" }];
  const rb = RS.joinEdges(branch, "e1a", "e1b");
  check(!rb.ok && rb.reason === "middle_vertex_has_additional_connections", "branch at middle vertex rejected");

  // protected source rejected
  const rpp = RS.joinEdges(RS.lockEdge(split1("eave", "eave"), "e1a"), "e1a", "e1b");
  check(!rpp.ok && rpp.reason === "edge_protected", "protected source edge rejected");

  // duplicate outer edge rejected
  const dupo = split1("eave", "eave");
  dupo.edges = [...dupo.edges, { id: "eout", v1: "v1", v2: "v2", type: "unclassified" }];
  const rdo = RS.joinEdges(dupo, "e1a", "e1b");
  check(!rdo.ok && rdo.reason === "duplicate_outer_edge", "duplicate outer edge rejected");

  // cyclic last->first join (rectangle e4 [last] + e1 [first] share v1)
  const rcyc = RS.joinEdges(rect(), "e4", "e1", { resultType: "eave" });
  check(rcyc.ok, "cyclic last->first join succeeds");
  check(RS.fById(rcyc.doc, "f1").edgeIds.length === 3, "cyclic join collapses the wrapped pair to one joined edge");
  check(RS.validateSketch(rcyc.doc).valid, "cyclic join result validates");

  const manual = RS.setEditMode(split1("eave", "eave"), "manual_polygon");
  const rman = RS.joinEdges(manual, "e1a", "e1b");
  check(!rman.ok && rman.reason === "connected_graph_required", "join rejected in manual_polygon");
}

// ==================== 22 — MUTATION VALIDATION CONTRACT ====================
begin("mutation-validation");
{
  const before = rect();
  const rs = RS.splitEdgeSafe(before, "e1", 5, 3);
  check(RS.validateMutation(before, rs.doc).ok, "successful split introduces no new hard errors");
  const rm = RS.mergeVertices(before, "v4", "v1");
  check(RS.validateMutation(before, rm.doc).ok, "successful merge introduces no new hard errors");
  const tri = triangle();
  const rt = RS.mergeVertices(tri, "v2", "v1");
  check(rt.ok === false && rt.doc === tri, "invalid candidate -> ok:false and the ORIGINAL document is returned");
}

// ==================== 23 — SNAP CONTRACTS ====================
begin("snap");
{
  const d = rect();
  const vWins = RS.snapTarget(d, [0.5, 0.2], 2);
  check(vWins.type === "vertex" && vWins.vertexId === "v1", "vertex wins over edge within tolerance");
  const eWins = RS.snapTarget(d, [5, -1], 2);
  check(eWins.type === "edge" && eWins.edgeId === "e1", "edge interior wins over free when no vertex near");
  check(Math.abs(eWins.point[1]) < 1e-9 && eWins.t > 0 && eWins.t < 1, "edge projection stays on the segment (not an infinite-line extension)");
  const free = RS.snapTarget(d, [100, 100], 2);
  check(free.type === "free", "free returned when nothing is near");
  const excl = RS.snapTarget(d, [0.5, 0.2], 2, { excludeVertexId: "v1" });
  check(excl.type === "edge", "excludeVertexId prevents snapping to the excluded vertex");
  const inel = RS.snapTarget(d, [5, -1], 2, { eligibleEdge: () => false });
  check(inel.type === "free", "eligibleEdge=false makes edges ineligible");
  check(RS.modelTolerance(10, 2) === 5 && RS.modelTolerance(10, 1) === 10, "modelTolerance scales by zoom (px / k)");
}

// ==================== 24 — GESTURE CONTRACTS ====================
begin("gesture");
{
  const locked = RS.lockEdge(rect(), "e1");
  const blocked = RS.candidateFor(locked, { type: "edge", edgeId: "e1", point: [5, 0] });
  check(blocked.type === "blocked", "candidate against a protected edge becomes blocked (never falls through to free)");

  const dfree = RS.drawSnap(rect(), [100, 100], 2);
  check(dfree.type === "free", "draw snap: free point far away");
  const dvert = RS.drawSnap(rect(), [0.4, 0.3], 2);
  check(dvert.type === "vertex", "draw snap: existing vertex");
  const dedge = RS.drawSnap(rect(), [5, -1], 2);
  check(dedge.type === "edge", "draw snap: eligible edge interior");

  const rBlocked = RS.applyDrawPoint(locked, { type: "blocked", edgeId: "e1", point: [5, 0] });
  check(!rBlocked.ok && rBlocked.reason === "edge_protected", "applyDrawPoint: protected/blocked candidate rejected");
  const rFree = RS.applyDrawPoint(rect(), { type: "free", point: [3, 9] });
  check(rFree.ok && rFree.doc.vertices.length === 5, "applyDrawPoint: free -> addVertex");
  const rReuse = RS.applyDrawPoint(rect(), { type: "vertex", vertexId: "v3" });
  check(rReuse.ok && rReuse.vertexId === "v3", "applyDrawPoint: existing vertex reused");
  const rSplit = RS.applyDrawPoint(rect(), { type: "edge", edgeId: "e1", point: [5, 0] });
  check(rSplit.ok && !RS.eById(rSplit.doc, "e1"), "applyDrawPoint: eligible edge -> splitEdgeSafe");

  // drag vertex -> vertex merge
  const dropMerge = RS.applyVertexDrop(rect(), "v4", { type: "vertex", vertexId: "v1" });
  check(dropMerge.ok && !RS.vById(dropMerge.doc, "v4"), "applyVertexDrop: vertex -> mergeVertices");
  // drag vertex -> edge insert
  function withFree() { const d = rect(); d.vertices = [...d.vertices, { id: "v5", x: 5, y: 3 }]; return d; }
  const dropInsert = RS.applyVertexDrop(withFree(), "v5", { type: "edge", edgeId: "e1", point: [5, 3] });
  check(dropInsert.ok && !RS.eById(dropInsert.doc, "e1"), "applyVertexDrop: edge -> insertExistingVertexIntoEdge");
  // drag free -> moveVertexFinal
  const dropFree = RS.applyVertexDrop(rect(), "v1", { type: "free", point: [-2, -2] });
  check(dropFree.ok && RS.vById(dropFree.doc, "v1").x === -2, "applyVertexDrop: free -> moveVertexFinal");
  // drag blocked -> original document
  const lockedDoc = RS.lockEdge(rect(), "e1");
  const dropBlocked = RS.applyVertexDrop(lockedDoc, "v4", { type: "blocked", edgeId: "e1", point: [5, 0] });
  check(!dropBlocked.ok && dropBlocked.doc === lockedDoc, "applyVertexDrop: blocked -> original document unchanged");
}

// ==================== 25 — DIMENSION CONTRACTS ====================
begin("dimension");
{
  const unscaled = rect();
  const du = RS.edgeDimension(unscaled, RS.eById(unscaled, "e1"));
  check(du.valueFeet === null && du.source === "unavailable", "unscaled -> unavailable (no fake LF)");

  const scaled = RS.setScale(rect(), { edgeId: "e1", realFeet: 10 }); // feetPerUnit = 1
  const ds = RS.edgeDimension(scaled, RS.eById(scaled, "e1"));
  check(ds.source === "geometry_scaled" && ds.valueFeet === 10, "scaled -> geometry_scaled with correct LF");

  const lockedShort = RS.lockEdge(RS.setConfirmedEdgeLength(scaled, "e1", 8), "e1");
  const dl = RS.edgeDimension(lockedShort, RS.eById(lockedShort, "e1"));
  check(dl.source === "confirmed_locked" && dl.locked === true, "locked confirmed -> confirmed_locked");
  check(dl.valueFeet === 8, "confirmed displayed value wins");
  check(dl.geometryFeet === 10, "geometry still available separately");
  check(dl.discrepancy === 2, "discrepancy positive (geometry 10 - confirmed 8 = +2)");

  const lockedLong = RS.lockEdge(RS.setConfirmedEdgeLength(scaled, "e1", 12), "e1");
  const dln = RS.edgeDimension(lockedLong, RS.eById(lockedLong, "e1"));
  check(dln.discrepancy === -2, "discrepancy negative (geometry 10 - confirmed 12 = -2)");
  check(RS.formatFeet(8) === "8.0 LF" && RS.formatFeet(null) === null, "formatFeet formats / passes through null");
}

// ==================== 26 — HISTORY CONTRACTS ====================
begin("history");
{
  const h0 = RS.makeHistory("a");
  check(h0.present === "a" && !RS.historyCanUndo(h0) && !RS.historyCanRedo(h0), "initial state: present set, no undo/redo");
  const h1 = RS.historyPush(h0, "b");
  check(h1.present === "b" && RS.historyCanUndo(h1) && h1.future.length === 0, "push advances present");
  const h1u = RS.historyUndo(h1);
  check(h1u.present === "a" && RS.historyCanRedo(h1u), "undo restores previous + enables redo");
  const h1r = RS.historyRedo(h1u);
  check(h1r.present === "b", "redo re-applies");
  const hpf = RS.historyPushFrom(RS.makeHistory("x"), "x", "y");
  check(hpf.present === "y" && hpf.past[hpf.past.length - 1] === "x", "pushFrom commits an explicit before->after");
  const hClears = RS.historyPush(RS.historyUndo(RS.historyPush(RS.makeHistory("a"), "b")), "c");
  check(hClears.future.length === 0 && hClears.present === "c", "a new edit clears the redo branch");
  let hcap = RS.makeHistory("0");
  for (let i = 1; i <= 130; i++) hcap = RS.historyPush(hcap, String(i));
  check(hcap.past.length <= RS.MAX_HISTORY && RS.MAX_HISTORY === 100, "history capped at 100 states");
}

// ---- report ----
let total = 0, failed = 0;
console.log("\n==== EDITOR ENGINE CONTRACT SUMMARY ====");
for (const k of Object.keys(counts)) {
  total += counts[k].passed; failed += counts[k].failed;
  console.log("  " + k + ": passed=" + counts[k].passed + " failed=" + counts[k].failed);
}
assert.strictEqual(failed, 0, "some editor-engine contracts failed");
console.log("\nEDITOR ENGINE: all " + total + " assertions passed");

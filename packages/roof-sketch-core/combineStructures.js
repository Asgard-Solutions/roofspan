"use strict";
// Combine every in-scope structure's deterministically-generated roof into ONE unified site-plan
// document. Each structure is framed independently (shared generator — no new geometry logic), then
// translated so the structures sit side-by-side along a common top edge, largest footprint first, with
// a small gap. Optional per-structure `offsets` (feet) let a user nudge a structure's placement; the
// offsets are the only adjustable state (positions are draggable in the UI and persisted on the
// revision's site_plan). Pure & deterministic: same input + offsets => same combined document.
//
// Never mutates measurements, never changes measured dimensions, never touches per-structure sketches.

const { generateSketchGeometry } = require("./generateSketchGeometry");

const GAP_FT = 12;               // horizontal gap between structures in the site plan (feet)
const rnd = (n) => Math.round(Number(n) * 1000) / 1000;
const num = (v) => { if (v === "" || v == null) return null; const n = Number(v); return Number.isFinite(n) ? n : null; };

function _bbox(vertices) {
  const xs = vertices.map((v) => v.x), ys = vertices.map((v) => v.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  return { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY };
}

// Scope this structure's relational records (facets by structure_id; edges/penetrations by facet owner).
function _scope(structureId, facets, edges, penetrations) {
  const sf = facets.filter((f) => String(f.structure_id) === String(structureId));
  const ids = new Set(sf.map((f) => String(f.id)));
  const se = edges.filter((e) => ids.has(String(e.facet_id)) || ids.has(String(e.facet_id_secondary)));
  const sp = penetrations.filter((p) => ids.has(String(p.facet_id)));
  return { facets: sf, edges: se, penetrations: sp };
}

function combineStructuresSitePlan(input) {
  const inp = input || {};
  const structuresIn = Array.isArray(inp.structures) ? inp.structures : [];
  const facets = Array.isArray(inp.facets) ? inp.facets : [];
  const edges = Array.isArray(inp.edges) ? inp.edges : [];
  const penetrations = Array.isArray(inp.penetrations) ? inp.penetrations : [];
  const offsets = inp.offsets || {};

  const inScope = structuresIn
    .filter((s) => s && s.id != null && s.included_in_scope !== false)
    .slice()
    .sort((a, b) => (Number(a.sort) || 0) - (Number(b.sort) || 0) || (String(a.id) < String(b.id) ? -1 : 1));

  const placedRaw = [];
  const unplaced = [];
  for (const s of inScope) {
    const sid = String(s.id);
    const scoped = _scope(sid, facets, edges, penetrations);
    if (!scoped.facets.length) { unplaced.push({ structure_id: sid, label: s.name || sid, reason: "no_roof_planes" }); continue; }
    let res = null;
    try { res = generateSketchGeometry({ structure: { id: sid }, facets: scoped.facets, edges: scoped.edges, penetrations: scoped.penetrations }); }
    catch (e) { res = null; }
    const doc = res && res.document;
    if (!doc || !(doc.vertices || []).length || !(doc.facets || []).length) {
      unplaced.push({ structure_id: sid, label: s.name || sid, reason: (res && res.readiness) || "needs_review" });
      continue;
    }
    placedRaw.push({ structure: s, sid, doc, bbox: _bbox(doc.vertices), readiness: res.readiness });
  }

  // Largest footprint first (main house leads), then structure sort/id for a stable order.
  placedRaw.sort((a, b) =>
    (b.bbox.width * b.bbox.height) - (a.bbox.width * a.bbox.height) ||
    (Number(a.structure.sort) || 0) - (Number(b.structure.sort) || 0) ||
    (a.sid < b.sid ? -1 : 1));

  const combined = { schema_version: 1, edit_mode: "manual_polygon", scale: { resolved: true, feetPerUnit: 1, feet_per_unit: 1, method: "combined_site_plan" }, vertices: [], edges: [], facets: [], penetrations: [] };
  const placements = [];
  let cursorX = 0;
  placedRaw.forEach((p, idx) => {
    const off = offsets[p.sid] || {};
    const dx = num(off.dx) || 0, dy = num(off.dy) || 0;
    // Auto: sit at the running cursor, aligned to a common top (y=0). User offset nudges from there.
    const tx = rnd(cursorX - p.bbox.minX + dx);
    const ty = rnd(-p.bbox.minY + dy);
    cursorX = cursorX + p.bbox.width + GAP_FT;

    const pfx = `s${idx}_`;
    const vid = (id) => pfx + id;
    p.doc.vertices.forEach((v) => combined.vertices.push({ id: vid(v.id), x: rnd(v.x + tx), y: rnd(v.y + ty), structure_id: p.sid }));
    p.doc.edges.forEach((e) => combined.edges.push({ ...e, id: pfx + e.id, v1: e.v1 != null ? vid(e.v1) : null, v2: e.v2 != null ? vid(e.v2) : null, structure_id: p.sid }));
    p.doc.facets.forEach((f) => combined.facets.push({
      ...f, id: pfx + f.id, structure_id: p.sid, structure_label: p.structure.name || p.sid,
      edgeIds: (f.edgeIds || []).map((id) => pfx + id),
      vertexIds: (f.vertexIds || []).map((id) => vid(id)),
    }));
    (p.doc.penetrations || []).forEach((pen) => combined.penetrations.push({
      ...pen, id: pfx + pen.id, structure_id: p.sid,
      x: pen.x != null ? rnd(pen.x + tx) : null, y: pen.y != null ? rnd(pen.y + ty) : null,
    }));
    placements.push({
      structure_id: p.sid, label: p.structure.name || p.sid, structure_type: p.structure.structure_type || null,
      tx, ty, dx, dy, readiness: p.readiness,
      bbox: { x: rnd(p.bbox.minX + tx), y: rnd(p.bbox.minY + ty), width: rnd(p.bbox.width), height: rnd(p.bbox.height) },
    });
  });

  return {
    ok: placements.length > 0,
    document: combined,
    placements,
    unplaced,
    structure_count: inScope.length,
    placed_count: placements.length,
  };
}

module.exports = { combineStructuresSitePlan, GAP_FT };

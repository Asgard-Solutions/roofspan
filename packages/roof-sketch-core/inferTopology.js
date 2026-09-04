"use strict";
// Topology inference for structures that have roof PLANES but NO roof-line edges entered.
// The deterministic solver needs a ridge (and hips for hip ends) to reconstruct a roof; without any
// edges it can only report "needs review". This module synthesizes a MINIMAL, deterministic topology
// for the common cases so the structure draws a sensible best-effort shape, which the UI flags as
// "auto-inferred — add roof lines to refine". It is used ONLY when zero edges exist; any real edge
// disables inference entirely (measured roof lines always win).
//
// Rules (deterministic):
//   - Find the largest matching PAIR of planes (equal pitch/width/length) => the main gable slopes;
//     synthesize a ridge between them + an eave on each (footprint length = the pair's ridge length).
//   - The next 1-2 largest leftover planes => hipped END(s): synthesize two hips (end<->each main)
//     + a short eave. One leftover => a gable with one hip return (half-hip); two => a full hip.
//   - Any further leftover planes are reported as `ignored` (cannot be placed without roof lines).
//   - If no equal pair exists, fall back to a ridge between the two largest planes.

const { planRunFromSlope } = require("./geometry");

const num = (v) => { if (v === "" || v == null) return null; const n = Number(v); return Number.isFinite(n) ? n : null; };
const sig = (f) => {
  const p = num(f.pitch_rise), w = num(f.width_ft), l = num(f.length_ft);
  if (p == null || w == null || w <= 0 || l == null || l <= 0) return null;
  return `${Math.round(p * 2) / 2}|${Math.round(w)}|${Math.round(l)}`;
};
const areaOf = (f) => { const a = num(f.area_sqft); if (a != null) return a; const w = num(f.width_ft) || 0, l = num(f.length_ft) || 0; return w * l; };

function inferTopologyEdges(facetsIn) {
  const planes = (Array.isArray(facetsIn) ? facetsIn : []).filter((f) => f && f.id != null);
  if (planes.length < 2) return { inferred: false, edges: [], ignored: [] };
  if (planes.some((f) => num(f.pitch_rise) == null)) return { inferred: false, edges: [], ignored: [] };

  const sorted = planes.slice().sort((a, b) => (areaOf(b) - areaOf(a)) || ((num(a.sort) || 0) - (num(b.sort) || 0)) || (String(a.id) < String(b.id) ? -1 : 1));
  const sid = sorted[0].structure_id;

  // Main gable pair: first equal-signature pair (largest first); else the two largest planes.
  let a = null, bb = null;
  outer:
  for (let i = 0; i < sorted.length; i++) {
    const si = sig(sorted[i]); if (!si) continue;
    for (let j = i + 1; j < sorted.length; j++) {
      if (sig(sorted[j]) === si) { a = sorted[i]; bb = sorted[j]; break outer; }
    }
  }
  if (!a) { a = sorted[0]; bb = sorted[1]; }
  if (!a || !bb) return { inferred: false, edges: [], ignored: [] };

  const La = num(a.length_ft), Lb = num(bb.length_ft);
  let L = null;
  if (La != null && La > 0 && Lb != null && Lb > 0) L = Math.min(La, Lb);
  else L = (La != null && La > 0) ? La : Lb;
  if (L == null || !(L > 0)) return { inferred: false, edges: [], ignored: [] };

  let n = 0;
  const mk = (edge_type, f1, f2, length_ft) => ({ id: `inf_${edge_type}_${n++}`, structure_id: sid, edge_type, length_ft: length_ft != null ? length_ft : null, facet_id: f1, facet_id_secondary: f2 != null ? f2 : null, sort: n, inferred: true });

  // Main gable slopes: a ridge along the plane LENGTH + a long eave (= L) on each. The roof depth W is
  // NOT synthesized here — the solver derives it from the two main slopes' own widths (planRun), so the
  // drawn depth matches the measured slope planes exactly.
  const leftovers = sorted.filter((f) => f !== a && f !== bb);
  const ends = leftovers.slice(0, 2);
  const ignored = leftovers.slice(2).map((f) => String(f.id));

  // Each hip END insets the ridge by the end plane's own plan run (planRun(end.width, end.pitch)), so the
  // hip triangle's footprint matches the measured end plane; unknown => fall back to a fraction of L.
  const insetOf = (e) => {
    const r = planRunFromSlope(num(e.width_ft), num(e.pitch_rise));
    if (r != null && r > 0) return r;
    const w = num(e.width_ft); return (w != null && w > 0) ? w : L * 0.3;
  };
  const insets = ends.map(insetOf);
  const totalInset = insets.reduce((s, v) => s + v, 0);
  let ridgeLen = L - totalInset;
  if (!(ridgeLen > 0)) { ridgeLen = null; }  // let the solver approximate if insets would swallow the ridge

  const edges = [mk("ridge", a.id, bb.id, ridgeLen), mk("eave", a.id, null, L), mk("eave", bb.id, null, L)];
  // Hip ends: two hips (end<->each main). No synthesized end eave, so the depth stays governed by the
  // main slopes. The hip length carries the measured end-plane width for provenance.
  ends.forEach((e) => {
    edges.push(mk("hip", e.id, a.id, num(e.width_ft) || null));
    edges.push(mk("hip", e.id, bb.id, num(e.width_ft) || null));
  });

  return { inferred: true, edges, ignored, mains: [String(a.id), String(bb.id)], ends: ends.map((f) => String(f.id)) };
}

module.exports = { inferTopologyEdges };

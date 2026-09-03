import React, { useMemo } from "react";
import { View, Text } from "react-native";
import Svg, { Polygon, Line } from "react-native-svg";
import * as RS from "@roofspan/roof-sketch-core";

// Field roof preview thumbnail — the same deterministic framing-solver geometry Office shows, rendered
// with react-native-svg on the mobile measurement structure row. Presentational only.
const EDGE_COLOR = { ridge: "#0f172a", hip: "#2563eb", valley: "#dc2626", dead_valley: "#b91c1c", eave: "#0f766e", rake: "#a16207" };
const W = 128, H = 84, PAD = 8;
const numOr = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : null; };

export default function RoofThumbnail({ structure, facets = [], edges = [], testID }) {
  const view = useMemo(() => {
    try {
      const s = structure || {};
      const sref = s.ref, sid = s.id;
      const key = sid || sref;
      const scoped = facets.filter((f) => (sref != null && f.structure_ref === sref) || (sid != null && f.structure_id === sid));
      if (!scoped.length) return { status: "empty" };
      const nf = scoped.map((f) => ({
        id: String(f.id || f.ref), structure_id: key, label: f.facet_label,
        pitch_rise: numOr(f.pitch_rise), width_ft: numOr(f.width_ft), length_ft: numOr(f.length_ft), area_sqft: numOr(f.area_sqft),
      }));
      const idset = new Set(scoped.map((f) => String(f.id || f.ref)));
      const fkey = (f1, f2) => String(f1 != null ? f1 : (f2 != null ? f2 : ""));
      const ne = edges.map((e) => ({
        id: String(e.id || e.ref), edge_type: e.edge_type, length_ft: numOr(e.length_ft),
        facet_id: fkey(e.facet_id, e.facet_ref), facet_id_secondary: e.facet_id_secondary != null || e.facet_ref_secondary != null ? fkey(e.facet_id_secondary, e.facet_ref_secondary) : null,
      })).filter((e) => idset.has(e.facet_id) || (e.facet_id_secondary && idset.has(e.facet_id_secondary)));
      const res = RS.generateSketchGeometry({ structure: { id: key }, facets: nf, edges: ne, penetrations: [] });
      const doc = res && res.document;
      if (!doc || !(doc.vertices || []).length || !(doc.facets || []).length) return { status: "unavailable" };
      const xs = doc.vertices.map((v) => v.x), ys = doc.vertices.map((v) => v.y);
      const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
      const spanX = Math.max(maxX - minX, 1e-6), spanY = Math.max(maxY - minY, 1e-6);
      const scale = Math.min((W - 2 * PAD) / spanX, (H - 2 * PAD) / spanY);
      const ox = (W - spanX * scale) / 2, oy = (H - spanY * scale) / 2;
      const map = (x, y) => ({ x: ox + (x - minX) * scale, y: oy + (y - minY) * scale });
      const vById = {}; doc.vertices.forEach((v) => { vById[v.id] = map(v.x, v.y); });
      const polys = doc.facets.map((f) => {
        const r = RS.resolveFacetBoundary(doc, f);
        return (r.points || []).map(([x, y]) => { const m = map(x, y); return `${m.x.toFixed(1)},${m.y.toFixed(1)}`; }).join(" ");
      }).filter(Boolean);
      const lines = doc.edges.map((e) => ({ a: vById[e.v1], b: vById[e.v2], type: e.type })).filter((l) => l.a && l.b);
      return { status: "ok", polys, lines };
    } catch (e) {
      return { status: "unavailable" };
    }
  }, [structure, facets, edges]);

  if (view.status !== "ok") {
    return (
      <View testID={testID} style={{ width: W, height: H, borderRadius: 6, borderWidth: 1, borderColor: "#e2e8f0", borderStyle: "dashed", alignItems: "center", justifyContent: "center", backgroundColor: "#f8fafc" }}>
        <Text style={{ fontSize: 10, color: "#94a3b8" }}>{view.status === "empty" ? "No roof planes yet" : "Preview needs review"}</Text>
      </View>
    );
  }
  return (
    <View testID={testID} style={{ width: W, height: H, borderRadius: 6, borderWidth: 1, borderColor: "#e2e8f0", backgroundColor: "#fff" }}>
      <Svg width={W} height={H}>
        {view.polys.map((pts, i) => <Polygon key={`p${i}`} points={pts} fill="rgba(148,163,184,0.14)" />)}
        {view.lines.map((l, i) => <Line key={`l${i}`} x1={l.a.x} y1={l.a.y} x2={l.b.x} y2={l.b.y} stroke={EDGE_COLOR[l.type] || "#94a3b8"} strokeWidth={1.4} strokeLinecap="round" />)}
      </Svg>
    </View>
  );
}

import React, { useMemo } from "react";
import { generateSketchGeometry, resolveFacetBoundary } from "@roofspan/roof-sketch-core";
import { scopeForStructure } from "@/components/roof-sketch/scopeMeasurements";

// A small, deterministic auto-generated roof preview drawn straight from the Measurements via the shared
// framing solver. Purely presentational — it never saves, mutates, or replaces the authoritative sketch.
const EDGE_COLOR = { ridge: "#0f172a", hip: "#2563eb", valley: "#dc2626", dead_valley: "#b91c1c", eave: "#0f766e", rake: "#a16207" };
const W = 132, H = 96, PAD = 8;

export default function RoofThumbnail({ structure, facets = [], edges = [], penetrations = [], testid }) {
  const view = useMemo(() => {
    try {
      const scoped = scopeForStructure({ structure, facets, edges, penetrations });
      if (!scoped.facets.length) return { status: "empty" };
      const res = generateSketchGeometry({ structure, facets: scoped.facets, edges: scoped.edges, penetrations: scoped.penetrations });
      const doc = res && res.document;
      if (!doc || !(doc.vertices || []).length || !(doc.facets || []).length) return { status: "unavailable" };
      const xs = doc.vertices.map((v) => v.x), ys = doc.vertices.map((v) => v.y);
      const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
      const spanX = Math.max(maxX - minX, 1e-6), spanY = Math.max(maxY - minY, 1e-6);
      const scale = Math.min((W - 2 * PAD) / spanX, (H - 2 * PAD) / spanY);
      const ox = (W - spanX * scale) / 2, oy = (H - spanY * scale) / 2;
      const map = (v) => ({ x: ox + (v.x - minX) * scale, y: oy + (v.y - minY) * scale });
      const vById = {}; doc.vertices.forEach((v) => { vById[v.id] = map(v); });
      const polys = doc.facets.map((f) => {
        const r = resolveFacetBoundary(doc, f);
        return (r.points || []).map(([x, y]) => { const m = map({ x, y }); return `${m.x.toFixed(1)},${m.y.toFixed(1)}`; }).join(" ");
      }).filter(Boolean);
      const lines = doc.edges.map((e) => ({ a: vById[e.v1], b: vById[e.v2], type: e.type }));
      return { status: "ok", polys, lines, readiness: res.readiness };
    } catch (e) {
      return { status: "unavailable" };
    }
  }, [structure, facets, edges, penetrations]);

  if (view.status !== "ok") {
    return (
      <div data-testid={testid} className="flex h-[96px] w-[132px] shrink-0 items-center justify-center rounded border border-dashed border-slate-200 bg-slate-50 text-[10px] text-slate-400">
        {view.status === "empty" ? "No roof planes yet" : "Preview needs review"}
      </div>
    );
  }
  return (
    <div data-testid={testid} className="shrink-0 rounded border border-slate-200 bg-white" title={`Auto preview (${view.readiness || "generated"})`}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Roof preview">
        {view.polys.map((pts, i) => <polygon key={`p${i}`} points={pts} fill="rgba(148,163,184,0.14)" stroke="none" />)}
        {view.lines.map((l, i) => l.a && l.b ? (
          <line key={`l${i}`} x1={l.a.x} y1={l.a.y} x2={l.b.x} y2={l.b.y}
            stroke={EDGE_COLOR[l.type] || "#94a3b8"} strokeWidth={1.4} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        ) : null)}
      </svg>
    </div>
  );
}

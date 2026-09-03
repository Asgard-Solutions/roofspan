import React, { useMemo } from "react";
import { generateSketchGeometry, resolveFacetBoundary } from "@roofspan/roof-sketch-core";
import { scopeForStructure } from "@/components/roof-sketch/scopeMeasurements";

// A small, deterministic auto-generated roof preview drawn straight from the Measurements via the shared
// framing solver. Purely presentational — it never saves, mutates, or replaces the authoritative sketch.
// When a roof plane carries an "Offset from left (ft)", a live guide + foot ruler show where it lands.
const EDGE_COLOR = { ridge: "#0f172a", hip: "#2563eb", valley: "#dc2626", dead_valley: "#b91c1c", eave: "#0f766e", rake: "#a16207" };
const W = 148, H = 108, PAD = 10, RULER_H = 12;
const num = (v) => { if (v === "" || v == null) return null; const n = Number(v); return Number.isFinite(n) ? n : null; };

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
      const scale = Math.min((W - 2 * PAD) / spanX, (H - RULER_H - 2 * PAD) / spanY);
      const ox = (W - spanX * scale) / 2, oy = (H - RULER_H - spanY * scale) / 2;
      const map = (v) => ({ x: ox + (v.x - minX) * scale, y: oy + (v.y - minY) * scale });
      const vById = {}; doc.vertices.forEach((v) => { vById[v.id] = map(v); });
      const polys = doc.facets.map((f) => {
        const r = resolveFacetBoundary(doc, f);
        return (r.points || []).map(([x, y]) => { const m = map({ x, y }); return `${m.x.toFixed(1)},${m.y.toFixed(1)}`; }).join(" ");
      }).filter(Boolean);
      const lines = doc.edges.map((e) => ({ a: vById[e.v1], b: vById[e.v2], type: e.type }));
      const roofTop = oy, roofBot = oy + spanY * scale;
      // Offset guides: a dashed vertical line at world-x = offset (where a pinned dormer/wing sits).
      const guides = (scoped.facets || [])
        .map((f) => ({ label: f.facet_label, off: num(f.position_offset_ft) }))
        .filter((g) => g.off != null && g.off > minX && g.off < maxX)
        .map((g) => ({ ...g, x: ox + (g.off - minX) * scale }));
      // Foot ruler tick positions (every 5 ft) across the drawn width.
      const step = spanX > 60 ? 20 : spanX > 30 ? 10 : 5;
      const ticks = [];
      for (let ft = Math.ceil(minX / step) * step; ft <= maxX + 1e-6; ft += step) ticks.push({ ft, x: ox + (ft - minX) * scale });
      return { status: "ok", polys, lines, readiness: res.readiness, guides, ticks, roofTop, roofBot, rulerY: H - RULER_H };
    } catch (e) {
      return { status: "unavailable" };
    }
  }, [structure, facets, edges, penetrations]);

  if (view.status !== "ok") {
    return (
      <div data-testid={testid} className="flex h-[108px] w-[148px] shrink-0 items-center justify-center rounded border border-dashed border-slate-200 bg-slate-50 text-[10px] text-slate-400">
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
        {/* Offset guides — where each pinned dormer/wing lands along the wall */}
        {view.guides.map((g, i) => (
          <g key={`g${i}`} data-testid={`roof-offset-guide-${g.label}`}>
            <line x1={g.x} y1={view.roofTop - 2} x2={g.x} y2={view.roofBot + 2} stroke="#d97706" strokeWidth={1} strokeDasharray="3 2" vectorEffect="non-scaling-stroke" />
            <circle cx={g.x} cy={view.roofBot} r={2.2} fill="#d97706" />
            <text x={g.x} y={view.roofTop - 3} textAnchor="middle" fill="#b45309" style={{ fontSize: 7, fontWeight: 700 }}>{g.off}′</text>
          </g>
        ))}
        {/* Foot ruler */}
        <line x1={PAD / 2} y1={view.rulerY} x2={W - PAD / 2} y2={view.rulerY} stroke="#cbd5e1" strokeWidth={1} />
        {view.ticks.map((t, i) => (
          <g key={`t${i}`}>
            <line x1={t.x} y1={view.rulerY} x2={t.x} y2={view.rulerY + 3} stroke="#94a3b8" strokeWidth={1} />
            <text x={t.x} y={view.rulerY + 10} textAnchor="middle" fill="#94a3b8" style={{ fontSize: 6 }}>{t.ft}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

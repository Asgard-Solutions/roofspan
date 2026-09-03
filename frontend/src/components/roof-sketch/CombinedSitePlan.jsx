import React, { useMemo, useRef, useState, useCallback } from "react";
import { combineStructuresSitePlan, resolveFacetBoundary } from "@roofspan/roof-sketch-core";
import { Button } from "@/components/ui/button";
import { RotateCcw, Download } from "lucide-react";
import { toast } from "sonner";

const NICE_FT = [1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000];
function niceScaleFeet(scale) { // scale = viewBox units per foot; aim for a ~110-unit bar
  const target = 110 / Math.max(scale, 1e-6);
  let best = NICE_FT[0];
  for (const f of NICE_FT) { if (f <= target) best = f; }
  return best;
}

// A unified, auto-arranged site plan combining every in-scope structure's deterministically-generated
// roof into one drawing. Structures sit side-by-side (largest first) and can be dragged to reposition;
// the drag offsets are persisted on the revision's site_plan. Presentational only — never alters
// measured dimensions or per-structure sketches.
const EDGE_COLOR = { ridge: "#0f172a", hip: "#2563eb", valley: "#dc2626", dead_valley: "#b91c1c", eave: "#0f766e", rake: "#a16207" };
const VB_W = 720, VB_H = 380, PAD = 24;

export default function CombinedSitePlan({ structures = [], facets = [], edges = [], penetrations = [], sitePlan = null, editable = false, onChangeOffsets }) {
  const svgRef = useRef(null);
  const [drag, setDrag] = useState(null); // { sid, startClientX, startClientY, dxPx, dyPx }
  const offsets = (sitePlan && sitePlan.offsets) || {};

  const combined = useMemo(() => {
    try { return combineStructuresSitePlan({ structures, facets, edges, penetrations, offsets }); }
    catch (e) { return null; }
  }, [structures, facets, edges, penetrations, offsets]);

  const view = useMemo(() => {
    const doc = combined && combined.document;
    if (!doc || !(doc.vertices || []).length) return null;
    const xs = doc.vertices.map((v) => v.x), ys = doc.vertices.map((v) => v.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const spanX = Math.max(maxX - minX, 1e-6), spanY = Math.max(maxY - minY, 1e-6);
    const scale = Math.min((VB_W - 2 * PAD) / spanX, (VB_H - 2 * PAD) / spanY);
    const ox = (VB_W - spanX * scale) / 2, oy = (VB_H - spanY * scale) / 2;
    const map = (x, y) => ({ x: ox + (x - minX) * scale, y: oy + (y - minY) * scale });
    const byStruct = {};
    doc.facets.forEach((f) => {
      const sid = f.structure_id;
      byStruct[sid] = byStruct[sid] || { sid, label: f.structure_label || sid, polys: [], lines: [] };
      const r = resolveFacetBoundary(doc, f);
      const pts = (r.points || []).map(([x, y]) => { const m = map(x, y); return `${m.x.toFixed(1)},${m.y.toFixed(1)}`; }).join(" ");
      if (pts) byStruct[sid].polys.push(pts);
    });
    const vById = {}; doc.vertices.forEach((v) => { vById[v.id] = map(v.x, v.y); });
    doc.edges.forEach((e) => {
      const sid = e.structure_id;
      if (!byStruct[sid]) return;
      const a = vById[e.v1], b = vById[e.v2];
      if (a && b) byStruct[sid].lines.push({ a, b, type: e.type });
    });
    // label anchor = centroid of the structure's mapped vertices; keep bottom + measured dims for tags
    const dimBySid = {}; (combined.placements || []).forEach((p) => { dimBySid[p.structure_id] = p.bbox; });
    Object.values(byStruct).forEach((g) => {
      const gv = doc.vertices.filter((v) => v.structure_id === g.sid).map((v) => map(v.x, v.y));
      g.cx = gv.reduce((s, p) => s + p.x, 0) / (gv.length || 1);
      g.top = Math.min(...gv.map((p) => p.y));
      g.bottom = Math.max(...gv.map((p) => p.y));
      const bb = dimBySid[g.sid];
      g.dims = bb ? `${Math.round(bb.width)}′ × ${Math.round(bb.height)}′` : null;
    });
    const barFt = niceScaleFeet(scale);
    return { scale, groups: Object.values(byStruct), barFt, barPx: barFt * scale };
  }, [combined]);

  const onPointerDown = useCallback((sid, e) => {
    if (!editable) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setDrag({ sid, startClientX: e.clientX, startClientY: e.clientY, dxPx: 0, dyPx: 0 });
  }, [editable]);

  const onPointerMove = useCallback((e) => {
    if (!drag) return;
    setDrag((d) => d ? { ...d, dxPx: e.clientX - d.startClientX, dyPx: e.clientY - d.startClientY } : d);
  }, [drag]);

  const commitDrag = useCallback(() => {
    if (!drag || !view || !svgRef.current) { setDrag(null); return; }
    const rect = svgRef.current.getBoundingClientRect();
    const vbPerClientX = VB_W / (rect.width || VB_W);
    const vbPerClientY = VB_H / (rect.height || VB_H);
    const dFeetX = (drag.dxPx * vbPerClientX) / view.scale;
    const dFeetY = (drag.dyPx * vbPerClientY) / view.scale;
    if (Math.abs(dFeetX) > 0.05 || Math.abs(dFeetY) > 0.05) {
      const cur = offsets[drag.sid] || { dx: 0, dy: 0 };
      const next = { ...offsets, [drag.sid]: { dx: Math.round(((cur.dx || 0) + dFeetX) * 10) / 10, dy: Math.round(((cur.dy || 0) + dFeetY) * 10) / 10 } };
      onChangeOffsets && onChangeOffsets({ offsets: next });
    }
    setDrag(null);
  }, [drag, view, offsets, onChangeOffsets]);

  const resetLayout = useCallback(() => { onChangeOffsets && onChangeOffsets({ offsets: {} }); }, [onChangeOffsets]);

  const downloadBlob = (blob, name) => {
    const url = URL.createObjectURL(blob); const a = document.createElement("a");
    a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const rasterize = () => new Promise((resolve, reject) => {
    const svg = svgRef.current; if (!svg) return reject(new Error("no svg"));
    const xml = new XMLSerializer().serializeToString(svg);
    const src = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(xml)));
    const img = new Image();
    img.onload = () => {
      const up = 2, canvas = document.createElement("canvas");
      canvas.width = VB_W * up; canvas.height = VB_H * up;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      resolve(canvas);
    };
    img.onerror = reject; img.src = src;
  });
  const exportPng = useCallback(async () => {
    try { const c = await rasterize(); c.toBlob((b) => b ? downloadBlob(b, "site-plan.png") : toast.error("Could not export PNG"), "image/png"); }
    catch (e) { toast.error("Could not export the site plan as PNG"); }
  }, []);
  const exportPdf = useCallback(async () => {
    try {
      const c = await rasterize();
      const dataUrl = c.toDataURL("image/png");
      const { jsPDF } = await import("jspdf");
      const pdf = new jsPDF({ orientation: "landscape", unit: "pt", format: "letter" });
      const pw = pdf.internal.pageSize.getWidth(), ph = pdf.internal.pageSize.getHeight(), m = 36;
      pdf.setFontSize(15); pdf.setTextColor(15, 23, 42); pdf.text("Combined Site Plan", m, m);
      pdf.setFontSize(9); pdf.setTextColor(100, 116, 139);
      pdf.text(`${combined.placed_count} structure(s) · scale bar = ${view.barFt} ft · North ↑`, m, m + 15);
      const availW = pw - 2 * m, availH = ph - 2 * m - 28;
      const ratio = Math.min(availW / c.width, availH / c.height);
      pdf.addImage(dataUrl, "PNG", m, m + 26, c.width * ratio, c.height * ratio);
      pdf.save("site-plan.pdf");
    } catch (e) { toast.error("Could not export the site plan as PDF"); }
  }, [combined, view]);

  if (!combined || !combined.ok || !view) {
    return (
      <div data-testid="combined-site-plan-empty" className="rounded border border-dashed border-slate-200 bg-slate-50 p-4 text-center text-xs text-slate-400">
        Add roof planes to at least one in-scope structure to see the combined site plan.
      </div>
    );
  }

  return (
    <div data-testid="combined-site-plan">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs text-slate-500">
          {combined.placed_count} structure{combined.placed_count > 1 ? "s" : ""} combined{editable ? " — drag to reposition" : ""}.
          {combined.unplaced.length ? ` ${combined.unplaced.length} need${combined.unplaced.length > 1 ? "" : "s"} review.` : ""}
        </div>
        <div className="flex items-center gap-1">
          {editable && Object.keys(offsets).length > 0 &&
            <Button size="sm" variant="ghost" onClick={resetLayout} data-testid="combined-site-plan-reset"><RotateCcw className="mr-1 h-3.5 w-3.5" />Reset layout</Button>}
          <Button size="sm" variant="outline" onClick={exportPng} data-testid="site-plan-export-png"><Download className="mr-1 h-3.5 w-3.5" />PNG</Button>
          <Button size="sm" variant="outline" onClick={exportPdf} data-testid="site-plan-export-pdf"><Download className="mr-1 h-3.5 w-3.5" />PDF</Button>
        </div>
      </div>
      <svg ref={svgRef} width="100%" viewBox={`0 0 ${VB_W} ${VB_H}`} className="rounded border border-slate-200 bg-white"
        role="img" aria-label="Combined site plan" onPointerMove={onPointerMove} onPointerUp={commitDrag} onPointerLeave={commitDrag}
        style={{ touchAction: "none" }}>
        <rect x={0} y={0} width={VB_W} height={VB_H} fill="#ffffff" />
        {view.groups.map((g) => {
          const t = drag && drag.sid === g.sid ? `translate(${drag.dxPx * (VB_W / (svgRef.current?.getBoundingClientRect().width || VB_W))} ${drag.dyPx * (VB_H / (svgRef.current?.getBoundingClientRect().height || VB_H))})` : undefined;
          return (
            <g key={g.sid} transform={t} data-testid={`site-plan-structure-${g.sid}`}
              onPointerDown={(e) => onPointerDown(g.sid, e)} style={{ cursor: editable ? "move" : "default" }}>
              {g.polys.map((pts, i) => <polygon key={`p${i}`} points={pts} fill="rgba(148,163,184,0.14)" stroke="none" />)}
              {g.lines.map((l, i) => (
                <line key={`l${i}`} x1={l.a.x} y1={l.a.y} x2={l.b.x} y2={l.b.y}
                  stroke={EDGE_COLOR[l.type] || "#94a3b8"} strokeWidth={1.6} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
              ))}
              <text x={g.cx} y={Math.max(g.top - 6, 10)} textAnchor="middle" fill="#475569" style={{ fontSize: 11, fontWeight: 600 }}>{g.label}</text>
              {g.dims && <text x={g.cx} y={Math.min(g.bottom + 13, VB_H - 22)} textAnchor="middle" fill="#94a3b8" data-testid={`site-plan-dim-${g.sid}`} style={{ fontSize: 9.5 }}>{g.dims}</text>}
            </g>
          );
        })}
        {/* North arrow (top-right) */}
        <g data-testid="site-plan-north" pointerEvents="none">
          <line x1={VB_W - 26} y1={12} x2={VB_W - 26} y2={40} stroke="#0f172a" strokeWidth={1.5} />
          <polygon points={`${VB_W - 26},8 ${VB_W - 30},18 ${VB_W - 22},18`} fill="#0f172a" />
          <text x={VB_W - 26} y={52} textAnchor="middle" fill="#0f172a" style={{ fontSize: 11, fontWeight: 700 }}>N</text>
        </g>
        {/* Foot scale bar (bottom-left) */}
        <g data-testid="site-plan-scalebar" pointerEvents="none">
          <rect x={14} y={VB_H - 30} width={view.barPx + 24} height={22} rx={3} fill="rgba(255,255,255,0.82)" />
          <line x1={20} y1={VB_H - 14} x2={20 + view.barPx} y2={VB_H - 14} stroke="#0f172a" strokeWidth={1.5} />
          <line x1={20} y1={VB_H - 18} x2={20} y2={VB_H - 10} stroke="#0f172a" strokeWidth={1.5} />
          <line x1={20 + view.barPx} y1={VB_H - 18} x2={20 + view.barPx} y2={VB_H - 10} stroke="#0f172a" strokeWidth={1.5} />
          <text x={20 + view.barPx / 2} y={VB_H - 20} textAnchor="middle" fill="#0f172a" style={{ fontSize: 9, fontWeight: 600 }}>{view.barFt} ft</text>
        </g>
      </svg>
    </div>
  );
}

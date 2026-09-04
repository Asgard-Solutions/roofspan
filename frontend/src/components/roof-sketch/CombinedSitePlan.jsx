import React, { useMemo, useRef, useState, useCallback } from "react";
import { combineStructuresSitePlan, resolveFacetBoundary, generateSketchGeometry } from "@roofspan/roof-sketch-core";
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

export default function CombinedSitePlan({ structures = [], facets = [], edges = [], penetrations = [], sitePlan = null, editable = false, onChangeOffsets, propertyAddress = "", preparedBy = "" }) {
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
      const gvx = gv.map((p) => p.x), gvy = gv.map((p) => p.y);
      g.cx = gvx.reduce((s, x) => s + x, 0) / (gvx.length || 1);
      g.top = Math.min(...gvy);
      g.bottom = Math.max(...gvy);
      g.vb = { x0: Math.min(...gvx), y0: Math.min(...gvy), x1: Math.max(...gvx), y1: Math.max(...gvy), cx: g.cx, cy: (Math.min(...gvy) + Math.max(...gvy)) / 2 };
      const bb = dimBySid[g.sid];
      g.dims = bb ? `${Math.round(bb.width)}′ × ${Math.round(bb.height)}′` : null;
    });
    const barFt = niceScaleFeet(scale);
    return { scale, groups: Object.values(byStruct), barFt, barPx: barFt * scale };
  }, [combined]);

  const onPointerDown = useCallback((sid, e) => {
    if (!editable) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setDrag({ sid, startClientX: e.clientX, startClientY: e.clientY, tvbx: 0, tvby: 0, guides: [] });
  }, [editable]);

  const onPointerMove = useCallback((e) => {
    if (!drag || !view || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const ratioX = VB_W / (rect.width || VB_W), ratioY = VB_H / (rect.height || VB_H);
    let tdx = (e.clientX - drag.startClientX) * ratioX, tdy = (e.clientY - drag.startClientY) * ratioY;
    // Snap-to-wall: align the dragged structure's edges/center to a neighbour's edges/center.
    const SNAP = 9; // viewBox units
    const me = view.groups.find((g) => g.sid === drag.sid);
    const guides = [];
    if (me) {
      const L = me.vb.x0 + tdx, R = me.vb.x1 + tdx, CX = me.vb.cx + tdx;
      const T = me.vb.y0 + tdy, B = me.vb.y1 + tdy, CY = me.vb.cy + tdy;
      let bestX = null, bestY = null;
      view.groups.forEach((o) => {
        if (o.sid === drag.sid) return;
        [[L, o.vb.x0], [L, o.vb.x1], [R, o.vb.x0], [R, o.vb.x1], [CX, o.vb.cx]].forEach(([cur, tgt]) => {
          const d = tgt - cur; if (Math.abs(d) <= SNAP && (bestX == null || Math.abs(d) < Math.abs(bestX.d))) bestX = { d, at: tgt };
        });
        [[T, o.vb.y0], [T, o.vb.y1], [B, o.vb.y0], [B, o.vb.y1], [CY, o.vb.cy]].forEach(([cur, tgt]) => {
          const d = tgt - cur; if (Math.abs(d) <= SNAP && (bestY == null || Math.abs(d) < Math.abs(bestY.d))) bestY = { d, at: tgt };
        });
      });
      if (bestX) { tdx += bestX.d; guides.push({ x: bestX.at }); }
      if (bestY) { tdy += bestY.d; guides.push({ y: bestY.at }); }
    }
    setDrag((d) => d ? { ...d, tvbx: tdx, tvby: tdy, guides } : d);
  }, [drag, view]);

  const commitDrag = useCallback(() => {
    if (!drag || !view) { setDrag(null); return; }
    const dFeetX = drag.tvbx / view.scale, dFeetY = drag.tvby / view.scale;
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

  // Build a standalone SVG string for one structure's own roof sketch (for the per-structure PDF pages).
  const structurePng = useCallback(async (sid, label) => {
    const sf = facets.filter((f) => String(f.structure_id) === String(sid));
    if (!sf.length) return null;
    const ids = new Set(sf.map((f) => String(f.id)));
    const se = edges.filter((e) => ids.has(String(e.facet_id)) || ids.has(String(e.facet_id_secondary)));
    const sp = penetrations.filter((p) => ids.has(String(p.facet_id)));
    let res; try { res = generateSketchGeometry({ structure: { id: sid }, facets: sf, edges: se, penetrations: sp }); } catch (e) { return null; }
    const doc = res && res.document;
    if (!doc || !(doc.vertices || []).length || !(doc.facets || []).length) return null;
    const PW = 900, PH = 560, P = 40;
    const xs = doc.vertices.map((v) => v.x), ys = doc.vertices.map((v) => v.y);
    const mnx = Math.min(...xs), mxx = Math.max(...xs), mny = Math.min(...ys), mxy = Math.max(...ys);
    const sx = Math.max(mxx - mnx, 1e-6), sy = Math.max(mxy - mny, 1e-6);
    const sc = Math.min((PW - 2 * P) / sx, (PH - 2 * P - 30) / sy);
    const ox = (PW - sx * sc) / 2, oy = (PH - 30 - sy * sc) / 2 + 30;
    const mp = (x, y) => [(ox + (x - mnx) * sc).toFixed(1), (oy + (y - mny) * sc).toFixed(1)];
    const vb = {}; doc.vertices.forEach((v) => { vb[v.id] = mp(v.x, v.y); });
    let body = `<rect x="0" y="0" width="${PW}" height="${PH}" fill="#ffffff"/>`;
    body += `<text x="${P}" y="26" fill="#0f172a" font-size="18" font-weight="700" font-family="Arial">${label}</text>`;
    doc.facets.forEach((f) => {
      const pts = (resolveFacetBoundary(doc, f).points || []).map(([x, y]) => mp(x, y).join(",")).join(" ");
      if (pts) body += `<polygon points="${pts}" fill="rgba(148,163,184,0.16)" stroke="none"/>`;
    });
    doc.edges.forEach((e) => { const a = vb[e.v1], b = vb[e.v2]; if (a && b) body += `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="${EDGE_COLOR[e.type] || "#94a3b8"}" stroke-width="2.2" stroke-linecap="round"/>`; });
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${PW}" height="${PH}" viewBox="0 0 ${PW} ${PH}">${body}</svg>`;
    return await new Promise((resolve) => {
      const img = new Image();
      img.onload = () => { const cv = document.createElement("canvas"); cv.width = PW * 2; cv.height = PH * 2; const cx = cv.getContext("2d"); cx.fillStyle = "#fff"; cx.fillRect(0, 0, cv.width, cv.height); cx.drawImage(img, 0, 0, cv.width, cv.height); resolve({ dataUrl: cv.toDataURL("image/png"), w: cv.width, h: cv.height }); };
      img.onerror = () => resolve(null);
      img.src = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svg)));
    });
  }, [facets, edges, penetrations]);

  const exportPdf = useCallback(async () => {
    try {
      const c = await rasterize();
      const dataUrl = c.toDataURL("image/png");
      const { jsPDF } = await import("jspdf");
      const pdf = new jsPDF({ orientation: "landscape", unit: "pt", format: "letter" });
      const pw = pdf.internal.pageSize.getWidth(), ph = pdf.internal.pageSize.getHeight(), m = 36;
      // ---- Title block ----
      pdf.setDrawColor(203, 213, 225); pdf.setLineWidth(1); pdf.rect(m, m, pw - 2 * m, 58);
      pdf.setFontSize(17); pdf.setTextColor(15, 23, 42); pdf.text("Combined Site Plan", m + 12, m + 24);
      pdf.setFontSize(10); pdf.setTextColor(71, 85, 105);
      if (propertyAddress) pdf.text(propertyAddress, m + 12, m + 42);
      const dstr = new Date().toLocaleDateString();
      pdf.setFontSize(9); pdf.setTextColor(100, 116, 139);
      const right = [`Date: ${dstr}`, preparedBy ? `Prepared by: ${preparedBy}` : null, `${combined.placed_count} structure(s) · scale bar = ${view.barFt} ft · North ↑`].filter(Boolean);
      right.forEach((line, i) => pdf.text(line, pw - m - 12, m + 20 + i * 13, { align: "right" }));
      // ---- Combined plan image ----
      const top = m + 58 + 12;
      const availW = pw - 2 * m, availH = ph - top - m;
      const ratio = Math.min(availW / c.width, availH / c.height);
      pdf.addImage(dataUrl, "PNG", (pw - c.width * ratio) / 2, top, c.width * ratio, c.height * ratio);
      // ---- One page per placed structure ----
      for (const pl of (combined.placements || [])) {
        const png = await structurePng(pl.structure_id, pl.label);
        if (!png) continue;
        pdf.addPage("letter", "landscape");
        pdf.setFontSize(13); pdf.setTextColor(15, 23, 42); pdf.text(`${pl.label} — roof sketch`, m, m + 4);
        pdf.setFontSize(9); pdf.setTextColor(100, 116, 139); pdf.text(`${Math.round(pl.bbox.width)}′ × ${Math.round(pl.bbox.height)}′`, pw - m, m + 4, { align: "right" });
        const t2 = m + 16, aW = pw - 2 * m, aH = ph - t2 - m;
        const r2 = Math.min(aW / png.w, aH / png.h);
        pdf.addImage(png.dataUrl, "PNG", (pw - png.w * r2) / 2, t2, png.w * r2, png.h * r2);
      }
      pdf.save("site-plan.pdf");
    } catch (e) { toast.error("Could not export the site plan as PDF"); }
  }, [combined, view, propertyAddress, preparedBy, structurePng]);

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
          const t = drag && drag.sid === g.sid ? `translate(${drag.tvbx} ${drag.tvby})` : undefined;
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
        {/* Snap guides while dragging */}
        {drag && (drag.guides || []).map((gd, i) => gd.x != null
          ? <line key={`sgx${i}`} data-testid="site-plan-snap-guide" x1={gd.x} y1={0} x2={gd.x} y2={VB_H} stroke="#2563eb" strokeWidth={1} strokeDasharray="4 3" pointerEvents="none" />
          : <line key={`sgy${i}`} data-testid="site-plan-snap-guide" x1={0} y1={gd.y} x2={VB_W} y2={gd.y} stroke="#2563eb" strokeWidth={1} strokeDasharray="4 3" pointerEvents="none" />)}
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

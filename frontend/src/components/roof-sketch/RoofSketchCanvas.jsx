import { useEffect, useMemo, useRef, useState } from "react";
import { resolveFacetBoundary, validateSketch } from "@roofspan/roof-sketch-core";
import { Button } from "@/components/ui/button";
import { addVertex, addEdge, moveVertex, splitEdge, createFacet, createManualFacet, placePenetration, movePenetration } from "./commands";

const EDGE_COLOR = { eave: "#2563eb", rake: "#7c3aed", ridge: "#dc2626", hip: "#ea580c", valley: "#0891b2", sidewall: "#16a34a", headwall: "#ca8a04", transition: "#db2777", unclassified: "#94a3b8" };

// Native SVG roof-sketch canvas: zoom/pan, select, connected-graph draw, facet creation, penetrations,
// shared-vertex drag, snapping, and validation markers. All model mutations go through pure commands.
export default function RoofSketchCanvas({ doc, editMode, mode, selection, onSelect, readOnly, ctl }) {
  const svgRef = useRef(null);
  const [view, setView] = useState({ k: 6, tx: 60, ty: 60 });
  const drag = useRef(null); // { vertexId, startDoc } | { pan:true, ... }
  const lastVertex = useRef(null); // draw chaining
  const [pendingEdges, setPendingEdges] = useState([]); // facet-tool selection
  const [pendingVerts, setPendingVerts] = useState([]); // manual polygon ring

  useEffect(() => { lastVertex.current = null; setPendingEdges([]); setPendingVerts([]); }, [mode, editMode]);

  const validation = useMemo(() => validateSketch(doc), [doc]);
  const errorFacetIds = new Set(validation.errors.filter((e) => e.facet_id).map((e) => e.facet_id));

  const toModel = (clientX, clientY) => {
    const r = svgRef.current.getBoundingClientRect();
    return { x: (clientX - r.left - view.tx) / view.k, y: (clientY - r.top - view.ty) / view.k };
  };
  const snapPx = 12;
  const snapVertex = (mx, my) => {
    let best = null, bd = (snapPx / view.k);
    for (const v of doc.vertices || []) {
      const d = Math.hypot(v.x - mx, v.y - my);
      if (d <= bd) { bd = d; best = v; }
    }
    return best;
  };

  const onWheel = (e) => {
    e.preventDefault();
    const r = svgRef.current.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    setView((v) => {
      const k = Math.min(80, Math.max(0.5, v.k * factor));
      return { k, tx: px - ((px - v.tx) * k) / v.k, ty: py - ((py - v.ty) * k) / v.k };
    });
  };

  const backgroundDown = (e) => {
    if (e.target.dataset.role) return; // handled by element handlers
    const m = toModel(e.clientX, e.clientY);
    if (mode === "select" || readOnly) {
      drag.current = { pan: true, sx: e.clientX, sy: e.clientY, tx: view.tx, ty: view.ty };
      onSelect(null);
      return;
    }
    if (mode === "draw") {
      const snapped = snapVertex(m.x, m.y);
      if (editMode === "manual_polygon") {
        const v = snapped || null;
        const res = ctl.run((d) => (v ? { doc: d, vertexId: v.id } : addVertex(d, m.x, m.y)));
        setPendingVerts((p) => [...p, res.vertexId]);
        return;
      }
      // connected graph: add a vertex (or reuse snapped) and chain an edge from the previous point
      const prev = lastVertex.current;
      const res = ctl.run((d) => {
        let nd = d, vid;
        if (snapped) { vid = snapped.id; } else { const a = addVertex(d, m.x, m.y); nd = a.doc; vid = a.vertexId; }
        if (prev && prev !== vid) { const b = addEdge(nd, prev, vid); if (b.doc) nd = b.doc; }
        return { doc: nd, vertexId: vid };
      });
      lastVertex.current = res.vertexId;
      onSelect({ type: "vertex", id: res.vertexId });
      return;
    }
    if (mode === "penetration") {
      const res = ctl.run((d) => placePenetration(d, m.x, m.y));
      onSelect({ type: "penetration", id: res.penetrationId });
    }
  };

  const vertexDown = (e, v) => {
    e.stopPropagation();
    onSelect({ type: "vertex", id: v.id });
    if (mode === "draw" && editMode === "connected_graph" && !readOnly) {
      // connect chain to this existing vertex
      if (lastVertex.current && lastVertex.current !== v.id) ctl.run((d) => { const b = addEdge(d, lastVertex.current, v.id); return { doc: b.doc || d }; });
      lastVertex.current = v.id;
      return;
    }
    if (mode === "draw" && editMode === "manual_polygon") { setPendingVerts((p) => [...p, v.id]); return; }
    if (mode === "select" && !readOnly) drag.current = { vertexId: v.id, startDoc: ctl.getDoc() };
  };

  const edgeClick = (e, edge) => {
    e.stopPropagation();
    if (mode === "facet" && !readOnly) {
      setPendingEdges((p) => (p.includes(edge.id) ? p.filter((x) => x !== edge.id) : [...p, edge.id]));
      return;
    }
    onSelect({ type: "edge", id: edge.id });
  };

  const edgeDouble = (e, edge) => {
    e.stopPropagation();
    if (readOnly || mode !== "select") return;
    const m = toModel(e.clientX, e.clientY);
    ctl.run((d) => ({ doc: splitEdge(d, edge.id, m.x, m.y) }));
  };

  const onMove = (e) => {
    if (!drag.current) return;
    if (drag.current.pan) {
      setView((v) => ({ ...v, tx: drag.current.tx + (e.clientX - drag.current.sx), ty: drag.current.ty + (e.clientY - drag.current.sy) }));
      return;
    }
    if (drag.current.vertexId) {
      const m = toModel(e.clientX, e.clientY);
      const snapped = snapVertex(m.x, m.y);
      const tx2 = snapped && snapped.id !== drag.current.vertexId ? snapped.x : m.x;
      const ty2 = snapped && snapped.id !== drag.current.vertexId ? snapped.y : m.y;
      ctl.preview(moveVertex(ctl.getDoc(), drag.current.vertexId, tx2, ty2));
    }
    if (drag.current.penId) {
      const m = toModel(e.clientX, e.clientY);
      ctl.preview(movePenetration(ctl.getDoc(), drag.current.penId, m.x, m.y));
    }
  };

  const onUp = () => {
    if (drag.current && (drag.current.vertexId || drag.current.penId)) ctl.commitFrom(drag.current.startDoc, ctl.getDoc());
    drag.current = null;
  };

  const commitFacet = () => {
    if (editMode === "manual_polygon") {
      if (pendingVerts.length >= 3) { ctl.run((d) => createManualFacet(d, pendingVerts)); setPendingVerts([]); lastVertex.current = null; }
    } else if (pendingEdges.length >= 3) {
      ctl.run((d) => createFacet(d, pendingEdges)); setPendingEdges([]);
    }
  };

  // rendering ----------------------------------------------------------------
  const vmap = {}; (doc.vertices || []).forEach((v) => (vmap[v.id] = v));
  const facetPolys = (doc.facets || []).map((f) => {
    const res = resolveFacetBoundary(doc, f);
    return res.points.length >= 3 ? { f, pts: res.points, bad: errorFacetIds.has(f.id) } : null;
  }).filter(Boolean);

  const showCommit = (mode === "facet" && !readOnly) || (mode === "draw" && editMode === "manual_polygon" && !readOnly);
  const canCommit = editMode === "manual_polygon" ? pendingVerts.length >= 3 : pendingEdges.length >= 3;

  return <div className="relative h-full w-full overflow-hidden rounded-md border border-slate-200 bg-slate-50" data-testid="roof-sketch-canvas">
    <svg ref={svgRef} className="h-full w-full" style={{ cursor: mode === "select" ? "default" : "crosshair", touchAction: "none" }}
      onWheel={onWheel} onPointerDown={backgroundDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={onUp}>
      <defs>
        <pattern id="rsgrid" width={view.k} height={view.k} patternUnits="userSpaceOnUse" x={view.tx} y={view.ty}>
          <path d={`M ${view.k} 0 L 0 0 0 ${view.k}`} fill="none" stroke="#e2e8f0" strokeWidth="1" />
        </pattern>
      </defs>
      <rect x="0" y="0" width="100%" height="100%" fill="url(#rsgrid)" />
      <g transform={`translate(${view.tx},${view.ty}) scale(${view.k})`}>
        {facetPolys.map(({ f, pts, bad }) => {
          const centroid = pts.reduce((a, p) => [a[0] + p[0], a[1] + p[1]], [0, 0]).map((c) => c / pts.length);
          const selected = selection?.type === "facet" && selection.id === f.id;
          return <g key={f.id} data-role="facet" onPointerDown={(e) => { e.stopPropagation(); onSelect({ type: "facet", id: f.id }); }}>
            <polygon data-role="facet" points={pts.map((p) => p.join(",")).join(" ")}
              fill={bad ? "rgba(244,63,94,0.14)" : selected ? "rgba(37,99,235,0.20)" : "rgba(148,163,184,0.14)"}
              stroke={selected ? "#2563eb" : "transparent"} strokeWidth="2" vectorEffect="non-scaling-stroke" style={{ cursor: "pointer" }} />
            <text data-role="facet" x={centroid[0]} y={centroid[1]} textAnchor="middle" fontSize="11" fill="#334155"
              style={{ fontSize: 11 / view.k, pointerEvents: "none" }}>{f.label || f.id}{f.pitch_rise ? ` · ${f.pitch_rise}/12` : ""}</text>
          </g>;
        })}
        {(doc.edges || []).map((e) => {
          const a = vmap[e.v1], b = vmap[e.v2]; if (!a || !b) return null;
          const selected = selection?.type === "edge" && selection.id === e.id;
          const pending = pendingEdges.includes(e.id);
          return <line key={e.id} data-role="edge" x1={a.x} y1={a.y} x2={b.x} y2={b.y}
            stroke={pending ? "#f59e0b" : selected ? "#111827" : (EDGE_COLOR[e.type] || EDGE_COLOR.unclassified)}
            strokeWidth={selected || pending ? 4 : 2.5} strokeLinecap="round" vectorEffect="non-scaling-stroke"
            onPointerDown={(ev) => edgeClick(ev, e)} onDoubleClick={(ev) => edgeDouble(ev, e)} style={{ cursor: "pointer" }} />;
        })}
        {(doc.vertices || []).map((v) => {
          const selected = selection?.type === "vertex" && selection.id === v.id;
          const isLast = lastVertex.current === v.id;
          return <circle key={v.id} data-role="vertex" cx={v.x} cy={v.y} r={5 / view.k}
            fill={selected ? "#2563eb" : isLast ? "#f59e0b" : "#ffffff"} stroke="#1e293b" strokeWidth="1.5" vectorEffect="non-scaling-stroke"
            onPointerDown={(e) => vertexDown(e, v)} style={{ cursor: mode === "select" ? "move" : "pointer" }} />;
        })}
        {(doc.penetrations || []).map((p) => {
          const selected = selection?.type === "penetration" && selection.id === p.id;
          return <g key={p.id} data-role="pen"
            onPointerDown={(e) => { e.stopPropagation(); onSelect({ type: "penetration", id: p.id }); if (mode === "select" && !readOnly) drag.current = { penId: p.id, startDoc: ctl.getDoc() }; }}>
            <rect data-role="pen" x={p.x - 5 / view.k} y={p.y - 5 / view.k} width={10 / view.k} height={10 / view.k}
              fill={selected ? "#2563eb" : "#0f766e"} stroke="#ffffff" strokeWidth="1.5" vectorEffect="non-scaling-stroke" style={{ cursor: "pointer" }} />
          </g>;
        })}
      </g>
    </svg>

    <div className="absolute right-2 top-2 flex flex-col gap-1">
      <Button size="icon" variant="outline" className="h-7 w-7" onClick={() => setView((v) => ({ ...v, k: Math.min(80, v.k * 1.2) }))} data-testid="zoom-in">+</Button>
      <Button size="icon" variant="outline" className="h-7 w-7" onClick={() => setView((v) => ({ ...v, k: Math.max(0.5, v.k / 1.2) }))} data-testid="zoom-out">−</Button>
      <Button size="icon" variant="outline" className="h-7 w-7 text-[10px]" onClick={() => setView({ k: 6, tx: 60, ty: 60 })} data-testid="zoom-reset">Fit</Button>
    </div>

    {mode === "draw" && !readOnly && <div className="absolute left-2 top-2 rounded bg-white/90 px-2 py-1 text-[11px] text-slate-600 shadow" data-testid="draw-hint">
      {editMode === "manual_polygon" ? "Click to add polygon points, then Close polygon." : "Click to drop connected vertices. Click an existing point to close a loop. Esc ends the chain."}
    </div>}
    {showCommit && <div className="absolute bottom-2 left-2"><Button size="sm" disabled={!canCommit} onClick={commitFacet} data-testid="create-facet-btn">{editMode === "manual_polygon" ? `Close polygon (${pendingVerts.length})` : `Create facet from ${pendingEdges.length} edges`}</Button></div>}
    {(doc.vertices || []).length === 0 && <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-center text-sm text-slate-400" data-testid="canvas-empty">
      <div>Empty sketch.<br />Pick the <b>Draw</b> tool and click to place roof corners.</div>
    </div>}
  </div>;
}

// Field Roof Sketch touch canvas (React Native + react-native-svg). ALL geometry/topology/snap/history
// math is delegated to @roofspan/roof-sketch-core via the parent screen's editor + the shared engine —
// this component only turns touches into shared-engine calls and renders. No local algorithms.
import React, { useRef, useState, useCallback } from "react";
import { View, PanResponder } from "react-native";
import Svg, { G, Line, Polygon, Circle, Rect, Text as SvgText } from "react-native-svg";
import * as RS from "@roofspan/roof-sketch-core";
import * as VIEW from "../roofSketchView";
import { C } from "../theme";

const EDGE_COLORS = {
  unclassified: "#94A3B8", eave: "#2563EB", rake: "#7C3AED", ridge: "#DC2626",
  hip: "#EA580C", valley: "#0891B2", sidewall: "#059669", headwall: "#CA8A04", transition: "#DB2777",
};
const SNAP_PX = 14;

export default function RoofSketchCanvas({
  editor, tool, editMode, readOnly, selection, onSelect, onChanged, onError, canvasSize,
}) {
  const { width, height } = canvasSize;
  const [view, setView] = useState(() => VIEW.fitToViewport(VIEW.documentPoints(editor.document), { width, height }));
  const [snap, setSnap] = useState(null);
  const [, force] = useState(0);
  const rerender = useCallback(() => force((x) => x + 1), []);

  const gesture = useRef({ mode: null, startDoc: null, dragVertexId: null, lastVertexId: null, pinchDist: 0, panLast: null });

  const toModel = (sx, sy) => VIEW.screenToModel([sx, sy], view);
  const tol = () => RS.modelTolerance(SNAP_PX, view.scale);

  const commit = (doc) => { editor.commit(doc); onChanged && onChanged(); rerender(); };
  const preview = (doc) => { editor.preview(doc); rerender(); };
  const restore = () => { editor.restore(); setSnap(null); rerender(); };

  const handleTap = (sx, sy) => {
    const m = toModel(sx, sy);
    if (tool === "select") return selectAt(m);
    if (readOnly) return;
    if (tool === "penetration") { const r = RS.placePenetration(editor.document, m[0], m[1]); commit(r.doc); onSelect && onSelect({ type: "penetration", id: r.penetrationId }); return; }
    if (tool === "facet") { pickFacetEdge(m); return; }
    if (tool === "draw") return drawAt(m);
  };

  const drawAt = (m) => {
    if (editMode === "manual_polygon") {
      const cand = RS.drawSnap(editor.document, m, tol(), { manual: true });
      let doc = editor.document, vid;
      if (cand.type === "vertex") vid = cand.vertexId;
      else { const a = RS.addVertex(doc, cand.point[0], cand.point[1]); doc = a.doc; vid = a.vertexId; }
      gesture.current.manualVertexIds = [...(gesture.current.manualVertexIds || []), vid];
      commit(doc);
      return;
    }
    const cand = RS.drawSnap(editor.document, m, tol());
    if (cand.type === "blocked") { onError && onError("This edge is mapped, confirmed, or locked and cannot be changed."); return; }
    const r = RS.applyDrawPoint(editor.document, cand, gesture.current.lastVertexId);
    if (!r.ok) { onError && onError(r.reason); return; }
    gesture.current.lastVertexId = r.vertexId;
    commit(r.doc);
  };

  const pickFacetEdge = (m) => {
    const cand = RS.snapTarget(editor.document, m, tol());
    if (cand.type !== "edge") return;
    const set = new Set(gesture.current.facetEdges || []);
    set.has(cand.edgeId) ? set.delete(cand.edgeId) : set.add(cand.edgeId);
    gesture.current.facetEdges = [...set];
    onSelect && onSelect({ type: "facet_build", edgeIds: gesture.current.facetEdges });
    rerender();
  };

  const selectAt = (m) => {
    const t = tol();
    for (const v of editor.document.vertices || []) if (Math.hypot(m[0] - v.x, m[1] - v.y) <= t) return onSelect && onSelect({ type: "vertex", id: v.id });
    for (const p of editor.document.penetrations || []) if (Math.hypot(m[0] - p.x, m[1] - p.y) <= t) return onSelect && onSelect({ type: "penetration", id: p.id });
    const eCand = RS.snapTarget(editor.document, m, t, { eligibleEdge: () => true });
    if (eCand.type === "edge") return onSelect && onSelect({ type: "edge", id: eCand.edgeId });
    for (const f of editor.document.facets || []) {
      const res = RS.resolveFacetBoundary(editor.document, f);
      if (!res.error && res.points.length >= 3 && pointInPoly(m, res.points)) return onSelect && onSelect({ type: "facet", id: f.id });
    }
    onSelect && onSelect(null);
  };

  const startVertexDrag = (m) => {
    const t = tol();
    for (const v of editor.document.vertices || []) {
      if (Math.hypot(m[0] - v.x, m[1] - v.y) <= t) { gesture.current.dragVertexId = v.id; gesture.current.startDoc = editor.document; return true; }
    }
    for (const p of editor.document.penetrations || []) {
      if (Math.hypot(m[0] - p.x, m[1] - p.y) <= t) { gesture.current.dragPenId = p.id; gesture.current.startDoc = editor.document; return true; }
    }
    return false;
  };

  const pan = createResponder();

  function createResponder() {
    return PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderGrant: (e) => {
        const t = e.nativeEvent.touches;
        if (t.length >= 2) { gesture.current.mode = "pinch"; gesture.current.pinchDist = VIEW.touchDistance([t[0].locationX, t[0].locationY], [t[1].locationX, t[1].locationY]); return; }
        const { locationX: sx, locationY: sy } = e.nativeEvent;
        gesture.current.panLast = [sx, sy];
        if (tool === "pan" || readOnly) { gesture.current.mode = "pan"; return; }
        if (tool === "select" && startVertexDrag(toModel(sx, sy))) { gesture.current.mode = "drag"; return; }
        gesture.current.mode = "tap"; gesture.current.tapAt = [sx, sy];
      },
      onPanResponderMove: (e, gs) => {
        const t = e.nativeEvent.touches;
        if (t.length >= 2) {
          const p1 = [t[0].locationX, t[0].locationY], p2 = [t[1].locationX, t[1].locationY];
          const d = VIEW.touchDistance(p1, p2), mid = VIEW.touchMidpoint(p1, p2);
          if (gesture.current.pinchDist > 0) setView((v) => VIEW.zoomAround(v, mid, d / gesture.current.pinchDist));
          gesture.current.pinchDist = d; gesture.current.mode = "pinch"; return;
        }
        const { locationX: sx, locationY: sy } = e.nativeEvent;
        if (gesture.current.mode === "pan") {
          const last = gesture.current.panLast || [sx, sy];
          setView((v) => VIEW.pan(v, sx - last[0], sy - last[1])); gesture.current.panLast = [sx, sy]; return;
        }
        if (gesture.current.mode === "drag") {
          const m = toModel(sx, sy);
          if (gesture.current.dragVertexId) {
            const cand = RS.dragSnap(editor.document, gesture.current.dragVertexId, m, tol());
            setSnap(cand);
            preview(RS.moveVertex(gesture.current.startDoc, gesture.current.dragVertexId, cand.type === "free" ? m[0] : cand.point[0], cand.type === "free" ? m[1] : cand.point[1]));
          } else if (gesture.current.dragPenId) {
            preview(RS.movePenetration(gesture.current.startDoc, gesture.current.dragPenId, m[0], m[1]));
          }
        }
      },
      onPanResponderRelease: (e) => {
        const g = gesture.current;
        if (g.mode === "tap" && g.tapAt) { handleTap(g.tapAt[0], g.tapAt[1]); }
        else if (g.mode === "drag" && g.dragVertexId) {
          const r = RS.applyVertexDrop(g.startDoc, g.dragVertexId, g.snapCandidate || snap || { type: "free", point: toModel(e.nativeEvent.locationX, e.nativeEvent.locationY) });
          if (r.ok) { editor.commitFrom(g.startDoc, r.doc); onChanged && onChanged(); } else { restore(); onError && onError(r.reason); }
        }
        else if (g.mode === "drag" && g.dragPenId) { editor.commitFrom(g.startDoc, editor.document); onChanged && onChanged(); }
        setSnap(null);
        gesture.current = { mode: null, startDoc: null, dragVertexId: null, dragPenId: null, lastVertexId: g.lastVertexId, manualVertexIds: g.manualVertexIds, facetEdges: g.facetEdges };
        rerender();
      },
    });
  }

  // ---- render ----
  const doc = editor.document;
  const validation = RS.validateSketch(doc);
  const invalidFacets = new Set((validation.errors || []).filter((x) => x.facet_id).map((x) => x.facet_id));
  const sp = (p) => VIEW.modelToScreen(p, view);
  const buildEdges = new Set((selection && selection.type === "facet_build" && selection.edgeIds) || gesture.current.facetEdges || []);

  return (
    <View testID="roof-sketch-canvas" style={{ width, height, backgroundColor: "#0B1220" }} {...pan.panHandlers}>
      <Svg width={width} height={height}>
        {/* facets */}
        <G>
          {(doc.facets || []).map((f) => {
            const res = RS.resolveFacetBoundary(doc, f);
            if (res.error || res.points.length < 3) return null;
            const pts = res.points.map(sp).map((p) => `${p[0]},${p[1]}`).join(" ");
            const bad = invalidFacets.has(f.id);
            const c = res.points.map(sp).reduce((a, p) => [a[0] + p[0] / res.points.length, a[1] + p[1] / res.points.length], [0, 0]);
            return (
              <G key={f.id}>
                <Polygon points={pts} fill={bad ? "rgba(220,38,38,0.18)" : (selection && selection.id === f.id ? "rgba(234,88,12,0.25)" : "rgba(37,99,235,0.14)")} stroke="none" />
                <SvgText x={c[0]} y={c[1]} fill="#E2E8F0" fontSize="12" textAnchor="middle">{`${f.label || "F"} · ${f.pitch_rise || 0}/12`}</SvgText>
              </G>
            );
          })}
        </G>
        {/* edges + dimensions */}
        <G>
          {(doc.edges || []).map((e) => {
            const a = RS.vById(doc, e.v1), b = RS.vById(doc, e.v2);
            if (!a || !b) return null;
            const pa = sp([a.x, a.y]), pb = sp([b.x, b.y]);
            const sel = selection && selection.id === e.id;
            const inBuild = buildEdges.has(e.id);
            const dim = RS.edgeDimension(doc, e);
            const mid = [(pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2];
            return (
              <G key={e.id}>
                <Line x1={pa[0]} y1={pa[1]} x2={pb[0]} y2={pb[1]} stroke="transparent" strokeWidth={22} />
                <Line x1={pa[0]} y1={pa[1]} x2={pb[0]} y2={pb[1]} stroke={inBuild ? C.brand : (sel ? "#FDE68A" : (EDGE_COLORS[e.type] || EDGE_COLORS.unclassified))} strokeWidth={sel || inBuild ? 4 : 2.5} />
                {dim.valueFeet != null ? (
                  <SvgText x={mid[0]} y={mid[1] - 4} fill={dim.locked ? "#FBBF24" : "#CBD5E1"} fontSize="11" textAnchor="middle">
                    {(dim.locked ? "🔒 " : "") + RS.formatFeet(dim.valueFeet)}
                  </SvgText>
                ) : null}
              </G>
            );
          })}
        </G>
        {/* vertices */}
        <G>
          {(doc.vertices || []).map((v) => {
            const p = sp([v.x, v.y]);
            const sel = selection && selection.id === v.id;
            return <Circle key={v.id} cx={p[0]} cy={p[1]} r={sel ? 7 : 5} fill={sel ? C.brand : "#E2E8F0"} stroke="#0B1220" strokeWidth={1.5} />;
          })}
        </G>
        {/* penetrations */}
        <G>
          {(doc.penetrations || []).map((pn) => {
            const p = sp([pn.x, pn.y]);
            const sel = selection && selection.id === pn.id;
            return <Rect key={pn.id} x={p[0] - 6} y={p[1] - 6} width={12} height={12} fill={sel ? C.brand : "#F59E0B"} stroke="#0B1220" strokeWidth={1.5} />;
          })}
        </G>
        {/* live snap marker (non-interactive) */}
        {snap ? (() => {
          const p = sp(snap.point);
          const color = snap.type === "vertex" ? "#22C55E" : snap.type === "edge" ? "#22D3EE" : snap.type === "blocked" ? "#EF4444" : "#94A3B8";
          return <Circle cx={p[0]} cy={p[1]} r={9} fill="none" stroke={color} strokeWidth={2.5} />;
        })() : null}
      </Svg>
    </View>
  );

  function pointInPoly(pt, poly) {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
      if (((yi > pt[1]) !== (yj > pt[1])) && (pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi)) inside = !inside;
    }
    return inside;
  }
}

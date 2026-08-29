// Field Roof Sketch screen — orchestrates load (local-draft authoritative), the touch canvas, the
// inspector, tools, undo/redo, validation, and HONEST on-device draft status. Uses the pure wiring
// adapters so the production paths are the ones under contract. B2A = LOCAL draft only (no PUT — B3).
import React, { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { View, Text, TouchableOpacity, StyleSheet, ScrollView, Alert } from "react-native";
import * as RS from "@roofspan/roof-sketch-core";
import { createFieldEditor } from "../roofSketchFieldController";
import * as WIRE from "../roofSketchFieldWiring";
import { loadSketchDraft, saveSketchDraftStrict, cache } from "../cache";
import RoofSketchCanvas from "../components/RoofSketchCanvas";
import SketchInspector from "../components/SketchInspector";
import { C } from "../theme";

const TOOLS = [["select", "Select"], ["draw", "Draw"], ["facet", "Facet"], ["penetration", "Roof feature"], ["pan", "Pan"]];

export default function RoofSketch({ route }) {
  const { revision_id, structure_id, structure_name = "Roof", editable = true } = route.params || {};
  const readOnly = !editable;
  const [ready, setReady] = useState(false);
  const [tool, setTool] = useState("select");
  const [editMode, setEditMode] = useState("connected_graph");
  const [selection, setSelection] = useState(null);
  const [status, setStatus] = useState(readOnly ? "Locked" : "Loading");
  const [resetToken, setResetToken] = useState(0);
  const [, bump] = useState(0);
  const rerender = useCallback(() => bump((x) => x + 1), []);
  const editorRef = useRef(null);
  const [size, setSize] = useState({ width: 360, height: 480 });

  useEffect(() => {
    let alive = true;
    (async () => {
      const draft = await loadSketchDraft(revision_id, structure_id);
      let sketchResult = null;
      if (!draft) { try { sketchResult = await cache.sketch(revision_id, structure_id); } catch (e) { sketchResult = null; } }
      if (!alive) return;
      const { initial, statusMeta } = WIRE.resolveFieldSketchLoad({ draft, sketchResult, structureId: structure_id });
      editorRef.current = createFieldEditor(WIRE.makeFieldEditorArgs({
        revision_id, structure_id, initial,
        persist: (d) => saveSketchDraftStrict(revision_id, structure_id, d),
      }));
      setEditMode(initial.editMode);
      setStatus(readOnly ? "Locked" : initialStatus(initial, statusMeta));
      setReady(true);
    })();
    return () => { alive = false; if (editorRef.current) editorRef.current.flush(); };
  }, [revision_id, structure_id]);

  const editor = editorRef.current;
  const validation = useMemo(() => (editor ? editor.validate() : { valid: true, errors: [], warnings: [] }), [ready, status, selection]);

  // After any committed edit, drain the serialized chain and report the HONEST result.
  const settle = useCallback(() => {
    if (!editor || readOnly) return;
    setStatus("Saving on device…"); rerender();
    editor.flush().then((res) => setStatus(res && res.ok ? "Saved on device" : "Could not save on device"));
  }, [editor, readOnly, rerender]);

  const onError = (reason) => Alert.alert("Cannot do that", humanReason(reason));

  const doCommit = (arg) => {
    if (!editor || readOnly) return;
    const next = typeof arg === "function" ? arg(editor.document) : arg;
    if (!next || next === editor.document) return;
    editor.commit(next); settle();
  };

  const clearBuild = () => setResetToken((x) => x + 1);
  const changeTool = (t) => { setTool(t); setSelection(null); clearBuild(); };
  const changeMode = (m) => { if (readOnly || !editor) return; setEditMode(m); editor.setEditMode(m); setSelection(null); clearBuild(); settle(); };

  const createFacetFromSelection = () => {
    if (!editor || !selection || selection.type !== "facet_build") return;
    const r = WIRE.commitFacetCreate(editor.document, selection.edgeIds);
    if (!r.ok) { onError(r.reason); return; }
    editor.commit(r.doc); setSelection({ type: "facet", id: r.facetId }); clearBuild(); settle();
  };
  const createManualPolygon = () => {
    if (!editor || !selection || selection.type !== "manual_build") return;
    const r = WIRE.commitManualCreate(editor.document, selection.vertexIds);
    if (!r.ok) { onError(r.reason); return; }
    editor.commit(r.doc); setSelection({ type: "facet", id: r.facetId }); clearBuild(); settle();
  };
  const cancelBuild = () => { setSelection(null); clearBuild(); };
  const retrySave = () => { if (editor) { setStatus("Saving on device…"); editor.retry().then((res) => setStatus(res && res.ok ? "Saved on device" : "Could not save on device")); } };

  if (!ready || !editor) return <View style={sx.centered}><Text style={sx.dim}>{status}…</Text></View>;

  const scaleResolved = editor.document.scale && editor.document.scale.resolved;

  return (
    <View style={sx.container} testID="roof-sketch-screen">
      <View style={sx.statusBar}>
        <Text style={sx.structure} testID="roof-sketch-title">{structure_name}</Text>
        <View style={sx.statusRight}>
          <Text style={sx.status} testID="roof-sketch-status">{status}</Text>
          {status === "Could not save on device" ? <TouchableOpacity testID="retry-save" onPress={retrySave} style={sx.retry}><Text style={sx.retryText}>Retry</Text></TouchableOpacity> : null}
        </View>
      </View>

      <View style={sx.controlRow}>
        <View style={sx.modeToggle}>
          <TouchableOpacity testID="mode-connected" disabled={readOnly} onPress={() => changeMode("connected_graph")} style={[sx.modeBtn, editMode === "connected_graph" && sx.modeOn]}><Text style={[sx.modeText, editMode === "connected_graph" && sx.modeTextOn]}>Connected</Text></TouchableOpacity>
          <TouchableOpacity testID="mode-manual" disabled={readOnly} onPress={() => changeMode("manual_polygon")} style={[sx.modeBtn, editMode === "manual_polygon" && sx.modeOn]}><Text style={[sx.modeText, editMode === "manual_polygon" && sx.modeTextOn]}>Manual</Text></TouchableOpacity>
        </View>
        <View style={sx.modeToggle}>
          <TouchableOpacity testID="undo-btn" disabled={readOnly || !editor.canUndo()} onPress={() => { editor.undo(); settle(); }} style={[sx.modeBtn, (!editor.canUndo()) && sx.disabled]}><Text style={sx.modeText}>Undo</Text></TouchableOpacity>
          <TouchableOpacity testID="redo-btn" disabled={readOnly || !editor.canRedo()} onPress={() => { editor.redo(); settle(); }} style={[sx.modeBtn, (!editor.canRedo()) && sx.disabled]}><Text style={sx.modeText}>Redo</Text></TouchableOpacity>
        </View>
      </View>

      <View style={sx.canvasWrap} onLayout={(e) => { const { width, height } = e.nativeEvent.layout; setSize({ width, height }); }}>
        <RoofSketchCanvas
          editor={editor} tool={tool} editMode={editMode} readOnly={readOnly}
          selection={selection} onSelect={setSelection} onChanged={settle} onError={onError}
          canvasSize={size} resetToken={resetToken}
        />
        {scaleResolved ? null : <Text style={sx.calibHint} testID="calibrate-hint">Calibrate scale to display edge dimensions.</Text>}
      </View>

      {selection && selection.type === "facet_build" ? (
        <View style={sx.buildRow}>
          <TouchableOpacity testID="create-facet" style={[sx.primary, (selection.edgeIds || []).length < 3 && sx.disabled]} disabled={(selection.edgeIds || []).length < 3} onPress={createFacetFromSelection}><Text style={sx.primaryText}>Create Facet ({(selection.edgeIds || []).length})</Text></TouchableOpacity>
          <TouchableOpacity testID="cancel-facet" style={sx.ghost} onPress={cancelBuild}><Text style={sx.ghostText}>Cancel</Text></TouchableOpacity>
        </View>
      ) : null}

      {selection && selection.type === "manual_build" ? (
        <View style={sx.buildRow}>
          <TouchableOpacity testID="create-polygon" style={[sx.primary, (selection.vertexIds || []).length < 3 && sx.disabled]} disabled={(selection.vertexIds || []).length < 3} onPress={createManualPolygon}><Text style={sx.primaryText}>Create Polygon ({(selection.vertexIds || []).length})</Text></TouchableOpacity>
          <TouchableOpacity testID="cancel-polygon" style={sx.ghost} onPress={cancelBuild}><Text style={sx.ghostText}>Cancel</Text></TouchableOpacity>
        </View>
      ) : null}

      {!validation.valid || (validation.warnings || []).length ? (
        <ScrollView horizontal style={sx.validation} testID="validation-panel">
          {(validation.errors || []).map((e, i) => <Text key={"e" + i} style={sx.vErr}>{humanValidation(e.code)}</Text>)}
          {(validation.warnings || []).map((w, i) => <Text key={"w" + i} style={sx.vWarn}>{humanValidation(w.code)}</Text>)}
        </ScrollView>
      ) : null}

      {readOnly ? <Text style={sx.locked} testID="readonly-banner">This measurement revision is locked.</Text> : null}

      <View style={sx.toolStrip}>
        {TOOLS.map(([t, label]) => (
          <TouchableOpacity key={t} testID={`tool-${t}`} disabled={readOnly && t !== "select" && t !== "pan"}
            onPress={() => changeTool(t)} style={[sx.tool, tool === t && sx.toolOn, (readOnly && t !== "select" && t !== "pan") && sx.disabled]}>
            <Text style={[sx.toolText, tool === t && sx.toolTextOn]}>{label}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {selection && ["edge", "facet", "vertex", "penetration"].includes(selection.type) ? (
        <SketchInspector doc={editor.document} selection={selection} readOnly={readOnly}
          onCommit={doCommit} onError={onError} onClose={() => setSelection(null)} />
      ) : null}
    </View>
  );
}

function initialStatus(initial, meta) {
  if (initial.source === "local_draft") return "Saved on device";
  if (initial.source === "server") return meta && meta.stale ? "Offline/cached sketch" : "Loaded from Office";
  return "New sketch";
}
function humanReason(reason) {
  const map = {
    edge_protected: "This edge is mapped, confirmed, or locked and cannot be changed.",
    duplicate_edge_creation: "That would create a duplicate edge.",
    facet_would_be_invalid: "That change would make a facet invalid.",
    connected_graph_required: "Switch to Connected mode for that operation.",
    protected_edge_collapse: "A protected edge would be removed — not allowed.",
    type_conflict: "Choose the resulting edge type before joining.",
    middle_vertex_has_additional_connections: "That vertex has other connections and cannot be joined.",
    duplicate_outer_edge: "Joining would duplicate an existing edge.",
    facet_needs_three_edges: "Select at least 3 edges that form a closed loop.",
    polygon_needs_three_points: "A polygon needs at least 3 points.",
  };
  return map[reason] || "That operation is not allowed here.";
}
function humanValidation(code) {
  const map = {
    open_facet_loop: "Open facet boundary", duplicate_edge: "Duplicate edge", duplicate_facet: "Duplicate facet",
    self_intersection: "Self-intersecting facet", disconnected_component: "Disconnected roof section",
    facet_missing_edges: "Facet needs a closed edge loop", broken_edge_reference: "Facet references a missing edge",
    non_positive_area: "Facet has no area", zero_length_edge: "Zero-length edge", dangling_edge: "Edge missing a vertex",
    possible_overlap: "Facets overlap", possible_gap: "Possible gap between facets", facet_boundary_mismatch: "Facet boundary mismatch",
  };
  return map[code] || code;
}

const sx = StyleSheet.create({
  container: { flex: 1, backgroundColor: C.bg },
  centered: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: C.bg },
  dim: { color: "#94A3B8" },
  statusBar: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: 14, paddingVertical: 8 },
  statusRight: { flexDirection: "row", alignItems: "center", gap: 8 },
  structure: { color: "#fff", fontSize: 16, fontWeight: "800" },
  status: { color: "#94A3B8", fontSize: 12, fontWeight: "600" },
  retry: { backgroundColor: C.danger, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 8 },
  retryText: { color: "#fff", fontWeight: "800", fontSize: 12 },
  controlRow: { flexDirection: "row", justifyContent: "space-between", paddingHorizontal: 12, marginBottom: 6 },
  modeToggle: { flexDirection: "row", backgroundColor: "#1E293B", borderRadius: 10, padding: 3 },
  modeBtn: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8 },
  modeOn: { backgroundColor: C.brand },
  modeText: { color: "#CBD5E1", fontWeight: "700", fontSize: 13 },
  modeTextOn: { color: "#fff" },
  disabled: { opacity: 0.4 },
  canvasWrap: { flex: 1, marginHorizontal: 8, borderRadius: 12, overflow: "hidden" },
  calibHint: { position: "absolute", top: 8, left: 8, color: "#FBBF24", fontSize: 12, backgroundColor: "rgba(0,0,0,0.4)", paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8 },
  buildRow: { flexDirection: "row", padding: 10, gap: 10 },
  primary: { backgroundColor: C.brand, paddingHorizontal: 16, paddingVertical: 12, borderRadius: 10 },
  primaryText: { color: "#fff", fontWeight: "800" },
  ghost: { paddingHorizontal: 16, paddingVertical: 12, borderRadius: 10, borderWidth: 1, borderColor: "#475569" },
  ghostText: { color: "#CBD5E1", fontWeight: "700" },
  validation: { maxHeight: 40, paddingHorizontal: 10 },
  vErr: { color: "#FCA5A5", backgroundColor: "rgba(220,38,38,0.15)", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, marginRight: 8, fontSize: 12, overflow: "hidden" },
  vWarn: { color: "#FDE68A", backgroundColor: "rgba(180,83,9,0.18)", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, marginRight: 8, fontSize: 12, overflow: "hidden" },
  locked: { color: "#FBBF24", textAlign: "center", paddingVertical: 6, fontWeight: "700" },
  toolStrip: { flexDirection: "row", justifyContent: "space-around", paddingVertical: 10, paddingHorizontal: 6, backgroundColor: "#0B1220", borderTopWidth: 1, borderTopColor: "#1E293B" },
  tool: { paddingHorizontal: 12, paddingVertical: 10, borderRadius: 10 },
  toolOn: { backgroundColor: C.brand },
  toolText: { color: "#CBD5E1", fontWeight: "700", fontSize: 13 },
  toolTextOn: { color: "#fff" },
});

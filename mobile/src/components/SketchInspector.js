// Field Roof Sketch inspector (touch-friendly bottom sheet). Delegates every mutation to the shared
// engine via onCommit; join type-conflicts go through the shared attemptJoin adapter. No local math.
import React, { useState } from "react";
import { View, Text, TouchableOpacity, TextInput, ScrollView, StyleSheet } from "react-native";
import * as RS from "@roofspan/roof-sketch-core";
import * as WIRE from "../roofSketchFieldWiring";
import { C } from "../theme";

const EDGE_TYPES = ["unclassified", "eave", "rake", "ridge", "hip", "valley", "sidewall", "headwall", "transition"];
const CLASSIFIED = ["eave", "rake", "ridge", "hip", "valley", "sidewall", "headwall", "transition"];
const PITCHES = [2, 3, 4, 5, 6, 7, 8, 9, 10, 12];
const PEN_TYPES = ["pipe_boot", "static_vent", "skylight", "turbine", "powered_vent", "exhaust_vent", "chimney", "satellite", "other"];

function Chip({ label, active, disabled, onPress, testID }) {
  return (
    <TouchableOpacity testID={testID} disabled={disabled} onPress={onPress}
      style={[st.chip, active && st.chipActive, disabled && st.chipDisabled]}>
      <Text style={[st.chipText, active && st.chipTextActive]}>{label}</Text>
    </TouchableOpacity>
  );
}

export default function SketchInspector({ doc, selection, readOnly, onCommit, onError, onClose }) {
  if (!selection || !selection.type) return null;
  const disabled = !!readOnly;
  const edge = selection.type === "edge" ? RS.eById(doc, selection.id) : null;
  const facet = selection.type === "facet" ? RS.fById(doc, selection.id) : null;
  const vertex = selection.type === "vertex" ? RS.vById(doc, selection.id) : null;
  const pen = selection.type === "penetration" ? (doc.penetrations || []).find((p) => p.id === selection.id) : null;

  return (
    <View testID="sketch-inspector" style={st.sheet}>
      <View style={st.header}>
        <Text style={st.title}>{edge ? "Edge" : facet ? "Facet" : vertex ? "Vertex" : pen ? "Penetration" : "Inspect"}</Text>
        <TouchableOpacity testID="inspector-close" onPress={onClose}><Text style={st.close}>Done</Text></TouchableOpacity>
      </View>
      <ScrollView style={{ maxHeight: 300 }}>
        {edge && <EdgeBody edge={edge} doc={doc} disabled={disabled} onCommit={onCommit} onError={onError} />}
        {facet && <FacetBody facet={facet} doc={doc} disabled={disabled} onCommit={onCommit} />}
        {vertex && <VertexBody vertex={vertex} disabled={disabled} onCommit={onCommit} />}
        {pen && <PenBody pen={pen} disabled={disabled} onCommit={onCommit} />}
      </ScrollView>
    </View>
  );
}

function EdgeBody({ edge, doc, disabled, onCommit, onError }) {
  const [confirmText, setConfirmText] = useState("");
  const [calibText, setCalibText] = useState("");
  const [joinPending, setJoinPending] = useState(null); // { candidateId } awaiting a result type
  const dim = RS.edgeDimension(doc, edge);
  const candidates = joinCandidates(doc, edge);

  const tryJoin = (cid, resultType) => {
    const r = WIRE.attemptJoin(doc, edge.id, cid, resultType);
    if (r.ok) { setJoinPending(null); onCommit(r.doc); return; }
    if (r.needsType) { setJoinPending({ candidateId: cid }); return; }
    setJoinPending(null); onError && onError(r.reason);
  };

  return (
    <View>
      <Text style={st.small}>Type</Text>
      <View style={st.chips}>{EDGE_TYPES.map((t) => (
        <Chip key={t} testID={`edge-type-${t}`} label={t} active={edge.type === t} disabled={disabled}
          onPress={() => onCommit(RS.setEdgeType(doc, edge.id, t))} />))}</View>

      <Text style={st.small}>Geometry LF</Text>
      <Text style={st.value} testID="edge-geometry-lf">{dim.geometryFeet != null ? RS.formatFeet(dim.geometryFeet) : "Calibrate scale to display"}</Text>

      <Text style={st.small}>Confirmed LF</Text>
      <View style={st.row}>
        <TextInput testID="edge-confirmed-input" style={st.input} editable={!disabled} keyboardType="numeric"
          placeholder={edge.confirmed_length_ft != null ? String(edge.confirmed_length_ft) : "measured ft"}
          value={confirmText} onChangeText={setConfirmText} />
        <TouchableOpacity testID="edge-confirmed-set" disabled={disabled} style={st.btn}
          onPress={() => onCommit(RS.setConfirmedEdgeLength(doc, edge.id, confirmText))}><Text style={st.btnText}>Set</Text></TouchableOpacity>
      </View>
      {dim.locked && dim.discrepancy != null ? <Text style={st.warn} testID="edge-discrepancy">Locked {RS.formatFeet(dim.valueFeet)} · geometry differs by {dim.discrepancy > 0 ? "+" : ""}{dim.discrepancy}</Text> : null}

      <View style={st.row}>
        {edge.locked
          ? <TouchableOpacity testID="edge-unlock" disabled={disabled} style={st.btn} onPress={() => onCommit(RS.unlockEdge(doc, edge.id))}><Text style={st.btnText}>Unlock</Text></TouchableOpacity>
          : <TouchableOpacity testID="edge-lock" disabled={disabled} style={st.btn} onPress={() => onCommit(RS.lockEdge(doc, edge.id))}><Text style={st.btnText}>Lock</Text></TouchableOpacity>}
      </View>

      <Text style={st.small}>Calibrate using this edge</Text>
      <View style={st.row}>
        <TextInput testID="edge-calibrate-input" style={st.input} editable={!disabled} keyboardType="numeric" placeholder="known ft" value={calibText} onChangeText={setCalibText} />
        <TouchableOpacity testID="edge-calibrate-set" disabled={disabled} style={st.btn} onPress={() => onCommit(RS.setScale(doc, { edgeId: edge.id, realFeet: Number(calibText) }))}><Text style={st.btnText}>Calibrate</Text></TouchableOpacity>
      </View>

      {candidates.length ? <>
        <Text style={st.small}>Join Edge</Text>
        <View style={st.chips}>{candidates.map((cid) => (
          <Chip key={cid} testID={`edge-join-${cid}`} label={"Join → " + cid.slice(0, 6)} disabled={disabled} onPress={() => tryJoin(cid)} />))}</View>
      </> : null}

      {joinPending ? <View testID="join-type-conflict">
        <Text style={st.warn}>These edges have different types — choose the resulting type:</Text>
        <View style={st.chips}>{CLASSIFIED.map((t) => (
          <Chip key={t} testID={`join-result-${t}`} label={t} disabled={disabled} onPress={() => tryJoin(joinPending.candidateId, t)} />))}</View>
        <TouchableOpacity testID="join-cancel" style={st.ghost} onPress={() => setJoinPending(null)}><Text style={st.ghostText}>Cancel join</Text></TouchableOpacity>
      </View> : null}

      <TouchableOpacity testID="edge-delete" disabled={disabled} style={[st.btn, st.danger]} onPress={() => onCommit(RS.deleteEdge(doc, edge.id))}><Text style={st.btnText}>Delete edge</Text></TouchableOpacity>
    </View>
  );
}

function FacetBody({ facet, doc, disabled, onCommit }) {
  const [label, setLabel] = useState(facet.label || "");
  return (
    <View>
      <Text style={st.small}>Label</Text>
      <View style={st.row}>
        <TextInput testID="facet-label-input" style={st.input} editable={!disabled} value={label} onChangeText={setLabel} />
        <TouchableOpacity testID="facet-label-set" disabled={disabled} style={st.btn} onPress={() => onCommit((d) => RS.setFacetLabel(d, facet.id, label))}><Text style={st.btnText}>Set</Text></TouchableOpacity>
      </View>
      <Text style={st.small}>Pitch</Text>
      <View style={st.chips}>{PITCHES.map((p) => (
        <Chip key={p} testID={`facet-pitch-${p}`} label={`${p}/12`} active={Number(facet.pitch_rise) === p} disabled={disabled}
          onPress={() => onCommit((d) => RS.setFacetPitch(d, facet.id, p))} />))}</View>
      <Text style={st.small}>Orientation</Text>
      <View style={st.chips}>{["N", "E", "S", "W", "NE", "SE", "SW", "NW"].map((o) => (
        <Chip key={o} testID={`facet-orient-${o}`} label={o} active={facet.orientation === o} disabled={disabled}
          onPress={() => onCommit((d) => RS.setFacetOrientation(d, facet.id, o))} />))}</View>
      <TouchableOpacity testID="facet-delete" disabled={disabled} style={[st.btn, st.danger]} onPress={() => onCommit((d) => RS.deleteFacet(d, facet.id))}><Text style={st.btnText}>Delete facet</Text></TouchableOpacity>
    </View>
  );
}

function VertexBody({ vertex, disabled, onCommit }) {
  return (
    <View>
      <Text style={st.small}>X</Text><Text style={st.value}>{Number(vertex.x).toFixed(2)}</Text>
      <Text style={st.small}>Y</Text><Text style={st.value}>{Number(vertex.y).toFixed(2)}</Text>
      <TouchableOpacity testID="vertex-delete" disabled={disabled} style={[st.btn, st.danger]} onPress={() => onCommit((d) => RS.deleteVertex(d, vertex.id))}><Text style={st.btnText}>Delete vertex</Text></TouchableOpacity>
    </View>
  );
}

function PenBody({ pen, disabled, onCommit }) {
  return (
    <View>
      <Text style={st.small}>Type</Text>
      <View style={st.chips}>{PEN_TYPES.map((t) => (
        <Chip key={t} testID={`pen-type-${t}`} label={t} active={pen.pen_type === t} disabled={disabled}
          onPress={() => onCommit((d) => RS.setPenetrationType(d, pen.id, t))} />))}</View>
      <TouchableOpacity testID="pen-delete" disabled={disabled} style={[st.btn, st.danger]} onPress={() => onCommit((d) => RS.deletePenetration(d, pen.id))}><Text style={st.btnText}>Delete penetration</Text></TouchableOpacity>
    </View>
  );
}

// Edges sharing exactly one endpoint with `edge` (plausible adjacency only; joinEdges decides validity).
function joinCandidates(doc, edge) {
  const ends = [edge.v1, edge.v2];
  return (doc.edges || []).filter((o) => o.id !== edge.id && (ends.includes(o.v1) !== ends.includes(o.v2))).map((o) => o.id);
}

const st = StyleSheet.create({
  sheet: { position: "absolute", left: 0, right: 0, bottom: 0, backgroundColor: C.surface, borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 14, borderTopWidth: 1, borderTopColor: C.line },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 },
  title: { fontSize: 18, fontWeight: "800", color: C.ink },
  close: { color: C.brand, fontWeight: "800", fontSize: 16 },
  small: { color: C.sub, fontSize: 12, marginTop: 10, marginBottom: 4, fontWeight: "600" },
  value: { color: C.ink, fontSize: 15, fontWeight: "700" },
  warn: { color: C.warn, fontSize: 13, marginTop: 6 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  input: { flex: 1, borderWidth: 1, borderColor: C.line, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 15, color: C.ink },
  btn: { backgroundColor: C.brand, paddingHorizontal: 16, paddingVertical: 10, borderRadius: 10, marginLeft: 8, marginTop: 8 },
  btnText: { color: "#fff", fontWeight: "800" },
  danger: { backgroundColor: C.danger, marginTop: 14 },
  ghost: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: 10, borderWidth: 1, borderColor: "#94A3B8", marginTop: 8, alignSelf: "flex-start" },
  ghostText: { color: C.sub, fontWeight: "700" },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { borderWidth: 1, borderColor: C.line, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 8, marginRight: 6, marginBottom: 6 },
  chipActive: { backgroundColor: C.brand, borderColor: C.brand },
  chipDisabled: { opacity: 0.4 },
  chipText: { color: C.ink, fontWeight: "600", fontSize: 13 },
  chipTextActive: { color: "#fff" },
});

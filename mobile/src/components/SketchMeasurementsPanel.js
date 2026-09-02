import React, { useState } from "react";
import { View, Text, TouchableOpacity, ScrollView, StyleSheet } from "react-native";
import { C } from "../theme";
const { summarizeStructureMeasurements } = require("../sketchMeasurementsSummary");

const EDGE_LABELS = { eave: "Eave", rake: "Rake", ridge: "Ridge", hip: "Hip", valley: "Valley", sidewall: "Sidewall", headwall: "Headwall", transition: "Transition", other: "Other" };
const PEN_LABELS = { pipe_boot: "Pipe Boot", static_vent: "Static Vent", skylight: "Skylight", turbine: "Turbine", powered_vent: "Powered Vent", exhaust_vent: "Exhaust Vent", chimney: "Chimney", satellite: "Satellite", other: "Other" };
const pitchText = (p) => (p == null ? "—" : `${p}/12`);

// Read-only reference of the measurements entered for THIS structure, so the rep knows what to draw.
export default function SketchMeasurementsPanel({ measDetail, structureId, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const s = summarizeStructureMeasurements(measDetail, structureId);
  const empty = !s.planes.length && !s.lines.length && !s.pens.length;
  return (
    <View style={st.wrap}>
      <TouchableOpacity style={st.toggle} onPress={() => setOpen((v) => !v)} testID="sketch-meas-toggle" accessibilityRole="button">
        <Text style={st.toggleText}>{open ? "▾" : "▸"} Measurements</Text>
        <Text style={st.toggleSub}>{s.totals.area.toFixed(0)} SF · {s.totals.squares.toFixed(2)} sq · {s.totals.planeCount} planes</Text>
      </TouchableOpacity>
      {open ? (
        <ScrollView style={st.body} testID="sketch-meas-panel">
          {empty ? <Text style={st.dim}>No measurements entered for this structure yet.</Text> : null}
          {s.planes.length ? (
            <View style={st.section}>
              <Text style={st.h}>Roof planes</Text>
              {s.planes.map((p) => (
                <View key={String(p.id)} style={st.row} testID={`sketch-meas-plane-${p.id}`}>
                  <Text style={st.rowKey}>{p.label}</Text>
                  <Text style={st.rowVal}>{pitchText(p.pitch_rise)} · {p.area.toFixed(0)} SF{p.width != null && p.length != null ? `  (${p.width}×${p.length})` : ""}</Text>
                </View>
              ))}
            </View>
          ) : null}
          {s.lines.length ? (
            <View style={st.section}>
              <Text style={st.h}>Roof lines</Text>
              {s.lines.map((l) => (
                <View key={l.type} style={st.row} testID={`sketch-meas-line-${l.type}`}>
                  <Text style={st.rowKey}>{EDGE_LABELS[l.type] || l.type}</Text>
                  <Text style={st.rowVal}>{l.lf.toFixed(1)} LF</Text>
                </View>
              ))}
            </View>
          ) : null}
          {s.pens.length ? (
            <View style={st.section}>
              <Text style={st.h}>Penetrations</Text>
              {s.pens.map((p) => (
                <View key={p.type} style={st.row} testID={`sketch-meas-pen-${p.type}`}>
                  <Text style={st.rowKey}>{PEN_LABELS[p.type] || p.type}</Text>
                  <Text style={st.rowVal}>× {p.qty}</Text>
                </View>
              ))}
            </View>
          ) : null}
        </ScrollView>
      ) : null}
    </View>
  );
}

const st = StyleSheet.create({
  wrap: { marginHorizontal: 8, marginBottom: 6, backgroundColor: "#0B1220", borderRadius: 10, borderWidth: 1, borderColor: "#1E293B" },
  toggle: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 12, paddingVertical: 10 },
  toggleText: { color: "#fff", fontWeight: "800", fontSize: 13 },
  toggleSub: { color: "#94A3B8", fontSize: 11, fontWeight: "600" },
  body: { maxHeight: 190, paddingHorizontal: 12, paddingBottom: 10 },
  section: { marginTop: 6 },
  h: { color: C.brand, fontSize: 11, fontWeight: "800", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 4 },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 3 },
  rowKey: { color: "#CBD5E1", fontSize: 13, fontWeight: "600" },
  rowVal: { color: "#E2E8F0", fontSize: 13 },
  dim: { color: "#64748B", fontSize: 12, fontStyle: "italic", paddingVertical: 6 },
});

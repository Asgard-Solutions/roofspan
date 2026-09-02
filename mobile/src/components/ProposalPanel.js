import React from "react";
import { View, Text, TouchableOpacity, StyleSheet, ScrollView } from "react-native";
import { C } from "../theme";

// Phase C — Field Roof Sketch reconciliation panel. Roofing-friendly terminology only (Confirmed /
// Proposed / Difference / Accept Proposed / Keep Current / Measured & Locked / Calibrate / Review
// Required). No raw ids or JSON are ever shown to the salesperson.
const fmt = (v, unit) => (v == null ? "—" : `${Number(v).toFixed(unit === "SF" ? 0 : 1)} ${unit}`);
const diffText = (d, unit) => (d == null ? "" : `${d > 0 ? "+" : ""}${Number(d).toFixed(unit === "SF" ? 0 : 1)} ${unit}`);

function StatusPill({ status }) {
  if (!status) return null;
  const tone = status === "Accepted / Synced" ? sx.pillOk : status === "Pending sync" ? sx.pillPend : sx.pillWarn;
  return <Text style={[sx.pill, tone]} testID="proposal-status">{status}</Text>;
}

export default function ProposalPanel({ rows, onAccept, onKeep }) {
  if (!rows || !rows.length) return null;
  return (
    <View style={sx.wrap} testID="proposal-panel">
      <Text style={sx.h}>Measurements</Text>
      <ScrollView style={sx.list}>
        {rows.map((r, i) => {
          if (r.kind === "calibrate") {
            return <View key={"c" + i} style={sx.notice} testID="proposal-calibrate"><Text style={sx.noticeT}>{r.message}</Text></View>;
          }
          if (r.kind === "measured_locked") {
            return (
              <View key={"ml" + i} style={sx.row} testID="proposal-measured-locked">
                <View style={sx.rowTop}>
                  <Text style={sx.label}>{r.label}</Text>
                  <Text style={[sx.pill, sx.pillLock]}>Measured &amp; Locked</Text>
                </View>
                <Text style={sx.vals}>Confirmed {fmt(r.confirmed, r.unit)} · Sketch {fmt(r.proposed, r.unit)} · Δ {diffText(r.difference, r.unit)}</Text>
                <Text style={sx.noticeT}>{r.message}</Text>
              </View>
            );
          }
          const key = `${r.target_type}:${r.sketch_id}:${r.metric}`;
          return (
            <View key={key} style={sx.row} testID={`proposal-row-${r.target_type}`}>
              <View style={sx.rowTop}>
                <Text style={sx.label}>{r.label} · {r.metric === "area_sqft" ? "Area" : "Length"}</Text>
                <StatusPill status={r.status} />
              </View>
              <Text style={sx.vals}>
                Confirmed <Text style={sx.strong}>{fmt(r.confirmed, r.unit)}</Text> · Proposed <Text style={sx.strong}>{fmt(r.proposed, r.unit)}</Text>
                {r.difference != null ? <Text style={sx.diff}>  ({diffText(r.difference, r.unit)})</Text> : null}
              </Text>
              {!r.mapped ? <Text style={sx.review} testID="proposal-review">{r.reviewMessage}</Text> : null}
              <View style={sx.actions}>
                <TouchableOpacity testID="accept-proposed" disabled={!r.canAccept}
                  onPress={() => onAccept && onAccept(r)} style={[sx.accept, !r.canAccept && sx.disabled]}>
                  <Text style={sx.acceptT}>Accept Proposed</Text>
                </TouchableOpacity>
                <TouchableOpacity testID="keep-current" disabled={!r.canKeep}
                  onPress={() => onKeep && onKeep(r)} style={[sx.keep, !r.canKeep && sx.disabled]}>
                  <Text style={sx.keepT}>Keep Current</Text>
                </TouchableOpacity>
              </View>
            </View>
          );
        })}
      </ScrollView>
    </View>
  );
}

const sx = StyleSheet.create({
  wrap: { maxHeight: 260, backgroundColor: "#0B1220", borderTopWidth: 1, borderTopColor: "#1E293B", paddingHorizontal: 10, paddingTop: 8 },
  h: { color: "#fff", fontWeight: "800", fontSize: 14, marginBottom: 6 },
  list: { maxHeight: 220 },
  row: { backgroundColor: "#111C2E", borderRadius: 10, padding: 10, marginBottom: 8 },
  rowTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 4 },
  label: { color: "#E2E8F0", fontWeight: "700", fontSize: 13 },
  vals: { color: "#CBD5E1", fontSize: 13 },
  strong: { color: "#fff", fontWeight: "700" },
  diff: { color: "#FBBF24", fontWeight: "700" },
  review: { color: "#FCA5A5", fontSize: 12, marginTop: 4 },
  actions: { flexDirection: "row", gap: 8, marginTop: 8 },
  accept: { backgroundColor: C.brand, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8 },
  acceptT: { color: "#fff", fontWeight: "800", fontSize: 12 },
  keep: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: "#475569" },
  keepT: { color: "#CBD5E1", fontWeight: "700", fontSize: 12 },
  disabled: { opacity: 0.4 },
  notice: { backgroundColor: "rgba(251,191,36,0.12)", borderRadius: 10, padding: 10, marginBottom: 8 },
  noticeT: { color: "#FDE68A", fontSize: 12 },
  pill: { fontSize: 11, fontWeight: "800", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, overflow: "hidden" },
  pillOk: { color: "#052e16", backgroundColor: "#4ADE80" },
  pillPend: { color: "#0B1220", backgroundColor: "#FBBF24" },
  pillWarn: { color: "#450a0a", backgroundColor: "#FCA5A5" },
  pillLock: { color: "#fff", backgroundColor: "#7C3AED" },
});

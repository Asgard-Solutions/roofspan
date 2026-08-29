// B3C: Roof Sketch 409 conflict review + explicit resolution (Base / Your Draft / Office Version).
// A read-only summary preview of each preserved snapshot (no graphical diff/merge engine). The rep must
// explicitly choose to Use the Office Version (discards local work — confirmed) or Keep the Local Draft.
import React from "react";
import { Modal, View, Text, TouchableOpacity, StyleSheet, ScrollView, Alert } from "react-native";
import { sketchSummary } from "../roofSketchConflict";
import { C } from "../theme";

function Summary({ label, testID, doc, version }) {
  const s = sketchSummary(doc);
  const empty = !doc;
  return (
    <View style={sx.card} testID={testID}>
      <View style={sx.cardHead}>
        <Text style={sx.cardTitle}>{label}</Text>
        {version != null ? <Text style={sx.cardVersion} testID={`${testID}-version`}>v{version}</Text> : null}
      </View>
      {empty ? (
        <Text style={sx.cardEmpty}>No document available</Text>
      ) : (
        <View style={sx.counts}>
          <Text style={sx.count} testID={`${testID}-facets`}>{s.facets} facets</Text>
          <Text style={sx.count}>{s.edges} edges</Text>
          <Text style={sx.count}>{s.vertices} vertices</Text>
          <Text style={sx.count}>{s.penetrations} roof features</Text>
        </View>
      )}
    </View>
  );
}

export default function SketchConflictReview({ visible, review, onUseOffice, onKeepLocal, onClose }) {
  if (!review) return null;
  const confirmUseOffice = () => {
    Alert.alert(
      "Use Office Version?",
      "Your unsynced sketch changes on this device will be discarded and replaced with the Office version. This cannot be undone.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Use Office Version", style: "destructive", onPress: onUseOffice },
      ]
    );
  };
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={sx.backdrop}>
        <View style={sx.sheet} testID="sketch-conflict-review">
          <Text style={sx.title}>Sync conflict — review required</Text>
          <Text style={sx.subtitle}>This roof sketch changed in Office while you were editing. Choose which version to keep.</Text>
          <ScrollView style={sx.body}>
            <Summary label="Base (what you started from)" testID="conflict-base" doc={review.base} />
            <Summary label="Your Draft (unsynced)" testID="conflict-local" doc={review.local} />
            <Summary label="Office Version (current)" testID="conflict-office" doc={review.office} version={review.officeVersion} />
          </ScrollView>
          <View style={sx.actions}>
            <TouchableOpacity testID="conflict-keep-local" style={sx.primary} onPress={onKeepLocal}>
              <Text style={sx.primaryText}>Keep Local Draft</Text>
            </TouchableOpacity>
            <TouchableOpacity testID="conflict-use-office" style={sx.danger} onPress={confirmUseOffice}>
              <Text style={sx.dangerText}>Use Office Version</Text>
            </TouchableOpacity>
          </View>
          <TouchableOpacity testID="conflict-review-close" style={sx.ghost} onPress={onClose}>
            <Text style={sx.ghostText}>Review later</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const sx = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: { backgroundColor: "#0B1220", borderTopLeftRadius: 18, borderTopRightRadius: 18, padding: 18, maxHeight: "88%" },
  title: { color: "#fff", fontSize: 18, fontWeight: "800" },
  subtitle: { color: "#94A3B8", fontSize: 13, marginTop: 4, marginBottom: 12 },
  body: { maxHeight: 340 },
  card: { backgroundColor: "#111C2E", borderRadius: 12, padding: 12, marginBottom: 10, borderWidth: 1, borderColor: "#1E293B" },
  cardHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 },
  cardTitle: { color: "#E2E8F0", fontWeight: "800", fontSize: 14 },
  cardVersion: { color: C.brand, fontWeight: "800", fontSize: 13 },
  cardEmpty: { color: "#64748B", fontStyle: "italic", fontSize: 13 },
  counts: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  count: { color: "#CBD5E1", fontSize: 13, fontWeight: "600" },
  actions: { flexDirection: "row", gap: 12, marginTop: 8 },
  primary: { flex: 1, backgroundColor: C.brand, paddingVertical: 14, borderRadius: 12, alignItems: "center" },
  primaryText: { color: "#fff", fontWeight: "800" },
  danger: { flex: 1, backgroundColor: C.danger, paddingVertical: 14, borderRadius: 12, alignItems: "center" },
  dangerText: { color: "#fff", fontWeight: "800" },
  ghost: { paddingVertical: 12, alignItems: "center", marginTop: 4 },
  ghostText: { color: "#94A3B8", fontWeight: "700" },
});

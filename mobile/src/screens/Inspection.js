import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, Alert } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { api } from "../api";
import { useAuth } from "../auth";
import { queueMutation } from "../sync";
import { C } from "../theme";
import PhotoSection from "../components/PhotoSection";

function InspectionField({ label, value, onChange, placeholder, testID, multiline = true }) {
  return (
    <View style={{ marginBottom: 12 }}>
      <Text style={s.label}>{label}</Text>
      <TextInput
        style={[s.input, multiline && { minHeight: 50 }]}
        value={value}
        onChangeText={onChange}
        placeholder={placeholder}
        multiline={multiline}
        testID={testID}
      />
    </View>
  );
}

export default function Inspection({ route, navigation }) {
  const { lead_id, property_id } = route.params || {};
  const { user } = useAuth();
  const [existing, setExisting] = useState(null);
  const [form, setForm] = useState({
    inspector: user?.full_name || user?.email || "",
    roof_condition: "", findings: "", recommended_work: "", measurements: "", notes: "",
  });

  const load = useCallback(async () => {
    try {
      const params = lead_id ? { lead_id } : { property_id };
      const r = await api.get(`/mobile/inspections`, { params });
      if (r.data && r.data.length) {
        const i = r.data[0];
        setExisting(i);
        setForm({
          inspector: i.inspector || user?.full_name || user?.email || "",
          roof_condition: i.roof_condition || "", findings: i.findings || "",
          recommended_work: i.recommended_work || "", measurements: i.measurements || "", notes: i.notes || "",
        });
      }
    } catch (e) {}
  }, [lead_id, property_id, user]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    if (existing) {
      // Update carries If-Match so a stale edit surfaces as a visible Conflict rather than overwriting.
      await queueMutation({ kind: "inspection_update", method: "patch", path: `/mobile/inspections/${existing.id}`, body: form, ifMatch: existing.if_match });
    } else {
      await queueMutation({ kind: "inspection", method: "post", path: "/mobile/inspections", body: { lead_id, property_id, ...form } });
    }
    Alert.alert("Saved", "Inspection queued (will sync).");
    navigation.goBack();
  };

  return (
    <ScrollView style={s.wrap} contentContainerStyle={{ paddingBottom: 40 }}>
      <Text style={s.h}>{existing ? "Update inspection" : "New inspection"}</Text>
      <InspectionField label="Inspector" value={form.inspector} onChange={set("inspector")} placeholder="Who inspected" testID="insp-inspector" multiline={false} />
      <InspectionField label="Roof condition" value={form.roof_condition} onChange={set("roof_condition")} placeholder="e.g. Fair — granule loss" testID="insp-roof_condition" multiline={false} />
      <InspectionField label="Findings" value={form.findings} onChange={set("findings")} placeholder="What you observed" testID="insp-findings" />
      <InspectionField label="Recommended work" value={form.recommended_work} onChange={set("recommended_work")} placeholder="What should be done" testID="insp-recommended_work" />
      <InspectionField label="Measurements" value={form.measurements} onChange={set("measurements")} placeholder="e.g. 24 sq, 6:12 pitch" testID="insp-measurements" />
      <InspectionField label="Notes" value={form.notes} onChange={set("notes")} placeholder="Anything else" testID="insp-notes" />
      <TouchableOpacity style={s.btn} onPress={save} testID="insp-save"><Text style={s.btnText}>Save inspection</Text></TouchableOpacity>

      <PhotoSection recordType={lead_id ? "lead" : "property"} recordId={lead_id || property_id} />
    </ScrollView>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 16 },
  h: { fontSize: 22, fontWeight: "800", color: C.ink, marginBottom: 14 },
  label: { fontWeight: "700", color: C.sub, marginBottom: 6 },
  input: { backgroundColor: "#fff", borderRadius: 12, padding: 14, fontSize: 16, minHeight: 50, borderWidth: 1, borderColor: C.line },
  btn: { backgroundColor: C.brand, borderRadius: 12, padding: 18, alignItems: "center", marginTop: 8 },
  btnText: { color: "#fff", fontSize: 17, fontWeight: "800" },
});

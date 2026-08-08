import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, Alert } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { api } from "../api";
import { queueMutation } from "../sync";
import { C } from "../theme";

export default function Inspection({ route, navigation }) {
  const { lead_id, property_id } = route.params || {};
  const [existing, setExisting] = useState(null);
  const [form, setForm] = useState({ roof_condition: "", findings: "", recommended_work: "", measurements: "", notes: "" });

  const load = useCallback(async () => {
    try {
      const r = await api.get(`/inspections`, { params: { lead_id } });
      if (r.data && r.data.length) {
        const i = r.data[0];
        setExisting(i);
        setForm({ roof_condition: i.roof_condition || "", findings: i.findings || "", recommended_work: i.recommended_work || "", measurements: i.measurements || "", notes: i.notes || "" });
      }
    } catch (e) {}
  }, [lead_id]);

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

  const F = ({ label, k, ph }) => (
    <View style={{ marginBottom: 12 }}>
      <Text style={s.label}>{label}</Text>
      <TextInput style={s.input} value={form[k]} onChangeText={set(k)} placeholder={ph} multiline testID={`insp-${k}`} />
    </View>
  );

  return (
    <ScrollView style={s.wrap} contentContainerStyle={{ paddingBottom: 40 }}>
      <Text style={s.h}>{existing ? "Update inspection" : "New inspection"}</Text>
      <F label="Roof condition" k="roof_condition" ph="e.g. Fair — granule loss" />
      <F label="Findings" k="findings" ph="What you observed" />
      <F label="Recommended work" k="recommended_work" ph="What should be done" />
      <F label="Measurements" k="measurements" ph="e.g. 24 sq, 6:12 pitch" />
      <F label="Notes" k="notes" ph="Anything else" />
      <TouchableOpacity style={s.btn} onPress={save} testID="insp-save"><Text style={s.btnText}>Save inspection</Text></TouchableOpacity>
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

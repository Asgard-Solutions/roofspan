import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, Alert } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { api } from "../api";
import { queueMutation } from "../sync";
import { C } from "../theme";

const OUTCOMES = ["no_answer", "interested", "not_interested", "do_not_knock"];

export default function LeadDetail({ route, navigation }) {
  const { id } = route.params;
  const [lead, setLead] = useState(null);
  const [prop, setProp] = useState(null);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    const r = await api.get(`/leads/${id}`);
    setLead(r.data);
    if (r.data.property_id) {
      try { setProp((await api.get(`/properties/${r.data.property_id}`)).data); } catch (e) {}
    }
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!lead) return <View style={s.wrap}><Text>Loading…</Text></View>;
  const dnk = prop && prop.do_not_knock;

  const recordVisit = async (outcome) => {
    if (!lead.property_id) return Alert.alert("No property linked");
    await queueMutation({ kind: "visit", method: "post", path: "/mobile/visits", body: { property_id: lead.property_id, outcome, notes: note || null } });
    setNote("");
    Alert.alert("Saved", "Visit recorded (will sync).");
  };

  const addNote = async () => {
    if (!note.trim()) return;
    await queueMutation({ kind: "note", method: "patch", path: `/leads/${id}`, body: { notes: note } });
    setNote("");
    Alert.alert("Saved", "Note queued.");
  };

  return (
    <ScrollView style={s.wrap}>
      {dnk ? (
        <View style={s.dnk} testID="lead-dnk-banner">
          <Text style={s.dnkText}>⛔ DO NOT KNOCK</Text>
          {prop.do_not_knock_reason ? <Text style={s.dnkSub}>{prop.do_not_knock_reason}</Text> : null}
        </View>
      ) : null}

      <Text style={s.name}>{lead.name}</Text>
      <Text style={s.sub}>{lead.property_address || lead.address || "—"}</Text>
      {lead.owner_name ? <Text style={s.meta}>Owner: {lead.owner_name}</Text> : null}
      {lead.phone ? <Text style={s.meta}>{lead.phone}</Text> : null}

      <Text style={s.h}>Field note</Text>
      <TextInput style={s.input} placeholder="Type a note…" value={note} onChangeText={setNote} multiline testID="lead-note-input" />
      <TouchableOpacity style={s.btnOutline} onPress={addNote} testID="lead-add-note"><Text style={s.btnOutlineText}>Add note</Text></TouchableOpacity>

      <Text style={s.h}>Record visit</Text>
      <View style={s.outcomes}>
        {OUTCOMES.map((o) => (
          <TouchableOpacity key={o} style={[s.chip, o === "do_not_knock" && { borderColor: C.dnk }]} onPress={() => recordVisit(o)} testID={`visit-${o}`}>
            <Text style={[s.chipText, o === "do_not_knock" && { color: C.dnk }]}>{o.replace(/_/g, " ")}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <TouchableOpacity style={s.btn} onPress={() => navigation.navigate("Inspection", { lead_id: id, property_id: lead.property_id })} testID="open-inspection">
        <Text style={s.btnText}>Inspection</Text>
      </TouchableOpacity>

      <Text style={s.h}>Visit history</Text>
      {(lead.visits || []).map((v) => (
        <View key={v.id} style={s.visit}><Text style={s.visitOut}>{v.outcome}</Text><Text style={s.visitMeta}>{new Date(v.visited_at).toLocaleString()} · {v.user_email}</Text>{v.notes ? <Text style={s.visitNote}>{v.notes}</Text> : null}</View>
      ))}
      {(lead.visits || []).length === 0 && <Text style={s.empty}>No visits yet.</Text>}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 16 },
  dnk: { backgroundColor: C.dnk, borderRadius: 12, padding: 16, marginBottom: 14 },
  dnkText: { color: "#fff", fontSize: 22, fontWeight: "900" },
  dnkSub: { color: "#FEE2E2", marginTop: 2 },
  name: { fontSize: 24, fontWeight: "800", color: C.ink },
  sub: { fontSize: 15, color: C.sub, marginTop: 2 },
  meta: { fontSize: 14, color: C.sub, marginTop: 4 },
  h: { fontSize: 16, fontWeight: "700", color: C.ink, marginTop: 20, marginBottom: 8 },
  input: { backgroundColor: "#fff", borderRadius: 12, padding: 14, fontSize: 16, minHeight: 60, borderWidth: 1, borderColor: C.line },
  outcomes: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { borderWidth: 2, borderColor: C.line, borderRadius: 24, paddingVertical: 12, paddingHorizontal: 16 },
  chipText: { fontWeight: "700", color: C.ink, textTransform: "capitalize" },
  btn: { backgroundColor: C.brand, borderRadius: 12, padding: 16, alignItems: "center", marginTop: 18 },
  btnText: { color: "#fff", fontSize: 16, fontWeight: "800" },
  btnOutline: { borderWidth: 2, borderColor: C.brand, borderRadius: 12, padding: 12, alignItems: "center", marginTop: 8 },
  btnOutlineText: { color: C.brand, fontWeight: "800" },
  visit: { backgroundColor: "#fff", borderRadius: 10, padding: 12, marginBottom: 8, borderWidth: 1, borderColor: C.line },
  visitOut: { fontWeight: "700", color: C.ink, textTransform: "capitalize" },
  visitMeta: { fontSize: 12, color: C.sub },
  visitNote: { fontSize: 14, color: C.ink, marginTop: 4 },
  empty: { color: C.sub, fontStyle: "italic" },
});

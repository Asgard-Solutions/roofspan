import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, Alert } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { api } from "../api";
import { queueMutation } from "../sync";
import { C } from "../theme";

export default function JobDetail({ route }) {
  const { id } = route.params;
  const [job, setJob] = useState(null);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    try { setJob((await api.get(`/jobs/${id}`)).data); } catch (e) {}
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!job) return <View style={s.wrap}><Text>Loading…</Text></View>;

  const addUpdate = async () => {
    if (!note.trim()) return;
    const existing = job.schedule_notes ? job.schedule_notes + "\n" : "";
    await queueMutation({ kind: "job_update", method: "patch", path: `/jobs/${id}`, body: { schedule_notes: existing + note } });
    setNote("");
    Alert.alert("Saved", "Field update queued.");
  };

  return (
    <ScrollView style={s.wrap}>
      <Text style={s.title}>{job.number}</Text>
      <Text style={s.status}>{job.status}</Text>
      {job.scheduled_start ? <Text style={s.meta}>Scheduled: {new Date(job.scheduled_start).toLocaleString()}</Text> : null}
      {job.assigned_to ? <Text style={s.meta}>Crew: {job.assigned_to}</Text> : null}

      <Text style={s.h}>Scope</Text>
      <Text style={s.body}>{job.scope || "—"}</Text>

      {job.materials && job.materials.length ? (
        <>
          <Text style={s.h}>Materials</Text>
          {job.materials.map((m) => (
            <Text key={m.id} style={s.body}>• {m.name || m.material_name} — {m.planned_quantity ?? m.quantity}</Text>
          ))}
        </>
      ) : null}

      <Text style={s.h}>Field update</Text>
      <TextInput style={s.input} placeholder="Add a field note/update…" value={note} onChangeText={setNote} multiline testID="job-note-input" />
      <TouchableOpacity style={s.btn} onPress={addUpdate} testID="job-add-update"><Text style={s.btnText}>Add update</Text></TouchableOpacity>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 16 },
  title: { fontSize: 24, fontWeight: "800", color: C.ink },
  status: { fontSize: 13, color: C.brand, fontWeight: "800", textTransform: "uppercase", marginTop: 2 },
  meta: { fontSize: 14, color: C.sub, marginTop: 4 },
  h: { fontSize: 16, fontWeight: "700", color: C.ink, marginTop: 18, marginBottom: 6 },
  body: { fontSize: 15, color: C.ink, marginBottom: 2 },
  input: { backgroundColor: "#fff", borderRadius: 12, padding: 14, fontSize: 16, minHeight: 60, borderWidth: 1, borderColor: C.line },
  btn: { backgroundColor: C.brand, borderRadius: 12, padding: 16, alignItems: "center", marginTop: 8 },
  btnText: { color: "#fff", fontSize: 16, fontWeight: "800" },
});

import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, Alert } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { cache, patchCachedDetail, patchCachedList } from "../cache";
import { queueMutation } from "../sync";
import { C } from "../theme";
import PhotoSection from "../components/PhotoSection";

const STATUSES = ["created", "pending", "scheduled", "in_progress", "completed", "cancelled"];

export default function JobDetail({ route }) {
  const { id } = route.params;
  const [job, setJob] = useState(null);
  const [stale, setStale] = useState(false);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    const r = await cache.job(id);
    setJob(r.data); setStale(!!r.stale);
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!job) return <View style={s.wrap}><Text>Loading…</Text></View>;

  const setStatus = async (status) => {
    if (status === job.status) return;
    await queueMutation({ kind: "job_update", method: "patch", path: `/mobile/jobs/${id}`, body: { status }, ifMatch: job.if_match, label: `Job → ${status}` });
    setJob((j) => ({ ...j, status }));
    await patchCachedDetail(`job:${id}`, { status });
    await patchCachedList("jobs", id, { status });
    Alert.alert("Saved offline", "Status change queued.");
  };

  const addUpdate = async () => {
    if (!note.trim()) return;
    const merged = (job.schedule_notes ? job.schedule_notes + "\n" : "") + note;
    await queueMutation({ kind: "job_update", method: "patch", path: `/mobile/jobs/${id}`, body: { schedule_notes: merged }, ifMatch: job.if_match, label: "Job field note" });
    setJob((j) => ({ ...j, schedule_notes: merged }));
    await patchCachedDetail(`job:${id}`, { schedule_notes: merged });
    setNote("");
    Alert.alert("Saved offline", "Field update queued.");
  };

  return (
    <ScrollView style={s.wrap} contentContainerStyle={{ paddingBottom: 40 }}>
      {stale ? <Text style={s.staleBar}>Showing saved copy — offline</Text> : null}
      <Text style={s.title}>{job.number}</Text>
      {job.customer_name ? <Text style={s.meta}>{job.customer_name}</Text> : null}
      {job.property_address ? <Text style={s.meta}>{job.property_address}</Text> : null}
      {job.scheduled_start ? <Text style={s.meta}>Scheduled: {new Date(job.scheduled_start).toLocaleString()}</Text> : null}
      {job.assigned_to ? <Text style={s.meta}>Crew: {job.assigned_to}</Text> : null}

      <Text style={s.h}>Status</Text>
      <View style={s.chips}>
        {STATUSES.map((st) => (
          <TouchableOpacity key={st} style={[s.chip, job.status === st && { borderColor: C.brand, backgroundColor: "#FFF7ED" }]} onPress={() => setStatus(st)} testID={`job-status-${st}`}>
            <Text style={[s.chipText, job.status === st && { color: C.brand }]}>{st.replace(/_/g, " ")}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <Text style={s.h}>Scope</Text>
      <Text style={s.body}>{job.scope || "—"}</Text>

      {job.materials && job.materials.length ? (
        <>
          <Text style={s.h}>Materials</Text>
          {job.materials.map((m) => (
            <Text key={m.id} style={s.body}>• {m.material_name} — {m.planned_quantity} {m.unit}</Text>
          ))}
        </>
      ) : null}

      {job.schedule_notes ? (<><Text style={s.h}>Field notes</Text><Text style={s.body}>{job.schedule_notes}</Text></>) : null}

      <Text style={s.h}>Add field update</Text>
      <TextInput style={s.input} placeholder="Add a field note/update…" value={note} onChangeText={setNote} multiline testID="job-note-input" />
      <TouchableOpacity style={s.btn} onPress={addUpdate} testID="job-add-update"><Text style={s.btnText}>Add update</Text></TouchableOpacity>

      <PhotoSection recordType="job" recordId={id} />
    </ScrollView>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 16 },
  staleBar: { backgroundColor: "#FEF3C7", color: "#92400E", textAlign: "center", paddingVertical: 6, fontSize: 12, fontWeight: "600", borderRadius: 8, marginBottom: 10 },
  title: { fontSize: 24, fontWeight: "800", color: C.ink },
  meta: { fontSize: 14, color: C.sub, marginTop: 4 },
  h: { fontSize: 16, fontWeight: "700", color: C.ink, marginTop: 18, marginBottom: 8 },
  body: { fontSize: 15, color: C.ink, marginBottom: 2 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { borderWidth: 2, borderColor: C.line, borderRadius: 24, paddingVertical: 10, paddingHorizontal: 14 },
  chipText: { fontWeight: "700", color: C.ink, textTransform: "capitalize" },
  input: { backgroundColor: "#fff", borderRadius: 12, padding: 14, fontSize: 16, minHeight: 60, borderWidth: 1, borderColor: C.line },
  btn: { backgroundColor: C.brand, borderRadius: 12, padding: 16, alignItems: "center", marginTop: 8 },
  btnText: { color: "#fff", fontSize: 16, fontWeight: "800" },
});

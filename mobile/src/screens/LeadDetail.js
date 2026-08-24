import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, Alert } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { cache, patchCachedDetail, patchCachedList } from "../cache";
import { queueMutation } from "../sync";
import { getCache, putCache } from "../storage";
import { C } from "../theme";
import PhotoSection from "../components/PhotoSection";

const OUTCOMES = ["no_answer", "interested", "not_interested", "do_not_knock"];
const STATUSES = ["new", "contacted", "interested", "qualified", "won", "lost"];

export default function LeadDetail({ route, navigation }) {
  const { id } = route.params;
  const [lead, setLead] = useState(null);
  const [stale, setStale] = useState(false);
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({});

  const load = useCallback(async () => {
    const r = await cache.lead(id);
    if (r.data) { setLead(r.data); setForm({ name: r.data.name, phone: r.data.phone, email: r.data.email, status: r.data.status }); }
    setStale(!!r.stale);
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!lead) return <View style={s.wrap}><Text>Loading…</Text></View>;
  const dnk = lead.do_not_knock;

  const recordVisit = async (outcome) => {
    if (!lead.property_id) return Alert.alert("No property linked", "This lead has no property to record a visit against.");
    await queueMutation({ kind: "visit", method: "post", path: "/mobile/visits", body: { property_id: lead.property_id, outcome, notes: note || null }, label: "Visit" });
    if (outcome === "do_not_knock") { setLead((l) => ({ ...l, do_not_knock: true })); await patchCachedDetail(`lead:${id}`, { do_not_knock: true }); }
    setNote("");
    Alert.alert("Saved offline", "Visit recorded — we'll sync when Office is available.");
  };

  const addNote = async () => {
    if (!note.trim()) return;
    const merged = note;
    await queueMutation({ kind: "lead_update", method: "patch", path: `/mobile/leads/${id}`, body: { notes: merged }, ifMatch: lead.if_match, label: "Lead note" });
    setLead((l) => ({ ...l, notes: merged }));
    await patchCachedDetail(`lead:${id}`, { notes: merged });
    setNote("");
    Alert.alert("Saved offline", "Note queued.");
  };

  const saveEdit = async () => {
    await queueMutation({ kind: "lead_update", method: "patch", path: `/mobile/leads/${id}`, body: { ...form }, ifMatch: lead.if_match, label: "Edit lead" });
    setLead((l) => ({ ...l, ...form }));
    await patchCachedDetail(`lead:${id}`, form);
    await patchCachedList("leads", id, { name: form.name, status: form.status });
    setEditing(false);
    Alert.alert("Saved offline", "Lead changes queued.");
  };

  const archive = () => {
    Alert.alert("Archive lead?", "It stays in RoofSpan Office history and can be restored there.", [
      { text: "Cancel", style: "cancel" },
      { text: "Archive", style: "destructive", onPress: async () => {
        await queueMutation({ kind: "lead_archive", method: "delete", path: `/mobile/leads/${id}`, label: "Archive lead" });
        try { const list = (await getCache("leads")) || []; await putCache("leads", list.filter((r) => r.id !== id)); } catch (e) {}
        navigation.goBack();
      } },
    ]);
  };

  return (
    <ScrollView style={s.wrap} contentContainerStyle={{ paddingBottom: 40 }}>
      {stale ? <Text style={s.staleBar} testID="lead-offline-banner">Showing saved copy — offline</Text> : null}
      {dnk ? (
        <View style={s.dnk} testID="lead-dnk-banner">
          <Text style={s.dnkText}>DO NOT KNOCK</Text>
          {lead.do_not_knock_reason ? <Text style={s.dnkSub}>{lead.do_not_knock_reason}</Text> : null}
        </View>
      ) : null}

      {!editing ? (
        <>
          <View style={s.headRow}>
            <Text style={s.name}>{lead.name}</Text>
            <TouchableOpacity onPress={() => setEditing(true)} testID="lead-edit"><Text style={s.edit}>Edit</Text></TouchableOpacity>
          </View>
          <Text style={s.sub}>{lead.address || "—"}</Text>
          {lead.phone ? <Text style={s.meta}>{lead.phone}</Text> : null}
          {lead.email ? <Text style={s.meta}>{lead.email}</Text> : null}
          <Text style={s.statusPill}>{lead.status}</Text>
        </>
      ) : (
        <View testID="lead-edit-form">
          <Field label="Name" value={form.name} onChange={(v) => setForm({ ...form, name: v })} testID="lead-edit-name" />
          <Field label="Phone" value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} testID="lead-edit-phone" />
          <Field label="Email" value={form.email} onChange={(v) => setForm({ ...form, email: v })} testID="lead-edit-email" />
          <Text style={s.label}>Status</Text>
          <View style={s.outcomes}>
            {STATUSES.map((st) => (
              <TouchableOpacity key={st} style={[s.chip, form.status === st && { borderColor: C.brand, backgroundColor: "#FFF7ED" }]} onPress={() => setForm({ ...form, status: st })} testID={`lead-status-${st}`}>
                <Text style={s.chipText}>{st}</Text>
              </TouchableOpacity>
            ))}
          </View>
          <View style={s.editBtns}>
            <TouchableOpacity style={s.btn} onPress={saveEdit} testID="lead-edit-save"><Text style={s.btnText}>Save</Text></TouchableOpacity>
            <TouchableOpacity style={s.btnGhost} onPress={() => setEditing(false)}><Text style={s.btnGhostText}>Cancel</Text></TouchableOpacity>
          </View>
        </View>
      )}

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

      <PhotoSection recordType="lead" recordId={id} />

      <Text style={s.h}>Visit history</Text>
      {(lead.visits || []).map((v) => (
        <View key={v.id} style={s.visit}><Text style={s.visitOut}>{v.outcome}</Text><Text style={s.visitMeta}>{new Date(v.visited_at).toLocaleString()} · {v.user_email}</Text>{v.notes ? <Text style={s.visitNote}>{v.notes}</Text> : null}</View>
      ))}
      {(lead.visits || []).length === 0 && <Text style={s.empty}>No visits yet.</Text>}

      <TouchableOpacity style={s.archive} onPress={archive} testID="lead-archive"><Text style={s.archiveText}>Archive lead</Text></TouchableOpacity>
    </ScrollView>
  );
}

function Field({ label, value, onChange, testID }) {
  return (
    <View style={{ marginBottom: 10 }}>
      <Text style={s.label}>{label}</Text>
      <TextInput style={s.input} value={value || ""} onChangeText={onChange} testID={testID} />
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 16 },
  staleBar: { backgroundColor: "#FEF3C7", color: "#92400E", textAlign: "center", paddingVertical: 6, fontSize: 12, fontWeight: "600", borderRadius: 8, marginBottom: 10 },
  dnk: { backgroundColor: C.dnk, borderRadius: 12, padding: 16, marginBottom: 14 },
  dnkText: { color: "#fff", fontSize: 22, fontWeight: "900" },
  dnkSub: { color: "#FEE2E2", marginTop: 2 },
  headRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  name: { fontSize: 24, fontWeight: "800", color: C.ink, flex: 1 },
  edit: { color: C.brand, fontWeight: "800", fontSize: 16 },
  sub: { fontSize: 15, color: C.sub, marginTop: 2 },
  meta: { fontSize: 14, color: C.sub, marginTop: 4 },
  statusPill: { alignSelf: "flex-start", marginTop: 8, backgroundColor: "#FFF7ED", color: C.brand, fontWeight: "800", textTransform: "uppercase", fontSize: 12, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 20 },
  h: { fontSize: 16, fontWeight: "700", color: C.ink, marginTop: 20, marginBottom: 8 },
  label: { fontSize: 13, color: C.sub, fontWeight: "600", marginBottom: 4, marginTop: 6 },
  input: { backgroundColor: "#fff", borderRadius: 12, padding: 14, fontSize: 16, minHeight: 48, borderWidth: 1, borderColor: C.line },
  outcomes: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { borderWidth: 2, borderColor: C.line, borderRadius: 24, paddingVertical: 10, paddingHorizontal: 14 },
  chipText: { fontWeight: "700", color: C.ink, textTransform: "capitalize" },
  editBtns: { flexDirection: "row", gap: 10, marginTop: 12 },
  btn: { backgroundColor: C.brand, borderRadius: 12, padding: 16, alignItems: "center", marginTop: 18, flex: 1 },
  btnText: { color: "#fff", fontSize: 16, fontWeight: "800" },
  btnGhost: { borderRadius: 12, padding: 16, alignItems: "center", marginTop: 18, flex: 1 },
  btnGhostText: { color: C.sub, fontWeight: "700" },
  btnOutline: { borderWidth: 2, borderColor: C.brand, borderRadius: 12, padding: 12, alignItems: "center", marginTop: 8 },
  btnOutlineText: { color: C.brand, fontWeight: "800" },
  visit: { backgroundColor: "#fff", borderRadius: 10, padding: 12, marginBottom: 8, borderWidth: 1, borderColor: C.line },
  visitOut: { fontWeight: "700", color: C.ink, textTransform: "capitalize" },
  visitMeta: { fontSize: 12, color: C.sub },
  visitNote: { fontSize: 14, color: C.ink, marginTop: 4 },
  empty: { color: C.sub, fontStyle: "italic" },
  archive: { marginTop: 28, padding: 14, alignItems: "center", borderRadius: 12, borderWidth: 1, borderColor: "#FCA5A5" },
  archiveText: { color: C.danger, fontWeight: "800" },
});

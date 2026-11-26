import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, Alert } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { cache, patchCachedDetail, patchCachedList } from "../cache";
import { queueMutation, refreshLead, registerActiveLead } from "../sync";
import { getCache, putCache } from "../storage";
import { C } from "../theme";
import PhotoSection from "../components/PhotoSection";
import FollowUpSheet from "../components/FollowUpSheet";
const { LEAD_STATUSES, whenOf, kindLabel, fmt, applyToMyDay, nextActionOf } = require("../followups");
const { uuidv4 } = require("../queue");

const OUTCOMES = ["no_answer", "interested", "callback", "appointment", "not_interested", "do_not_knock"];
const STATUSES = LEAD_STATUSES;
const WHEN_COLOR = { overdue: "#B91C1C", today: "#C2410C", upcoming: "#475569" };

export default function LeadDetail({ route, navigation }) {
  const { id } = route.params;
  const [lead, setLead] = useState(null);
  const [stale, setStale] = useState(false);
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({});
  const [sheet, setSheet] = useState(null); // "followup" | "inspection" | null

  const load = useCallback(async () => {
    const r = await cache.lead(id);
    if (r.data) { setLead(r.data); setForm({ name: r.data.name, phone: r.data.phone, email: r.data.email, status: r.data.status }); }
    setStale(!!r.stale);
    // Lead-aware sync: opening a lead registers it + pulls the canonical measurements for it (screen-independent).
    registerActiveLead({ lead_id: id });
    refreshLead({ lead_id: id }, "lead_open").catch(() => {});
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!lead) return <View style={s.wrap}><Text>Loading…</Text></View>;
  const dnk = lead.do_not_knock;

  const recordVisit = async (outcome) => {
    if (!lead.property_id) return Alert.alert("No property linked", "This lead has no property to record a visit against.");
    await queueMutation({ kind: "visit", method: "post", path: "/mobile/visits", body: { property_id: lead.property_id, outcome, notes: note || null }, label: "Visit" });
    if (outcome === "do_not_knock") { setLead((l) => ({ ...l, do_not_knock: true })); await patchCachedDetail(`lead:${id}`, { do_not_knock: true }); }
    setNote("");
    if (outcome === "callback") return setSheet("followup");
    if (outcome === "appointment") return setSheet("inspection");
    Alert.alert("Saved offline", "Visit recorded — we'll sync when Office is available.");
  };

  // Appends on the server (never replaces earlier notes), so no If-Match is needed.
  const addNote = async () => {
    const text = note.trim();
    if (!text) return;
    await queueMutation({ kind: "lead_note", method: "patch", path: `/mobile/leads/${id}`, body: { append_note: text }, label: "Lead note" });
    const merged = lead.notes ? `${lead.notes}\n\n${text}` : text;
    setLead((l) => ({ ...l, notes: merged }));
    await patchCachedDetail(`lead:${id}`, { notes: merged });
    setNote("");
    Alert.alert("Saved offline", "Note queued.");
  };

  const saveSheet = async ({ kind, due_at, note: n }) => {
    const mode = sheet;
    setSheet(null);
    if (mode === "inspection") {
      await queueMutation({ kind: "inspection_book", method: "post", path: "/mobile/inspections", label: "Book inspection",
        body: { lead_id: id, property_id: lead.property_id || null, status: "scheduled", inspection_date: due_at, notes: n } });
      const booked = [...(lead.scheduled_inspections || []), { id: `pending-${Date.now()}`, inspection_date: due_at, notes: n, status: "scheduled", _pending: true }];
      setLead((l) => ({ ...l, scheduled_inspections: booked }));
      await patchCachedDetail(`lead:${id}`, { scheduled_inspections: booked });
      return Alert.alert("Inspection booked", `${fmt(due_at)} — syncs when Office is available.`);
    }
    const fu = { id: uuidv4(), lead_id: id, kind, due_at, note: n, status: "open", _pending: true };
    await queueMutation({ kind: "follow_up", method: "post", path: `/leads/${id}/follow-ups`, body: { id: fu.id, kind, due_at, note: n }, label: "Follow-up" });
    await setFollowUps([...(lead.follow_ups || []), fu], fu);
  };

  const setFollowUps = async (list, changed) => {
    const na = nextActionOf({ ...lead, follow_ups: list });
    setLead((l) => ({ ...l, follow_ups: list, next_action: na }));
    await patchCachedDetail(`lead:${id}`, { follow_ups: list, next_action: na });
    await patchCachedList("leads", id, { next_action: na });
    try { await putCache("myday", applyToMyDay(await getCache("myday"), lead, changed)); } catch (e) { /* best effort */ }
  };

  const finishFollowUp = async (f, status) => {
    await queueMutation({ kind: "follow_up_update", method: "patch", path: `/follow-ups/${f.id}`, body: { status }, label: status === "done" ? "Follow-up done" : "Follow-up cancelled" });
    const changed = { ...f, status };
    await setFollowUps((lead.follow_ups || []).map((x) => (x.id === f.id ? changed : x)), changed);
    if (status === "done") Alert.alert("Done", "Schedule the next follow-up?", [{ text: "Not now", style: "cancel" }, { text: "Schedule", onPress: () => setSheet("followup") }]);
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

      <FollowUpsBlock lead={lead} onSchedule={() => setSheet("followup")} onBook={() => setSheet("inspection")} onFinish={finishFollowUp} />

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
      <FollowUpSheet visible={!!sheet} mode={sheet} onClose={() => setSheet(null)} onSave={saveSheet} />
    </ScrollView>
  );
}

function FollowUpsBlock({ lead, onSchedule, onBook, onFinish }) {
  const open = (lead.follow_ups || []).filter((f) => f.status === "open").sort((a, b) => new Date(a.due_at) - new Date(b.due_at));
  const booked = lead.scheduled_inspections || [];
  const na = nextActionOf(lead);
  return (
    <View testID="lead-followups">
      {na ? (
        <View style={s.next} testID="lead-next-action">
          <Text style={s.nextLabel}>NEXT STEP</Text>
          <Text style={s.nextText}>{na.text}</Text>
          {na.due_at ? <Text style={[s.nextDue, { color: WHEN_COLOR[whenOf(na.due_at)] }]}>{whenOf(na.due_at) === "overdue" ? "Overdue · " : ""}{fmt(na.due_at)}</Text> : null}
        </View>
      ) : null}
      <Text style={s.h}>Follow-ups</Text>
      {open.length === 0 && <Text style={s.empty}>Nothing scheduled.</Text>}
      {open.map((f) => (
        <View key={f.id} style={s.visit} testID={`followup-${f.id}`}>
          <Text style={[s.visitOut, { color: WHEN_COLOR[whenOf(f.due_at)] }]}>{kindLabel(f.kind)} · {fmt(f.due_at)}{f._pending ? " · waiting to sync" : ""}</Text>
          {f.note ? <Text style={s.visitNote}>{f.note}</Text> : null}
          <View style={s.editBtns}>
            <TouchableOpacity style={[s.btnOutline, { flex: 1 }]} onPress={() => onFinish(f, "done")} testID={`followup-done-${f.id}`}><Text style={s.btnOutlineText}>Done</Text></TouchableOpacity>
            <TouchableOpacity style={[s.btnGhost, { marginTop: 8 }]} onPress={() => onFinish(f, "cancelled")} testID={`followup-cancel-${f.id}`}><Text style={s.btnGhostText}>Cancel</Text></TouchableOpacity>
          </View>
        </View>
      ))}
      {booked.map((i) => (
        <View key={i.id} style={[s.visit, { borderColor: "#FDBA74" }]} testID={`booked-inspection-${i.id}`}>
          <Text style={s.visitOut}>Inspection booked · {fmt(i.inspection_date)}{i._pending ? " · waiting to sync" : ""}</Text>
          {i.notes ? <Text style={s.visitNote}>{i.notes}</Text> : null}
        </View>
      ))}
      <View style={s.editBtns}>
        <TouchableOpacity style={[s.btnOutline, { flex: 1 }]} onPress={onSchedule} testID="lead-schedule-followup"><Text style={s.btnOutlineText}>+ Follow-up</Text></TouchableOpacity>
        <TouchableOpacity style={[s.btnOutline, { flex: 1 }]} onPress={onBook} testID="lead-book-inspection"><Text style={s.btnOutlineText}>Book inspection</Text></TouchableOpacity>
      </View>
    </View>
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
  next: { backgroundColor: "#FFF7ED", borderColor: "#FDBA74", borderWidth: 1, borderRadius: 12, padding: 14, marginTop: 16 },
  nextLabel: { fontSize: 11, fontWeight: "800", color: C.brand, letterSpacing: 1 },
  nextText: { fontSize: 16, fontWeight: "700", color: C.ink, marginTop: 2 },
  nextDue: { fontSize: 13, fontWeight: "700", marginTop: 2 },
  archive: { marginTop: 28, padding: 14, alignItems: "center", borderRadius: 12, borderWidth: 1, borderColor: "#FCA5A5" },
  archiveText: { color: C.danger, fontWeight: "800" },
});

import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, TouchableOpacity, TextInput, StyleSheet, Alert } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { cache, patchCachedDetail, patchCanvassFeature } from "../cache";
import { queueMutation, conflictMutationForProperty, resolveFieldConflict } from "../sync";
import { api } from "../api";
import { C } from "../theme";
import PhotoSection from "../components/PhotoSection";

// Canonical RoofSpan visit outcomes fallback (used offline / before the backend list loads). The live
// list is fetched from GET /api/visit-outcomes so Field and Office render from ONE backend source.
const FALLBACK_OUTCOMES = [
  ["no_answer", "No answer"],
  ["not_interested", "Not interested"],
  ["interested", "Interested"],
  ["callback", "Callback requested"],
  ["appointment", "Appointment set"],
  ["do_not_knock", "Do Not Knock"],
];
const OUTCOME_LABEL = Object.fromEntries(OUTCOMES);

function occupancyLabel(v) {
  if (v === true) return "Owner-occupied";
  if (v === false) return "Non-owner-occupied";
  return "Occupancy unknown";
}

export default function Property({ route, navigation }) {
  const { id } = route.params;
  const [prop, setProp] = useState(null);
  const [stale, setStale] = useState(false);
  const [outcome, setOutcome] = useState("no_answer");
  const [notes, setNotes] = useState("");
  const [outcomes, setOutcomes] = useState(FALLBACK_OUTCOMES);
  const [conflict, setConflict] = useState(null);
  const OUTCOME_LABEL = Object.fromEntries(outcomes);

  const load = useCallback(async () => {
    const r = await cache.property(id);
    setProp(r.data); setStale(!!r.stale);
    setConflict(await conflictMutationForProperty(id));
    try {
      const res = await api.get("/visit-outcomes");                 // ONE backend source of truth
      if (res && res.data && Array.isArray(res.data.outcomes) && res.data.outcomes.length) {
        setOutcomes(res.data.outcomes.map((o) => [o.value, o.label]));
      }
    } catch (e) { /* offline: keep fallback list */ }
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!prop) return <View style={s.wrap}><Text>Loading…</Text></View>;

  // Canonical fields only (compat aliases retired).
  const contacts = prop.contacts || [];
  const owner = contacts.find((c) => c.kind === "owner") || null;
  const renter = contacts.find((c) => c.kind === "renter") || null;
  const leadId = prop.lead_id || null;

  const resolveConflict = async (choice) => {
    await resolveFieldConflict(conflict.client_id, choice);
    setConflict(null);
    await load();
    Alert.alert("Conflict resolved", choice === "use_server" ? "Using Office's version." : "Keeping your local change — retrying.");
  };

  const recordVisit = async () => {
    await queueMutation({
      kind: "visit", method: "post", path: "/mobile/visits",
      body: { property_id: id, outcome, notes: notes || null },
      label: `Visit — ${OUTCOME_LABEL[outcome] || outcome}`,
    });
    // Optimistic local reflection of the pending visit (+ DNK when that outcome is chosen).
    const pendingVisit = { id: `pending-${Date.now()}`, outcome, notes: notes || null, visited_at: new Date().toISOString(), user_email: "you (pending)" };
    const patch = { visits: [pendingVisit, ...(prop.visits || [])], last_outcome: outcome, last_visited_at: pendingVisit.visited_at };
    if (outcome === "do_not_knock") { patch.do_not_knock = true; patch.do_not_knock_reason = prop.do_not_knock_reason || "Marked during visit"; }
    setProp((p) => ({ ...p, ...patch }));
    await patchCachedDetail(`property:${id}`, patch);
    // Optimistic Map/canvass reflection (authoritative reconcile happens on acknowledgement).
    await patchCanvassFeature(id, { last_outcome: outcome, last_visited_at: pendingVisit.visited_at, ...(outcome === "do_not_knock" ? { do_not_knock: true } : {}) });
    setNotes("");
    Alert.alert("Saved offline", "Visit recorded — we'll sync when Office is available.");
  };

  const toggleDNK = async (next) => {
    await queueMutation({
      kind: "property_patch", method: "patch", path: `/mobile/properties/${id}`,
      body: { do_not_knock: next, do_not_knock_reason: next ? (prop.do_not_knock_reason || "Marked by field rep") : null },
      label: next ? "Do Not Knock ON" : "Do Not Knock OFF",
    });
    const patch = { do_not_knock: next, do_not_knock_reason: next ? (prop.do_not_knock_reason || "Marked by field rep") : null };
    setProp((p) => ({ ...p, ...patch }));
    await patchCachedDetail(`property:${id}`, patch);
    await patchCanvassFeature(id, { do_not_knock: next });
    Alert.alert("Saved offline", `Do Not Knock turned ${next ? "ON" : "OFF"} — will sync when Office is available.`);
  };

  const createLead = () => {
    if (leadId) return navigation.getParent()?.navigate("LeadsTab", { screen: "LeadDetail", params: { id: leadId } });
    navigation.navigate("NewLead", { property_id: id, name: (owner && owner.name) || "", address: prop.formatted_address });
  };

  return (
    <ScrollView style={s.wrap} contentContainerStyle={{ paddingBottom: 40 }}>
      {stale ? <Text style={s.staleBar}>Showing saved copy — offline</Text> : null}
      {conflict ? (
        <View style={s.conflict} testID="property-conflict-banner">
          <Text style={s.conflictTitle}>Sync conflict — review required</Text>
          <Text style={s.conflictSub}>This home changed in Office while your change was offline.</Text>
          <View style={s.conflictRow}>
            <TouchableOpacity style={s.conflictBtn} onPress={() => resolveConflict("use_server")} testID="conflict-use-server"><Text style={s.conflictBtnText}>Use Office version</Text></TouchableOpacity>
            <TouchableOpacity style={[s.conflictBtn, s.conflictBtnAlt]} onPress={() => resolveConflict("keep_local")} testID="conflict-keep-local"><Text style={[s.conflictBtnText, s.conflictBtnTextAlt]}>Keep my change</Text></TouchableOpacity>
          </View>
        </View>
      ) : null}
      {prop.do_not_knock ? (
        <View style={s.dnk} testID="property-dnk-banner">
          <Text style={s.dnkText}>DO NOT KNOCK</Text>
          {prop.do_not_knock_reason ? <Text style={s.dnkSub}>{prop.do_not_knock_reason}</Text> : null}
        </View>
      ) : null}

      <Text style={s.addr} testID="property-address">{prop.formatted_address}</Text>

      <Text style={s.h}>Property details</Text>
      <View style={s.card}>
        {prop.property_type ? <Text style={s.meta} testID="property-type">Type: {String(prop.property_type).replace(/_/g, " ")}</Text> : null}
        <Text style={s.meta}>Bedrooms: {prop.bedrooms ?? "—"}  ·  Bathrooms: {prop.bathrooms ?? "—"}</Text>
        <Text style={s.meta}>Square footage: {prop.square_footage ?? "—"}  ·  Year built: {prop.year_built ?? "—"}</Text>
        {(prop.latitude != null && prop.longitude != null)
          ? <Text style={s.meta} testID="property-coords">Coordinates: {prop.latitude}, {prop.longitude}</Text>
          : <Text style={s.meta}>Coordinates: —</Text>}
      </View>

      <Text style={s.h}>Owner / Renter</Text>
      <View style={s.card} testID="property-contacts">
        <Text style={s.meta}>{occupancyLabel(prop.owner_occupied)}</Text>
        {owner ? (
          <View style={s.contactBlock}>
            <Text style={s.contactName}>Owner: {owner.name || "—"}{owner.contact_type ? ` (${owner.contact_type})` : ""}</Text>
            {owner.mailing_address ? <Text style={s.meta}>Mailing: {owner.mailing_address}</Text> : null}
            {owner.phone ? <Text style={s.meta}>Phone: {owner.phone}</Text> : null}
            {owner.email ? <Text style={s.meta}>Email: {owner.email}</Text> : null}
          </View>
        ) : <Text style={s.meta}>No owner on file</Text>}
        {renter ? (
          <View style={s.contactBlock}>
            <Text style={s.contactName}>Renter: {renter.name || "—"}{renter.contact_type ? ` (${renter.contact_type})` : ""}</Text>
            {renter.mailing_address ? <Text style={s.meta}>Mailing: {renter.mailing_address}</Text> : null}
            {renter.phone ? <Text style={s.meta}>Phone: {renter.phone}</Text> : null}
            {renter.email ? <Text style={s.meta}>Email: {renter.email}</Text> : null}
          </View>
        ) : null}
      </View>

      <TouchableOpacity style={s.btn} onPress={createLead} testID="property-create-lead">
        <Text style={s.btnText}>{leadId ? "Open existing lead" : "Create lead from this property"}</Text>
      </TouchableOpacity>

      <Text style={s.h}>Do Not Knock</Text>
      <View style={s.card}>
        <Text style={s.meta} testID="property-dnk-status">Status: {prop.do_not_knock ? "ON" : "OFF"}{prop.do_not_knock && prop.do_not_knock_reason ? ` — ${prop.do_not_knock_reason}` : ""}</Text>
        {prop.do_not_knock ? (
          <TouchableOpacity style={s.btnOutline} onPress={() => toggleDNK(false)} testID="property-dnk-off"><Text style={s.btnOutlineText}>Turn Do Not Knock OFF</Text></TouchableOpacity>
        ) : (
          <TouchableOpacity style={[s.btnOutline, { borderColor: C.dnk }]} onPress={() => toggleDNK(true)} testID="property-dnk-on"><Text style={[s.btnOutlineText, { color: C.dnk }]}>Turn Do Not Knock ON</Text></TouchableOpacity>
        )}
      </View>

      <Text style={s.h}>Record visit</Text>
      <View style={s.outcomes}>
        {outcomes.map(([value, label]) => {
          const sel = outcome === value;
          const isDnk = value === "do_not_knock";
          return (
            <TouchableOpacity key={value} testID={`property-visit-${value}`}
              style={[s.chip, sel && s.chipOn, isDnk && { borderColor: C.dnk }]} onPress={() => setOutcome(value)}>
              <Text style={[s.chipText, sel && s.chipTextOn, isDnk && !sel && { color: C.dnk }]}>{label}</Text>
            </TouchableOpacity>
          );
        })}
      </View>
      <TextInput style={s.notes} placeholder="Notes (optional)" value={notes} onChangeText={setNotes}
        multiline testID="property-visit-notes" placeholderTextColor={C.sub} />
      <TouchableOpacity style={s.btn} onPress={recordVisit} testID="property-visit-save">
        <Text style={s.btnText}>Save visit</Text>
      </TouchableOpacity>

      <TouchableOpacity style={s.btnOutline} onPress={() => navigation.getParent()?.navigate("LeadsTab", { screen: "Inspection", params: { property_id: id } })} testID="property-inspection">
        <Text style={s.btnOutlineText}>Inspection</Text>
      </TouchableOpacity>

      <PhotoSection recordType="property" recordId={id} />

      <Text style={s.h}>Visit history</Text>
      {(prop.visits || []).map((v) => (
        <View key={v.id} style={s.visit}>
          <Text style={s.visitOut}>{OUTCOME_LABEL[v.outcome] || v.outcome}</Text>
          <Text style={s.visitMeta}>{new Date(v.visited_at).toLocaleString()} · {v.user_email}</Text>
          {v.notes ? <Text style={s.visitNote}>{v.notes}</Text> : null}
        </View>
      ))}
      {(prop.visits || []).length === 0 && <Text style={s.empty}>No visits yet.</Text>}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 16 },
  staleBar: { backgroundColor: "#FEF3C7", color: "#92400E", textAlign: "center", paddingVertical: 6, fontSize: 12, fontWeight: "600", borderRadius: 8, marginBottom: 10 },
  conflict: { backgroundColor: "#FEF2F2", borderWidth: 1, borderColor: "#FCA5A5", borderRadius: 12, padding: 14, marginBottom: 12 },
  conflictTitle: { color: "#991B1B", fontWeight: "800", fontSize: 15 },
  conflictSub: { color: "#B91C1C", marginTop: 2, fontSize: 13 },
  conflictRow: { flexDirection: "row", gap: 10, marginTop: 12 },
  conflictBtn: { flex: 1, backgroundColor: "#DC2626", borderRadius: 10, paddingVertical: 12, alignItems: "center" },
  conflictBtnText: { color: "#fff", fontWeight: "800" },
  conflictBtnAlt: { backgroundColor: "#fff", borderWidth: 2, borderColor: "#DC2626" },
  conflictBtnTextAlt: { color: "#DC2626" },
  dnk: { backgroundColor: C.dnk, borderRadius: 12, padding: 16, marginBottom: 14 },
  dnkText: { color: "#fff", fontSize: 22, fontWeight: "900" },
  dnkSub: { color: "#FEE2E2", marginTop: 2 },
  addr: { fontSize: 22, fontWeight: "800", color: C.ink },
  card: { backgroundColor: "#fff", borderRadius: 10, padding: 12, borderWidth: 1, borderColor: C.line },
  contactBlock: { marginTop: 8, paddingTop: 8, borderTopWidth: 1, borderTopColor: C.line },
  contactName: { fontWeight: "700", color: C.ink },
  meta: { fontSize: 14, color: C.sub, marginTop: 4 },
  h: { fontSize: 16, fontWeight: "700", color: C.ink, marginTop: 20, marginBottom: 8 },
  outcomes: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { borderWidth: 2, borderColor: C.line, borderRadius: 24, paddingVertical: 12, paddingHorizontal: 16 },
  chipOn: { backgroundColor: C.brand, borderColor: C.brand },
  chipText: { fontWeight: "700", color: C.ink },
  chipTextOn: { color: "#fff" },
  notes: { backgroundColor: "#fff", borderWidth: 1, borderColor: C.line, borderRadius: 10, padding: 12, marginTop: 12, minHeight: 60, color: C.ink, textAlignVertical: "top" },
  btn: { backgroundColor: C.brand, borderRadius: 12, padding: 16, alignItems: "center", marginTop: 14 },
  btnText: { color: "#fff", fontSize: 16, fontWeight: "800" },
  btnOutline: { borderWidth: 2, borderColor: C.brand, borderRadius: 12, padding: 14, alignItems: "center", marginTop: 12 },
  btnOutlineText: { color: C.brand, fontWeight: "800" },
  visit: { backgroundColor: "#fff", borderRadius: 10, padding: 12, marginBottom: 8, borderWidth: 1, borderColor: C.line },
  visitOut: { fontWeight: "700", color: C.ink },
  visitMeta: { fontSize: 12, color: C.sub },
  visitNote: { fontSize: 14, color: C.ink, marginTop: 4 },
  empty: { color: C.sub, fontStyle: "italic" },
});

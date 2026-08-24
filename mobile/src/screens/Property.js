import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, TouchableOpacity, StyleSheet, Alert } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { cache, patchCachedDetail } from "../cache";
import { queueMutation } from "../sync";
import { C } from "../theme";
import PhotoSection from "../components/PhotoSection";

const OUTCOMES = ["no_answer", "interested", "not_interested", "do_not_knock"];

// Open a canvass Property from My Area and continue the field workflow (record visit / create lead).
export default function Property({ route, navigation }) {
  const { id } = route.params;
  const [prop, setProp] = useState(null);
  const [stale, setStale] = useState(false);

  const load = useCallback(async () => {
    const r = await cache.property(id);
    setProp(r.data); setStale(!!r.stale);
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!prop) return <View style={s.wrap}><Text>Loading…</Text></View>;

  const recordVisit = async (outcome) => {
    await queueMutation({ kind: "visit", method: "post", path: "/mobile/visits", body: { property_id: id, outcome }, label: `Visit — ${outcome}` });
    if (outcome === "do_not_knock") { setProp((p) => ({ ...p, do_not_knock: true })); await patchCachedDetail(`property:${id}`, { do_not_knock: true }); }
    Alert.alert("Saved offline", "Visit recorded — we'll sync when Office is available.");
  };

  const createLead = () => {
    if (prop.existing_lead_id) {
      return navigation.getParent()?.navigate("LeadsTab", { screen: "LeadDetail", params: { id: prop.existing_lead_id } });
    }
    navigation.navigate("NewLead", { property_id: id, name: prop.owner_name || "", address: prop.formatted_address });
  };

  return (
    <ScrollView style={s.wrap} contentContainerStyle={{ paddingBottom: 40 }}>
      {stale ? <Text style={s.staleBar}>Showing saved copy — offline</Text> : null}
      {prop.do_not_knock ? (
        <View style={s.dnk} testID="property-dnk-banner">
          <Text style={s.dnkText}>DO NOT KNOCK</Text>
          {prop.do_not_knock_reason ? <Text style={s.dnkSub}>{prop.do_not_knock_reason}</Text> : null}
        </View>
      ) : null}

      <Text style={s.addr} testID="property-address">{prop.formatted_address}</Text>
      {prop.owner_name ? <Text style={s.meta}>Owner: {prop.owner_name}</Text> : null}
      {prop.owner_phone ? <Text style={s.meta}>{prop.owner_phone}</Text> : null}
      {prop.property_type ? <Text style={s.meta}>{prop.property_type}</Text> : null}

      <TouchableOpacity style={s.btn} onPress={createLead} testID="property-create-lead">
        <Text style={s.btnText}>{prop.existing_lead_id ? "Open existing lead" : "Create lead from this property"}</Text>
      </TouchableOpacity>

      <Text style={s.h}>Record visit</Text>
      <View style={s.outcomes}>
        {OUTCOMES.map((o) => (
          <TouchableOpacity key={o} style={[s.chip, o === "do_not_knock" && { borderColor: C.dnk }]} onPress={() => recordVisit(o)} testID={`property-visit-${o}`}>
            <Text style={[s.chipText, o === "do_not_knock" && { color: C.dnk }]}>{o.replace(/_/g, " ")}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <TouchableOpacity style={s.btnOutline} onPress={() => navigation.getParent()?.navigate("LeadsTab", { screen: "Inspection", params: { property_id: id } })} testID="property-inspection">
        <Text style={s.btnOutlineText}>Inspection</Text>
      </TouchableOpacity>

      <PhotoSection recordType="property" recordId={id} />

      <Text style={s.h}>Visit history</Text>
      {(prop.visits || []).map((v) => (
        <View key={v.id} style={s.visit}><Text style={s.visitOut}>{v.outcome}</Text><Text style={s.visitMeta}>{new Date(v.visited_at).toLocaleString()} · {v.user_email}</Text>{v.notes ? <Text style={s.visitNote}>{v.notes}</Text> : null}</View>
      ))}
      {(prop.visits || []).length === 0 && <Text style={s.empty}>No visits yet.</Text>}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 16 },
  staleBar: { backgroundColor: "#FEF3C7", color: "#92400E", textAlign: "center", paddingVertical: 6, fontSize: 12, fontWeight: "600", borderRadius: 8, marginBottom: 10 },
  dnk: { backgroundColor: C.dnk, borderRadius: 12, padding: 16, marginBottom: 14 },
  dnkText: { color: "#fff", fontSize: 22, fontWeight: "900" },
  dnkSub: { color: "#FEE2E2", marginTop: 2 },
  addr: { fontSize: 22, fontWeight: "800", color: C.ink },
  meta: { fontSize: 14, color: C.sub, marginTop: 4 },
  h: { fontSize: 16, fontWeight: "700", color: C.ink, marginTop: 20, marginBottom: 8 },
  outcomes: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { borderWidth: 2, borderColor: C.line, borderRadius: 24, paddingVertical: 12, paddingHorizontal: 16 },
  chipText: { fontWeight: "700", color: C.ink, textTransform: "capitalize" },
  btn: { backgroundColor: C.brand, borderRadius: 12, padding: 16, alignItems: "center", marginTop: 18 },
  btnText: { color: "#fff", fontSize: 16, fontWeight: "800" },
  btnOutline: { borderWidth: 2, borderColor: C.brand, borderRadius: 12, padding: 14, alignItems: "center", marginTop: 12 },
  btnOutlineText: { color: C.brand, fontWeight: "800" },
  visit: { backgroundColor: "#fff", borderRadius: 10, padding: 12, marginBottom: 8, borderWidth: 1, borderColor: C.line },
  visitOut: { fontWeight: "700", color: C.ink, textTransform: "capitalize" },
  visitMeta: { fontSize: 12, color: C.sub },
  visitNote: { fontSize: 14, color: C.ink, marginTop: 4 },
  empty: { color: C.sub, fontStyle: "italic" },
});

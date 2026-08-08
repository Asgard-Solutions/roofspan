import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, StyleSheet, RefreshControl, TouchableOpacity } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { api } from "../api";
import { putCache, getCache } from "../storage";
import { pendingSummary, runSync } from "../sync";
import { C, badge } from "../theme";

export default function Home({ navigation }) {
  const [leads, setLeads] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [counts, setCounts] = useState({ pending: 0, failed: 0, conflict: 0, synced: 0 });
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      await runSync();
      const [l, j] = await Promise.all([api.get("/mobile/leads"), api.get("/mobile/jobs")]);
      setLeads(l.data); setJobs(j.data);
      await putCache("leads", l.data); await putCache("jobs", j.data);
    } catch (e) {
      setLeads((await getCache("leads")) || []);
      setJobs((await getCache("jobs")) || []);
    }
    setCounts((await pendingSummary()).counts);
    setRefreshing(false);
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const open = leads.filter((l) => l.status !== "won" && l.status !== "lost");

  return (
    <ScrollView style={s.wrap} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} />}>
      <Text style={s.h}>Today</Text>
      <View style={s.row}>
        <Stat label="Open leads" value={open.length} />
        <Stat label="Jobs" value={jobs.length} />
        <Stat label="Pending sync" value={counts.pending + counts.failed + counts.conflict} highlight={counts.conflict > 0 || counts.failed > 0} />
      </View>

      {(counts.pending || counts.failed || counts.conflict) ? (
        <View style={s.syncBar} testID="home-sync-status">
          <Text style={s.syncText}>
            {counts.pending ? `${counts.pending} pending · ` : ""}
            {counts.failed ? `${counts.failed} failed · ` : ""}
            {counts.conflict ? `${counts.conflict} conflict` : ""}
          </Text>
          <TouchableOpacity onPress={load}><Text style={s.syncBtn}>Sync now</Text></TouchableOpacity>
        </View>
      ) : (
        <View style={[s.syncBar, { backgroundColor: badge.synced.bg }]}><Text style={[s.syncText, { color: badge.synced.fg }]}>All field work synced</Text></View>
      )}

      <Text style={s.h2}>Assigned / open leads</Text>
      {open.slice(0, 6).map((l) => (
        <TouchableOpacity key={l.id} style={s.card} onPress={() => navigation.navigate("LeadsTab", { screen: "LeadDetail", params: { id: l.id } })} testID={`home-lead-${l.id}`}>
          <Text style={s.cardTitle}>{l.name}</Text>
          <Text style={s.cardSub}>{l.property_address || l.address || "—"}</Text>
        </TouchableOpacity>
      ))}
      {open.length === 0 && <Text style={s.empty}>No open leads.</Text>}
    </ScrollView>
  );
}

function Stat({ label, value, highlight }) {
  return (
    <View style={[s.stat, highlight && { borderColor: C.danger }]}>
      <Text style={[s.statVal, highlight && { color: C.danger }]}>{value}</Text>
      <Text style={s.statLabel}>{label}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 16 },
  h: { fontSize: 26, fontWeight: "800", color: C.ink, marginBottom: 12 },
  h2: { fontSize: 16, fontWeight: "700", color: C.sub, marginTop: 18, marginBottom: 8 },
  row: { flexDirection: "row", gap: 10 },
  stat: { flex: 1, backgroundColor: "#fff", borderRadius: 14, padding: 16, borderWidth: 2, borderColor: C.line },
  statVal: { fontSize: 30, fontWeight: "800", color: C.ink },
  statLabel: { fontSize: 12, color: C.sub, marginTop: 2 },
  syncBar: { marginTop: 16, backgroundColor: "#FEF3C7", borderRadius: 12, padding: 14, flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  syncText: { color: "#92400E", fontWeight: "600" },
  syncBtn: { color: C.brand, fontWeight: "800" },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 16, marginBottom: 10, borderWidth: 1, borderColor: C.line },
  cardTitle: { fontSize: 18, fontWeight: "700", color: C.ink },
  cardSub: { fontSize: 14, color: C.sub, marginTop: 2 },
  empty: { color: C.sub, fontStyle: "italic" },
});

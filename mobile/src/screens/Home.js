import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, StyleSheet, RefreshControl, TouchableOpacity } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { cache } from "../cache";
import { pendingSummary, runSync, lastSyncAt } from "../sync";
import SyncStatusChip from "../components/SyncStatusChip";
import { C, badge } from "../theme";

const ACTION_STATUSES = ["new", "contacted", "interested", "qualified"];

export default function Home({ navigation }) {
  const [leads, setLeads] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [sections, setSections] = useState([]);
  const [summary, setSummary] = useState({ counts: { pending: 0, failed: 0, conflict: 0 }, label: "All changes synced", waiting: 0 });
  const [last, setLast] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    await runSync().catch(() => {});
    const [l, j, s] = await Promise.all([cache.leads(), cache.jobs(), cache.sections()]);
    setLeads(l.data || []);
    setJobs(j.data || []);
    setSections((s.data && s.data.sections) || []);
    setSummary(await pendingSummary());
    setLast(await lastSyncAt());
    setRefreshing(false);
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const open = leads.filter((l) => l.status !== "won" && l.status !== "lost" && l.status !== "archived");
  const needAction = open.filter((l) => ACTION_STATUSES.includes(l.status));
  const today = new Date().toDateString();
  const todayJobs = jobs.filter((j) => j.scheduled_start && new Date(j.scheduled_start).toDateString() === today);
  const hasIssues = (summary.counts.conflict || 0) > 0 || (summary.counts.failed || 0) > 0;
  // RN7: navigate() no longer goes back to an existing screen (it pushes). Pass { pop: true } to
  // preserve the RN6 behavior for these tab shortcuts so they return to the target's root/instance
  // instead of stacking a duplicate on top of a deep nested stack.
  const goLeads = () => navigation.navigate("LeadsTab", { screen: "Leads" }, { pop: true });
  const goNewLead = () => navigation.navigate("LeadsTab", { screen: "NewLead", params: {} }, { pop: true });
  const goMap = () => navigation.navigate("Map");
  const goJobs = () => navigation.navigate("JobsTab", { screen: "Jobs" }, { pop: true });

  return (
    <ScrollView style={s.wrap} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} />}>
      <Text style={s.h}>My Day</Text>
      <SyncStatusChip testid="home-sync-chip" />
      <View style={s.row}>
        <Stat label="Open leads" value={open.length} onPress={goLeads} testID="stat-open-leads" />
        <Stat label="Today's jobs" value={todayJobs.length} onPress={goJobs} testID="stat-today-jobs" />
        <Stat label="Pending sync" value={summary.waiting} highlight={hasIssues} testID="stat-pending-sync" />
      </View>

      <View style={[s.syncBar, hasIssues ? s.syncWarn : s.syncOk]} testID="home-sync-status">
        <View style={{ flex: 1 }}>
          <Text style={[s.syncText, hasIssues && { color: "#991B1B" }]}>{summary.label}</Text>
          {last ? <Text style={s.syncSub}>Last synced {new Date(last).toLocaleString()}</Text> : <Text style={s.syncSub}>Not synced yet</Text>}
        </View>
        <TouchableOpacity onPress={load} testID="home-sync-now"><Text style={s.syncBtn}>Sync now</Text></TouchableOpacity>
      </View>

      <View style={s.actions}>
        <Action label="New Lead" onPress={goNewLead} testID="action-new-lead" />
        <Action label="My Leads" onPress={goLeads} testID="action-my-leads" />
        <Action label="My Area" onPress={goMap} testID="action-my-area" />
        <Action label="My Jobs" onPress={goJobs} testID="action-my-jobs" />
      </View>

      <Text style={s.h2}>My area</Text>
      {sections.length === 0 ? <Text style={s.empty}>No canvass area assigned yet.</Text> : (
        <TouchableOpacity style={s.card} onPress={goMap} testID="home-area">
          <Text style={s.cardTitle}>{sections[0].name}{sections.length > 1 ? ` +${sections.length - 1} more` : ""}</Text>
          <Text style={s.cardSub}>{sections.reduce((n, x) => n + (x.property_count || 0), 0)} properties in your assigned area</Text>
        </TouchableOpacity>
      )}

      <Text style={s.h2}>Leads needing action</Text>
      {needAction.slice(0, 6).map((l) => (
        <TouchableOpacity key={l.id} style={s.card} onPress={() => navigation.navigate("LeadsTab", { screen: "LeadDetail", params: { id: l.id } }, { pop: true })} testID={`home-lead-${l.id}`}>
          <Text style={s.cardTitle}>{l.name}</Text>
          <Text style={s.cardSub}>{l.property_address || l.address || "—"} · {l.status}</Text>
        </TouchableOpacity>
      ))}
      {needAction.length === 0 && <Text style={s.empty}>Nothing needs action right now.</Text>}
    </ScrollView>
  );
}

function Stat({ label, value, highlight, onPress, testID }) {
  return (
    <TouchableOpacity style={[s.stat, highlight && { borderColor: C.danger }]} onPress={onPress} testID={testID}>
      <Text style={[s.statVal, highlight && { color: C.danger }]}>{value}</Text>
      <Text style={s.statLabel}>{label}</Text>
    </TouchableOpacity>
  );
}
function Action({ label, onPress, testID }) {
  return <TouchableOpacity style={s.action} onPress={onPress} testID={testID}><Text style={s.actionText}>{label}</Text></TouchableOpacity>;
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 16 },
  h: { fontSize: 26, fontWeight: "800", color: C.ink, marginBottom: 12 },
  h2: { fontSize: 16, fontWeight: "700", color: C.sub, marginTop: 18, marginBottom: 8 },
  row: { flexDirection: "row", gap: 10 },
  stat: { flex: 1, backgroundColor: "#fff", borderRadius: 14, padding: 16, borderWidth: 2, borderColor: C.line },
  statVal: { fontSize: 28, fontWeight: "800", color: C.ink },
  statLabel: { fontSize: 12, color: C.sub, marginTop: 2 },
  syncBar: { marginTop: 16, borderRadius: 12, padding: 14, flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  syncOk: { backgroundColor: badge.synced.bg },
  syncWarn: { backgroundColor: "#FEE2E2" },
  syncText: { color: "#065F46", fontWeight: "700" },
  syncSub: { color: C.sub, fontSize: 12, marginTop: 2 },
  syncBtn: { color: C.brand, fontWeight: "800" },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 14 },
  action: { backgroundColor: "#fff", borderWidth: 2, borderColor: C.brand, borderRadius: 12, paddingVertical: 12, paddingHorizontal: 14, flexGrow: 1, alignItems: "center" },
  actionText: { color: C.brand, fontWeight: "800" },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 16, marginBottom: 10, borderWidth: 1, borderColor: C.line },
  cardTitle: { fontSize: 18, fontWeight: "700", color: C.ink },
  cardSub: { fontSize: 14, color: C.sub, marginTop: 2 },
  empty: { color: C.sub, fontStyle: "italic" },
});

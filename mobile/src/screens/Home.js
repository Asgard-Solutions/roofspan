import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, StyleSheet, RefreshControl, TouchableOpacity } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { cache } from "../cache";
import { pendingSummary, runSync, lastSyncAt, measurementAttention, onSyncChange } from "../sync";
import SyncStatusChip from "../components/SyncStatusChip";
import { C, badge } from "../theme";
const { myDayView, fmt, OPEN_STATUSES } = require("../followups");

export default function Home({ navigation }) {
  const [leads, setLeads] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [sections, setSections] = useState([]);
  const [myDay, setMyDay] = useState(null);
  const [myDayStale, setMyDayStale] = useState(false);
  const [summary, setSummary] = useState({ counts: { pending: 0, failed: 0, conflict: 0 }, label: "All changes synced", waiting: 0 });
  const [last, setLast] = useState(null);
  const [attention, setAttention] = useState({ conflicts: [], failures: [] });
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    await runSync().catch(() => {});
    const [l, j, s, md] = await Promise.all([cache.leads(), cache.jobs(), cache.sections(), cache.myDay()]);
    setMyDay(md.data || null);
    setMyDayStale(!!md.stale);
    setLeads(l.data || []);
    setJobs(j.data || []);
    setSections((s.data && s.data.sections) || []);
    setSummary(await pendingSummary());
    setLast(await lastSyncAt());
    setAttention(measurementAttention());
    setRefreshing(false);
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Startup recovery reports conflicts/failures asynchronously — adopt them as soon as it finishes.
  useFocusEffect(useCallback(() => {
    const off = onSyncChange((e) => {
      if (e && (e.type === "measurement_recovery_done" || e.type === "measurement_reconciled")) setAttention(measurementAttention());
    });
    return off;
  }, []));

  // Measurements that need explicit review after recovery (durable conflicts + failed syncs).
  const reviewItems = [
    ...((attention.conflicts) || []).map((x) => ({ ...x, tone: "conflict", label: "Conflict — review required" })),
    ...((attention.failures) || []).map((x) => ({ ...x, tone: "failed", label: x.error || "Sync failed — retry needed" })),
  ];
  const goReview = (item) => {
    const sc = item.scope || {};
    if (sc.lead_id) navigation.navigate("LeadsTab", { screen: "LeadDetail", params: { id: sc.lead_id } }, { pop: true });
    else navigation.navigate("Map");
  };

  const open = leads.filter((l) => OPEN_STATUSES.includes(l.status));
  const day = myDayView(myDay);
  const goLead = (leadId) => navigation.navigate("LeadsTab", { screen: "LeadDetail", params: { id: leadId } }, { pop: true });
  const today = new Date().toDateString();
  const todayJobs = jobs.filter((j) => j.scheduled_start && new Date(j.scheduled_start).toDateString() === today);
  const hasIssues = (summary.counts.conflict || 0) > 0 || (summary.counts.failed || 0) > 0 || (summary.counts.locked || 0) > 0;
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

      {reviewItems.length > 0 && (
        <View testID="home-meas-review">
          <Text style={s.h2}>Measurements needing review</Text>
          {reviewItems.slice(0, 6).map((item, i) => (
            <TouchableOpacity key={`${item.tone}-${item.client_id || item.revisionId || i}`} style={[s.card, s.reviewCard]} onPress={() => goReview(item)} testID={`home-meas-review-${i}`}>
              <Text style={[s.cardTitle, { color: "#991B1B", fontSize: 15 }]}>{item.tone === "conflict" ? "Conflict — review required" : "Sync failed — retry needed"}</Text>
              <Text style={s.cardSub}>{item.label}{item.scope && item.scope.lead_id ? " · tap to open the lead" : ""}</Text>
            </TouchableOpacity>
          ))}
        </View>
      )}

      <Text style={s.h2}>My area</Text>      {sections.length === 0 ? <Text style={s.empty}>No canvass area assigned yet.</Text> : (
        <TouchableOpacity style={s.card} onPress={goMap} testID="home-area">
          <Text style={s.cardTitle}>{sections[0].name}{sections.length > 1 ? ` +${sections.length - 1} more` : ""}</Text>
          <Text style={s.cardSub}>{sections.reduce((n, x) => n + (x.property_count || 0), 0)} properties in your assigned area</Text>
        </TouchableOpacity>
      )}

      {myDayStale ? <Text style={s.stale} testID="myday-offline">My Day as of last sync — due times use this phone's clock</Text> : null}
      <DayList title="Overdue" tone="overdue" items={day.overdue} onOpen={goLead} empty="Nothing overdue." testID="myday-overdue" />
      <DayList title="Due today" tone="today" items={day.today} onOpen={goLead} empty="No follow-ups due today." testID="myday-today" />
      <DayList title="Inspections" items={day.inspections} onOpen={goLead} empty="No inspections booked this week." testID="myday-inspections"
        meta={(i) => (i.when === "overdue" ? "Results missing" : fmt(i.date))} />
      <DayList title="Proposals needing attention" items={day.proposals} onOpen={goLead} empty="No proposals need attention." testID="myday-proposals"
        meta={(i) => i.reason} />
      <DayList title={`No follow-up set (${day.noFollowUp.count})`} items={(day.noFollowUp.items || []).slice(0, 5)} onOpen={goLead}
        empty="Every open lead has a next step." testID="myday-no-followup" meta={(i) => i.subtitle} hideSub />
    </ScrollView>
  );
}

function DayList({ title, items, onOpen, empty, testID, tone, meta, hideSub }) {
  return (
    <View testID={testID}>
      <Text style={[s.h2, tone === "overdue" && items.length ? { color: C.danger } : null]}>{title}{items.length ? ` · ${items.length}` : ""}</Text>
      {items.map((i, n) => (
        <TouchableOpacity key={i.id || n} style={[s.card, tone === "overdue" && { borderColor: "#FCA5A5" }]} onPress={() => onOpen(i.lead_id)} testID={`${testID}-${n}`}>
          <Text style={s.cardTitle}>{i.title}</Text>
          {!hideSub && i.subtitle ? <Text style={s.cardSub}>{i.subtitle}</Text> : null}
          <Text style={[s.cardSub, { fontWeight: "700" }]}>{meta ? meta(i) : fmt(i.date)}{i._pending ? " · waiting to sync" : ""}</Text>
        </TouchableOpacity>
      ))}
      {items.length === 0 && <Text style={s.empty}>{empty}</Text>}
    </View>
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
  reviewCard: { borderColor: "#FCA5A5", backgroundColor: "#FEF2F2" },
  cardTitle: { fontSize: 18, fontWeight: "700", color: C.ink },
  cardSub: { fontSize: 14, color: C.sub, marginTop: 2 },
  empty: { color: C.sub, fontStyle: "italic" },
  stale: { backgroundColor: "#FEF3C7", color: "#92400E", textAlign: "center", paddingVertical: 6, fontSize: 12, fontWeight: "600", borderRadius: 8, marginTop: 14 },
});

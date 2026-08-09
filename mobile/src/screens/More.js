import React, { useCallback, useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { useAuth } from "../auth";
import { pendingSummary, runSync } from "../sync";
import { API_BASE } from "../config";
import { C, badge } from "../theme";

export default function More() {
  const { user, logout } = useAuth();
  const [counts, setCounts] = useState({ pending: 0, failed: 0, conflict: 0, synced: 0 });
  const [attention, setAttention] = useState([]);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async () => {
    const { counts: c, items } = await pendingSummary();
    setCounts(c);
    // Items that need the field user's attention (not yet synced), newest first.
    setAttention(
      items
        .filter((m) => m.state !== "synced")
        .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""))
    );
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const syncNow = async () => {
    setSyncing(true);
    try { await runSync(); } finally { setSyncing(false); load(); }
  };

  const labelFor = (m) => m.label || (m.kind ? m.kind.replace(/_/g, " ") : "Field update");

  return (
    <View style={s.wrap}>
      <Text style={s.h}>Account</Text>
      <View style={s.card}>
        <Text style={s.name}>{user?.full_name || user?.email}</Text>
        <Text style={s.role}>{user?.role}</Text>
      </View>

      <Text style={s.h}>Sync status</Text>
      <View style={s.card} testID="more-sync">
        {["pending", "failed", "conflict", "synced"].map((k) => (
          <View key={k} style={s.syncRow}>
            <Text style={s.syncLabel}>{badge[k].label}</Text>
            <Text style={[s.syncVal, { color: badge[k].fg }]}>{counts[k] || 0}</Text>
          </View>
        ))}
        <TouchableOpacity style={s.syncBtn} onPress={syncNow} disabled={syncing} testID="more-sync-now">
          <Text style={s.syncBtnText}>{syncing ? "Syncing…" : "Sync now"}</Text>
        </TouchableOpacity>
      </View>

      {attention.length > 0 && (
        <>
          <Text style={s.h}>Needs attention</Text>
          <View style={s.card} testID="more-attention">
            {attention.map((m) => {
              const b = badge[m.state] || badge.pending;
              return (
                <View key={m.client_id} style={s.attRow} testID={`att-${m.client_id}`}>
                  <View style={{ flex: 1, paddingRight: 8 }}>
                    <Text style={s.attLabel}>{labelFor(m)}</Text>
                    {m.state === "conflict" && m.error ? <Text style={s.attErr}>{m.error}</Text> : null}
                    {m.state === "failed" && m.error ? <Text style={s.attErrMuted}>{m.error}</Text> : null}
                  </View>
                  <View style={[s.pill, { backgroundColor: b.bg }]}><Text style={[s.pillText, { color: b.fg }]}>{b.label}</Text></View>
                </View>
              );
            })}
            <Text style={s.attHint}>Pending &amp; failed items retry automatically on “Sync now”. Conflicts kept your changes without overwriting the office — reopen the record to update again.</Text>
          </View>
        </>
      )}

      <Text style={s.h}>App</Text>
      <View style={s.card}>
        <Text style={s.meta}>RoofSpan Field v1.0.0</Text>
        <Text style={s.metaSm}>{API_BASE}</Text>
      </View>

      <TouchableOpacity style={s.logout} onPress={logout} testID="more-logout"><Text style={s.logoutText}>Log out</Text></TouchableOpacity>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 16 },
  h: { fontSize: 16, fontWeight: "700", color: C.sub, marginTop: 18, marginBottom: 8 },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 16, borderWidth: 1, borderColor: C.line },
  name: { fontSize: 18, fontWeight: "800", color: C.ink },
  role: { fontSize: 13, color: C.brand, fontWeight: "700", textTransform: "uppercase" },
  syncRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6 },
  syncLabel: { color: C.ink, fontSize: 15 },
  syncVal: { fontWeight: "800", fontSize: 15 },
  syncBtn: { backgroundColor: C.brand, borderRadius: 10, padding: 12, alignItems: "center", marginTop: 10 },
  syncBtnText: { color: "#fff", fontWeight: "800" },
  attRow: { flexDirection: "row", alignItems: "center", paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: C.line },
  attLabel: { color: C.ink, fontSize: 15, fontWeight: "700", textTransform: "capitalize" },
  attErr: { color: C.warn, fontSize: 12, marginTop: 2 },
  attErrMuted: { color: C.sub, fontSize: 12, marginTop: 2 },
  attHint: { color: C.sub, fontSize: 12, marginTop: 10, lineHeight: 17 },
  pill: { borderRadius: 8, paddingVertical: 3, paddingHorizontal: 8 },
  pillText: { fontSize: 11, fontWeight: "800" },
  meta: { color: C.ink, fontWeight: "600" },
  metaSm: { color: C.sub, fontSize: 12, marginTop: 2 },
  logout: { borderWidth: 2, borderColor: C.danger, borderRadius: 12, padding: 16, alignItems: "center", marginTop: 24 },
  logoutText: { color: C.danger, fontWeight: "800", fontSize: 16 },
});

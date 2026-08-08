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

  const load = useCallback(async () => { setCounts((await pendingSummary()).counts); }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

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
        <TouchableOpacity style={s.syncBtn} onPress={async () => { await runSync(); load(); }} testID="more-sync-now">
          <Text style={s.syncBtnText}>Sync now</Text>
        </TouchableOpacity>
      </View>

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
  meta: { color: C.ink, fontWeight: "600" },
  metaSm: { color: C.sub, fontSize: 12, marginTop: 2 },
  logout: { borderWidth: 2, borderColor: C.danger, borderRadius: 12, padding: 16, alignItems: "center", marginTop: 24 },
  logoutText: { color: C.danger, fontWeight: "800", fontSize: 16 },
});

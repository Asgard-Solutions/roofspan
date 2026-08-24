import React, { useCallback, useState } from "react";
import { View, Text, FlatList, TouchableOpacity, StyleSheet, RefreshControl } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { cache } from "../cache";
import { C } from "../theme";

export default function Leads({ navigation }) {
  const [rows, setRows] = useState([]);
  const [stale, setStale] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    const r = await cache.leads();
    setRows(r.data || []);
    setStale(!!r.stale);
    setRefreshing(false);
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <View style={{ flex: 1 }}>
      {stale ? <Text style={s.stale} testID="leads-offline-banner">Showing saved copy — offline</Text> : null}
      <FlatList
        style={s.wrap}
        data={rows}
        keyExtractor={(i) => i.id}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} />}
        ListEmptyComponent={<Text style={s.empty}>No leads assigned to you yet.</Text>}
        renderItem={({ item }) => (
          <TouchableOpacity style={s.card} onPress={() => navigation.navigate("LeadDetail", { id: item.id })} testID={`lead-${item.id}`}>
            <Text style={s.title}>{item.name}</Text>
            <Text style={s.sub}>{item.property_address || item.address || "—"}</Text>
            <View style={s.rowB}>
              <Text style={s.status}>{item.status}</Text>
              {item._pending ? <Text style={s.pending} testID={`lead-pending-${item.id}`}>Waiting to sync</Text> : null}
            </View>
          </TouchableOpacity>
        )}
      />
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 14 },
  stale: { backgroundColor: "#FEF3C7", color: "#92400E", textAlign: "center", paddingVertical: 6, fontSize: 12, fontWeight: "600" },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 16, marginBottom: 10, borderWidth: 1, borderColor: C.line },
  title: { fontSize: 18, fontWeight: "700", color: C.ink },
  sub: { fontSize: 14, color: C.sub, marginTop: 2 },
  rowB: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 6 },
  status: { fontSize: 12, color: C.brand, fontWeight: "700", textTransform: "uppercase" },
  pending: { fontSize: 11, color: C.warn, fontWeight: "700" },
  empty: { color: C.sub, fontStyle: "italic", padding: 20 },
});

import React, { useCallback, useState } from "react";
import { View, Text, FlatList, TouchableOpacity, StyleSheet, RefreshControl } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { cache } from "../cache";
import { C } from "../theme";

export default function Jobs({ navigation }) {
  const [rows, setRows] = useState([]);
  const [stale, setStale] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    const r = await cache.jobs();
    setRows(r.data || []); setStale(!!r.stale);
    setRefreshing(false);
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <View style={{ flex: 1 }}>
      {stale ? <Text style={s.stale} testID="jobs-offline-banner">Showing saved copy — offline</Text> : null}
      <FlatList
        style={s.wrap}
        data={rows}
        keyExtractor={(i) => i.id}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} />}
        ListEmptyComponent={<Text style={s.empty}>No jobs assigned to you.</Text>}
        renderItem={({ item }) => (
          <TouchableOpacity style={s.card} onPress={() => navigation.navigate("JobDetail", { id: item.id })} testID={`job-${item.id}`}>
            <Text style={s.title}>{item.number}</Text>
            <Text style={s.sub}>{item.scope || "—"}</Text>
            <Text style={s.status}>{item.status}</Text>
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
  title: { fontSize: 18, fontWeight: "800", color: C.ink },
  sub: { fontSize: 14, color: C.sub, marginTop: 2 },
  status: { fontSize: 12, color: C.brand, marginTop: 6, fontWeight: "700", textTransform: "uppercase" },
  empty: { color: C.sub, fontStyle: "italic", padding: 20 },
});

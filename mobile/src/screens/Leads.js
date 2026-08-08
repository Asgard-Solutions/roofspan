import React, { useCallback, useState } from "react";
import { View, Text, FlatList, TouchableOpacity, StyleSheet, RefreshControl } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { api } from "../api";
import { putCache, getCache } from "../storage";
import { C } from "../theme";

export default function Leads({ navigation }) {
  const [rows, setRows] = useState([]);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const r = await api.get("/leads");
      setRows(r.data);
      await putCache("leads", r.data);
    } catch (e) {
      setRows((await getCache("leads")) || []);
    }
    setRefreshing(false);
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <FlatList
      style={s.wrap}
      data={rows}
      keyExtractor={(i) => i.id}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} />}
      ListEmptyComponent={<Text style={s.empty}>No leads.</Text>}
      renderItem={({ item }) => (
        <TouchableOpacity style={s.card} onPress={() => navigation.navigate("LeadDetail", { id: item.id })} testID={`lead-${item.id}`}>
          <Text style={s.title}>{item.name}</Text>
          <Text style={s.sub}>{item.property_address || item.address || "—"}</Text>
          <Text style={s.status}>{item.status}</Text>
        </TouchableOpacity>
      )}
    />
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 14 },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 16, marginBottom: 10, borderWidth: 1, borderColor: C.line },
  title: { fontSize: 18, fontWeight: "700", color: C.ink },
  sub: { fontSize: 14, color: C.sub, marginTop: 2 },
  status: { fontSize: 12, color: C.brand, marginTop: 6, fontWeight: "700", textTransform: "uppercase" },
  empty: { color: C.sub, fontStyle: "italic", padding: 20 },
});

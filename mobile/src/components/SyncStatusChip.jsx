import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet } from "react-native";
import { transportHealth } from "../transport";
import { lastSyncAt } from "../sync";

function ago(ts) {
  if (!ts) return "never";
  const s = Math.max(0, Math.floor((Date.now() - new Date(ts).getTime()) / 1000));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// Live "Connected to Office / Reconnecting…" chip so reps can see whether their work is getting
// through, instead of sync failures piling up silently.
export default function SyncStatusChip({ testid = "sync-status-chip" }) {
  const [health, setHealth] = useState({ online: false });
  const [last, setLast] = useState(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      if (!alive) return;
      setHealth(transportHealth());
      try { setLast(await lastSyncAt()); } catch (e) {}
    };
    tick();
    const id = setInterval(tick, 4000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const online = !!health.online;
  return (
    <View style={[s.chip, online ? s.chipOn : s.chipOff]} testID={testid}>
      <View style={[s.dot, online ? s.dotOn : s.dotOff]} />
      <Text style={[s.text, online ? s.textOn : s.textOff]} testID={`${testid}-label`}>
        {online ? "Connected to Office" : "Reconnecting…"}
      </Text>
      <Text style={s.sub} testID={`${testid}-last`}>· Last synced {ago(last)}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  chip: { flexDirection: "row", alignItems: "center", alignSelf: "flex-start", borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7, borderWidth: 1 },
  chipOn: { backgroundColor: "#ECFDF5", borderColor: "#A7F3D0" },
  chipOff: { backgroundColor: "#FFFBEB", borderColor: "#FDE68A" },
  dot: { width: 8, height: 8, borderRadius: 4, marginRight: 8 },
  dotOn: { backgroundColor: "#10B981" },
  dotOff: { backgroundColor: "#F59E0B" },
  text: { fontSize: 13, fontWeight: "800" },
  textOn: { color: "#047857" },
  textOff: { color: "#B45309" },
  sub: { fontSize: 12, color: "#94A3B8", marginLeft: 6, fontWeight: "600" },
});

import React, { useEffect, useState } from "react";
import { TouchableOpacity, Text, StyleSheet, View } from "react-native";
import { transportHealth, forceReconnect, startTunnelHeartbeat } from "../transport";
import { lastSyncAt, runSync } from "../sync";

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

// Live "Connected to Office / Reconnecting…" chip. A keepalive heartbeat keeps it fresh even when
// idle, and tapping it forces an immediate reconnect + sync.
export default function SyncStatusChip({ testid = "sync-status-chip" }) {
  const [health, setHealth] = useState({ online: false });
  const [last, setLast] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    startTunnelHeartbeat(); // singleton; keeps the tunnel warm + detects drops within seconds
    const tick = async () => {
      if (!alive) return;
      setHealth(transportHealth());
      try { setLast(await lastSyncAt()); } catch (e) {}
    };
    tick();
    const id = setInterval(tick, 4000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const onPress = async () => {
    if (busy) return;
    setBusy(true);
    try { forceReconnect(); await runSync(); } catch (e) {}
    setHealth(transportHealth());
    try { setLast(await lastSyncAt()); } catch (e) {}
    setBusy(false);
  };

  const online = !!health.online;
  const label = busy ? "Syncing…" : online ? "Connected to Office" : "Reconnecting…";
  return (
    <TouchableOpacity onPress={onPress} activeOpacity={0.7} style={[s.chip, online ? s.chipOn : s.chipOff]} testID={testid} accessibilityLabel="Tap to reconnect and sync">
      <View style={[s.dot, online ? s.dotOn : s.dotOff]} />
      <Text style={[s.text, online ? s.textOn : s.textOff]} testID={`${testid}-label`}>{label}</Text>
      <Text style={s.sub} testID={`${testid}-last`}>· Last synced {ago(last)} · tap to sync</Text>
    </TouchableOpacity>
  );
}

const s = StyleSheet.create({
  chip: { flexDirection: "row", alignItems: "center", alignSelf: "flex-start", borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7, borderWidth: 1, flexWrap: "wrap" },
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

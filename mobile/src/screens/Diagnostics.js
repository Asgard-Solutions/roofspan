import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, TouchableOpacity, StyleSheet } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { syncDiagnostics, pendingSummary, runSync } from "../sync";
import { getCache } from "../storage";
import { MAP_DIAG_CACHE_KEY, MAP_LOAD_DIAG_CACHE_KEY } from "../mapDiagnostics";
import { C } from "../theme";

function fmt(ts) {
  if (!ts) return "—";
  try {
    const d = new Date(ts);
    return d.toLocaleString();
  } catch (e) { return String(ts); }
}

function Row({ label, value, testID }) {
  return (
    <View style={s.row} testID={testID}>
      <Text style={s.rowLabel}>{label}</Text>
      <Text style={s.rowValue}>{value}</Text>
    </View>
  );
}

// Support/diagnostics screen. Surfaces the PERSISTED sync diagnostics (survive app kill/restart) so an
// engineer can explain a stuck device. Operational metadata only — never tokens/credentials/PII/photos.
export default function Diagnostics() {
  const [diag, setDiag] = useState({ mutations: [] });
  const [summary, setSummary] = useState({ counts: {} });
  const [mapDiag, setMapDiag] = useState(null);
  const [mapLoad, setMapLoad] = useState(null);

  const load = useCallback(async () => {
    setDiag(syncDiagnostics());
    try { setSummary(await pendingSummary()); } catch (e) { /* offline */ }
    try { setMapDiag(await getCache(MAP_DIAG_CACHE_KEY)); } catch (e) { /* none */ }
    try { setMapLoad(await getCache(MAP_LOAD_DIAG_CACHE_KEY)); } catch (e) { /* none */ }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const refresh = async () => { try { await runSync(); } catch (e) {} await load(); };

  const c = summary.counts || {};
  const mutations = (diag.mutations || []).slice().reverse();   // newest first

  return (
    <ScrollView style={s.wrap} contentContainerStyle={{ padding: 16 }} testID="diagnostics-screen">
      <Text style={s.h1}>Sync Diagnostics</Text>
      <Text style={s.sub}>Operational metadata only — no personal data, tokens, or photos.</Text>

      <Text style={s.section}>Timestamps</Text>
      <View style={s.card}>
        <Row label="Last push attempt" value={fmt(diag.last_push_attempt_at)} testID="diag-last-push-attempt" />
        <Row label="Last successful push" value={fmt(diag.last_successful_push_at)} testID="diag-last-push-ok" />
        <Row label="Last successful pull" value={fmt(diag.last_successful_pull_at)} testID="diag-last-pull-ok" />
        <Row label="Last fully converged" value={fmt(summary.last_fully_converged_at)} testID="diag-last-converged" />
      </View>

      <Text style={s.section}>Queue state</Text>
      <View style={s.card}>
        <Row label="Pending" value={String(c.pending || 0)} testID="diag-count-pending" />
        <Row label="Failed" value={String(c.failed || 0)} testID="diag-count-failed" />
        <Row label="Conflict" value={String(c.conflict || 0)} testID="diag-count-conflict" />
        <Row label="Locked" value={String(c.locked || 0)} testID="diag-count-locked" />
        <Row label="Synced" value={String(c.synced || 0)} testID="diag-count-synced" />
      </View>

      <Text style={s.section}>My Area load</Text>
      <View style={s.card} testID="diag-map-load">
        {mapLoad ? (
          <>
            <Row label="User" value={`${mapLoad.user_email || "—"} (${mapLoad.user_role || "—"})`} testID="diag-load-user" />
            <Row label="Properties status" value={mapLoad.map_properties_status} testID="diag-load-props-status" />
            <Row label="Property count" value={String(mapLoad.property_feature_count)} testID="diag-load-prop-count" />
            <Row label="Cached property count" value={String(mapLoad.cached_property_feature_count)} testID="diag-load-cached-props" />
            <Row label="Canvass status" value={mapLoad.canvass_status} testID="diag-load-canvass-status" />
            <Row label="Section count" value={String(mapLoad.section_count)} testID="diag-load-section-count" />
            <Row label="Area count" value={String(mapLoad.area_count != null ? mapLoad.area_count : "—")} testID="diag-load-area-count" />
            <Row label="Selected area" value={mapLoad.selected_area_id || mapLoad.selected_section_id || "—"} testID="diag-load-selected" />
            <Row label="Native available" value={mapLoad.native_available ? "yes" : "no"} testID="diag-load-native" />
            <Row label="Execution env" value={mapLoad.execution_environment || "—"} testID="diag-load-exec" />
            <Row label="Map mount attempted" value={mapLoad.map_mount_attempted ? "yes" : "no"} testID="diag-load-mount-attempted" />
            <Row label="Map mount succeeded" value={mapLoad.map_mount_succeeded ? "yes" : "no"} testID="diag-load-mount-succeeded" />
            <Row label="Map config" value={mapLoad.map_config_status} testID="diag-load-cfg" />
            <Row label="Map style loaded" value={mapLoad.map_style_loaded ? "yes" : "no"} testID="diag-load-style" />
            <Row label="MapLibre version" value={mapLoad.maplibre_version || "—"} testID="diag-load-mlv" />
            <Row label="Source API" value={mapLoad.source_api || "—"} testID="diag-load-source" />
            <Row label="Prop features -> map" value={String(mapLoad.property_source_feature_count)} testID="diag-load-prop-src" />
            <Row label="Canvass features -> map" value={String(mapLoad.canvass_source_feature_count)} testID="diag-load-canvass-src" />
          </>
        ) : (
          <Text style={s.empty} testID="diag-load-none">Open My Area once to record a load snapshot.</Text>
        )}
      </View>

      <Text style={s.section}>Map renderer</Text>
      <View style={s.card} testID="diag-map-renderer">
        {mapDiag ? (
          <>
            <Row label="Last map failure" value={fmt(mapDiag.at)} testID="diag-map-last-failure" />
            <Row label="MapLibre JS loaded" value={mapDiag.maplibre_js_loaded ? "yes" : "no"} testID="diag-map-js" />
            <Row label="Native module available" value={mapDiag.maplibre_native_available ? "yes" : "no"} testID="diag-map-native" />
            <Row label="Style built" value={mapDiag.map_style_built ? "yes" : "no"} testID="diag-map-style" />
            <Row label="Map config loaded" value={mapDiag.map_config_loaded ? "yes" : "no"} testID="diag-map-cfg" />
            <Row label="Properties loaded" value={mapDiag.properties_loaded ? "yes" : "no"} testID="diag-map-props" />
            <Row label="Canvass loaded" value={mapDiag.canvass_loaded ? "yes" : "no"} testID="diag-map-canvass" />
            <Row label="Base layer" value={mapDiag.active_base_layer || "—"} testID="diag-map-base" />
            <Row label="MapTiler configured" value={mapDiag.maptiler_configured ? "yes" : "no"} testID="diag-map-maptiler" />
            <Row label="Tile ticket present" value={mapDiag.tile_ticket_present ? "yes" : "no"} testID="diag-map-ticket" />
            <Row label="Mount attempted" value={mapDiag.map_mount_attempted ? "yes" : "no"} testID="diag-map-mount-attempted" />
            <Row label="Mount succeeded" value={mapDiag.map_mount_succeeded ? "yes" : "no"} testID="diag-map-mount-succeeded" />
            <Row label="Error" value={mapDiag.error_name ? `${mapDiag.error_name}: ${mapDiag.error_message || ""}` : (mapDiag.error_message || "—")} testID="diag-map-error" />
          </>
        ) : (
          <Text style={s.empty} testID="diag-map-none">No map renderer failures recorded.</Text>
        )}
      </View>

      <TouchableOpacity style={s.btn} onPress={refresh} testID="diag-refresh-button">
        <Text style={s.btnText}>Run sync now & refresh</Text>
      </TouchableOpacity>

      <Text style={s.section}>Recent mutations ({mutations.length})</Text>
      {mutations.length === 0 ? (
        <Text style={s.empty} testID="diag-empty">No recorded mutations yet.</Text>
      ) : mutations.map((m, i) => (
        <View key={`${m.client_id || "m"}-${i}`} style={s.mut} testID={`diag-mutation-${i}`}>
          <View style={s.mutHead}>
            <Text style={[s.state, s[`state_${m.state}`] || s.state_pending]}>{m.state || "—"}</Text>
            <Text style={s.mutKind}>{m.kind || m.path_category || "—"}</Text>
            <Text style={s.mutAt}>{fmt(m.at)}</Text>
          </View>
          <Text style={s.meta}>path: {m.path_category || "—"}   http: {m.http_status != null ? m.http_status : "—"}   relay: {m.relay_error_code || "—"}</Text>
          <Text style={s.meta}>gen: {m.mutation_generation != null ? m.mutation_generation : "—"}   rev: {m.revision_id ? String(m.revision_id).slice(0, 8) : "—"}   token: {m.server_token != null ? String(m.server_token).slice(0, 12) : "—"}</Text>
          <Text style={s.meta}>cache: {m.cache_source || "—"}   recovery: {m.recovery_action || "—"}</Text>
          {m.error ? <Text style={s.err} numberOfLines={2}>err: {m.error}</Text> : null}
        </View>
      ))}
      <View style={{ height: 32 }} />
    </ScrollView>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC" },
  h1: { color: C.ink, fontSize: 22, fontWeight: "800" },
  sub: { color: C.sub, fontSize: 12, marginTop: 4, marginBottom: 8 },
  section: { color: C.brand, fontSize: 13, fontWeight: "800", marginTop: 18, marginBottom: 8, textTransform: "uppercase", letterSpacing: 0.5 },
  card: { backgroundColor: "#fff", borderRadius: 12, paddingHorizontal: 14, paddingVertical: 4, borderWidth: 1, borderColor: C.line },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: C.line },
  rowLabel: { color: C.sub, fontSize: 14 },
  rowValue: { color: C.ink, fontSize: 14, fontWeight: "600" },
  btn: { backgroundColor: C.brand, borderRadius: 10, paddingVertical: 12, alignItems: "center", marginTop: 16 },
  btnText: { color: "#fff", fontWeight: "800", fontSize: 15 },
  empty: { color: C.sub, fontStyle: "italic", paddingVertical: 8 },
  mut: { backgroundColor: "#fff", borderRadius: 10, padding: 12, marginBottom: 8, borderWidth: 1, borderColor: C.line },
  mutHead: { flexDirection: "row", alignItems: "center", marginBottom: 6 },
  state: { fontSize: 11, fontWeight: "800", paddingHorizontal: 8, paddingVertical: 2, borderRadius: 6, overflow: "hidden", color: "#fff" },
  state_pending: { backgroundColor: "#64748B" },
  state_failed: { backgroundColor: C.danger },
  state_conflict: { backgroundColor: C.warn },
  state_locked: { backgroundColor: "#7C3AED" },
  state_synced: { backgroundColor: C.ok },
  mutKind: { color: C.ink, fontSize: 13, fontWeight: "700", marginLeft: 8, flex: 1 },
  mutAt: { color: "#64748B", fontSize: 11 },
  meta: { color: C.sub, fontSize: 12, marginTop: 2, fontVariant: ["tabular-nums"] },
  err: { color: C.danger, fontSize: 12, marginTop: 4 },
});

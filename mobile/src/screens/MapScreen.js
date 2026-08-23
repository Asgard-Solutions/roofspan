import React, { useCallback, useState } from "react";
import { View, Text, FlatList, TouchableOpacity, StyleSheet, Platform, ScrollView } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import Constants from "expo-constants";
import { api } from "../api";
import { putCache, getCache } from "../storage";
import { C } from "../theme";
import { buildMapStyle, safeCenter, safeZoom, isNativeMapAvailable } from "../mapConfig";
import { CACHE_SECTIONS, propsCacheKey, pickDefaultSection, buildSectionPolygonFC } from "../canvass";

let MapLibre = null;
if (Platform.OS !== "web") {
  try { MapLibre = require("@maplibre/maplibre-react-native"); } catch (e) { MapLibre = null; }
}
const NATIVE_MAP_OK = MapLibre && isNativeMapAvailable(Constants.executionEnvironment);

class MapErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { failed: false }; }
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() {}
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

export default function MapScreen({ navigation }) {
  const [sections, setSections] = useState([]);
  const [selId, setSelId] = useState(null);
  const [features, setFeatures] = useState([]);
  const [cfg, setCfg] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [offlineNoCache, setOfflineNoCache] = useState(false);

  const loadSectionProps = useCallback(async (id) => {
    if (!id) { setFeatures([]); return; }
    try {
      const g = await api.get(`/mobile/canvass-sections/${id}/properties`);
      const feats = g.data.features || [];
      setFeatures(feats);
      await putCache(propsCacheKey(id), feats);
    } catch (e) {
      setFeatures((await getCache(propsCacheKey(id))) || []);
    }
  }, []);

  const load = useCallback(async () => {
    let secs = [];
    let online = true;
    try {
      const [s, m] = await Promise.all([api.get("/mobile/canvass-sections"), api.get("/map-config")]);
      secs = s.data.sections || [];
      setCfg(m.data);
      await putCache(CACHE_SECTIONS, secs);
      await putCache("mapcfg", m.data);
    } catch (e) {
      online = false;
      secs = (await getCache(CACHE_SECTIONS)) || [];
      setCfg((await getCache("mapcfg")) || null);
    }
    setSections(secs);
    setOfflineNoCache(!online && secs.length === 0);
    const sel = pickDefaultSection(secs);
    setSelId(sel);
    await loadSectionProps(sel);
    setLoaded(true);
  }, [loadSectionProps]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const selectSection = async (id) => { setSelId(id); await loadSectionProps(id); };
  const openProp = (pid) => navigation.getParent()?.navigate("LeadsTab", { screen: "LeadDetail", params: { id: pid } });

  const selected = sections.find((s) => s.id === selId) || null;
  const mapStyle = NATIVE_MAP_OK ? buildMapStyle(cfg) : null;

  const header = (
    <View style={s.hero} testID="my-area-header">
      <Text style={s.heroKicker}>MY AREA</Text>
      <Text style={s.heroTitle} testID="my-area-title">{selected ? selected.name : "No canvass area assigned"}</Text>
      {selected ? <Text style={s.heroSub}>{features.length} properties</Text> : null}
      {sections.length > 1 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 8 }}>
          {sections.map((sec) => (
            <TouchableOpacity key={sec.id} onPress={() => selectSection(sec.id)} testID={`section-chip-${sec.id}`}
              style={[s.chip, sec.id === selId && { backgroundColor: sec.color || C.brand, borderColor: sec.color || C.brand }]}>
              <Text style={[s.chipText, sec.id === selId && { color: "#fff" }]}>{sec.name}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      )}
    </View>
  );

  // Empty / offline states
  if (loaded && sections.length === 0) {
    return (
      <View style={s.center} testID="no-area-state">
        {offlineNoCache ? (
          <>
            <Text style={s.emptyTitle}>No saved map data offline</Text>
            <Text style={s.emptyBody}>No saved map data is available offline yet. Connect to RoofSpan Office to sync your assigned area.</Text>
          </>
        ) : (
          <>
            <Text style={s.emptyTitle}>No canvass area assigned</Text>
            <Text style={s.emptyBody}>Your office has not assigned you a canvass section yet.</Text>
          </>
        )}
      </View>
    );
  }

  const renderFallback = (reason) => (
    <View style={{ flex: 1, backgroundColor: "#F8FAFC" }}>
      {header}
      <FlatList
        style={{ flex: 1, paddingHorizontal: 14 }}
        data={features}
        keyExtractor={(f) => f.properties.id}
        ListHeaderComponent={<Text style={s.note}>{reason}</Text>}
        ListEmptyComponent={<Text style={s.empty}>No properties in this section yet.</Text>}
        renderItem={({ item }) => {
          const p = item.properties;
          return (
            <TouchableOpacity style={[s.card, p.do_not_knock && s.dnkCard]} onPress={() => openProp(p.id)} testID={`map-prop-${p.id}`}>
              <Text style={[s.addr, p.do_not_knock && { color: "#fff" }]}>{p.address}</Text>
              {p.do_not_knock ? <Text style={s.dnk}>⛔ DO NOT KNOCK</Text> : <Text style={s.type}>{p.property_type || "property"}</Text>}
            </TouchableOpacity>
          );
        }}
      />
    </View>
  );

  if (NATIVE_MAP_OK && mapStyle) {
    const { MapView, Camera, ShapeSource, CircleLayer, FillLayer, LineLayer } = MapLibre;
    const fc = { type: "FeatureCollection", features };
    const secColor = selected?.color || C.brand;
    const polyFc = buildSectionPolygonFC(selected);
    const center = selected?.geometry?.coordinates?.[0]?.[0] || safeCenter(cfg);
    const fallback = renderFallback("Map unavailable — showing list view.");
    return (
      <MapErrorBoundary fallback={fallback}>
        <View style={{ flex: 1 }} testID="map-container">
          {header}
          <MapView style={{ flex: 1 }} mapStyle={mapStyle} testID="map-view">
            <Camera zoomLevel={safeZoom(cfg)} centerCoordinate={center} />
            <ShapeSource id="myarea" shape={polyFc}>
              <FillLayer id="myarea-fill" style={{ fillColor: secColor, fillOpacity: 0.15 }} />
              <LineLayer id="myarea-line" style={{ lineColor: secColor, lineWidth: 2.5 }} />
            </ShapeSource>
            <ShapeSource id="props" shape={fc} onPress={(e) => { const f = e.features && e.features[0]; if (f) openProp(f.properties.id); }}>
              <CircleLayer id="pins" style={{ circleRadius: 7, circleColor: ["case", ["get", "do_not_knock"], C.dnk, C.brand], circleStrokeWidth: 2, circleStrokeColor: "#fff" }} />
            </ShapeSource>
          </MapView>
        </View>
      </MapErrorBoundary>
    );
  }

  const inExpoGo = Constants.executionEnvironment === "storeClient";
  const reason = !MapLibre
    ? "Map list view (native MapLibre renders on device)."
    : inExpoGo
      ? "Map requires a development build (Expo Go can't load native maps) — showing list view."
      : loaded && !mapStyle
        ? "Map unavailable — showing list view."
        : "Loading map…";
  return renderFallback(reason);
}

const s = StyleSheet.create({
  hero: { backgroundColor: "#fff", paddingHorizontal: 16, paddingTop: 14, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: C.line },
  heroKicker: { fontSize: 11, fontWeight: "800", letterSpacing: 1, color: C.sub },
  heroTitle: { fontSize: 20, fontWeight: "900", color: C.ink, marginTop: 2 },
  heroSub: { fontSize: 13, color: C.sub, marginTop: 2 },
  chip: { borderWidth: 1, borderColor: C.line, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6, marginRight: 8, backgroundColor: "#fff" },
  chipText: { fontSize: 12, fontWeight: "700", color: C.ink },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 28, backgroundColor: "#F8FAFC" },
  emptyTitle: { fontSize: 17, fontWeight: "800", color: C.ink, marginBottom: 6, textAlign: "center" },
  emptyBody: { fontSize: 14, color: C.sub, textAlign: "center", lineHeight: 20 },
  note: { color: C.sub, fontStyle: "italic", marginVertical: 10 },
  empty: { color: C.sub, fontStyle: "italic", paddingVertical: 20 },
  card: { backgroundColor: "#fff", borderRadius: 12, padding: 14, marginBottom: 8, borderWidth: 1, borderColor: C.line },
  dnkCard: { backgroundColor: C.dnk, borderColor: C.dnk },
  addr: { fontSize: 15, fontWeight: "700", color: C.ink },
  type: { fontSize: 12, color: C.sub, marginTop: 2 },
  dnk: { color: "#fff", fontWeight: "900", marginTop: 4 },
});

import React, { useCallback, useState } from "react";
import { View, Text, FlatList, TouchableOpacity, StyleSheet, Platform } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import Constants from "expo-constants";
import { api } from "../api";
import { putCache, getCache } from "../storage";
import { C } from "../theme";
import { buildMapStyle, safeCenter, safeZoom, isNativeMapAvailable } from "../mapConfig";

// Native MapLibre is loaded lazily so the web target (and Node) don't crash on the native module.
let MapLibre = null;
if (Platform.OS !== "web") {
  try { MapLibre = require("@maplibre/maplibre-react-native"); } catch (e) { MapLibre = null; }
}

// Expo Go cannot load MapLibre's native module (only dev/standalone builds can). Detect it so the
// Map tab degrades to the list fallback instead of erroring with "View config not found for MLRNCamera".
const NATIVE_MAP_OK = MapLibre && isNativeMapAvailable(Constants.executionEnvironment);

// Catch any JS-level render error from the native map and fall back gracefully (never crash the app).
class MapErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { failed: false }; }
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(err) { /* swallow: map is non-critical, fallback UI is shown */ }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

export default function MapScreen({ navigation }) {
  const [features, setFeatures] = useState([]);
  const [cfg, setCfg] = useState(null);
  const [cfgLoaded, setCfgLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const [g, m] = await Promise.all([api.get("/properties/geojson"), api.get("/map-config")]);
      setFeatures(g.data.features || []);
      setCfg(m.data);
      await putCache("geojson", g.data.features || []);
      await putCache("mapcfg", m.data);
    } catch (e) {
      // Offline / server error: fall back to last cached values (may be null → list view).
      setFeatures((await getCache("geojson")) || []);
      setCfg((await getCache("mapcfg")) || null);
    } finally {
      setCfgLoaded(true);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const openProp = (pid) => navigation.getParent()?.navigate("LeadsTab", { screen: "LeadDetail", params: { id: pid } });

  // Build a validated style JSON from server config. Null => config missing/invalid/malformed => fallback.
  const mapStyle = NATIVE_MAP_OK ? buildMapStyle(cfg) : null;

  // Fallback list view (web/dev, offline, or invalid/unavailable map config). DNK is unmistakable.
  const renderFallback = (reason) => (
    <FlatList
      style={s.wrap}
      data={features}
      keyExtractor={(f) => f.properties.id}
      ListHeaderComponent={<Text style={s.note}>{reason}</Text>}
      ListEmptyComponent={<Text style={s.empty}>No properties to show yet.</Text>}
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
  );

  // Native map (device builds) — only when we have a VALID style JSON. Server-provided OSM raster; no provider secret on device.
  if (NATIVE_MAP_OK && mapStyle) {
    const { MapView, Camera, ShapeSource, CircleLayer } = MapLibre;
    const fc = { type: "FeatureCollection", features };
    const fallback = renderFallback("Map unavailable — showing list view.");
    return (
      <MapErrorBoundary fallback={fallback}>
        <View style={{ flex: 1 }} testID="map-container">
          <MapView style={{ flex: 1 }} mapStyle={mapStyle} testID="map-view">
            <Camera zoomLevel={safeZoom(cfg)} centerCoordinate={safeCenter(cfg)} />
            <ShapeSource id="props" shape={fc} onPress={(e) => { const f = e.features && e.features[0]; if (f) openProp(f.properties.id); }}>
              <CircleLayer id="pins" style={{ circleRadius: 7, circleColor: ["case", ["get", "do_not_knock"], C.dnk, C.brand], circleStrokeWidth: 2, circleStrokeColor: "#fff" }} />
            </ShapeSource>
          </MapView>
        </View>
      </MapErrorBoundary>
    );
  }

  // No valid map: explain briefly (only once config has actually loaded) and keep the app usable.
  const inExpoGo = Constants.executionEnvironment === "storeClient";
  const reason = !MapLibre
    ? "Map list view (native MapLibre renders on device)."
    : inExpoGo
      ? "Map requires a development build (Expo Go can't load native maps) — showing list view."
      : cfgLoaded && !mapStyle
        ? "Map unavailable — showing list view."
        : "Loading map…";
  return renderFallback(reason);
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 14 },
  note: { color: C.sub, fontStyle: "italic", marginBottom: 10 },
  empty: { color: C.sub, fontStyle: "italic", paddingVertical: 20 },
  card: { backgroundColor: "#fff", borderRadius: 12, padding: 14, marginBottom: 8, borderWidth: 1, borderColor: C.line },
  dnkCard: { backgroundColor: C.dnk, borderColor: C.dnk },
  addr: { fontSize: 15, fontWeight: "700", color: C.ink },
  type: { fontSize: 12, color: C.sub, marginTop: 2 },
  dnk: { color: "#fff", fontWeight: "900", marginTop: 4 },
});

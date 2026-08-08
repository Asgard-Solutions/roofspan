import React, { useCallback, useEffect, useState } from "react";
import { View, Text, FlatList, TouchableOpacity, StyleSheet, Platform } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { api } from "../api";
import { putCache, getCache } from "../storage";
import { C } from "../theme";

// Native MapLibre is loaded lazily so the web target (and Node) don't crash on the native module.
let MapLibre = null;
if (Platform.OS !== "web") {
  try { MapLibre = require("@maplibre/maplibre-react-native"); } catch (e) { MapLibre = null; }
}

export default function MapScreen({ navigation }) {
  const [features, setFeatures] = useState([]);
  const [cfg, setCfg] = useState(null);

  const load = useCallback(async () => {
    try {
      const [g, m] = await Promise.all([api.get("/properties/geojson"), api.get("/map-config")]);
      setFeatures(g.data.features || []);
      setCfg(m.data);
      await putCache("geojson", g.data.features || []);
      await putCache("mapcfg", m.data);
    } catch (e) {
      setFeatures((await getCache("geojson")) || []);
      setCfg((await getCache("mapcfg")) || null);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const openProp = (pid) => navigation.getParent()?.navigate("LeadsTab", { screen: "LeadDetail", params: { id: pid } });

  // Native map (device builds). Server-provided OSM raster style; no provider secret on device.
  if (MapLibre && cfg) {
    const { MapView, Camera, RasterSource, RasterLayer, ShapeSource, CircleLayer } = MapLibre;
    const fc = { type: "FeatureCollection", features };
    return (
      <View style={{ flex: 1 }}>
        <MapView style={{ flex: 1 }} testID="map-view">
          <Camera zoomLevel={cfg.default_zoom || 11} centerCoordinate={cfg.default_center || [-97.74, 30.27]} />
          <RasterSource id="osm" tileUrlTemplates={[cfg.osm_tile_url]} tileSize={256}>
            <RasterLayer id="osm-layer" />
          </RasterSource>
          <ShapeSource id="props" shape={fc} onPress={(e) => { const f = e.features && e.features[0]; if (f) openProp(f.properties.id); }}>
            <CircleLayer id="pins" style={{ circleRadius: 7, circleColor: ["case", ["get", "do_not_knock"], C.dnk, C.brand], circleStrokeWidth: 2, circleStrokeColor: "#fff" }} />
          </ShapeSource>
        </MapView>
      </View>
    );
  }

  // Fallback list view (web/dev). DNK is unmistakable.
  return (
    <FlatList
      style={s.wrap}
      data={features}
      keyExtractor={(f) => f.properties.id}
      ListHeaderComponent={<Text style={s.note}>Map list view (native MapLibre renders on device).</Text>}
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
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 14 },
  note: { color: C.sub, fontStyle: "italic", marginBottom: 10 },
  card: { backgroundColor: "#fff", borderRadius: 12, padding: 14, marginBottom: 8, borderWidth: 1, borderColor: C.line },
  dnkCard: { backgroundColor: C.dnk, borderColor: C.dnk },
  addr: { fontSize: 15, fontWeight: "700", color: C.ink },
  type: { fontSize: 12, color: C.sub, marginTop: 2 },
  dnk: { color: "#fff", fontWeight: "900", marginTop: 4 },
});

import React, { useCallback, useMemo, useState } from "react";
import { View, Text, FlatList, TouchableOpacity, StyleSheet, Platform, ScrollView } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import Constants from "expo-constants";
import { api } from "../api";
import { getToken } from "../auth";
import { usePairing } from "../pairingContext";
import { putCache, getCache } from "../storage";
import { C, PIN } from "../theme";
import { mintTileTicket, tileTemplate, TILE_TICKET_HEADER } from "../tiles";
import { downloadSectionArea, sectionBounds } from "../offlineTiles";
import { buildMapStyle, safeCenter, safeZoom, isNativeMapAvailable } from "../mapConfig";
import { CACHE_SECTIONS, propsCacheKey, pickDefaultSection, buildSectionPolygonFC } from "../canvass";

let MapLibre = null;
if (Platform.OS !== "web") {
  try { MapLibre = require("@maplibre/maplibre-react-native"); } catch (e) { MapLibre = null; }
}
const NATIVE_MAP_OK = MapLibre && isNativeMapAvailable(Constants.executionEnvironment);

// When satellite is selected we must NOT keep the opaque OSM base underneath (that's why satellite
// looked like it "wasn't rendering"). Office hides its OSM layer for satellite; on native we swap to a
// background-only style so the satellite raster child IS the visible base — matching Office.
const SATELLITE_BG_STYLE = { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#0b1b2b" } }] };

// Grow MapLibre's ambient tile cache once so recently viewed satellite/building tiles remain
// available when a rep loses signal in the field. Best-effort; never blocks the map.
let _ambientCacheReady = false;
function ensureAmbientCache() {
  if (_ambientCacheReady || !MapLibre || !MapLibre.offlineManager) return;
  _ambientCacheReady = true;
  try { MapLibre.offlineManager.setMaximumAmbientCacheSize(120 * 1024 * 1024); } catch (e) { /* noop */ }
}

// Data-driven pin color — MUST mirror the RoofSpan Office legend.
const PIN_COLOR = [
  "case",
  ["to-boolean", ["get", "do_not_knock"]], PIN.dnk,
  ["==", ["get", "owner_occupied"], true], PIN.owned,
  ["==", ["get", "owner_occupied"], false], PIN.rented,
  PIN.unknown,
];

const LEGEND = [
  { key: "owned", color: PIN.owned, label: "Owned" },
  { key: "rented", color: PIN.rented, label: "Rented" },
  { key: "unknown", color: PIN.unknown, label: "Unknown" },
  { key: "dnk", color: PIN.dnk, label: "Do Not Knock" },
];

// Door-knocking progress colors + legend (second pin coloring mode).
const PROG = {
  knocked_today: "#16A34A", // green — visited today
  callback: "#2563EB",      // blue — needs a return visit
  not_home: "#F59E0B",      // amber — no answer
  contacted: "#0D9488",     // teal — spoken to previously
  none: "#94A3B8",          // slate — not visited yet
  dnk: PIN.dnk,             // red — do not knock
};
const PROGRESS_LEGEND = [
  { key: "knocked_today", color: PROG.knocked_today, label: "Knocked today" },
  { key: "callback", color: PROG.callback, label: "Callback" },
  { key: "not_home", color: PROG.not_home, label: "Not home" },
  { key: "contacted", color: PROG.contacted, label: "Contacted" },
  { key: "none", color: PROG.none, label: "Not visited" },
  { key: "dnk", color: PROG.dnk, label: "Do Not Knock" },
];
const PROGRESS_COLOR = [
  "match", ["get", "progress"],
  "dnk", PROG.dnk,
  "knocked_today", PROG.knocked_today,
  "callback", PROG.callback,
  "not_home", PROG.not_home,
  "contacted", PROG.contacted,
  PROG.none,
];

function deriveProgress(p) {
  if (p.do_not_knock) return "dnk";
  const lv = p.last_visited_at ? new Date(p.last_visited_at) : null;
  if (lv && !isNaN(lv.getTime()) && lv.toDateString() === new Date().toDateString()) return "knocked_today";
  const o = p.last_outcome;
  if (o === "callback" || o === "appointment") return "callback";
  if (o === "no_answer") return "not_home";
  if (o) return "contacted";
  return "none";
}

const FILTERS = [
  { key: "all", label: "All" },
  { key: "owned", label: "Owned" },
  { key: "rented", label: "Rented" },
  { key: "unknown", label: "Unknown" },
];

function matchesFilter(p, filter) {
  if (filter === "all") return true;
  if (filter === "owned") return p.owner_occupied === true;
  if (filter === "rented") return p.owner_occupied === false;
  if (filter === "unknown") return p.owner_occupied === null || p.owner_occupied === undefined;
  return true;
}

function pinColorFor(p) {
  return p.do_not_knock ? PIN.dnk : p.owner_occupied === true ? PIN.owned : p.owner_occupied === false ? PIN.rented : PIN.unknown;
}

class MapErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { failed: false }; }
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() {}
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

export default function MapScreen({ navigation }) {
  const pairingCtx = usePairing();
  const pairing = pairingCtx ? pairingCtx.pairing : null;

  const [sections, setSections] = useState([]);
  const [selId, setSelId] = useState(null);
  const [features, setFeatures] = useState([]);
  const [cfg, setCfg] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [offlineNoCache, setOfflineNoCache] = useState(false);
  const [base, setBase] = useState("street"); // street | satellite | buildings
  const [filter, setFilter] = useState("all");
  const [colorMode, setColorMode] = useState("occupancy"); // occupancy | progress
  const [dl, setDl] = useState({ status: "idle", pct: 0 }); // offline download
  const [ticketReady, setTicketReady] = useState(false);

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
    let mapCfg = null;
    try {
      const [s, m] = await Promise.all([api.get("/mobile/canvass-sections"), api.get("/map-config")]);
      secs = s.data.sections || [];
      mapCfg = m.data;
      await putCache(CACHE_SECTIONS, secs);
      await putCache("mapcfg", m.data);
    } catch (e) {
      online = false;
      secs = (await getCache(CACHE_SECTIONS)) || [];
      mapCfg = (await getCache("mapcfg")) || null;
    }
    setCfg(mapCfg);
    setSections(secs);
    setOfflineNoCache(!online && secs.length === 0);
    const sel = pickDefaultSection(secs);
    setSelId(sel);
    await loadSectionProps(sel);
    setLoaded(true);

    // Best-effort tile authorization: mint a short-lived ticket and register it as a global header
    // so tile URLs stay secret-free and stable. If offline, cached tiles still render from the
    // ambient cache; only new tiles are unavailable until reconnected.
    if (NATIVE_MAP_OK && mapCfg && mapCfg.maptiler_configured && pairing) {
      ensureAmbientCache();
      try {
        const token = await getToken();
        const ticket = await mintTileTicket(pairing, token);
        if (ticket && MapLibre && MapLibre.addCustomHeader) {
          MapLibre.addCustomHeader(TILE_TICKET_HEADER, ticket);
          setTicketReady(true);
        }
      } catch (e) { /* keep any previously registered ticket */ }
    }
  }, [loadSectionProps, pairing]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const selectSection = async (id) => { setSelId(id); await loadSectionProps(id); };
  const openProp = (pid) => navigation.navigate("Property", { id: pid });

  const selected = sections.find((s) => s.id === selId) || null;
  const mapStyle = NATIVE_MAP_OK ? buildMapStyle(cfg) : null;

  const visibleFeatures = useMemo(
    () => features
      .map((f) => ({ ...f, properties: { ...f.properties, progress: deriveProgress(f.properties || {}) } }))
      .filter((f) => matchesFilter(f.properties || {}, filter)),
    [features, filter]
  );

  // Imagery is offered when the Office has MapTiler configured. Tiles use a stable URL + ticket header;
  // when offline, previously viewed tiles are served from the ambient cache.
  const satelliteUrl = tileTemplate(pairing, "satellite");
  const buildingsUrl = tileTemplate(pairing, "buildings");
  const imageryReady = !!(NATIVE_MAP_OK && cfg && cfg.maptiler_configured && satelliteUrl && buildingsUrl);
  const activeBase = imageryReady ? base : "street";

  const startDownload = useCallback(async () => {
    if (!selected || !satelliteUrl || !cfg || !cfg.osm_tile_url || !MapLibre) return;
    setDl({ status: "downloading", pct: 0 });
    try {
      await downloadSectionArea({
        MapLibre, section: selected, osmTileUrl: cfg.osm_tile_url, satelliteUrl,
        onProgress: (pct) => setDl({ status: "downloading", pct }),
      });
      setDl({ status: "done", pct: 100 });
    } catch (e) {
      setDl({ status: "error", pct: 0 });
    }
  }, [selected, satelliteUrl, cfg]);

  const colorModeSwitcher = (
    <View style={s.switcher} testID="pin-color-mode">
      {[["occupancy", "Occupancy"], ["progress", "Progress"]].map(([v, label]) => (
        <TouchableOpacity key={v} onPress={() => setColorMode(v)} style={[s.segBtn, colorMode === v && s.segBtnActive]} testID={`colormode-${v}-button`}>
          <Text style={[s.segText, colorMode === v && s.segTextActive]}>{label}</Text>
        </TouchableOpacity>
      ))}
    </View>
  );

  const canPrefetch = imageryReady && selected && !!sectionBounds(selected);
  const prefetchButton = canPrefetch ? (
    <TouchableOpacity onPress={startDownload} disabled={dl.status === "downloading"} style={s.dlBtn} testID="download-area-button">
      <Text style={s.dlBtnText}>
        {dl.status === "downloading" ? `Downloading… ${dl.pct}%`
          : dl.status === "done" ? "Area saved for offline ✓"
          : dl.status === "error" ? "Download failed — tap to retry"
          : "Download area for offline"}
      </Text>
    </TouchableOpacity>
  ) : null;

  const baseSwitcher = imageryReady ? (
    <View style={s.switcher} testID="basemap-switcher">
      {[["street", "Street"], ["satellite", "Satellite"], ["buildings", "Buildings"]].map(([v, label]) => (
        <TouchableOpacity key={v} onPress={() => setBase(v)} style={[s.segBtn, activeBase === v && s.segBtnActive]} testID={`basemap-${v}-button`}>
          <Text style={[s.segText, activeBase === v && s.segTextActive]}>{label}</Text>
        </TouchableOpacity>
      ))}
    </View>
  ) : null;

  const filterChips = (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 10 }} testID="pin-filters">
      {FILTERS.map((f) => {
        const dot = f.key === "all" ? null : f.key === "owned" ? PIN.owned : f.key === "rented" ? PIN.rented : PIN.unknown;
        return (
          <TouchableOpacity key={f.key} onPress={() => setFilter(f.key)} testID={`filter-${f.key}`}
            style={[s.filterChip, filter === f.key && s.filterChipActive]}>
            {dot ? <View style={[s.filterDot, { backgroundColor: dot }]} /> : null}
            <Text style={[s.filterText, filter === f.key && s.filterTextActive]}>{f.label}</Text>
          </TouchableOpacity>
        );
      })}
    </ScrollView>
  );

  const header = (
    <View style={s.hero} testID="my-area-header">
      <Text style={s.heroKicker}>MY AREA</Text>
      <Text style={s.heroTitle} testID="my-area-title">{selected ? selected.name : "No canvass area assigned"}</Text>
      {selected ? <Text style={s.heroSub}>{visibleFeatures.length}{filter !== "all" ? ` of ${features.length}` : ""} properties</Text> : null}
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
      {baseSwitcher}
      {imageryReady ? colorModeSwitcher : null}
      {filterChips}
      {prefetchButton}
    </View>
  );

  const legend = (
    <View style={s.legend} testID="map-legend" pointerEvents="none">
      <Text style={s.legendTitle}>{colorMode === "progress" ? "Progress" : "Pins"}</Text>
      {(colorMode === "progress" ? PROGRESS_LEGEND : LEGEND).map((l) => (
        <View key={l.key} style={s.legendRow} testID={`legend-${l.key}`}>
          <View style={[s.legendDot, { backgroundColor: l.color }]} />
          <Text style={s.legendLabel}>{l.label}</Text>
        </View>
      ))}
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
        data={visibleFeatures}
        keyExtractor={(f) => f.properties.id}
        ListHeaderComponent={<Text style={s.note}>{reason}</Text>}
        ListEmptyComponent={<Text style={s.empty}>No properties match this filter.</Text>}
        renderItem={({ item }) => {
          const p = item.properties;
          return (
            <TouchableOpacity style={[s.card, p.do_not_knock && s.dnkCard]} onPress={() => openProp(p.id)} testID={`map-prop-${p.id}`}>
              <View style={s.cardRow}>
                <View style={[s.cardDot, { backgroundColor: pinColorFor(p) }]} />
                <Text style={[s.addr, p.do_not_knock && { color: "#fff" }]}>{p.address}</Text>
              </View>
              {p.do_not_knock ? <Text style={s.dnk}>DO NOT KNOCK</Text> : <Text style={s.type}>{p.property_type || "property"}</Text>}
            </TouchableOpacity>
          );
        }}
      />
    </View>
  );

  if (NATIVE_MAP_OK && mapStyle) {
    const { MapView, Camera, ShapeSource, CircleLayer, FillLayer, LineLayer, RasterSource, RasterLayer, VectorSource } = MapLibre;
    const fc = { type: "FeatureCollection", features: visibleFeatures };
    const secColor = selected?.color || C.brand;
    const polyFc = buildSectionPolygonFC(selected);
    const center = selected?.geometry?.coordinates?.[0]?.[0] || safeCenter(cfg);
    const fallback = renderFallback("Map unavailable — showing list view.");
    return (
      <MapErrorBoundary fallback={fallback}>
        <View style={{ flex: 1 }} testID="map-container">
          {header}
          <View style={{ flex: 1 }}>
            <MapView style={{ flex: 1 }} mapStyle={activeBase === "satellite" ? SATELLITE_BG_STYLE : mapStyle} testID="map-view">
              <Camera zoomLevel={safeZoom(cfg)} centerCoordinate={center} />

              {activeBase === "satellite" && RasterSource && (
                <RasterSource id="rs-satellite" tileUrlTemplates={[satelliteUrl]} tileSize={512}>
                  <RasterLayer id="rs-satellite-layer" style={{}} />
                </RasterSource>
              )}

              {activeBase === "buildings" && VectorSource && (
                <VectorSource id="rs-buildings" tileUrlTemplates={[buildingsUrl]} minZoomLevel={14} maxZoomLevel={20}>
                  <FillLayer id="rs-buildings-fill" sourceLayerID="building" minZoomLevel={14}
                    style={{ fillColor: ["case", ["==", ["get", "class"], "residential"], "#F97316", "#64748B"], fillOpacity: 0.35 }} />
                  <LineLayer id="rs-buildings-line" sourceLayerID="building" minZoomLevel={14}
                    style={{ lineColor: ["case", ["==", ["get", "class"], "residential"], "#C2410C", "#475569"], lineWidth: 1.25, lineOpacity: 0.9 }} />
                </VectorSource>
              )}

              <ShapeSource id="myarea" shape={polyFc}>
                <FillLayer id="myarea-fill" style={{ fillColor: secColor, fillOpacity: 0.15 }} />
                <LineLayer id="myarea-line" style={{ lineColor: secColor, lineWidth: 2.5 }} />
              </ShapeSource>
              <ShapeSource id="props" shape={fc} onPress={(e) => { const f = e.features && e.features[0]; if (f) openProp(f.properties.id); }}>
                <CircleLayer id="pins" style={{ circleRadius: 7, circleColor: colorMode === "progress" ? PROGRESS_COLOR : PIN_COLOR, circleStrokeWidth: 2, circleStrokeColor: "#fff" }} />
              </ShapeSource>
            </MapView>
            {legend}
          </View>
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
  switcher: { flexDirection: "row", backgroundColor: "#F1F5F9", borderRadius: 10, padding: 3, marginTop: 10 },
  segBtn: { flex: 1, paddingVertical: 8, borderRadius: 8, alignItems: "center" },
  segBtnActive: { backgroundColor: "#fff", shadowColor: "#000", shadowOpacity: 0.12, shadowRadius: 3, shadowOffset: { width: 0, height: 1 }, elevation: 2 },
  segText: { fontSize: 13, fontWeight: "700", color: C.sub },
  segTextActive: { color: C.ink },
  filterChip: { flexDirection: "row", alignItems: "center", borderWidth: 1, borderColor: C.line, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6, marginRight: 8, backgroundColor: "#fff" },
  filterChipActive: { backgroundColor: C.ink, borderColor: C.ink },
  filterDot: { width: 9, height: 9, borderRadius: 5, marginRight: 6 },
  filterText: { fontSize: 12, fontWeight: "700", color: C.sub },
  filterTextActive: { color: "#fff" },
  dlBtn: { marginTop: 10, backgroundColor: C.brand, borderRadius: 10, paddingVertical: 11, alignItems: "center" },
  dlBtnText: { color: "#fff", fontSize: 13, fontWeight: "800" },
  legend: { position: "absolute", left: 12, bottom: 12, backgroundColor: "rgba(255,255,255,0.95)", borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10, borderWidth: 1, borderColor: C.line, shadowColor: "#000", shadowOpacity: 0.12, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 3 },
  legendTitle: { fontSize: 10, fontWeight: "800", letterSpacing: 0.8, color: C.sub, marginBottom: 6, textTransform: "uppercase" },
  legendRow: { flexDirection: "row", alignItems: "center", marginBottom: 4 },
  legendDot: { width: 12, height: 12, borderRadius: 6, marginRight: 8, borderWidth: 1.5, borderColor: "#fff" },
  legendLabel: { fontSize: 12, fontWeight: "600", color: C.ink },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 28, backgroundColor: "#F8FAFC" },
  emptyTitle: { fontSize: 17, fontWeight: "800", color: C.ink, marginBottom: 6, textAlign: "center" },
  emptyBody: { fontSize: 14, color: C.sub, textAlign: "center", lineHeight: 20 },
  note: { color: C.sub, fontStyle: "italic", marginVertical: 10 },
  empty: { color: C.sub, fontStyle: "italic", paddingVertical: 20 },
  card: { backgroundColor: "#fff", borderRadius: 12, padding: 14, marginBottom: 8, borderWidth: 1, borderColor: C.line },
  cardRow: { flexDirection: "row", alignItems: "center" },
  cardDot: { width: 12, height: 12, borderRadius: 6, marginRight: 10, borderWidth: 1.5, borderColor: "#fff" },
  dnkCard: { backgroundColor: C.dnk, borderColor: C.dnk },
  addr: { fontSize: 15, fontWeight: "700", color: C.ink, flex: 1 },
  type: { fontSize: 12, color: C.sub, marginTop: 4, marginLeft: 22 },
  dnk: { color: "#fff", fontWeight: "900", marginTop: 4, marginLeft: 22 },
});

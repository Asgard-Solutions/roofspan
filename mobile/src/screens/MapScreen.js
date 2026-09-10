import React, { useCallback, useMemo, useState, useEffect } from "react";
import { View, Text, TouchableOpacity, StyleSheet, Platform, ScrollView } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import Constants from "expo-constants";
import { api } from "../api";
import { getToken, useAuth } from "../auth";
import { usePairing } from "../pairingContext";
import { putCache, getCache } from "../storage";
import { C, PIN } from "../theme";
import { mintTileTicket, tileTemplate, TILE_TICKET_HEADER } from "../tiles";
import { downloadSectionArea, sectionBounds } from "../offlineTiles";
import { buildMapStyle, safeCenter, safeZoom, isNativeMapAvailable } from "../mapConfig";
import { CACHE_MAP_PROPS, CACHE_MAP_CFG, buildAllSectionsFC } from "../canvass";
import { normalizeAreas, pickDefaultArea, findArea, boundsToCamera, filterFeaturesForArea, boundsFromFeatures } from "../mapAreas";
import { buildMapDiagnostic, buildMapLoadDiagnostic, MAP_DIAG_CACHE_KEY, MAP_LOAD_DIAG_CACHE_KEY } from "../mapDiagnostics";

const CACHE_AREAS = "map_areas_full"; // last good authorized area list (selector + polygons)
const REQ_TIMEOUT_MS = 15000; // finite timeout so a hung request can NEVER strand the map

let MapLibre = null;
if (Platform.OS !== "web") {
  try { MapLibre = require("@maplibre/maplibre-react-native"); } catch (e) { MapLibre = null; }
}
const NATIVE_MAP_OK = MapLibre && isNativeMapAvailable(Constants.executionEnvironment);

// Background-only style so the native MapView ALWAYS mounts even when /map-config is slow/failed —
// the base OSM raster (from config) and satellite raster (from ticket) attach as children when ready.
const BASE_FALLBACK_STYLE = { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#0b1b2b" } }] };
const SATELLITE_BG_STYLE = BASE_FALLBACK_STYLE;

let _ambientCacheReady = false;
function ensureAmbientCache() {
  if (_ambientCacheReady || !MapLibre || !MapLibre.offlineManager) return;
  _ambientCacheReady = true;
  try { MapLibre.offlineManager.setMaximumAmbientCacheSize(120 * 1024 * 1024); } catch (e) { /* noop */ }
}

// Finite-timeout wrapper: a request that never settles must not block the screen forever.
function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("request_timeout")), ms);
    promise.then((v) => { clearTimeout(t); resolve(v); }, (e) => { clearTimeout(t); reject(e); });
  });
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
const PROG = {
  knocked_today: "#16A34A", callback: "#2563EB", not_home: "#F59E0B", contacted: "#0D9488", none: "#94A3B8", dnk: PIN.dnk,
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
  "dnk", PROG.dnk, "knocked_today", PROG.knocked_today, "callback", PROG.callback,
  "not_home", PROG.not_home, "contacted", PROG.contacted, PROG.none,
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
  { key: "all", label: "All" }, { key: "owned", label: "Owned" }, { key: "rented", label: "Rented" }, { key: "unknown", label: "Unknown" },
];
function matchesFilter(p, filter) {
  if (filter === "all") return true;
  if (filter === "owned") return p.owner_occupied === true;
  if (filter === "rented") return p.owner_occupied === false;
  if (filter === "unknown") return p.owner_occupied === null || p.owner_occupied === undefined;
  return true;
}

class MapErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { failed: false }; }
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error, info) {
    try { this.props.onError && this.props.onError(error, info); } catch (e) { /* never crash the boundary */ }
  }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

export default function MapScreen({ navigation }) {
  const pairingCtx = usePairing();
  const pairing = pairingCtx ? pairingCtx.pairing : null;
  const authCtx = useAuth();
  const user = authCtx ? authCtx.user : null;

  // INDEPENDENT dataset states — NO single global `loaded` boolean gates the native map anymore.
  const [propStatus, setPropStatus] = useState("loading"); // loading | ok | cache | failed
  const [cfgStatus, setCfgStatus] = useState("loading");
  const [areaStatus, setAreaStatus] = useState("loading");
  const [features, setFeatures] = useState([]);
  const [cfg, setCfg] = useState(null);
  const [areas, setAreas] = useState([]);
  const [selectedAreaId, setSelectedAreaId] = useState(null);

  const [mapMounted, setMapMounted] = useState(false);
  const [mapInitError, setMapInitError] = useState(false);
  const [retryToken, setRetryToken] = useState(0);

  const [base, setBase] = useState("street");
  const [overlayBuildings, setOverlayBuildings] = useState(false);
  const [imageryLoading, setImageryLoading] = useState(false);
  const [imageryError, setImageryError] = useState(false);
  const [imageryMsg, setImageryMsg] = useState(null);
  const [filter, setFilter] = useState("all");
  const [colorMode, setColorMode] = useState("occupancy");
  const [dl, setDl] = useState({ status: "idle", pct: 0 });
  const [ticket, setTicket] = useState(null);
  const mintingRef = React.useRef(false);
  const loadingTimer = React.useRef(null);
  const mountAttemptedRef = React.useRef(false);

  const flashLoading = () => {
    setImageryLoading(true);
    if (loadingTimer.current) clearTimeout(loadingTimer.current);
    loadingTimer.current = setTimeout(() => setImageryLoading(false), 2800);
  };
  const chooseBase = (v) => { setBase(v); if (v === "satellite") { flashLoading(); ensureTicket(); } };
  const toggleBuildings = () => { setOverlayBuildings((v) => { const nv = !v; if (nv) { flashLoading(); ensureTicket(); } return nv; }); };

  // Capture (never swallow) a native map-init failure into Field Diagnostics — redacted, no secrets.
  const recordMapError = useCallback(async (error) => {
    setMapInitError(true);
    try {
      const diag = buildMapDiagnostic({
        appVersion: Constants.expoConfig?.version || Constants.manifest?.version,
        executionEnvironment: Constants.executionEnvironment,
        reactNativeVersion: (Platform.constants && Platform.constants.reactNativeVersion)
          ? Object.values(Platform.constants.reactNativeVersion).slice(0, 3).join(".") : undefined,
        maplibreJsLoaded: !!MapLibre,
        maplibreNativeAvailable: NATIVE_MAP_OK,
        mapStyleBuilt: !!buildMapStyle(cfg),
        mapConfigLoaded: cfgStatus === "ok" || cfgStatus === "cache",
        propertiesLoaded: propStatus === "ok" || propStatus === "cache",
        canvassLoaded: areaStatus === "ok" || areaStatus === "cache",
        activeBaseLayer: base,
        maptilerConfigured: !!(cfg && cfg.maptiler_configured),
        tileTicketPresent: !!ticket,
        mapMountAttempted: mountAttemptedRef.current,
        mapMountSucceeded: mapMounted,
        areaCount: areas.length,
        selectedAreaId,
        error,
      });
      await putCache(MAP_DIAG_CACHE_KEY, diag);
    } catch (e) { /* diagnostics must never crash the app */ }
  }, [cfg, base, ticket, cfgStatus, propStatus, areaStatus, mapMounted, areas, selectedAreaId]);

  // ---- Independent loaders (each owns its own state; one failing NEVER blocks the others/the map) ----
  // Build the SCOPED property endpoint for the selected area — Field NEVER downloads the whole DB.
  const areaPropsUrl = (area) => {
    if (!area) return null;
    if (area.type === "canvass_section") return `/mobile/canvass-sections/${area.id}/properties`;
    if (area.type === "territory") return `/mobile/map/properties?territory_id=${encodeURIComponent(area.territory_id || area.id)}`;
    if (area.type === "zip") return `/mobile/map/properties?zip=${encodeURIComponent(area.zip_code || "")}`;
    return "/mobile/map/properties";
  };

  const loadPropsForArea = useCallback(async (area) => {
    if (!area) { setFeatures([]); setPropStatus("ok"); return []; }
    const cacheKey = `${CACHE_MAP_PROPS}:${area.id}`;
    setPropStatus("loading");
    try {
      const g = await withTimeout(api.get(areaPropsUrl(area)), REQ_TIMEOUT_MS);
      const feats = (g.data && g.data.features) || [];
      setFeatures(feats); await putCache(cacheKey, feats); setPropStatus("ok");
      return feats;
    } catch (e) {
      const cached = (await getCache(cacheKey)) || [];
      setFeatures(cached); setPropStatus(cached.length ? "cache" : "failed");
      return cached;
    }
  }, []);

  const loadCfg = useCallback(async () => {
    try {
      const r = await withTimeout(api.get("/map-config"), REQ_TIMEOUT_MS);
      setCfg(r.data); await putCache(CACHE_MAP_CFG, r.data); setCfgStatus("ok");
      // Eagerly mint a tile ticket so satellite is available without an extra tap.
      if (NATIVE_MAP_OK && r.data && r.data.maptiler_configured && pairing) {
        ensureAmbientCache();
        try {
          const token = await getToken();
          const res = await mintTileTicket(pairing, token);
          if (res.ticket) {
            setTicket(res.ticket); setImageryMsg(null);
            if (MapLibre && MapLibre.addCustomHeader) { try { MapLibre.addCustomHeader(TILE_TICKET_HEADER, res.ticket); } catch (e) {} }
          }
        } catch (e) { /* keep any previously registered ticket */ }
      }
      return r.data;
    } catch (e) {
      const cached = (await getCache(CACHE_MAP_CFG)) || null;
      setCfg(cached); setCfgStatus(cached ? "cache" : "failed");
      return cached;
    }
  }, [pairing]);

  const loadAreas = useCallback(async () => {
    try {
      const r = await withTimeout(api.get("/mobile/map/areas"), REQ_TIMEOUT_MS);
      const norm = normalizeAreas(r.data);
      setAreas(norm); await putCache(CACHE_AREAS, norm);
      setSelectedAreaId((cur) => cur || pickDefaultArea(norm));
      setAreaStatus("ok");
      return norm;
    } catch (e) {
      const cached = normalizeAreas((await getCache(CACHE_AREAS)) || []);
      setAreas(cached); setSelectedAreaId((cur) => cur || pickDefaultArea(cached));
      setAreaStatus(cached.length ? "cache" : "failed");
      return cached;
    }
  }, []);

  // Fire config + areas INDEPENDENTLY on focus. Properties load per-area (effect below).
  const load = useCallback(() => {
    setMapInitError(false);
    loadCfg(); loadAreas();
  }, [loadCfg, loadAreas]);

  useFocusEffect(useCallback(() => { load(); }, [load, retryToken]));

  // Load properties SCOPED to the selected area (server-authoritative). Re-runs when the user switches
  // area; each area has its own cache so switching never corrupts another area's dataset.
  useEffect(() => {
    const area = findArea(areas, selectedAreaId);
    loadPropsForArea(area);
  }, [selectedAreaId, areas, loadPropsForArea]);

  // Record a redacted load snapshot whenever the datasets settle (counts/statuses only — never secrets).
  useEffect(() => {
    const settled = propStatus !== "loading" && cfgStatus !== "loading" && areaStatus !== "loading";
    if (!settled) return;
    (async () => {
      try {
        const rnv = (Platform.constants && Platform.constants.reactNativeVersion)
          ? Object.values(Platform.constants.reactNativeVersion).slice(0, 3).join(".") : null;
        const sectionAreas = areas.filter((a) => a.type === "canvass_section" && a.geometry);
        const loadDiag = buildMapLoadDiagnostic({
          userId: user?.id, userEmail: user?.email, userRole: user?.role,
          propertiesOk: propStatus === "ok" || propStatus === "cache", propertyFeatures: features,
          cachedPropertyFeatures: (await getCache(`${CACHE_MAP_PROPS}:${selectedAreaId}`)) || [],
          canvassOk: areaStatus === "ok" || areaStatus === "cache",
          sections: sectionAreas.map((a) => ({ id: a.id, name: a.name, geometry: a.geometry, property_count: a.property_count })),
          cachedSectionCount: normalizeAreas((await getCache(CACHE_AREAS)) || []).filter((a) => a.type === "canvass_section").length,
          selectedSectionId: selectedAreaId, selectedAreaId, areaCount: areas.length,
          mapConfigOk: cfgStatus === "ok" || cfgStatus === "cache", mapStyleBuilt: !!buildMapStyle(cfg),
          maplibreVersion: (MapLibre && MapLibre.version) || null, reactNativeVersion: rnv,
          nativeAvailable: NATIVE_MAP_OK, executionEnvironment: Constants.executionEnvironment,
          mapMountAttempted: mountAttemptedRef.current, mapMountSucceeded: mapMounted,
          sourceApi: MapLibre && MapLibre.ShapeSource ? "ShapeSource" : (MapLibre && MapLibre.GeoJSONSource ? "GeoJSONSource" : null),
        });
        await putCache(MAP_LOAD_DIAG_CACHE_KEY, loadDiag);
      } catch (e) { /* diagnostics must never break the map */ }
    })();
  }, [propStatus, cfgStatus, areaStatus, features, areas, cfg, selectedAreaId, mapMounted, user]);

  const ensureTicket = useCallback(async () => {
    if (ticket || mintingRef.current || !imageryAvailable || !pairing) return;
    mintingRef.current = true; setImageryError(false);
    try {
      const token = await getToken();
      const res = await mintTileTicket(pairing, token);
      if (res.ticket) {
        setTicket(res.ticket); setImageryMsg(null);
        if (MapLibre && MapLibre.addCustomHeader) { try { MapLibre.addCustomHeader(TILE_TICKET_HEADER, res.ticket); } catch (e) {} }
      } else { setImageryError(true); setImageryMsg(res.detail || null); }
    } catch (e) { setImageryError(true); } finally { mintingRef.current = false; }
  }, [ticket, pairing]); // eslint-disable-line

  const retryMap = useCallback(() => { setMapInitError(false); setMapMounted(false); mountAttemptedRef.current = false; setRetryToken((x) => x + 1); }, []);

  const openProp = (pid) => navigation.navigate("Property", { id: pid });
  const selectArea = (id) => setSelectedAreaId(id);

  const selectedArea = findArea(areas, selectedAreaId);
  const scopeKind = selectedArea ? (selectedArea.type === "zip" ? "ZIP" : selectedArea.type === "territory" ? "Territory" : "Canvass") : null;
  const sectionAreas = useMemo(() => areas.filter((a) => a.type === "canvass_section" && a.geometry), [areas]);
  // Polygons to draw: all assigned canvass sections + the selected Territory boundary (if a territory).
  const polyAreas = useMemo(() => {
    const secs = areas.filter((a) => a.type === "canvass_section" && a.geometry);
    if (selectedArea && selectedArea.type === "territory" && selectedArea.geometry) {
      return [...secs, { id: selectedArea.id, name: selectedArea.name, color: selectedArea.color, geometry: selectedArea.geometry }];
    }
    return secs;
  }, [areas, selectedArea]);

  const visibleFeatures = useMemo(
    () => features
      .map((f) => ({ ...f, properties: { ...f.properties, progress: deriveProgress(f.properties || {}) } }))
      .filter((f) => matchesFilter(f.properties || {}, filter)),
    [features, filter]
  );
  // Pins scoped to the selected area (ZIP → by zip_code; polygon area → by bounds; none → full map).
  const areaFeatures = useMemo(() => filterFeaturesForArea(visibleFeatures, selectedArea), [visibleFeatures, selectedArea]);

  const satelliteUrl = tileTemplate(pairing, "satellite", ticket);
  const buildingsUrl = tileTemplate(pairing, "buildings", ticket);
  const imageryAvailable = !!(NATIVE_MAP_OK && cfg && cfg.maptiler_configured);
  const imageryReady = imageryAvailable && !!satelliteUrl && !!buildingsUrl;
  const activeBase = imageryAvailable ? base : "street";

  const startDownload = useCallback(async () => {
    const sec = sectionAreas.find((a) => a.id === selectedAreaId);
    if (!sec || !satelliteUrl || !cfg || !cfg.osm_tile_url || !MapLibre) return;
    setDl({ status: "downloading", pct: 0 });
    try {
      await downloadSectionArea({ MapLibre, section: sec, osmTileUrl: cfg.osm_tile_url, satelliteUrl, onProgress: (pct) => setDl({ status: "downloading", pct }) });
      setDl({ status: "done", pct: 100 });
    } catch (e) { setDl({ status: "error", pct: 0 }); }
  }, [sectionAreas, selectedAreaId, satelliteUrl, cfg]);

  // ---------- Header (selector + filters) — shown on every state so controls stay reachable ----------
  const areaSelector = areas.length >= 1 ? (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 8 }} testID="area-selector">
      {areas.map((a) => (
        <TouchableOpacity key={a.id} onPress={() => selectArea(a.id)} testID={`area-chip-${a.id}`}
          style={[s.chip, a.id === selectedAreaId && { backgroundColor: a.color || C.brand, borderColor: a.color || C.brand }]}>
          <Text style={[s.chipKind, a.id === selectedAreaId && { color: "#fff" }]}>{a.type === "zip" ? "ZIP" : a.type === "territory" ? "TERR" : "AREA"}</Text>
          <Text style={[s.chipText, a.id === selectedAreaId && { color: "#fff" }]}>{a.name}</Text>
        </TouchableOpacity>
      ))}
    </ScrollView>
  ) : null;

  const colorModeSwitcher = (
    <View style={s.switcher} testID="pin-color-mode">
      {[["occupancy", "Occupancy"], ["progress", "Progress"]].map(([v, label]) => (
        <TouchableOpacity key={v} onPress={() => setColorMode(v)} style={[s.segBtn, colorMode === v && s.segBtnActive]} testID={`colormode-${v}-button`}>
          <Text style={[s.segText, colorMode === v && s.segTextActive]}>{label}</Text>
        </TouchableOpacity>
      ))}
    </View>
  );

  const baseSwitcher = imageryAvailable ? (
    <View style={s.switcher} testID="basemap-switcher">
      {[["street", "Street"], ["satellite", "Satellite"]].map(([v, label]) => (
        <TouchableOpacity key={v} onPress={() => chooseBase(v)} style={[s.segBtn, activeBase === v && s.segBtnActive]} testID={`basemap-${v}-button`}>
          <Text style={[s.segText, activeBase === v && s.segTextActive]}>{label}</Text>
        </TouchableOpacity>
      ))}
      <TouchableOpacity onPress={toggleBuildings} style={[s.segBtn, overlayBuildings && s.segBtnActive]} testID="basemap-buildings-toggle">
        <Text style={[s.segText, overlayBuildings && s.segTextActive]}>Buildings</Text>
      </TouchableOpacity>
    </View>
  ) : null;

  const filterChips = (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 10 }} testID="pin-filters">
      {FILTERS.map((f) => {
        const dot = f.key === "all" ? null : f.key === "owned" ? PIN.owned : f.key === "rented" ? PIN.rented : PIN.unknown;
        return (
          <TouchableOpacity key={f.key} onPress={() => setFilter(f.key)} testID={`filter-${f.key}`} style={[s.filterChip, filter === f.key && s.filterChipActive]}>
            {dot ? <View style={[s.filterDot, { backgroundColor: dot }]} /> : null}
            <Text style={[s.filterText, filter === f.key && s.filterTextActive]}>{f.label}</Text>
          </TouchableOpacity>
        );
      })}
    </ScrollView>
  );

  const canPrefetch = imageryReady && selectedArea && selectedArea.type === "canvass_section" && !!sectionBounds(selectedArea);
  const prefetchButton = canPrefetch ? (
    <TouchableOpacity onPress={startDownload} disabled={dl.status === "downloading"} style={s.dlBtn} testID="download-area-button">
      <Text style={s.dlBtnText}>
        {dl.status === "downloading" ? `Downloading… ${dl.pct}%` : dl.status === "done" ? "Area saved for offline ✓" : dl.status === "error" ? "Download failed — tap to retry" : "Download area for offline"}
      </Text>
    </TouchableOpacity>
  ) : null;

  const header = (
    <View style={s.hero} testID="my-area-header">
      <Text style={s.heroKicker}>MY AREA</Text>
      <Text style={s.heroTitle} testID="my-area-title">{selectedArea ? `${scopeKind}: ${selectedArea.name}` : "My Area"}</Text>
      <Text style={s.heroSub}>{areaFeatures.length}{filter !== "all" ? ` of ${features.length}` : ""} properties</Text>
      {areaSelector}
      {baseSwitcher}
      {imageryAvailable ? colorModeSwitcher : null}
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

  // ---------- MAP STATES (never a property directory) ----------
  // 1) Native module unavailable (Expo Go / not bundled): compact state, NOT a list.
  if (!NATIVE_MAP_OK) {
    const inExpoGo = Constants.executionEnvironment === "storeClient";
    return (
      <View style={{ flex: 1, backgroundColor: "#F8FAFC" }}>
        {header}
        <View style={s.mapState} testID="map-native-unavailable">
          <Text style={s.stateTitle}>Map needs the RoofSpan Field app</Text>
          <Text style={s.stateBody}>{inExpoGo ? "The satellite map only renders in a RoofSpan Field build (not Expo Go). Open the installed app to view your area." : "The native map is unavailable on this build."}</Text>
        </View>
      </View>
    );
  }

  // 1b) No area available at all (no canvass section, no territory, no ZIP): compact state — NEVER a
  //     fallback that dumps every property in the database onto the map.
  if (areaStatus !== "loading" && areas.length === 0) {
    return (
      <View style={{ flex: 1, backgroundColor: "#F8FAFC" }}>
        {header}
        <View style={s.mapState} testID="map-no-area">
          <Text style={s.stateTitle}>No property area available</Text>
          <Text style={s.stateBody}>You don't have a canvass section or territory assigned yet. Ask your manager to assign you an area.</Text>
        </View>
      </View>
    );
  }

  const realStyle = buildMapStyle(cfg);            // null when config is not yet usable
  const mapStyle = realStyle || BASE_FALLBACK_STYLE; // map STILL mounts on a valid background style
  const camBounds = selectedArea
    ? boundsToCamera(selectedArea.bounds || boundsFromFeatures(filterFeaturesForArea(features, selectedArea)))
    : null;

  // 2) Native map initialization threw: compact retry inside the map region (diagnostic already recorded).
  if (mapInitError) {
    return (
      <View style={{ flex: 1, backgroundColor: "#F8FAFC" }}>
        {header}
        <View style={s.mapState} testID="map-init-error">
          <Text style={s.stateTitle}>Map unavailable</Text>
          <Text style={s.stateBody}>The map couldn't start. Your data is safe.</Text>
          <TouchableOpacity style={s.retryBtn} onPress={retryMap} testID="map-retry-button"><Text style={s.retryText}>Tap to retry</Text></TouchableOpacity>
        </View>
      </View>
    );
  }

  const { MapView, Camera, ShapeSource, CircleLayer, FillLayer, LineLayer, RasterSource, RasterLayer, VectorSource } = MapLibre;
  const fc = { type: "FeatureCollection", features: areaFeatures };
  const polyFc = buildAllSectionsFC(polyAreas.map((a) => ({ id: a.id, name: a.name, color: a.color, geometry: a.geometry })), selectedAreaId);
  const secColor = (selectedArea && selectedArea.color) || C.brand;
  mountAttemptedRef.current = true;

  const fallback = (
    <View style={{ flex: 1, backgroundColor: "#F8FAFC" }}>
      {header}
      <View style={s.mapState} testID="map-init-error">
        <Text style={s.stateTitle}>Map unavailable</Text>
        <Text style={s.stateBody}>The map couldn't start. Your data is safe.</Text>
        <TouchableOpacity style={s.retryBtn} onPress={retryMap} testID="map-retry-button"><Text style={s.retryText}>Tap to retry</Text></TouchableOpacity>
      </View>
    </View>
  );

  return (
    <MapErrorBoundary fallback={fallback} onError={recordMapError}>
      <View style={{ flex: 1 }} testID="map-container">
        {header}
        <View style={{ flex: 1 }}>
          <MapView style={{ flex: 1 }} mapStyle={activeBase === "satellite" && satelliteUrl ? SATELLITE_BG_STYLE : mapStyle}
            testID="map-view" onDidFinishRenderingMapFully={() => setMapMounted(true)}>
            <Camera
              {...(camBounds ? { bounds: camBounds } : { zoomLevel: safeZoom(cfg), centerCoordinate: safeCenter(cfg) })}
              animationDuration={600}
            />

            {activeBase === "satellite" && satelliteUrl && RasterSource && (
              <RasterSource id="rs-satellite" tileUrlTemplates={[satelliteUrl]} tileSize={512}>
                <RasterLayer id="rs-satellite-layer" style={{}} />
              </RasterSource>
            )}
            {/* When NOT satellite, draw the base OSM raster from config as a child so the map mounts even
                if config arrives after the MapView (background style is used until then). */}
            {activeBase !== "satellite" && realStyle && RasterSource && (
              <RasterSource id="rs-osm" tileUrlTemplates={[cfg.osm_tile_url]} tileSize={256}>
                <RasterLayer id="rs-osm-layer" style={{}} />
              </RasterSource>
            )}

            {overlayBuildings && buildingsUrl && VectorSource && (
              <VectorSource id="rs-buildings" tileUrlTemplates={[buildingsUrl]} minZoomLevel={14} maxZoomLevel={20}>
                <FillLayer id="rs-buildings-fill" sourceLayerID="building" minZoomLevel={14}
                  style={{ fillColor: ["case", ["==", ["get", "class"], "residential"], "#F97316", "#64748B"], fillOpacity: 0.35 }} />
                <LineLayer id="rs-buildings-line" sourceLayerID="building" minZoomLevel={14}
                  style={{ lineColor: ["case", ["==", ["get", "class"], "residential"], "#C2410C", "#475569"], lineWidth: 1.25, lineOpacity: 0.9 }} />
              </VectorSource>
            )}

            <ShapeSource id="myarea" shape={polyFc}>
              <FillLayer id="myarea-fill" style={{ fillColor: ["case", ["get", "selected"], secColor, ["coalesce", ["get", "color"], C.brand]], fillOpacity: ["case", ["get", "selected"], 0.28, 0.1] }} />
              <LineLayer id="myarea-line" style={{ lineColor: ["case", ["get", "selected"], secColor, ["coalesce", ["get", "color"], C.brand]], lineWidth: ["case", ["get", "selected"], 3.5, 1.5] }} />
            </ShapeSource>
            <ShapeSource id="props" shape={fc} onPress={(e) => { const f = e.features && e.features[0]; if (f) openProp(f.properties.id); }}>
              <CircleLayer id="pins" style={{ circleRadius: 7, circleColor: colorMode === "progress" ? PROGRESS_COLOR : PIN_COLOR, circleStrokeWidth: 2, circleStrokeColor: "#fff" }} />
            </ShapeSource>
          </MapView>

          {/* Base tiles genuinely unavailable (no config + no satellite ticket): non-blocking retry chip —
              the MapView itself stays mounted. */}
          {!realStyle && !(activeBase === "satellite" && satelliteUrl) ? (
            <View style={s.imgHintWrap} pointerEvents="box-none">
              <TouchableOpacity style={s.imgHint} onPress={retryMap} testID="basemap-retry">
                <Text style={s.imgHintText}>{cfgStatus === "failed" ? "Base map unavailable — tap to retry" : "Loading base map…"}</Text>
              </TouchableOpacity>
            </View>
          ) : null}

          {(activeBase === "satellite" || overlayBuildings) && (!satelliteUrl || imageryLoading) ? (
            <View style={s.imgHintWrap} pointerEvents="box-none">
              <TouchableOpacity style={s.imgHint} onPress={ensureTicket} disabled={!!satelliteUrl && imageryLoading} testID="imagery-hint">
                <Text style={s.imgHintText}>{imageryError && !satelliteUrl ? (imageryMsg ? `Imagery unavailable: ${imageryMsg}` : "Imagery unavailable — tap to retry") : "Loading imagery…"}</Text>
              </TouchableOpacity>
            </View>
          ) : null}
          {legend}
        </View>
      </View>
    </MapErrorBoundary>
  );
}

const s = StyleSheet.create({
  hero: { backgroundColor: "#fff", paddingHorizontal: 16, paddingTop: 14, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: C.line },
  heroKicker: { fontSize: 11, fontWeight: "800", letterSpacing: 1, color: C.sub },
  heroTitle: { fontSize: 20, fontWeight: "900", color: C.ink, marginTop: 2 },
  heroSub: { fontSize: 13, color: C.sub, marginTop: 2 },
  chip: { borderWidth: 1, borderColor: C.line, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6, marginRight: 8, backgroundColor: "#fff", flexDirection: "row", alignItems: "center" },
  chipKind: { fontSize: 9, fontWeight: "900", letterSpacing: 0.6, color: C.sub, marginRight: 6 },
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
  imgHintWrap: { position: "absolute", top: 12, left: 0, right: 0, alignItems: "center" },
  imgHint: { backgroundColor: "rgba(15,27,43,0.92)", borderRadius: 999, paddingHorizontal: 14, paddingVertical: 8 },
  imgHintText: { color: "#fff", fontSize: 12, fontWeight: "700" },
  legend: { position: "absolute", left: 12, bottom: 12, backgroundColor: "rgba(255,255,255,0.95)", borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10, borderWidth: 1, borderColor: C.line, shadowColor: "#000", shadowOpacity: 0.12, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 3 },
  legendTitle: { fontSize: 10, fontWeight: "800", letterSpacing: 0.8, color: C.sub, marginBottom: 6, textTransform: "uppercase" },
  legendRow: { flexDirection: "row", alignItems: "center", marginBottom: 4 },
  legendDot: { width: 12, height: 12, borderRadius: 6, marginRight: 8, borderWidth: 1.5, borderColor: "#fff" },
  legendLabel: { fontSize: 12, fontWeight: "600", color: C.ink },
  mapState: { flex: 1, alignItems: "center", justifyContent: "center", padding: 28, backgroundColor: "#0b1b2b" },
  stateTitle: { fontSize: 17, fontWeight: "800", color: "#fff", marginBottom: 6, textAlign: "center" },
  stateBody: { fontSize: 14, color: "#CBD5E1", textAlign: "center", lineHeight: 20 },
  retryBtn: { marginTop: 18, backgroundColor: C.brand, borderRadius: 10, paddingHorizontal: 22, paddingVertical: 11 },
  retryText: { color: "#fff", fontSize: 14, fontWeight: "800" },
});

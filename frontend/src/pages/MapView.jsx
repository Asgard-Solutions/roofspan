import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import * as maplibregl from "maplibre-gl";
import Supercluster from "supercluster";
import "maplibre-gl/dist/maplibre-gl.css";
import { toast } from "sonner";
import { api, apiError, getToken, API_BASE } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import ImportDialog from "@/components/ImportDialog";
import PropertySheet from "@/components/PropertySheet";
import { PencilRuler, Download, Trash2, MapPin, Ban, Check, X, Plus, Loader2, UserPlus } from "lucide-react";

const OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const MANAGE = ["owner", "administrator", "office"];
const COLORS = ["#2563EB", "#EA580C", "#16A34A", "#9333EA", "#DC2626", "#0891B2"];

function baseStyle() {
  return {
    version: 8,
    sources: { osm: { type: "raster", tiles: [OSM], tileSize: 256, maxzoom: 19, attribution: "© OpenStreetMap contributors" } },
    layers: [{ id: "osm", type: "raster", source: "osm" }],
  };
}

export default function MapView() {
  const { user } = useAuth();
  const canManage = MANAGE.includes(user?.role);
  const navigate = useNavigate();

  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const loadedRef = useRef(false);
  const drawing = useRef(false);
  const drawPts = useRef([]);
  const canvassGeom = useRef(null);
  const vertexMarkers = useRef([]);
  const routeMarkers = useRef([]);
  const zipForTerritory = useRef(null);
  const openSheetRef = useRef(null);
  const superRef = useRef(null);
  const markersRef = useRef([]);
  const clusterZoomMax = 16;

  const [territories, setTerritories] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [propCount, setPropCount] = useState(0);
  const [isDrawing, setIsDrawing] = useState(false);
  const [drawCount, setDrawCount] = useState(0);
  const [zip, setZip] = useState("");
  const [geoLoading, setGeoLoading] = useState(false);
  const [zipHit, setZipHit] = useState(null);
  const [mapConfig, setMapConfig] = useState(null);
  const [baseLayer, setBaseLayer] = useState("map");
  const [occFilter, setOccFilter] = useState("all");
  const [contactableOnly, setContactableOnly] = useState(false);
  const [features, setFeatures] = useState([]);
  const [routeInfo, setRouteInfo] = useState(null);
  const [builtRoute, setBuiltRoute] = useState([]);
  const [assignOpen, setAssignOpen] = useState(false);
  const [reps, setReps] = useState([]);
  const [routeName, setRouteName] = useState("");
  const [routeRepId, setRouteRepId] = useState("");
  const [savingRoute, setSavingRoute] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState(COLORS[0]);
  const [saving, setSaving] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [sheetId, setSheetId] = useState(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [sections, setSections] = useState([]);
  const [selectedSectionId, setSelectedSectionId] = useState(null);
  const [sectionPropIds, setSectionPropIds] = useState(null);
  const [isCanvassDrawing, setIsCanvassDrawing] = useState(false);
  const [canvassOpen, setCanvassOpen] = useState(false);
  const [canvassPreview, setCanvassPreview] = useState(null);
  const [canvassName, setCanvassName] = useState("");
  const [canvassColor, setCanvassColor] = useState(COLORS[0]);
  const [canvassRepId, setCanvassRepId] = useState("");
  const [savingSection, setSavingSection] = useState(false);

  const selected = territories.find((t) => t.id === selectedId);

  const loadTerritories = useCallback(async () => {
    try {
      const { data } = await api.get("/territories");
      setTerritories(data);
      return data;
    } catch (e) {
      toast.error(apiError(e));
      return [];
    }
  }, []);

  const setTerritorySource = useCallback((list, selId) => {
    const map = mapRef.current;
    if (!map || !map.getSource("territories")) return;
    map.getSource("territories").setData({
      type: "FeatureCollection",
      features: list.map((t) => ({
        type: "Feature",
        geometry: t.geometry,
        properties: { id: t.id, color: t.color, selected: t.id === selId },
      })),
    });
  }, []);

  const clearMarkers = useCallback(() => {
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];
  }, []);

  // Main-thread clustering rendered with DOM markers is the authoritative packaged-Windows path.
  // The MapLibre GeoJSON worker can fail to tile a large property source under WebView2, so marker
  // visibility must never depend on that worker.
  const renderClusters = useCallback(() => {
    const map = mapRef.current;
    const index = superRef.current;
    clearMarkers();
    if (!map || !index) return;
    const b = map.getBounds();
    const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
    const zoom = Math.round(map.getZoom());
    const clustered = index.getClusters(bbox, zoom);
    for (const f of clustered) {
      const [lng, lat] = f.geometry.coordinates;
      const el = document.createElement("div");
      if (f.properties.cluster) {
        const count = f.properties.point_count;
        const size = count >= 50 ? 46 : count >= 10 ? 38 : 30;
        const color = count >= 50 ? "#1D4ED8" : count >= 10 ? "#3B82F6" : "#60A5FA";
        el.setAttribute("data-testid", "map-cluster");
        el.style.cssText = `width:${size}px;height:${size}px;background:${color};color:#fff;border:2px solid #fff;border-radius:9999px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;cursor:pointer;box-shadow:0 1px 4px rgba(0,0,0,.35)`;
        el.textContent = f.properties.point_count_abbreviated;
        el.addEventListener("click", (ev) => {
          ev.stopPropagation();
          try {
            const z = Math.min(index.getClusterExpansionZoom(f.properties.cluster_id), 19);
            map.easeTo({ center: [lng, lat], zoom: z, duration: 500 });
          } catch (err) { /* noop */ }
        });
      } else {
        const dnk = !!f.properties.do_not_knock;
        const occupancy = f.properties.occupancy;
        const color = dnk ? "#DC2626" : occupancy === "owned" ? "#16A34A" : occupancy === "rented" ? "#D97706" : "#64748B";
        el.setAttribute("data-testid", "map-property-pin");
        el.style.cssText = `width:16px;height:16px;background:${color};border:2px solid #fff;border-radius:9999px;cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.35)`;
        const id = f.properties.id;
        el.addEventListener("click", (ev) => {
          ev.stopPropagation();
          if (drawing.current) return;
          if (id && openSheetRef.current) openSheetRef.current(id);
        });
      }
      const marker = new maplibregl.Marker({ element: el }).setLngLat([lng, lat]).addTo(map);
      markersRef.current.push(marker);
    }
  }, [clearMarkers]);

  const loadProperties = useCallback(async (territoryId) => {
    const map = mapRef.current;
    if (!map) return;
    if (!territoryId) {
      superRef.current = null;
      clearMarkers();
      setPropCount(0);
      setFeatures([]);
      return;
    }
    try {
      const { data } = await api.get(`/properties/geojson?territory_id=${territoryId}`);
      const feats = (data.features || []).filter((f) => {
        const c = f?.geometry?.coordinates;
        return (
          f?.geometry?.type === "Point" && Array.isArray(c) && c.length >= 2 &&
          Number.isFinite(Number(c[0])) && Number.isFinite(Number(c[1])) &&
          Number(c[0]) >= -180 && Number(c[0]) <= 180 &&
          Number(c[1]) >= -90 && Number(c[1]) <= 90
        );
      }).map((f) => ({
        ...f,
        geometry: { ...f.geometry, coordinates: [Number(f.geometry.coordinates[0]), Number(f.geometry.coordinates[1])] },
      }));

      // Keep the GeoJSON source populated for existing hit/route integrations, but hide MapLibre's
      // direct property layers so the DOM/Supercluster renderer remains the single visible path.
      const normalized = { type: "FeatureCollection", features: feats };
      const source = map.getSource("properties");
      if (source) source.setData(normalized);
      if (map.getLayer("prop-points")) map.setLayoutProperty("prop-points", "visibility", "none");
      if (map.getLayer("prop-hit")) map.setLayoutProperty("prop-hit", "visibility", "none");

      setPropCount(feats.length);
      setFeatures(feats);
    } catch (e) {
      toast.error(apiError(e));
    }
  }, [clearMarkers]);

  const fitToTerritory = useCallback((t) => {
    const map = mapRef.current;
    if (!map || !t) return;
    const b = new maplibregl.LngLatBounds();
    t.geometry.coordinates[0].forEach((c) => b.extend(c));
    map.fitBounds(b, { padding: 60, maxZoom: 15, duration: 600 });
  }, []);

  const renderVertexMarkers = useCallback((pts) => {
    const map = mapRef.current;
    if (!map) return;
    vertexMarkers.current.forEach((m) => m.remove());
    vertexMarkers.current = [];
    if (pts.length > 24) return;
    pts.forEach((c, i) => {
      const el = document.createElement("div");
      el.className = "rs-vertex-marker";
      el.setAttribute("data-testid", `draw-vertex-${i + 1}`);
      el.textContent = String(i + 1);
      const marker = new maplibregl.Marker({ element: el, anchor: "center" }).setLngLat(c).addTo(map);
      vertexMarkers.current.push(marker);
    });
  }, []);

  const updateDrawSource = useCallback(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("draw")) return;
    const pts = drawPts.current;
    let feat = { type: "FeatureCollection", features: [] };
    if (pts.length >= 3) {
      feat = { type: "FeatureCollection", features: [{ type: "Feature", geometry: { type: "Polygon", coordinates: [[...pts, pts[0]]] }, properties: {} }] };
    } else if (pts.length >= 2) {
      feat = { type: "FeatureCollection", features: [{ type: "Feature", geometry: { type: "LineString", coordinates: pts }, properties: {} }] };
    }
    map.getSource("draw").setData(feat);
    map.getSource("draw-pts").setData({ type: "FeatureCollection", features: pts.map((c) => ({ type: "Feature", geometry: { type: "Point", coordinates: c }, properties: {} })) });
    renderVertexMarkers(pts);
  }, [renderVertexMarkers]);

  useEffect(() => {
    api.get("/map-config").then(({ data }) => {
      if (mapRef.current || !containerRef.current) return;
      setMapConfig(data);
      const startBase = data.satellite_enabled ? "satellite" : "map";
      setBaseLayer(startBase);
      const map = new maplibregl.Map({
        container: containerRef.current,
        style: baseStyle(),
        center: data.default_center,
        zoom: data.default_zoom,
        transformRequest: (url) => {
          if (url.includes("/map/tiles/satellite/") || url.includes("/map/tiles/buildings/")) {
            return { url, headers: { Authorization: `Bearer ${getToken()}` } };
          }
          return { url };
        },
      });
      map.addControl(new maplibregl.NavigationControl(), "top-right");
      mapRef.current = map;

      const initMapLayers = () => {
        if (data.maptiler_configured) {
          map.addSource("satellite", {
            type: "raster",
            tiles: [`${API_BASE}/map/tiles/satellite/{z}/{x}/{y}`],
            tileSize: 512,
            attribution: "© MapTiler © OpenStreetMap contributors",
          });
          map.addLayer({
            id: "satellite-layer", type: "raster", source: "satellite",
            layout: { visibility: startBase === "satellite" ? "visible" : "none" },
          });
          map.setLayoutProperty("osm", "visibility", startBase === "satellite" ? "none" : "visible");

          map.addSource("buildings", {
            type: "vector",
            tiles: [`${API_BASE}/map/tiles/buildings/{z}/{x}/{y}`],
            minzoom: 14,
            maxzoom: 20,
            attribution: "© MapTiler © OpenStreetMap contributors",
          });
          map.addLayer({
            id: "buildings-fill",
            type: "fill",
            source: "buildings",
            "source-layer": "building",
            minzoom: 14,
            layout: { visibility: "none" },
            paint: {
              "fill-color": ["case", ["==", ["get", "class"], "residential"], "#f97316", "#64748b"],
              "fill-opacity": 0.35,
            },
          });
          map.addLayer({
            id: "buildings-outline",
            type: "line",
            source: "buildings",
            "source-layer": "building",
            minzoom: 14,
            layout: { visibility: "none" },
            paint: {
              "line-color": ["case", ["==", ["get", "class"], "residential"], "#c2410c", "#475569"],
              "line-width": 1.25,
              "line-opacity": 0.9,
            },
          });
        }

        map.addSource("territories", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "terr-fill", type: "fill", source: "territories", paint: { "fill-color": ["get", "color"], "fill-opacity": ["case", ["get", "selected"], 0.18, 0.06] } });
        map.addLayer({ id: "terr-line", type: "line", source: "territories", paint: { "line-color": ["get", "color"], "line-width": ["case", ["get", "selected"], 3, 1.5] } });

        map.addSource("canvass-sections", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "canvass-section-fill", type: "fill", source: "canvass-sections", paint: { "fill-color": ["get", "color"], "fill-opacity": ["case", ["get", "selected"], 0.28, 0.12] } });
        map.addLayer({ id: "canvass-section-line", type: "line", source: "canvass-sections", paint: { "line-color": ["get", "color"], "line-width": ["case", ["get", "selected"], 3.5, 2], "line-dasharray": [1, 0] } });

        map.addSource("properties", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({
          id: "prop-points", type: "circle", source: "properties", layout: { visibility: "none" },
          paint: { "circle-radius": 8, "circle-color": "#64748B", "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 },
        });
        map.addLayer({
          id: "prop-hit", type: "circle", source: "properties", layout: { visibility: "none" },
          paint: { "circle-radius": 16, "circle-color": "#000000", "circle-opacity": 0 },
        });

        map.addSource("draw", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "draw-fill", type: "fill", source: "draw", paint: { "fill-color": "#EA580C", "fill-opacity": 0.15 } });
        map.addLayer({ id: "draw-line", type: "line", source: "draw", paint: { "line-color": "#EA580C", "line-width": 2, "line-dasharray": [2, 1] } });
        map.addSource("draw-pts", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "draw-vertices", type: "circle", source: "draw-pts", paint: { "circle-radius": 7, "circle-color": "#EA580C", "circle-stroke-color": "#fff", "circle-stroke-width": 2.5 } });

        map.addSource("route", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "route-line", type: "line", source: "route",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: { "line-color": "#4F46E5", "line-width": 4, "line-opacity": 0.85 } });

        loadedRef.current = true;

        map.on("click", (e) => {
          if (drawing.current) {
            drawPts.current = [...drawPts.current, [e.lngLat.lng, e.lngLat.lat]];
            updateDrawSource();
            setDrawCount(drawPts.current.length);
          }
        });

        map.on("moveend", () => renderClusters());
        loadTerritories().then((list) => setTerritorySource(list, null));
      };

      if (map.isStyleLoaded()) initMapLayers();
      else map.on("load", initMapLayers);
    });
    return () => {
      clearMarkers();
      if (mapRef.current) { mapRef.current.remove(); mapRef.current = null; }
    };
  }, [loadTerritories, setTerritorySource, updateDrawSource, renderClusters, clearMarkers]);

  openSheetRef.current = (id) => { setSheetId(id); setSheetOpen(true); };

  const selectTerritory = (t, list = territories) => {
    setSelectedId(t.id);
    setTerritorySource(list, t.id);
    fitToTerritory(t);
    loadProperties(t.id);
    setSelectedSectionId(null);
    setSectionPropIds(null);
    loadSections(t.id);
  };

  const setCanvassSource = useCallback((list, selId) => {
    const map = mapRef.current;
    if (!map || !map.getSource("canvass-sections")) return;
    map.getSource("canvass-sections").setData({
      type: "FeatureCollection",
      features: (list || []).filter((s) => s.geometry).map((s) => ({
        type: "Feature", geometry: s.geometry,
        properties: { id: s.id, color: s.color, selected: s.id === selId },
      })),
    });
  }, []);

  const loadSections = useCallback(async (territoryId) => {
    if (!territoryId) { setSections([]); setCanvassSource([], null); return; }
    try {
      const { data } = await api.get(`/canvass-sections?territory_id=${territoryId}`);
      setSections(data);
      setCanvassSource(data, null);
    } catch (e) { setSections([]); }
    try { const r = await api.get("/users/assignable"); setReps(r.data); } catch (e) { /* noop */ }
  }, [setCanvassSource]);

  const clearSection = useCallback(() => {
    setSelectedSectionId(null);
    setSectionPropIds(null);
    setCanvassSource(sections, null);
  }, [sections, setCanvassSource]);

  const selectSection = useCallback(async (s) => {
    setSelectedSectionId(s.id);
    setCanvassSource(sections, s.id);
    const ring = s.geometry?.coordinates?.[0] || [];
    if (ring.length && mapRef.current) {
      const b = ring.reduce((bb, c) => bb.extend(c), new maplibregl.LngLatBounds(ring[0], ring[0]));
      mapRef.current.fitBounds(b, { padding: 70, duration: 600 });
    }
    try {
      const { data } = await api.get(`/canvass-sections/${s.id}/properties`);
      setSectionPropIds(new Set(data.map((p) => p.id)));
    } catch (e) { toast.error(apiError(e)); }
  }, [sections, setCanvassSource]);

  const startCanvassDraw = () => {
    if (!selectedId) { toast.error("Select a Territory first"); return; }
    drawing.current = true;
    drawPts.current = [];
    zipForTerritory.current = null;
    setIsCanvassDrawing(true);
    setIsDrawing(true);
    setDrawCount(0);
    updateDrawSource();
    if (mapRef.current) mapRef.current.getCanvas().style.cursor = "crosshair";
    toast.info("Click the map to outline the Canvass Section");
  };

  const finishCanvassDraw = async () => {
    if (drawPts.current.length < 3) { toast.error("Add at least 3 points to form a section"); return; }
    drawing.current = false;
    setIsDrawing(false);
    if (mapRef.current) mapRef.current.getCanvas().style.cursor = "";
    const ring = [...drawPts.current, drawPts.current[0]];
    const geometry = { type: "Polygon", coordinates: [ring] };
    canvassGeom.current = geometry;
    try {
      const { data } = await api.post("/canvass-sections/preview", { territory_id: selectedId, geometry });
      setCanvassPreview(data);
      setCanvassName(""); setCanvassColor(COLORS[0]); setCanvassRepId("");
      setCanvassOpen(true);
    } catch (e) {
      toast.error(apiError(e));
      cancelDraw();
    }
  };

  const saveCanvassSection = async () => {
    if (!canvassName.trim()) { toast.error("Name the section"); return; }
    if (canvassPreview?.conflict_count > 0) { toast.error("Resolve overlapping properties before saving"); return; }
    setSavingSection(true);
    try {
      await api.post("/canvass-sections", {
        territory_id: selectedId, name: canvassName.trim(), color: canvassColor,
        geometry: canvassGeom.current, assigned_user_id: canvassRepId || null,
      });
      toast.success("Canvass Section created");
      setCanvassOpen(false);
      setIsCanvassDrawing(false);
      drawPts.current = []; setDrawCount(0); updateDrawSource();
      await loadSections(selectedId);
    } catch (e) {
      const d = e?.response?.data?.detail;
      if (e?.response?.status === 409) toast.error(typeof d === "object" ? d.message : "Overlap conflict — resolve and try again");
      else toast.error(apiError(e));
    } finally { setSavingSection(false); }
  };

  const deleteSection = async (s) => {
    if (!window.confirm(`Delete Canvass Section "${s.name}"? Properties, visits and leads are kept.`)) return;
    try {
      await api.delete(`/canvass-sections/${s.id}`);
      toast.success("Section deleted (properties preserved)");
      if (selectedSectionId === s.id) clearSection();
      await loadSections(selectedId);
    } catch (e) { toast.error(apiError(e)); }
  };

  const reassignSection = async (s, userId) => {
    try {
      await api.put(`/canvass-sections/${s.id}`, { assigned_user_id: userId || null });
      toast.success("Section reassigned");
      await loadSections(selectedId);
    } catch (e) { toast.error(apiError(e)); }
  };

  const handleImportComplete = useCallback(async () => {    const list = await loadTerritories();
    if (selectedId) {
      setTerritorySource(list, selectedId);
      await loadProperties(selectedId);
    }
  }, [loadTerritories, setTerritorySource, loadProperties, selectedId]);

  const filteredFeatures = useMemo(() => features.filter((f) => {
    const p = f.properties || {};
    if (sectionPropIds && !sectionPropIds.has(p.id)) return false;
    if (occFilter !== "all" && p.occupancy !== occFilter) return false;
    if (contactableOnly && !p.contactable) return false;
    return true;
  }), [features, occFilter, contactableOnly, sectionPropIds]);

  // Rebuild the main-thread cluster index whenever the loaded property set or user filter changes.
  // This is the missing link that previously left superRef empty while the UI reported thousands of
  // loaded properties.
  useEffect(() => {
    if (!filteredFeatures.length) {
      superRef.current = null;
      clearMarkers();
      return;
    }
    const index = new Supercluster({ radius: 55, maxZoom: clusterZoomMax, minPoints: 2 });
    index.load(filteredFeatures);
    superRef.current = index;
    renderClusters();
  }, [filteredFeatures, renderClusters, clearMarkers]);

  const clearRoute = useCallback(() => {
    const map = mapRef.current;
    routeMarkers.current.forEach((m) => m.remove());
    routeMarkers.current = [];
    if (map && map.getSource("route")) map.getSource("route").setData({ type: "FeatureCollection", features: [] });
    setRouteInfo(null);
    setBuiltRoute([]);
  }, []);

  const _haversineMi = (a, b) => {
    const R = 3958.8, toRad = (d) => (d * Math.PI) / 180;
    const dLat = toRad(b[1] - a[1]), dLng = toRad(b[0] - a[0]);
    const s = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a[1])) * Math.cos(toRad(b[1])) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(s));
  };

  const buildRoute = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    const pts = filteredFeatures.slice(0, 200).map((f) => ({ id: f.properties.id, c: f.geometry.coordinates, address: f.properties.address }));
    if (pts.length < 2) { toast.error("Need at least 2 matching stops to build a route"); return; }
    const remaining = [...pts].sort((a, b) => a.c[0] - b.c[0]);
    const order = [remaining.shift()];
    let miles = 0;
    while (remaining.length) {
      const last = order[order.length - 1].c;
      let bi = 0, bd = Infinity;
      remaining.forEach((r, i) => { const d = _haversineMi(last, r.c); if (d < bd) { bd = d; bi = i; } });
      miles += bd;
      order.push(remaining.splice(bi, 1)[0]);
    }
    map.getSource("route").setData({
      type: "FeatureCollection",
      features: [{ type: "Feature", geometry: { type: "LineString", coordinates: order.map((o) => o.c) }, properties: {} }],
    });
    routeMarkers.current.forEach((m) => m.remove());
    routeMarkers.current = order.map((o, i) => {
      const el = document.createElement("div");
      el.className = "rs-route-marker";
      el.textContent = String(i + 1);
      return new maplibregl.Marker({ element: el, anchor: "center" }).setLngLat(o.c).addTo(map);
    });
    map.fitBounds(order.reduce((b, o) => b.extend(o.c), new maplibregl.LngLatBounds(order[0].c, order[0].c)), { padding: 70, duration: 700 });
    setRouteInfo({ stops: order.length, miles: miles.toFixed(1) });
    setBuiltRoute(order.map((o, i) => ({
      property_id: o.id, latitude: o.c[1], longitude: o.c[0], sort: i, address: o.address || "",
    })));
    toast.success(`Route ready: ${order.length} stops, ~${miles.toFixed(1)} mi`);
  }, [filteredFeatures]);

  useEffect(() => { clearRoute(); }, [features, clearRoute]);

  const openAssign = useCallback(async () => {
    setRouteName(selected?.name ? `${selected.name} route` : (zipHit?.zip ? `ZIP ${zipHit.zip} route` : "Canvassing route"));
    setRouteRepId("");
    setAssignOpen(true);
    try {
      const { data } = await api.get("/users/assignable");
      setReps(data);
    } catch (e) {
      toast.error(apiError(e));
    }
  }, [selected, zipHit]);

  const saveRoute = useCallback(async () => {
    if (!routeName.trim()) { toast.error("Give the route a name"); return; }
    if (builtRoute.length < 2) { toast.error("Build a walking route first"); return; }
    setSavingRoute(true);
    try {
      const { data } = await api.post("/routes", {
        name: routeName.trim(), territory_id: selectedId || null, assigned_user_id: routeRepId || null,
        est_miles: routeInfo ? Number(routeInfo.miles) : 0, stops: builtRoute,
      });
      toast.success(routeRepId ? "Route assigned" : "Route saved");
      setAssignOpen(false);
      navigate(`/routes/${data.id}`);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSavingRoute(false);
    }
  }, [routeName, builtRoute, selectedId, routeRepId, routeInfo, navigate]);

  const switchBase = (layer) => {
    const map = mapRef.current;
    if (!map || layer === baseLayer) return;
    if (layer === "satellite" && !map.getLayer("satellite-layer")) return;
    if (layer === "buildings" && !map.getLayer("buildings-fill")) return;
    setBaseLayer(layer);
    if (map.getLayer("satellite-layer")) map.setLayoutProperty("satellite-layer", "visibility", layer === "satellite" ? "visible" : "none");
    if (map.getLayer("osm")) map.setLayoutProperty("osm", "visibility", layer === "satellite" ? "none" : "visible");
    if (map.getLayer("buildings-fill")) map.setLayoutProperty("buildings-fill", "visibility", layer === "buildings" ? "visible" : "none");
    if (map.getLayer("buildings-outline")) map.setLayoutProperty("buildings-outline", "visibility", layer === "buildings" ? "visible" : "none");
    if (layer === "buildings" && map.getZoom() < 14) {
      toast.info("Zoom in to level 14 or closer to see MapTiler building footprints.");
    }
  };

  const searchZip = async (e) => {
    e?.preventDefault?.();
    const code = zip.trim();
    if (!code) { toast.error("Enter a ZIP or postal code"); return; }
    setGeoLoading(true);
    try {
      const { data } = await api.get(`/geocode/zip?zip=${encodeURIComponent(code)}`);
      setZipHit(data);
      const map = mapRef.current;
      if (map) {
        const [[w, s], [e2, n]] = data.bbox;
        map.fitBounds([[w, s], [e2, n]], { padding: 60, maxZoom: 15, duration: 800 });
      }
      toast.success(`Centered on ${data.display_name}`);
    } catch (err) {
      setZipHit(null);
      toast.error(apiError(err));
    } finally {
      setGeoLoading(false);
    }
  };

  const addZipAsTerritory = () => {
    if (!zipHit) return;
    const [[w, s], [e2, n]] = zipHit.bbox;
    let ring = null;
    const geom = zipHit.geometry;
    if (geom && geom.type === "Polygon" && geom.coordinates?.[0]?.length >= 3) ring = geom.coordinates[0];
    else if (geom && geom.type === "MultiPolygon" && geom.coordinates?.length) ring = geom.coordinates.map((poly) => poly[0]).sort((a, b) => b.length - a.length)[0];
    if (!ring || ring.length < 3) {
      ring = [[w, s], [e2, s], [e2, n], [w, n]];
      toast.info("No exact boundary for this ZIP — added its area as an editable rectangle.");
    } else toast.info("Snapped the ZIP boundary. Review and click Finish to name & save.");
    if (ring.length > 1) {
      const a = ring[0], b = ring[ring.length - 1];
      if (a[0] === b[0] && a[1] === b[1]) ring = ring.slice(0, -1);
    }
    drawPts.current = ring.map((c) => [c[0], c[1]]);
    zipForTerritory.current = (zip || "").trim() || null;
    drawing.current = true;
    setIsDrawing(true);
    setDrawCount(drawPts.current.length);
    updateDrawSource();
    const map = mapRef.current;
    if (map) {
      map.getCanvas().style.cursor = "crosshair";
      map.fitBounds([[w, s], [e2, n]], { padding: 60, maxZoom: 15, duration: 600 });
    }
  };

  const startDraw = () => {
    drawing.current = true;
    drawPts.current = [];
    zipForTerritory.current = null;
    setIsCanvassDrawing(false);
    setIsDrawing(true);
    setDrawCount(0);
    updateDrawSource();
    if (mapRef.current) mapRef.current.getCanvas().style.cursor = "crosshair";
    toast.info("Click on the map to add territory corners");
  };

  const cancelDraw = () => {
    drawing.current = false;
    drawPts.current = [];
    setIsDrawing(false);
    setIsCanvassDrawing(false);
    setDrawCount(0);
    updateDrawSource();
    if (mapRef.current) mapRef.current.getCanvas().style.cursor = "";
  };

  const finishDraw = () => {
    if (drawPts.current.length < 3) { toast.error("Add at least 3 points to form a territory"); return; }
    drawing.current = false;
    setIsDrawing(false);
    if (mapRef.current) mapRef.current.getCanvas().style.cursor = "";
    setNewName("");
    setSaveOpen(true);
  };

  const saveTerritory = async () => {
    if (!newName.trim()) { toast.error("Enter a territory name"); return; }
    setSaving(true);
    const ring = [...drawPts.current, drawPts.current[0]];
    try {
      const { data } = await api.post("/territories", {
        name: newName.trim(), color: newColor,
        geometry: { type: "Polygon", coordinates: [ring] },
        zip_code: zipForTerritory.current || undefined,
      });
      toast.success("Territory created");
      setSaveOpen(false);
      drawPts.current = [];
      setDrawCount(0);
      updateDrawSource();
      const list = await loadTerritories();
      const created = list.find((t) => t.id === data.id);
      if (created) selectTerritory(created, list);
      else setTerritorySource(list, data.id);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  const deleteTerritory = async (t) => {
    if (!window.confirm(`Delete territory "${t.name}"? Imported properties are kept.`)) return;
    try {
      await api.delete(`/territories/${t.id}`);
      toast.success("Territory deleted (properties preserved)");
      if (selectedId === t.id) { setSelectedId(null); loadProperties(null); }
      const list = await loadTerritories();
      setTerritorySource(list, null);
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col md:h-screen">
      <div className="flex flex-1 overflow-hidden">
        <div className="hidden w-80 shrink-0 flex-col border-r border-border bg-white md:flex" data-testid="territory-panel">
          <div className="border-b border-border px-5 py-4">
            <h1 className="font-heading text-lg font-bold text-slate-900">Property Acquisition</h1>
            <p className="text-xs text-slate-500">Territories, imports & properties</p>
          </div>

          <div className="flex-1 overflow-y-auto">
            {mapConfig?.maptiler_configured && (
              <div className="space-y-2 border-b border-border p-4" data-testid="basemap-panel">
                <Label className="text-xs font-semibold text-slate-600">Map view</Label>
                <div className="flex gap-1 rounded-md bg-slate-100 p-1">
                  <button type="button" onClick={() => switchBase("map")}
                    className={`flex-1 rounded px-2 py-1.5 text-xs font-medium transition-colors ${baseLayer === "map" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}
                    data-testid="basemap-map-button">Street</button>
                  <button type="button" onClick={() => switchBase("satellite")} disabled={!mapConfig?.satellite_enabled}
                    className={`flex-1 rounded px-2 py-1.5 text-xs font-medium transition-colors ${baseLayer === "satellite" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"} disabled:cursor-not-allowed disabled:opacity-40`}
                    data-testid="basemap-satellite-button">Satellite</button>
                  <button type="button" onClick={() => switchBase("buildings")}
                    className={`flex-1 rounded px-2 py-1.5 text-xs font-medium transition-colors ${baseLayer === "buildings" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}
                    data-testid="basemap-buildings-button">Buildings</button>
                </div>
                {baseLayer === "buildings" && <p className="text-[11px] text-slate-500">MapTiler building footprints appear at zoom level 14 and closer.</p>}
              </div>
            )}

            <div className="space-y-2 border-b border-border p-4" data-testid="zip-search-panel">
              <Label className="text-xs font-semibold text-slate-600">Find a ZIP / postal code</Label>
              <form onSubmit={searchZip} className="flex gap-2">
                <Input value={zip} onChange={(e) => setZip(e.target.value)} placeholder="e.g. 78701" data-testid="zip-search-input" />
                <Button type="submit" variant="outline" disabled={geoLoading} data-testid="zip-search-button">
                  {geoLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <MapPin className="h-4 w-4" />}
                </Button>
              </form>
              {zipHit && <><p className="truncate text-xs text-slate-500" title={zipHit.display_name} data-testid="zip-result-name">{zipHit.display_name}</p>{canManage && !isDrawing && <Button onClick={addZipAsTerritory} variant="secondary" className="w-full" data-testid="add-zip-territory-button"><Plus className="h-4 w-4" /> Add ZIP area as territory</Button>}</>}
            </div>

            <div className="space-y-2 border-b border-border p-4" data-testid="property-filters">
              <Label className="text-xs font-semibold text-slate-600">Show properties</Label>
              <div className="flex flex-wrap gap-1">
                {[["all", "All"], ["owned", "Owned"], ["rented", "Rented"], ["unknown", "Unknown"]].map(([v, label]) => (
                  <button key={v} type="button" onClick={() => setOccFilter(v)}
                    className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${occFilter === v ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
                    data-testid={`occ-filter-${v}`}>{label}</button>
                ))}
              </div>
              <button type="button" onClick={() => setContactableOnly((v) => !v)}
                className={`flex w-full items-center justify-between rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${contactableOnly ? "border-green-600 bg-green-50 text-green-800" : "border-border bg-white text-slate-600 hover:bg-slate-50"}`}
                data-testid="contactable-toggle"><span>Contactable leads only</span><span>{contactableOnly ? "On" : "Off"}</span></button>
              <div className="pt-1 text-xs text-slate-500" data-testid="filtered-count">Showing <span className="font-semibold text-slate-800">{filteredFeatures.length}</span> of {features.length}{(occFilter !== "all" || contactableOnly) && <span> matching</span>}</div>
              <div className="flex gap-2 pt-1"><Button size="sm" variant="secondary" className="flex-1" onClick={buildRoute} disabled={filteredFeatures.length < 2} data-testid="build-route-button">Build walking route</Button>{routeInfo && <Button size="sm" variant="ghost" onClick={clearRoute} data-testid="clear-route-button">Clear</Button>}</div>
              {routeInfo && <div className="rounded-md bg-indigo-50 px-3 py-1.5 text-xs text-indigo-800" data-testid="route-info">Route: <strong>{routeInfo.stops}</strong> stops · ~<strong>{routeInfo.miles}</strong> mi walking</div>}
              {routeInfo && canManage && <Button size="sm" className="w-full" onClick={openAssign} data-testid="assign-route-button"><UserPlus className="h-4 w-4" /> Assign route to rep</Button>}
            </div>

            {canManage && !isCanvassDrawing && <div className="border-b border-border p-4">{!isDrawing ? <Button onClick={startDraw} className="w-full" data-testid="draw-territory-button"><PencilRuler className="h-4 w-4" /> Draw new territory</Button> : <div className="space-y-2"><div className="rounded-md bg-orange-50 px-3 py-2 text-xs text-orange-800">Drawing… {drawCount} point{drawCount === 1 ? "" : "s"}. Click the map to add corners.</div><div className="flex gap-2"><Button onClick={finishDraw} className="flex-1" data-testid="finish-draw-button"><Check className="h-4 w-4" /> Finish</Button><Button variant="outline" onClick={cancelDraw} data-testid="cancel-draw-button"><X className="h-4 w-4" /></Button></div></div>}</div>}

            <div className="p-2">
              {territories.length === 0 && <div className="px-3 py-6 text-center text-sm text-slate-400">No territories yet.{canManage ? " Draw one to begin." : ""}</div>}
              {territories.map((t) => (
                <div key={t.id} onClick={() => selectTerritory(t)}
                  className={`mb-1 cursor-pointer rounded-md border p-3 transition-colors ${selectedId === t.id ? "border-slate-900 bg-slate-50" : "border-transparent hover:bg-slate-50"}`}
                  data-testid={`territory-item-${t.id}`}>
                  <div className="flex items-center justify-between"><div className="flex items-center gap-2"><span className="h-3 w-3 rounded-sm" style={{ backgroundColor: t.color }} /><span className="font-medium text-slate-900">{t.name}</span></div>{canManage && <button onClick={(e) => { e.stopPropagation(); deleteTerritory(t); }} className="text-slate-300 hover:text-red-500" data-testid={`delete-territory-${t.id}`}><Trash2 className="h-4 w-4" /></button>}</div>
                  <div className="mt-1 flex items-center gap-3 text-xs text-slate-500"><span className="flex items-center gap-1"><MapPin className="h-3 w-3" /> {t.property_count} properties</span></div>
                  {selectedId === t.id && canManage && <Button size="sm" variant="outline" className="mt-2 w-full" onClick={(e) => { e.stopPropagation(); setImportOpen(true); }} data-testid="import-button"><Download className="h-4 w-4" /> Import properties</Button>}
                </div>
              ))}
            </div>
          </div>

          {selected && (
            <div className="border-t border-border px-5 py-4" data-testid="canvass-sections-panel">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Canvass Sections</span>
                {selectedSectionId && <button className="text-xs font-medium text-blue-600" onClick={clearSection} data-testid="clear-section-button">Show all</button>}
              </div>
              {sections.length === 0 ? (
                <div className="text-xs text-slate-400" data-testid="canvass-empty">No canvass sections yet. Draw a section to assign part of this territory to a salesperson.</div>
              ) : (
                <div className="space-y-1.5">
                  {sections.map((s) => (
                    <div key={s.id} className={`rounded-md border p-2 ${selectedSectionId === s.id ? "border-slate-900 bg-slate-50" : "border-border"}`} data-testid={`section-item-${s.id}`}>
                      <button className="flex w-full items-center gap-2 text-left" onClick={() => selectSection(s)} data-testid={`select-section-${s.id}`}>
                        <span className="h-3 w-3 shrink-0 rounded-sm" style={{ backgroundColor: s.color }} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium text-slate-800">{s.name}</span>
                          <span className="block text-xs text-slate-500">{s.assigned_user_name || "Unassigned"} · {s.property_count} properties</span>
                        </span>
                      </button>
                      {canManage && selectedSectionId === s.id && (
                        <div className="mt-2 flex items-center gap-2">
                          <select value={s.assigned_user_id || ""} onChange={(e) => reassignSection(s, e.target.value)} className="h-8 flex-1 rounded border border-input bg-white px-2 text-xs" data-testid={`reassign-section-${s.id}`}>
                            <option value="">Unassigned</option>
                            {reps.map((u) => <option key={u.id} value={u.id}>{u.full_name || u.email}</option>)}
                          </select>
                          <button className="text-xs font-medium text-red-600" onClick={() => deleteSection(s)} data-testid={`delete-section-${s.id}`}>Delete</button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {canManage && (isCanvassDrawing ? (
                <div className="mt-3 space-y-2">
                  <div className="rounded-md bg-blue-50 px-3 py-2 text-xs text-blue-800">Drawing section… {drawCount} point{drawCount === 1 ? "" : "s"}. Click the map.</div>
                  <div className="flex gap-2">
                    <Button onClick={finishCanvassDraw} className="flex-1" data-testid="finish-canvass-button"><Check className="h-4 w-4" /> Finish</Button>
                    <Button variant="outline" onClick={cancelDraw} data-testid="cancel-canvass-button"><X className="h-4 w-4" /></Button>
                  </div>
                </div>
              ) : (
                <Button variant="outline" className="mt-3 w-full" onClick={startCanvassDraw} data-testid="draw-canvass-button"><PencilRuler className="h-4 w-4" /> Draw Canvass Section</Button>
              ))}
            </div>
          )}
          {selected && <div className="border-t border-border px-5 py-3 text-xs text-slate-500" data-testid="selected-summary"><span className="font-semibold text-slate-700">{selected.name}</span> · {propCount} properties on map<div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1"><span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-green-600" /> Owned</span><span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-amber-600" /> Rented</span><span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-slate-500" /> Unknown</span><span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-red-600" /> Do Not Knock</span></div></div>}
        </div>

        <div className="relative flex-1"><div ref={containerRef} className="h-full w-full" data-testid="map-container" />{isDrawing && <div className="pointer-events-none absolute left-1/2 top-4 z-10 -translate-x-1/2 rounded-full bg-slate-900/90 px-4 py-1.5 text-sm text-white shadow">Click to place corners · Finish when done</div>}</div>
      </div>

      <Dialog open={saveOpen} onOpenChange={setSaveOpen}><DialogContent data-testid="save-territory-dialog"><DialogHeader><DialogTitle>Name this territory</DialogTitle><DialogDescription>Give the drawn territory a name and color.</DialogDescription></DialogHeader><div className="space-y-4"><div className="space-y-1.5"><Label>Territory name</Label><Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. North Austin" data-testid="territory-name-input" /></div><div className="space-y-1.5"><Label>Color</Label><div className="flex gap-2">{COLORS.map((c) => <button key={c} onClick={() => setNewColor(c)} className={`h-7 w-7 rounded-md border-2 ${newColor === c ? "border-slate-900" : "border-transparent"}`} style={{ backgroundColor: c }} data-testid={`color-${c}`} />)}</div></div></div><DialogFooter><Button variant="outline" onClick={() => { setSaveOpen(false); cancelDraw(); }}>Cancel</Button><Button onClick={saveTerritory} disabled={saving} data-testid="save-territory-button">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Plus className="h-4 w-4" /> Create territory</>}</Button></DialogFooter></DialogContent></Dialog>

      <Dialog open={assignOpen} onOpenChange={setAssignOpen}><DialogContent data-testid="assign-route-dialog"><DialogHeader><DialogTitle>Assign this route</DialogTitle><DialogDescription>Save the {builtRoute.length}-stop walking route and assign it to a sales rep for canvassing.</DialogDescription></DialogHeader><div className="space-y-4"><div className="space-y-1.5"><Label>Route name</Label><Input value={routeName} onChange={(e) => setRouteName(e.target.value)} placeholder="e.g. North Austin route" data-testid="route-name-input" /></div><div className="space-y-1.5"><Label>Assign to rep</Label><select value={routeRepId} onChange={(e) => setRouteRepId(e.target.value)} className="flex h-10 w-full rounded-md border border-input bg-white px-3 py-2 text-sm" data-testid="route-rep-select"><option value="">Unassigned (assign later)</option>{reps.map((u) => <option key={u.id} value={u.id}>{u.full_name || u.email} · {u.role}</option>)}</select></div><div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">{builtRoute.length} stops{routeInfo ? ` · ~${routeInfo.miles} mi walking` : ""}</div></div><DialogFooter><Button variant="outline" onClick={() => setAssignOpen(false)}>Cancel</Button><Button onClick={saveRoute} disabled={savingRoute} data-testid="save-route-button">{savingRoute ? <Loader2 className="h-4 w-4 animate-spin" /> : <><UserPlus className="h-4 w-4" /> {routeRepId ? "Assign route" : "Save route"}</>}</Button></DialogFooter></DialogContent></Dialog>

      {selected && <ImportDialog open={importOpen} onOpenChange={setImportOpen} territory={selected} onComplete={handleImportComplete} />}

      <Dialog open={canvassOpen} onOpenChange={(o) => { if (!o) { setCanvassOpen(false); cancelDraw(); } }}>
        <DialogContent data-testid="canvass-section-dialog">
          <DialogHeader><DialogTitle>New Canvass Section</DialogTitle><DialogDescription>Name it, pick a color, and assign a rep. A property may belong to only one active Canvass Section per Territory.</DialogDescription></DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-4 gap-2 text-center text-[11px] text-slate-500">
              <div className="rounded bg-slate-50 p-2"><div className="text-lg font-semibold text-slate-800" data-testid="preview-property-count">{canvassPreview?.property_count ?? 0}</div>In polygon</div>
              <div className="rounded bg-emerald-50 p-2"><div className="text-lg font-semibold text-emerald-700" data-testid="preview-available-count">{canvassPreview?.available_count ?? 0}</div>Available</div>
              <div className="rounded bg-red-50 p-2"><div className="text-lg font-semibold text-red-700" data-testid="preview-conflict-count">{canvassPreview?.conflict_count ?? 0}</div>Conflicts</div>
              <div className="rounded bg-amber-50 p-2"><div className="text-lg font-semibold text-amber-700" data-testid="preview-dnk-count">{canvassPreview?.do_not_knock_count ?? 0}</div>Do Not Knock</div>
            </div>
            {canvassPreview?.conflict_count > 0 && (
              <div className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-800" data-testid="conflict-list">
                <div className="font-semibold">Resolve the overlap before saving — these properties already belong to another section:</div>
                <ul className="mt-1 max-h-28 space-y-0.5 overflow-auto">{canvassPreview.conflicts.map((c) => <li key={c.property_id}>{c.address} → <b>{c.section_name}</b>{c.assigned_user_name ? ` (${c.assigned_user_name})` : ""}</li>)}</ul>
                <div className="mt-1">Adjust the polygon to exclude them, then draw again.</div>
              </div>
            )}
            <div className="space-y-1.5"><Label>Section name</Label><Input value={canvassName} onChange={(e) => setCanvassName(e.target.value)} placeholder="e.g. 73010 - Section A" data-testid="canvass-name-input" /></div>
            <div className="space-y-1.5"><Label>Color</Label><div className="flex gap-2">{COLORS.map((c) => <button key={c} onClick={() => setCanvassColor(c)} className={`h-7 w-7 rounded-md border-2 ${canvassColor === c ? "border-slate-900" : "border-transparent"}`} style={{ backgroundColor: c }} data-testid={`canvass-color-${c}`} />)}</div></div>
            <div className="space-y-1.5"><Label>Assigned Rep</Label><select value={canvassRepId} onChange={(e) => setCanvassRepId(e.target.value)} className="flex h-10 w-full rounded-md border border-input bg-white px-3 py-2 text-sm" data-testid="canvass-rep-select"><option value="">Unassigned</option>{reps.map((u) => <option key={u.id} value={u.id}>{u.full_name || u.email} · {u.role}</option>)}</select></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => { setCanvassOpen(false); cancelDraw(); }}>Cancel</Button><Button onClick={saveCanvassSection} disabled={savingSection || (canvassPreview?.conflict_count > 0)} data-testid="save-canvass-button">{savingSection ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Plus className="h-4 w-4" /> Create Section</>}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <PropertySheet propertyId={sheetId} open={sheetOpen} onOpenChange={setSheetOpen} onChanged={() => loadProperties(selectedId)} />
    </div>
  );
}

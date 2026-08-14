import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import * as maplibregl from "maplibre-gl";
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
    sources: { osm: { type: "raster", tiles: [OSM], tileSize: 256, attribution: "© OpenStreetMap contributors" } },
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
  const vertexMarkers = useRef([]);
  const routeMarkers = useRef([]);
  const zipForTerritory = useRef(null);
  const openSheetRef = useRef(null);

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

  const loadProperties = useCallback(async (territoryId) => {
    const map = mapRef.current;
    if (!map || !map.getSource("properties")) return;
    if (!territoryId) {
      map.getSource("properties").setData({ type: "FeatureCollection", features: [] });
      setPropCount(0);
      setFeatures([]);
      return;
    }
    try {
      const { data } = await api.get(`/properties/geojson?territory_id=${territoryId}`);
      map.getSource("properties").setData(data);
      setPropCount(data.features.length);
      setFeatures(data.features || []);
    } catch (e) {
      toast.error(apiError(e));
    }
  }, []);

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
    // Numbered corner markers are for hand-drawn territories. A snapped ZIP boundary can have hundreds
    // of vertices, so past a small count we show only the outline (the draw-line/fill layers).
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

  // init map once
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
        // Satellite tiles are proxied through the local backend (key stays server-side) and require the
        // auth token; map raster requests bypass our axios interceptor, so attach the Bearer here.
        transformRequest: (url) => {
          if (url.includes("/map/tiles/satellite/")) {
            return { url, headers: { Authorization: `Bearer ${getToken()}` } };
          }
          return { url };
        },
      });
      map.addControl(new maplibregl.NavigationControl(), "top-right");
      mapRef.current = map;

      map.on("load", () => {
        // Satellite base (MapTiler via backend proxy), added first so territory/property/draw layers
        // stack on top. Visibility follows the saved default; the on-map toggle switches osm <-> satellite.
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
        }

        map.addSource("territories", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "terr-fill", type: "fill", source: "territories", paint: { "fill-color": ["get", "color"], "fill-opacity": ["case", ["get", "selected"], 0.18, 0.06] } });
        map.addLayer({ id: "terr-line", type: "line", source: "territories", paint: { "line-color": ["get", "color"], "line-width": ["case", ["get", "selected"], 3, 1.5] } });

        map.addSource("properties", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({
          id: "prop-points", type: "circle", source: "properties",
          paint: {
            "circle-radius": 8,
            // Do-not-knock always shows red; otherwise color by occupancy so sales can read the map:
            // owned = green (talk to the homeowner), rented = amber, unknown = gray.
            "circle-color": [
              "case",
              ["get", "do_not_knock"], "#DC2626",
              ["==", ["get", "occupancy"], "owned"], "#16A34A",
              ["==", ["get", "occupancy"], "rented"], "#D97706",
              "#64748B",
            ],
            "circle-stroke-color": "#ffffff", "circle-stroke-width": 2,
          },
        });
        // Larger invisible hit target for easier clicking / touch (accessibility)
        map.addLayer({
          id: "prop-hit", type: "circle", source: "properties",
          paint: { "circle-radius": 16, "circle-color": "#000000", "circle-opacity": 0 },
        });

        map.addSource("draw", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "draw-fill", type: "fill", source: "draw", paint: { "fill-color": "#EA580C", "fill-opacity": 0.15 } });
        map.addLayer({ id: "draw-line", type: "line", source: "draw", paint: { "line-color": "#EA580C", "line-width": 2, "line-dasharray": [2, 1] } });
        map.addSource("draw-pts", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "draw-vertices", type: "circle", source: "draw-pts", paint: { "circle-radius": 7, "circle-color": "#EA580C", "circle-stroke-color": "#fff", "circle-stroke-width": 2.5 } });

        // Walking-route line (built from the filtered contactable/owner set)
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
        map.on("click", "prop-points", (e) => {
          if (drawing.current) return;
          const id = e.features?.[0]?.properties?.id;
          if (id && openSheetRef.current) openSheetRef.current(id);
        });
        map.on("click", "prop-hit", (e) => {
          if (drawing.current) return;
          const id = e.features?.[0]?.properties?.id;
          if (id && openSheetRef.current) openSheetRef.current(id);
        });
        map.on("mouseenter", "prop-hit", () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", "prop-hit", () => { map.getCanvas().style.cursor = ""; });

        loadTerritories().then((list) => setTerritorySource(list, null));
      });
    });
    return () => {
      if (mapRef.current) { mapRef.current.remove(); mapRef.current = null; }
    };
  }, [loadTerritories, setTerritorySource, updateDrawSource]);

  openSheetRef.current = (id) => { setSheetId(id); setSheetOpen(true); };

  const selectTerritory = (t) => {
    setSelectedId(t.id);
    setTerritorySource(territories, t.id);
    fitToTerritory(t);
    loadProperties(t.id);
  };

  const applyPropFilter = useCallback(() => {
    const map = mapRef.current;
    if (!map || !map.getLayer("prop-points")) return;
    const clauses = ["all"];
    if (occFilter !== "all") clauses.push(["==", ["get", "occupancy"], occFilter]);
    if (contactableOnly) clauses.push(["==", ["get", "contactable"], true]);
    const f = clauses.length > 1 ? clauses : null;
    map.setFilter("prop-points", f);
    if (map.getLayer("prop-hit")) map.setFilter("prop-hit", f);
  }, [occFilter, contactableOnly]);

  useEffect(() => { applyPropFilter(); }, [applyPropFilter]);

  const filteredFeatures = useMemo(() => features.filter((f) => {
    const p = f.properties || {};
    if (occFilter !== "all" && p.occupancy !== occFilter) return false;
    if (contactableOnly && !p.contactable) return false;
    return true;
  }), [features, occFilter, contactableOnly]);

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
    // Nearest-neighbour walking order starting from the western-most stop.
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
        name: routeName.trim(),
        territory_id: selectedId || null,
        assigned_user_id: routeRepId || null,
        est_miles: routeInfo ? Number(routeInfo.miles) : 0,
        stops: builtRoute,
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
    setBaseLayer(layer);
    if (map.getLayer("satellite-layer")) {
      map.setLayoutProperty("satellite-layer", "visibility", layer === "satellite" ? "visible" : "none");
    }
    if (map.getLayer("osm")) {
      map.setLayoutProperty("osm", "visibility", layer === "satellite" ? "none" : "visible");
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
    if (geom && geom.type === "Polygon" && geom.coordinates?.[0]?.length >= 3) {
      ring = geom.coordinates[0];
    } else if (geom && geom.type === "MultiPolygon" && geom.coordinates?.length) {
      ring = geom.coordinates.map((poly) => poly[0]).sort((a, b) => b.length - a.length)[0];  // largest ring
    }
    if (!ring || ring.length < 3) {
      ring = [[w, s], [e2, s], [e2, n], [w, n]];  // fallback: bbox rectangle when no boundary available
      toast.info("No exact boundary for this ZIP — added its area as an editable rectangle.");
    } else {
      toast.info("Snapped the ZIP boundary. Review and click Finish to name & save.");
    }
    if (ring.length > 1) {  // drop the closing duplicate vertex (save re-closes the ring)
      const a = ring[0], b = ring[ring.length - 1];
      if (a[0] === b[0] && a[1] === b[1]) ring = ring.slice(0, -1);
    }
    drawPts.current = ring.map((c) => [c[0], c[1]]);
    zipForTerritory.current = (zip || "").trim() || null;  // remember the ZIP for an exact RentCast pull
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
    zipForTerritory.current = null;  // a hand-drawn territory is not tied to a ZIP
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
    setDrawCount(0);
    updateDrawSource();
    if (mapRef.current) mapRef.current.getCanvas().style.cursor = "";
  };

  const finishDraw = () => {
    if (drawPts.current.length < 3) {
      toast.error("Add at least 3 points to form a territory");
      return;
    }
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
      setTerritorySource(list, data.id);
      const created = list.find((t) => t.id === data.id);
      if (created) selectTerritory(created);
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
        {/* Left panel */}
        <div className="hidden w-80 shrink-0 flex-col border-r border-border bg-white md:flex" data-testid="territory-panel">
          <div className="border-b border-border px-5 py-4">
            <h1 className="font-heading text-lg font-bold text-slate-900">Property Acquisition</h1>
            <p className="text-xs text-slate-500">Territories, imports & properties</p>
          </div>

          <div className="flex-1 overflow-y-auto">
            {/* Base layer toggle (only when MapTiler satellite is configured) */}
            {mapConfig?.maptiler_configured && (
              <div className="space-y-2 border-b border-border p-4" data-testid="basemap-panel">
                <Label className="text-xs font-semibold text-slate-600">Base map</Label>
                <div className="flex gap-1 rounded-md bg-slate-100 p-1">
                  <button
                    type="button"
                    onClick={() => switchBase("map")}
                    className={`flex-1 rounded px-3 py-1.5 text-xs font-medium transition-colors ${baseLayer === "map" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}
                    data-testid="basemap-map-button"
                  >
                    Street
                  </button>
                  <button
                    type="button"
                    onClick={() => switchBase("satellite")}
                    className={`flex-1 rounded px-3 py-1.5 text-xs font-medium transition-colors ${baseLayer === "satellite" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}
                    data-testid="basemap-satellite-button"
                  >
                    Satellite
                  </button>
                </div>
              </div>
            )}

            {/* ZIP / postal code search */}
            <div className="space-y-2 border-b border-border p-4" data-testid="zip-search-panel">
              <Label className="text-xs font-semibold text-slate-600">Find a ZIP / postal code</Label>
              <form onSubmit={searchZip} className="flex gap-2">
                <Input value={zip} onChange={(e) => setZip(e.target.value)} placeholder="e.g. 78701" data-testid="zip-search-input" />
                <Button type="submit" variant="outline" disabled={geoLoading} data-testid="zip-search-button">
                  {geoLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <MapPin className="h-4 w-4" />}
                </Button>
              </form>
              {zipHit && (
                <>
                  <p className="truncate text-xs text-slate-500" title={zipHit.display_name} data-testid="zip-result-name">{zipHit.display_name}</p>
                  {canManage && !isDrawing && (
                    <Button onClick={addZipAsTerritory} variant="secondary" className="w-full" data-testid="add-zip-territory-button">
                      <Plus className="h-4 w-4" /> Add ZIP area as territory
                    </Button>
                  )}
                </>
              )}
            </div>

            {/* Property filters — focus reps on homeowners / contactable leads */}
            <div className="space-y-2 border-b border-border p-4" data-testid="property-filters">
              <Label className="text-xs font-semibold text-slate-600">Show properties</Label>
              <div className="flex flex-wrap gap-1">
                {[["all", "All"], ["owned", "Owned"], ["rented", "Rented"], ["unknown", "Unknown"]].map(([v, label]) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setOccFilter(v)}
                    className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${occFilter === v ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
                    data-testid={`occ-filter-${v}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => setContactableOnly((v) => !v)}
                className={`flex w-full items-center justify-between rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${contactableOnly ? "border-green-600 bg-green-50 text-green-800" : "border-border bg-white text-slate-600 hover:bg-slate-50"}`}
                data-testid="contactable-toggle"
              >
                <span>Contactable leads only</span>
                <span>{contactableOnly ? "On" : "Off"}</span>
              </button>
              <div className="pt-1 text-xs text-slate-500" data-testid="filtered-count">
                Showing <span className="font-semibold text-slate-800">{filteredFeatures.length}</span> of {features.length}
                {(occFilter !== "all" || contactableOnly) && <span> matching</span>}
              </div>
              <div className="flex gap-2 pt-1">
                <Button size="sm" variant="secondary" className="flex-1" onClick={buildRoute}
                  disabled={filteredFeatures.length < 2} data-testid="build-route-button">
                  Build walking route
                </Button>
                {routeInfo && (
                  <Button size="sm" variant="ghost" onClick={clearRoute} data-testid="clear-route-button">Clear</Button>
                )}
              </div>
              {routeInfo && (
                <div className="rounded-md bg-indigo-50 px-3 py-1.5 text-xs text-indigo-800" data-testid="route-info">
                  Route: <strong>{routeInfo.stops}</strong> stops · ~<strong>{routeInfo.miles}</strong> mi walking
                </div>
              )}
              {routeInfo && canManage && (
                <Button size="sm" className="w-full" onClick={openAssign} data-testid="assign-route-button">
                  <UserPlus className="h-4 w-4" /> Assign route to rep
                </Button>
              )}
            </div>


            {/* Draw controls */}
            {canManage && (
              <div className="border-b border-border p-4">
                {!isDrawing ? (
                  <Button onClick={startDraw} className="w-full" data-testid="draw-territory-button">
                    <PencilRuler className="h-4 w-4" /> Draw new territory
                  </Button>
                ) : (
                  <div className="space-y-2">
                    <div className="rounded-md bg-orange-50 px-3 py-2 text-xs text-orange-800">Drawing… {drawCount} point{drawCount === 1 ? "" : "s"}. Click the map to add corners.</div>
                    <div className="flex gap-2">
                      <Button onClick={finishDraw} className="flex-1" data-testid="finish-draw-button"><Check className="h-4 w-4" /> Finish</Button>
                      <Button variant="outline" onClick={cancelDraw} data-testid="cancel-draw-button"><X className="h-4 w-4" /></Button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Territory list */}
            <div className="p-2">
              {territories.length === 0 && (
                <div className="px-3 py-6 text-center text-sm text-slate-400">No territories yet.{canManage ? " Draw one to begin." : ""}</div>
              )}
              {territories.map((t) => (
                <div
                  key={t.id}
                  onClick={() => selectTerritory(t)}
                  className={`mb-1 cursor-pointer rounded-md border p-3 transition-colors ${selectedId === t.id ? "border-slate-900 bg-slate-50" : "border-transparent hover:bg-slate-50"}`}
                  data-testid={`territory-item-${t.id}`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="h-3 w-3 rounded-sm" style={{ backgroundColor: t.color }} />
                      <span className="font-medium text-slate-900">{t.name}</span>
                    </div>
                    {canManage && (
                      <button onClick={(e) => { e.stopPropagation(); deleteTerritory(t); }} className="text-slate-300 hover:text-red-500" data-testid={`delete-territory-${t.id}`}>
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                  <div className="mt-1 flex items-center gap-3 text-xs text-slate-500">
                    <span className="flex items-center gap-1"><MapPin className="h-3 w-3" /> {t.property_count} properties</span>
                  </div>
                  {selectedId === t.id && canManage && (
                    <Button size="sm" variant="outline" className="mt-2 w-full" onClick={(e) => { e.stopPropagation(); setImportOpen(true); }} data-testid="import-button">
                      <Download className="h-4 w-4" /> Import properties
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </div>

          {selected && (
            <div className="border-t border-border px-5 py-3 text-xs text-slate-500" data-testid="selected-summary">
              <span className="font-semibold text-slate-700">{selected.name}</span> · {propCount} properties on map
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-green-600" /> Owned</span>
                <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-amber-600" /> Rented</span>
                <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-slate-500" /> Unknown</span>
                <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-red-600" /> Do Not Knock</span>
              </div>
            </div>
          )}
        </div>

        {/* Map */}
        <div className="relative flex-1">
          <div ref={containerRef} className="h-full w-full" data-testid="map-container" />
          {isDrawing && (
            <div className="pointer-events-none absolute left-1/2 top-4 z-10 -translate-x-1/2 rounded-full bg-slate-900/90 px-4 py-1.5 text-sm text-white shadow">
              Click to place corners · Finish when done
            </div>
          )}
        </div>
      </div>

      {/* Save territory dialog */}
      <Dialog open={saveOpen} onOpenChange={setSaveOpen}>
        <DialogContent data-testid="save-territory-dialog">
          <DialogHeader><DialogTitle>Name this territory</DialogTitle><DialogDescription>Give the drawn territory a name and color.</DialogDescription></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label>Territory name</Label>
              <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. North Austin" data-testid="territory-name-input" />
            </div>
            <div className="space-y-1.5">
              <Label>Color</Label>
              <div className="flex gap-2">
                {COLORS.map((c) => (
                  <button key={c} onClick={() => setNewColor(c)} className={`h-7 w-7 rounded-md border-2 ${newColor === c ? "border-slate-900" : "border-transparent"}`} style={{ backgroundColor: c }} data-testid={`color-${c}`} />
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setSaveOpen(false); cancelDraw(); }}>Cancel</Button>
            <Button onClick={saveTerritory} disabled={saving} data-testid="save-territory-button">
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Plus className="h-4 w-4" /> Create territory</>}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={assignOpen} onOpenChange={setAssignOpen}>
        <DialogContent data-testid="assign-route-dialog">
          <DialogHeader>
            <DialogTitle>Assign this route</DialogTitle>
            <DialogDescription>Save the {builtRoute.length}-stop walking route and assign it to a sales rep for canvassing.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label>Route name</Label>
              <Input value={routeName} onChange={(e) => setRouteName(e.target.value)} placeholder="e.g. North Austin route" data-testid="route-name-input" />
            </div>
            <div className="space-y-1.5">
              <Label>Assign to rep</Label>
              <select
                value={routeRepId}
                onChange={(e) => setRouteRepId(e.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-white px-3 py-2 text-sm"
                data-testid="route-rep-select"
              >
                <option value="">Unassigned (assign later)</option>
                {reps.map((u) => (
                  <option key={u.id} value={u.id}>{u.full_name || u.email} · {u.role}</option>
                ))}
              </select>
            </div>
            <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">
              {builtRoute.length} stops{routeInfo ? ` · ~${routeInfo.miles} mi walking` : ""}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssignOpen(false)}>Cancel</Button>
            <Button onClick={saveRoute} disabled={savingRoute} data-testid="save-route-button">
              {savingRoute ? <Loader2 className="h-4 w-4 animate-spin" /> : <><UserPlus className="h-4 w-4" /> {routeRepId ? "Assign route" : "Save route"}</>}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {selected && (
        <ImportDialog open={importOpen} onOpenChange={setImportOpen} territory={selected} onComplete={() => loadProperties(selectedId)} />
      )}
      <PropertySheet propertyId={sheetId} open={sheetOpen} onOpenChange={setSheetOpen} onChanged={() => loadProperties(selectedId)} />
    </div>
  );
}

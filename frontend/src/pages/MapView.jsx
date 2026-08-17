import { useEffect, useRef, useState, useCallback } from "react";
import * as maplibregl from "maplibre-gl";
import Supercluster from "supercluster";
import "maplibre-gl/dist/maplibre-gl.css";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import ImportDialog from "@/components/ImportDialog";
import PropertySheet from "@/components/PropertySheet";
import { PencilRuler, Download, Trash2, MapPin, Ban, Check, X, Plus, Loader2 } from "lucide-react";

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

  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const loadedRef = useRef(false);
  const drawing = useRef(false);
  const drawPts = useRef([]);
  const openSheetRef = useRef(null);
  const superRef = useRef(null);
  const markersRef = useRef([]);
  const clusterZoomMax = 16;

  const [territories, setTerritories] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [propCount, setPropCount] = useState(0);
  const [isDrawing, setIsDrawing] = useState(false);
  const [drawCount, setDrawCount] = useState(0);
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

  const clearMarkers = useCallback(() => {
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];
  }, []);

  // Main-thread clustering (supercluster) rendered with HTML DOM markers. We do NOT use a MapLibre
  // geojson source/layer for property pins because the geojson worker does not reliably tile the
  // 'properties' source in this webpack build. DOM markers (maplibregl.Marker) always render.
  const renderClusters = useCallback(() => {
    const map = mapRef.current;
    const index = superRef.current;
    clearMarkers();
    if (!map || !index) return;
    const b = map.getBounds();
    const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
    const zoom = Math.round(map.getZoom());
    const features = index.getClusters(bbox, zoom);
    for (const f of features) {
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
        el.setAttribute("data-testid", "map-property-pin");
        el.style.cssText = `width:16px;height:16px;background:${dnk ? "#DC2626" : "#2563EB"};border:2px solid #fff;border-radius:9999px;cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.35)`;
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
      return;
    }
    try {
      const { data } = await api.get(`/properties/geojson?territory_id=${territoryId}`);
      const feats = (data.features || []).filter((f) => f?.geometry?.type === "Point");
      const index = new Supercluster({ radius: 55, maxZoom: clusterZoomMax });
      index.load(feats);
      superRef.current = index;
      setPropCount(feats.length);
      renderClusters();
    } catch (e) {
      toast.error(apiError(e));
    }
  }, [renderClusters, clearMarkers]);

  const fitToTerritory = useCallback((t) => {
    const map = mapRef.current;
    if (!map || !t) return;
    const b = new maplibregl.LngLatBounds();
    t.geometry.coordinates[0].forEach((c) => b.extend(c));
    map.fitBounds(b, { padding: 60, maxZoom: 15, duration: 600 });
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
  }, []);

  // init map once
  useEffect(() => {
    api.get("/map-config").then(({ data }) => {
      if (mapRef.current || !containerRef.current) return;
      const map = new maplibregl.Map({
        container: containerRef.current,
        style: baseStyle(),
        center: data.default_center,
        zoom: data.default_zoom,
        maxZoom: 19,
      });
      map.addControl(new maplibregl.NavigationControl(), "top-right");
      mapRef.current = map;

      // Surface any MapLibre errors (style/source/layer/tile) that would otherwise fail silently.
      map.on("error", (e) => {
        // eslint-disable-next-line no-console
        console.error("[MapLibre error]", (e && e.error) || e);
      });

      const initMapLayers = () => {
        // Guard: never add sources/layers before the style is ready.
        if (!map.isStyleLoaded()) {
          // eslint-disable-next-line no-console
          console.warn("[MapView] initMapLayers called before style loaded — deferring");
          map.once("load", initMapLayers);
          return;
        }
        if (map.getLayer("draw-vertices")) return; // already initialized (idempotent)

        if (!map.getSource("territories")) map.addSource("territories", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        if (!map.getLayer("terr-fill")) map.addLayer({ id: "terr-fill", type: "fill", source: "territories", paint: { "fill-color": ["get", "color"], "fill-opacity": ["case", ["get", "selected"], 0.18, 0.06] } });
        if (!map.getLayer("terr-line")) map.addLayer({ id: "terr-line", type: "line", source: "territories", paint: { "line-color": ["get", "color"], "line-width": ["case", ["get", "selected"], 3, 1.5] } });

        // NOTE: property clusters/points are rendered as HTML DOM markers (see renderClusters), NOT as a
        // geojson source+layer. In this webpack build the geojson worker does not reliably tile the
        // 'properties' source, so DOM markers (maplibregl.Marker) are used to guarantee rendering.

        if (!map.getSource("draw")) map.addSource("draw", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        if (!map.getLayer("draw-fill")) map.addLayer({ id: "draw-fill", type: "fill", source: "draw", paint: { "fill-color": "#EA580C", "fill-opacity": 0.15 } });
        if (!map.getLayer("draw-line")) map.addLayer({ id: "draw-line", type: "line", source: "draw", paint: { "line-color": "#EA580C", "line-width": 2, "line-dasharray": [2, 1] } });
        if (!map.getSource("draw-pts")) map.addSource("draw-pts", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        if (!map.getLayer("draw-vertices")) map.addLayer({ id: "draw-vertices", type: "circle", source: "draw-pts", paint: { "circle-radius": 4, "circle-color": "#EA580C", "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 } });

        loadedRef.current = true;

        map.on("click", (e) => {
          if (drawing.current) {
            drawPts.current = [...drawPts.current, [e.lngLat.lng, e.lngLat.lat]];
            updateDrawSource();
            setDrawCount(drawPts.current.length);
          }
        });

        // Re-cluster (and re-place DOM markers) for the new viewport whenever the map settles.
        map.on("moveend", () => renderClusters());

        loadTerritories().then((list) => setTerritorySource(list, null));
      };

      // Only add sources/layers once the style is ready: use the load event, or run
      // immediately if the style is already loaded (e.g. cached/fast init).
      if (map.isStyleLoaded()) initMapLayers();
      else map.on("load", initMapLayers);
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

  const startDraw = () => {
    drawing.current = true;
    drawPts.current = [];
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
              <span className="ml-2 inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-red-600" /> Do Not Knock</span>
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

      {selected && (
        <ImportDialog open={importOpen} onOpenChange={setImportOpen} territory={selected} onComplete={() => loadProperties(selectedId)} />
      )}
      <PropertySheet propertyId={sheetId} open={sheetOpen} onOpenChange={setSheetOpen} onChanged={() => loadProperties(selectedId)} />
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { api, getToken, BACKEND_URL } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Layers, Map as MapIcon } from "lucide-react";

function buildStyle(cfg, mode) {
  if (mode === "satellite") {
    return {
      version: 8,
      sources: {
        sat: {
          type: "raster",
          tiles: [`${BACKEND_URL}/api/map/tiles/satellite/{z}/{x}/{y}`],
          tileSize: 256,
          attribution: "© MapTiler © OpenStreetMap contributors",
        },
      },
      layers: [{ id: "sat", type: "raster", source: "sat" }],
    };
  }
  return {
    version: 8,
    sources: {
      osm: { type: "raster", tiles: [cfg.osm_tile_url], tileSize: 256, attribution: cfg.attribution },
    },
    layers: [{ id: "osm", type: "raster", source: "osm" }],
  };
}

export default function MapView() {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const [cfg, setCfg] = useState(null);
  const [mode, setMode] = useState("street");

  useEffect(() => {
    api.get("/map-config").then((r) => setCfg(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!cfg || !containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: buildStyle(cfg, "street"),
      center: cfg.default_center,
      zoom: cfg.default_zoom,
      transformRequest: (url) => {
        if (url.startsWith(`${BACKEND_URL}/api/`)) {
          return { url, headers: { Authorization: `Bearer ${getToken()}` } };
        }
        return { url };
      },
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [cfg]);

  const switchMode = (next) => {
    if (!mapRef.current || !cfg) return;
    setMode(next);
    mapRef.current.setStyle(buildStyle(cfg, next));
  };

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col md:h-screen">
      <PageHeader
        title="Property Map"
        description="OpenStreetMap base layer. Satellite imagery requires a MapTiler key."
        testid="page-map"
        actions={
          <div className="flex overflow-hidden rounded-md border border-border">
            <Button
              variant={mode === "street" ? "default" : "ghost"}
              size="sm"
              className="rounded-none"
              onClick={() => switchMode("street")}
              data-testid="map-mode-street"
            >
              <MapIcon className="h-4 w-4" /> Street
            </Button>
            <Button
              variant={mode === "satellite" ? "default" : "ghost"}
              size="sm"
              className="rounded-none"
              disabled={!cfg?.maptiler_configured}
              onClick={() => switchMode("satellite")}
              data-testid="map-mode-satellite"
              title={cfg?.maptiler_configured ? "Satellite" : "Add a MapTiler key in Settings to enable satellite"}
            >
              <Layers className="h-4 w-4" /> Satellite
            </Button>
          </div>
        }
      />
      <div className="relative flex-1">
        <div ref={containerRef} className="h-full w-full" data-testid="map-container" />
      </div>
    </div>
  );
}

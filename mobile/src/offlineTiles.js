// Offline map prefetch for the RoofSpan Field app.
//
// Downloads the rep's current canvass section (street + satellite) into a MapLibre offline pack so the
// area's imagery stays available with no signal. Uses the SAME stable relay tile URLs + global ticket
// header as the live map, so packs and live tiles share the ambient/offline stores.
import * as FileSystem from "expo-file-system";

// Bounding box [[neLng,neLat],[swLng,swLat]] for a section polygon ring.
export function sectionBounds(section) {
  const ring = section?.geometry?.coordinates?.[0];
  if (!Array.isArray(ring) || ring.length < 3) return null;
  let minLng = 180, minLat = 90, maxLng = -180, maxLat = -90;
  for (const c of ring) {
    const lng = Number(c[0]); const lat = Number(c[1]);
    if (!Number.isFinite(lng) || !Number.isFinite(lat)) continue;
    if (lng < minLng) minLng = lng; if (lng > maxLng) maxLng = lng;
    if (lat < minLat) minLat = lat; if (lat > maxLat) maxLat = lat;
  }
  if (minLng > maxLng || minLat > maxLat) return null;
  return [[maxLng, maxLat], [minLng, minLat]];
}

function packStyle(osmTileUrl, satelliteUrl) {
  return {
    version: 8,
    sources: {
      osm: { type: "raster", tiles: [osmTileUrl], tileSize: 256 },
      satellite: { type: "raster", tiles: [satelliteUrl], tileSize: 512 },
    },
    layers: [
      { id: "osm", type: "raster", source: "osm" },
      { id: "satellite", type: "raster", source: "satellite" },
    ],
  };
}

// Download (or refresh) an offline pack for a section. onProgress receives 0..100.
export async function downloadSectionArea({ MapLibre, section, osmTileUrl, satelliteUrl, onProgress }) {
  if (!MapLibre || !MapLibre.offlineManager) throw new Error("offline manager unavailable");
  const bounds = sectionBounds(section);
  if (!bounds) throw new Error("section has no area");

  const name = `rs-area-${section.id}`;
  const stylePath = `${FileSystem.cacheDirectory}${name}.style.json`;
  await FileSystem.writeAsStringAsync(stylePath, JSON.stringify(packStyle(osmTileUrl, satelliteUrl)));

  const om = MapLibre.offlineManager;
  try { await om.deletePack(name); } catch (e) { /* no existing pack */ }

  return await new Promise((resolve, reject) => {
    om.createPack(
      { name, styleURL: stylePath, bounds, minZoom: 13, maxZoom: 18 },
      (_pack, status) => {
        if (onProgress && status) onProgress(Math.round(status.percentage || 0));
        if (status && status.percentage >= 100) resolve(status);
      },
      (_pack, err) => reject(err instanceof Error ? err : new Error(String(err))),
    ).catch(reject);
  });
}

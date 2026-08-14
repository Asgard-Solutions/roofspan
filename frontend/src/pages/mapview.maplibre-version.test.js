import mlpkg from "maplibre-gl/package.json";

// Regression guard for the "Map shows 0 property points" bug.
//
// Root cause: MapLibre GL JS v6 is ESM-only and requires an explicit `setWorkerUrl` for bundlers
// (CRA/webpack). Without it the GeoJSON tiling Web Worker never starts, so raster tiles render but
// EVERY geojson source (territories, properties, draw, route) stays permanently "not loaded" and no
// property circles appear — even though React holds all the features. v5 auto-bundles its worker in
// CRA and does not need setWorkerUrl.
//
// Keep MapLibre on v5 (or, if upgrading to v6+, wire up maplibregl.setWorkerUrl and re-verify that
// geojson points actually render before changing this test).
test("maplibre-gl stays on a CRA-worker-safe major (v5)", () => {
  const major = Number(String(mlpkg.version).split(".")[0]);
  expect(Number.isFinite(major)).toBe(true);
  expect(major).toBe(5);
});

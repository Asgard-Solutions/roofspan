import { setWorkerUrl } from "maplibre-gl";

// Served by the same Office backend as the UI, including when installed offline.
setWorkerUrl(`${process.env.PUBLIC_URL}/static/maplibre/maplibre-gl-worker.mjs`);

export * from "maplibre-gl";

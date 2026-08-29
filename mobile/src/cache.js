// Read-through cache facade for salesperson field data. Try RoofSpan Office first; on success cache
// the fresh copy; on any failure fall back to the last scoped cache so the app stays usable offline.
// Returns { data, stale } — `stale:true` means the value came from cache, not Office.
import { api } from "./api";
import { putCache, getCache, getCacheMeta, putCacheSerialized } from "./storage";
const measurementKeys = require("./measurementCache");
const sketchKeys = require("./sketchCache");

async function readThrough(name, fetcher) {
  try {
    const r = await fetcher();
    const data = r && r.data;
    if (data !== undefined && data !== null) await putCache(name, data);
    return { data, stale: false };
  } catch (e) {
    const cached = await getCache(name);
    const meta = await getCacheMeta(name);
    return { data: cached, stale: true, cachedAt: meta && meta.updated_at, error: e };
  }
}

export const cache = {
  leads: () => readThrough("leads", () => api.get("/mobile/leads")),
  lead: (id) => readThrough(`lead:${id}`, () => api.get(`/mobile/leads/${id}`)),
  jobs: () => readThrough("jobs", () => api.get("/mobile/jobs")),
  job: (id) => readThrough(`job:${id}`, () => api.get(`/mobile/jobs/${id}`)),
  sections: () => readThrough("sections", () => api.get("/mobile/canvass-sections")),
  sectionProperties: (id) => readThrough(`section:${id}:props`, () => api.get(`/mobile/canvass-sections/${id}/properties`)),
  property: (id) => readThrough(`property:${id}`, () => api.get(`/mobile/properties/${id}`)),
  mapConfig: () => readThrough("mapcfg", () => api.get("/map-config")),
  measurements: (scope) => readThrough(
    measurementKeys.scopeKey(scope),
    () => api.get("/mobile/measurements", { params: scope || {} }),
  ),
  measurement: (id) => readThrough(
    measurementKeys.detailKey(id),
    () => api.get(`/mobile/measurements/${id}`),
  ),
  // Read-through the current server sketch for a structure; falls back to the last cached copy offline.
  sketch: (revisionId, structureId) => readThrough(
    sketchKeys.sketchDetailKey(revisionId, structureId),
    () => api.get(`/mobile/measurements/${revisionId}/sketches/${structureId}`),
  ),
};

// Persist the latest sketch draft locally BEFORE queueing, so a crash after an edit cannot lose it.
export async function saveSketchDraft(revisionId, structureId, draft) {
  try { await putCache(sketchKeys.sketchDraftKey(revisionId, structureId), draft); } catch (e) { /* best effort */ }
}
// Strict variant for the Roof Sketch editor: local durability IS the B2A persistence contract, so a
// storage failure must PROPAGATE (the controller records it and the screen shows an honest status).
// Uses the SERIALIZED write so an editor draft write (generation C) and an acknowledgement
// reconciliation are mutually serialized against the same scoped draft key (B3B1 atomicity).
export async function saveSketchDraftStrict(revisionId, structureId, draft) {
  await putCacheSerialized(sketchKeys.sketchDraftKey(revisionId, structureId), draft);
}
export async function loadSketchDraft(revisionId, structureId) {
  try { return await getCache(sketchKeys.sketchDraftKey(revisionId, structureId)); } catch (e) { return null; }
}
export async function clearSketchDraft(revisionId, structureId) {
  try { await putCacheSerialized(sketchKeys.sketchDraftKey(revisionId, structureId), null); } catch (e) { /* best effort */ }
}
export async function cacheSketchDetail(revisionId, structureId, sketch) {
  try { await putCache(sketchKeys.sketchDetailKey(revisionId, structureId), sketch); } catch (e) { /* best effort */ }
}

export async function cacheMeasurementDetail(revision) {
  if (!revision || !revision.id) return;
  try { await putCache(measurementKeys.detailKey(revision.id), revision); } catch (e) { /* best effort */ }
}

export async function loadMeasurementDraft(scope) {
  try { return await getCache(measurementKeys.draftKey(scope)); } catch (e) { return null; }
}

export async function saveMeasurementDraft(scope, draft) {
  try { await putCache(measurementKeys.draftKey(scope), draft); } catch (e) { /* durable cache best effort */ }
}

export async function clearMeasurementDraft(scope) {
  try { await putCache(measurementKeys.draftKey(scope), null); } catch (e) { /* best effort */ }
}

// Optimistic local write-through: patch a cached list/detail immediately so the UI reflects a queued
// offline change before Office acknowledges it. Never throws.
export async function patchCachedList(name, id, patch) {
  try {
    const list = (await getCache(name)) || [];
    const next = list.map((row) => (row && row.id === id ? { ...row, ...patch } : row));
    await putCache(name, next);
  } catch (e) { /* cache is best-effort */ }
}

export async function patchCachedDetail(name, patch) {
  try {
    const cur = (await getCache(name)) || {};
    await putCache(name, { ...cur, ...patch });
  } catch (e) { /* best-effort */ }
}

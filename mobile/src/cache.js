// Read-through cache facade for salesperson field data. Try RoofSpan Office first; on success cache
// the fresh copy; on any failure fall back to the last scoped cache so the app stays usable offline
// (spec §14). Returns { data, stale } — `stale:true` means the value came from cache, not Office.
import { api } from "./api";
import { putCache, getCache, getCacheMeta } from "./storage";

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
};

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

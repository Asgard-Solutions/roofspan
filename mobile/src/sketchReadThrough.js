"use strict";
// Roof-sketch GET read-through with the sketch-SPECIFIC 404 contract. The backend returns HTTP 404 for a
// structure that has never had a sketch ("No sketch for this structure yet"). That is an AUTHORITATIVE
// empty state — NOT a load failure — and must be modelled distinctly so the viewer can offer first-time
// sketch creation instead of a retryable error screen.
//
// This 404 handling is specific to the roof-sketch GET; it is NOT a generic "treat every 404 as success".
//
// Envelope shapes returned:
//   existing sketch (HTTP 200): { data:<sketch>, stale:false, notFound:false, error:null }
//   authoritative 404:          { data:null,     stale:false, notFound:true,  error:null }
//   network/relay failure + cache: { data:<cached>, stale:true, notFound:false, cachedAt, error }
//   network/relay failure, no cache: { data:null, stale:true, notFound:false, error }
//
// An authoritative 404 also RETIRES any obsolete cached sketch (clearCache) so a later offline read can
// never resurrect a deleted/never-existed sketch as though it still exists — it represents current Office
// state (no sketch). Dependencies are injected so this runs and is tested in pure Node against the REAL
// api.get() error shape (Error with e.response.status).
async function readThroughSketch({ fetcher, getCache, getCacheMeta, putCache, clearCache, name } = {}) {
  try {
    const r = await fetcher();
    const data = r && r.data != null ? r.data : null;
    if (data != null) { try { await putCache(name, data); } catch (e) { /* best effort */ } }
    return { data, stale: false, notFound: false, error: null };
  } catch (e) {
    // AUTHORITATIVE "no sketch yet": a real HTTP 404 response reached us (never a transport/network error).
    if (e && e.response && e.response.status === 404) {
      try { await clearCache(name); } catch (_) { /* best effort */ }
      return { data: null, stale: false, notFound: true, error: null };
    }
    // Network / relay / 5xx: fall back to the last cached copy so the app stays usable offline.
    let cached = null, meta = null;
    try { cached = await getCache(name); } catch (_) { cached = null; }
    try { meta = await getCacheMeta(name); } catch (_) { meta = null; }
    return { data: cached != null ? cached : null, stale: true, notFound: false, cachedAt: meta && meta.updated_at, error: e };
  }
}

module.exports = { readThroughSketch };

"use strict";
// Roof-sketch GET read-through with the sketch-SPECIFIC 404 contract. The backend returns HTTP 404 for a
// structure that has never had a sketch, carrying the machine-readable detail
// {code:"sketch_not_found", message:"No sketch for this structure yet"}. That is an AUTHORITATIVE empty
// state — NOT a load failure — and must be modelled distinctly so the viewer can offer first-time sketch
// creation instead of a retryable error screen.
//
// This 404 handling is NARROW: ONLY the explicit sketch_not_found condition (or the legacy exact string,
// for rollout) is treated as notFound. A generic 404, a missing/stale revision 404
// ("Measurement revision not found"), 401 and 403 are NOT no-sketch — they surface as errors so a deleted
// or stale revision can never open a blank/cached sketch.
//
// Envelope shapes returned:
//   existing sketch (HTTP 200):        { data:<sketch>, stale:false, notFound:false, error:null }
//   authoritative no-sketch 404:       { data:null,     stale:false, notFound:true,  error:null }
//   other 4xx (missing rev/401/403):   { data:null,     stale:false, notFound:false, error }   (reload/error)
//   network/relay/5xx + cache:         { data:<cached>, stale:true,  notFound:false, cachedAt, error }
//   network/relay/5xx, no cache:       { data:null,     stale:true,  notFound:false, error }
//
// An authoritative no-sketch 404 also RETIRES any obsolete cached sketch (clearCache) so a later offline
// read can never resurrect a deleted/never-existed sketch. Dependencies are injected so this runs and is
// tested in pure Node against the REAL api.get() error shape (Error with e.response.status and .data).

// True ONLY for the explicit "no sketch for this structure yet" condition — never a generic 404.
function isSketchNotFound(e) {
  const d = e && e.response && e.response.data && e.response.data.detail;
  if (!d) return false;
  if (typeof d === "object") return d.code === "sketch_not_found" || d.message === "No sketch for this structure yet"; // new contract (+ legacy message)
  if (typeof d === "string") return d === "No sketch for this structure yet"; // legacy exact string (backward compat)
  return false;
}

async function readThroughSketch({ fetcher, getCache, getCacheMeta, putCache, clearCache, name } = {}) {
  try {
    const r = await fetcher();
    const data = r && r.data != null ? r.data : null;
    if (data != null) { try { await putCache(name, data); } catch (e) { /* best effort */ } }
    return { data, stale: false, notFound: false, error: null };
  } catch (e) {
    const status = e && e.response && typeof e.response.status === "number" ? e.response.status : null;
    // AUTHORITATIVE "no sketch yet": the explicit sketch_not_found 404 (or legacy string). NOT a failure.
    if (status === 404 && isSketchNotFound(e)) {
      try { await clearCache(name); } catch (_) { /* best effort */ }
      return { data: null, stale: false, notFound: true, error: null };
    }
    // Any other definitive HTTP client error (missing/stale revision 404, generic 404, 401, 403): do NOT
    // serve a cached sketch and do NOT fabricate one — surface a reload/error state.
    if (status !== null && status >= 400 && status < 500) {
      return { data: null, stale: false, notFound: false, error: e };
    }
    // Network / relay / 5xx (transient): fall back to the last cached copy so the app stays usable offline.
    let cached = null, meta = null;
    try { cached = await getCache(name); } catch (_) { cached = null; }
    try { meta = await getCacheMeta(name); } catch (_) { meta = null; }
    return { data: cached != null ? cached : null, stale: true, notFound: false, cachedAt: meta && meta.updated_at, error: e };
  }
}

module.exports = { readThroughSketch, isSketchNotFound };

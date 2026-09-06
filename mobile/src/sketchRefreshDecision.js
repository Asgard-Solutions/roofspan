"use strict";
/*
 * RoofSpan Field — PURE decision for what a lead refresh should do about ONE structure's roof sketch,
 * given Office vs local sketch versions and local edit state (no RN/IO).
 *
 * Fixes the "structure row still says 'Sketch Roof' after Office created the first sketch" gap: a missing
 * local sketch with Office version > 0 is now treated as STALE and pulled (unless the rep holds an active
 * local draft/mutation). A same-version-but-different-content local draft with no active mutation is routed
 * to explicit REVIEW instead of silently keeping the local copy authoritative.
 *
 * Returns one of:
 *   "pull"           — fetch + cache the Office sketch (Field had none; Office created it).
 *   "floor_and_pull" — versions differ: raise the CAS floor to Office AND fetch the newer Office sketch.
 *   "review"         — same version, different content, no active mutation: needs explicit review.
 *   "none"           — nothing to do (in sync, or the rep's unsynced work stays authoritative).
 */
function sketchRefreshDecision({ officeVersion = 0, localVersion = null, hasDraft = false,
                                 hasActiveMutation = false, contentDiffers = false } = {}) {
  const office = Number(officeVersion) || 0;
  // The rep has unsynced local work for this sketch — never pull over it or force review from a refresh.
  if (hasActiveMutation) return "none";
  if (localVersion == null) {
    // Field has NO cached sketch. Pull ONLY if Office actually created one and there is no local draft.
    return office > 0 && !hasDraft ? "pull" : "none";
  }
  if (Number(localVersion) !== office) return "floor_and_pull";
  // Same document_version: a divergent local draft (no active mutation) must be reviewed, not ignored.
  if (hasDraft && contentDiffers) return "review";
  return "none";
}

module.exports = { sketchRefreshDecision };

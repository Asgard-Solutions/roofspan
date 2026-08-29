"use strict";
// Shared process-lifetime CAS version floor: once an authoritative server version is known for a
// revision+structure, ALL future staging (while the app/screen is open) preserves at least it. Lives
// in module scope so sync-ack (producer) and the sketch coordinator (consumer) share it without props.
const _floor = {};
const key = (r, s) => `${r}:${s}`;
function noteVersion(revisionId, structureId, version) {
  const k = key(revisionId, structureId);
  _floor[k] = Math.max(_floor[k] || 0, Number(version) || 0);
  return _floor[k];
}
function floor(revisionId, structureId) { return _floor[key(revisionId, structureId)] || 0; }
module.exports = { noteVersion, floor };

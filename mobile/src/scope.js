// Pure helpers that namespace cached data + queued mutations by paired installation AND user.
// CommonJS so it is unit-testable in plain Node (no Expo imports).
// Data isolation (spec §29): user A's cache/queue must never surface for user B, and installation
// A's data must never surface for installation B, on the same device.

function makeScope(installationId, userId) {
  return `${installationId || "none"}::${userId || "anon"}`;
}

function scopedKey(scope, name) {
  return `${scope || "none::anon"}::${name}`;
}

// Filter a list of mutations to a single scope (legacy/no-scope items count as the active scope so
// pre-upgrade pending work is never silently orphaned).
function forScope(mutations, scope) {
  return (mutations || []).filter((m) => (m.scope || scope) === scope);
}

function otherScopes(mutations, scope) {
  return (mutations || []).filter((m) => m.scope && m.scope !== scope);
}

module.exports = { makeScope, scopedKey, forScope, otherScopes };

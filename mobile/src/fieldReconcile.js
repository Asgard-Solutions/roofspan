"use strict";
// PURE cache reconciliation for Field Property / Visit / Do-Not-Knock / Lead acknowledgements.
//
// Given the AUTHORITATIVE server response for a synced mutation, these reducers compute the next
// Property-detail cache and the next Map/canvass FeatureCollection so PostgreSQL, the Property detail
// cache and the canvass cache never disagree after a successful sync. Optimistic local values are never
// treated as permanently authoritative — the server response wins on acknowledgement.

function _leadIdFrom(detail) {
  if (!detail) return null;
  if (detail.lead_id != null) return detail.lead_id;
  if (detail.existing_lead_id != null) return detail.existing_lead_id;
  return null;
}

// Resolve which cached Property a synced mutation belongs to (server value first, then request context).
function propertyIdForMutation(m) {
  const sv = m && m.serverValue;
  if (sv && sv.property_id != null) return String(sv.property_id);
  if (m && m.kind === "property_patch" && sv && sv.id != null) return String(sv.id);
  if (m && m.body && m.body.property_id != null) return String(m.body.property_id);
  if (m && m.kind === "property_patch" && typeof m.path === "string") {
    const parts = m.path.split("/").filter(Boolean);           // .../properties/<id>
    const i = parts.indexOf("properties");
    if (i >= 0 && parts[i + 1]) return parts[i + 1];
  }
  return null;
}

// Property detail cache reducer. Returns the next cached detail (unchanged base when N/A).
function reconcilePropertyDetail(kind, serverValue, cur) {
  const base = cur && typeof cur === "object" ? cur : {};
  if (!serverValue || typeof serverValue !== "object") return base;

  if (kind === "property_patch") {
    // Authoritative full canonical detail replaces the optimistic copy entirely.
    return { ...serverValue };
  }

  if (kind === "visit") {
    const visits = Array.isArray(base.visits) ? base.visits : [];
    // Drop any optimistic "pending-*" placeholder, then prepend the authoritative server visit.
    const cleaned = visits.filter((v) => v && !String(v.id || "").startsWith("pending-"));
    const authoritative = {
      id: serverValue.id, outcome: serverValue.outcome, notes: serverValue.notes,
      visited_at: serverValue.visited_at, user_email: serverValue.user_email,
    };
    const next = {
      ...base, visits: [authoritative, ...cleaned],
      last_outcome: serverValue.outcome, last_visited_at: serverValue.visited_at,
    };
    if (serverValue.outcome === "do_not_knock") {
      next.do_not_knock = true;
      if (!next.do_not_knock_reason) next.do_not_knock_reason = "Marked during visit";
    }
    return next;
  }

  if (kind === "lead_create") {
    const leadId = serverValue.id != null ? String(serverValue.id) : null;
    return { ...base, lead_id: leadId, existing_lead_id: leadId };
  }

  return base;
}

// Map/canvass FeatureCollection reducer: patch ONLY the feature for propertyId. Returns the next
// collection (or the unchanged input when there is no matching feature / not applicable).
function reconcileCanvassFeatures(kind, serverValue, propertyId, cur) {
  if (!cur || !Array.isArray(cur.features)) return cur;
  let changed = false;
  const features = cur.features.map((f) => {
    if (!f || !f.properties || String(f.properties.id) !== String(propertyId)) return f;
    const patch = {};
    if (kind === "property_patch" && serverValue) {
      if ("do_not_knock" in serverValue) patch.do_not_knock = serverValue.do_not_knock;
      if ("owner_occupied" in serverValue) patch.owner_occupied = serverValue.owner_occupied;
      patch.has_lead = _leadIdFrom(serverValue) != null;
      const lv = Array.isArray(serverValue.visits) && serverValue.visits.length ? serverValue.visits[0] : null;
      if (lv) { patch.last_outcome = lv.outcome; patch.last_visited_at = lv.visited_at; }
    } else if (kind === "visit" && serverValue) {
      patch.last_outcome = serverValue.outcome;
      patch.last_visited_at = serverValue.visited_at;
      if (serverValue.outcome === "do_not_knock") patch.do_not_knock = true;
    } else if (kind === "lead_create") {
      patch.has_lead = true;
    } else {
      return f;
    }
    changed = true;
    return { ...f, properties: { ...f.properties, ...patch } };
  });
  return changed ? { ...cur, features } : cur;
}

// Optimistic (pre-acknowledgement) canvass feature patch — applies a raw field patch to the matching
// feature so the Map reflects the rep's change immediately; the authoritative reducer above overwrites
// it on acknowledgement.
function optimisticCanvassPatch(propertyId, patch, cur) {
  if (!cur || !Array.isArray(cur.features)) return cur;
  return {
    ...cur,
    features: cur.features.map((f) =>
      f && f.properties && String(f.properties.id) === String(propertyId)
        ? { ...f, properties: { ...f.properties, ...patch } }
        : f
    ),
  };
}

module.exports = {
  propertyIdForMutation, reconcilePropertyDetail, reconcileCanvassFeatures, optimisticCanvassPatch,
};

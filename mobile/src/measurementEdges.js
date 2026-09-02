/*
 * RoofSpan Mobile — measurement edge identity/lineage helpers (pure, Node-testable, no Expo/RN).
 *
 * The backend reconciles an editable measurement revision BY IDENTITY using EdgeIn.ref: a server-UUID
 * ref claims an existing MeasurementEdge (UPDATE in place, its roof sketch survives); a temporary
 * (non-UUID) ref means a brand-new edge (INSERT). If Field ever drops the ref for a persisted edge the
 * backend treats it as new -> inserts a duplicate and deletes the original, destroying identity.
 *
 * These helpers are the single source of truth shared by the Field measurement screen and its contract
 * test so existing edges ALWAYS carry ref = MeasurementEdge.id through hydrate -> edit -> buildBody ->
 * optimistic cache -> offline queue -> PUT.
 */
const uid = () => "r" + Math.random().toString(36).slice(2, 10);

// Hydrate a server/persisted edge into editable state, pinning a stable identity ref.
function edgeForEdit(e) {
  const ref = e.ref || e.id || e._k || uid();
  const length = Number(e.length_ft || 0);
  const ft = Math.floor(length);
  const inches = Math.round((length - ft) * 12 * 10) / 10;
  return {
    ...e,
    ref,
    _k: e._k || e.id || ref,
    facet_ref: e.facet_ref || e.facet_id || "",
    facet_ref_secondary: e.facet_ref_secondary || e.facet_id_secondary || "",
    ft: String(ft || ""),
    in: String(inches || ""),
  };
}

// A brand-new local edge: one temporary key used for BOTH identity properties.
function newEdge() {
  const ref = uid();
  return { ref, _k: ref, edge_type: "eave", ft: "", in: "", length_ft: 0, facet_ref: "", facet_ref_secondary: "" };
}

// Serialize an editable edge into the PUT payload, always carrying its identity ref AND both plane
// associations (the model supports two facets per edge — dropping the secondary erases Office/sketch data).
function edgeToBody(e, i) {
  return {
    ref: e.ref || e.id || e._k,
    edge_type: e.edge_type || "eave",
    length_ft: parseFloat(e.length_ft) || 0,
    facet_ref: e.facet_ref || e.facet_id || null,
    facet_ref_secondary: e.facet_ref_secondary || e.facet_id_secondary || null,
    label: e.label || null,
    notes: e.notes || null,
    sort: i,
  };
}

module.exports = { edgeForEdit, newEdge, edgeToBody, uid };

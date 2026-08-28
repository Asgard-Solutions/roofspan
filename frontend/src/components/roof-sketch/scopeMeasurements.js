// Structure-safe measurement scoping (pure, Node-testable). The Roof Sketch Editor must only ever
// receive the relational records that belong to the Structure being edited — never facets/edges/
// penetrations from other structures. Identity is by relational ownership only, NEVER by type/length.

const sameId = (a, b) => a != null && b != null && String(a) === String(b);

export function scopeFacetsForStructure(facets, structureId) {
  return (facets || []).filter((f) => sameId(f.structure_id, structureId));
}

export function facetIdSet(scopedFacets) {
  return new Set((scopedFacets || []).map((f) => String(f.id)));
}

// An edge belongs to the structure if EITHER of its facets (shared edges have two) is in-structure.
export function scopeEdgesForStructure(edges, scopedFacets) {
  const ids = facetIdSet(scopedFacets);
  return (edges || []).filter(
    (e) => (e.facet_id != null && ids.has(String(e.facet_id))) ||
           (e.facet_id_secondary != null && ids.has(String(e.facet_id_secondary))),
  );
}

export function scopePenetrationsForStructure(penetrations, scopedFacets) {
  const ids = facetIdSet(scopedFacets);
  return (penetrations || []).filter((p) => p.facet_id != null && ids.has(String(p.facet_id)));
}

// Convenience: everything the editor needs for one structure, derived deterministically.
export function scopeForStructure({ structure, facets, edges, penetrations }) {
  const sid = structure?.id;
  const scopedFacets = scopeFacetsForStructure(facets, sid);
  return {
    facets: scopedFacets,
    edges: scopeEdgesForStructure(edges, scopedFacets),
    penetrations: scopePenetrationsForStructure(penetrations, scopedFacets),
  };
}

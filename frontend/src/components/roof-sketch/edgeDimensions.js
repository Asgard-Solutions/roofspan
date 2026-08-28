// Pure dimension-label resolution for a graph edge (Node-testable). A locked confirmed measurement is
// ALWAYS authoritative for the displayed value; geometry never silently overwrites it. Uses shared-core
// edgeGeometryLengthFeet so the displayed LF and the proposal LF can never disagree.
import { edgeGeometryLengthFeet } from "@roofspan/roof-sketch-core";

const round1 = (n) => (n == null ? null : Math.round(n * 10) / 10);

export function edgeDimension(doc, edge) {
  const geometryFeet = round1(edgeGeometryLengthFeet(doc, edge));
  const locked = edge && edge.locked === true && edge.confirmed_length_ft != null;
  if (locked) {
    const valueFeet = round1(Number(edge.confirmed_length_ft));
    // Canonical difference convention (matches compareProposal): proposed geometry - confirmed.
    const discrepancy = geometryFeet != null ? round1(geometryFeet - valueFeet) : null;
    return { valueFeet, source: "confirmed_locked", locked: true, geometryFeet, discrepancy };
  }
  if (geometryFeet != null) return { valueFeet: geometryFeet, source: "geometry_scaled", locked: false, geometryFeet, discrepancy: null };
  return { valueFeet: null, source: "unavailable", locked: false, geometryFeet: null, discrepancy: null };
}

export function formatFeet(valueFeet) {
  return valueFeet == null ? null : `${valueFeet.toFixed(1)} LF`;
}

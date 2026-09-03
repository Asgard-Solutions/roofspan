"use strict";
// Pure dimension-label resolution for a graph edge (Node-testable, CommonJS). A locked confirmed
// measurement is ALWAYS authoritative for the displayed value; geometry never silently overwrites it.
// Uses shared-core edgeGeometryLengthFeet so the displayed LF and the proposal LF can never disagree.
// Ported verbatim from the approved Office edgeDimensions.js.
const { edgeGeometryLengthFeet } = require("./geometry");

const round1 = (n) => (n == null ? null : Math.round(n * 10) / 10);

function edgeDimension(doc, edge) {
  const geometryFeet = round1(edgeGeometryLengthFeet(doc, edge));
  const locked = edge && edge.locked === true && edge.confirmed_length_ft != null;
  if (locked) {
    const valueFeet = round1(Number(edge.confirmed_length_ft));
    // Canonical difference convention (matches compareProposal): proposed geometry - confirmed.
    const discrepancy = geometryFeet != null ? round1(geometryFeet - valueFeet) : null;
    return { valueFeet, source: "confirmed_locked", locked: true, geometryFeet, discrepancy };
  }
  if (geometryFeet != null) return { valueFeet: geometryFeet, source: "geometry_scaled", locked: false, geometryFeet, discrepancy: null };
  // Fallbacks so a length still shows while drawing (scale not yet calibrated) or on generated edges.
  if (edge && edge.confirmed_length_ft != null) return { valueFeet: round1(Number(edge.confirmed_length_ft)), source: "confirmed", locked: false, geometryFeet: null, discrepancy: null };
  if (edge && edge.drawn_length_ft != null) return { valueFeet: round1(Number(edge.drawn_length_ft)), source: "drawn", locked: false, geometryFeet: round1(Number(edge.drawn_length_ft)), discrepancy: null };
  return { valueFeet: null, source: "unavailable", locked: false, geometryFeet: null, discrepancy: null };
}

function formatFeet(valueFeet) {
  return valueFeet == null ? null : `${valueFeet.toFixed(1)} LF`;
}

module.exports = { edgeDimension, formatFeet };

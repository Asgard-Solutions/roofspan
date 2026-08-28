"use strict";
// Public API for @roofspan/roof-sketch-core. Office, Field, and the import/reconciliation system
// must consume geometry/topology/proposal math ONLY through this module.
const geometry = require("./geometry");
const schema = require("./schema");
const topology = require("./topology");
const proposals = require("./proposals");

module.exports = {
  // schema / document
  SCHEMA_VERSION: schema.SCHEMA_VERSION,
  EDIT_MODES: schema.EDIT_MODES,
  EDGE_TYPES: schema.EDGE_TYPES,
  createSketchDocument: schema.createSketchDocument,
  normalizeSketchDocument: schema.normalizeSketchDocument,
  // geometry
  distance: geometry.distance,
  polygonArea: geometry.polygonArea,
  pitchAdjustedArea: geometry.pitchAdjustedArea,
  calibrateScale: geometry.calibrateScale,
  segmentsCross: geometry.segmentsCross,
  // topology / validation
  findSharedEdges: topology.findSharedEdges,
  validateSketch: topology.validateSketch,
  polygonSelfIntersects: topology.polygonSelfIntersects,
  // proposals
  deriveProposals: proposals.deriveProposals,
  compareProposal: proposals.compareProposal,
};

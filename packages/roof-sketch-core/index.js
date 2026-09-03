"use strict";
// Public API for @roofspan/roof-sketch-core. Office, Field, and the import/reconciliation system
// must consume geometry/topology/proposal math ONLY through this module.
const geometry = require("./geometry");
const schema = require("./schema");
const topology = require("./topology");
const proposals = require("./proposals");
const editorCommands = require("./editorCommands");
const generateSketch = require("./generateSketch");
const generateSketchGeometry = require("./generateSketchGeometry");
const compareSketchProposal = require("./compareSketchProposal");
const snapping = require("./snapping");
const edgeDimensions = require("./edgeDimensions");
const gestures = require("./gestures");
const history = require("./history");

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
  planRunFromSlope: geometry.planRunFromSlope,
  calibrateScale: geometry.calibrateScale,
  segmentsCross: geometry.segmentsCross,
  projectPointToSegment: geometry.projectPointToSegment,
  edgeGeometryLengthFeet: geometry.edgeGeometryLengthFeet,
  // topology / validation
  findSharedEdges: topology.findSharedEdges,
  validateSketch: topology.validateSketch,
  polygonSelfIntersects: topology.polygonSelfIntersects,
  edgeLoopVertices: topology.edgeLoopVertices,
  sameCycle: topology.sameCycle,
  polygonsOverlap: topology.polygonsOverlap,
  facetComponents: topology.facetComponents,
  edgeMap: topology.edgeMap,
  resolveFacetBoundary: topology.resolveFacetBoundary,
  polygonCycleKey: topology.polygonCycleKey,
  // proposals
  deriveProposals: proposals.deriveProposals,
  compareProposal: proposals.compareProposal,

  // ---- measurements -> proposed sketch (shared deterministic foundation) ----
  generateProposedSketch: generateSketch.generateProposedSketch,
  GENERATOR_VERSION: generateSketch.GENERATOR_VERSION,
  // ---- measurements -> proposed sketch GEOMETRY (single plane + simple gable) ----
  generateSketchGeometry: generateSketchGeometry.generateSketchGeometry,
  // ---- existing sketch vs new proposal comparison (Office review) ----
  compareSketchProposal: compareSketchProposal.compareSketchProposal,

  // ---- shared editor engine (Phase B1A: additive; Office not yet migrated) ----
  // editor commands (pure; each returns the next canonical document)
  nid: editorCommands.nid,
  vById: editorCommands.vById,
  eById: editorCommands.eById,
  fById: editorCommands.fById,
  addVertex: editorCommands.addVertex,
  moveVertex: editorCommands.moveVertex,
  moveVertexFinal: editorCommands.moveVertexFinal,
  deleteVertex: editorCommands.deleteVertex,
  addEdge: editorCommands.addEdge,
  setEdgeType: editorCommands.setEdgeType,
  deleteEdge: editorCommands.deleteEdge,
  splitEdge: editorCommands.splitEdge,
  splitEdgeSafe: editorCommands.splitEdgeSafe,
  createFacet: editorCommands.createFacet,
  createManualFacet: editorCommands.createManualFacet,
  deleteFacet: editorCommands.deleteFacet,
  setFacetPitch: editorCommands.setFacetPitch,
  setFacetOrientation: editorCommands.setFacetOrientation,
  setFacetLabel: editorCommands.setFacetLabel,
  setScale: editorCommands.setScale,
  setConfirmedEdgeLength: editorCommands.setConfirmedEdgeLength,
  lockEdge: editorCommands.lockEdge,
  unlockEdge: editorCommands.unlockEdge,
  placePenetration: editorCommands.placePenetration,
  movePenetration: editorCommands.movePenetration,
  setPenetrationType: editorCommands.setPenetrationType,
  deletePenetration: editorCommands.deletePenetration,
  setProposalDecision: editorCommands.setProposalDecision,
  setDecisions: editorCommands.setDecisions,
  decisionFor: editorCommands.decisionFor,
  isMeasurementFacetTaken: editorCommands.isMeasurementFacetTaken,
  setFacetMeasurementLink: editorCommands.setFacetMeasurementLink,
  isMeasurementEdgeTaken: editorCommands.isMeasurementEdgeTaken,
  setEdgeMeasurementLink: editorCommands.setEdgeMeasurementLink,
  setEditMode: editorCommands.setEditMode,
  edgeIsProtected: editorCommands.edgeIsProtected,
  validateMutation: editorCommands.validateMutation,
  mergeVertices: editorCommands.mergeVertices,
  insertExistingVertexIntoEdge: editorCommands.insertExistingVertexIntoEdge,
  joinEdges: editorCommands.joinEdges,
  // snapping
  modelTolerance: snapping.modelTolerance,
  snapTarget: snapping.snapTarget,
  // edge dimensions
  edgeDimension: edgeDimensions.edgeDimension,
  formatFeet: edgeDimensions.formatFeet,
  // gestures
  candidateFor: gestures.candidateFor,
  drawSnap: gestures.drawSnap,
  dragSnap: gestures.dragSnap,
  applyDrawPoint: gestures.applyDrawPoint,
  applyVertexDrop: gestures.applyVertexDrop,
  // history
  MAX_HISTORY: history.MAX_HISTORY,
  makeHistory: history.makeHistory,
  historyPush: history.push,
  historyPushFrom: history.pushFrom,
  historyUndo: history.undo,
  historyRedo: history.redo,
  historyCanUndo: history.canUndo,
  historyCanRedo: history.canRedo,
};

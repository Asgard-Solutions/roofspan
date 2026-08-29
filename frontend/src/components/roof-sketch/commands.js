// Thin compatibility wrapper (Phase B1B). The authoritative editor engine now lives in
// @roofspan/roof-sketch-core. Office keeps this local import path unchanged; every symbol below is a
// reference-preserving re-export — there is NO local algorithm here anymore.
export {
  nid, vById, eById, fById,
  addVertex, moveVertex, moveVertexFinal, deleteVertex,
  addEdge, setEdgeType, deleteEdge,
  splitEdge, splitEdgeSafe,
  createFacet, createManualFacet, deleteFacet,
  setFacetPitch, setFacetOrientation, setFacetLabel,
  setScale,
  setConfirmedEdgeLength, lockEdge, unlockEdge,
  placePenetration, movePenetration, setPenetrationType, deletePenetration,
  setProposalDecision, setDecisions, decisionFor,
  isMeasurementFacetTaken, setFacetMeasurementLink,
  isMeasurementEdgeTaken, setEdgeMeasurementLink,
  setEditMode,
  edgeIsProtected, validateMutation,
  mergeVertices, insertExistingVertexIntoEdge, joinEdges,
} from "@roofspan/roof-sketch-core";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { createSketchDocument, deriveProposals, validateSketch, generateSketchGeometry, compareSketchProposal } from "@roofspan/roof-sketch-core";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { MousePointer2, PenLine, Square, Dot, Undo2, Redo2, Save, X, Loader2 } from "lucide-react";
import RoofSketchCanvas from "./RoofSketchCanvas";
import SketchInspector from "./SketchInspector";
import ProposalPanel from "./ProposalPanel";
import { summarizeScoped } from "./scopeMeasurements";
import { useSketchHistory } from "./history";
import { getSketch, saveSketch } from "./sketchApi";
import * as C from "./commands";
import * as SL from "./saveLifecycle";
import * as PL from "./proposalLifecycle";
import { resolveKey } from "./keyboardGate";

const SAVE_BADGE = {
  saved: ["Saved", "bg-emerald-100 text-emerald-800"], unsaved: ["Unsaved changes", "bg-amber-100 text-amber-800"],
  saving: ["Saving…", "bg-blue-100 text-blue-800"], error: ["Save failed", "bg-rose-100 text-rose-800"],
  conflict: ["Conflict", "bg-rose-100 text-rose-800"], validation: ["Rejected", "bg-rose-100 text-rose-800"],
};

const RS_EDGE_LABELS = { eave: "Eave", rake: "Rake", ridge: "Ridge", hip: "Hip", valley: "Valley", sidewall: "Sidewall", headwall: "Headwall", transition: "Transition", other: "Other" };
const RS_PEN_LABELS = { pipe_boot: "Pipe Boot", static_vent: "Static Vent", skylight: "Skylight", turbine: "Turbine", powered_vent: "Powered Vent", exhaust_vent: "Exhaust Vent", chimney: "Chimney", satellite: "Satellite", other: "Other" };
const rsPitch = (p) => (p === "" || p == null ? "—" : `${p}/12`);

export default function RoofSketchEditor({ revision, structure, facets = [], edges = [], penetrations = [], onMeasurementChanged, onDiscardSession, onClose }) {
  const readOnly = revision?.editable === false;
  const hist = useSketchHistory(createSketchDocument({ structureId: structure?.id }));
  const docRef = useRef(hist.doc);
  useEffect(() => { docRef.current = hist.doc; }, [hist.doc]);

  const [loading, setLoading] = useState(true);
  const [save, setSave] = useState(() => SL.initSaveState(null));
  const saveRef = useRef(save);
  // Authoritative, synchronous save-state controller: every transition updates the ref AND React state
  // from the same code path so request-control decisions never race the async React state queue.
  const commitSaveState = useCallback((nextOrUpdater) => {
    const current = saveRef.current;
    const next = typeof nextOrUpdater === "function" ? nextOrUpdater(current) : nextOrUpdater;
    saveRef.current = next;
    setSave(next);
    return next;
  }, []);
  useEffect(() => { saveRef.current = save; }, [save]); // defensive only; not relied on for correctness
  const [mode, setMode] = useState("select");
  const [selection, setSelection] = useState(null);
  const [conflict, setConflict] = useState(null);
  const [validationMsg, setValidationMsg] = useState(null);
  const [closeConfirm, setCloseConfirm] = useState(false);
  const [showMeas, setShowMeas] = useState(true);
  const [proposal, setProposal] = useState(null);   // local Generate-Proposed preview (unsaved, not persisted)
  const [regen, setRegen] = useState(null);          // existing-sketch: {result, comparison} review (no auto-replace)
  const [regenConfirm, setRegenConfirm] = useState(false); // explicit replace confirmation gate
  const preGenRef = useRef(null);                    // exact pre-generation snapshot for Cancel
  const regenPanelRef = useRef(null);                // regen review panel (for scroll-into-view feedback)
  const measRef = useMemo(() => summarizeScoped({ facets, edges, penetrations }), [facets, edges, penetrations]);
  const [closing, setClosing] = useState(false);       // Save & Close request in progress
  const closeConfirmRef = useRef(false);
  const closingRef = useRef(false);
  useEffect(() => { closeConfirmRef.current = closeConfirm; }, [closeConfirm]);
  useEffect(() => { closingRef.current = closing; }, [closing]);
  // Bring the newly-opened proposal review panel into view so the action is never perceived as "nothing happened".
  useEffect(() => { if (regen && regenPanelRef.current) regenPanelRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [regen]);
  const sessionRef = useRef(PL.makeSession());     // editor-session worksheet changes (for safe Discard)

  const relFacets = useMemo(() => facets.filter((f) => f.id), [facets]);
  const relEdges = useMemo(() => edges.filter((e) => e.id), [edges]);
  const relFacetsById = useMemo(() => { const m = {}; relFacets.forEach((f) => (m[f.id] = f)); return m; }, [relFacets]);
  const relEdgesById = useMemo(() => { const m = {}; relEdges.forEach((e) => (m[e.id] = e)); return m; }, [relEdges]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const rec = await getSketch(revision.id, structure.id);
        if (!alive) return;
        if (rec) { hist.reset(rec.document); docRef.current = rec.document; commitSaveState(SL.initSaveState(rec.document_version)); }
        else { const fresh = createSketchDocument({ structureId: structure.id }); hist.reset(fresh); docRef.current = fresh; commitSaveState(SL.initSaveState(null)); }
      } catch (e) { toast.error("Could not load roof sketch."); }
      finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [revision.id, structure.id]); // eslint-disable-line

  const bumpEdit = useCallback(() => commitSaveState((s) => SL.markEdited(s)), [commitSaveState]);
  const doUndo = useCallback(() => { hist.undo(); bumpEdit(); }, [hist, bumpEdit]);
  const doRedo = useCallback(() => { hist.redo(); bumpEdit(); }, [hist, bumpEdit]);
  const ctl = useMemo(() => ({
    getDoc: () => docRef.current,
    run: (fn) => { const res = fn(docRef.current) || {}; const nd = res.doc || docRef.current; docRef.current = nd; hist.commit(nd); bumpEdit(); return res; },
    preview: (nd) => { docRef.current = nd; hist.setDocDirect(nd); bumpEdit(); },
    // Live drag preview: update the visible document WITHOUT creating a history entry or bumping the
    // edit generation. The single history/edit commit happens on pointer-up via commitFrom.
    previewSilent: (nd) => { docRef.current = nd; hist.setDocDirect(nd); },
    commitFrom: (prev, next) => { docRef.current = next; hist.commitFrom(prev, next); bumpEdit(); },
  }), [hist, bumpEdit]);

  const doc = hist.doc;
  const validation = useMemo(() => validateSketch(doc), [doc]);
  const proposals = useMemo(() => deriveProposals(doc), [doc]);

  // --- Generate Proposed Sketch (Office, empty-sketch only) ---------------------------------------
  // Offered ONLY when: editable, no saved sketch yet (serverVersion null), and the canvas is empty.
  // Generation runs the shared core locally — it never saves, never touches Measurements.
  const isEmptyDoc = (doc.facets?.length || 0) === 0 && (doc.edges?.length || 0) === 0 && (doc.vertices?.length || 0) === 0;
  const canGenerate = !readOnly && save.serverVersion == null && isEmptyDoc && !proposal;
  // Placement resolutions (the user's per-plane side choices) for connected complex roofs. Persisted on
  // the sketch document so they travel with it (offline-safe, Office<->Field parity).
  const [resolutions, setResolutions] = useState([]);
  useEffect(() => { const pr = docRef.current?.placement_resolutions; if (Array.isArray(pr) && pr.length) setResolutions(pr.map((r) => ({ plane: String(r.plane), side: r.side }))); }, []);
  const setSide = useCallback((plane, side) => setResolutions((prev) => { const rest = prev.filter((r) => String(r.plane) !== String(plane)); return side ? [...rest, { plane: String(plane), side }] : rest; }), []);

  const generateProposed = useCallback(() => {
    if (readOnly || saveRef.current.serverVersion != null) return;
    preGenRef.current = { doc: docRef.current, save: saveRef.current };
    const res = generateSketchGeometry({ structure, facets, edges, penetrations, resolutions });
    setProposal(res); setSelection(null);
    if (res.document && (res.document.vertices?.length || 0) > 0) { docRef.current = res.document; hist.setDocDirect(res.document); }
  }, [readOnly, structure, facets, edges, penetrations, hist, resolutions]);
  const useProposed = useCallback(() => {
    if (readOnly || !proposal || !proposal.document || (proposal.document.vertices?.length || 0) === 0) return;
    hist.reset(proposal.document); docRef.current = proposal.document; bumpEdit();
    setProposal(null); setSelection(null);
    toast.success(proposal.readiness === "high_confidence"
      ? "Proposed sketch adopted. Review and Save when ready."
      : "Proposed sketch adopted — unresolved items remain. Review and Save when ready.");
  }, [readOnly, proposal, hist, bumpEdit]);
  const cancelProposed = useCallback(() => {
    const snap = preGenRef.current;
    if (snap) { hist.reset(snap.doc); docRef.current = snap.doc; commitSaveState(snap.save); }
    setProposal(null); setSelection(null);
  }, [hist, commitSaveState]);
  const proposalPenPlacements = proposal ? (proposal.document?.penetrations || []).filter((p) => p.position_known === false) : [];

  // --- Existing sketch: Generate New Proposal + safe review (Office) ------------------------------
  // Offered when a saved sketch exists and the canvas is non-empty. The proposal stays a SEPARATE
  // candidate — the current sketch is never auto-replaced and Measurements are never touched. No graph
  // auto-merge. "Use Proposed" replaces the editor geometry only after an explicit confirm, and remains
  // an UNSAVED edit until the normal Save (with its existing CAS/conflict rules) succeeds.
  const hasExistingSketch = save.serverVersion != null && !isEmptyDoc;
  const canRegenerate = !readOnly && hasExistingSketch && !regen && !proposal;
  const regenerateProposed = useCallback(() => {
    if (readOnly || saveRef.current.serverVersion == null) return;
    const result = generateSketchGeometry({ structure, facets, edges, penetrations, resolutions });
    const comparison = compareSketchProposal(docRef.current, result);
    setRegen({ result, comparison }); setRegenConfirm(false);
    // Immediate, unmissable feedback — the existing-sketch flow opens a review panel (it never auto-replaces
    // your sketch), so without this the button felt like it "did nothing / drew no roof".
    if (comparison.identical) {
      toast.info("No changes — the new proposal matches your current roof sketch.");
    } else if (comparison.proposal_has_geometry) {
      toast.success("New proposal ready — review it in the panel on the right, then choose “Use Proposed Sketch” to draw it.");
    } else {
      toast.warning("The current measurements don’t support a proposed roof sketch yet — your current sketch is kept.");
    }
  }, [readOnly, structure, facets, edges, penetrations, resolutions]);
  const regenKeepCurrent = useCallback(() => { setRegen(null); setRegenConfirm(false); }, []);
  const regenUseProposed = useCallback(() => {
    if (readOnly || !regen || !regen.comparison.proposal_has_geometry) return;
    if (!regenConfirm) { setRegenConfirm(true); return; }          // require explicit confirmation first
    hist.reset(regen.result.document); docRef.current = regen.result.document; bumpEdit();
    setRegen(null); setRegenConfirm(false); setSelection(null);
    toast.success("Proposed sketch replaced the current geometry — review and Save to keep it.");
  }, [readOnly, regen, regenConfirm, hist, bumpEdit]);

  const cmd = useMemo(() => ({
    setEdgeType: (id, t) => ctl.run((d) => ({ doc: C.setEdgeType(d, id, t) })),
    deleteEdge: (id) => { ctl.run((d) => ({ doc: C.deleteEdge(d, id) })); setSelection(null); },
    setConfirmedEdgeLength: (id, ft) => ctl.run((d) => ({ doc: C.setConfirmedEdgeLength(d, id, ft) })),
    lockEdge: (id) => ctl.run((d) => ({ doc: C.lockEdge(d, id) })),
    unlockEdge: (id) => ctl.run((d) => ({ doc: C.unlockEdge(d, id) })),
    setFacetPitch: (id, p) => ctl.run((d) => ({ doc: C.setFacetPitch(d, id, p) })),
    setFacetOrientation: (id, o) => ctl.run((d) => ({ doc: C.setFacetOrientation(d, id, o) })),
    setFacetLabel: (id, l) => ctl.run((d) => ({ doc: C.setFacetLabel(d, id, l) })),
    setFacetLink: (id, mfid) => { const before = C.fById(docRef.current, id)?.measurement_facet_id || null; const nd = C.setFacetMeasurementLink(docRef.current, id, mfid); if (nd === docRef.current && mfid && before !== mfid) { toast.error("That Measurement Facet is already mapped to another sketch facet."); return; } ctl.run(() => ({ doc: nd })); },
    setEdgeLink: (id, meid) => { const before = C.eById(docRef.current, id)?.measurement_edge_id || null; const nd = C.setEdgeMeasurementLink(docRef.current, id, meid); if (nd === docRef.current && meid && before !== meid) { toast.error("That Measurement Edge is already mapped to another sketch edge."); return; } ctl.run(() => ({ doc: nd })); },
    deleteFacet: (id) => { ctl.run((d) => ({ doc: C.deleteFacet(d, id) })); setSelection(null); },
    setPenetrationType: (id, t) => ctl.run((d) => ({ doc: C.setPenetrationType(d, id, t) })),
    deletePenetration: (id) => { ctl.run((d) => ({ doc: C.deletePenetration(d, id) })); setSelection(null); },
    calibrate: (edgeId, feet) => ctl.run((d) => ({ doc: C.setScale(d, { edgeId, realFeet: feet }) })),
    join: (edgeId, neighborId, opts) => {
      const cur = docRef.current;
      const r = C.joinEdges(cur, edgeId, neighborId, opts);
      const REASON = { edge_protected: "This edge is mapped, confirmed, or locked. Clear the confirmed length and/or unmap/unlock it before changing its topology.", type_conflict: "Choose the resulting edge type before joining.", middle_vertex_has_additional_connections: "The shared vertex has another edge; joining would break that branch.", facet_boundary_mismatch: "These edges are not a consecutive pair on a facet boundary.", duplicate_outer_edge: "An edge already connects those outer endpoints.", connected_graph_required: "Switch to Connected mode to join edges." };
      if (!r.ok) { toast.error(REASON[r.reason] || `Cannot join (${r.reason}).`); return; }
      ctl.commitFrom(cur, r.doc); setSelection({ type: "edge", id: r.edgeId });
      toast.success("Edges joined.");
    },
  }), [ctl]);

  const deleteSelected = useCallback(() => {
    if (readOnly || !selection) return;
    const { type, id } = selection;
    ctl.run((d) => ({ doc: type === "edge" ? C.deleteEdge(d, id) : type === "facet" ? C.deleteFacet(d, id) : type === "penetration" ? C.deletePenetration(d, id) : C.deleteVertex(d, id) }));
    setSelection(null);
  }, [ctl, selection, readOnly]);

  useEffect(() => {
    const onKey = (e) => {
      const tag = (e.target.tagName || "").toLowerCase();
      if (["input", "textarea", "select"].includes(tag) || e.target.isContentEditable) return;
      const action = resolveKey({ closeConfirm: closeConfirmRef.current, closing: closingRef.current, ctrlOrMeta: e.ctrlKey || e.metaKey, key: e.key, shift: e.shiftKey });
      if (action === "none") return;
      e.preventDefault();
      if (action === "undo") doUndo();
      else if (action === "redo") doRedo();
      else if (action === "delete") deleteSelected();
      else if (action === "deselect") { setSelection(null); setMode("select"); }
      else if (action === "dismiss-modal") setCloseConfirm(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [doUndo, doRedo, deleteSelected]);

  const doSave = async () => {
    // HARD in-flight guard: exactly one active sketch-save per editor. Enforced on the authoritative ref
    // so a re-enabled button (or a Save & Close after a normal Save) can never launch a second PUT that
    // reuses the same CAS version. No second request preparation happens.
    if (!SL.canBeginSave(saveRef.current)) return { ok: false, reason: "already_saving" };
    // Prepare the request SYNCHRONOUSLY from the current state, freezing a detached document snapshot.
    const prep = SL.prepareSketchSave(saveRef.current, docRef.current);
    commitSaveState(prep.nextSaveState);   // saveRef.current.saving === true synchronously, before any await
    setConflict(null); setValidationMsg(null);
    const res = await saveSketch(revision.id, structure.id, { document: prep.snapshotDocument, editMode: prep.snapshotDocument.edit_mode, expectedVersion: prep.expectedVersion });
    if (res.ok) {
      const next = commitSaveState((s) => SL.resolveSaveSuccess(s, prep.snapshotGeneration, res.record.document_version));
      const clean = SL.isCleanState(next);
      if (clean) toast.success("Roof sketch saved.");
      else toast.message("The saved version completed, but newer sketch changes are still unsaved. Save again before closing.");
      return { ok: true, clean };
    }
    if (res.kind === "conflict") { commitSaveState((s) => SL.resolveSaveFailure(s, "conflict")); setConflict(res.server); toast.error("Sketch was changed by someone else."); }
    else if (res.kind === "validation") { commitSaveState((s) => SL.resolveSaveFailure(s, "validation")); setValidationMsg(res.message); toast.error("Server rejected the sketch."); }
    else if (res.kind === "locked") { commitSaveState((s) => SL.resolveSaveFailure(s, "error")); toast.error(res.message); }
    else { commitSaveState((s) => SL.resolveSaveFailure(s, "error")); toast.error(res.message || "Save failed."); }
    return { ok: false, clean: false };
  };

  const reloadServer = async () => {
    const rec = await getSketch(revision.id, structure.id);
    if (rec) { hist.reset(rec.document); docRef.current = rec.document; commitSaveState(SL.adoptServerVersion(saveRef.current, rec.document_version)); }
    setConflict(null); setSelection(null);
    toast.message("Loaded the latest server version. Your local edits were discarded.");
  };

  const switchMode = (m) => {
    if (m === docRef.current.edit_mode) return;
    if ((docRef.current.facets?.length || docRef.current.edges?.length) && !window.confirm("Switching edit mode may reinterpret existing geometry. Continue?")) return;
    ctl.run((d) => ({ doc: C.setEditMode(d, m) }));
    setSelection(null);
  };

  // ACCEPT: never marks accepted. Requires an explicit relational mapping. Updates the Worksheet DRAFT
  // (parent) and records a pending_accept decision on the sketch document.
  const acceptProposal = (p) => {
    const isFacet = p.target_type === "facet";
    const sketchEntity = isFacet ? C.fById(docRef.current, p.target_id) : C.eById(docRef.current, p.target_id);
    const relId = isFacet ? sketchEntity?.measurement_facet_id : sketchEntity?.measurement_edge_id;
    const rel = relId ? (isFacet ? relFacetsById[relId] : relEdgesById[relId]) : null;
    if (!rel) { toast.error(`Map this sketch ${isFacet ? "facet to a Measurement Facet" : "edge to a Measurement Edge"} before accepting.`); return; }
    const currentValue = isFacet ? Number(rel.area_sqft) || 0 : Number(rel.length_ft) || 0;
    const out = PL.acceptProposed({ decisions: docRef.current.proposal_decisions || [], session: sessionRef.current },
      { target_type: p.target_type, relationalTargetId: String(relId), metric: p.metric, proposedValue: p.proposed, currentValue });
    sessionRef.current = out.session;
    ctl.run((d) => ({ doc: C.setDecisions(d, out.decisions) }));
    if (onMeasurementChanged) onMeasurementChanged(out.draftChange);
    toast.success("Proposed value applied to the Worksheet draft (pending until you save the Worksheet).");
  };

  const keepProposal = (p) => {
    const isFacet = p.target_type === "facet";
    const sketchEntity = isFacet ? C.fById(docRef.current, p.target_id) : C.eById(docRef.current, p.target_id);
    const relId = (isFacet ? sketchEntity?.measurement_facet_id : sketchEntity?.measurement_edge_id) || p.target_id;
    const out = PL.keepCurrent({ decisions: docRef.current.proposal_decisions || [] }, { target_type: p.target_type, targetId: String(relId), metric: p.metric });
    ctl.run((d) => ({ doc: C.setDecisions(d, out.decisions) }));
  };

  // Reopened persisted pending decisions (do NOT auto-apply to the Worksheet).
  const pendingDecisions = (doc.proposal_decisions || []).filter((d) => d.decision === PL.PENDING);
  const validIdSet = useMemo(() => new Set([...relFacets.map((f) => String(f.id)), ...relEdges.map((e) => String(e.id))]), [relFacets, relEdges]);
  const applyPending = (dec) => {
    if (!PL.canApplyPending(dec, validIdSet)) { toast.error("This pending proposal's measurement mapping is no longer valid and cannot be applied."); return; }
    const rel = dec.target_type === "facet" ? relFacetsById[dec.target_id] : relEdgesById[dec.target_id];
    const currentValue = dec.target_type === "facet" ? Number(rel.area_sqft) || 0 : Number(rel.length_ft) || 0;
    const out = PL.applyPendingToDraft({ session: sessionRef.current }, dec, currentValue);
    sessionRef.current = out.session;
    if (onMeasurementChanged) onMeasurementChanged(out.draftChange);
    toast.success("Applied to the Worksheet draft (still pending until the Worksheet is saved).");
  };
  const keepPending = (dec) => { const out = PL.keepCurrent({ decisions: doc.proposal_decisions || [] }, { target_type: dec.target_type, targetId: dec.target_id, metric: dec.metric }); ctl.run((d) => ({ doc: C.setDecisions(d, out.decisions) })); };

  const dirty = SL.isDirty(save) || ["conflict", "validation", "error"].includes(save.phase);
  const requestClose = () => { if (save.saving) return; return dirty ? setCloseConfirm(true) : onClose(); };
  const discardAndClose = () => { if (closing || save.saving) return; setCloseConfirm(false); if (onDiscardSession) onDiscardSession(sessionRef.current); onClose(); };
  const saveAndClose = async () => {
    if (closing || save.saving) return;                 // never launch a second save
    setClosing(true);
    const res = await doSave();
    setClosing(false);
    // Close ONLY when the save resolved clean. A newer edit made while Save(A) ran keeps the editor open.
    if (res.ok && res.clean) { setCloseConfirm(false); onClose(); }
  };
  const [badgeText, badgeCls] = SAVE_BADGE[save.phase] || SAVE_BADGE.saved;

  const ToolBtn = ({ id, icon: Icon, label }) => (
    <Button size="sm" variant={mode === id ? "default" : "outline"} disabled={readOnly && id !== "select"} onClick={() => setMode(id)} data-testid={`tool-${id}`}><Icon className="mr-1 h-4 w-4" />{label}</Button>
  );

  // Side-choice resolver for connected complex roofs — shown when the engine returns placement_requests.
  const renderPlacementResolver = (requests, onApply) => (requests && requests.length > 0) ? (
    <div className="mt-2 rounded border border-violet-300 bg-violet-50 p-2" data-testid="placement-resolver">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-violet-700">Resolve placement</div>
      <div className="mt-1 text-[11px] text-violet-800">These planes can sit on more than one side. Pick where each attaches, then generate the roof.</div>
      {requests.map((r) => {
        const cur = resolutions.find((x) => String(x.plane) === String(r.plane));
        return <div key={r.plane} className="mt-2" data-testid={`placement-req-${r.plane}`}>
          <div className="text-[11px] text-slate-700">{r.prompt}</div>
          <select className="mt-1 w-full rounded border border-slate-300 bg-white px-1 py-1 text-[11px]" value={cur ? cur.side : ""} onChange={(e) => setSide(r.plane, e.target.value)} data-testid={`placement-side-${r.plane}`}>
            <option value="">Choose a side…</option>
            {r.options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
          </select>
        </div>;
      })}
      {!readOnly && <Button size="sm" className="mt-2" disabled={resolutions.length === 0} onClick={onApply} data-testid="placement-apply-btn">Generate with these placements</Button>}
    </div>
  ) : null;

  return <div className="fixed inset-0 z-50 flex flex-col bg-white" data-testid="roof-sketch-editor">
    <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-4 py-2">
      <div className="mr-2 text-sm font-semibold text-slate-800">Roof Sketch — {structure?.name || "Structure"}</div>
      {readOnly && <Badge variant="outline" className="text-slate-500" data-testid="sketch-readonly-badge">Read-only revision</Badge>}
      {!readOnly && <div className="flex gap-1">
        <ToolBtn id="select" icon={MousePointer2} label="Select" />
        <ToolBtn id="draw" icon={PenLine} label="Draw" />
        <ToolBtn id="facet" icon={Square} label="Facet" />
        <ToolBtn id="penetration" icon={Dot} label="Penetration" />
      </div>}
      {canGenerate && <Button size="sm" variant="secondary" onClick={generateProposed} data-testid="generate-proposed-btn"><Square className="mr-1 h-4 w-4" />Generate Proposed Sketch</Button>}
      {canRegenerate && <Button size="sm" variant="secondary" onClick={regenerateProposed} data-testid="regenerate-proposed-btn"><Square className="mr-1 h-4 w-4" />Generate New Proposal from Measurements</Button>}
      {!readOnly && <div className="ml-2 flex gap-1">
        <Button size="sm" variant={doc.edit_mode === "connected_graph" ? "secondary" : "ghost"} onClick={() => switchMode("connected_graph")} data-testid="mode-connected">Connected</Button>
        <Button size="sm" variant={doc.edit_mode === "manual_polygon" ? "secondary" : "ghost"} onClick={() => switchMode("manual_polygon")} data-testid="mode-manual">Manual</Button>
      </div>}
      <div className="ml-auto flex items-center gap-2">
        {!readOnly && <Button size="sm" variant="outline" disabled={!hist.canUndo} onClick={doUndo} data-testid="undo-btn"><Undo2 className="h-4 w-4" /></Button>}
        {!readOnly && <Button size="sm" variant="outline" disabled={!hist.canRedo} onClick={doRedo} data-testid="redo-btn"><Redo2 className="h-4 w-4" /></Button>}
        <Badge className={badgeCls} data-testid="save-state-badge">{badgeText}</Badge>
        {!readOnly && <Button size="sm" onClick={doSave} disabled={save.saving} data-testid="save-sketch-btn">{save.saving ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Save className="mr-1 h-4 w-4" />}Save Sketch</Button>}
        <Button size="sm" variant="ghost" onClick={requestClose} disabled={save.saving} data-testid="close-sketch-btn"><X className="mr-1 h-4 w-4" />Close</Button>
      </div>
    </div>

    {conflict && <div className="flex flex-wrap items-center gap-3 border-b border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-900" data-testid="conflict-banner">
      <span>This roof sketch was changed after you opened it (server v{conflict?.document_version ?? "?"}). Your unsaved sketch is preserved locally.</span>
      <Button size="sm" variant="outline" onClick={reloadServer} data-testid="reload-server-btn">Reload Server Version</Button>
    </div>}
    {validationMsg && <div className="border-b border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-900" data-testid="server-validation-banner">Server rejected the document: {validationMsg} — your draft is kept; fix and save again.</div>}

    {loading ? <div className="flex flex-1 items-center justify-center text-slate-400"><Loader2 className="mr-2 h-5 w-5 animate-spin" />Loading sketch…</div> :
      <div className="grid flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[1fr_360px]">
        <div className="min-h-[300px] p-3">
          <RoofSketchCanvas doc={doc} editMode={doc.edit_mode} mode={mode} selection={selection} onSelect={setSelection} readOnly={readOnly} ctl={ctl} />
        </div>
        <div className="flex flex-col overflow-y-auto border-l border-slate-200 p-3">
          {regen && <div ref={regenPanelRef} className="mb-3 rounded border-2 border-indigo-400 bg-indigo-50 p-2 shadow-md ring-2 ring-indigo-300/50" data-testid="regen-review-panel">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-indigo-700">New proposal vs current sketch</span>
              <Badge data-testid="regen-readiness" className={regen.comparison.readiness === "high_confidence" ? "bg-emerald-100 text-emerald-800" : regen.comparison.readiness === "needs_review" ? "bg-amber-100 text-amber-900" : "bg-rose-100 text-rose-800"}>
                {regen.comparison.readiness === "high_confidence" ? "High confidence" : regen.comparison.readiness === "needs_review" ? "Needs review" : "Insufficient information"}
              </Badge>
            </div>
            {regen.comparison.identical
              ? <div className="mt-1 text-[11px] text-slate-600" data-testid="regen-identical">No meaningful differences — the proposal matches your current sketch.</div>
              : <div className="mt-1 text-[11px] text-slate-700" data-testid="regen-diff-summary">
                  {regen.comparison.added_planes.length > 0 && <div data-testid="regen-added-planes">Added roof planes: {regen.comparison.added_planes.join(", ")}</div>}
                  {regen.comparison.removed_planes.length > 0 && <div data-testid="regen-removed-planes">Removed roof planes: {regen.comparison.removed_planes.join(", ")}</div>}
                  {regen.comparison.changed_planes.map((p) => <div key={p.measurement_facet_id} data-testid="regen-changed-plane">Plane {p.measurement_facet_id} changed: {p.changes.join(", ")}</div>)}
                  {regen.comparison.added_lines.length > 0 && <div data-testid="regen-added-lines">Added roof lines: {regen.comparison.added_lines.join(", ")}</div>}
                  {regen.comparison.removed_lines.length > 0 && <div data-testid="regen-removed-lines">Removed roof lines: {regen.comparison.removed_lines.join(", ")}</div>}
                  {regen.comparison.changed_lines.map((l) => <div key={l.measurement_edge_id} data-testid="regen-changed-line">Roof line {l.measurement_edge_id} changed: {l.changes.join(", ")}</div>)}
                </div>}
            {regen.comparison.unmapped_current_facets > 0 && <div className="mt-1 rounded bg-rose-100 px-2 py-1 text-[11px] text-rose-800" data-testid="regen-manual-warning">Warning: {regen.comparison.unmapped_current_facets} manual facet(s) not linked to Measurements would be lost if replaced.</div>}
            {regen.comparison.ambiguities.map((a, i) => <div key={i} className="mt-1 rounded bg-amber-100 px-2 py-1 text-[11px] text-amber-900" data-testid="regen-ambiguity">{a.message}</div>)}
            {!regen.comparison.proposal_has_geometry && <div className="mt-1 text-[11px] text-rose-700" data-testid="regen-no-geometry">The new proposal has no drawable geometry — keep your current sketch.</div>}
            {renderPlacementResolver(regen.result.placement_requests, regenerateProposed)}
            {regenConfirm && <div className="mt-2 rounded bg-rose-50 px-2 py-1 text-[11px] font-semibold text-rose-800" data-testid="regen-confirm-warning">This will REPLACE your current sketch geometry in the editor. It stays unsaved until you Save.</div>}
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" variant={regenConfirm ? "destructive" : "default"} disabled={!regen.comparison.proposal_has_geometry || regen.comparison.identical} onClick={regenUseProposed} data-testid={regenConfirm ? "regen-confirm-btn" : "regen-use-btn"}>{regenConfirm ? "Confirm Replace" : "Use Proposed Sketch"}</Button>
              <Button size="sm" variant="outline" onClick={regenKeepCurrent} data-testid="regen-keep-btn">Keep Current Sketch</Button>
              {regenConfirm && <Button size="sm" variant="ghost" onClick={() => setRegenConfirm(false)} data-testid="regen-cancel-confirm-btn">Cancel</Button>}
            </div>
          </div>}
          {proposal && <div className="mb-3 rounded border border-sky-200 bg-sky-50 p-2" data-testid="generate-proposal-panel">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-sky-700">Proposed sketch (unsaved)</span>
              <Badge data-testid="generate-readiness" className={proposal.readiness === "high_confidence" ? "bg-emerald-100 text-emerald-800" : proposal.readiness === "needs_review" ? "bg-amber-100 text-amber-900" : "bg-rose-100 text-rose-800"}>
                {proposal.readiness === "high_confidence" ? "High confidence" : proposal.readiness === "needs_review" ? "Needs review" : "Insufficient information"}
              </Badge>
            </div>
            <div className="mt-1 text-[11px] text-slate-600" data-testid="generate-meas-used">Measurements used: {proposal.mappings?.facets?.length || 0} planes · {proposal.mappings?.edges?.length || 0} roof lines{(proposal.mappings?.penetrations?.length || 0) > 0 ? ` · ${proposal.mappings.penetrations.length} penetrations` : ""}</div>
            {proposal.readiness === "insufficient_information" && <div className="mt-1 text-[11px] text-rose-700" data-testid="generate-insufficient">Not enough measurement detail to propose geometry. Draw manually.</div>}
            {(proposal.unresolved_planes?.length || 0) > 0 && <div className="mt-1 text-[11px] text-amber-800" data-testid="generate-unresolved">Unresolved roof planes: {proposal.unresolved_planes.join(", ")}</div>}
            {(proposal.ambiguities || []).map((a, i) => <div key={i} className="mt-1 rounded bg-amber-100 px-2 py-1 text-[11px] text-amber-900" data-testid="generate-ambiguity">{a.message}</div>)}
            {proposalPenPlacements.map((p) => <div key={p.id} className="mt-1 text-[11px] text-slate-600" data-testid="generate-pen-placement">Penetration {p.measurement_penetration_id} needs manual placement (no position in measurements).</div>)}
            {renderPlacementResolver(proposal.placement_requests, generateProposed)}
            {!readOnly && <div className="mt-2 flex gap-2">
              <Button size="sm" disabled={(proposal.document?.vertices?.length || 0) === 0} onClick={useProposed} data-testid="generate-use-btn">Use Proposed Sketch</Button>
              <Button size="sm" variant="outline" onClick={cancelProposed} data-testid="generate-cancel-btn">Cancel / Draw Manually</Button>
            </div>}
          </div>}
          <div className="mb-3" data-testid="sketch-measurements-ref">
            <button type="button" onClick={() => setShowMeas((v) => !v)} className="flex w-full items-center justify-between rounded bg-slate-100 px-2 py-1 text-left" data-testid="sketch-measurements-toggle">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-600">{showMeas ? "▾" : "▸"} Measurements</span>
              <span className="text-[11px] text-slate-500">{measRef.totals.area.toFixed(0)} SF · {measRef.totals.squares.toFixed(2)} sq · {measRef.totals.planeCount} planes</span>
            </button>
            {showMeas && <div className="mt-2 space-y-2 rounded border border-slate-200 p-2 text-xs" data-testid="sketch-measurements-panel">
              {measRef.planes.length === 0 && measRef.lines.length === 0 && measRef.pens.length === 0 && <div className="text-slate-400">No measurements entered for this structure yet.</div>}
              {measRef.planes.length > 0 && <div>
                <div className="mb-1 font-semibold text-slate-600">Roof planes</div>
                {measRef.planes.map((p) => <div key={String(p.id)} className="flex justify-between text-slate-700" data-testid={`sketch-meas-plane-${p.id}`}><span>{p.label}</span><span>{rsPitch(p.pitch_rise)} · {p.area.toFixed(0)} SF{p.width != null && p.length != null ? ` (${p.width}×${p.length})` : ""}</span></div>)}
              </div>}
              {measRef.lines.length > 0 && <div>
                <div className="mb-1 font-semibold text-slate-600">Roof lines</div>
                {measRef.lines.map((l) => <div key={l.type} className="flex justify-between text-slate-700" data-testid={`sketch-meas-line-${l.type}`}><span>{RS_EDGE_LABELS[l.type] || l.type}</span><span>{l.lf.toFixed(1)} LF</span></div>)}
              </div>}
              {measRef.pens.length > 0 && <div>
                <div className="mb-1 font-semibold text-slate-600">Penetrations</div>
                {measRef.pens.map((p) => <div key={p.type} className="flex justify-between text-slate-700" data-testid={`sketch-meas-pen-${p.type}`}><span>{RS_PEN_LABELS[p.type] || p.type}</span><span>× {p.qty}</span></div>)}
              </div>}
            </div>}
          </div>
          <SketchInspector doc={doc} selection={selection} cmd={cmd} readOnly={readOnly} relFacets={relFacets} relEdges={relEdges} />
          <div className="mt-3">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Validation</div>
            {validation.errors.length === 0 && validation.warnings.length === 0 && <div className="text-xs text-emerald-700" data-testid="validation-ok">No issues.</div>}
            {validation.errors.map((e, i) => <div key={`e${i}`} className="rounded bg-rose-50 px-2 py-1 text-xs text-rose-800" data-testid="validation-error">⛔ {e.message}{e.facet_id ? ` (${e.facet_id})` : ""}</div>)}
            {validation.warnings.map((w, i) => <div key={`w${i}`} className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-800" data-testid="validation-warning">⚠ {w.message}</div>)}
          </div>
          {pendingDecisions.length > 0 && <div className="mt-3" data-testid="pending-proposals">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Pending proposals</div>
            {pendingDecisions.map((d) => {
              const rel = d.target_type === "facet" ? relFacetsById[d.target_id] : relEdgesById[d.target_id];
              const unit = d.metric === "area_sqft" ? "SF" : "LF";
              const cur = rel ? (d.target_type === "facet" ? rel.area_sqft : rel.length_ft) : null;
              const canApply = PL.canApplyPending(d, validIdSet);
              return <div key={`${d.target_type}-${d.target_id}-${d.metric}`} className="rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900" data-testid={`pending-${d.target_id}`}>
                <div>Proposed: <b>{Number(d.proposed_value ?? d.value).toFixed(unit === "SF" ? 0 : 1)} {unit}</b> · Worksheet currently: {cur == null ? "—" : `${Number(cur).toFixed(unit === "SF" ? 0 : 1)} ${unit}`}</div>
                {!canApply && <div className="mt-1 text-[11px] text-rose-700" data-testid={`pending-invalid-${d.target_id}`}>This pending proposal's measurement mapping is no longer valid. Re-map this sketch entity or choose Keep Current.</div>}
                {!readOnly && <div className="mt-1 flex gap-2">
                  <Button size="sm" disabled={!canApply} onClick={() => applyPending(d)} data-testid={`apply-pending-${d.target_id}`}>Apply to Worksheet Draft</Button>
                  <Button size="sm" variant="outline" onClick={() => keepPending(d)} data-testid={`keep-pending-${d.target_id}`}>Keep Current</Button>
                </div>}
              </div>;
            })}
          </div>}
          <div className="mt-3">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Proposals</div>
            <ProposalPanel doc={doc} proposals={proposals} relFacetsById={relFacetsById} relEdgesById={relEdgesById} onAccept={acceptProposal} onKeep={keepProposal} readOnly={readOnly} />
          </div>
        </div>
      </div>}

    {closeConfirm && <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/40" data-testid="close-confirm">
      <div className="w-[380px] rounded-lg bg-white p-4 shadow-xl">
        <div className="text-sm font-semibold text-slate-800">You have unsaved roof sketch changes.</div>
        <div className="mt-1 text-sm text-slate-500">Save before closing, discard your changes, or keep editing. Discarding also rolls back any proposal values this editor applied to the Worksheet draft (your other edits are preserved).</div>
        <div className="mt-4 flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={() => setCloseConfirm(false)} disabled={closing} data-testid="close-continue">Continue Editing</Button>
          <Button size="sm" variant="outline" className="text-rose-600" onClick={discardAndClose} disabled={closing} data-testid="close-discard">Discard Changes</Button>
          <Button size="sm" onClick={saveAndClose} disabled={closing || save.saving} data-testid="close-save">{closing ? <><Loader2 className="mr-1 h-4 w-4 animate-spin" />Saving…</> : "Save & Close"}</Button>
        </div>
      </div>
    </div>}
  </div>;
}

// Field Roof Sketch screen — orchestrates load (local-draft authoritative), the touch canvas, the
// inspector, tools, undo/redo, validation, and HONEST on-device draft status. Uses the pure wiring
// adapters so the production paths are the ones under contract. B2A = LOCAL draft only (no PUT — B3).
import React, { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { View, Text, TouchableOpacity, StyleSheet, ScrollView, Alert, AppState } from "react-native";
import * as RS from "@roofspan/roof-sketch-core";
import { createFieldEditor } from "../roofSketchFieldController";
import { createSketchSyncCoordinator } from "../roofSketchSyncCoordinator";
import * as WIRE from "../roofSketchFieldWiring";
import { loadSketchDraft, saveSketchDraftStrict, cache, cacheMeasurementDetail } from "../cache";
import { queueMutation, onSyncChange, isSyncing, currentSketchMutation, currentMeasurementMutation, syncNow, resolveSketchConflictUseOffice, resolveSketchConflictKeepLocal } from "../sync";
import { conflictReview } from "../roofSketchConflict";
import * as RECON from "../roofProposalReconcile";
import RoofSketchCanvas from "../components/RoofSketchCanvas";
import SketchInspector from "../components/SketchInspector";
import SketchConflictReview from "../components/SketchConflictReview";
import SketchMeasurementsPanel from "../components/SketchMeasurementsPanel";
import ProposalPanel from "../components/ProposalPanel";
import { scopeStructureForGenerator } from "../sketchMeasurementsSummary";
import { C } from "../theme";

const TOOLS = [["select", "Select"], ["draw", "Draw"], ["facet", "Facet"], ["penetration", "Roof feature"], ["pan", "Pan"]];

export default function RoofSketch({ route }) {
  const { revision_id, structure_id, structure_name = "Roof", editable = true } = route.params || {};
  const readOnly = !editable;
  const [ready, setReady] = useState(false);
  const [tool, setTool] = useState("select");
  const [editMode, setEditMode] = useState("connected_graph");
  const [selection, setSelection] = useState(null);
  const [status, setStatus] = useState(readOnly ? "Locked" : "Loading");
  const [resetToken, setResetToken] = useState(0);
  const [conflict, setConflict] = useState(null);       // B3C: Base/Local/Office review, or null
  const [locked, setLocked] = useState(false);          // B3D: revision locked live while editor is open
  const [reviewOpen, setReviewOpen] = useState(false);  // B3C: conflict review modal visibility
  const [measDetail, setMeasDetail] = useState(null);   // Phase C: authoritative measurement revision detail
  const [measMutState, setMeasMutState] = useState(null); // Phase C: measurement_update mutation state
  const [proposal, setProposal] = useState(null);          // Generate-Proposed preview (unsaved), or null
  const [, bump] = useState(0);
  const rerender = useCallback(() => bump((x) => x + 1), []);
  const editorRef = useRef(null);
  const coordRef = useRef(null);
  const stageTimer = useRef(null);
  const syncStateRef = useRef({ seq: 0, acked: 0, localSave: null }); // latest-wins refresh state
  const editedRef = useRef(false);     // has the rep committed a local edit this session?
  const editingBlockedRef = useRef(false);  // B3C: fresh editingBlocked for stable useCallback handlers
  const runningRef = useRef(false);    // sync engine actively processing (from sync_start/sync_end)
  const [size, setSize] = useState({ width: 360, height: 480 });

  useEffect(() => {
    let alive = true;
    (async () => {
      const draft = await loadSketchDraft(revision_id, structure_id);
      let sketchResult = null;
      if (!draft) { try { sketchResult = await cache.sketch(revision_id, structure_id); } catch (e) { sketchResult = null; } }
      if (!alive) return;
      const { initial, statusMeta } = WIRE.resolveFieldSketchLoad({ draft, sketchResult, structureId: structure_id });
      editorRef.current = createFieldEditor(WIRE.makeFieldEditorArgs({
        revision_id, structure_id, initial,
        persist: (d) => saveSketchDraftStrict(revision_id, structure_id, d),
      }));
      coordRef.current = createSketchSyncCoordinator({ queueMutation });
      editedRef.current = initial.source === "local_draft";   // reopened local work is already "edited"
      setEditMode(initial.editMode);
      setStatus(readOnly ? "Locked" : initialStatus(initial, statusMeta));
      setReady(true);
    })();
    return () => { alive = false; if (editorRef.current) editorRef.current.flush(); };
  }, [revision_id, structure_id]);

  // B3B2: structure-specific live sync status + CAS-metadata adoption for the OPEN editor. Reads ONLY
  // this structure's deterministic mutation (never the global queue), adopts newly acknowledged CAS
  // metadata without touching geometry/history/generation, and derives the honest status label.
  const refreshSync = useCallback(async () => {
    const ed = editorRef.current;
    if (!ed || readOnly) return;
    const seq = WIRE.nextRefreshSeq(syncStateRef.current);   // claim this refresh's sequence number
    const m = await currentSketchMutation(revision_id, structure_id);
    // Untouched sketch (server/cache/new) with no mutation: keep its initial label — an unrelated
    // onSyncChange() event (another structure / a photo) must NOT relabel it.
    if (!editedRef.current && !m) return;
    const draft = await loadSketchDraft(revision_id, structure_id);
    if (seq !== syncStateRef.current.seq) return;   // a newer refresh superseded this one
    // B3D: a live immutable-revision lock for THIS structure surfaces the locked banner and blocks
    // editing immediately. It preserves the local draft (never adopts stale server/cache over newer
    // local work — applySketchRefresh only advances CAS metadata monotonically, never the geometry).
    setLocked(WIRE.deriveSketchLocked(m));
    // B3C: a real 409 for THIS structure surfaces the Base/Local/Office review and locks editing.
    setConflict(m && m.state === "conflict" ? conflictReview(m, draft) : null);
    // Latest-wins: discard this result if a newer refresh has since started (out-of-order async reads).
    WIRE.applySketchRefresh({
      seq, state: syncStateRef.current, editor: ed, mutation: m, draft,
      running: runningRef.current || isSyncing(), setStatus,
    });
  }, [readOnly, revision_id, structure_id]);

  // Subscribe to the EXISTING sync events only (no polling/timer). Refresh this structure's status when
  // the queue changes or a sync pass starts/ends.
  useEffect(() => {
    if (!ready || readOnly) return;
    const unsub = onSyncChange((evt) => {
      if (evt.type === "sync_start") runningRef.current = true;
      else if (evt.type === "sync_end") runningRef.current = false;
      refreshSync();
    });
    refreshSync();
    return unsub;
  }, [ready, readOnly, refreshSync]);

  const editor = editorRef.current;
  const conflictActive = !!conflict;                  // B3C: a real 409 is awaiting explicit resolution
  const editingBlocked = WIRE.editingLocked({ readOnly, conflict, locked });  // no edits/undo/redo/mode/Save/build while blocked
  editingBlockedRef.current = editingBlocked;         // fresh value for stable useCallback handlers
  const validation = useMemo(() => (editor ? editor.validate() : { valid: true, errors: [], warnings: [] }), [ready, status, selection]);

  // B3C: when a conflict becomes active, cancel any in-flight Facet/Manual build so no build-commit route
  // can survive into the locked state (defensive, in addition to the disabled UI + handler guards below).
  useEffect(() => {
    if (!conflictActive) return;
    setSelection((sel) => (sel && (sel.type === "facet_build" || sel.type === "manual_build") ? null : sel));
    setResetToken((x) => x + 1);
  }, [conflictActive]);

  // B3C — Use Office Version: discard local unsynced work, adopt the authoritative Office document into
  // the OPEN editor (fresh history) and return status to Synced to Office (atomic + generation-checked in
  // storage). Invalidate any in-flight refresh (latest-wins) so a stale pre-resolution refresh started
  // from the conflict state cannot overwrite the resolved Synced-to-Office status.
  const useOfficeVersion = useCallback(async () => {
    const plan = await resolveSketchConflictUseOffice(revision_id, structure_id);
    if (plan.action !== "use_office") { setReviewOpen(false); refreshSync(); return; }
    WIRE.nextRefreshSeq(syncStateRef.current);   // supersede any refresh that began from the conflict state
    if (editorRef.current) {
      editorRef.current.adoptOfficeDocument({ document: plan.editor.document, documentVersion: plan.editor.documentVersion, editMode: plan.editor.editMode });
      setEditMode(plan.editor.editMode);
    }
    editedRef.current = false;                 // no pending local work remains
    syncStateRef.current.acked = 0;
    syncStateRef.current.localSave = null;
    setSelection(null); setConflict(null); setReviewOpen(false);
    setStatus("Synced to Office"); rerender();
  }, [revision_id, structure_id, refreshSync, rerender]);

  // B3C — Keep Local Draft: keep local geometry, rebase onto the Office base/version, and re-stage as a
  // fresh pending mutation (expected_version = Office version). Status stays pending until Office acks.
  const keepLocalDraft = useCallback(async () => {
    const plan = await resolveSketchConflictKeepLocal(revision_id, structure_id);
    if (plan.action !== "keep_local") { setReviewOpen(false); refreshSync(); return; }
    if (editorRef.current) editorRef.current.adoptServerVersion({ documentVersion: plan.editor.documentVersion, baseServerDocument: plan.editor.baseServerDocument });
    setConflict(null); setReviewOpen(false);
    refreshSync();
  }, [revision_id, structure_id, refreshSync]);


  // Stage the current committed generation into the EXISTING durable queue, but only once it is locally
  // durable (B3A). Reuses the shared coordinator; no new network/retry logic here.
  const stageNow = useCallback(async () => {
    if (!editor || !coordRef.current || editingBlockedRef.current) return;
    // Stage the controller's authoritative committed CAS snapshot (never the visual document).
    await WIRE.stageFromController(editor, coordRef.current, { revisionId: revision_id, structureId: structure_id });
  }, [editor, revision_id, structure_id]);

  // After any committed edit, drain the serialized chain, report the HONEST result, and debounce-stage.
  const settle = useCallback(() => {
    if (!editor || editingBlockedRef.current) return;
    editedRef.current = true;
    syncStateRef.current.localSave = "Saving on device…";
    setStatus("Saving on device…"); rerender();
    editor.flush().then((res) => { syncStateRef.current.localSave = WIRE.localSaveStatus(res); refreshSync(); });
    if (stageTimer.current) clearTimeout(stageTimer.current);
    stageTimer.current = setTimeout(() => { stageTimer.current = null; stageNow().then(() => refreshSync()); }, 800);
  }, [editor, rerender, stageNow, refreshSync]);

  // B3D: app lifecycle durability + recovery (event-driven; NO polling).
  //  • Background/inactive: flush the LATEST COMMITTED generation to durable local persistence, THEN
  //    stage it into the durable deterministic queue — in that exact order. stageFromController awaits
  //    the editor's serialized persist chain, so an in-flight persist safely completes first and the
  //    queue can never capture an older generation. If editing is blocked (locked/conflict) we still
  //    flush so the unsynced draft is preserved on device, but never stage against a locked revision.
  //  • Foreground: re-run the same generation/CAS-safe refresh (existing auto-sync re-sends pending
  //    work on foreground; a now-locked revision surfaces via that send's lock response).
  useEffect(() => {
    if (!ready || readOnly) return;
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "background" || s === "inactive") {
        if (stageTimer.current) { clearTimeout(stageTimer.current); stageTimer.current = null; }
        const ed = editorRef.current;
        if (!ed) return;
        if (editedRef.current && !editingBlockedRef.current) {
          stageNow().then(() => refreshSync()).catch(() => {});
        } else {
          ed.flush().catch(() => {});   // preserve the latest committed draft durably, even when blocked
        }
      } else if (s === "active") {
        refreshSync();
      }
    });
    return () => { try { sub && sub.remove && sub.remove(); } catch (e) {} };
  }, [ready, readOnly, stageNow, refreshSync]);

  // Phase C: load the authoritative Measurement Revision detail + the measurement_update mutation state,
  // then FINALIZE any pending acceptances whose value the revision now actually holds (durable promotion,
  // skipped while editing is blocked so a locked revision is never mutated). Event-driven off the queue.
  const refreshMeasurement = useCallback(async () => {
    try {
      const res = await cache.measurement(revision_id);
      const detail = res && res.data ? res.data : null;
      const mm = await currentMeasurementMutation(revision_id);
      setMeasDetail(detail);
      setMeasMutState(mm ? mm.state : null);
      const ed = editorRef.current;
      if (ed && !editingBlockedRef.current) {
        const fin = RECON.finalizeDecisions(ed.document, { measurementDetail: detail, measurementMutationState: mm ? mm.state : null });
        if (fin.changed) { ed.commit(fin.doc); settle(); }
      }
    } catch (e) { /* offline/cache miss — proposals simply compare against what we have */ }
  }, [revision_id, settle]);

  useEffect(() => {
    if (!ready) return;
    refreshMeasurement();
    const unsub = onSyncChange(() => refreshMeasurement());
    return unsub;
  }, [ready, refreshMeasurement]);

  // Accept Proposed: route the value through the EXISTING Field measurement_update workflow (newest
  // durable revision detail, ONLY the mapped value changed, all else preserved, coalescing + If-Match),
  // AND record a durable pending_accept provenance decision on the sketch. Never reports Accepted here —
  // promotion happens only in refreshMeasurement once the authoritative revision holds the value.
  const onAcceptProposal = useCallback(async (row) => {
    const ed = editorRef.current;
    if (!ed || editingBlockedRef.current || !row || !row.canAccept || !row.relational_id) return;
    const rec = { target_type: row.target_type, metric: row.metric, target_id: row.sketch_id };
    const res = await cache.measurement(revision_id);
    const current = res && res.data ? res.data : measDetail;
    const upd = RECON.buildAcceptedMeasurementUpdate(current, { targetType: row.target_type, relationalId: row.relational_id, metric: row.metric, proposedValue: row.proposed });
    if (upd.changed) {
      await cacheMeasurementDetail(upd.nextDetail);
      await queueMutation({ kind: "measurement_update", method: "put", path: `/mobile/measurements/${revision_id}`, body: upd.body, ifMatch: upd.ifMatch, label: "Roof measurement" });
    }
    ed.commit(RECON.acceptProposalDecision(ed.document, rec, row.relational_id, row.proposed));
    settle();
    refreshMeasurement();
  }, [revision_id, measDetail, settle, refreshMeasurement]);

  // Keep Current: provenance only — no measurement mutation. Durable via the sketch draft/queue.
  const onKeepCurrent = useCallback((row) => {
    const ed = editorRef.current;
    if (!ed || editingBlockedRef.current || !row || !row.canKeep) return;
    const rec = { target_type: row.target_type, metric: row.metric, target_id: row.sketch_id };
    ed.commit(RECON.keepCurrentDecision(ed.document, rec, row.relational_id || row.sketch_id));
    settle();
    rerender();
  }, [settle, rerender]);

  const onError = (reason) => Alert.alert("Cannot do that", humanReason(reason));

  const doCommit = (arg) => {
    if (!editor || editingBlocked) return;
    const next = typeof arg === "function" ? arg(editor.document) : arg;
    if (!next || next === editor.document) return;
    editor.commit(next); settle();
  };

  const clearBuild = () => setResetToken((x) => x + 1);
  const changeTool = (t) => { setTool(t); setSelection(null); clearBuild(); };
  const changeMode = (m) => { if (editingBlocked || !editor) return; setEditMode(m); editor.setEditMode(m); setSelection(null); clearBuild(); settle(); };

  // B3C: Undo/Redo must be blocked BEFORE they mutate the controller (settle()'s guard runs too late).
  // Uses the same fresh editingBlockedRef as the other defensive routes — not just the button's disabled.
  const doUndo = () => { if (!editor || editingBlockedRef.current) return; editor.undo(); settle(); };
  const doRedo = () => { if (!editor || editingBlockedRef.current) return; editor.redo(); settle(); };

  const createFacetFromSelection = () => {
    if (!editor || editingBlocked || !selection || selection.type !== "facet_build") return;
    const r = WIRE.commitFacetCreate(editor.document, selection.edgeIds);
    if (!r.ok) { onError(r.reason); return; }
    editor.commit(r.doc); setSelection({ type: "facet", id: r.facetId }); clearBuild(); settle();
  };
  const createManualPolygon = () => {
    if (!editor || editingBlocked || !selection || selection.type !== "manual_build") return;
    const r = WIRE.commitManualCreate(editor.document, selection.vertexIds);
    if (!r.ok) { onError(r.reason); return; }
    editor.commit(r.doc); setSelection({ type: "facet", id: r.facetId }); clearBuild(); settle();
  };
  const cancelBuild = () => { setSelection(null); clearBuild(); };
  const retrySave = () => {
    if (!editor) return;
    syncStateRef.current.localSave = "Saving on device…";
    setStatus("Saving on device…");
    editor.retry().then((res) => {
      syncStateRef.current.localSave = WIRE.localSaveStatus(res);
      syncNow().catch(() => {});   // also re-attempt server sync (for "Sync issue — retry needed")
      refreshSync();
    });
  };

  if (!ready || !editor) return <View style={sx.centered}><Text style={sx.dim}>{status}…</Text></View>;

  const scaleResolved = editor.document.scale && editor.document.scale.resolved;
  const proposals = RECON.buildFieldProposals({
    doc: editor.document, measurementDetail: measDetail, structureId: structure_id,
    editingBlocked, measurementMutationState: measMutState,
  });

  // --- Generate Proposed Sketch (Field, empty-sketch only) ----------------------------------------
  // Offered ONLY when: editable/unlocked, a brand-new sketch (no saved server sketch, no local draft),
  // and the canvas is empty. Runs the SAME shared generator locally from the offline-cached measurement
  // detail — no network, no Measurement mutation, no server save. Preview is visual-only.
  const genDoc = editor.document;
  const isEmptyDoc = (genDoc.facets?.length || 0) === 0 && (genDoc.edges?.length || 0) === 0 && (genDoc.vertices?.length || 0) === 0;
  const canGenerate = !editingBlocked && editor.source === "new" && isEmptyDoc && !proposal;
  const generateProposed = () => {
    if (editingBlockedRef.current || !measDetail) {
      if (!measDetail) Alert.alert("Measurements unavailable", "Roof measurements for this structure aren't available on this device yet.");
      return;
    }
    const res = RS.generateSketchGeometry(scopeStructureForGenerator(measDetail, structure_id));
    setProposal(res);
    if (res.document && (res.document.vertices?.length || 0) > 0) { editor.preview(res.document); }
    setSelection(null); setResetToken((x) => x + 1); rerender();
  };
  const useProposed = () => {
    if (editingBlockedRef.current || !proposal || !proposal.document || (proposal.document.vertices?.length || 0) === 0) return;
    editor.commit(proposal.document);   // becomes the working draft via the existing durable pipeline
    setProposal(null); setSelection(null); setResetToken((x) => x + 1);
    settle();                            // autosave (SQLite) + debounce-stage into the offline queue
  };
  const cancelProposed = () => {
    editor.restore();                    // exact pre-generation state (preview never committed)
    setProposal(null); setSelection(null); setResetToken((x) => x + 1); rerender();
  };
  const proposalHasGeometry = !!(proposal && proposal.document && (proposal.document.vertices?.length || 0) > 0);

  return (
    <View style={sx.container} testID="roof-sketch-screen">
      <View style={sx.statusBar}>
        <Text style={sx.structure} testID="roof-sketch-title">{structure_name}</Text>
        <View style={sx.statusRight}>
          <Text style={[sx.status, conflictActive && sx.statusConflict]} testID="roof-sketch-status">{status}</Text>
          {conflictActive ? <TouchableOpacity testID="review-conflict" onPress={() => setReviewOpen(true)} style={sx.review}><Text style={sx.retryText}>Review</Text></TouchableOpacity> : null}
          {(status === "Could not save on device" || status === "Sync issue — retry needed") ? <TouchableOpacity testID="retry-save" onPress={retrySave} style={sx.retry}><Text style={sx.retryText}>Retry</Text></TouchableOpacity> : null}
        </View>
      </View>

      <View style={sx.controlRow}>
        <View style={sx.modeToggle}>
          <TouchableOpacity testID="mode-connected" disabled={editingBlocked} onPress={() => changeMode("connected_graph")} style={[sx.modeBtn, editMode === "connected_graph" && sx.modeOn, editingBlocked && sx.disabled]}><Text style={[sx.modeText, editMode === "connected_graph" && sx.modeTextOn]}>Connected</Text></TouchableOpacity>
          <TouchableOpacity testID="mode-manual" disabled={editingBlocked} onPress={() => changeMode("manual_polygon")} style={[sx.modeBtn, editMode === "manual_polygon" && sx.modeOn, editingBlocked && sx.disabled]}><Text style={[sx.modeText, editMode === "manual_polygon" && sx.modeTextOn]}>Manual</Text></TouchableOpacity>
        </View>
        <View style={sx.modeToggle}>
          <TouchableOpacity testID="undo-btn" disabled={editingBlocked || !editor.canUndo()} onPress={doUndo} style={[sx.modeBtn, (editingBlocked || !editor.canUndo()) && sx.disabled]}><Text style={sx.modeText}>Undo</Text></TouchableOpacity>
          <TouchableOpacity testID="redo-btn" disabled={editingBlocked || !editor.canRedo()} onPress={doRedo} style={[sx.modeBtn, (editingBlocked || !editor.canRedo()) && sx.disabled]}><Text style={sx.modeText}>Redo</Text></TouchableOpacity>
          <TouchableOpacity testID="save-sketch-btn" disabled={editingBlocked} onPress={() => { if (stageTimer.current) clearTimeout(stageTimer.current); stageNow().then(() => refreshSync()); }} style={[sx.modeBtn, sx.modeOn, editingBlocked && sx.disabled]}><Text style={sx.modeTextOn}>Save Sketch</Text></TouchableOpacity>
        </View>
      </View>

      <View style={sx.canvasWrap} onLayout={(e) => { const { width, height } = e.nativeEvent.layout; setSize({ width, height }); }}>
        <RoofSketchCanvas
          editor={editor} tool={tool} editMode={editMode} readOnly={editingBlocked}
          selection={selection} onSelect={setSelection} onChanged={settle} onError={onError}
          canvasSize={size} resetToken={resetToken}
        />
        {scaleResolved ? null : <Text style={sx.calibHint} testID="calibrate-hint">Calibrate scale to display edge dimensions.</Text>}
      </View>

      {selection && selection.type === "facet_build" ? (
        <View style={sx.buildRow}>
          <TouchableOpacity testID="create-facet" style={[sx.primary, (selection.edgeIds || []).length < 3 && sx.disabled]} disabled={(selection.edgeIds || []).length < 3} onPress={createFacetFromSelection}><Text style={sx.primaryText}>Create Facet ({(selection.edgeIds || []).length})</Text></TouchableOpacity>
          <TouchableOpacity testID="cancel-facet" style={sx.ghost} onPress={cancelBuild}><Text style={sx.ghostText}>Cancel</Text></TouchableOpacity>
        </View>
      ) : null}

      {selection && selection.type === "manual_build" ? (
        <View style={sx.buildRow}>
          <TouchableOpacity testID="create-polygon" style={[sx.primary, (selection.vertexIds || []).length < 3 && sx.disabled]} disabled={(selection.vertexIds || []).length < 3} onPress={createManualPolygon}><Text style={sx.primaryText}>Create Polygon ({(selection.vertexIds || []).length})</Text></TouchableOpacity>
          <TouchableOpacity testID="cancel-polygon" style={sx.ghost} onPress={cancelBuild}><Text style={sx.ghostText}>Cancel</Text></TouchableOpacity>
        </View>
      ) : null}

      {!validation.valid || (validation.warnings || []).length ? (
        <ScrollView horizontal style={sx.validation} testID="validation-panel">
          {(validation.errors || []).map((e, i) => <Text key={"e" + i} style={sx.vErr}>{humanValidation(e.code)}</Text>)}
          {(validation.warnings || []).map((w, i) => <Text key={"w" + i} style={sx.vWarn}>{humanValidation(w.code)}</Text>)}
        </ScrollView>
      ) : null}

      {readOnly ? <Text style={sx.locked} testID="readonly-banner">This measurement revision is locked.</Text> : null}
      {locked && !readOnly ? <Text style={sx.locked} testID="revision-locked-banner">Measurement revision locked — changes require a new measurement revision.</Text> : null}
      {conflictActive ? <Text style={sx.conflictBanner} testID="conflict-banner">Sync conflict — review required before editing.</Text> : null}

      {canGenerate ? (
        <TouchableOpacity testID="field-generate-btn" onPress={generateProposed} style={sx.genCta}>
          <Text style={sx.genCtaText}>Generate Proposed Sketch</Text>
        </TouchableOpacity>
      ) : null}

      {proposal ? (
        <View style={sx.genPanel} testID="field-generate-panel">
          <View style={sx.genHead}>
            <Text style={sx.genTitle}>Proposed sketch (unsaved)</Text>
            <Text style={[sx.genBadge, proposal.readiness === "high_confidence" ? sx.genBadgeHi : proposal.readiness === "needs_review" ? sx.genBadgeRev : sx.genBadgeIns]} testID="field-generate-readiness">
              {proposal.readiness === "high_confidence" ? "High confidence" : proposal.readiness === "needs_review" ? "Needs review" : "Insufficient information"}
            </Text>
          </View>
          <Text style={sx.genMeta} testID="field-generate-meas-used">Measurements used: {proposal.mappings?.facets?.length || 0} planes · {proposal.mappings?.edges?.length || 0} roof lines</Text>
          {proposal.readiness === "insufficient_information" ? <Text style={sx.genIns} testID="field-generate-insufficient">Not enough measurement detail to propose geometry. Draw manually.</Text> : null}
          {(proposal.unresolved_planes?.length || 0) > 0 ? <Text style={sx.genWarn} testID="field-generate-unresolved">Unresolved roof planes: {proposal.unresolved_planes.join(", ")}</Text> : null}
          {(proposal.ambiguities || []).map((a, i) => <Text key={i} style={sx.genAmb} testID="field-generate-ambiguity">{a.message}</Text>)}
          {(proposal.document?.penetrations || []).filter((p) => p.position_known === false).map((p) => <Text key={p.id} style={sx.genMeta} testID="field-generate-pen-placement">Penetration {p.measurement_penetration_id} needs manual placement.</Text>)}
          <View style={sx.genRow}>
            <TouchableOpacity testID="field-generate-use-btn" disabled={!proposalHasGeometry} onPress={useProposed} style={[sx.primary, !proposalHasGeometry && sx.disabled]}><Text style={sx.primaryText}>Use Proposed Sketch</Text></TouchableOpacity>
            <TouchableOpacity testID="field-generate-cancel-btn" onPress={cancelProposed} style={sx.ghost}><Text style={sx.ghostText}>Cancel / Draw Manually</Text></TouchableOpacity>
          </View>
        </View>
      ) : null}

      <SketchMeasurementsPanel measDetail={measDetail} structureId={structure_id} />

      <ProposalPanel rows={proposals} onAccept={onAcceptProposal} onKeep={onKeepCurrent} />

      <View style={sx.toolStrip}>
        {TOOLS.map(([t, label]) => (
          <TouchableOpacity key={t} testID={`tool-${t}`} disabled={editingBlocked && t !== "select" && t !== "pan"}
            onPress={() => changeTool(t)} style={[sx.tool, tool === t && sx.toolOn, (editingBlocked && t !== "select" && t !== "pan") && sx.disabled]}>
            <Text style={[sx.toolText, tool === t && sx.toolTextOn]}>{label}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {selection && ["edge", "facet", "vertex", "penetration"].includes(selection.type) ? (
        <SketchInspector doc={editor.document} selection={selection} readOnly={editingBlocked}
          onCommit={doCommit} onError={onError} onClose={() => setSelection(null)} />
      ) : null}

      <SketchConflictReview
        visible={reviewOpen && conflictActive}
        review={conflict}
        onUseOffice={useOfficeVersion}
        onKeepLocal={keepLocalDraft}
        onClose={() => setReviewOpen(false)}
      />
    </View>
  );
}

function initialStatus(initial, meta) {
  if (initial.source === "local_draft") return "Saved on device";
  if (initial.source === "server") return meta && meta.stale ? "Offline/cached sketch" : "Synced to Office";
  return "New sketch";
}
function humanReason(reason) {
  const map = {
    edge_protected: "This edge is mapped, confirmed, or locked and cannot be changed.",
    duplicate_edge_creation: "That would create a duplicate edge.",
    facet_would_be_invalid: "That change would make a facet invalid.",
    connected_graph_required: "Switch to Connected mode for that operation.",
    protected_edge_collapse: "A protected edge would be removed — not allowed.",
    type_conflict: "Choose the resulting edge type before joining.",
    middle_vertex_has_additional_connections: "That vertex has other connections and cannot be joined.",
    duplicate_outer_edge: "Joining would duplicate an existing edge.",
    facet_needs_three_edges: "Select at least 3 edges that form a closed loop.",
    polygon_needs_three_points: "A polygon needs at least 3 points.",
  };
  return map[reason] || "That operation is not allowed here.";
}
function humanValidation(code) {
  const map = {
    open_facet_loop: "Open facet boundary", duplicate_edge: "Duplicate edge", duplicate_facet: "Duplicate facet",
    self_intersection: "Self-intersecting facet", disconnected_component: "Disconnected roof section",
    facet_missing_edges: "Facet needs a closed edge loop", broken_edge_reference: "Facet references a missing edge",
    non_positive_area: "Facet has no area", zero_length_edge: "Zero-length edge", dangling_edge: "Edge missing a vertex",
    possible_overlap: "Facets overlap", possible_gap: "Possible gap between facets", facet_boundary_mismatch: "Facet boundary mismatch",
  };
  return map[code] || code;
}

const sx = StyleSheet.create({
  container: { flex: 1, backgroundColor: C.bg },
  centered: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: C.bg },
  dim: { color: "#94A3B8" },
  statusBar: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: 14, paddingVertical: 8 },
  statusRight: { flexDirection: "row", alignItems: "center", gap: 8 },
  structure: { color: "#fff", fontSize: 16, fontWeight: "800" },
  status: { color: "#94A3B8", fontSize: 12, fontWeight: "600" },
  statusConflict: { color: "#FCA5A5" },
  retry: { backgroundColor: C.danger, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 8 },
  review: { backgroundColor: "#B45309", paddingHorizontal: 10, paddingVertical: 4, borderRadius: 8 },
  retryText: { color: "#fff", fontWeight: "800", fontSize: 12 },
  controlRow: { flexDirection: "row", justifyContent: "space-between", paddingHorizontal: 12, marginBottom: 6 },
  modeToggle: { flexDirection: "row", backgroundColor: "#1E293B", borderRadius: 10, padding: 3 },
  modeBtn: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8 },
  modeOn: { backgroundColor: C.brand },
  modeText: { color: "#CBD5E1", fontWeight: "700", fontSize: 13 },
  modeTextOn: { color: "#fff" },
  disabled: { opacity: 0.4 },
  canvasWrap: { flex: 1, marginHorizontal: 8, borderRadius: 12, overflow: "hidden" },
  calibHint: { position: "absolute", top: 8, left: 8, color: "#FBBF24", fontSize: 12, backgroundColor: "rgba(0,0,0,0.4)", paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8 },
  buildRow: { flexDirection: "row", padding: 10, gap: 10 },
  primary: { backgroundColor: C.brand, paddingHorizontal: 16, paddingVertical: 12, borderRadius: 10 },
  primaryText: { color: "#fff", fontWeight: "800" },
  ghost: { paddingHorizontal: 16, paddingVertical: 12, borderRadius: 10, borderWidth: 1, borderColor: "#475569" },
  ghostText: { color: "#CBD5E1", fontWeight: "700" },
  validation: { maxHeight: 40, paddingHorizontal: 10 },
  vErr: { color: "#FCA5A5", backgroundColor: "rgba(220,38,38,0.15)", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, marginRight: 8, fontSize: 12, overflow: "hidden" },
  vWarn: { color: "#FDE68A", backgroundColor: "rgba(180,83,9,0.18)", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, marginRight: 8, fontSize: 12, overflow: "hidden" },
  locked: { color: "#FBBF24", textAlign: "center", paddingVertical: 6, fontWeight: "700" },
  conflictBanner: { color: "#FCA5A5", backgroundColor: "rgba(220,38,38,0.15)", textAlign: "center", paddingVertical: 6, fontWeight: "700" },
  toolStrip: { flexDirection: "row", justifyContent: "space-around", paddingVertical: 10, paddingHorizontal: 6, backgroundColor: "#0B1220", borderTopWidth: 1, borderTopColor: "#1E293B" },
  tool: { paddingHorizontal: 12, paddingVertical: 10, borderRadius: 10 },
  toolOn: { backgroundColor: C.brand },
  toolText: { color: "#CBD5E1", fontWeight: "700", fontSize: 13 },
  toolTextOn: { color: "#fff" },
  genCta: { backgroundColor: C.brand, marginHorizontal: 12, marginTop: 6, paddingVertical: 12, borderRadius: 10, alignItems: "center" },
  genCtaText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  genPanel: { marginHorizontal: 12, marginTop: 8, padding: 10, borderRadius: 10, backgroundColor: "#0E2A3B", borderWidth: 1, borderColor: "#164E63" },
  genHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  genTitle: { color: "#7DD3FC", fontWeight: "800", fontSize: 12, textTransform: "uppercase", letterSpacing: 0.5 },
  genBadge: { fontSize: 11, fontWeight: "800", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 8, overflow: "hidden" },
  genBadgeHi: { color: "#052E1B", backgroundColor: "#6EE7B7" },
  genBadgeRev: { color: "#3B2A05", backgroundColor: "#FCD34D" },
  genBadgeIns: { color: "#3B0A0A", backgroundColor: "#FCA5A5" },
  genMeta: { color: "#94A3B8", fontSize: 11, marginTop: 4 },
  genIns: { color: "#FCA5A5", fontSize: 11, marginTop: 4 },
  genWarn: { color: "#FDE68A", fontSize: 11, marginTop: 4 },
  genAmb: { color: "#FDE68A", backgroundColor: "rgba(180,83,9,0.25)", fontSize: 11, marginTop: 4, padding: 6, borderRadius: 6 },
  genRow: { flexDirection: "row", gap: 10, marginTop: 8 },
});

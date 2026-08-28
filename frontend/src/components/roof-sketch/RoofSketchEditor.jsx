import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { createSketchDocument, deriveProposals, validateSketch } from "@roofspan/roof-sketch-core";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { MousePointer2, PenLine, Square, Dot, Undo2, Redo2, Save, X, Loader2 } from "lucide-react";
import RoofSketchCanvas from "./RoofSketchCanvas";
import SketchInspector from "./SketchInspector";
import ProposalPanel from "./ProposalPanel";
import { useSketchHistory } from "./history";
import { getSketch, saveSketch } from "./sketchApi";
import * as C from "./commands";

const SAVE_BADGE = {
  saved: ["Saved", "bg-emerald-100 text-emerald-800"], unsaved: ["Unsaved changes", "bg-amber-100 text-amber-800"],
  saving: ["Saving…", "bg-blue-100 text-blue-800"], error: ["Save failed", "bg-rose-100 text-rose-800"],
  conflict: ["Conflict", "bg-rose-100 text-rose-800"], validation: ["Rejected", "bg-rose-100 text-rose-800"],
};

export default function RoofSketchEditor({ revision, structure, facets = [], onMeasurementChanged, onClose }) {
  const readOnly = revision?.editable === false;
  const hist = useSketchHistory(createSketchDocument({ structureId: structure?.id }));
  const docRef = useRef(hist.doc);
  useEffect(() => { docRef.current = hist.doc; }, [hist.doc]);

  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(null); // null = not yet created on the server
  const [saveState, setSaveState] = useState("saved");
  const [mode, setMode] = useState("select");
  const [selection, setSelection] = useState(null);
  const [conflict, setConflict] = useState(null);
  const [validationMsg, setValidationMsg] = useState(null);
  const [closeConfirm, setCloseConfirm] = useState(false);

  const relFacetsById = useMemo(() => { const m = {}; facets.forEach((f) => f.id && (m[f.id] = f)); return m; }, [facets]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const rec = await getSketch(revision.id, structure.id);
        if (!alive) return;
        if (rec) { hist.reset(rec.document); docRef.current = rec.document; setVersion(rec.document_version); }
        else { const fresh = createSketchDocument({ structureId: structure.id }); hist.reset(fresh); docRef.current = fresh; setVersion(null); }
        setSaveState("saved");
      } catch (e) { toast.error("Could not load roof sketch."); }
      finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [revision.id, structure.id]); // eslint-disable-line

  const markDirty = () => setSaveState((s) => (s === "saving" ? s : "unsaved"));
  const doUndo = useCallback(() => { hist.undo(); markDirty(); }, [hist]);
  const doRedo = useCallback(() => { hist.redo(); markDirty(); }, [hist]);
  const ctl = useMemo(() => ({
    getDoc: () => docRef.current,
    run: (fn) => { const res = fn(docRef.current) || {}; const nd = res.doc || docRef.current; docRef.current = nd; hist.commit(nd); markDirty(); return res; },
    preview: (nd) => { docRef.current = nd; hist.setDocDirect(nd); markDirty(); },
    commitFrom: (prev, next) => { docRef.current = next; hist.commitFrom(prev, next); markDirty(); },
  }), [hist]);

  const doc = hist.doc;
  const validation = useMemo(() => validateSketch(doc), [doc]);
  const proposals = useMemo(() => deriveProposals(doc), [doc]);

  const cmd = useMemo(() => ({
    setEdgeType: (id, t) => ctl.run((d) => ({ doc: C.setEdgeType(d, id, t) })),
    deleteEdge: (id) => { ctl.run((d) => ({ doc: C.deleteEdge(d, id) })); setSelection(null); },
    setConfirmedEdgeLength: (id, ft) => ctl.run((d) => ({ doc: C.setConfirmedEdgeLength(d, id, ft) })),
    lockEdge: (id) => ctl.run((d) => ({ doc: C.lockEdge(d, id) })),
    unlockEdge: (id) => ctl.run((d) => ({ doc: C.unlockEdge(d, id) })),
    setFacetPitch: (id, p) => ctl.run((d) => ({ doc: C.setFacetPitch(d, id, p) })),
    setFacetOrientation: (id, o) => ctl.run((d) => ({ doc: C.setFacetOrientation(d, id, o) })),
    setFacetLabel: (id, l) => ctl.run((d) => ({ doc: C.setFacetLabel(d, id, l) })),
    deleteFacet: (id) => { ctl.run((d) => ({ doc: C.deleteFacet(d, id) })); setSelection(null); },
    setPenetrationType: (id, t) => ctl.run((d) => ({ doc: C.setPenetrationType(d, id, t) })),
    deletePenetration: (id) => { ctl.run((d) => ({ doc: C.deletePenetration(d, id) })); setSelection(null); },
    calibrate: (edgeId, feet) => ctl.run((d) => ({ doc: C.setScale(d, { edgeId, realFeet: feet }) })),
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
      const meta = e.ctrlKey || e.metaKey;
      if (meta && e.key.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); doUndo(); }
      else if (meta && (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey))) { e.preventDefault(); doRedo(); }
      else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); deleteSelected(); }
      else if (e.key === "Escape") { setSelection(null); setMode("select"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [doUndo, doRedo, deleteSelected]);

  const doSave = async () => {
    setSaveState("saving"); setConflict(null); setValidationMsg(null);
    const res = await saveSketch(revision.id, structure.id, { document: docRef.current, editMode: docRef.current.edit_mode, expectedVersion: version });
    if (res.ok) { setVersion(res.record.document_version); setSaveState("saved"); toast.success("Roof sketch saved."); return true; }
    if (res.kind === "conflict") { setSaveState("conflict"); setConflict(res.server); toast.error("Sketch was changed by someone else."); }
    else if (res.kind === "validation") { setSaveState("validation"); setValidationMsg(res.message); toast.error("Server rejected the sketch."); }
    else if (res.kind === "locked") { setSaveState("error"); toast.error(res.message); }
    else { setSaveState("error"); toast.error(res.message || "Save failed."); }
    return false;
  };

  const reloadServer = async () => {
    const rec = await getSketch(revision.id, structure.id);
    if (rec) { hist.reset(rec.document); docRef.current = rec.document; setVersion(rec.document_version); }
    setConflict(null); setSaveState("saved"); setSelection(null);
    toast.message("Loaded the latest server version. Your local edits were discarded.");
  };

  const switchMode = (m) => {
    if (m === docRef.current.edit_mode) return;
    if ((docRef.current.facets?.length || docRef.current.edges?.length) && !window.confirm("Switching edit mode may reinterpret existing geometry. Continue?")) return;
    ctl.run((d) => ({ doc: C.setEditMode(d, m) }));
    setSelection(null);
  };

  const acceptProposal = (p, { measurementFacetId }) => {
    ctl.run((d) => ({ doc: C.setProposalDecision(d, { targetType: p.target_type, targetId: p.target_id, metric: p.metric, decision: "accepted", value: p.proposed }) }));
    if (measurementFacetId && onMeasurementChanged) onMeasurementChanged({ type: "facet", measurementFacetId, field: "area_sqft", value: p.proposed });
    toast.success("Proposed value accepted into the Worksheet draft.");
  };
  const keepProposal = (p) => ctl.run((d) => ({ doc: C.setProposalDecision(d, { targetType: p.target_type, targetId: p.target_id, metric: p.metric, decision: "keep_current" }) }));

  const dirty = ["unsaved", "validation", "conflict"].includes(saveState);
  const requestClose = () => (dirty ? setCloseConfirm(true) : onClose());
  const [badgeText, badgeCls] = SAVE_BADGE[saveState] || SAVE_BADGE.saved;

  const ToolBtn = ({ id, icon: Icon, label }) => (
    <Button size="sm" variant={mode === id ? "default" : "outline"} disabled={readOnly && id !== "select"} onClick={() => setMode(id)} data-testid={`tool-${id}`}><Icon className="mr-1 h-4 w-4" />{label}</Button>
  );

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
      {!readOnly && <div className="ml-2 flex gap-1">
        <Button size="sm" variant={doc.edit_mode === "connected_graph" ? "secondary" : "ghost"} onClick={() => switchMode("connected_graph")} data-testid="mode-connected">Connected</Button>
        <Button size="sm" variant={doc.edit_mode === "manual_polygon" ? "secondary" : "ghost"} onClick={() => switchMode("manual_polygon")} data-testid="mode-manual">Manual</Button>
      </div>}
      <div className="ml-auto flex items-center gap-2">
        {!readOnly && <Button size="sm" variant="outline" disabled={!hist.canUndo} onClick={doUndo} data-testid="undo-btn"><Undo2 className="h-4 w-4" /></Button>}
        {!readOnly && <Button size="sm" variant="outline" disabled={!hist.canRedo} onClick={doRedo} data-testid="redo-btn"><Redo2 className="h-4 w-4" /></Button>}
        <Badge className={badgeCls} data-testid="save-state-badge">{badgeText}</Badge>
        {!readOnly && <Button size="sm" onClick={doSave} disabled={saveState === "saving"} data-testid="save-sketch-btn">{saveState === "saving" ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Save className="mr-1 h-4 w-4" />}Save Sketch</Button>}
        <Button size="sm" variant="ghost" onClick={requestClose} data-testid="close-sketch-btn"><X className="mr-1 h-4 w-4" />Close</Button>
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
          <SketchInspector doc={doc} selection={selection} cmd={cmd} readOnly={readOnly} />
          <div className="mt-3">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Validation</div>
            {validation.errors.length === 0 && validation.warnings.length === 0 && <div className="text-xs text-emerald-700" data-testid="validation-ok">No issues.</div>}
            {validation.errors.map((e, i) => <div key={`e${i}`} className="rounded bg-rose-50 px-2 py-1 text-xs text-rose-800" data-testid="validation-error">⛔ {e.message}{e.facet_id ? ` (${e.facet_id})` : ""}</div>)}
            {validation.warnings.map((w, i) => <div key={`w${i}`} className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-800" data-testid="validation-warning">⚠ {w.message}</div>)}
          </div>
          <div className="mt-3">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Proposals</div>
            <ProposalPanel doc={doc} proposals={proposals} relFacetsById={relFacetsById} onAccept={acceptProposal} onKeep={keepProposal} readOnly={readOnly} />
          </div>
        </div>
      </div>}

    {closeConfirm && <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/40" data-testid="close-confirm">
      <div className="w-[380px] rounded-lg bg-white p-4 shadow-xl">
        <div className="text-sm font-semibold text-slate-800">You have unsaved roof sketch changes.</div>
        <div className="mt-1 text-sm text-slate-500">Save before closing, discard your changes, or keep editing.</div>
        <div className="mt-4 flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={() => setCloseConfirm(false)} data-testid="close-continue">Continue Editing</Button>
          <Button size="sm" variant="outline" className="text-rose-600" onClick={() => { setCloseConfirm(false); onClose(); }} data-testid="close-discard">Discard Changes</Button>
          <Button size="sm" onClick={async () => { const ok = await doSave(); if (ok) { setCloseConfirm(false); onClose(); } }} data-testid="close-save">Save &amp; Close</Button>
        </div>
      </div>
    </div>}
  </div>;
}

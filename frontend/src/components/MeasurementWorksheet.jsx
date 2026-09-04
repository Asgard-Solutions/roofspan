import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import PhotoGallery from "@/components/PhotoGallery";
import { Plus, Trash2, Check, ShieldCheck, Lock, Undo2, Save, Loader2, GitBranch, PencilRuler, AlertTriangle, RefreshCw } from "lucide-react";
import RoofSketchEditor from "@/components/roof-sketch/RoofSketchEditor";
import { listSketches, saveSketch } from "@/components/roof-sketch/sketchApi";
import { scopeForStructure } from "@/components/roof-sketch/scopeMeasurements";
import { inferTopologyEdges } from "@roofspan/roof-sketch-core";
import RoofThumbnail from "@/components/roof-sketch/RoofThumbnail";
import CombinedSitePlan from "@/components/roof-sketch/CombinedSitePlan";
import { finalizeAfterSave, rollbackPlan } from "@/components/roof-sketch/proposalLifecycle";
import { setDecisions } from "@/components/roof-sketch/commands";
import { num, buildEditablePayload, buildRebasePayload } from "@/components/measurementRebase";

const STRUCTURE_TYPES = [
  ["main_house", "Main House"], ["attached_garage", "Attached Garage"], ["detached_garage", "Detached Garage"],
  ["porch", "Porch"], ["addition", "Addition"], ["shed", "Shed"], ["other", "Other"],
];
const EDGE_TYPES = [
  ["eave", "Eave"], ["rake", "Rake"], ["ridge", "Ridge"], ["hip", "Hip"], ["valley", "Valley"], ["dead_valley", "Dead Valley"],
  ["sidewall", "Sidewall (Step Flashing)"], ["headwall", "Headwall (Apron Flashing)"], ["transition", "Transition"],
];
const PEN_TYPES = [
  ["pipe_boot", "Pipe Boot"], ["static_vent", "Static Vent"], ["skylight", "Skylight"], ["turbine", "Turbine"],
  ["powered_vent", "Powered Vent"], ["exhaust_vent", "Exhaust Vent"], ["chimney", "Chimney"], ["satellite", "Satellite"], ["other", "Other"],
];
const PITCHES = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
const STATUS_LABEL = { draft: "Draft", field_complete: "Field Complete", office_verified: "Office Verified", locked: "Locked" };
const STATUS_STYLE = {
  draft: "bg-slate-100 text-slate-700", field_complete: "bg-amber-100 text-amber-800",
  office_verified: "bg-emerald-100 text-emerald-800", locked: "bg-slate-800 text-white",
};
const uid = () => "r" + Math.random().toString(36).slice(2, 10);

function penetrationForEdit(row) {
  const ref = row.ref || row.id || row._k || uid();
  return { ...row, ref, _k: row._k || row.id || ref, facet_ref: row.facet_id || row.facet_ref || "" };
}

function newPenetration() {
  const ref = uid();
  return { _k: ref, ref, pen_type: "pipe_boot", quantity: 1 };
}

function toEditable(rev) {
  return {
    reported_area_sqft: rev?.reported_area_sqft ?? null,
    structures: (rev?.structures || []).map((row) => ({ ...row, ref: row.id || row.ref || uid(), included_in_scope: row.included_in_scope !== false })),
    facets: (rev?.facets || []).map((row) => ({ ...row, ref: row.id || row.ref || uid(), structure_ref: row.structure_id || row.structure_ref || "" })),
    edges: (rev?.edges || []).map((row) => { const L = Number(row.length_ft || 0); const ft = Math.floor(L); const inches = Math.round((L - ft) * 12 * 10) / 10; return ({ ...row, ref: row.id || row.ref || uid(), _k: row.id || row._k || uid(), facet_ref: row.facet_id || "", facet_ref_secondary: row.facet_id_secondary || "", ft: String(ft || ""), in: String(inches || "") }); }),
    penetrations: (rev?.penetrations || []).map(penetrationForEdit),
    summary: rev?.summary || {},
    site_plan: rev?.site_plan || null,
  };
}

export default function MeasurementWorksheet({ leadId, propertyId, inspectionId, propertyAddress }) {
  const { user } = useAuth();
  const isOffice = ["owner", "administrator", "office"].includes(user?.role);
  const [list, setList] = useState([]);
  const [rev, setRev] = useState(null);
  const [ed, setEd] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [needsReview, setNeedsReview] = useState(null);   // {server} when Office save hit a stale-version 409
  const [confirmKeep, setConfirmKeep] = useState(false);  // warning gate before Keep My Version overwrites
  const [confirmDelete, setConfirmDelete] = useState(false); // confirm gate before deleting a draft revision
  const [sketchFor, setSketchFor] = useState(null); // structure row being sketched
  const [sketchStructIds, setSketchStructIds] = useState(new Set());

  const scopeParam = leadId ? `lead_id=${leadId}` : propertyId ? `property_id=${propertyId}` : `inspection_id=${inspectionId}`;

  const loadList = useCallback(async () => {
    try {
      const rows = (await api.get(`/measurements?${scopeParam}`)).data;
      setList(rows);
      return rows;
    } catch (e) { toast.error(apiError(e)); return []; }
  }, [scopeParam]);

  const loadRevision = useCallback(async (id) => {
    const loaded = (await api.get(`/measurements/${id}`)).data;
    setRev(loaded); setEd(toEditable(loaded)); setDirty(false);
  }, []);

  useEffect(() => {
    (async () => {
      setLoading(true);
      const rows = await loadList();
      if (rows.length) await loadRevision(rows[0].id);
      else { setRev(null); setEd(null); }
      setLoading(false);
    })();
  }, [loadList, loadRevision]);

  useEffect(() => {
    let alive = true;
    if (!rev?.id) { setSketchStructIds(new Set()); return; }
    (async () => {
      try { const rows = await listSketches(rev.id); if (alive) setSketchStructIds(new Set(rows.map((r) => r.structure_id))); }
      catch { if (alive) setSketchStructIds(new Set()); }
    })();
    return () => { alive = false; };
  }, [rev?.id]);

  // --- Live two-way sync (auto-refresh) --------------------------------------------------------------
  // Keep this worksheet in step with Field edits without a manual reload. Every 15s (and on window focus)
  // we re-pull the current revision. If the Office user has NO unsaved edits we quietly adopt the latest;
  // if they are mid-edit (dirty) or already reviewing a conflict, we only surface a banner so their work
  // is never overwritten — Save still runs the existing stale-version (409) review flow.
  const [remoteUpdate, setRemoteUpdate] = useState(false);
  const dirtyRef = useRef(dirty); dirtyRef.current = dirty;
  const busyRef = useRef(busy); busyRef.current = busy;
  const needsReviewRef = useRef(needsReview); needsReviewRef.current = needsReview;
  const revIdRef = useRef(null); revIdRef.current = rev?.id || null;
  const revUpdatedRef = useRef(null); revUpdatedRef.current = rev?.updated_at || null;

  const checkRemote = useCallback(async () => {
    const id = revIdRef.current;
    if (!id || busyRef.current) return;
    let latest;
    try { latest = (await api.get(`/measurements/${id}`)).data; }
    catch { return; }   // transient/offline — try again next tick
    if (!latest?.updated_at || latest.updated_at === revUpdatedRef.current) return;
    if (dirtyRef.current || needsReviewRef.current) {
      setRemoteUpdate(true);   // changed while we're editing — never clobber unsaved work
    } else {
      setRev(latest); setEd(toEditable(latest)); setDirty(false); setRemoteUpdate(false);
      loadList();
      toast.message("Updated with the latest changes from the field");
    }
  }, [loadList]);

  useEffect(() => {
    const iv = setInterval(() => { checkRemote(); }, 15000);
    const onFocus = () => checkRemote();
    window.addEventListener("focus", onFocus);
    return () => { clearInterval(iv); window.removeEventListener("focus", onFocus); };
  }, [checkRemote]);

  // Adopt the latest server copy on demand from the banner (discards unsaved Office edits by explicit choice).
  const loadRemoteLatest = async () => {
    const id = revIdRef.current;
    if (!id) return;
    setBusy(true);
    try { await loadRevision(id); setRemoteUpdate(false); setNeedsReview(null); toast.message("Loaded the latest version from the field."); }
    catch (e) { toast.error(apiError(e)); }
    finally { setBusy(false); }
  };

  const editable = rev ? rev.editable : true;
  const totals = rev?.totals;

  const liveTotals = useMemo(() => {
    if (!ed) return null;
    const included = new Set(ed.structures.filter((row) => row.included_in_scope !== false).map((row) => row.ref));
    const area = ed.facets.reduce((sum, facet) => sum + (parseFloat(facet.area_sqft) || 0), 0);
    const takeoffArea = ed.facets.reduce((sum, facet) => sum + ((!facet.structure_ref || included.has(facet.structure_ref)) ? (parseFloat(facet.area_sqft) || 0) : 0), 0);
    const byPitch = {};
    ed.facets.forEach((facet) => { const pitch = facet.pitch_rise ?? "—"; byPitch[pitch] = (byPitch[pitch] || 0) + (parseFloat(facet.area_sqft) || 0); });
    const edge = {};
    ed.edges.forEach((row) => { edge[row.edge_type] = (edge[row.edge_type] || 0) + (parseFloat(row.length_ft) || 0); });
    const pen = ed.penetrations.reduce((sum, row) => sum + (parseInt(row.quantity) || 0), 0);
    return { area, takeoffArea, squares: area / 100, takeoffSquares: takeoffArea / 100, byPitch, edge, pen, facets: ed.facets.length, structures: ed.structures.length };
  }, [ed]);

  const setRow = (key, i, field, value) => {
    setEd((doc) => {
      const rows = [...doc[key]]; const nx = { ...rows[i], [field]: value };
      // Square footage is computed for the user: Area (SF) = Width × Length whenever both are present.
      // Area stays editable so the user can override; changing a dimension recomputes it.
      if (key === "facets" && (field === "width_ft" || field === "length_ft")) {
        const w = parseFloat(nx.width_ft), l = parseFloat(nx.length_ft);
        if (Number.isFinite(w) && Number.isFinite(l)) nx.area_sqft = Math.round(w * l * 100) / 100;
      }
      rows[i] = nx; return { ...doc, [key]: rows };
    });
    setDirty(true);
  };
  const addRow = (key, row) => { setEd((doc) => ({ ...doc, [key]: [...doc[key], row] })); setDirty(true); };
  const delRow = (key, i) => { setEd((doc) => ({ ...doc, [key]: doc[key].filter((_, idx) => idx !== i) })); setDirty(true); };
  // Roof Line ft/in entry: keep length_ft (decimal) in sync so the salesperson never converts inches.
  const setEdgePart = (i, field, value) => {
    setEd((doc) => {
      const rows = [...doc.edges]; const nx = { ...rows[i], [field]: value };
      nx.length_ft = (parseFloat(nx.ft) || 0) + (parseFloat(nx.in) || 0) / 12;
      rows[i] = nx; return { ...doc, edges: rows };
    });
    setDirty(true);
  };
  const setSummary = (field, value) => { setEd((doc) => ({ ...doc, summary: { ...doc.summary, [field]: value } })); setDirty(true); };
  const setSiteOffsets = (val) => { setEd((doc) => ({ ...doc, site_plan: val })); setDirty(true); };
  // Quick-add: materialize the auto-inferred ridge/eave/hip lines into editable roof-line rows so a rep
  // can turn an auto-inferred roof into a measured one in one tap, then refine lengths.
  const addRoofLines = (structureId) => {
    const sf = (ed.facets || []).filter((f) => (f.structure_id || f.structure_ref) === structureId);
    const inf = inferTopologyEdges(sf);
    if (!inf.inferred || !inf.edges.length) { toast.error("Not enough roof planes to infer roof lines"); return; }
    const rows = inf.edges.map((e) => { const L = Number(e.length_ft || 0); const ft = Math.floor(L); const inch = Math.round((L - ft) * 12 * 10) / 10; return { ref: uid(), _k: uid(), edge_type: e.edge_type, length_ft: L || 0, facet_ref: e.facet_id, facet_ref_secondary: e.facet_id_secondary || "", label: "", notes: "", ft: String(ft || ""), in: String(inch || "") }; });
    setEd((doc) => ({ ...doc, edges: [...doc.edges, ...rows] }));
    setDirty(true);
    toast.success(`Added ${rows.length} roof line${rows.length > 1 ? "s" : ""} — refine lengths, then Save`);
  };

  const scope = { leadId, propertyId, inspectionId };
  // Normal save: whole document from the local form + `base` top-level metadata (see measurementRebase.js).
  const buildPayload = (base = rev) => buildEditablePayload(ed, base, scope);
  // Keep My Version: rebase onto the newer authoritative server copy; only Office-editable values win.
  const buildRebase = (server) => buildRebasePayload(ed, server, scope);

  const finalizePending = async (saved) => {
    if (!saved?.id) return;
    let rows;
    try { rows = await listSketches(saved.id); }
    catch { toast.message("Measurement saved successfully, but Roof Sketch proposal status could not be finalized. The measurement is safe; proposals remain pending and can be finalized later."); return; }
    const savedFacet = {}; (saved.facets || []).forEach((f) => { savedFacet[String(f.id)] = f; });
    const savedEdge = {}; (saved.edges || []).forEach((e) => { savedEdge[String(e.id)] = e; });
    const savedValueOf = (type, id, metric) => (type === "facet" ? savedFacet[String(id)]?.[metric] : type === "edge" ? savedEdge[String(id)]?.[metric] : undefined);
    let promoted = 0, failed = 0;
    for (const rec of rows) {
      const fin = finalizeAfterSave(rec.document?.proposal_decisions || [], savedValueOf);
      if (!fin.changed) continue;
      // second sketch save via CAS: changes ONLY proposal provenance, never relational measurement data.
      const res = await saveSketch(saved.id, rec.structure_id, { document: setDecisions(rec.document, fin.decisions), editMode: rec.edit_mode, expectedVersion: rec.document_version });
      if (res.ok) promoted += fin.promoted.length; else failed += 1;
    }
    if (promoted) toast.success(`${promoted} roof-sketch proposal${promoted > 1 ? "s" : ""} finalized as accepted.`);
    if (failed) toast.message("Measurement saved successfully, but a roof-sketch proposal status could not be finalized. The measurement is safe; the proposal stays pending until the sketch is saved again.");
  };

  const save = async () => {
    if (needsReview) return;   // blocked until the stale-version conflict is explicitly resolved
    setBusy(true);
    try {
      const body = buildPayload();
      // Cross-app concurrency: send our base version so the server refuses to silently overwrite a newer
      // (e.g. synced Field) copy. On 409 we surface an explicit refresh/review — never destroy newer work.
      const saved = rev
        ? (await api.put(`/measurements/${rev.id}`, body, { headers: rev.updated_at ? { "If-Match": rev.updated_at } : {} })).data
        : (await api.post(`/measurements`, body)).data;
      toast.success("Measurement saved");
      await loadList(); setRev(saved); setEd(toEditable(saved)); setDirty(false);
      await finalizePending(saved);
    } catch (e) {
      if (e?.response?.status === 409) {
        const server = e.response.data?.detail?.server;
        // #16: enter an explicit Needs Review state. Do NOT advance rev/token under the dirty form —
        // that would let a second Save overwrite the newer version. Save stays blocked until resolved.
        setNeedsReview({ server: server || null });
        toast.error("Measurement changed elsewhere. Review required before saving.");
      } else {
        toast.error(apiError(e));
      }
    } finally { setBusy(false); }
  };

  // Use Latest Version: adopt the newer authoritative server revision into the working form. The user's
  // stale local edits are discarded ONLY because they explicitly chose this. Clears Needs Review.
  const useLatestVersion = async () => {
    setBusy(true);
    try {
      const server = needsReview?.server;
      if (server) { setRev(server); setEd(toEditable(server)); }
      else if (rev?.id) { await loadRevision(rev.id); }
      setDirty(false); setNeedsReview(null); setConfirmKeep(false);
      toast.message("Loaded the latest version. Your unsaved changes were discarded.");
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  // Keep My Version: the user's current editable measurement fields intentionally win, but they are rebased
  // onto the NEWER authoritative server revision — its hidden/system metadata (top-level report fields,
  // Roof Plane orientation/geometry, hidden summary keys) is preserved via buildRebasePayload(). We save
  // using the server's fresh If-Match token; if the server advanced AGAIN it 409s again (never force-writes).
  // Needs Review clears only after the authoritative save succeeds.
  const keepMyVersion = async () => {
    const server = needsReview?.server;
    if (!server || !rev) return;
    setBusy(true);
    try {
      const body = buildRebase(server);
      const saved = (await api.put(`/measurements/${rev.id}`, body, { headers: server.updated_at ? { "If-Match": server.updated_at } : {} })).data;
      toast.success("Your version saved over the newer copy");
      await loadList(); setRev(saved); setEd(toEditable(saved)); setDirty(false);
      setNeedsReview(null); setConfirmKeep(false);
      await finalizePending(saved);
    } catch (e) {
      if (e?.response?.status === 409) {
        const again = e.response.data?.detail?.server;
        setNeedsReview({ server: again || null }); setConfirmKeep(false);
        toast.error("Measurement changed again while saving. Review the latest version once more.");
      } else { toast.error(apiError(e)); }
    } finally { setBusy(false); }
  };

  const startNew = async () => {
    setBusy(true);
    try {
      const body = { lead_id: leadId || null, property_id: propertyId || null, inspection_id: inspectionId || null, source: "office", structures: [], facets: [], edges: [], penetrations: [], summary: {} };
      const saved = (await api.post(`/measurements`, body)).data;
      await loadList(); setRev(saved); setEd(toEditable(saved)); setDirty(false); toast.success("New measurement started");
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const cloneRevision = async () => {
    setBusy(true);
    try {
      const next = (await api.post(`/measurements/${rev.id}/new-revision`)).data;
      await loadList(); setRev(next); setEd(toEditable(next)); setDirty(false); toast.success(`Revision ${next.revision_number} created for editing`);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const changeStatus = async (to) => {
    setBusy(true);
    try {
      const next = (await api.post(`/measurements/${rev.id}/status`, { to })).data;
      await loadList(); setRev(next); setEd(toEditable(next)); setDirty(false); toast.success(`Marked ${STATUS_LABEL[to]}`);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  // Delete a Draft revision, then auto-select the next most recent (or empty state if none remain).
  const deleteRevision = async () => {
    if (!rev?.id) return;
    setBusy(true);
    try {
      const num = rev.revision_number;
      await api.delete(`/measurements/${rev.id}`);
      setConfirmDelete(false); setNeedsReview(null); setRemoteUpdate(false);
      const rows = await loadList();
      if (rows.length) { await loadRevision(rows[0].id); }
      else { setRev(null); setEd(null); setDirty(false); }
      toast.success(`Revision ${num} deleted`);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  // Unlock a locked revision back to Office Verified (manual locks only; estimate-referenced stay locked).
  const unlockRevision = async () => {
    if (!rev?.id) return;
    setBusy(true);
    try {
      const next = (await api.post(`/measurements/${rev.id}/unlock`)).data;
      await loadList(); setRev(next); setEd(toEditable(next)); setDirty(false); toast.success(`Revision ${next.revision_number} unlocked`);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  if (loading) return <div className="p-3 text-sm text-slate-500" data-testid="measurement-loading"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />Loading measurements…</div>;

  const applySketchProposal = ({ target_type, target_id, metric, value }) => {
    if (!target_id || !metric) return;
    if (target_type === "facet") setEd((doc) => ({ ...doc, facets: doc.facets.map((f) => (String(f.id) === String(target_id) ? { ...f, [metric]: value } : f)) }));
    else if (target_type === "edge") setEd((doc) => ({ ...doc, edges: doc.edges.map((e) => (String(e.id) === String(target_id) ? { ...e, [metric]: value } : e)) }));
    else return;
    setDirty(true);
  };

  // Discard from the sketch editor: roll back ONLY the worksheet fields this editor session applied,
  // and only when the current draft value still equals what the editor set (a later manual edit wins).
  const discardEditorSession = (session) => {
    if (!session) return;
    setEd((doc) => {
      const valueOf = (type, id, metric) => {
        const coll = type === "facet" ? doc.facets : doc.edges;
        const row = (coll || []).find((r) => String(r.id) === String(id));
        return row ? Number(row[metric]) : undefined;
      };
      const plan = rollbackPlan(session, valueOf);
      if (!plan.length) return doc;
      let facets = doc.facets, edges = doc.edges;
      for (const p of plan) {
        if (p.target_type === "facet") facets = facets.map((f) => (String(f.id) === String(p.target_id) ? { ...f, [p.metric]: p.restore_value } : f));
        else if (p.target_type === "edge") edges = edges.map((e) => (String(e.id) === String(p.target_id) ? { ...e, [p.metric]: p.restore_value } : e));
      }
      return { ...doc, facets, edges };
    });
  };

  const structOptions = (ed?.structures || []).filter((row) => row.ref).map((row) => [row.ref, row.name || STRUCTURE_TYPES.find((t) => t[0] === row.structure_type)?.[1] || "Structure"]);
  const facetOptions = (ed?.facets || []).filter((row) => row.ref).map((row) => [row.ref, row.facet_label || "Roof plane"]);
  const t = liveTotals;
  const hasScopeExclusion = !!(t && Math.abs(t.area - t.takeoffArea) > 0.001);

  return <div className="space-y-4" data-testid="measurement-worksheet">
    <div className="flex flex-wrap items-center gap-2">
      {list.length > 0 && <Select value={rev?.id || ""} onValueChange={loadRevision}>
        <SelectTrigger className="w-[230px]" data-testid="measurement-revision-select"><SelectValue placeholder="Select revision" /></SelectTrigger>
        <SelectContent>{list.map((row) => <SelectItem key={row.id} value={row.id}>Rev {row.revision_number} · {STATUS_LABEL[row.status]} · {row.total_squares} sq</SelectItem>)}</SelectContent>
      </Select>}
      {rev && <Badge className={STATUS_STYLE[rev.status]}>{STATUS_LABEL[rev.status]}</Badge>}
      {rev?.supersedes_revision_id && <span className="text-xs text-slate-400">supersedes an earlier revision</span>}
      <div className="ml-auto flex flex-wrap gap-2">
        {!rev && <Button size="sm" onClick={startNew} disabled={busy}><Plus className="mr-1 h-4 w-4" />Start measurement</Button>}
        {rev && !editable && <Button size="sm" variant="outline" onClick={cloneRevision} disabled={busy}><GitBranch className="mr-1 h-4 w-4" />New revision</Button>}
        {rev && editable && dirty && <Button size="sm" onClick={save} disabled={busy || !!needsReview} data-testid="measurement-save-btn">{busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Save className="mr-1 h-4 w-4" />}Save Measurements</Button>}
        {rev?.status === "draft" && !dirty && <Button size="sm" variant="outline" onClick={() => changeStatus("field_complete")} disabled={busy}><Check className="mr-1 h-4 w-4" />Field Complete</Button>}
        {rev?.status === "field_complete" && isOffice && <Button size="sm" variant="outline" onClick={() => changeStatus("office_verified")} disabled={busy}><ShieldCheck className="mr-1 h-4 w-4" />Office Verify</Button>}
        {rev?.status === "office_verified" && isOffice && <Button size="sm" variant="outline" onClick={() => changeStatus("locked")} disabled={busy}><Lock className="mr-1 h-4 w-4" />Lock</Button>}
        {rev?.status === "locked" && isOffice && <Button size="sm" variant="outline" onClick={unlockRevision} disabled={busy} data-testid="measurement-unlock-btn"><Undo2 className="mr-1 h-4 w-4" />Unlock</Button>}
        {rev && ["field_complete", "office_verified"].includes(rev.status) && isOffice && <Button size="sm" variant="ghost" onClick={() => changeStatus("draft")} disabled={busy}><Undo2 className="mr-1 h-4 w-4" />Return to field</Button>}
        {rev?.status === "draft" && !rev.is_immutable && <Button size="sm" variant="outline" className="border-rose-200 text-rose-600 hover:bg-rose-50 hover:text-rose-700" onClick={() => setConfirmDelete(true)} disabled={busy} data-testid="measurement-delete-revision-btn"><Trash2 className="mr-1 h-4 w-4" />Delete revision</Button>}
      </div>
    </div>

    {confirmDelete && rev && <div className="rounded-lg border border-rose-300 bg-rose-50 p-3" data-testid="measurement-delete-confirm">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-rose-600" />
        <div className="flex-1 space-y-2">
          <div className="text-sm font-semibold text-rose-900">Delete Revision {rev.revision_number}?</div>
          <p className="text-xs text-rose-800">This permanently removes this draft roof measurement revision and all of its structures, roof planes, roof lines and penetrations. This can't be undone.</p>
          <div className="flex flex-wrap gap-2 pt-1">
            <Button size="sm" variant="destructive" onClick={deleteRevision} disabled={busy} data-testid="measurement-delete-confirm-btn">{busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Trash2 className="mr-1 h-4 w-4" />}Delete revision</Button>
            <Button size="sm" variant="outline" onClick={() => setConfirmDelete(false)} disabled={busy} data-testid="measurement-delete-cancel-btn">Cancel</Button>
          </div>
        </div>
      </div>
    </div>}

    {needsReview && <div className="rounded-lg border border-amber-300 bg-amber-50 p-3" data-testid="measurement-needs-review">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
        <div className="flex-1 space-y-2">
          <div className="text-sm font-semibold text-amber-900">Needs review — this measurement changed elsewhere</div>
          <p className="text-xs text-amber-800">A newer version of this measurement was saved on the server (for example from a Field sync) after you started editing. Saving is paused so nothing is lost. Choose how to resolve it. Both your unsaved edits and the newer server version are preserved until you decide.</p>
          {!confirmKeep ? <div className="flex flex-wrap gap-2 pt-1">
            <Button size="sm" variant="outline" onClick={useLatestVersion} disabled={busy} data-testid="conflict-use-latest-btn"><RefreshCw className="mr-1 h-4 w-4" />Use Latest Version</Button>
            <Button size="sm" onClick={() => setConfirmKeep(true)} disabled={busy} data-testid="conflict-keep-mine-btn"><Save className="mr-1 h-4 w-4" />Keep My Version</Button>
          </div> : <div className="rounded border border-amber-300 bg-white p-2">
            <p className="text-xs font-medium text-amber-900">Keep My Version will replace the newer measurement values with your unsaved Office changes. Continue?</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" onClick={keepMyVersion} disabled={busy} data-testid="conflict-keep-mine-confirm-btn">{busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Check className="mr-1 h-4 w-4" />}Yes, keep my version</Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmKeep(false)} disabled={busy} data-testid="conflict-keep-mine-cancel-btn">Cancel</Button>
            </div>
          </div>}
        </div>
      </div>
    </div>}

    {remoteUpdate && !needsReview && <div className="flex items-center gap-2 rounded-lg border border-sky-300 bg-sky-50 p-3" data-testid="measurement-remote-update">
      <RefreshCw className="h-4 w-4 shrink-0 text-sky-600" />
      <span className="flex-1 text-xs text-sky-900">New changes from the field are available for this measurement. Your unsaved edits are kept — saving will prompt you to review.</span>
      <Button size="sm" variant="outline" onClick={loadRemoteLatest} disabled={busy} data-testid="measurement-remote-update-load"><RefreshCw className="mr-1 h-4 w-4" />Load latest</Button>
      <Button size="sm" variant="ghost" onClick={() => setRemoteUpdate(false)} disabled={busy} data-testid="measurement-remote-update-dismiss">Keep editing</Button>
    </div>}

    {!rev && <div className="rounded border border-dashed border-border p-6 text-center text-sm text-slate-500">No roof measurement yet. Start one to capture structures, roof planes, roof lines and penetrations.</div>}

    {rev && ed && <>
      <div className="grid grid-cols-2 gap-3 rounded-lg bg-slate-50 p-3 sm:grid-cols-5" data-testid="measurement-totals">
        <Totm label="Measured area" value={`${t.area.toFixed(0)} SF`} testid="tot-area" />
        <Totm label="Measured squares" value={t.squares.toFixed(2)} testid="tot-squares" />
        <Totm label="Takeoff squares" value={t.takeoffSquares.toFixed(2)} testid="tot-takeoff-squares" />
        <Totm label="Roof planes" value={t.facets} testid="tot-facets" />
        <Totm label="Structures" value={t.structures} testid="tot-structures" />
      </div>
      {hasScopeExclusion && <div className="rounded border border-blue-200 bg-blue-50 p-2 text-xs text-blue-900">Measured totals retain every structure. Takeoff totals exclude structures marked “Exclude from estimate.”</div>}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">{EDGE_TYPES.map(([k, label]) => t.edge[k] ? <span key={k}>{label}: <b>{t.edge[k].toFixed(0)} LF</b></span> : null)}{t.pen ? <span>Penetrations: <b>{t.pen}</b></span> : null}</div>

      <TableCard title="Structures" onAdd={editable ? () => addRow("structures", { ref: uid(), name: "", structure_type: "main_house", included_in_scope: true }) : null} testid="structures">
        {ed.structures.map((row, i) => <div key={row.ref || i} className="rounded border border-slate-100 p-2" data-testid={`structure-row-${i}`}>
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Name" className="w-40"><Input placeholder="e.g. Main House" value={row.name || ""} disabled={!editable} onChange={(e) => setRow("structures", i, "name", e.target.value)} /></Field>
            <Field label="Structure Type" className="w-44"><Select value={row.structure_type} disabled={!editable} onValueChange={(v) => setRow("structures", i, "structure_type", v)}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent>{STRUCTURE_TYPES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select></Field>
            <label className="flex items-center gap-1 pb-2 text-sm"><input type="checkbox" checked={row.included_in_scope !== false} disabled={!editable} onChange={(e) => setRow("structures", i, "included_in_scope", e.target.checked)} />Include in estimate</label>
            <Field label="Stories" className="w-24"><Input type="number" value={row.stories ?? ""} disabled={!editable} onChange={(e) => setRow("structures", i, "stories", e.target.value)} /></Field>
            <Field label="Approx Height (ft)" className="w-28"><Input type="number" value={row.approx_height_ft ?? ""} disabled={!editable} onChange={(e) => setRow("structures", i, "approx_height_ft", e.target.value)} /></Field>
            <Field label="Attachment" className="w-32"><Select value={row.attachment || "none"} disabled={!editable} onValueChange={(v) => setRow("structures", i, "attachment", v === "none" ? "" : v)}><SelectTrigger className="w-full"><SelectValue placeholder="Attachment" /></SelectTrigger><SelectContent><SelectItem value="none">—</SelectItem><SelectItem value="attached">Attached</SelectItem><SelectItem value="detached">Detached</SelectItem></SelectContent></Select></Field>
            {editable && <Button size="icon" variant="ghost" className="mb-0.5" onClick={() => delRow("structures", i)}><Trash2 className="h-4 w-4 text-rose-500" /></Button>}
          </div>
          <div className="mt-2 flex items-center gap-3">
            {row.id
              ? <>
                  <RoofThumbnail structure={{ id: row.id }} facets={ed?.facets || []} edges={ed?.edges || []} penetrations={ed?.penetrations || []} testid={`structure-roof-thumbnail-${i}`} />
                  <Button size="sm" variant="outline" onClick={() => setSketchFor(row)} data-testid={`sketch-roof-btn-${i}`}><PencilRuler className="mr-1 h-4 w-4" />{sketchStructIds.has(row.id) ? "Edit Roof Sketch" : "Sketch Roof"}</Button>
                  {(() => {
                    const sf = (ed.facets || []).filter((f) => (f.structure_id || f.structure_ref) === row.id);
                    const ids = new Set(sf.map((f) => f.id).filter(Boolean));
                    const se = (ed.edges || []).filter((e) => ids.has(e.facet_ref) || ids.has(e.facet_ref_secondary) || ids.has(e.facet_id) || ids.has(e.facet_id_secondary));
                    return sf.length >= 2 && se.length === 0 ? (
                      <span data-testid={`structure-inferred-badge-${i}`} className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
                        <AlertTriangle className="h-3 w-3" />Auto-inferred — add roof lines to refine
                      </span>
                    ) : null;
                  })()}
                  {editable && (() => {
                    const sf = (ed.facets || []).filter((f) => (f.structure_id || f.structure_ref) === row.id);
                    const ids = new Set(sf.map((f) => f.id).filter(Boolean));
                    const se = (ed.edges || []).filter((e) => ids.has(e.facet_ref) || ids.has(e.facet_ref_secondary) || ids.has(e.facet_id) || ids.has(e.facet_id_secondary));
                    return sf.length >= 2 && se.length === 0 ? (
                      <Button size="sm" variant="outline" className="border-amber-300 text-amber-700 hover:bg-amber-50" onClick={() => addRoofLines(row.id)} data-testid={`add-roof-lines-btn-${i}`}>
                        <Plus className="mr-1 h-3.5 w-3.5" />Add roof lines
                      </Button>
                    ) : null;
                  })()}
                </>
              : <span className="text-xs text-slate-400">Save the worksheet to sketch this structure's roof.</span>}
          </div>
          <div className="mt-2"><Field label="Structure Notes"><Input placeholder="Optional" value={row.notes || ""} disabled={!editable} onChange={(e) => setRow("structures", i, "notes", e.target.value)} /></Field></div>
        </div>)}
      </TableCard>

      {ed.structures.filter((s) => s.id).length >= 2 && (
        <TableCard title="Combined site plan" testid="site-plan">
          <CombinedSitePlan
            structures={ed.structures.map((s, i) => ({ id: s.id, name: s.name, structure_type: s.structure_type, included_in_scope: s.included_in_scope !== false, sort: i }))}
            facets={(ed.facets || []).map((f) => ({ ...f, structure_id: f.structure_id || f.structure_ref || null }))}
            edges={ed.edges || []}
            penetrations={ed.penetrations || []}
            sitePlan={ed.site_plan}
            editable={editable}
            onChangeOffsets={setSiteOffsets}
            propertyAddress={propertyAddress}
            preparedBy={user?.name || user?.full_name || user?.email || ""}
          />
        </TableCard>
      )}

      <TableCard title="Roof planes" onAdd={editable ? () => addRow("facets", { ref: uid(), facet_label: `F${ed.facets.length + 1}`, pitch_rise: "", area_sqft: "" }) : null} testid="facets">
        {ed.facets.map((row, i) => <div key={row.ref || i} className="rounded border border-slate-100 p-2" data-testid={`facet-block-${i}`}>
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Plane" className="w-24"><Input placeholder="F1" value={row.facet_label || ""} disabled={!editable} onChange={(e) => setRow("facets", i, "facet_label", e.target.value)} /></Field>
            <Field label="Structure" className="w-40"><Select value={row.structure_ref || "none"} disabled={!editable} onValueChange={(v) => setRow("facets", i, "structure_ref", v === "none" ? "" : v)}><SelectTrigger className="w-full"><SelectValue placeholder="Structure" /></SelectTrigger><SelectContent><SelectItem value="none">—</SelectItem>{structOptions.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select></Field>
            <Field label="Pitch" className="w-28"><PitchSelect value={row.pitch_rise} disabled={!editable} onChange={(v) => setRow("facets", i, "pitch_rise", v)} /></Field>
            <Field label="Width (ft)" className="w-24"><Input type="number" value={row.width_ft ?? ""} disabled={!editable} onChange={(e) => setRow("facets", i, "width_ft", e.target.value)} /></Field>
            <Field label="Length (ft)" className="w-24"><Input type="number" value={row.length_ft ?? ""} disabled={!editable} onChange={(e) => setRow("facets", i, "length_ft", e.target.value)} /></Field>
            <Field label="Offset from left (ft)" className="w-32"><Input type="number" placeholder="Optional" value={row.position_offset_ft ?? ""} disabled={!editable} onChange={(e) => setRow("facets", i, "position_offset_ft", e.target.value)} data-testid={`facet-offset-${i}`} /></Field>
            <Field label="Area (SF)" className="w-28"><Input type="number" placeholder="= W × L" value={row.area_sqft ?? ""} disabled={!editable} onChange={(e) => setRow("facets", i, "area_sqft", e.target.value)} /></Field>
            <Field label="Roof Material" className="min-w-40 flex-1"><Input placeholder="Optional" value={row.roof_material || ""} disabled={!editable} onChange={(e) => setRow("facets", i, "roof_material", e.target.value)} /></Field>
            {editable && <Button size="icon" variant="ghost" className="mb-0.5" onClick={() => delRow("facets", i)}><Trash2 className="h-4 w-4 text-rose-500" /></Button>}
          </div>
          <div className="mt-2"><Field label="Roof Plane Notes"><Input placeholder="Optional" value={row.notes || ""} disabled={!editable} onChange={(e) => setRow("facets", i, "notes", e.target.value)} /></Field></div>
          {row.id && <div className="mt-1"><PhotoGallery compact hideWhenEmpty recordType="measurement_facet" recordId={row.id} /></div>}
        </div>)}
      </TableCard>

      <TableCard title="Roof lines" onAdd={editable ? () => addRow("edges", { _k: uid(), ref: uid(), edge_type: "eave", ft: "", in: "", length_ft: "", facet_ref: "", facet_ref_secondary: "" }) : null} testid="edges">
        {ed.edges.map((row, i) => <div key={row._k || i} className="flex flex-wrap items-end gap-2" data-testid={`edge-row-${i}`}>
          <Field label="Type" className="w-36"><Select value={row.edge_type} disabled={!editable} onValueChange={(v) => setRow("edges", i, "edge_type", v)}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent>{EDGE_TYPES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select></Field>
          <Field label="Feet" className="w-20"><Input type="number" placeholder="ft" value={row.ft ?? ""} disabled={!editable} onChange={(e) => setEdgePart(i, "ft", e.target.value)} /></Field>
          <Field label="Inches" className="w-20"><Input type="number" placeholder="in" value={row.in ?? ""} disabled={!editable} onChange={(e) => setEdgePart(i, "in", e.target.value)} /></Field>
          <Field label="Total LF" className="w-16"><span className="block pb-2 text-xs font-medium text-slate-500">{(parseFloat(row.length_ft) || 0).toFixed(1)} LF</span></Field>
          <Field label="Primary Roof Plane" className="w-40"><Select value={row.facet_ref || "none"} disabled={!editable} onValueChange={(v) => setRow("edges", i, "facet_ref", v === "none" ? "" : v)}><SelectTrigger className="w-full"><SelectValue placeholder="Primary plane" /></SelectTrigger><SelectContent><SelectItem value="none">Primary plane —</SelectItem>{facetOptions.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select></Field>
          <Field label="Secondary Roof Plane" className="w-40"><Select value={row.facet_ref_secondary || "none"} disabled={!editable} onValueChange={(v) => setRow("edges", i, "facet_ref_secondary", v === "none" ? "" : v)}><SelectTrigger className="w-full"><SelectValue placeholder="Secondary plane" /></SelectTrigger><SelectContent><SelectItem value="none">Secondary plane —</SelectItem>{facetOptions.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select></Field>
          <Field label="Label" className="w-32"><Input value={row.label || ""} disabled={!editable} onChange={(e) => setRow("edges", i, "label", e.target.value)} /></Field>
          <Field label="Notes" className="min-w-40 flex-1"><Input value={row.notes || ""} disabled={!editable} onChange={(e) => setRow("edges", i, "notes", e.target.value)} /></Field>
          {editable && <Button size="icon" variant="ghost" className="mb-0.5" onClick={() => delRow("edges", i)}><Trash2 className="h-4 w-4 text-rose-500" /></Button>}
        </div>)}
      </TableCard>

      <TableCard title="Penetrations" onAdd={editable ? () => addRow("penetrations", newPenetration()) : null} testid="penetrations">
        {ed.penetrations.map((row, i) => <div key={row._k || i} className="rounded border border-slate-100 p-2">
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Type" className="w-40"><Select value={row.pen_type} disabled={!editable} onValueChange={(v) => setRow("penetrations", i, "pen_type", v)}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent>{PEN_TYPES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select></Field>
            <Field label="Qty" className="w-20"><Input type="number" value={row.quantity ?? 1} disabled={!editable} onChange={(e) => setRow("penetrations", i, "quantity", e.target.value)} /></Field>
            <Field label="Roof Plane" className="w-36"><Select value={row.facet_ref || "none"} disabled={!editable} onValueChange={(v) => setRow("penetrations", i, "facet_ref", v === "none" ? "" : v)}><SelectTrigger className="w-full"><SelectValue placeholder="Roof plane" /></SelectTrigger><SelectContent><SelectItem value="none">—</SelectItem>{facetOptions.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select></Field>
            <Field label="Diameter (in)" className="w-28"><Input type="number" value={row.diameter_in ?? ""} disabled={!editable} onChange={(e) => setRow("penetrations", i, "diameter_in", e.target.value)} /></Field>
            <Field label="Width (in)" className="w-24"><Input type="number" value={row.width_in ?? ""} disabled={!editable} onChange={(e) => setRow("penetrations", i, "width_in", e.target.value)} /></Field>
            <Field label="Length (in)" className="w-24"><Input type="number" value={row.length_in ?? ""} disabled={!editable} onChange={(e) => setRow("penetrations", i, "length_in", e.target.value)} /></Field>
            <Field label="Notes" className="min-w-44 flex-1"><Input value={row.notes || ""} disabled={!editable} onChange={(e) => setRow("penetrations", i, "notes", e.target.value)} /></Field>
            {editable && <Button size="icon" variant="ghost" className="mb-0.5" onClick={() => delRow("penetrations", i)}><Trash2 className="h-4 w-4 text-rose-500" /></Button>}
          </div>
          {row.id && <div className="mt-1"><PhotoGallery compact hideWhenEmpty recordType="measurement_penetration" recordId={row.id} /></div>}
        </div>)}
      </TableCard>

      <div className="rounded-lg border border-border p-3" data-testid="measurement-existing-roof-card">
        <div className="mb-2 text-sm font-semibold text-slate-700">Existing Roof & Deck</div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Existing Covering"><Input value={ed.summary.existing_covering_type || ""} disabled={!editable} onChange={(e) => setSummary("existing_covering_type", e.target.value)} /></Field>
          <Field label="Existing Condition"><Input value={ed.summary.existing_condition || ""} disabled={!editable} onChange={(e) => setSummary("existing_condition", e.target.value)} /></Field>
          <Field label="Existing Layers"><Input type="number" value={ed.summary.existing_layers ?? ""} disabled={!editable} onChange={(e) => setSummary("existing_layers", num(e.target.value))} /></Field>
          <Field label="Existing Underlayment"><Input value={ed.summary.existing_underlayment || ""} disabled={!editable} onChange={(e) => setSummary("existing_underlayment", e.target.value)} /></Field>
          <Field label="Deck Type"><Input value={ed.summary.deck_type || ""} disabled={!editable} onChange={(e) => setSummary("deck_type", e.target.value)} /></Field>
          <Field label="Deck Thickness (in)"><Input type="number" value={ed.summary.deck_thickness_in ?? ""} disabled={!editable} onChange={(e) => setSummary("deck_thickness_in", num(e.target.value))} /></Field>
          <Field label="Damaged Deck (SF)"><Input type="number" value={ed.summary.damaged_deck_sf ?? ""} disabled={!editable} onChange={(e) => setSummary("damaged_deck_sf", num(e.target.value))} /></Field>
          <Field label="Replacement Sheets"><Input type="number" value={ed.summary.replacement_sheets ?? ""} disabled={!editable} onChange={(e) => setSummary("replacement_sheets", num(e.target.value))} /></Field>
        </div>
        <label className="mt-3 flex items-center gap-1.5 text-sm text-slate-600"><input type="checkbox" checked={!!ed.summary.full_redeck} disabled={!editable} onChange={(e) => setSummary("full_redeck", e.target.checked)} />Full Re-deck</label>
      </div>

      <div className="rounded-lg border border-border p-3" data-testid="measurement-ventilation-card">
        <div className="mb-2 text-sm font-semibold text-slate-700">Ventilation</div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Drip Edge (LF)"><Input type="number" value={ed.summary.drip_edge_lf ?? ""} disabled={!editable} onChange={(e) => setSummary("drip_edge_lf", num(e.target.value))} /></Field>
          <Field label="Ridge Vent (LF)"><Input type="number" value={ed.summary.ridge_vent_lf ?? ""} disabled={!editable} onChange={(e) => setSummary("ridge_vent_lf", num(e.target.value))} /></Field>
          <Field label="Soffit Intake Vent (LF)"><Input type="number" value={ed.summary.intake_soffit_vent_lf ?? ""} disabled={!editable} onChange={(e) => setSummary("intake_soffit_vent_lf", num(e.target.value))} /></Field>
        </div>
      </div>

      <div className="rounded-lg border border-border p-3" data-testid="measurement-access-card">
        <div className="mb-2 text-sm font-semibold text-slate-700">Access / Conditions</div>
        <div className="flex flex-wrap gap-4 text-sm">
          {[["steep_access", "Steep Access"], ["high_access", "High Access"], ["long_carry", "Long Carry"], ["restricted_access", "Restricted Access"], ["landscaping_protection", "Landscaping Protection"]].map(([k, label]) => <label key={k} className="flex items-center gap-1.5 text-slate-600"><input type="checkbox" checked={!!ed.summary[k]} disabled={!editable} onChange={(e) => setSummary(k, e.target.checked)} />{label}</label>)}
        </div>
        <Textarea className="mt-3" placeholder="Conditions notes" value={ed.summary.conditions_notes || ""} disabled={!editable} onChange={(e) => setSummary("conditions_notes", e.target.value)} />
      </div>

      <div className="rounded-lg border border-border p-3" data-testid="measurement-gutters-card">
        <details data-testid="office-gutters">
          <summary className="cursor-pointer text-sm font-semibold text-slate-700">Gutters (Optional)</summary>
          <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="Gutter LF"><Input type="number" value={ed.summary.gutter_lf ?? ""} disabled={!editable} onChange={(e) => setSummary("gutter_lf", num(e.target.value))} /></Field>
            <Field label="Gutter Size"><Input value={ed.summary.gutter_size || ""} disabled={!editable} onChange={(e) => setSummary("gutter_size", e.target.value)} /></Field>
            <Field label="Gutter Type"><Input value={ed.summary.gutter_type || ""} disabled={!editable} onChange={(e) => setSummary("gutter_type", e.target.value)} /></Field>
            <Field label="Downspout Count"><Input type="number" value={ed.summary.downspout_count ?? ""} disabled={!editable} onChange={(e) => setSummary("downspout_count", num(e.target.value))} /></Field>
            <Field label="Downspout LF"><Input type="number" value={ed.summary.downspout_lf ?? ""} disabled={!editable} onChange={(e) => setSummary("downspout_lf", num(e.target.value))} /></Field>
            <Field label="Gutter Guard LF"><Input type="number" value={ed.summary.gutter_guard_lf ?? ""} disabled={!editable} onChange={(e) => setSummary("gutter_guard_lf", num(e.target.value))} /></Field>
          </div>
          <div className="mt-2"><Field label="Gutter Notes"><Input value={ed.summary.gutter_notes || ""} disabled={!editable} onChange={(e) => setSummary("gutter_notes", e.target.value)} /></Field></div>
        </details>
      </div>

      {rev.status === "locked" && <div className="text-xs text-slate-500"><Lock className="mr-1 inline h-3 w-3" />This revision is locked. Use “New revision” to make changes — history is preserved.</div>}
      <div className="rounded-lg border border-border p-3" data-testid="measurement-allphotos-card"><div className="mb-2 text-sm font-semibold text-slate-700">Measurement Photos</div><PhotoGallery sourceUrl={`/mobile/photos/measurement/${rev.id}`} testid="measurement-allphotos" hideWhenEmpty={false} recordType="measurement_all" recordId={rev.id} /></div>
    </>}
    {sketchFor && rev && (() => {
      const scoped = scopeForStructure({ structure: { id: sketchFor.id }, facets: ed?.facets || [], edges: ed?.edges || [], penetrations: ed?.penetrations || [] });
      return <RoofSketchEditor
        revision={{ id: rev.id, editable, status: rev.status }}
        structure={{ id: sketchFor.id, name: sketchFor.name || "Structure" }}
        facets={scoped.facets}
        edges={scoped.edges}
        penetrations={scoped.penetrations}
        onMeasurementChanged={applySketchProposal}
        onDiscardSession={discardEditorSession}
        onClose={() => { setSketchFor(null); if (rev?.id) listSketches(rev.id).then((rows) => setSketchStructIds(new Set(rows.map((r) => r.structure_id)))).catch(() => {}); }}
      />;
    })()}
  </div>;
}

function PitchSelect({ value, disabled, onChange }) {
  const inCommon = value != null && value !== "" && PITCHES.includes(Number(value));
  const [custom, setCustom] = useState(value != null && value !== "" && !inCommon);
  if (custom) {
    return <div className="flex items-center gap-1" data-testid="pitch-custom">
      <Input type="number" step="0.5" className="w-16" placeholder="rise" value={value ?? ""} disabled={disabled} onChange={(e) => onChange(num(e.target.value))} />
      <span className="text-xs text-slate-400">/12</span>
      <Button size="icon" variant="ghost" className="h-8 w-8 shrink-0" disabled={disabled} onClick={() => setCustom(false)} title="Choose a common pitch">↺</Button>
    </div>;
  }
  return <Select value={inCommon ? String(value) : ""} disabled={disabled} onValueChange={(v) => { if (v === "__custom__") setCustom(true); else onChange(Number(v)); }}>
    <SelectTrigger data-testid="pitch-select"><SelectValue placeholder="Pitch" /></SelectTrigger>
    <SelectContent>{PITCHES.map((p) => <SelectItem key={p} value={String(p)}>{p}/12</SelectItem>)}<SelectItem value="__custom__">Custom…</SelectItem></SelectContent>
  </Select>;
}

function Totm({ label, value, testid }) {
  return <div data-testid={testid}><div className="text-[11px] uppercase tracking-wide text-slate-400">{label}</div><div className="text-lg font-bold text-slate-800">{value}</div></div>;
}
function Field({ label, children, className }) { return <div className={`space-y-1 ${className || ""}`}><div className="text-[11px] font-medium uppercase text-slate-400">{label}</div>{children}</div>; }
function TableCard({ title, onAdd, children, testid }) {
  return <div className="rounded-lg border border-border p-3" data-testid={`measurement-${testid}-card`}><div className="mb-2 flex items-center justify-between"><div className="text-sm font-semibold text-slate-700">{title}</div>{onAdd && <Button size="sm" variant="outline" onClick={onAdd}><Plus className="mr-1 h-4 w-4" />Add</Button>}</div><div className="space-y-2">{children}</div></div>;
}

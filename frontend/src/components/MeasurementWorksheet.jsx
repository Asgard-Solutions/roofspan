import { useEffect, useState, useCallback, useMemo } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import PhotoGallery from "@/components/PhotoGallery";
import { Ruler, Plus, Trash2, Check, ShieldCheck, Lock, Undo2, Save, Loader2, GitBranch } from "lucide-react";

const STRUCTURE_TYPES = [
  ["main_house", "Main House"], ["attached_garage", "Attached Garage"], ["detached_garage", "Detached Garage"],
  ["porch", "Porch"], ["addition", "Addition"], ["shed", "Shed"], ["other", "Other"],
];
const EDGE_TYPES = [
  ["eave", "Eave"], ["rake", "Rake"], ["ridge", "Ridge"], ["hip", "Hip"], ["valley", "Valley"],
  ["sidewall", "Sidewall"], ["headwall", "Headwall"], ["transition", "Transition"],
];
const PEN_TYPES = [
  ["pipe_boot", "Pipe boot"], ["skylight", "Skylight"], ["chimney", "Chimney"], ["static_vent", "Static vent"],
  ["turbine", "Turbine"], ["powered_vent", "Powered vent"], ["exhaust_vent", "Exhaust vent"], ["satellite", "Satellite"], ["other", "Other"],
];
const STATUS_LABEL = {
  draft: "Draft", field_complete: "Field Complete", office_verified: "Office Verified", locked: "Locked",
};
const STATUS_STYLE = {
  draft: "bg-slate-100 text-slate-700", field_complete: "bg-amber-100 text-amber-800",
  office_verified: "bg-emerald-100 text-emerald-800", locked: "bg-slate-800 text-white",
};
const uid = () => "r" + Math.random().toString(36).slice(2, 10);

// Build editable local state from a loaded revision. Every facet/structure gets a stable local `ref`
// (its server id) so edges/penetrations can link by ref on save (works for both loaded + new rows).
function toEditable(rev) {
  const structures = (rev?.structures || []).map((s) => ({ ...s, ref: s.id }));
  const facets = (rev?.facets || []).map((f) => ({ ...f, ref: f.id, structure_ref: f.structure_id || "" }));
  const edges = (rev?.edges || []).map((e) => ({ ...e, _k: e.id, facet_ref: e.facet_id || "", facet_ref_secondary: e.facet_id_secondary || "" }));
  const pens = (rev?.penetrations || []).map((p) => ({ ...p, _k: p.id, facet_ref: p.facet_id || "" }));
  const summary = rev?.summary || {};
  return { structures, facets, edges, penetrations: pens, summary };
}

export default function MeasurementWorksheet({ leadId, propertyId, inspectionId }) {
  const { user } = useAuth();
  const isOffice = ["owner", "administrator", "office"].includes(user?.role);
  const [list, setList] = useState([]);
  const [rev, setRev] = useState(null);          // full current revision (from API)
  const [ed, setEd] = useState(null);            // editable local doc
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const scopeParam = leadId ? `lead_id=${leadId}` : `property_id=${propertyId}`;

  const loadList = useCallback(async () => {
    try {
      const r = (await api.get(`/measurements?${scopeParam}`)).data;
      setList(r);
      return r;
    } catch (e) { return []; }
  }, [scopeParam]);

  const loadRevision = useCallback(async (id) => {
    const r = (await api.get(`/measurements/${id}`)).data;
    setRev(r);
    setEd(toEditable(r));
    setDirty(false);
  }, []);

  useEffect(() => {
    (async () => {
      setLoading(true);
      const r = await loadList();
      if (r.length) await loadRevision(r[0].id);
      else { setRev(null); setEd(null); }
      setLoading(false);
    })();
  }, [loadList, loadRevision]);

  const editable = rev ? rev.editable : true;
  const totals = rev?.totals;

  // ---- live totals from local editable state (so the worksheet updates before save) ----
  const liveTotals = useMemo(() => {
    if (!ed) return null;
    const area = ed.facets.reduce((s, f) => s + (parseFloat(f.area_sqft) || 0), 0);
    const byPitch = {};
    ed.facets.forEach((f) => { const p = f.pitch_rise ?? "—"; byPitch[p] = (byPitch[p] || 0) + (parseFloat(f.area_sqft) || 0); });
    const edge = {};
    ed.edges.forEach((e) => { const k = e.edge_type; edge[k] = (edge[k] || 0) + (parseFloat(e.length_ft) || 0); });
    const pen = ed.penetrations.reduce((s, p) => s + (parseInt(p.quantity) || 0), 0);
    return { area, squares: area / 100, byPitch, edge, pen, facets: ed.facets.length, structures: ed.structures.length };
  }, [ed]);

  const mut = (patch) => { setEd((d) => ({ ...d, ...patch })); setDirty(true); };
  const setRow = (key, i, field, value) => {
    setEd((d) => { const arr = [...d[key]]; arr[i] = { ...arr[i], [field]: value }; return { ...d, [key]: arr }; });
    setDirty(true);
  };
  const addRow = (key, row) => { setEd((d) => ({ ...d, [key]: [...d[key], row] })); setDirty(true); };
  const delRow = (key, i) => { setEd((d) => ({ ...d, [key]: d[key].filter((_, idx) => idx !== i) })); setDirty(true); };
  const setSummary = (field, value) => { setEd((d) => ({ ...d, summary: { ...d.summary, [field]: value } })); setDirty(true); };

  const buildPayload = () => ({
    lead_id: leadId || null, property_id: propertyId || null, inspection_id: inspectionId || null,
    source: rev?.source || "office", reported_area_sqft: ed.reported_area_sqft ?? rev?.reported_area_sqft ?? null,
    structures: ed.structures.map((s, i) => ({ ref: s.ref, name: s.name, structure_type: s.structure_type, stories: s.stories ? parseFloat(s.stories) : null, notes: s.notes, sort: i })),
    facets: ed.facets.map((f, i) => ({ ref: f.ref, structure_ref: f.structure_ref || null, facet_label: f.facet_label, pitch_rise: f.pitch_rise === "" || f.pitch_rise == null ? null : parseFloat(f.pitch_rise), area_sqft: parseFloat(f.area_sqft) || 0, roof_material: f.roof_material, notes: f.notes, sort: i })),
    edges: ed.edges.map((e, i) => ({ edge_type: e.edge_type, length_ft: parseFloat(e.length_ft) || 0, facet_ref: e.facet_ref || null, facet_ref_secondary: e.facet_ref_secondary || null, label: e.label, sort: i })),
    penetrations: ed.penetrations.map((p, i) => ({ pen_type: p.pen_type, quantity: parseInt(p.quantity) || 1, facet_ref: p.facet_ref || null, width_in: p.width_in ? parseFloat(p.width_in) : null, length_in: p.length_in ? parseFloat(p.length_in) : null, diameter_in: p.diameter_in ? parseFloat(p.diameter_in) : null, sort: i })),
    summary: ed.summary || {},
  });

  const save = async () => {
    setBusy(true);
    try {
      const body = buildPayload();
      let saved;
      if (rev) saved = (await api.put(`/measurements/${rev.id}`, body)).data;
      else saved = (await api.post(`/measurements`, body)).data;
      toast.success("Measurement saved");
      await loadList();
      setRev(saved); setEd(toEditable(saved)); setDirty(false);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const startNew = async () => {
    setBusy(true);
    try {
      const body = { lead_id: leadId || null, property_id: propertyId || null, inspection_id: inspectionId || null, source: "office", structures: [], facets: [], edges: [], penetrations: [], summary: {} };
      const saved = (await api.post(`/measurements`, body)).data;
      await loadList(); setRev(saved); setEd(toEditable(saved)); setDirty(false);
      toast.success("New measurement started");
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const cloneRevision = async () => {
    setBusy(true);
    try {
      const nr = (await api.post(`/measurements/${rev.id}/new-revision`)).data;
      await loadList(); setRev(nr); setEd(toEditable(nr)); setDirty(false);
      toast.success(`Revision ${nr.revision_number} created for editing`);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const changeStatus = async (to) => {
    setBusy(true);
    try {
      const r = (await api.post(`/measurements/${rev.id}/status`, { to })).data;
      await loadList(); setRev(r); setEd(toEditable(r)); setDirty(false);
      toast.success(`Marked ${STATUS_LABEL[to]}`);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  if (loading) return <div className="p-3 text-sm text-slate-500" data-testid="measurement-loading"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />Loading measurements…</div>;

  const structOptions = (ed?.structures || []).filter((s) => s.ref).map((s) => [s.ref, s.name || STRUCTURE_TYPES.find((t) => t[0] === s.structure_type)?.[1] || "Structure"]);
  const facetOptions = (ed?.facets || []).filter((f) => f.ref).map((f) => [f.ref, f.facet_label || "Facet"]);
  const t = liveTotals;

  return (
    <div className="space-y-4" data-testid="measurement-worksheet">
      {/* Header: revision selector + status + actions */}
      <div className="flex flex-wrap items-center gap-2">
        {list.length > 0 && (
          <Select value={rev?.id || ""} onValueChange={(v) => loadRevision(v)}>
            <SelectTrigger className="w-[230px]" data-testid="measurement-revision-select"><SelectValue placeholder="Select revision" /></SelectTrigger>
            <SelectContent>
              {list.map((r) => (
                <SelectItem key={r.id} value={r.id} data-testid={`measurement-rev-option-${r.revision_number}`}>
                  Rev {r.revision_number} · {STATUS_LABEL[r.status]} · {r.total_squares} sq
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        {rev && <Badge className={STATUS_STYLE[rev.status]} data-testid="measurement-status-badge">{STATUS_LABEL[rev.status]}</Badge>}
        {rev && rev.supersedes_revision_id && <span className="text-xs text-slate-400">supersedes an earlier revision</span>}
        <div className="ml-auto flex flex-wrap gap-2">
          {!rev && <Button size="sm" onClick={startNew} disabled={busy} data-testid="measurement-start-btn"><Plus className="mr-1 h-4 w-4" />Start measurement</Button>}
          {rev && !editable && <Button size="sm" variant="outline" onClick={cloneRevision} disabled={busy} data-testid="measurement-new-revision-btn"><GitBranch className="mr-1 h-4 w-4" />New revision</Button>}
          {rev && editable && dirty && <Button size="sm" onClick={save} disabled={busy} data-testid="measurement-save-btn">{busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Save className="mr-1 h-4 w-4" />}Save</Button>}
          {rev && rev.status === "draft" && !dirty && <Button size="sm" variant="outline" onClick={() => changeStatus("field_complete")} disabled={busy} data-testid="measurement-fieldcomplete-btn"><Check className="mr-1 h-4 w-4" />Field Complete</Button>}
          {rev && rev.status === "field_complete" && isOffice && <Button size="sm" variant="outline" onClick={() => changeStatus("office_verified")} disabled={busy} data-testid="measurement-verify-btn"><ShieldCheck className="mr-1 h-4 w-4" />Office Verify</Button>}
          {rev && rev.status === "office_verified" && isOffice && <Button size="sm" variant="outline" onClick={() => changeStatus("locked")} disabled={busy} data-testid="measurement-lock-btn"><Lock className="mr-1 h-4 w-4" />Lock</Button>}
          {rev && ["field_complete", "office_verified"].includes(rev.status) && isOffice && <Button size="sm" variant="ghost" onClick={() => changeStatus("draft")} disabled={busy} data-testid="measurement-return-btn"><Undo2 className="mr-1 h-4 w-4" />Return to field</Button>}
        </div>
      </div>

      {!rev && <div className="rounded border border-dashed border-border p-6 text-center text-sm text-slate-500" data-testid="measurement-empty">No roof measurement yet. Start one to capture structures, facets, edges and penetrations.</div>}

      {rev && ed && (
        <>
          {/* Totals panel */}
          <div className="grid grid-cols-2 gap-3 rounded-lg bg-slate-50 p-3 sm:grid-cols-4" data-testid="measurement-totals">
            <Totm label="Roof area" value={`${(t.area).toFixed(0)} sq ft`} testid="tot-area" />
            <Totm label="Squares" value={(t.squares).toFixed(2)} testid="tot-squares" />
            <Totm label="Facets" value={t.facets} testid="tot-facets" />
            <Totm label="Structures" value={t.structures} testid="tot-structures" />
          </div>
          {totals?.reported_area_sqft != null && (
            <div className="text-xs text-slate-500" data-testid="measurement-reported">
              Reported report area: {totals.reported_area_sqft} sq ft
              {totals.reported_area_delta_sqft != null && <span className={Math.abs(totals.reported_area_delta_sqft) > 50 ? "ml-2 font-medium text-amber-700" : "ml-2"}>(entered − reported: {totals.reported_area_delta_sqft} sq ft)</span>}
            </div>
          )}
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600" data-testid="measurement-edge-totals">
            {EDGE_TYPES.map(([k, lbl]) => (t.edge[k] ? <span key={k}>{lbl}: <b>{(t.edge[k]).toFixed(0)} LF</b></span> : null))}
            {t.pen ? <span>Penetrations: <b>{t.pen}</b></span> : null}
          </div>

          {/* Structures */}
          <TableCard title="Structures" onAdd={editable ? () => addRow("structures", { ref: uid(), name: "", structure_type: "main_house" }) : null} testid="structures">
            {ed.structures.map((s, i) => (
              <div key={s.ref || i} className="flex flex-wrap items-center gap-2" data-testid={`structure-row-${i}`}>
                <Input className="w-40" placeholder="Name" value={s.name || ""} disabled={!editable} onChange={(e) => setRow("structures", i, "name", e.target.value)} data-testid={`structure-name-${i}`} />
                <Select value={s.structure_type} disabled={!editable} onValueChange={(v) => setRow("structures", i, "structure_type", v)}>
                  <SelectTrigger className="w-44" data-testid={`structure-type-${i}`}><SelectValue /></SelectTrigger>
                  <SelectContent>{STRUCTURE_TYPES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
                </Select>
                <Input className="w-24" type="number" placeholder="Stories" value={s.stories || ""} disabled={!editable} onChange={(e) => setRow("structures", i, "stories", e.target.value)} data-testid={`structure-stories-${i}`} />
                {editable && <Button size="icon" variant="ghost" onClick={() => delRow("structures", i)} data-testid={`structure-del-${i}`}><Trash2 className="h-4 w-4 text-rose-500" /></Button>}
              </div>
            ))}
          </TableCard>

          {/* Facets */}
          <TableCard title="Roof facets" onAdd={editable ? () => addRow("facets", { ref: uid(), facet_label: `F${ed.facets.length + 1}`, pitch_rise: "", area_sqft: "" }) : null} testid="facets">
            <div className="hidden grid-cols-[90px_130px_110px_120px_1fr_40px] gap-2 text-[11px] font-semibold uppercase text-slate-400 sm:grid"><span>Facet</span><span>Structure</span><span>Pitch /12</span><span>Area sq ft</span><span>Notes</span><span /></div>
            {ed.facets.map((f, i) => (
              <div key={f.ref || i} data-testid={`facet-block-${i}`}>
              <div className="grid grid-cols-2 items-center gap-2 sm:grid-cols-[90px_130px_110px_120px_1fr_40px]" data-testid={`facet-row-${i}`}>
                <Input className="" placeholder="F1" value={f.facet_label || ""} disabled={!editable} onChange={(e) => setRow("facets", i, "facet_label", e.target.value)} data-testid={`facet-label-${i}`} />
                <Select value={f.structure_ref || "none"} disabled={!editable} onValueChange={(v) => setRow("facets", i, "structure_ref", v === "none" ? "" : v)}>
                  <SelectTrigger data-testid={`facet-structure-${i}`}><SelectValue placeholder="—" /></SelectTrigger>
                  <SelectContent><SelectItem value="none">—</SelectItem>{structOptions.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
                </Select>
                <Input type="number" step="0.5" placeholder="6" value={f.pitch_rise ?? ""} disabled={!editable} onChange={(e) => setRow("facets", i, "pitch_rise", e.target.value)} data-testid={`facet-pitch-${i}`} />
                <Input type="number" placeholder="0" value={f.area_sqft ?? ""} disabled={!editable} onChange={(e) => setRow("facets", i, "area_sqft", e.target.value)} data-testid={`facet-area-${i}`} />
                <Input placeholder="Notes" value={f.notes || ""} disabled={!editable} onChange={(e) => setRow("facets", i, "notes", e.target.value)} data-testid={`facet-notes-${i}`} />
                {editable && <Button size="icon" variant="ghost" onClick={() => delRow("facets", i)} data-testid={`facet-del-${i}`}><Trash2 className="h-4 w-4 text-rose-500" /></Button>}
              </div>
              {f.id && <div className="mt-1 pl-1"><PhotoGallery compact hideWhenEmpty recordType="measurement_facet" recordId={f.id} testid={`facet-photos-${i}`} /></div>}
              </div>
            ))}
          </TableCard>

          {/* Edges */}
          <TableCard title="Edges (linear feet)" onAdd={editable ? () => addRow("edges", { _k: uid(), edge_type: "eave", length_ft: "" }) : null} testid="edges">
            {ed.edges.map((e, i) => (
              <div key={e._k || i} className="flex flex-wrap items-center gap-2" data-testid={`edge-row-${i}`}>
                <Select value={e.edge_type} disabled={!editable} onValueChange={(v) => setRow("edges", i, "edge_type", v)}>
                  <SelectTrigger className="w-36" data-testid={`edge-type-${i}`}><SelectValue /></SelectTrigger>
                  <SelectContent>{EDGE_TYPES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
                </Select>
                <Input className="w-28" type="number" placeholder="LF" value={e.length_ft ?? ""} disabled={!editable} onChange={(ev) => setRow("edges", i, "length_ft", ev.target.value)} data-testid={`edge-length-${i}`} />
                <Select value={e.facet_ref || "none"} disabled={!editable} onValueChange={(v) => setRow("edges", i, "facet_ref", v === "none" ? "" : v)}>
                  <SelectTrigger className="w-32" data-testid={`edge-facet-${i}`}><SelectValue placeholder="Facet" /></SelectTrigger>
                  <SelectContent><SelectItem value="none">—</SelectItem>{facetOptions.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
                </Select>
                {editable && <Button size="icon" variant="ghost" onClick={() => delRow("edges", i)} data-testid={`edge-del-${i}`}><Trash2 className="h-4 w-4 text-rose-500" /></Button>}
              </div>
            ))}
          </TableCard>

          {/* Penetrations */}
          <TableCard title="Penetrations" onAdd={editable ? () => addRow("penetrations", { _k: uid(), pen_type: "pipe_boot", quantity: 1 }) : null} testid="penetrations">
            {ed.penetrations.map((p, i) => (
              <div key={p._k || i} data-testid={`pen-block-${i}`}>
              <div className="flex flex-wrap items-center gap-2" data-testid={`pen-row-${i}`}>
                <Select value={p.pen_type} disabled={!editable} onValueChange={(v) => setRow("penetrations", i, "pen_type", v)}>
                  <SelectTrigger className="w-40" data-testid={`pen-type-${i}`}><SelectValue /></SelectTrigger>
                  <SelectContent>{PEN_TYPES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
                </Select>
                <Input className="w-24" type="number" placeholder="Qty" value={p.quantity ?? 1} disabled={!editable} onChange={(e) => setRow("penetrations", i, "quantity", e.target.value)} data-testid={`pen-qty-${i}`} />
                {editable && <Button size="icon" variant="ghost" onClick={() => delRow("penetrations", i)} data-testid={`pen-del-${i}`}><Trash2 className="h-4 w-4 text-rose-500" /></Button>}
              </div>
              {p.id && <div className="mt-1 pl-1"><PhotoGallery compact hideWhenEmpty recordType="measurement_penetration" recordId={p.id} testid={`pen-photos-${i}`} /></div>}
              </div>
            ))}
          </TableCard>

          {/* Summary / conditions */}
          <div className="rounded-lg border border-border p-3" data-testid="measurement-summary-card">
            <div className="mb-2 text-sm font-semibold text-slate-700">Existing roof, decking & conditions</div>
            <div className="grid gap-2 sm:grid-cols-3">
              <Field label="Existing covering"><Input value={ed.summary.existing_covering_type || ""} disabled={!editable} onChange={(e) => setSummary("existing_covering_type", e.target.value)} data-testid="sum-covering" /></Field>
              <Field label="Layers"><Input type="number" value={ed.summary.existing_layers ?? ""} disabled={!editable} onChange={(e) => setSummary("existing_layers", e.target.value ? parseInt(e.target.value) : null)} data-testid="sum-layers" /></Field>
              <Field label="Deck type"><Input value={ed.summary.deck_type || ""} disabled={!editable} onChange={(e) => setSummary("deck_type", e.target.value)} data-testid="sum-decktype" /></Field>
              <Field label="Damaged deck SF"><Input type="number" value={ed.summary.damaged_deck_sf ?? ""} disabled={!editable} onChange={(e) => setSummary("damaged_deck_sf", e.target.value ? parseFloat(e.target.value) : null)} data-testid="sum-damagedsf" /></Field>
              <Field label="Replacement sheets"><Input type="number" value={ed.summary.replacement_sheets ?? ""} disabled={!editable} onChange={(e) => setSummary("replacement_sheets", e.target.value ? parseInt(e.target.value) : null)} data-testid="sum-sheets" /></Field>
              <Field label="Ridge vent LF"><Input type="number" value={ed.summary.ridge_vent_lf ?? ""} disabled={!editable} onChange={(e) => setSummary("ridge_vent_lf", e.target.value ? parseFloat(e.target.value) : null)} data-testid="sum-ridgevent" /></Field>
            </div>
            <div className="mt-2 flex flex-wrap gap-4 text-sm">
              {[["full_redeck", "Full re-deck"], ["steep_access", "Steep"], ["high_access", "High"], ["long_carry", "Long carry"], ["restricted_access", "Restricted access"]].map(([k, lbl]) => (
                <label key={k} className="flex items-center gap-1.5 text-slate-600"><input type="checkbox" checked={!!ed.summary[k]} disabled={!editable} onChange={(e) => setSummary(k, e.target.checked)} data-testid={`sum-${k}`} />{lbl}</label>
              ))}
            </div>
            <Textarea className="mt-2" placeholder="Condition / access notes" value={ed.summary.conditions_notes || ""} disabled={!editable} onChange={(e) => setSummary("conditions_notes", e.target.value)} data-testid="sum-notes" />
          </div>

          {rev.status === "locked" && <div className="text-xs text-slate-500" data-testid="measurement-locked-note"><Lock className="mr-1 inline h-3 w-3" />This revision is locked. Use "New revision" to make changes — history is preserved.</div>}

          {/* All measurement photos (revision + structures + facets + penetrations) */}
          <div className="rounded-lg border border-border p-3" data-testid="measurement-allphotos-card">
            <div className="mb-2 text-sm font-semibold text-slate-700">All measurement photos</div>
            <PhotoGallery sourceUrl={`/mobile/photos/measurement/${rev.id}`} testid="measurement-allphotos" hideWhenEmpty={false} recordType="measurement_all" recordId={rev.id} />
          </div>
        </>
      )}
    </div>
  );
}

function Totm({ label, value, testid }) {
  return <div data-testid={testid}><div className="text-[11px] uppercase tracking-wide text-slate-400">{label}</div><div className="text-lg font-bold text-slate-800" data-testid={`${testid}-value`}>{value}</div></div>;
}
function Field({ label, children }) {
  return <div className="space-y-1"><div className="text-[11px] font-medium uppercase text-slate-400">{label}</div>{children}</div>;
}
function TableCard({ title, onAdd, children, testid }) {
  return (
    <div className="rounded-lg border border-border p-3" data-testid={`measurement-${testid}-card`}>
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-semibold text-slate-700">{title}</div>
        {onAdd && <Button size="sm" variant="outline" onClick={onAdd} data-testid={`measurement-add-${testid}`}><Plus className="mr-1 h-4 w-4" />Add</Button>}
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

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
import { Plus, Trash2, Check, ShieldCheck, Lock, Undo2, Save, Loader2, GitBranch } from "lucide-react";

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
const STATUS_LABEL = { draft: "Draft", field_complete: "Field Complete", office_verified: "Office Verified", locked: "Locked" };
const STATUS_STYLE = {
  draft: "bg-slate-100 text-slate-700", field_complete: "bg-amber-100 text-amber-800",
  office_verified: "bg-emerald-100 text-emerald-800", locked: "bg-slate-800 text-white",
};
const uid = () => "r" + Math.random().toString(36).slice(2, 10);
const num = (value) => value === "" || value == null ? null : (Number.isFinite(Number(value)) ? Number(value) : null);

function toEditable(rev) {
  return {
    reported_area_sqft: rev?.reported_area_sqft ?? null,
    structures: (rev?.structures || []).map((row) => ({ ...row, ref: row.id || row.ref || uid(), included_in_scope: row.included_in_scope !== false })),
    facets: (rev?.facets || []).map((row) => ({ ...row, ref: row.id || row.ref || uid(), structure_ref: row.structure_id || row.structure_ref || "" })),
    edges: (rev?.edges || []).map((row) => ({ ...row, _k: row.id || uid(), facet_ref: row.facet_id || "", facet_ref_secondary: row.facet_id_secondary || "" })),
    penetrations: (rev?.penetrations || []).map((row) => ({ ...row, _k: row.id || uid(), facet_ref: row.facet_id || "" })),
    summary: rev?.summary || {},
  };
}

export default function MeasurementWorksheet({ leadId, propertyId, inspectionId }) {
  const { user } = useAuth();
  const isOffice = ["owner", "administrator", "office"].includes(user?.role);
  const [list, setList] = useState([]);
  const [rev, setRev] = useState(null);
  const [ed, setEd] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

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
    setEd((doc) => { const rows = [...doc[key]]; rows[i] = { ...rows[i], [field]: value }; return { ...doc, [key]: rows }; });
    setDirty(true);
  };
  const addRow = (key, row) => { setEd((doc) => ({ ...doc, [key]: [...doc[key], row] })); setDirty(true); };
  const delRow = (key, i) => { setEd((doc) => ({ ...doc, [key]: doc[key].filter((_, idx) => idx !== i) })); setDirty(true); };
  const setSummary = (field, value) => { setEd((doc) => ({ ...doc, summary: { ...doc.summary, [field]: value } })); setDirty(true); };

  const buildPayload = () => ({
    lead_id: leadId || null, property_id: propertyId || null, inspection_id: inspectionId || null,
    source: rev?.source || "office", reported_area_sqft: num(ed.reported_area_sqft),
    structures: ed.structures.map((row, i) => ({
      ref: row.ref, name: row.name || "", structure_type: row.structure_type || "main_house",
      included_in_scope: row.included_in_scope !== false, stories: num(row.stories), approx_height_ft: num(row.approx_height_ft),
      attachment: row.attachment || null, notes: row.notes || null, sort: i,
    })),
    facets: ed.facets.map((row, i) => ({
      ref: row.ref, structure_ref: row.structure_ref || null, facet_label: row.facet_label || `F${i + 1}`,
      pitch_rise: num(row.pitch_rise), area_sqft: parseFloat(row.area_sqft) || 0,
      width_ft: num(row.width_ft), length_ft: num(row.length_ft), orientation_azimuth: num(row.orientation_azimuth),
      roof_material: row.roof_material || null, notes: row.notes || null, geometry: row.geometry || null, sort: i,
    })),
    edges: ed.edges.map((row, i) => ({
      edge_type: row.edge_type, length_ft: parseFloat(row.length_ft) || 0, facet_ref: row.facet_ref || null,
      facet_ref_secondary: row.facet_ref_secondary || null, label: row.label || null, notes: row.notes || null, sort: i,
    })),
    penetrations: ed.penetrations.map((row, i) => ({
      pen_type: row.pen_type, quantity: parseInt(row.quantity) || 1, facet_ref: row.facet_ref || null,
      width_in: num(row.width_in), length_in: num(row.length_in), diameter_in: num(row.diameter_in), notes: row.notes || null, sort: i,
    })),
    summary: ed.summary || {},
  });

  const save = async () => {
    setBusy(true);
    try {
      const body = buildPayload();
      const saved = rev ? (await api.put(`/measurements/${rev.id}`, body)).data : (await api.post(`/measurements`, body)).data;
      toast.success("Measurement saved");
      await loadList(); setRev(saved); setEd(toEditable(saved)); setDirty(false);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
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

  if (loading) return <div className="p-3 text-sm text-slate-500" data-testid="measurement-loading"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />Loading measurements…</div>;

  const structOptions = (ed?.structures || []).filter((row) => row.ref).map((row) => [row.ref, row.name || STRUCTURE_TYPES.find((t) => t[0] === row.structure_type)?.[1] || "Structure"]);
  const facetOptions = (ed?.facets || []).filter((row) => row.ref).map((row) => [row.ref, row.facet_label || "Facet"]);
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
        {rev && editable && dirty && <Button size="sm" onClick={save} disabled={busy}>{busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Save className="mr-1 h-4 w-4" />}Save</Button>}
        {rev?.status === "draft" && !dirty && <Button size="sm" variant="outline" onClick={() => changeStatus("field_complete")} disabled={busy}><Check className="mr-1 h-4 w-4" />Field Complete</Button>}
        {rev?.status === "field_complete" && isOffice && <Button size="sm" variant="outline" onClick={() => changeStatus("office_verified")} disabled={busy}><ShieldCheck className="mr-1 h-4 w-4" />Office Verify</Button>}
        {rev?.status === "office_verified" && isOffice && <Button size="sm" variant="outline" onClick={() => changeStatus("locked")} disabled={busy}><Lock className="mr-1 h-4 w-4" />Lock</Button>}
        {rev && ["field_complete", "office_verified"].includes(rev.status) && isOffice && <Button size="sm" variant="ghost" onClick={() => changeStatus("draft")} disabled={busy}><Undo2 className="mr-1 h-4 w-4" />Return to field</Button>}
      </div>
    </div>

    {!rev && <div className="rounded border border-dashed border-border p-6 text-center text-sm text-slate-500">No roof measurement yet. Start one to capture structures, facets, edges and penetrations.</div>}

    {rev && ed && <>
      <div className="grid grid-cols-2 gap-3 rounded-lg bg-slate-50 p-3 sm:grid-cols-5" data-testid="measurement-totals">
        <Totm label="Measured area" value={`${t.area.toFixed(0)} sq ft`} testid="tot-area" />
        <Totm label="Measured squares" value={t.squares.toFixed(2)} testid="tot-squares" />
        <Totm label="Takeoff squares" value={t.takeoffSquares.toFixed(2)} testid="tot-takeoff-squares" />
        <Totm label="Facets" value={t.facets} testid="tot-facets" />
        <Totm label="Structures" value={t.structures} testid="tot-structures" />
      </div>
      {hasScopeExclusion && <div className="rounded border border-blue-200 bg-blue-50 p-2 text-xs text-blue-900">Measured totals retain every structure. Takeoff totals exclude structures marked “Exclude from estimate.”</div>}
      {totals?.reported_area_sqft != null && <div className="text-xs text-slate-500">Reported report area: {totals.reported_area_sqft} sq ft {totals.reported_area_delta_sqft != null && <span className={Math.abs(totals.reported_area_delta_sqft) > 50 ? "ml-2 font-medium text-amber-700" : "ml-2"}>(entered − reported: {totals.reported_area_delta_sqft} sq ft)</span>}</div>}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">{EDGE_TYPES.map(([k, label]) => t.edge[k] ? <span key={k}>{label}: <b>{t.edge[k].toFixed(0)} LF</b></span> : null)}{t.pen ? <span>Penetrations: <b>{t.pen}</b></span> : null}</div>

      <TableCard title="Structures" onAdd={editable ? () => addRow("structures", { ref: uid(), name: "", structure_type: "main_house", included_in_scope: true }) : null} testid="structures">
        {ed.structures.map((row, i) => <div key={row.ref || i} className="rounded border border-slate-100 p-2" data-testid={`structure-row-${i}`}>
          <div className="flex flex-wrap items-center gap-2">
            <Input className="w-40" placeholder="Name" value={row.name || ""} disabled={!editable} onChange={(e) => setRow("structures", i, "name", e.target.value)} />
            <Select value={row.structure_type} disabled={!editable} onValueChange={(v) => setRow("structures", i, "structure_type", v)}><SelectTrigger className="w-44"><SelectValue /></SelectTrigger><SelectContent>{STRUCTURE_TYPES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select>
            <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={row.included_in_scope !== false} disabled={!editable} onChange={(e) => setRow("structures", i, "included_in_scope", e.target.checked)} />Include in estimate</label>
            <Input className="w-24" type="number" placeholder="Stories" value={row.stories ?? ""} disabled={!editable} onChange={(e) => setRow("structures", i, "stories", e.target.value)} />
            <Input className="w-28" type="number" placeholder="Height ft" value={row.approx_height_ft ?? ""} disabled={!editable} onChange={(e) => setRow("structures", i, "approx_height_ft", e.target.value)} />
            <Select value={row.attachment || "none"} disabled={!editable} onValueChange={(v) => setRow("structures", i, "attachment", v === "none" ? "" : v)}><SelectTrigger className="w-32"><SelectValue placeholder="Attachment" /></SelectTrigger><SelectContent><SelectItem value="none">—</SelectItem><SelectItem value="attached">Attached</SelectItem><SelectItem value="detached">Detached</SelectItem></SelectContent></Select>
            {editable && <Button size="icon" variant="ghost" onClick={() => delRow("structures", i)}><Trash2 className="h-4 w-4 text-rose-500" /></Button>}
          </div>
          <Input className="mt-2" placeholder="Structure notes" value={row.notes || ""} disabled={!editable} onChange={(e) => setRow("structures", i, "notes", e.target.value)} />
        </div>)}
      </TableCard>

      <TableCard title="Roof facets" onAdd={editable ? () => addRow("facets", { ref: uid(), facet_label: `F${ed.facets.length + 1}`, pitch_rise: "", area_sqft: "" }) : null} testid="facets">
        {ed.facets.map((row, i) => <div key={row.ref || i} className="rounded border border-slate-100 p-2" data-testid={`facet-block-${i}`}>
          <div className="grid grid-cols-2 items-center gap-2 lg:grid-cols-[80px_150px_90px_120px_100px_100px_1fr_40px]">
            <Input placeholder="F1" value={row.facet_label || ""} disabled={!editable} onChange={(e) => setRow("facets", i, "facet_label", e.target.value)} />
            <Select value={row.structure_ref || "none"} disabled={!editable} onValueChange={(v) => setRow("facets", i, "structure_ref", v === "none" ? "" : v)}><SelectTrigger><SelectValue placeholder="Structure" /></SelectTrigger><SelectContent><SelectItem value="none">—</SelectItem>{structOptions.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select>
            <Input type="number" step="0.5" placeholder="Pitch" value={row.pitch_rise ?? ""} disabled={!editable} onChange={(e) => setRow("facets", i, "pitch_rise", e.target.value)} />
            <Input type="number" placeholder="Area SF" value={row.area_sqft ?? ""} disabled={!editable} onChange={(e) => setRow("facets", i, "area_sqft", e.target.value)} />
            <Input type="number" placeholder="Width ft" value={row.width_ft ?? ""} disabled={!editable} onChange={(e) => setRow("facets", i, "width_ft", e.target.value)} />
            <Input type="number" placeholder="Length ft" value={row.length_ft ?? ""} disabled={!editable} onChange={(e) => setRow("facets", i, "length_ft", e.target.value)} />
            <Input placeholder="Roof material" value={row.roof_material || ""} disabled={!editable} onChange={(e) => setRow("facets", i, "roof_material", e.target.value)} />
            {editable && <Button size="icon" variant="ghost" onClick={() => delRow("facets", i)}><Trash2 className="h-4 w-4 text-rose-500" /></Button>}
          </div>
          <Input className="mt-2" placeholder="Facet notes" value={row.notes || ""} disabled={!editable} onChange={(e) => setRow("facets", i, "notes", e.target.value)} />
          {row.id && <div className="mt-1"><PhotoGallery compact hideWhenEmpty recordType="measurement_facet" recordId={row.id} /></div>}
        </div>)}
      </TableCard>

      <TableCard title="Edges (linear feet)" onAdd={editable ? () => addRow("edges", { _k: uid(), edge_type: "eave", length_ft: "" }) : null} testid="edges">
        {ed.edges.map((row, i) => <div key={row._k || i} className="flex flex-wrap items-center gap-2">
          <Select value={row.edge_type} disabled={!editable} onValueChange={(v) => setRow("edges", i, "edge_type", v)}><SelectTrigger className="w-36"><SelectValue /></SelectTrigger><SelectContent>{EDGE_TYPES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select>
          <Input className="w-28" type="number" placeholder="LF" value={row.length_ft ?? ""} disabled={!editable} onChange={(e) => setRow("edges", i, "length_ft", e.target.value)} />
          <Select value={row.facet_ref || "none"} disabled={!editable} onValueChange={(v) => setRow("edges", i, "facet_ref", v === "none" ? "" : v)}><SelectTrigger className="w-32"><SelectValue placeholder="Facet" /></SelectTrigger><SelectContent><SelectItem value="none">—</SelectItem>{facetOptions.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select>
          <Input className="min-w-44 flex-1" placeholder="Label / notes" value={row.label || row.notes || ""} disabled={!editable} onChange={(e) => setRow("edges", i, "notes", e.target.value)} />
          {editable && <Button size="icon" variant="ghost" onClick={() => delRow("edges", i)}><Trash2 className="h-4 w-4 text-rose-500" /></Button>}
        </div>)}
      </TableCard>

      <TableCard title="Penetrations" onAdd={editable ? () => addRow("penetrations", { _k: uid(), pen_type: "pipe_boot", quantity: 1 }) : null} testid="penetrations">
        {ed.penetrations.map((row, i) => <div key={row._k || i} className="rounded border border-slate-100 p-2">
          <div className="flex flex-wrap items-center gap-2">
            <Select value={row.pen_type} disabled={!editable} onValueChange={(v) => setRow("penetrations", i, "pen_type", v)}><SelectTrigger className="w-40"><SelectValue /></SelectTrigger><SelectContent>{PEN_TYPES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select>
            <Input className="w-20" type="number" placeholder="Qty" value={row.quantity ?? 1} disabled={!editable} onChange={(e) => setRow("penetrations", i, "quantity", e.target.value)} />
            <Select value={row.facet_ref || "none"} disabled={!editable} onValueChange={(v) => setRow("penetrations", i, "facet_ref", v === "none" ? "" : v)}><SelectTrigger className="w-32"><SelectValue placeholder="Facet" /></SelectTrigger><SelectContent><SelectItem value="none">—</SelectItem>{facetOptions.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select>
            <Input className="w-28" type="number" placeholder="Diameter in" value={row.diameter_in ?? ""} disabled={!editable} onChange={(e) => setRow("penetrations", i, "diameter_in", e.target.value)} />
            <Input className="w-24" type="number" placeholder="Width in" value={row.width_in ?? ""} disabled={!editable} onChange={(e) => setRow("penetrations", i, "width_in", e.target.value)} />
            <Input className="w-24" type="number" placeholder="Length in" value={row.length_in ?? ""} disabled={!editable} onChange={(e) => setRow("penetrations", i, "length_in", e.target.value)} />
            <Input className="min-w-44 flex-1" placeholder="Notes" value={row.notes || ""} disabled={!editable} onChange={(e) => setRow("penetrations", i, "notes", e.target.value)} />
            {editable && <Button size="icon" variant="ghost" onClick={() => delRow("penetrations", i)}><Trash2 className="h-4 w-4 text-rose-500" /></Button>}
          </div>
          {row.id && <div className="mt-1"><PhotoGallery compact hideWhenEmpty recordType="measurement_penetration" recordId={row.id} /></div>}
        </div>)}
      </TableCard>

      <div className="rounded-lg border border-border p-3" data-testid="measurement-summary-card">
        <div className="mb-2 text-sm font-semibold text-slate-700">Existing roof, decking & conditions</div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Existing covering"><Input value={ed.summary.existing_covering_type || ""} disabled={!editable} onChange={(e) => setSummary("existing_covering_type", e.target.value)} /></Field>
          <Field label="Existing condition"><Input value={ed.summary.existing_condition || ""} disabled={!editable} onChange={(e) => setSummary("existing_condition", e.target.value)} /></Field>
          <Field label="Existing underlayment"><Input value={ed.summary.existing_underlayment || ""} disabled={!editable} onChange={(e) => setSummary("existing_underlayment", e.target.value)} /></Field>
          <Field label="Layers"><Input type="number" value={ed.summary.existing_layers ?? ""} disabled={!editable} onChange={(e) => setSummary("existing_layers", num(e.target.value))} /></Field>
          <Field label="Deck type"><Input value={ed.summary.deck_type || ""} disabled={!editable} onChange={(e) => setSummary("deck_type", e.target.value)} /></Field>
          <Field label="Deck thickness in"><Input type="number" value={ed.summary.deck_thickness_in ?? ""} disabled={!editable} onChange={(e) => setSummary("deck_thickness_in", num(e.target.value))} /></Field>
          <Field label="Damaged deck SF"><Input type="number" value={ed.summary.damaged_deck_sf ?? ""} disabled={!editable} onChange={(e) => setSummary("damaged_deck_sf", num(e.target.value))} /></Field>
          <Field label="Replacement sheets"><Input type="number" value={ed.summary.replacement_sheets ?? ""} disabled={!editable} onChange={(e) => setSummary("replacement_sheets", num(e.target.value))} /></Field>
          <Field label="Measured drip edge LF"><Input type="number" value={ed.summary.drip_edge_lf ?? ""} disabled={!editable} onChange={(e) => setSummary("drip_edge_lf", num(e.target.value))} /></Field>
          <Field label="Ridge vent LF"><Input type="number" value={ed.summary.ridge_vent_lf ?? ""} disabled={!editable} onChange={(e) => setSummary("ridge_vent_lf", num(e.target.value))} /></Field>
          <Field label="Soffit intake LF"><Input type="number" value={ed.summary.intake_soffit_vent_lf ?? ""} disabled={!editable} onChange={(e) => setSummary("intake_soffit_vent_lf", num(e.target.value))} /></Field>
          <Field label="Reported area SF"><Input type="number" value={ed.reported_area_sqft ?? ""} disabled={!editable} onChange={(e) => { setEd((doc) => ({ ...doc, reported_area_sqft: e.target.value })); setDirty(true); }} /></Field>
        </div>
        <div className="mt-3 flex flex-wrap gap-4 text-sm">
          {[["full_redeck", "Full re-deck"], ["steep_access", "Steep access"], ["high_access", "High access"], ["long_carry", "Long carry"], ["restricted_access", "Restricted access"], ["landscaping_protection", "Landscape protection"]].map(([k, label]) => <label key={k} className="flex items-center gap-1.5 text-slate-600"><input type="checkbox" checked={!!ed.summary[k]} disabled={!editable} onChange={(e) => setSummary(k, e.target.checked)} />{label}</label>)}
        </div>
        <Textarea className="mt-3" placeholder="Condition / access notes" value={ed.summary.conditions_notes || ""} disabled={!editable} onChange={(e) => setSummary("conditions_notes", e.target.value)} />
      </div>

      {rev.status === "locked" && <div className="text-xs text-slate-500"><Lock className="mr-1 inline h-3 w-3" />This revision is locked. Use “New revision” to make changes — history is preserved.</div>}
      <div className="rounded-lg border border-border p-3" data-testid="measurement-allphotos-card"><div className="mb-2 text-sm font-semibold text-slate-700">All measurement photos</div><PhotoGallery sourceUrl={`/mobile/photos/measurement/${rev.id}`} testid="measurement-allphotos" hideWhenEmpty={false} recordType="measurement_all" recordId={rev.id} /></div>
    </>}
  </div>;
}

function Totm({ label, value, testid }) {
  return <div data-testid={testid}><div className="text-[11px] uppercase tracking-wide text-slate-400">{label}</div><div className="text-lg font-bold text-slate-800">{value}</div></div>;
}
function Field({ label, children }) { return <div className="space-y-1"><div className="text-[11px] font-medium uppercase text-slate-400">{label}</div>{children}</div>; }
function TableCard({ title, onAdd, children, testid }) {
  return <div className="rounded-lg border border-border p-3" data-testid={`measurement-${testid}-card`}><div className="mb-2 flex items-center justify-between"><div className="text-sm font-semibold text-slate-700">{title}</div>{onAdd && <Button size="sm" variant="outline" onClick={onAdd}><Plus className="mr-1 h-4 w-4" />Add</Button>}</div><div className="space-y-2">{children}</div></div>;
}

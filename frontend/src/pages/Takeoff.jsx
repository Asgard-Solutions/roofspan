import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { AlertTriangle, Calculator, CheckCircle2, Layers, Plus, RefreshCw, Save } from "lucide-react";

const METRICS = [
  ["roof_squares", "Roof squares"], ["roof_area_sqft", "Roof area (sq ft)"],
  ["eave_lf", "Eave LF"], ["rake_lf", "Rake LF"], ["ridge_lf", "Ridge LF"],
  ["hip_lf", "Hip LF"], ["valley_lf", "Valley LF"], ["drip_edge_lf", "Drip edge LF (eave + rake)"],
  ["sidewall_lf", "Sidewall LF"], ["headwall_lf", "Headwall LF"], ["tearoff_squares", "Tear-off squares × layers"],
  ["ridge_vent_lf", "Ridge vent LF"], ["intake_soffit_vent_lf", "Soffit intake LF"],
  ["damaged_deck_sf", "Damaged decking SF"], ["replacement_sheets", "Decking sheets"],
  ["penetration_total", "All penetrations"], ["penetration:pipe_boot", "Pipe boots"],
  ["penetration:skylight", "Skylights"], ["penetration:chimney", "Chimneys"],
  ["stories", "Stories"], ["steep_access", "Steep access flag"], ["high_access", "High access flag"],
  ["long_carry", "Long carry flag"], ["restricted_access", "Restricted access flag"],
];

const blankRule = () => ({ name: "", metric_key: "roof_squares", quantity_factor: 1, apply_waste: true,
  assembly_id: "", assembly_waste_percent: "", coverage_per_package: "" });

export default function Takeoff() {
  const [settings, setSettings] = useState({ default_waste_percent: 10 });
  const [templates, setTemplates] = useState([]);
  const [assemblies, setAssemblies] = useState([]);
  const [estimates, setEstimates] = useState([]);
  const [estimateId, setEstimateId] = useState("");
  const [measurements, setMeasurements] = useState([]);
  const [measurementId, setMeasurementId] = useState("");
  const [measurement, setMeasurement] = useState(null);
  const [templateRevisionId, setTemplateRevisionId] = useState("");
  const [estimateWaste, setEstimateWaste] = useState("");
  const [dripOverride, setDripOverride] = useState("");
  const [structureWaste, setStructureWaste] = useState({});
  const [preview, setPreview] = useState(null);
  const [status, setStatus] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const [busy, setBusy] = useState(false);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [revisionTemplateId, setRevisionTemplateId] = useState(null);
  const [templateForm, setTemplateForm] = useState({ name: "", description: "", default_waste_percent: 10, notes: "", rules: [blankRule()] });

  const selectedEstimate = useMemo(() => estimates.find((e) => e.id === estimateId), [estimates, estimateId]);
  const verifiedMeasurements = useMemo(() => measurements.filter((m) => ["office_verified", "locked"].includes(m.status)), [measurements]);
  const templateRevisions = useMemo(() => templates.map((t) => t.latest_revision).filter(Boolean), [templates]);

  const loadReference = useCallback(async () => {
    try {
      const [s, t, a, e] = await Promise.all([
        api.get("/takeoff/settings"), api.get("/takeoff/templates", { params: { active: true } }),
        api.get("/estimating/assemblies", { params: { active: true } }), api.get("/estimates"),
      ]);
      setSettings(s.data); setTemplates(t.data); setAssemblies(a.data); setEstimates(e.data);
    } catch (err) { toast.error(apiError(err)); }
  }, []);
  useEffect(() => { loadReference(); }, [loadReference]);

  useEffect(() => {
    setMeasurements([]); setMeasurementId(""); setMeasurement(null); setPreview(null); setWarnings([]); setStatus(null);
    if (!selectedEstimate) return;
    const params = selectedEstimate.property_id ? { property_id: selectedEstimate.property_id } :
      (selectedEstimate.inspection_id ? { inspection_id: selectedEstimate.inspection_id } : null);
    if (!params) return;
    api.get("/measurements", { params }).then(({ data }) => {
      setMeasurements(data);
      const first = data.find((m) => ["office_verified", "locked"].includes(m.status));
      if (first) setMeasurementId(first.id);
    }).catch((e) => toast.error(apiError(e)));
    api.get(`/takeoff/estimates/${selectedEstimate.id}/status`).then(({ data }) => setStatus(data)).catch(() => {});
  }, [selectedEstimate]);

  useEffect(() => {
    setMeasurement(null); setWarnings([]); setStructureWaste({}); setPreview(null);
    if (!measurementId) return;
    Promise.all([api.get(`/measurements/${measurementId}`), api.get(`/takeoff/measurements/${measurementId}/warnings`)]).then(([m, w]) => {
      setMeasurement(m.data); setWarnings(w.data.warnings || []);
    }).catch((e) => toast.error(apiError(e)));
  }, [measurementId]);

  const payload = (replace = false) => ({
    measurement_revision_id: measurementId,
    template_revision_id: templateRevisionId,
    estimate_waste_override: estimateWaste === "" ? null : Number(estimateWaste),
    drip_edge_override_lf: dripOverride === "" ? null : Number(dripOverride),
    structure_waste_overrides: Object.fromEntries(Object.entries(structureWaste).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)])),
    replace_modified_generated: replace,
  });

  const doPreview = async () => {
    if (!estimateId || !measurementId || !templateRevisionId) return toast.error("Select an estimate, verified measurement revision, and takeoff template.");
    setBusy(true);
    try { const { data } = await api.post(`/takeoff/estimates/${estimateId}/preview`, payload(false)); setPreview(data); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const doApply = async (replace = false) => {
    setBusy(true);
    try {
      const { data } = await api.post(`/takeoff/estimates/${estimateId}/apply`, payload(replace));
      toast.success(`Takeoff applied — ${data.created_line_ids.length} estimate line(s) generated`);
      setPreview(null);
      const st = await api.get(`/takeoff/estimates/${estimateId}/status`); setStatus(st.data);
      const es = await api.get("/estimates"); setEstimates(es.data);
    } catch (e) {
      if (e?.response?.status === 409 && e?.response?.data?.detail?.code === "TAKEOFF_GENERATED_LINES_MODIFIED") {
        setPreview((p) => ({ ...(p || {}), review_required: true, manually_modified_generated_lines: e.response.data.detail.lines || [] }));
        toast.warning("Takeoff-generated lines were manually edited. Review before replacing.");
      } else toast.error(apiError(e));
    } finally { setBusy(false); }
  };

  const saveDefaultWaste = async () => {
    try {
      const { data } = await api.put("/takeoff/settings", null, { params: { default_waste_percent: Number(settings.default_waste_percent) } });
      setSettings(data); toast.success("Company takeoff waste default saved");
    } catch (e) { toast.error(apiError(e)); }
  };

  const openNewTemplate = () => {
    setRevisionTemplateId(null); setTemplateForm({ name: "", description: "", default_waste_percent: 10, notes: "", rules: [blankRule()] }); setTemplateOpen(true);
  };
  const openNewRevision = (t) => {
    const r = t.latest_revision;
    setRevisionTemplateId(t.id);
    setTemplateForm({ name: t.name, description: t.description || "", default_waste_percent: r?.default_waste_percent ?? 10, notes: r?.notes || "",
      rules: (r?.rules || []).map((x) => ({ name: x.name, metric_key: x.metric_key, quantity_factor: x.quantity_factor, apply_waste: x.apply_waste,
        assembly_id: x.assembly_id || "", assembly_waste_percent: x.assembly_waste_percent ?? "", coverage_per_package: x.coverage_per_package ?? "" })) || [blankRule()] });
    setTemplateOpen(true);
  };
  const setRule = (i, patch) => setTemplateForm((f) => ({ ...f, rules: f.rules.map((r, idx) => idx === i ? { ...r, ...patch } : r) }));
  const saveTemplate = async () => {
    const rules = templateForm.rules.filter((r) => r.name && r.assembly_id).map((r) => ({ ...r,
      quantity_factor: Number(r.quantity_factor) || 0,
      assembly_waste_percent: r.assembly_waste_percent === "" ? null : Number(r.assembly_waste_percent),
      coverage_per_package: r.coverage_per_package === "" ? null : Number(r.coverage_per_package),
    }));
    if (!rules.length) return toast.error("Add at least one named rule with an Assembly.");
    try {
      if (revisionTemplateId) {
        await api.post(`/takeoff/templates/${revisionTemplateId}/revisions`, { default_waste_percent: Number(templateForm.default_waste_percent), notes: templateForm.notes || null, rules });
        toast.success("New immutable takeoff template revision created");
      } else {
        await api.post("/takeoff/templates", { name: templateForm.name, description: templateForm.description || null, active: true,
          default_waste_percent: Number(templateForm.default_waste_percent), notes: templateForm.notes || null, rules });
        toast.success("Takeoff template created");
      }
      setTemplateOpen(false); await loadReference();
    } catch (e) { toast.error(apiError(e)); }
  };

  const wasteExtraSquares = measurement && preview ? ((Number(measurement.totals?.total_squares) || 0) * (Number(preview.effective_roof_waste_percent) || 0) / 100) : 0;

  return <div>
    <PageHeader title="Roof Takeoff" description="Bind verified roof measurements to versioned estimating templates without changing the physical measurement snapshot." testid="page-takeoff" />
    <div className="space-y-6 p-6 sm:p-8">
      <section className="rounded-md border bg-white p-4" data-testid="takeoff-settings">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div><div className="font-semibold text-slate-900">Company takeoff settings</div><div className="text-sm text-slate-500">Waste is an estimating assumption, not a roof measurement.</div></div>
          <div className="flex items-end gap-2"><div><Label className="text-xs">Default waste %</Label><Input className="w-28" type="number" value={settings.default_waste_percent} onChange={(e) => setSettings({ ...settings, default_waste_percent: e.target.value })} /></div><Button variant="outline" onClick={saveDefaultWaste}><Save className="h-4 w-4" /> Save</Button></div>
        </div>
      </section>

      <section className="rounded-md border bg-white p-4" data-testid="takeoff-templates">
        <div className="mb-3 flex items-center justify-between"><div><div className="font-semibold">Takeoff Templates</div><div className="text-sm text-slate-500">Every edit creates a new immutable revision with an Assembly snapshot.</div></div><Button onClick={openNewTemplate}><Plus className="h-4 w-4" /> New template</Button></div>
        <Table><TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Revision</TableHead><TableHead>Waste</TableHead><TableHead>Rules</TableHead><TableHead /></TableRow></TableHeader><TableBody>
          {templates.map((t) => <TableRow key={t.id}><TableCell className="font-medium">{t.name}</TableCell><TableCell>v{t.latest_revision?.revision_number || "—"}</TableCell><TableCell>{t.latest_revision?.default_waste_percent ?? 10}%</TableCell><TableCell>{t.latest_revision?.rules?.length || 0}</TableCell><TableCell className="text-right"><Button size="sm" variant="outline" onClick={() => openNewRevision(t)}>New revision</Button></TableCell></TableRow>)}
          {!templates.length && <TableRow><TableCell colSpan={5} className="py-6 text-center text-slate-400">No takeoff templates yet.</TableCell></TableRow>}
        </TableBody></Table>
      </section>

      <section className="rounded-md border bg-white p-4" data-testid="estimate-takeoff-workspace">
        <div className="mb-4"><div className="font-semibold text-slate-900">Estimate Takeoff</div><div className="text-sm text-slate-500">Select the exact measurement and template revisions. Recalculation is always explicit.</div></div>
        {status?.measurements_changed && <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900" data-testid="measurements-changed-warning">
          <div className="flex items-center gap-2 font-semibold"><AlertTriangle className="h-4 w-4" /> Measurements have changed since Estimate {selectedEstimate?.number} was calculated.</div>
          <div className="mt-1">Estimate used Revision {status.measurement_revision_number}; current is Revision {status.latest_measurement_revision_number}. Review the changes below and recalculate only when you choose.</div>
          {!!status.changed_metrics?.length && <div className="mt-2 max-h-36 overflow-auto rounded bg-white/70 p-2 text-xs">{status.changed_metrics.map((c) => <div key={c.metric}><b>{c.metric}</b>: {JSON.stringify(c.from)} → {JSON.stringify(c.to)}</div>)}</div>}
        </div>}
        <div className="grid gap-3 lg:grid-cols-3">
          <div><Label className="text-xs">Estimate</Label><Select value={estimateId} onValueChange={setEstimateId}><SelectTrigger data-testid="takeoff-estimate"><SelectValue placeholder="Select estimate" /></SelectTrigger><SelectContent>{estimates.map((e) => <SelectItem key={e.id} value={e.id}>{e.number} · {e.status}</SelectItem>)}</SelectContent></Select></div>
          <div><Label className="text-xs">Office-Verified Measurement Revision</Label><Select value={measurementId} onValueChange={setMeasurementId} disabled={!estimateId}><SelectTrigger data-testid="takeoff-measurement"><SelectValue placeholder="Select revision" /></SelectTrigger><SelectContent>{verifiedMeasurements.map((m) => <SelectItem key={m.id} value={m.id}>Revision {m.revision_number} · {m.status} · {Number(m.total_squares || 0).toFixed(2)} SQ</SelectItem>)}</SelectContent></Select></div>
          <div><Label className="text-xs">Takeoff Template Revision</Label><Select value={templateRevisionId} onValueChange={setTemplateRevisionId}><SelectTrigger data-testid="takeoff-template-revision"><SelectValue placeholder="Select template" /></SelectTrigger><SelectContent>{templateRevisions.map((r) => <SelectItem key={r.id} value={r.id}>{r.template_name} · v{r.revision_number}</SelectItem>)}</SelectContent></Select></div>
        </div>
        {measurement && <>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><div><Label className="text-xs">Estimate waste override %</Label><Input type="number" placeholder="Use template/default" value={estimateWaste} onChange={(e) => setEstimateWaste(e.target.value)} /></div><div><Label className="text-xs">Drip edge override LF</Label><Input type="number" placeholder={`${Number(measurement.totals?.edge_totals?.eave_lf || 0) + Number(measurement.totals?.edge_totals?.rake_lf || 0)} calculated`} value={dripOverride} onChange={(e) => setDripOverride(e.target.value)} /></div></div>
          {!!measurement.totals?.area_by_structure?.length && <div className="mt-3"><div className="mb-1 text-xs font-semibold uppercase text-slate-400">Per-structure waste override</div><div className="flex flex-wrap gap-3">{measurement.totals.area_by_structure.map((s) => s.structure_id && <div key={s.structure_id}><Label className="text-xs">{s.name} ({Number(s.squares).toFixed(2)} SQ)</Label><Input className="w-32" type="number" placeholder="Default" value={structureWaste[s.structure_id] ?? ""} onChange={(e) => setStructureWaste({ ...structureWaste, [s.structure_id]: e.target.value })} /></div>)}</div></div>}
          {!!warnings.length && <div className="mt-4 space-y-2">{warnings.map((w) => <div key={w.code} className="rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900"><AlertTriangle className="mr-1 inline h-4 w-4" /> {w.message}</div>)}</div>}
        </>}
        <div className="mt-4 flex gap-2"><Button variant="outline" onClick={doPreview} disabled={busy || !measurementId || !templateRevisionId}><Calculator className="h-4 w-4" /> Preview takeoff</Button>{status?.measurements_changed && status.latest_measurement_revision_id && <Button variant="ghost" onClick={() => setMeasurementId(status.latest_measurement_revision_id)}><RefreshCw className="h-4 w-4" /> Use latest revision</Button>}</div>

        {preview && <div className="mt-5 rounded-md border bg-slate-50 p-3" data-testid="takeoff-preview">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><div><b>Preview:</b> Measurement R{preview.measurement_revision_number} + Template v{preview.template_revision_number}</div><div className="flex gap-2"><Badge variant="secondary">Effective roof waste {Number(preview.effective_roof_waste_percent).toFixed(2)}%</Badge><Badge variant="secondary">+{wasteExtraSquares.toFixed(2)} SQ waste impact</Badge></div></div>
          {preview.review_required && <div className="mb-3 rounded border border-red-200 bg-red-50 p-2 text-sm text-red-800"><AlertTriangle className="mr-1 inline h-4 w-4" /> Previously generated lines were manually edited. Applying requires explicit replacement confirmation.</div>}
          <Table><TableHeader><TableRow><TableHead>Description</TableHead><TableHead>Assembly</TableHead><TableHead>Measured</TableHead><TableHead>Waste</TableHead><TableHead>Calculated Qty</TableHead></TableRow></TableHeader><TableBody>{preview.lines.map((l, i) => <TableRow key={`${l.description}-${i}`}><TableCell>{l.description}</TableCell><TableCell>{l.assembly_name || "—"} v{l.assembly_version || "—"}</TableCell><TableCell>{Number(l.measured_quantity).toFixed(2)} {l.unit}</TableCell><TableCell>{Number(l.waste_percent).toFixed(2)}%</TableCell><TableCell>{Number(l.quantity).toFixed(2)} {l.unit}</TableCell></TableRow>)}</TableBody></Table>
          <div className="mt-3 flex justify-end">{preview.review_required ? <Button variant="destructive" onClick={() => doApply(true)} disabled={busy}>Replace reviewed generated lines & recalculate</Button> : <Button onClick={() => doApply(false)} disabled={busy}><CheckCircle2 className="h-4 w-4" /> Apply to Estimate</Button>}</div>
        </div>}
      </section>
    </div>

    <Dialog open={templateOpen} onOpenChange={setTemplateOpen}><DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto" data-testid="takeoff-template-dialog">
      <DialogHeader><DialogTitle>{revisionTemplateId ? `New revision — ${templateForm.name}` : "New Takeoff Template"}</DialogTitle><DialogDescription>Rules map one measurement metric to an existing Assembly. Saving an existing template creates a new immutable revision.</DialogDescription></DialogHeader>
      {!revisionTemplateId && <div className="grid grid-cols-2 gap-3"><div><Label>Name</Label><Input value={templateForm.name} onChange={(e) => setTemplateForm({ ...templateForm, name: e.target.value })} /></div><div><Label>Description</Label><Input value={templateForm.description} onChange={(e) => setTemplateForm({ ...templateForm, description: e.target.value })} /></div></div>}
      <div className="grid grid-cols-2 gap-3"><div><Label>Template default waste %</Label><Input type="number" value={templateForm.default_waste_percent} onChange={(e) => setTemplateForm({ ...templateForm, default_waste_percent: e.target.value })} /></div><div><Label>Revision notes</Label><Input value={templateForm.notes} onChange={(e) => setTemplateForm({ ...templateForm, notes: e.target.value })} /></div></div>
      <div className="space-y-3"><div className="font-semibold">Rules</div>{templateForm.rules.map((r, i) => <div key={i} className="rounded border p-3"><div className="grid gap-2 lg:grid-cols-4"><div><Label className="text-xs">Rule name</Label><Input value={r.name} onChange={(e) => setRule(i, { name: e.target.value })} /></div><div><Label className="text-xs">Measurement metric</Label><Select value={r.metric_key} onValueChange={(v) => setRule(i, { metric_key: v })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{METRICS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select></div><div><Label className="text-xs">Assembly</Label><Select value={r.assembly_id || "none"} onValueChange={(v) => setRule(i, { assembly_id: v === "none" ? "" : v })}><SelectTrigger><SelectValue placeholder="Select Assembly" /></SelectTrigger><SelectContent><SelectItem value="none">Select Assembly</SelectItem>{assemblies.map((a) => <SelectItem key={a.id} value={a.id}>{a.name} · v{a.version}</SelectItem>)}</SelectContent></Select></div><div><Label className="text-xs">Metric multiplier</Label><Input type="number" value={r.quantity_factor} onChange={(e) => setRule(i, { quantity_factor: e.target.value })} /></div></div><div className="mt-2 flex flex-wrap items-end gap-4"><label className="flex items-center gap-2 text-sm"><Checkbox checked={r.apply_waste} onCheckedChange={(v) => setRule(i, { apply_waste: !!v })} /> Apply waste to material items</label><div><Label className="text-xs">Assembly waste default %</Label><Input className="w-32" type="number" placeholder="inherit" value={r.assembly_waste_percent} onChange={(e) => setRule(i, { assembly_waste_percent: e.target.value })} /></div><div><Label className="text-xs">Coverage per package (optional)</Label><Input className="w-40" type="number" placeholder="e.g. 0.333 SQ" value={r.coverage_per_package} onChange={(e) => setRule(i, { coverage_per_package: e.target.value })} /></div><Button variant="ghost" size="sm" onClick={() => setTemplateForm((f) => ({ ...f, rules: f.rules.filter((_, idx) => idx !== i) }))}>Remove</Button></div></div>)}<Button variant="outline" size="sm" onClick={() => setTemplateForm((f) => ({ ...f, rules: [...f.rules, blankRule()] }))}><Plus className="h-4 w-4" /> Add rule</Button></div>
      <DialogFooter><Button variant="outline" onClick={() => setTemplateOpen(false)}>Cancel</Button><Button onClick={saveTemplate} disabled={!revisionTemplateId && !templateForm.name}><Layers className="h-4 w-4" /> {revisionTemplateId ? "Create Revision" : "Create Template"}</Button></DialogFooter>
    </DialogContent></Dialog>
  </div>;
}

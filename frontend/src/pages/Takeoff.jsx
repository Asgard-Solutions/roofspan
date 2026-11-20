import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Layers, Plus, Save } from "lucide-react";

const METRICS = [
  ["roof_squares", "Roof squares (included structures)"], ["roof_area_sqft", "Roof area SF (included structures)"],
  ["roof_squares_pitch_gte:7", "Roof squares at 7/12+"], ["roof_squares_pitch_gte:9", "Roof squares at 9/12+"],
  ["roof_squares_pitch_gte:12", "Roof squares at 12/12+"], ["roof_area_sqft_pitch_gte:7", "Roof area SF at 7/12+"],
  ["roof_area_sqft_pitch_gte:9", "Roof area SF at 9/12+"], ["roof_area_sqft_pitch_gte:12", "Roof area SF at 12/12+"],
  ["eave_lf", "Eave LF"], ["rake_lf", "Rake LF"], ["ridge_lf", "Ridge LF"], ["hip_lf", "Hip LF"],
  ["valley_lf", "Valley LF"], ["drip_edge_lf", "Drip edge LF (measured, else eave + rake)"],
  ["sidewall_lf", "Sidewall LF"], ["headwall_lf", "Headwall LF"], ["transition_lf", "Transition LF"],
  ["tearoff_squares", "Tear-off squares × layers"], ["ridge_vent_lf", "Ridge vent LF"],
  ["intake_soffit_vent_lf", "Soffit intake LF"], ["damaged_deck_sf", "Damaged decking SF"],
  ["replacement_sheets", "Decking sheets"], ["penetration_total", "All penetrations"],
  ["penetration:pipe_boot", "Pipe boots"], ["penetration:skylight", "Skylights"], ["penetration:chimney", "Chimneys"],
  ["penetration:static_vent", "Static vents"], ["penetration:turbine", "Turbines"], ["penetration:powered_vent", "Powered vents"],
  ["penetration:exhaust_vent", "Exhaust vents"], ["penetration:satellite", "Satellite dishes"],
  ["stories", "Maximum included stories"], ["height_ft", "Maximum included height (ft)"],
  ["steep_access", "Steep access flag"], ["high_access", "High access flag"], ["long_carry", "Long carry flag"],
  ["restricted_access", "Restricted access flag"], ["landscaping_protection", "Landscape protection flag"],
];
const blankRule = () => ({ name: "", metric_key: "roof_squares", quantity_factor: 1, apply_waste: true, assembly_id: "", assembly_waste_percent: "", coverage_per_package: "" });
const coverageLabel = (source) => ({ template_rule: "Template override", material_catalog: "Product catalog", supplier_conversion: "Supplier conversion" }[source] || "—");

export default function Takeoff() {
  const [settings, setSettings] = useState({ default_waste_percent: 10 });
  const [templates, setTemplates] = useState([]);
  const [assemblies, setAssemblies] = useState([]);
  const [busy, setBusy] = useState(false);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [revisionTemplateId, setRevisionTemplateId] = useState(null);
  const [templateForm, setTemplateForm] = useState({ name: "", description: "", default_waste_percent: 10, notes: "", rules: [blankRule()] });


  const loadReference = useCallback(async () => {
    try {
      const [s, t, a] = await Promise.all([
        api.get("/takeoff/settings"), api.get("/takeoff/templates", { params: { active: true } }),
        api.get("/estimating/assemblies", { params: { active: true } }),
      ]);
      setSettings(s.data); setTemplates(t.data); setAssemblies(a.data);
    } catch (err) { toast.error(apiError(err)); }
  }, []);
  useEffect(() => { loadReference(); }, [loadReference]);

  const saveDefaultWaste = async () => {
    try { setSettings((await api.put("/takeoff/settings", null, { params: { default_waste_percent: Number(settings.default_waste_percent) } })).data); toast.success("Company takeoff waste default saved"); }
    catch (e) { toast.error(apiError(e)); }
  };

  const openNewTemplate = () => { setRevisionTemplateId(null); setTemplateForm({ name: "", description: "", default_waste_percent: 10, notes: "", rules: [blankRule()] }); setTemplateOpen(true); };
  const openNewRevision = (template) => {
    const r = template.latest_revision;
    setRevisionTemplateId(template.id);
    setTemplateForm({ name: template.name, description: template.description || "", default_waste_percent: r?.default_waste_percent ?? 10, notes: r?.notes || "",
      rules: (r?.rules || []).map((x) => ({ name: x.name, metric_key: x.metric_key, quantity_factor: x.quantity_factor, apply_waste: x.apply_waste, assembly_id: x.assembly_id || "", assembly_waste_percent: x.assembly_waste_percent ?? "", coverage_per_package: x.coverage_per_package ?? "" })) || [blankRule()] });
    setTemplateOpen(true);
  };
  const setRule = (i, patch) => setTemplateForm((form) => ({ ...form, rules: form.rules.map((row, idx) => idx === i ? { ...row, ...patch } : row) }));
  const saveTemplate = async () => {
    const rules = templateForm.rules.filter((row) => row.name && row.assembly_id).map((row) => ({ ...row,
      quantity_factor: Number(row.quantity_factor) || 0,
      assembly_waste_percent: row.assembly_waste_percent === "" ? null : Number(row.assembly_waste_percent),
      coverage_per_package: row.coverage_per_package === "" ? null : Number(row.coverage_per_package),
    }));
    if (!rules.length) return toast.error("Add at least one named rule with an Assembly.");
    try {
      if (revisionTemplateId) {
        await api.post(`/takeoff/templates/${revisionTemplateId}/revisions`, { default_waste_percent: Number(templateForm.default_waste_percent), notes: templateForm.notes || null, rules });
        toast.success("New version saved");
      } else {
        await api.post("/takeoff/templates", { name: templateForm.name, description: templateForm.description || null, active: true, default_waste_percent: Number(templateForm.default_waste_percent), notes: templateForm.notes || null, rules });
        toast.success("Takeoff template created");
      }
      setTemplateOpen(false); await loadReference();
    } catch (e) { toast.error(apiError(e)); }
  };

  return <div>
    <PageHeader title="Roof Takeoff Setup" description="Roof systems (takeoff templates) turn roof measurements into estimate materials." testid="page-takeoff" actions={<Link to="/settings" className="text-sm font-medium text-orange-700 hover:underline" data-testid="back-to-settings">All settings</Link>} />
    <div className="space-y-6 p-6 sm:p-8">
      <section className="rounded-md border bg-white p-4" data-testid="takeoff-settings">
        <div className="flex flex-wrap items-end justify-between gap-3"><div><div className="font-semibold text-slate-900">Company takeoff settings</div><div className="text-sm text-slate-500">Waste is an estimating assumption, not a roof measurement.</div></div><div className="flex items-end gap-2"><div><Label className="text-xs">Default waste %</Label><Input className="w-28" type="number" value={settings.default_waste_percent} onChange={(e) => setSettings({ ...settings, default_waste_percent: e.target.value })} /></div><Button variant="outline" onClick={saveDefaultWaste}><Save className="h-4 w-4" /> Save</Button></div></div>
      </section>

      <section className="rounded-md border bg-white p-4" data-testid="takeoff-templates">
        <div className="mb-3 flex items-center justify-between"><div><div className="font-semibold">Roof systems (takeoff templates)</div><div className="text-sm text-slate-500">Each change saves a new version. Estimates keep the version they were calculated with.</div></div><Button onClick={openNewTemplate} data-testid="takeoff-new-template"><Plus className="h-4 w-4" /> New template</Button></div>
        <Table><TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Version</TableHead><TableHead>Waste</TableHead><TableHead>Rules</TableHead><TableHead /></TableRow></TableHeader><TableBody>{templates.map((template) => <TableRow key={template.id}><TableCell className="font-medium">{template.name}</TableCell><TableCell>v{template.latest_revision?.revision_number || "—"}</TableCell><TableCell>{template.latest_revision?.default_waste_percent ?? 10}%</TableCell><TableCell>{template.latest_revision?.rules?.length || 0}</TableCell><TableCell className="text-right"><Button size="sm" variant="outline" onClick={() => openNewRevision(template)} data-testid={`takeoff-edit-template-${template.id}`}>Edit (new version)</Button></TableCell></TableRow>)}{!templates.length && <TableRow><TableCell colSpan={5} className="py-6 text-center text-slate-400">No takeoff templates yet.</TableCell></TableRow>}</TableBody></Table>
      </section>

      <p className="text-sm text-slate-500" data-testid="takeoff-setup-usage-note">To use a roof system, open an estimate and choose <b>Calculate materials</b> under Roof measurements.</p>
    </div>

    <Dialog open={templateOpen} onOpenChange={setTemplateOpen}><DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto" data-testid="takeoff-template-dialog">
      <DialogHeader><DialogTitle>{revisionTemplateId ? `Edit ${templateForm.name} (new version)` : "New Takeoff Template"}</DialogTitle><DialogDescription>Each rule turns one roof measurement into an assembly of materials. Saving an existing template saves a new version.</DialogDescription></DialogHeader>
      {!revisionTemplateId && <div className="grid grid-cols-2 gap-3"><div><Label>Name</Label><Input value={templateForm.name} onChange={(e) => setTemplateForm({ ...templateForm, name: e.target.value })} /></div><div><Label>Description</Label><Input value={templateForm.description} onChange={(e) => setTemplateForm({ ...templateForm, description: e.target.value })} /></div></div>}
      <div className="grid grid-cols-2 gap-3"><div><Label>Template default waste %</Label><Input type="number" value={templateForm.default_waste_percent} onChange={(e) => setTemplateForm({ ...templateForm, default_waste_percent: e.target.value })} /></div><div><Label>Revision notes</Label><Input value={templateForm.notes} onChange={(e) => setTemplateForm({ ...templateForm, notes: e.target.value })} /></div></div>
      <div className="space-y-3"><div className="font-semibold">Rules</div>{templateForm.rules.map((rule, i) => <div key={i} className="rounded border p-3"><div className="grid gap-2 lg:grid-cols-4"><div><Label className="text-xs">Rule name</Label><Input value={rule.name} onChange={(e) => setRule(i, { name: e.target.value })} /></div><div><Label className="text-xs">Measurement metric</Label><Select value={rule.metric_key} onValueChange={(v) => setRule(i, { metric_key: v })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{METRICS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select></div><div><Label className="text-xs">Assembly</Label><Select value={rule.assembly_id || "none"} onValueChange={(v) => setRule(i, { assembly_id: v === "none" ? "" : v })}><SelectTrigger><SelectValue placeholder="Select Assembly" /></SelectTrigger><SelectContent><SelectItem value="none">Select Assembly</SelectItem>{assemblies.map((a) => <SelectItem key={a.id} value={a.id}>{a.name} · v{a.version}</SelectItem>)}</SelectContent></Select></div><div><Label className="text-xs">Quantity multiplier</Label><Input type="number" value={rule.quantity_factor} onChange={(e) => setRule(i, { quantity_factor: e.target.value })} /></div></div><div className="mt-2 flex flex-wrap items-end gap-4"><label className="flex items-center gap-2 text-sm"><Checkbox checked={rule.apply_waste} onCheckedChange={(v) => setRule(i, { apply_waste: !!v })} /> Apply waste to material items</label><div><Label className="text-xs">Assembly waste default %</Label><Input className="w-32" type="number" placeholder="inherit" value={rule.assembly_waste_percent} onChange={(e) => setRule(i, { assembly_waste_percent: e.target.value })} /></div><div><Label className="text-xs">Package coverage (optional)</Label><Input className="w-44" type="number" placeholder="blank = product catalog" value={rule.coverage_per_package} onChange={(e) => setRule(i, { coverage_per_package: e.target.value })} /></div><Button variant="ghost" size="sm" onClick={() => setTemplateForm((form) => ({ ...form, rules: form.rules.filter((_, idx) => idx !== i) }))}>Remove</Button></div><div className="mt-1 text-xs text-slate-400">Leave package coverage blank to use the product's coverage from the catalog (or the supplier conversion).</div></div>)}<Button variant="outline" size="sm" onClick={() => setTemplateForm((form) => ({ ...form, rules: [...form.rules, blankRule()] }))}><Plus className="h-4 w-4" /> Add rule</Button></div>
      <DialogFooter><Button variant="outline" onClick={() => setTemplateOpen(false)}>Cancel</Button><Button onClick={saveTemplate} disabled={!revisionTemplateId && !templateForm.name}><Layers className="h-4 w-4" /> {revisionTemplateId ? "Save new version" : "Create Template"}</Button></DialogFooter>
    </DialogContent></Dialog>
  </div>;
}

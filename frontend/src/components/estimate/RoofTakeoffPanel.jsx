import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { shortDate } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { AlertTriangle, Calculator, CheckCircle2, ChevronDown, Ruler } from "lucide-react";

const VERIFIED = ["office_verified", "locked"];
const coverageLabel = (s) => ({ template_rule: "Template override", material_catalog: "Product catalog", supplier_conversion: "Supplier conversion" }[s] || "—");
const n2 = (v) => Number(v || 0).toFixed(2);

// Roof takeoff for ONE estimate: plain path by default, every existing control under Advanced.
export default function RoofTakeoffPanel({ est, canCalculate, locked, dirty, onApplied }) {
  const [revisions, setRevisions] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [usedTemplate, setUsedTemplate] = useState(null);
  const [status, setStatus] = useState(null);
  const [defaultWaste, setDefaultWaste] = useState(null);
  const [measurementId, setMeasurementId] = useState("");
  const [measurement, setMeasurement] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const [templateRevisionId, setTemplateRevisionId] = useState("");
  const [estimateWaste, setEstimateWaste] = useState("");
  const [dripOverride, setDripOverride] = useState("");
  const [structureWaste, setStructureWaste] = useState({});
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [adv, setAdv] = useState(false);

  const loadAll = useCallback(async () => {
    const params = est.lead_id ? { lead_id: est.lead_id } : est.property_id ? { property_id: est.property_id } : est.inspection_id ? { inspection_id: est.inspection_id } : null;
    const [revs, tpl, st, ts] = await Promise.all([
      params ? api.get("/measurements", { params }).then((r) => r.data).catch(() => []) : Promise.resolve([]),
      api.get("/takeoff/templates", { params: { active: true } }).then((r) => r.data).catch(() => []),
      api.get(`/takeoff/estimates/${est.id}/status`).then((r) => r.data).catch(() => null),
      api.get("/takeoff/settings").then((r) => r.data).catch(() => null),
    ]);
    setRevisions(revs); setTemplates(tpl); setStatus(st); setDefaultWaste(ts?.default_waste_percent ?? null);
    const verified = revs.filter((r) => VERIFIED.includes(r.status)).sort((a, b) => b.revision_number - a.revision_number);
    const used = st?.has_takeoff && verified.find((r) => r.id === st.measurement_revision_id);
    setMeasurementId((used || verified[0])?.id || "");
    const latestIds = tpl.map((t) => t.latest_revision?.id).filter(Boolean);
    if (st?.has_takeoff && st.template_revision_id) {
      setTemplateRevisionId(st.template_revision_id);
      if (!latestIds.includes(st.template_revision_id)) {
        api.get(`/takeoff/templates/revisions/${st.template_revision_id}`).then((r) => setUsedTemplate(r.data)).catch(() => {});
      }
    } else if (latestIds.length === 1) setTemplateRevisionId(latestIds[0]);
  }, [est.id, est.lead_id, est.property_id, est.inspection_id]);
  useEffect(() => { loadAll(); }, [loadAll]);

  useEffect(() => {
    setMeasurement(null); setWarnings([]); setStructureWaste({}); setPreview(null);
    if (!measurementId) return;
    Promise.all([api.get(`/measurements/${measurementId}`), api.get(`/takeoff/measurements/${measurementId}/warnings`)])
      .then(([m, w]) => { setMeasurement(m.data); setWarnings(w.data.warnings || []); })
      .catch((e) => toast.error(apiError(e)));
  }, [measurementId]);

  const verified = useMemo(() => revisions.filter((r) => VERIFIED.includes(r.status)).sort((a, b) => b.revision_number - a.revision_number), [revisions]);
  const chosen = verified.find((r) => r.id === measurementId);
  const newestVerified = verified[0];
  const pending = revisions.some((r) => !VERIFIED.includes(r.status) && r.revision_number > (newestVerified?.revision_number || 0));
  const templateOptions = useMemo(() => {
    const opts = templates.map((t) => t.latest_revision).filter(Boolean).map((r) => ({ id: r.id, label: r.template_name, version: r.revision_number }));
    if (usedTemplate && !opts.find((o) => o.id === usedTemplate.id)) opts.push({ id: usedTemplate.id, label: `${usedTemplate.template_name} (version used last time)`, version: usedTemplate.revision_number });
    return opts;
  }, [templates, usedTemplate]);
  const newerVerified = status?.has_takeoff && newestVerified && newestVerified.revision_number > (status.measurement_revision_number || 0) ? newestVerified : null;

  const payload = (replace) => ({
    measurement_revision_id: measurementId, template_revision_id: templateRevisionId,
    estimate_waste_override: estimateWaste === "" ? null : Number(estimateWaste),
    drip_edge_override_lf: dripOverride === "" ? null : Number(dripOverride),
    structure_waste_overrides: Object.fromEntries(Object.entries(structureWaste).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)])),
    replace_modified_generated: replace,
  });
  const doPreview = async () => {
    setBusy(true);
    try { setPreview((await api.post(`/takeoff/estimates/${est.id}/preview`, payload(false))).data); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const doApply = async (replace) => {
    setBusy(true);
    try {
      const { data } = await api.post(`/takeoff/estimates/${est.id}/apply`, payload(replace));
      toast.success(`Estimate updated with ${data.created_line_ids.length} item(s) from the roof measurements`);
      setPreview(null); await loadAll(); onApplied();
    } catch (e) {
      if (e?.response?.status === 409 && e?.response?.data?.detail?.code === "TAKEOFF_GENERATED_LINES_MODIFIED") {
        setPreview((p) => ({ ...(p || {}), review_required: true, manually_modified_generated_lines: e.response.data.detail.lines || [] }));
        toast.warning("Some of these items were edited by hand. Review before replacing them.");
      } else toast.error(apiError(e));
    } finally { setBusy(false); }
  };

  const scopedSquares = Number(measurement?.totals?.takeoff_squares ?? measurement?.totals?.total_squares ?? 0);
  const measuredDrip = measurement?.summary?.drip_edge_lf;
  const calcDrip = Number(measurement?.totals?.takeoff_edge_totals?.eave_lf ?? measurement?.totals?.edge_totals?.eave_lf ?? 0) + Number(measurement?.totals?.takeoff_edge_totals?.rake_lf ?? measurement?.totals?.edge_totals?.rake_lf ?? 0);
  const wasteChanged = preview?.waste_change && (Math.abs(Number(preview.waste_change.percent_delta || 0)) > 0.0001 || Math.abs(Number(preview.waste_change.extra_squares_delta || 0)) > 0.0001);

  return (
    <section className="rounded-md border border-border bg-white" data-testid="estimate-takeoff-workspace">
      <div className="flex items-center gap-2 border-b border-border px-5 py-3">
        <Ruler className="h-4 w-4 text-orange-600" /><h2 className="text-sm font-semibold text-slate-900">1. Roof measurements</h2>
      </div>
      <div className="space-y-4 p-5">
        {!chosen ? (
          <div className="text-sm text-slate-600" data-testid="takeoff-no-measurement">
            {pending ? "Roof measurements are waiting for office verification." : "No verified roof measurements yet."}{" "}
            {est.lead_id && <Link to={`/leads/${est.lead_id}`} className="font-medium text-orange-700 hover:underline" data-testid="takeoff-go-measure">Measure the roof on the lead</Link>}
            <span className="block text-xs text-slate-400">You can still add items by hand below.</span>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm" data-testid="takeoff-measurement-summary">
            <span className="font-medium text-slate-900">Using the roof measured {shortDate(chosen.verified_at || chosen.created_at)}</span>
            <span className="text-slate-600">{n2(chosen.total_squares)} squares{measurement && scopedSquares !== Number(chosen.total_squares) ? ` · ${n2(scopedSquares)} in this job` : ""}</span>
            {chosen.id === newestVerified?.id ? <Badge variant="secondary" className="bg-green-50 text-green-700">Latest</Badge> : <Badge variant="secondary" className="bg-amber-50 text-amber-700">Older measurements</Badge>}
            {pending && <span className="text-xs text-amber-700" data-testid="takeoff-pending-note">Newer measurements are waiting for office verification.</span>}
            {status?.has_takeoff && chosen.id === status.measurement_revision_id && <span className="text-xs text-slate-500" data-testid="takeoff-applied-note">Materials on this estimate already come from these measurements.</span>}
          </div>
        )}

        {(status?.measurements_changed || newerVerified) && (
          <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900" data-testid="measurements-changed-warning">
            <div className="flex items-center gap-2 font-medium"><AlertTriangle className="h-4 w-4" /> The roof was re-measured after this estimate was calculated.</div>
            {newerVerified
              ? (measurementId === newerVerified.id
                ? <div className="mt-1" data-testid="takeoff-using-new">Now using the new measurements. Calculate materials, then update the estimate.</div>
                : <div className="mt-1">Nothing changes until you choose. <button type="button" className="font-semibold underline" onClick={() => setMeasurementId(newerVerified.id)} data-testid="takeoff-use-latest">Use the new measurements</button>, then calculate and update.</div>)
              : <div className="mt-1">The new measurements are waiting for office verification. This estimate keeps the previous ones.</div>}
          </div>
        )}

        {!!warnings.length && <div className="space-y-1.5">{warnings.map((w) => <div key={w.code} className="rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900"><AlertTriangle className="mr-1 inline h-4 w-4" /> {w.message}</div>)}</div>}

        {chosen && !canCalculate && (locked
          ? <p className="text-sm text-slate-500" data-testid="takeoff-locked">This estimate is locked because its proposal was accepted.</p>
          : <p className="text-sm text-slate-500" data-testid="takeoff-office-only">The office turns the roof measurements into estimate materials.</p>)}

        {chosen && canCalculate && (
          <>
            <div className="flex flex-wrap items-end gap-3">
              <div className="w-64"><Label className="text-xs">Roof system</Label>
                <Select value={templateRevisionId} onValueChange={(v) => { setTemplateRevisionId(v); setPreview(null); }}>
                  <SelectTrigger data-testid="takeoff-template-select"><SelectValue placeholder={templateOptions.length ? "Choose roof system" : "No roof systems set up"} /></SelectTrigger>
                  <SelectContent>{templateOptions.map((o) => <SelectItem key={o.id} value={o.id}>{o.label}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="w-36"><Label className="text-xs">Waste %</Label>
                <Input type="number" placeholder={defaultWaste != null ? `Default` : ""} value={estimateWaste} onChange={(e) => setEstimateWaste(e.target.value)} data-testid="takeoff-waste" />
              </div>
              <Button variant="outline" onClick={doPreview} disabled={busy || dirty || !templateRevisionId} data-testid="takeoff-preview-button"><Calculator className="h-4 w-4" /> Calculate materials</Button>
              {dirty && <span className="text-xs text-amber-600" data-testid="takeoff-save-first">Save your changes first.</span>}
              {!templateOptions.length && <Link to="/estimating/takeoff" className="text-xs font-medium text-orange-700 hover:underline" data-testid="takeoff-setup-link">Set up a roof system</Link>}
            </div>

            {preview && (
              <div className="rounded-md border border-border bg-slate-50 p-3" data-testid="takeoff-preview">
                <div className="mb-2 text-sm text-slate-600">Includes {n2(preview.effective_roof_waste_percent)}% waste. Nothing changes on the estimate until you add it.</div>
                {wasteChanged && <div className="mb-3 rounded border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900" data-testid="takeoff-waste-change"><AlertTriangle className="mr-1 inline h-4 w-4" />{Math.abs(Number(preview.waste_change.percent_delta || 0)) > 0.0001
                  ? <>Waste changed from <b>{n2(preview.waste_change.previous_percent)}%</b> to <b>{n2(preview.waste_change.current_percent)}%</b> </>
                  : <>Same {n2(preview.waste_change.current_percent)}% waste on a changed roof area </>}({Number(preview.waste_change.extra_squares_delta) >= 0 ? "+" : ""}{n2(preview.waste_change.extra_squares_delta)} squares of waste material).</div>}
                {preview.review_required && <div className="mb-3 rounded border border-red-200 bg-red-50 p-2 text-sm text-red-800" data-testid="takeoff-review-required"><AlertTriangle className="mr-1 inline h-4 w-4" /> Some items from the last calculation were edited by hand. Updating replaces them with the new quantities.</div>}
                <Table data-testid="takeoff-preview-table">
                  <TableHeader><TableRow><TableHead>Item</TableHead><TableHead className="text-right">Quantity</TableHead><TableHead className="text-right">Order</TableHead></TableRow></TableHeader>
                  <TableBody>{preview.lines.map((l, i) => (
                    <TableRow key={`${l.description}-${i}`}><TableCell>{l.description}</TableCell><TableCell className="text-right tabular-nums">{n2(l.quantity)} {l.unit}</TableCell><TableCell className="text-right tabular-nums">{l.order_quantity != null ? `${Number(l.order_quantity).toFixed(0)} ${l.purchase_unit || "pkg"}` : "—"}</TableCell></TableRow>
                  ))}</TableBody>
                </Table>
                <div className="mt-3 flex justify-end">
                  {preview.review_required
                    ? <Button variant="destructive" onClick={() => doApply(true)} disabled={busy} data-testid="takeoff-replace-apply">Replace edited items &amp; update estimate</Button>
                    : <Button onClick={() => doApply(false)} disabled={busy} data-testid="takeoff-apply"><CheckCircle2 className="h-4 w-4" /> {status?.has_takeoff ? "Update estimate" : "Add to estimate"}</Button>}
                </div>
              </div>
            )}

            <Collapsible open={adv} onOpenChange={setAdv} data-testid="takeoff-advanced">
              <CollapsibleTrigger className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-slate-800" data-testid="takeoff-advanced-toggle">
                <ChevronDown className={`h-3.5 w-3.5 transition-transform ${adv ? "rotate-180" : ""}`} /> Advanced takeoff options
              </CollapsibleTrigger>
              <CollapsibleContent className="mt-3 space-y-4 rounded-md border border-dashed border-border p-4">
                <div className="grid gap-3 lg:grid-cols-3">
                  <div><Label className="text-xs">Measurement version</Label>
                    <Select value={measurementId} onValueChange={setMeasurementId}><SelectTrigger data-testid="takeoff-measurement-select"><SelectValue /></SelectTrigger>
                      <SelectContent>{verified.map((r) => <SelectItem key={r.id} value={r.id}>Revision {r.revision_number} · {r.status} · {n2(r.total_squares)} SQ</SelectItem>)}</SelectContent></Select>
                  </div>
                  <div><Label className="text-xs">Template version</Label>
                    <Select value={templateRevisionId} onValueChange={(v) => { setTemplateRevisionId(v); setPreview(null); }}><SelectTrigger data-testid="takeoff-template-version-select"><SelectValue placeholder="Select template" /></SelectTrigger>
                      <SelectContent>{templateOptions.map((o) => <SelectItem key={o.id} value={o.id}>{o.label} · v{o.version}</SelectItem>)}</SelectContent></Select>
                  </div>
                  <div><Label className="text-xs">Drip edge override LF</Label>
                    <Input type="number" placeholder={measuredDrip != null ? `${measuredDrip} measured` : `${calcDrip} eave+rake`} value={dripOverride} onChange={(e) => setDripOverride(e.target.value)} data-testid="takeoff-drip-override" />
                  </div>
                </div>
                {defaultWaste != null && <div className="text-xs text-slate-500">Blank waste uses the roof system's waste, then the company default ({defaultWaste}%).</div>}
                {!!measurement?.totals?.area_by_structure?.length && (
                  <div><div className="mb-1 text-xs font-semibold uppercase text-slate-400">Per-structure waste override</div>
                    <div className="flex flex-wrap gap-3">{measurement.totals.area_by_structure.filter((r) => r.structure_id && r.included_in_scope !== false).map((r) => (
                      <div key={r.structure_id}><Label className="text-xs">{r.name} ({n2(r.squares)} SQ)</Label><Input className="w-32" type="number" placeholder="Default" value={structureWaste[r.structure_id] ?? ""} onChange={(e) => setStructureWaste({ ...structureWaste, [r.structure_id]: e.target.value })} data-testid={`takeoff-structure-waste-${r.structure_id}`} /></div>
                    ))}</div>
                  </div>
                )}
                {status?.has_takeoff && <div className="text-xs text-slate-500" data-testid="takeoff-used-versions">Last calculated with measurement revision {status.measurement_revision_number} and template v{status.template_revision_number}.</div>}
                {!!status?.changed_metrics?.length && <div className="max-h-36 overflow-auto rounded bg-slate-50 p-2 text-xs" data-testid="takeoff-changed-metrics">{status.changed_metrics.map((c) => <div key={c.metric}><b>{c.metric.replace(/_/g, " ")}</b>: {(c.from && typeof c.from === "object") || (c.to && typeof c.to === "object") ? "changed" : `${c.from ?? "—"} → ${c.to ?? "—"}`}</div>)}</div>}
                {preview && (
                  <Table data-testid="takeoff-preview-details">
                    <TableHeader><TableRow><TableHead>Description</TableHead><TableHead>Assembly</TableHead><TableHead>Measured</TableHead><TableHead>Waste</TableHead><TableHead>Calculated Qty</TableHead><TableHead>Packaging source</TableHead></TableRow></TableHeader>
                    <TableBody>{preview.lines.map((l, i) => (
                      <TableRow key={`d-${i}`}><TableCell>{l.description}</TableCell><TableCell>{l.assembly_name || "—"} v{l.assembly_version || "—"}</TableCell><TableCell>{n2(l.measured_quantity)} {l.unit}</TableCell><TableCell>{n2(l.waste_percent)}%</TableCell><TableCell>{n2(l.quantity)} {l.unit}</TableCell>
                        <TableCell><div>{coverageLabel(l.coverage_source)}</div>{l.coverage_per_package != null && <div className="text-xs text-slate-400">{Number(l.coverage_per_package).toFixed(4)} {l.unit}/pkg</div>}</TableCell></TableRow>
                    ))}</TableBody>
                  </Table>
                )}
                <Link to="/estimating/takeoff" className="inline-block text-xs font-medium text-orange-700 hover:underline" data-testid="takeoff-setup-advanced-link">Manage roof systems &amp; waste defaults in Estimating Setup</Link>
              </CollapsibleContent>
            </Collapsible>
          </>
        )}
      </div>
    </section>
  );
}

import { useEffect, useState, useCallback } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { money, shortDate } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StageBar, STAGE_LABELS } from "@/components/lead/StageBar";
import { nextAction, NextActionBanner } from "@/components/lead/NextAction";
import PhotoGallery from "@/components/PhotoGallery";
import MeasurementWorksheet from "@/components/MeasurementWorksheet";
import { Home, User, ClipboardCheck, FileText, FileCheck2, Receipt, Hammer, Plus, Check, Send, Ban, Loader2, MapPin, UserCheck, Camera, Download, Trash2 } from "lucide-react";

const MANAGE = ["owner", "administrator", "office"];
const UNASSIGNED = "__unassigned__";

function Section({ icon: Icon, title, action, children, testid }) {
  return (
    <div className="rounded-md border border-border bg-white" data-testid={testid}>
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2"><Icon className="h-4 w-4 text-orange-600" /><h3 className="font-heading font-semibold text-slate-900">{title}</h3></div>
        {action}
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

const statusColor = { new: "bg-blue-50 text-blue-700", working: "bg-amber-50 text-amber-700", converted: "bg-orange-50 text-orange-700", draft: "bg-slate-100 text-slate-600", sent: "bg-blue-50 text-blue-700", accepted: "bg-green-50 text-green-700", declined: "bg-red-50 text-red-700", paid: "bg-green-50 text-green-700", issued: "bg-blue-50 text-blue-700", void: "bg-slate-100 text-slate-500" };

export default function LeadDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const isManage = MANAGE.includes(user?.role);

  const [lead, setLead] = useState(null);
  const [inspections, setInspections] = useState([]);
  const [estimates, setEstimates] = useState([]);
  const [quotes, setQuotes] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [jobs, setJobs] = useState([]);

  const [inspOpen, setInspOpen] = useState(false);
  const [insp, setInsp] = useState({ inspector: "", roof_condition: "", findings: "", recommended_work: "", measurements: "", notes: "" });
  const [wf, setWf] = useState(null);
  const [view, setView] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [acceptOpen, setAcceptOpen] = useState(false);
  const [acceptTarget, setAcceptTarget] = useState(null);
  const [acceptName, setAcceptName] = useState("");
  const [acceptPackage, setAcceptPackage] = useState("");
  const [assignable, setAssignable] = useState([]);
  const [assigning, setAssigning] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const l = (await api.get(`/leads/${id}`)).data;
      setLead(l);
      const [insR, estR, quoR, jobR] = await Promise.all([
        api.get(`/inspections?lead_id=${id}`),
        api.get(`/estimates?lead_id=${id}`),
        api.get(`/quotes?lead_id=${id}`),
        l.customer_id ? api.get(`/jobs?customer_id=${l.customer_id}`) : Promise.resolve({ data: [] }),
      ]);
      setInspections(insR.data); setEstimates(estR.data); setQuotes(quoR.data); setJobs(jobR.data);
      api.get(`/leads/${id}/workflow`).then((r) => setWf(r.data)).catch((e) => setLoadError(apiError(e)));
      if (isManage && l.customer_id) {
        try { setInvoices((await api.get(`/invoices?customer_id=${l.customer_id}`)).data); } catch (e) { /* noop */ }
      }
    } catch (e) {
      setLoadError(apiError(e));
    }
  }, [id, isManage]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (isManage) api.get("/users/assignable").then((r) => setAssignable(r.data)).catch(() => {});
  }, [isManage]);

  const assignLead = async (value) => {
    setAssigning(true);
    try {
      const user_id = value === UNASSIGNED ? null : value;
      const { data } = await api.put(`/leads/${id}/assign`, { user_id });
      setLead(data);
      toast.success(user_id ? `Assigned to ${data.assigned_user_name}` : "Assignment cleared");
    } catch (e) { toast.error(apiError(e)); } finally { setAssigning(false); }
  };

  const createCustomer = async () => {
    setBusy(true);
    try { await api.post(`/customers/from-lead/${id}`); toast.success("Customer created & linked"); await load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const addInspection = async () => {
    setBusy(true);
    try {
      await api.post("/inspections", { lead_id: id, customer_id: lead.customer_id, property_id: lead.property_id, inspection_date: new Date().toISOString(), ...insp });
      toast.success("Inspection recorded"); setInspOpen(false); setInsp({ inspector: "", roof_condition: "", findings: "", recommended_work: "", measurements: "", notes: "" }); load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const createDraftEstimate = async () => {
    try {
      const { data } = await api.post("/estimates", { lead_id: id, customer_id: lead.customer_id, property_id: lead.property_id, inspection_id: inspections[0]?.id, tax_rate: 0, items: [] });
      navigate(`/estimates/${data.id}`);
    } catch (e) { toast.error(apiError(e)); }
  };

  const generateQuote = async (estId) => {
    try { await api.post("/quotes", { estimate_id: estId }); toast.success("Quote generated"); load(); }
    catch (e) { toast.error(apiError(e)); }
  };
  const sendQuote = async (q) => { try { await api.put(`/quotes/${q.id}`, { status: "sent" }); toast.success("Quote marked sent"); load(); } catch (e) { toast.error(apiError(e)); } };
  const declineQuote = async (q) => { try { await api.post(`/quotes/${q.id}/decline`); toast.success("Quote declined"); load(); } catch (e) { toast.error(apiError(e)); } };
  const duplicateEstimate = async (e) => {
    try { const { data } = await api.post(`/estimates/${e.id}/duplicate`); toast.success(`Duplicated as ${data.number}`); load(); }
    catch (err) { toast.error(apiError(err)); }
  };
  const deleteEstimate = (e) => {
    setEstimates((prev) => prev.filter((x) => x.id !== e.id));
    const t = setTimeout(async () => {
      try { await api.delete(`/estimates/${e.id}`); load(); } catch (err) { toast.error(apiError(err)); load(); }
    }, 5000);
    toast(`Estimate ${e.number} deleted`, { duration: 5000, action: { label: "Undo", onClick: () => { clearTimeout(t); toast.success("Restored"); load(); } } });
  };
  const deleteQuote = (q) => {
    setQuotes((prev) => prev.filter((x) => x.id !== q.id));
    const t = setTimeout(async () => {
      try { await api.delete(`/quotes/${q.id}`); load(); } catch (err) { toast.error(apiError(err)); load(); }
    }, 5000);
    toast(`Quote ${q.number} deleted`, { duration: 5000, action: { label: "Undo", onClick: () => { clearTimeout(t); toast.success("Restored"); load(); } } });
  };
  const downloadProposal = async (q) => {
    try {
      const res = await api.get(`/quotes/${q.id}/proposal.pdf`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (e) { toast.error(apiError(e)); }
  };
  const openAccept = (q) => { setAcceptTarget(q); setAcceptName(lead?.name || ""); setAcceptPackage(q.multi_package && q.packages?.length ? q.packages[q.packages.length - 1].id : ""); setAcceptOpen(true); };
  const confirmAccept = async () => {
    setBusy(true);
    try { await api.post(`/quotes/${acceptTarget.id}/accept`, { acceptance_name: acceptName, package_id: acceptPackage || null }); toast.success(`Quote accepted — Job created`); setAcceptOpen(false); load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const createInvoice = async (q) => {
    try { await api.post("/invoices", { quote_id: q.id }); toast.success("Invoice created"); load(); }
    catch (e) { toast.error(apiError(e)); }
  };

  if (loadError && (!lead || !wf)) return (
    <div className="p-8" data-testid="lead-load-error">
      <div className="max-w-md rounded-md border border-border bg-white p-6">
        <h3 className="font-heading text-lg font-semibold text-slate-900">Can't open this lead</h3>
        <p className="mt-1 text-sm text-slate-500">{loadError}</p>
        <Link to="/leads" className="mt-3 inline-block text-sm font-medium text-orange-700 hover:underline" data-testid="lead-load-error-back">Back to leads</Link>
      </div>
    </div>
  );
  if (!lead || !wf) return <div className="flex h-64 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>;

  const viewing = view || wf.stage;
  const quoteIds = quotes.map((q) => q.id);
  const leadJobs = jobs.filter((j) => quoteIds.includes(j.quote_id));
  const jobIds = leadJobs.map((j) => j.id);
  const leadInvoices = invoices.filter((i) => quoteIds.includes(i.quote_id) || jobIds.includes(i.job_id));
  const invoicedQuoteIds = leadInvoices.filter((i) => i.status !== "void").map((i) => i.quote_id);
  const action = nextAction(wf, isManage);
  const f = wf.facts;

  const assignment = (
    <Section icon={UserCheck} title="Assignment" testid="section-assignment">
      {isManage ? (
        <div className="space-y-1.5">
          <Label>Assigned to</Label>
          <Select value={lead.assigned_user_id || UNASSIGNED} onValueChange={assignLead} disabled={assigning}>
            <SelectTrigger data-testid="lead-assign-select"><SelectValue placeholder="Unassigned" /></SelectTrigger>
            <SelectContent>
              <SelectItem value={UNASSIGNED} data-testid="lead-assign-unassigned">Unassigned</SelectItem>
              {assignable.map((u) => (
                <SelectItem key={u.id} value={u.id} data-testid={`lead-assign-${u.id}`}>{u.full_name || u.email} · {u.role}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : (
        <p className="text-sm text-slate-600" data-testid="lead-assigned-readonly">{lead.assigned_user_name ? `Assigned to ${lead.assigned_user_name}` : "Unassigned"}</p>
      )}
    </Section>
  );

  const customer = (
    <Section icon={User} title="Customer" testid="section-customer"
      action={!lead.customer_id && <Button size="sm" onClick={createCustomer} disabled={busy} data-testid="create-customer-button"><Plus className="h-4 w-4" /> Create customer</Button>}>
      {lead.customer_id ? (
        <div className="text-sm">
          <Link to={`/customers`} className="font-medium text-slate-900 hover:underline" data-testid="linked-customer">{lead.customer_name}</Link>
          <div className="mt-1 text-slate-500">{lead.phone || "—"} · {lead.email || "—"}</div>
          {lead.owner_name && <div className="mt-1 text-slate-400">Property owner: {lead.owner_name}</div>}
        </div>
      ) : (
        <p className="text-sm text-slate-500">No customer yet. Create one from this lead to continue the sale.</p>
      )}
    </Section>
  );

  const progress = (
    <Section icon={ClipboardCheck} title="Progress so far" testid="section-progress">
      <ul className="space-y-1.5 text-sm">
        {[
          ["inspection", `${f.inspections} inspection${f.inspections === 1 ? "" : "s"} · ${f.has_measurements ? "roof measured" : "not measured yet"}`],
          ["estimate", `${f.estimates} estimate${f.estimates === 1 ? "" : "s"} · ${f.quotes} proposal${f.quotes === 1 ? "" : "s"}${f.quotes_accepted ? " · accepted" : f.quotes_sent ? " · waiting on customer" : ""}`],
          ["production", f.jobs ? `${f.jobs} job${f.jobs === 1 ? "" : "s"}${f.jobs_completed ? " · completed" : f.jobs_scheduled ? " · scheduled" : " · not scheduled"}` : "No job yet"],
          ["billing", f.invoices ? `${f.invoices_paid} of ${f.invoices} invoice${f.invoices === 1 ? "" : "s"} paid` : "Not invoiced"],
        ].map(([k, t]) => (
          <li key={k}><button type="button" onClick={() => setView(k)} className="flex w-full justify-between gap-3 rounded px-1 py-0.5 text-left hover:bg-slate-50" data-testid={`progress-${k}`}>
            <span className="text-slate-500">{STAGE_LABELS[k]}</span><span className="text-right text-slate-800">{t}</span>
          </button></li>
        ))}
      </ul>
    </Section>
  );

  const inspectionsSection = (
    <Section icon={ClipboardCheck} title="Inspections" testid="section-inspections"
      action={<Button size="sm" variant="outline" onClick={() => setInspOpen(true)} data-testid="add-inspection-button"><Plus className="h-4 w-4" /> Add</Button>}>
      {inspections.length === 0 ? <p className="text-sm text-slate-500">No inspections yet.</p> : (
        <div className="space-y-2">
          {inspections.map((i) => (
            <div key={i.id} className="rounded border border-border p-2 text-sm" data-testid={`inspection-${i.id}`}>
              <div className="flex justify-between"><span className="font-medium text-slate-800">{i.roof_condition || "Inspection"}</span><span className="text-xs text-slate-400">{shortDate(i.inspection_date)}</span></div>
              {i.findings && <div className="mt-1 text-slate-600 whitespace-pre-wrap" data-testid={`inspection-findings-${i.id}`}>Findings: {i.findings}</div>}
              {i.recommended_work && <div className="text-slate-500 whitespace-pre-wrap" data-testid={`inspection-recommended-${i.id}`}>Recommended: {i.recommended_work}</div>}
              {i.measurements && <div className="text-slate-500 whitespace-pre-wrap" data-testid={`inspection-measurements-${i.id}`}>Measurements: {i.measurements}</div>}
              {i.notes && <div className="text-slate-500 whitespace-pre-wrap" data-testid={`inspection-notes-${i.id}`}>Notes: {i.notes}</div>}
              {(i.inspector || i.created_by) && <div className="mt-1 text-xs text-slate-400" data-testid={`inspection-inspector-${i.id}`}>by {i.inspector || i.created_by}</div>}
            </div>
          ))}
        </div>
      )}
    </Section>
  );

  const estimatesSection = (
    <Section icon={FileText} title="Estimates" testid="section-estimates"
      action={<Button size="sm" variant="outline" disabled={!lead.customer_id} onClick={createDraftEstimate} data-testid="new-estimate-button"><Plus className="h-4 w-4" /> New</Button>}>
      {!lead.customer_id && <p className="mb-2 text-xs text-amber-600">Create a customer first (Overview).</p>}
      {estimates.length === 0 ? <p className="text-sm text-slate-500">No estimates yet.</p> : (
        <div className="space-y-2">
          {estimates.map((e) => (
            <div key={e.id} className="flex items-center justify-between rounded border border-border p-2 text-sm" data-testid={`estimate-${e.id}`}>
              <div><span className="font-medium text-slate-900">{e.number}</span> · <span className="tabular-nums">{money(e.total)}</span> <Badge className={statusColor[e.status] || ""} variant="secondary">{e.status}</Badge></div>
              <div className="flex items-center gap-1">
                <Button size="sm" variant="ghost" onClick={() => navigate(`/estimates/${e.id}`)} data-testid={`edit-estimate-${e.id}`}>Edit</Button>
                <Button size="sm" variant="ghost" onClick={() => duplicateEstimate(e)} data-testid={`duplicate-estimate-${e.id}`}><FileText className="h-4 w-4" /> Duplicate</Button>
                <Button size="sm" variant="ghost" onClick={() => generateQuote(e.id)} data-testid={`generate-quote-${e.id}`}><FileCheck2 className="h-4 w-4" /> Proposal</Button>
                {isManage && <Button size="sm" variant="ghost" className="text-red-600 hover:text-red-700" onClick={() => deleteEstimate(e)} data-testid={`delete-estimate-${e.id}`}><Trash2 className="h-4 w-4" /></Button>}
              </div>
            </div>
          ))}
        </div>
      )}
    </Section>
  );

  const quotesSection = (
    <Section icon={FileCheck2} title="Proposals" testid="section-quotes">
      {quotes.length === 0 ? <p className="text-sm text-slate-500">No proposals yet. Use “Proposal” on an estimate.</p> : (
        <div className="space-y-2">
          {quotes.map((q) => (
            <div key={q.id} className="rounded border border-border p-3 text-sm" data-testid={`quote-${q.id}`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2"><span className="font-medium text-slate-900">{q.number}</span><Badge className={statusColor[q.status] || ""} variant="secondary">{q.status}</Badge></div>
                <span className="tabular-nums font-semibold">{money(q.total)}</span>
              </div>
              {q.accepted_by && <div className="mt-1 text-xs text-green-600">Accepted by {q.acceptance_name || "customer"} · {shortDate(q.accepted_at)}</div>}
              {q.multi_package && q.packages?.length > 0 && (
                <div className="mt-2 grid gap-1.5" data-testid={`quote-packages-${q.id}`}>
                  {q.packages.map((p) => (
                    <div key={p.id} className={`flex items-center justify-between rounded border px-2 py-1 text-xs ${q.accepted_package_id === p.id ? "border-green-300 bg-green-50" : "border-border"}`} data-testid={`quote-package-${p.id}`}>
                      <span className="font-medium text-slate-700">{p.name}{q.accepted_package_id === p.id ? " · accepted" : ""}</span>
                      <span className="tabular-nums">{money(p.total)}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-2 flex flex-wrap gap-2">
                {q.status === "draft" && <Button size="sm" variant="outline" onClick={() => sendQuote(q)} data-testid={`send-quote-${q.id}`}><Send className="h-3.5 w-3.5" /> Mark sent</Button>}
                <Button size="sm" variant="ghost" onClick={() => navigate(`/quotes/${q.id}/proposal`)} data-testid={`preview-proposal-${q.id}`}><FileText className="h-3.5 w-3.5" /> Preview & share</Button>
                <Button size="sm" variant="ghost" onClick={() => downloadProposal(q)} data-testid={`download-proposal-${q.id}`}><Download className="h-3.5 w-3.5" /> PDF</Button>
                {isManage && q.status !== "accepted" && q.status !== "declined" && <Button size="sm" onClick={() => openAccept(q)} data-testid={`accept-quote-${q.id}`}><Check className="h-3.5 w-3.5" /> Accept</Button>}
                {isManage && q.status !== "accepted" && q.status !== "declined" && <Button size="sm" variant="ghost" onClick={() => declineQuote(q)} data-testid={`decline-quote-${q.id}`}><Ban className="h-3.5 w-3.5" /> Decline</Button>}
                {isManage && q.status !== "accepted" && <Button size="sm" variant="ghost" className="text-red-600 hover:text-red-700" onClick={() => deleteQuote(q)} data-testid={`delete-quote-${q.id}`}><Trash2 className="h-3.5 w-3.5" /> Delete</Button>}
              </div>
            </div>
          ))}
        </div>
      )}
    </Section>
  );

  const jobsSection = (
    <Section icon={Hammer} title="Jobs" testid="section-jobs">
      {leadJobs.length === 0 ? <p className="text-sm text-slate-500">No job yet. Accepting a proposal creates the job.</p> : (
        <div className="space-y-2">
          {leadJobs.map((j) => (
            <Link key={j.id} to={`/jobs/${j.id}`} className="flex items-center justify-between rounded border border-border p-3 text-sm hover:border-slate-300 hover:bg-slate-50" data-testid={`job-${j.id}`}>
              <div>
                <div><span className="font-medium text-slate-900">{j.number}</span> <Badge variant="secondary" className="ml-1">{j.status.replace("_", " ")}</Badge></div>
                <div className="mt-1 text-xs text-slate-500">{j.scheduled_start ? `Install ${shortDate(j.scheduled_start)}` : "Not scheduled"} · {j.assigned_user_name || j.assigned_to || "Unassigned"} · Materials: {{ ready: "ready", short: "short", none: "not planned" }[j.material_status] || "—"}</div>
              </div>
              <span className="tabular-nums">{money(j.total)}</span>
            </Link>
          ))}
        </div>
      )}
    </Section>
  );

  const billingSection = isManage ? (
    <Section icon={Receipt} title="Invoices" testid="section-invoices">
      {quotes.filter((q) => q.status === "accepted" && !invoicedQuoteIds.includes(q.id)).map((q) => (
        <div key={q.id} className="mb-3 flex items-center justify-between rounded border border-dashed border-border p-2 text-sm">
          <span className="text-slate-600">{q.number} accepted · {money(q.total)} not invoiced yet</span>
          <Button size="sm" variant="outline" onClick={() => createInvoice(q)} data-testid={`create-invoice-${q.id}`}><Receipt className="h-3.5 w-3.5" /> Create invoice</Button>
        </div>
      ))}
      {leadInvoices.length === 0 ? <p className="text-sm text-slate-500">No invoices yet.</p> : (
        <div className="space-y-2">
          {leadInvoices.map((inv) => (
            <div key={inv.id} className="flex items-center justify-between rounded border border-border p-2 text-sm" data-testid={`invoice-${inv.id}`}>
              <div className="flex items-center gap-2"><span className="font-medium text-slate-900">{inv.number}</span><Badge className={statusColor[inv.status] || ""} variant="secondary">{inv.status}</Badge>{inv.due_date && <span className="text-xs text-slate-400">due {shortDate(inv.due_date)}</span>}</div>
              <span className="tabular-nums font-semibold">{money(inv.total)}</span>
            </div>
          ))}
          <Link to="/billing" className="inline-block text-xs font-medium text-orange-700 hover:underline" data-testid="lead-open-billing">Manage payments in Billing</Link>
        </div>
      )}
    </Section>
  ) : (
    <Section icon={Receipt} title="Billing" testid="section-invoices-readonly"><p className="text-sm text-slate-500">Invoicing and payments are handled by the office.</p></Section>
  );

  const PANELS = {
    overview: <>{customer}{assignment}{progress}</>,
    inspection: <>{inspectionsSection}<Section icon={Camera} title="Field photos" testid="section-lead-photos"><PhotoGallery recordType="lead" recordId={id} testid="lead-photos" /></Section>
      <div className="lg:col-span-2"><Section icon={ClipboardCheck} title="Roof measurements" testid="section-measurements">
        <MeasurementWorksheet leadId={id} propertyId={lead.property_id || null} inspectionId={inspections[0]?.id || null} propertyAddress={lead.property_address || lead.address || ""} customerName={lead.customer_name || lead.name || ""} />
      </Section></div></>,
    estimate: <>{estimatesSection}{quotesSection}</>,
    production: <div className="lg:col-span-2">{jobsSection}</div>,
    billing: <div className="lg:col-span-2">{billingSection}</div>,
  };

  return (
    <div>
      <PageHeader
        title={lead.name}
        description={<span className="flex items-center gap-1"><MapPin className="h-3.5 w-3.5" /> {lead.property_address || lead.address || "No property"}</span>}
        testid="page-lead-detail"
        actions={<><span className="hidden text-xs text-slate-500 sm:inline" data-testid="lead-current-stage">Stage: <span className="font-semibold text-slate-800">{STAGE_LABELS[wf.stage]}</span></span><Badge className={statusColor[lead.status] || ""} variant="secondary" data-testid="lead-status-badge">{lead.status}</Badge></>}
      />
      <div className="space-y-5 p-6 sm:p-8">
        <StageBar stages={wf.stages} current={wf.stage} viewing={viewing} onSelect={setView} />
        <NextActionBanner action={action} viewing={viewing} onGo={setView} navigateToJob={() => navigate(`/jobs/${action.jobId}`)} />
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2" data-testid={`stage-panel-${viewing}`}>
          {PANELS[viewing]}
        </div>
      </div>

      {/* Inspection dialog */}
      <Dialog open={inspOpen} onOpenChange={setInspOpen}>
        <DialogContent data-testid="inspection-dialog">
          <DialogHeader><DialogTitle>Record inspection</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5"><Label>Inspector</Label><Input value={insp.inspector} onChange={(e) => setInsp({ ...insp, inspector: e.target.value })} data-testid="insp-inspector" /></div>
            <div className="space-y-1.5"><Label>Roof condition</Label><Input value={insp.roof_condition} onChange={(e) => setInsp({ ...insp, roof_condition: e.target.value })} placeholder="Good / Fair / Poor" data-testid="insp-condition" /></div>
            <div className="space-y-1.5"><Label>Findings</Label><Textarea value={insp.findings} onChange={(e) => setInsp({ ...insp, findings: e.target.value })} data-testid="insp-findings" /></div>
            <div className="space-y-1.5"><Label>Recommended work</Label><Textarea value={insp.recommended_work} onChange={(e) => setInsp({ ...insp, recommended_work: e.target.value })} data-testid="insp-recommended" /></div>
            <div className="space-y-1.5"><Label>Measurement notes (optional)</Label><Textarea value={insp.measurements} onChange={(e) => setInsp({ ...insp, measurements: e.target.value })} placeholder="Quick note only. Use the Roof measurements worksheet for the real numbers." data-testid="insp-measurements" /></div>
            <div className="space-y-1.5"><Label>Notes</Label><Textarea value={insp.notes} onChange={(e) => setInsp({ ...insp, notes: e.target.value })} data-testid="insp-notes" /></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setInspOpen(false)}>Cancel</Button><Button onClick={addInspection} disabled={busy} data-testid="save-inspection">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Accept dialog */}
      <Dialog open={acceptOpen} onOpenChange={setAcceptOpen}>
        <DialogContent data-testid="accept-dialog">
          <DialogHeader><DialogTitle>Accept quote {acceptTarget?.number}</DialogTitle><DialogDescription>This records acceptance and creates a Job.</DialogDescription></DialogHeader>
          <div className="space-y-1.5"><Label>Customer acceptance name</Label><Input value={acceptName} onChange={(e) => setAcceptName(e.target.value)} data-testid="accept-name" /></div>
          {acceptTarget?.multi_package && acceptTarget?.packages?.length > 0 && (
            <div className="space-y-1.5" data-testid="accept-package-block">
              <Label>Package accepted</Label>
              <Select value={acceptPackage} onValueChange={setAcceptPackage}>
                <SelectTrigger data-testid="accept-package-select"><SelectValue placeholder="Choose package" /></SelectTrigger>
                <SelectContent>{acceptTarget.packages.map((p) => <SelectItem key={p.id} value={p.id}>{p.name} · {money(p.total)}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          )}
          <DialogFooter><Button variant="outline" onClick={() => setAcceptOpen(false)}>Cancel</Button><Button onClick={confirmAccept} disabled={busy || (acceptTarget?.multi_package && !acceptPackage)} data-testid="confirm-accept">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Accept & create job"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

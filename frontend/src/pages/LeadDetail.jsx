import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
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
import LineItemsEditor, { computeTotals } from "@/components/LineItemsEditor";
import PhotoGallery from "@/components/PhotoGallery";
import { Home, User, ClipboardCheck, FileText, FileCheck2, Receipt, Hammer, Plus, Check, Send, Ban, Loader2, MapPin, UserCheck, Camera } from "lucide-react";

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
  const { user } = useAuth();
  const isManage = MANAGE.includes(user?.role);

  const [lead, setLead] = useState(null);
  const [inspections, setInspections] = useState([]);
  const [estimates, setEstimates] = useState([]);
  const [quotes, setQuotes] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [jobs, setJobs] = useState([]);

  const [inspOpen, setInspOpen] = useState(false);
  const [insp, setInsp] = useState({ inspector: "", roof_condition: "", findings: "", recommended_work: "", notes: "" });
  const [estOpen, setEstOpen] = useState(false);
  const [items, setItems] = useState([{ description: "", quantity: 1, unit: "ea", unit_price: 0 }]);
  const [taxRate, setTaxRate] = useState(0);
  const [acceptOpen, setAcceptOpen] = useState(false);
  const [acceptTarget, setAcceptTarget] = useState(null);
  const [acceptName, setAcceptName] = useState("");
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
      if (isManage && l.customer_id) {
        try { setInvoices((await api.get(`/invoices?customer_id=${l.customer_id}`)).data); } catch (e) { /* noop */ }
      }
    } catch (e) {
      toast.error(apiError(e));
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
      toast.success("Inspection recorded"); setInspOpen(false); setInsp({ inspector: "", roof_condition: "", findings: "", recommended_work: "", notes: "" }); load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const createEstimate = async () => {
    setBusy(true);
    try {
      await api.post("/estimates", { lead_id: id, customer_id: lead.customer_id, property_id: lead.property_id, inspection_id: inspections[0]?.id, tax_rate: Number(taxRate) || 0, items: items.map((it) => ({ ...it, quantity: Number(it.quantity) || 0, unit_price: Number(it.unit_price) || 0 })) });
      toast.success("Estimate created"); setEstOpen(false); setItems([{ description: "", quantity: 1, unit: "ea", unit_price: 0 }]); setTaxRate(0); load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const generateQuote = async (estId) => {
    try { await api.post("/quotes", { estimate_id: estId }); toast.success("Quote generated"); load(); }
    catch (e) { toast.error(apiError(e)); }
  };
  const sendQuote = async (q) => { try { await api.put(`/quotes/${q.id}`, { status: "sent" }); toast.success("Quote marked sent"); load(); } catch (e) { toast.error(apiError(e)); } };
  const declineQuote = async (q) => { try { await api.post(`/quotes/${q.id}/decline`); toast.success("Quote declined"); load(); } catch (e) { toast.error(apiError(e)); } };
  const openAccept = (q) => { setAcceptTarget(q); setAcceptName(lead?.name || ""); setAcceptOpen(true); };
  const confirmAccept = async () => {
    setBusy(true);
    try { const { data } = await api.post(`/quotes/${acceptTarget.id}/accept`, { acceptance_name: acceptName }); toast.success(`Quote accepted — Job created`); setAcceptOpen(false); load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const createInvoice = async (q) => {
    try { await api.post("/invoices", { quote_id: q.id }); toast.success("Invoice created"); load(); }
    catch (e) { toast.error(apiError(e)); }
  };

  if (!lead) return <div className="flex h-64 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>;

  return (
    <div>
      <PageHeader
        title={lead.name}
        description={<span className="flex items-center gap-1"><MapPin className="h-3.5 w-3.5" /> {lead.property_address || lead.address || "No property"}</span>}
        testid="page-lead-detail"
        actions={<Badge className={statusColor[lead.status] || ""} variant="secondary" data-testid="lead-status-badge">{lead.status}</Badge>}
      />
      <div className="grid grid-cols-1 gap-5 p-6 sm:p-8 lg:grid-cols-2">
        {/* Assignment */}
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

        {/* Customer */}
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

        {/* Inspections */}
        <Section icon={ClipboardCheck} title="Inspections" testid="section-inspections"
          action={<Button size="sm" variant="outline" onClick={() => setInspOpen(true)} data-testid="add-inspection-button"><Plus className="h-4 w-4" /> Add</Button>}>
          {inspections.length === 0 ? <p className="text-sm text-slate-500">No inspections yet.</p> : (
            <div className="space-y-2">
              {inspections.map((i) => (
                <div key={i.id} className="rounded border border-border p-2 text-sm" data-testid={`inspection-${i.id}`}>
                  <div className="flex justify-between"><span className="font-medium text-slate-800">{i.roof_condition || "Inspection"}</span><span className="text-xs text-slate-400">{shortDate(i.inspection_date)}</span></div>
                  {i.recommended_work && <div className="text-slate-500">Recommended: {i.recommended_work}</div>}
                  {i.inspector && <div className="text-xs text-slate-400">by {i.inspector}</div>}
                  <div className="mt-2">
                    <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">Field photos</div>
                    <PhotoGallery recordType="inspection" recordId={i.id} compact testid={`insp-photos-${i.id}`} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </Section>

        {/* Field Photos (lead-level) */}
        <Section icon={Camera} title="Field photos" testid="section-lead-photos">
          <PhotoGallery recordType="lead" recordId={id} testid="lead-photos" />
        </Section>

        {/* Estimates */}
        <Section icon={FileText} title="Estimates" testid="section-estimates"
          action={<Button size="sm" variant="outline" disabled={!lead.customer_id} onClick={() => setEstOpen(true)} data-testid="new-estimate-button"><Plus className="h-4 w-4" /> New</Button>}>
          {!lead.customer_id && <p className="mb-2 text-xs text-amber-600">Create a customer first.</p>}
          {estimates.length === 0 ? <p className="text-sm text-slate-500">No estimates yet.</p> : (
            <div className="space-y-2">
              {estimates.map((e) => (
                <div key={e.id} className="flex items-center justify-between rounded border border-border p-2 text-sm" data-testid={`estimate-${e.id}`}>
                  <div><span className="font-medium text-slate-900">{e.number}</span> · <span className="tabular-nums">{money(e.total)}</span></div>
                  <Button size="sm" variant="ghost" onClick={() => generateQuote(e.id)} data-testid={`generate-quote-${e.id}`}><FileCheck2 className="h-4 w-4" /> Quote</Button>
                </div>
              ))}
            </div>
          )}
        </Section>

        {/* Quotes */}
        <Section icon={FileCheck2} title="Quotes" testid="section-quotes">
          {quotes.length === 0 ? <p className="text-sm text-slate-500">No quotes yet.</p> : (
            <div className="space-y-2">
              {quotes.map((q) => (
                <div key={q.id} className="rounded border border-border p-3 text-sm" data-testid={`quote-${q.id}`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2"><span className="font-medium text-slate-900">{q.number}</span><Badge className={statusColor[q.status] || ""} variant="secondary">{q.status}</Badge></div>
                    <span className="tabular-nums font-semibold">{money(q.total)}</span>
                  </div>
                  {q.accepted_by && <div className="mt-1 text-xs text-green-600">Accepted by {q.acceptance_name || "customer"} · {shortDate(q.accepted_at)}</div>}
                  <div className="mt-2 flex flex-wrap gap-2">
                    {q.status === "draft" && <Button size="sm" variant="outline" onClick={() => sendQuote(q)} data-testid={`send-quote-${q.id}`}><Send className="h-3.5 w-3.5" /> Send</Button>}
                    {isManage && q.status !== "accepted" && q.status !== "declined" && <Button size="sm" onClick={() => openAccept(q)} data-testid={`accept-quote-${q.id}`}><Check className="h-3.5 w-3.5" /> Accept</Button>}
                    {isManage && q.status !== "accepted" && q.status !== "declined" && <Button size="sm" variant="ghost" onClick={() => declineQuote(q)} data-testid={`decline-quote-${q.id}`}><Ban className="h-3.5 w-3.5" /> Decline</Button>}
                    {isManage && q.status === "accepted" && <Button size="sm" variant="outline" onClick={() => createInvoice(q)} data-testid={`create-invoice-${q.id}`}><Receipt className="h-3.5 w-3.5" /> Create invoice</Button>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Section>

        {/* Jobs */}
        <Section icon={Hammer} title="Jobs" testid="section-jobs">
          {jobs.length === 0 ? <p className="text-sm text-slate-500">No jobs yet. Accepting a quote creates a job.</p> : (
            <div className="space-y-2">
              {jobs.map((j) => (
                <div key={j.id} className="flex items-center justify-between rounded border border-border p-2 text-sm" data-testid={`job-${j.id}`}>
                  <div><span className="font-medium text-slate-900">{j.number}</span> <Badge variant="secondary" className="ml-1">{j.status}</Badge></div>
                  <span className="tabular-nums">{money(j.total)}</span>
                </div>
              ))}
            </div>
          )}
        </Section>

        {/* Invoices (manage only) */}
        {isManage && (
          <Section icon={Receipt} title="Invoices" testid="section-invoices">
            {invoices.length === 0 ? <p className="text-sm text-slate-500">No invoices yet.</p> : (
              <div className="space-y-2">
                {invoices.map((inv) => (
                  <div key={inv.id} className="flex items-center justify-between rounded border border-border p-2 text-sm" data-testid={`invoice-${inv.id}`}>
                    <div className="flex items-center gap-2"><span className="font-medium text-slate-900">{inv.number}</span><Badge className={statusColor[inv.status] || ""} variant="secondary">{inv.status}</Badge></div>
                    <span className="tabular-nums font-semibold">{money(inv.total)}</span>
                  </div>
                ))}
              </div>
            )}
          </Section>
        )}
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
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setInspOpen(false)}>Cancel</Button><Button onClick={addInspection} disabled={busy} data-testid="save-inspection">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Estimate dialog */}
      <Dialog open={estOpen} onOpenChange={setEstOpen}>
        <DialogContent className="max-w-2xl" data-testid="estimate-dialog">
          <DialogHeader><DialogTitle>New estimate</DialogTitle><DialogDescription>Totals are calculated and validated on the server.</DialogDescription></DialogHeader>
          <LineItemsEditor items={items} onChange={setItems} taxRate={taxRate} onTaxChange={setTaxRate} />
          <DialogFooter><Button variant="outline" onClick={() => setEstOpen(false)}>Cancel</Button><Button onClick={createEstimate} disabled={busy} data-testid="save-estimate">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create estimate"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Accept dialog */}
      <Dialog open={acceptOpen} onOpenChange={setAcceptOpen}>
        <DialogContent data-testid="accept-dialog">
          <DialogHeader><DialogTitle>Accept quote {acceptTarget?.number}</DialogTitle><DialogDescription>This records acceptance and creates a Job.</DialogDescription></DialogHeader>
          <div className="space-y-1.5"><Label>Customer acceptance name</Label><Input value={acceptName} onChange={(e) => setAcceptName(e.target.value)} data-testid="accept-name" /></div>
          <DialogFooter><Button variant="outline" onClick={() => setAcceptOpen(false)}>Cancel</Button><Button onClick={confirmAccept} disabled={busy} data-testid="confirm-accept">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Accept & create job"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

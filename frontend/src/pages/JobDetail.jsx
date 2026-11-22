import { useEffect, useState, useCallback } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { money, shortDay } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import PODialog from "@/components/PODialog";
import JobMaterialPlan from "@/components/JobMaterialPlan";
import JobCosting from "@/components/JobCosting";
import PhotoGallery from "@/components/PhotoGallery";
import { CalendarClock, Boxes, ShoppingCart, User, Home, Plus, Loader2, Users, Camera, DollarSign } from "lucide-react";
import { ReadyPanel } from "@/components/job/ReadyPanel";
import { JobPeople } from "@/components/job/JobPeople";
import { JobSchedule } from "@/components/job/JobSchedule";

const MANAGE = ["owner", "administrator", "office"];
const sc = { created: "bg-slate-100 text-slate-600", pending: "bg-slate-100 text-slate-600", scheduled: "bg-blue-50 text-blue-700", in_progress: "bg-amber-50 text-amber-700", completed: "bg-green-50 text-green-700", cancelled: "bg-red-50 text-red-500" };

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

export default function JobDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canManage = MANAGE.includes(user?.role);
  const [job, setJob] = useState(null);
  const [materials, setMaterials] = useState([]);
  const [addOpen, setAddOpen] = useState(false);
  const [pick, setPick] = useState({ material_id: "", planned_quantity: 1 });
  const [poOpen, setPoOpen] = useState(false);
  const [planKey, setPlanKey] = useState(0);

  const load = useCallback(async () => {
    try { setJob((await api.get(`/jobs/${id}`)).data); } catch (e) { toast.error(apiError(e)); }
  }, [id]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (canManage) api.get("/materials").then((r) => setMaterials(r.data)).catch(() => {}); }, [canManage]);

  const addMaterial = async () => {
    if (!pick.material_id) { toast.error("Select a material"); return; }
    try {
      await api.post(`/jobs/${id}/materials`, { material_id: pick.material_id, planned_quantity: Number(pick.planned_quantity) || 1 });
      toast.success("Material added to job"); setAddOpen(false); setPick({ material_id: "", planned_quantity: 1 }); setPlanKey((k) => k + 1); load();
    } catch (e) { toast.error(apiError(e)); }
  };

  if (!job) return <div className="flex h-64 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>;

  return (
    <div>
      <PageHeader title={`Job ${job.number}`}
        description={<span className="flex flex-wrap items-center gap-3"><span className="flex items-center gap-1"><User className="h-3.5 w-3.5" />{job.customer_name || "—"}</span><span className="flex items-center gap-1"><Home className="h-3.5 w-3.5" />{job.property_address || "—"}</span></span>}
        testid="page-job-detail"
        actions={<div className="flex items-center gap-2"><Badge className={sc[job.status] || ""} variant="secondary" data-testid="job-status-badge">{job.status.replace("_", " ")}</Badge><span className="font-heading font-bold text-slate-900">{money(job.total)}</span></div>} />
      <div className="space-y-5 p-6 sm:p-8">
        <ReadyPanel job={job} />
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <Section icon={Users} title="Who's on this job" testid="section-people">
            <JobPeople job={job} canManage={canManage} onChange={setJob} />
          </Section>
          <Section icon={CalendarClock} title="Schedule & status" testid="section-schedule">
            <JobSchedule job={job} canManage={canManage} onSaved={setJob} />
            {job.quote_id && <p className="mt-3 text-xs text-slate-400">From accepted quote · <Link to="/sales/quotes" className="hover:underline" data-testid="job-view-quote-link">view in Quotes</Link></p>}
          </Section>
        </div>

        <Section icon={Boxes} title="Job materials" testid="section-job-materials"
          action={canManage && <Button size="sm" variant="outline" onClick={() => setAddOpen(true)} data-testid="add-job-material"><Plus className="h-4 w-4" /> Add</Button>}>
          <JobMaterialPlan jobId={id} canManage={canManage} refreshKey={planKey} onChanged={load} />
        </Section>

        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <Section icon={ShoppingCart} title="Purchase orders" testid="section-job-pos"
            action={canManage && <Button size="sm" variant="outline" onClick={() => setPoOpen(true)} data-testid="job-create-po"><Plus className="h-4 w-4" /> New PO</Button>}>
            {job.purchase_orders.length === 0 ? <p className="text-sm text-slate-500">No purchase orders for this job.</p> : (
              <div className="space-y-2">
                {job.purchase_orders.map((po) => (
                  <div key={po.id} className={`flex items-center justify-between gap-3 rounded border border-border p-2 text-sm ${canManage ? "cursor-pointer hover:border-orange-300" : ""}`} onClick={canManage ? () => navigate(`/purchase-orders/${po.id}`) : undefined} data-testid={`job-po-${po.id}`}>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2"><span className="font-medium text-slate-900">{po.number}</span><Badge variant="secondary" data-testid={`job-po-status-${po.id}`}>{po.status.replace(/_/g, " ")}</Badge></div>
                      <div className="mt-0.5 truncate text-xs text-slate-500" data-testid={`job-po-meta-${po.id}`}>{po.supplier_name || "No supplier"}{po.expected_date ? ` · Expected ${shortDay(po.expected_date)}` : ""}</div>
                    </div>
                    {po.total != null && <span className="tabular-nums" data-testid={`job-po-total-${po.id}`}>{money(po.total)}</span>}
                  </div>
                ))}
              </div>
            )}
          </Section>

          {canManage && (
            <Section icon={DollarSign} title="Costing" testid="section-job-costing">
              <JobCosting jobId={id} canManage={canManage} />
            </Section>
          )}

          <Section icon={Camera} title="Field photos" testid="section-job-photos">
            <PhotoGallery recordType="job" recordId={id} testid="job-photos" />
          </Section>
        </div>
      </div>

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent data-testid="job-material-dialog">
          <DialogHeader><DialogTitle>Add material to job</DialogTitle><DialogDescription>Plan a material and quantity for this job.</DialogDescription></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5"><Label>Material</Label>
              <Select value={pick.material_id} onValueChange={(v) => setPick({ ...pick, material_id: v })}>
                <SelectTrigger data-testid="jobmat-select"><SelectValue placeholder="Select material" /></SelectTrigger>
                <SelectContent>{materials.map((m) => <SelectItem key={m.id} value={m.id}>{m.name} ({m.unit}) · on hand {m.quantity_on_hand}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5"><Label>Planned quantity</Label><Input type="number" value={pick.planned_quantity} onChange={(e) => setPick({ ...pick, planned_quantity: e.target.value })} data-testid="jobmat-qty" /></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setAddOpen(false)}>Cancel</Button><Button onClick={addMaterial} data-testid="jobmat-save">Add</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <PODialog open={poOpen} onOpenChange={setPoOpen} jobId={id} onCreated={load} />
    </div>
  );
}

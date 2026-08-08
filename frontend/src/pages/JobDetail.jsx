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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import PODialog from "@/components/PODialog";
import PhotoGallery from "@/components/PhotoGallery";
import { CalendarClock, Boxes, ShoppingCart, User, Home, Plus, AlertTriangle, Save, Loader2, UserCheck, Camera } from "lucide-react";

const MANAGE = ["owner", "administrator", "office"];
const UNASSIGNED = "__unassigned__";
const STATUSES = ["created", "pending", "scheduled", "in_progress", "completed", "cancelled"];
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
  const { user } = useAuth();
  const canManage = MANAGE.includes(user?.role);
  const [job, setJob] = useState(null);
  const [materials, setMaterials] = useState([]);
  const [sched, setSched] = useState({ status: "created", scheduled_start: "", scheduled_end: "", schedule_notes: "", assigned_to: "" });
  const [addOpen, setAddOpen] = useState(false);
  const [pick, setPick] = useState({ material_id: "", planned_quantity: 1 });
  const [poOpen, setPoOpen] = useState(false);
  const [assignable, setAssignable] = useState([]);
  const [assigning, setAssigning] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const j = (await api.get(`/jobs/${id}`)).data;
      setJob(j);
      setSched({
        status: j.status || "created",
        scheduled_start: j.scheduled_start ? j.scheduled_start.slice(0, 10) : "",
        scheduled_end: j.scheduled_end ? j.scheduled_end.slice(0, 10) : "",
        schedule_notes: j.schedule_notes || "", assigned_to: j.assigned_to || "",
      });
    } catch (e) { toast.error(apiError(e)); }
  }, [id]);

  useEffect(() => { load(); api.get("/materials").then((r) => setMaterials(r.data)).catch(() => {}); }, [load]);

  useEffect(() => {
    if (canManage) api.get("/users/assignable").then((r) => setAssignable(r.data)).catch(() => {});
  }, [canManage]);

  const assignJob = async (value) => {
    setAssigning(true);
    try {
      const user_id = value === UNASSIGNED ? null : value;
      const { data } = await api.put(`/jobs/${id}/assign`, { user_id });
      setJob(data);
      toast.success(user_id ? `Assigned to ${data.assigned_user_name}` : "Assignment cleared");
    } catch (e) { toast.error(apiError(e)); } finally { setAssigning(false); }
  };

  const saveSchedule = async () => {
    setBusy(true);
    try {
      await api.patch(`/jobs/${id}`, {
        status: sched.status,
        scheduled_start: sched.scheduled_start ? new Date(sched.scheduled_start).toISOString() : null,
        scheduled_end: sched.scheduled_end ? new Date(sched.scheduled_end).toISOString() : null,
        schedule_notes: sched.schedule_notes, assigned_to: sched.assigned_to,
      });
      toast.success("Schedule saved"); load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const addMaterial = async () => {
    if (!pick.material_id) { toast.error("Select a material"); return; }
    try { await api.post(`/jobs/${id}/materials`, { material_id: pick.material_id, planned_quantity: Number(pick.planned_quantity) || 1 }); toast.success("Material added to job"); setAddOpen(false); setPick({ material_id: "", planned_quantity: 1 }); load(); }
    catch (e) { toast.error(apiError(e)); }
  };

  if (!job) return <div className="flex h-64 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>;

  return (
    <div>
      <PageHeader title={`Job ${job.number}`}
        description={<span className="flex flex-wrap items-center gap-3"><span className="flex items-center gap-1"><User className="h-3.5 w-3.5" />{job.customer_name || "—"}</span><span className="flex items-center gap-1"><Home className="h-3.5 w-3.5" />{job.property_address || "—"}</span></span>}
        testid="page-job-detail"
        actions={<div className="flex items-center gap-2"><Badge className={sc[job.status] || ""} variant="secondary" data-testid="job-status-badge">{job.status.replace("_", " ")}</Badge><span className="font-heading font-bold text-slate-900">{money(job.total)}</span></div>} />
      <div className="grid grid-cols-1 gap-5 p-6 sm:p-8 lg:grid-cols-2">
        {/* Schedule */}
        <Section icon={CalendarClock} title="Schedule & status" testid="section-schedule">
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label>Status</Label>
                <Select value={sched.status} onValueChange={(v) => setSched({ ...sched, status: v })} disabled={!canManage}>
                  <SelectTrigger data-testid="job-status-select"><SelectValue /></SelectTrigger>
                  <SelectContent>{STATUSES.map((s) => <SelectItem key={s} value={s}>{s.replace("_", " ")}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5"><Label>Assigned to (crew)</Label><Input value={sched.assigned_to} onChange={(e) => setSched({ ...sched, assigned_to: e.target.value })} disabled={!canManage} data-testid="job-assigned" /></div>
            </div>
            <div className="space-y-1.5"><Label>Assigned field user</Label>
              {canManage ? (
                <Select value={job.assigned_user_id || UNASSIGNED} onValueChange={assignJob} disabled={assigning}>
                  <SelectTrigger data-testid="job-assign-select"><SelectValue placeholder="Unassigned" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={UNASSIGNED} data-testid="job-assign-unassigned">Unassigned</SelectItem>
                    {assignable.map((u) => (
                      <SelectItem key={u.id} value={u.id} data-testid={`job-assign-${u.id}`}>{u.full_name || u.email} · {u.role}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <p className="text-sm text-slate-600" data-testid="job-assigned-readonly">{job.assigned_user_name ? `Assigned to ${job.assigned_user_name}` : "Unassigned"}</p>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label>Start date</Label><Input type="date" value={sched.scheduled_start} onChange={(e) => setSched({ ...sched, scheduled_start: e.target.value })} disabled={!canManage} data-testid="job-start" /></div>
              <div className="space-y-1.5"><Label>End date</Label><Input type="date" value={sched.scheduled_end} onChange={(e) => setSched({ ...sched, scheduled_end: e.target.value })} disabled={!canManage} data-testid="job-end" /></div>
            </div>
            <div className="space-y-1.5"><Label>Scheduling notes</Label><Textarea value={sched.schedule_notes} onChange={(e) => setSched({ ...sched, schedule_notes: e.target.value })} disabled={!canManage} data-testid="job-schednotes" /></div>
            {canManage && <Button onClick={saveSchedule} disabled={busy} data-testid="save-schedule">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Save className="h-4 w-4" /> Save schedule</>}</Button>}
            {job.quote_id && <p className="text-xs text-slate-400">From accepted quote · <Link to="/finance" className="hover:underline">view in Finance</Link></p>}
          </div>
        </Section>

        {/* Materials */}
        <Section icon={Boxes} title="Required materials" testid="section-job-materials"
          action={canManage && <Button size="sm" variant="outline" onClick={() => setAddOpen(true)} data-testid="add-job-material"><Plus className="h-4 w-4" /> Add</Button>}>
          {job.materials.length === 0 ? <p className="text-sm text-slate-500">No materials assigned yet.</p> : (
            <div className="space-y-2">
              {job.materials.map((m) => (
                <div key={m.id} className="flex items-center justify-between rounded border border-border p-2 text-sm" data-testid={`jobmat-${m.id}`}>
                  <div><span className="font-medium text-slate-900">{m.material_name}</span> <span className="text-slate-400">· need {m.planned_quantity} {m.unit}</span></div>
                  <div className="flex items-center gap-2">
                    <span className="tabular-nums text-slate-500">on hand {m.quantity_on_hand}</span>
                    {m.low_stock && <Badge className="bg-amber-50 text-amber-700" variant="secondary" data-testid={`jobmat-low-${m.id}`}><AlertTriangle className="mr-1 h-3 w-3" /> Low</Badge>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Section>

        {/* Purchase orders */}
        <Section icon={ShoppingCart} title="Purchase orders" testid="section-job-pos"
          action={canManage && <Button size="sm" variant="outline" onClick={() => setPoOpen(true)} data-testid="job-create-po"><Plus className="h-4 w-4" /> New PO</Button>}>
          {job.purchase_orders.length === 0 ? <p className="text-sm text-slate-500">No purchase orders for this job. Manage receiving in Inventory.</p> : (
            <div className="space-y-2">
              {job.purchase_orders.map((po) => (
                <div key={po.id} className="flex items-center justify-between rounded border border-border p-2 text-sm" data-testid={`job-po-${po.id}`}>
                  <div className="flex items-center gap-2"><span className="font-medium text-slate-900">{po.number}</span><Badge variant="secondary">{po.status.replace("_", " ")}</Badge></div>
                  <span className="tabular-nums">{money(po.total)}</span>
                </div>
              ))}
              <Link to="/inventory" className="text-xs text-orange-600 hover:underline">Receive materials in Inventory →</Link>
            </div>
          )}
        </Section>

        {/* Field Photos */}
        <Section icon={Camera} title="Field photos" testid="section-job-photos">
          <PhotoGallery recordType="job" recordId={id} testid="job-photos" />
        </Section>
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

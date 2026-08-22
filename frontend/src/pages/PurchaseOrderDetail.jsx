import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money, shortDate } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { useAuth } from "@/context/AuthContext";
import ReceivingAttachments from "@/components/ReceivingAttachments";
import { ArrowLeft, Loader2, PackageCheck, Ban, Truck, Building2, Link2, Paperclip, CircleDot } from "lucide-react";

const MANAGE = ["owner", "administrator", "office"];

function StatusTimeline({ poId }) {
  const [events, setEvents] = useState(null);
  useEffect(() => { api.get(`/purchase-orders/${poId}/status-history`).then((r) => setEvents(r.data.events)).catch(() => setEvents([])); }, [poId]);
  if (events === null) return <div className="flex items-center gap-2 text-sm text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>;
  if (events.length === 0) return <p className="text-sm text-slate-400">No status events recorded.</p>;
  return (
    <ol className="relative ml-2 border-l border-slate-200" data-testid="po-status-timeline">
      {events.map((e) => (
        <li key={e.id} className="mb-4 ml-4" data-testid={`po-status-event-${e.normalized_status}`}>
          <span className="absolute -left-1.5 mt-1 flex h-3 w-3 items-center justify-center"><CircleDot className="h-3 w-3 text-orange-500" /></span>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium capitalize text-slate-800">{e.normalized_status.replace(/_/g, " ")}</span>
            {e.source === "abc" && <Badge variant="secondary" className="bg-indigo-50 text-indigo-700">ABC</Badge>}
            {e.source === "imported" && <Badge variant="secondary" className="bg-slate-100 text-slate-500">imported</Badge>}
            {e.provider_status && <span className="text-xs text-slate-400">provider: {e.provider_status}</span>}
          </div>
          <div className="text-xs text-slate-400">{e.created_at ? new Date(e.created_at).toLocaleString() : ""}{e.note ? ` · ${e.note}` : ""}</div>
        </li>
      ))}
    </ol>
  );
}
const STATUS = {
  draft: "bg-slate-100 text-slate-600", ready_for_review: "bg-blue-50 text-blue-700",
  submitted: "bg-indigo-50 text-indigo-700", acknowledged: "bg-indigo-50 text-indigo-700",
  scheduled: "bg-blue-50 text-blue-700", partially_received: "bg-amber-50 text-amber-700",
  received: "bg-green-50 text-green-700", backordered: "bg-red-50 text-red-700",
  cancelled: "bg-slate-100 text-slate-400",
};

export default function PurchaseOrderDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canManage = MANAGE.includes(user?.role);
  const [po, setPo] = useState(null);
  const [recvOpen, setRecvOpen] = useState(false);
  const [recv, setRecv] = useState({});
  const [recvLoc, setRecvLoc] = useState("");
  const [locations, setLocations] = useState([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.get("/inventory/locations", { params: { active: true } }).then((r) => { setLocations(r.data); const d = r.data.find((l) => l.is_default) || r.data[0]; if (d) setRecvLoc(d.id); }).catch(() => {}); }, []);

  const load = useCallback(async () => {
    try { const { data } = await api.get(`/purchase-orders/${id}`); setPo(data); }
    catch (e) { toast.error(apiError(e)); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const isAbc = po?.integration_provider === "abc_supply";
  const openReceive = () => { const init = {}; (po.items || []).forEach((i) => { init[i.id] = Math.max((i.quantity || 0) - (i.received_quantity || 0), 0); }); setRecv(init); setRecvOpen(true); };
  const doReceive = async () => {
    const items = Object.entries(recv).filter(([, q]) => Number(q) > 0).map(([po_item_id, q]) => ({ po_item_id, quantity: Number(q) }));
    if (!items.length) { toast.error("Enter quantities to receive"); return; }
    setBusy(true);
    try { await api.post(`/purchase-orders/${id}/receive`, { items, location_id: recvLoc || null }); toast.success("Received"); setRecvOpen(false); load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const cancel = async () => { try { await api.post(`/purchase-orders/${id}/status`, { status: "cancelled" }); toast.success("PO cancelled"); load(); } catch (e) { toast.error(apiError(e)); } };
  const setStatus = async (status) => { try { await api.post(`/purchase-orders/${id}/status`, { status }); toast.success(`Marked ${status.replace(/_/g, " ")}`); load(); } catch (e) { toast.error(apiError(e)); } };

  if (!po) return <div className="p-8"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>;
  const canReceive = canManage && !["draft", "cancelled", "received"].includes(po.status);

  return (
    <div>
      <PageHeader title={`PO ${po.number}`} description="Purchase order detail, supplier integration and receiving." testid="page-po-detail" />
      <div className="p-6 sm:p-8">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <Button variant="ghost" size="sm" onClick={() => navigate(-1)} data-testid="po-back"><ArrowLeft className="h-4 w-4" /> Back</Button>
          <div className="flex flex-wrap gap-2">
            {canManage && isAbc && ["draft", "ready_for_review"].includes(po.status) && po.job_id && <Button size="sm" onClick={() => navigate(`/jobs/${po.job_id}`)} data-testid="po-abc-review"><Truck className="h-4 w-4" /> Review &amp; submit in ABC</Button>}
            {canManage && !isAbc && po.status === "draft" && <Button size="sm" onClick={() => setStatus("ordered")} data-testid="po-mark-ordered"><Truck className="h-4 w-4" /> Mark ordered</Button>}
            {canReceive && <Button size="sm" onClick={openReceive} data-testid="po-receive"><PackageCheck className="h-4 w-4" /> Receive</Button>}
            {canManage && po.status !== "cancelled" && po.status !== "received" && <Button size="sm" variant="outline" onClick={cancel} data-testid="po-cancel"><Ban className="h-4 w-4" /> Cancel</Button>}
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <Card title="Header" icon={Link2} testid="po-header">
            <Field label="Status" value={<Badge variant="secondary" className={STATUS[po.status] || ""} data-testid="po-status">{po.status.replace(/_/g, " ")}</Badge>} />
            <Field label="Supplier" value={po.supplier_name || "—"} />
            <Field label="Linked job" value={po.job_id ? <button className="text-orange-600 hover:underline" onClick={() => navigate(`/jobs/${po.job_id}`)} data-testid="po-job-link">View job</button> : "—"} />
            <Field label="Order date" value={po.order_date ? shortDate(po.order_date) : "—"} />
            <Field label="Expected" value={po.expected_date ? shortDate(po.expected_date) : "—"} />
            <Field label="Total" value={<span className="font-semibold tabular-nums">{money(po.total)}</span>} />
          </Card>

          <Card title="Supplier & delivery" icon={Building2} testid="po-supplier-card">
            <Field label="Integration" value={isAbc ? <Badge variant="secondary" className="bg-blue-50 text-blue-700">ABC Supply</Badge> : "Manual"} />
            {isAbc && <>
              <Field label="Ship-To" value={po.abc_ship_to_number || "—"} />
              <Field label="Branch" value={po.abc_branch_number || "—"} />
            </>}
            {po.abc_delivery && <Field label="Delivery" value={<span className="text-xs">{po.abc_delivery.address_line1 || po.abc_delivery.contact_name || "—"}</span>} />}
            {po.notes && <Field label="Notes" value={<span className="text-xs">{po.notes}</span>} />}
          </Card>

          <Card title="Supplier integration" icon={Truck} testid="po-integration-card">
            {isAbc ? <>
              <Field label="External order #" value={po.external_order_number || "—"} />
              <Field label="Confirmation #" value={po.external_confirmation_number || "—"} />
              <Field label="Tracking" value={po.external_tracking_id || "—"} />
              <Field label="Provider status" value={po.abc_order_status || "—"} />
              <Field label="Normalized" value={po.abc_normalized_status || po.status} />
              <Field label="Last sync" value={po.abc_last_sync_at ? shortDate(po.abc_last_sync_at) : "—"} />
            </> : <p className="text-sm text-slate-400">Manual supplier — status updated manually. No electronic submission.</p>}
          </Card>
        </div>

        <div className="mt-4 overflow-x-auto rounded-md border border-border bg-white">
          <Table data-testid="po-lines-table">
            <TableHeader><TableRow>
              <TableHead>Item</TableHead><TableHead>Supplier item #</TableHead><TableHead className="text-right">Ordered</TableHead>
              <TableHead className="text-right">Received</TableHead><TableHead className="text-right">Remaining</TableHead>
              <TableHead className="text-right">Unit cost</TableHead><TableHead className="text-right">Line total</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {(po.items || []).map((i) => {
                const remaining = Math.max((i.quantity || 0) - (i.received_quantity || 0), 0);
                return (
                  <TableRow key={i.id} data-testid={`po-line-${i.id}`}>
                    <TableCell>{i.description || i.material_name || "—"}</TableCell>
                    <TableCell className="font-mono text-xs">{i.supplier_item_number || i.abc_item_number || "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{i.quantity} {i.unit}</TableCell>
                    <TableCell className="text-right tabular-nums">{i.received_quantity || 0}</TableCell>
                    <TableCell className="text-right tabular-nums">{remaining}</TableCell>
                    <TableCell className="text-right tabular-nums">{money(i.unit_cost || 0)}</TableCell>
                    <TableCell className="text-right tabular-nums">{money(i.line_total ?? (i.quantity * (i.unit_cost || 0)))}</TableCell>
                  </TableRow>
                );
              })}
              {(po.items || []).length === 0 && <TableRow><TableCell colSpan={7} className="py-6 text-center text-slate-400">No line items.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>

        {/* Status timeline (real stored events) */}
        <div className="mt-6 rounded-md border border-border bg-white p-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-700">Status timeline</h3>
          <StatusTimeline poId={id} />
        </div>

        {/* Receiving attachments (reuses RoofSpan photo infrastructure) */}
        <div className="mt-4 rounded-md border border-border bg-white p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-700"><Paperclip className="h-4 w-4" /> Receiving attachments</h3>
          <ReceivingAttachments poId={id} canUpload={canManage} />
        </div>
      </div>

      <Dialog open={recvOpen} onOpenChange={setRecvOpen}>
        <DialogContent data-testid="po-receive-dialog">
          <DialogHeader><DialogTitle>Receive items</DialogTitle><DialogDescription>Enter received quantities. Partial receipts are supported and update inventory On Hand at the selected location.</DialogDescription></DialogHeader>
          <div className="mb-2 space-y-1"><Label className="text-xs">Receive to location</Label>
            <Select value={recvLoc} onValueChange={setRecvLoc}><SelectTrigger data-testid="recv-location"><SelectValue placeholder="Location" /></SelectTrigger>
              <SelectContent>{locations.map((l) => <SelectItem key={l.id} value={l.id}>{l.name} ({l.type})</SelectItem>)}</SelectContent></Select>
          </div>
          <div className="space-y-2">
            {(po.items || []).map((i) => {
              const remaining = Math.max((i.quantity || 0) - (i.received_quantity || 0), 0);
              return (
                <div key={i.id} className="flex items-center justify-between gap-2" data-testid={`recv-line-${i.id}`}>
                  <span className="min-w-0 flex-1 truncate text-sm">{i.description || i.material_name} <span className="text-xs text-slate-400">(rem {remaining})</span></span>
                  <Input type="number" value={recv[i.id] ?? 0} max={remaining} onChange={(e) => setRecv({ ...recv, [i.id]: e.target.value })} className="h-8 w-24" data-testid={`recv-qty-${i.id}`} />
                </div>
              );
            })}
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setRecvOpen(false)}>Cancel</Button><Button onClick={doReceive} disabled={busy} data-testid="recv-confirm">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Receive"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Card({ title, icon: Icon, children, testid }) {
  return <div className="rounded-md border border-border bg-white p-4" data-testid={testid}><div className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-slate-700"><Icon className="h-4 w-4 text-orange-500" />{title}</div><div className="space-y-1.5">{children}</div></div>;
}
function Field({ label, value }) {
  return <div className="flex items-center justify-between gap-3 text-sm"><span className="text-slate-400">{label}</span><span className="text-right text-slate-800">{value}</span></div>;
}

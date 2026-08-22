import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { shortDate } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAuth } from "@/context/AuthContext";
import { Warehouse, Plus, ArrowLeftRight, Loader2, MapPin } from "lucide-react";

const MANAGE = ["owner", "administrator", "office"];
const TYPES = ["warehouse", "yard", "truck", "job_site", "returns", "damaged", "other"];

export default function InventoryLocations() {
  const { user } = useAuth();
  const canManage = MANAGE.includes(user?.role);
  const [rows, setRows] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", type: "warehouse", address: "", notes: "" });
  const [editing, setEditing] = useState(null);
  const [detail, setDetail] = useState(null);
  const [counting, setCounting] = useState(null); // {location_id, lines:[{material_id,material_name,unit,system,counted}]}
  const [xfer, setXfer] = useState(null); // { material_id, source_location_id, destination_location_id, quantity }

  const startCount = () => {
    setCounting({ location_id: detail.location.id, lines: detail.materials.map((m) => ({ material_id: m.material_id, material_name: m.material_name, unit: m.unit, system: m.quantity_on_hand, counted: m.quantity_on_hand })) });
  };
  const submitCount = async () => {
    try {
      const changed = counting.lines.filter((l) => Number(l.counted) !== l.system);
      if (!changed.length) { toast.info("No variances to post"); setCounting(null); return; }
      await api.post("/inventory/cycle-count", { location_id: counting.location_id, lines: changed.map((l) => ({ material_id: l.material_id, counted_quantity: Number(l.counted) })) });
      toast.success(`Posted ${changed.length} adjustment(s)`); setCounting(null); openDetail({ id: detail.location.id });
    } catch (e) { toast.error(apiError(e)); }
  };

  const load = useCallback(async () => {
    try { const { data } = await api.get("/inventory/locations"); setRows(data); }
    catch (e) { toast.error(apiError(e)); }
  }, []);
  useEffect(() => { load(); api.get("/materials", { params: { active: true } }).then((r) => setMaterials(r.data)).catch(() => {}); }, [load]);

  const save = async () => {
    try {
      if (editing) await api.patch(`/inventory/locations/${editing}`, form);
      else await api.post("/inventory/locations", form);
      toast.success(editing ? "Location updated" : "Location created"); setOpen(false); setEditing(null); setForm({ name: "", type: "warehouse", address: "", notes: "" }); load();
    } catch (e) { toast.error(apiError(e)); }
  };
  const openEdit = (l) => { setEditing(l.id); setForm({ name: l.name, type: l.type, address: l.address || "", notes: l.notes || "", active: l.active }); setOpen(true); };
  const toggle = async (l) => { try { await api.patch(`/inventory/locations/${l.id}`, { active: !l.active }); load(); } catch (e) { toast.error(apiError(e)); } };
  const openDetail = async (l) => { try { const { data } = await api.get(`/inventory/locations/${l.id}`); setDetail(data); } catch (e) { toast.error(apiError(e)); } };

  const doTransfer = async () => {
    try { await api.post("/inventory/transfer", { ...xfer, quantity: Number(xfer.quantity) }); toast.success("Transfer complete"); setXfer(null); if (detail) openDetail({ id: detail.location.id }); }
    catch (e) { toast.error(apiError(e)); }
  };

  return (
    <div>
      <PageHeader title="Inventory Locations" description="Warehouses, yards, trucks and job sites — track where every material is stored." testid="page-locations" />
      <div className="p-6 sm:p-8">
        {canManage && <div className="mb-4 flex gap-2">
          <Button onClick={() => { setEditing(null); setForm({ name: "", type: "warehouse", address: "", notes: "" }); setOpen(true); }} data-testid="add-location-button"><Plus className="h-4 w-4" /> New location</Button>
          <Button variant="outline" onClick={() => setXfer({ material_id: "", source_location_id: "", destination_location_id: "", quantity: 1 })} data-testid="transfer-button"><ArrowLeftRight className="h-4 w-4" /> Transfer</Button>
        </div>}
        <div className="rounded-md border border-border bg-white">
          <Table data-testid="locations-table">
            <TableHeader><TableRow><TableHead>Location</TableHead><TableHead>Type</TableHead><TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>
              {rows.map((l) => (
                <TableRow key={l.id} data-testid={`location-row-${l.id}`}>
                  <TableCell className="font-medium text-slate-800 cursor-pointer hover:text-orange-600" onClick={() => openDetail(l)}><Warehouse className="mr-1 inline h-3.5 w-3.5 text-orange-500" />{l.name}{l.is_default ? <Badge variant="secondary" className="ml-2 bg-indigo-50 text-indigo-700">Default</Badge> : ""}</TableCell>
                  <TableCell className="text-slate-500">{l.type.replace(/_/g, " ")}</TableCell>
                  <TableCell>{l.active ? <Badge className="bg-green-50 text-green-700" variant="secondary">Active</Badge> : <Badge variant="secondary" className="bg-slate-100 text-slate-500">Inactive</Badge>}</TableCell>
                  <TableCell className="text-right">{canManage && <><Button size="sm" variant="outline" onClick={() => openEdit(l)} data-testid={`edit-location-${l.id}`}>Edit</Button> {!l.is_default && <Button size="sm" variant="ghost" onClick={() => toggle(l)} data-testid={`toggle-location-${l.id}`}>{l.active ? "Deactivate" : "Reactivate"}</Button>}</>}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="location-form">
          <DialogHeader><DialogTitle>{editing ? "Edit location" : "New location"}</DialogTitle><DialogDescription>Physical place where inventory is stored.</DialogDescription></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1"><Label className="text-xs">Name</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="location-name" /></div>
            <div className="space-y-1"><Label className="text-xs">Type</Label><Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}><SelectTrigger data-testid="location-type"><SelectValue /></SelectTrigger><SelectContent>{TYPES.map((t) => <SelectItem key={t} value={t}>{t.replace(/_/g, " ")}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-1"><Label className="text-xs">Address</Label><Input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} /></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={save} disabled={!form.name} data-testid="location-save">{editing ? "Save" : "Create"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto" data-testid="location-detail">
          <DialogHeader><DialogTitle>{detail?.location?.name}</DialogTitle><DialogDescription>{detail?.location?.type} {detail?.location?.address ? `· ${detail.location.address}` : ""}</DialogDescription></DialogHeader>
          {detail && <div className="space-y-4">
            {canManage && <div className="flex gap-2"><Button size="sm" variant="outline" onClick={startCount} data-testid="start-cycle-count"><MapPin className="h-4 w-4" /> Cycle Count</Button></div>}
            <div>
              <div className="mb-1 text-xs font-semibold uppercase text-slate-400">Materials at this location</div>
              <div className="max-h-56 overflow-y-auto rounded-md border border-border">
                <Table><TableHeader><TableRow><TableHead>Material</TableHead><TableHead className="text-right">On hand</TableHead></TableRow></TableHeader>
                  <TableBody>{detail.materials.map((m) => <TableRow key={m.material_id}><TableCell>{m.material_name}</TableCell><TableCell className="text-right tabular-nums">{m.quantity_on_hand} {m.unit}</TableCell></TableRow>)}{detail.materials.length === 0 && <TableRow><TableCell colSpan={2} className="text-center text-slate-400">Empty.</TableCell></TableRow>}</TableBody>
                </Table>
              </div>
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold uppercase text-slate-400">Recent transactions</div>
              <div className="max-h-48 overflow-y-auto rounded-md border border-border">
                <Table><TableHeader><TableRow><TableHead>When</TableHead><TableHead>Reason</TableHead><TableHead className="text-right">Δ</TableHead></TableRow></TableHeader>
                  <TableBody>{detail.recent_transactions.map((t) => <TableRow key={t.id}><TableCell className="text-xs">{shortDate(t.created_at)}</TableCell><TableCell className="text-xs">{t.reason}</TableCell><TableCell className="text-right tabular-nums">{t.delta}</TableCell></TableRow>)}{detail.recent_transactions.length === 0 && <TableRow><TableCell colSpan={3} className="text-center text-slate-400">No activity.</TableCell></TableRow>}</TableBody>
                </Table>
              </div>
            </div>
          </div>}
        </DialogContent>
      </Dialog>

      <Dialog open={!!xfer} onOpenChange={(o) => !o && setXfer(null)}>
        <DialogContent className="max-w-md" data-testid="transfer-dialog">
          <DialogHeader><DialogTitle>Transfer inventory</DialogTitle><DialogDescription>Move stock between locations. Company total is unchanged.</DialogDescription></DialogHeader>
          {xfer && <div className="space-y-3">
            <div className="space-y-1"><Label className="text-xs">Material</Label><Select value={xfer.material_id} onValueChange={(v) => setXfer({ ...xfer, material_id: v })}><SelectTrigger data-testid="xfer-material"><SelectValue placeholder="Material" /></SelectTrigger><SelectContent className="max-h-64">{materials.map((m) => <SelectItem key={m.id} value={m.id}>{m.name}</SelectItem>)}</SelectContent></Select></div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1"><Label className="text-xs">From</Label><Select value={xfer.source_location_id} onValueChange={(v) => setXfer({ ...xfer, source_location_id: v })}><SelectTrigger data-testid="xfer-source"><SelectValue placeholder="Source" /></SelectTrigger><SelectContent>{rows.filter((l) => l.active).map((l) => <SelectItem key={l.id} value={l.id}>{l.name}</SelectItem>)}</SelectContent></Select></div>
              <div className="space-y-1"><Label className="text-xs">To</Label><Select value={xfer.destination_location_id} onValueChange={(v) => setXfer({ ...xfer, destination_location_id: v })}><SelectTrigger data-testid="xfer-dest"><SelectValue placeholder="Destination" /></SelectTrigger><SelectContent>{rows.filter((l) => l.active).map((l) => <SelectItem key={l.id} value={l.id}>{l.name}</SelectItem>)}</SelectContent></Select></div>
            </div>
            <div className="space-y-1"><Label className="text-xs">Quantity</Label><Input type="number" value={xfer.quantity} onChange={(e) => setXfer({ ...xfer, quantity: e.target.value })} data-testid="xfer-qty" /></div>
          </div>}
          <DialogFooter><Button variant="outline" onClick={() => setXfer(null)}>Cancel</Button><Button onClick={doTransfer} disabled={!xfer?.material_id || !xfer?.source_location_id || !xfer?.destination_location_id} data-testid="xfer-confirm">Transfer</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!counting} onOpenChange={(o) => !o && setCounting(null)}>
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto" data-testid="cycle-count-dialog">
          <DialogHeader><DialogTitle>Cycle count</DialogTitle><DialogDescription>Enter physical counts. Variances post as adjustment ledger entries (server-authoritative).</DialogDescription></DialogHeader>
          {counting && <div className="rounded-md border border-border">
            <Table><TableHeader><TableRow><TableHead>Material</TableHead><TableHead className="text-right">System</TableHead><TableHead className="text-right w-28">Counted</TableHead><TableHead className="text-right">Variance</TableHead></TableRow></TableHeader>
              <TableBody>{counting.lines.map((l, i) => { const v = Math.round((Number(l.counted) - l.system) * 1000) / 1000; return (
                <TableRow key={l.material_id} data-testid={`count-row-${l.material_id}`}>
                  <TableCell>{l.material_name}</TableCell>
                  <TableCell className="text-right tabular-nums">{l.system} {l.unit}</TableCell>
                  <TableCell><Input type="number" value={l.counted} onChange={(e) => setCounting({ ...counting, lines: counting.lines.map((x, idx) => idx === i ? { ...x, counted: e.target.value } : x) })} className="h-8 text-right" data-testid={`count-input-${l.material_id}`} /></TableCell>
                  <TableCell className={`text-right tabular-nums ${v > 0 ? "text-green-600" : v < 0 ? "text-red-600" : "text-slate-400"}`} data-testid={`count-variance-${l.material_id}`}>{v > 0 ? "+" : ""}{v}</TableCell>
                </TableRow>
              ); })}{counting.lines.length === 0 && <TableRow><TableCell colSpan={4} className="text-center text-slate-400">No materials at this location.</TableCell></TableRow>}</TableBody>
            </Table>
          </div>}
          <DialogFooter><Button variant="outline" onClick={() => setCounting(null)}>Cancel</Button><Button onClick={submitCount} data-testid="count-submit">Post adjustments</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

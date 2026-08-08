import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { money, shortDate } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import PODialog from "@/components/PODialog";
import ReceiveDialog from "@/components/ReceiveDialog";
import { Boxes, Plus, AlertTriangle, PackageCheck, Loader2 } from "lucide-react";

const MANAGE = ["owner", "administrator", "office"];
const PO_STATUS = ["draft", "ordered", "partially_received", "received", "cancelled"];
const sc = { draft: "bg-slate-100 text-slate-600", ordered: "bg-blue-50 text-blue-700", partially_received: "bg-amber-50 text-amber-700", received: "bg-green-50 text-green-700", cancelled: "bg-red-50 text-red-500" };

export default function Inventory() {
  const { user } = useAuth();
  const canManage = MANAGE.includes(user?.role);
  const [materials, setMaterials] = useState([]);
  const [pos, setPos] = useState([]);
  const [matOpen, setMatOpen] = useState(false);
  const [form, setForm] = useState({ name: "", category: "", unit: "each", reorder_threshold: 0, quantity_on_hand: 0 });
  const [adjOpen, setAdjOpen] = useState(false);
  const [adjTarget, setAdjTarget] = useState(null);
  const [adj, setAdj] = useState({ delta: 0, reason: "correction" });
  const [poOpen, setPoOpen] = useState(false);
  const [recvOpen, setRecvOpen] = useState(false);
  const [recvPo, setRecvPo] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.get("/materials").then((r) => setMaterials(r.data)).catch((e) => toast.error(apiError(e)));
    api.get("/purchase-orders").then((r) => setPos(r.data)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  const lowCount = materials.filter((m) => m.low_stock).length;

  const createMaterial = async () => {
    if (!form.name.trim()) { toast.error("Name is required"); return; }
    setBusy(true);
    try { await api.post("/materials", { ...form, reorder_threshold: Number(form.reorder_threshold) || 0, quantity_on_hand: Number(form.quantity_on_hand) || 0 }); toast.success("Material added"); setMatOpen(false); setForm({ name: "", category: "", unit: "each", reorder_threshold: 0, quantity_on_hand: 0 }); load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const doAdjust = async () => {
    try { await api.post(`/materials/${adjTarget.id}/adjust`, { delta: Number(adj.delta) || 0, reason: adj.reason }); toast.success("Inventory adjusted"); setAdjOpen(false); load(); }
    catch (e) { toast.error(apiError(e)); }
  };
  const setPoStatus = async (id, status) => {
    try { await api.post(`/purchase-orders/${id}/status`, { status }); toast.success("PO updated"); load(); }
    catch (e) { toast.error(apiError(e)); }
  };

  return (
    <div>
      <PageHeader title="Inventory" description={lowCount > 0 ? `${lowCount} material${lowCount === 1 ? "" : "s"} low on stock` : "Materials, stock levels & purchasing"} testid="page-inventory"
        actions={lowCount > 0 && <Badge className="bg-amber-50 text-amber-700" variant="secondary" data-testid="low-stock-count"><AlertTriangle className="mr-1 h-3.5 w-3.5" /> {lowCount} low</Badge>} />
      <div className="p-6 sm:p-8">
        <Tabs defaultValue="materials">
          <TabsList data-testid="inventory-tabs">
            <TabsTrigger value="materials" data-testid="tab-materials">Materials</TabsTrigger>
            <TabsTrigger value="pos" data-testid="tab-pos">Purchase Orders</TabsTrigger>
          </TabsList>

          <TabsContent value="materials" className="mt-6">
            {canManage && <div className="mb-4"><Button onClick={() => setMatOpen(true)} data-testid="add-material-button"><Plus className="h-4 w-4" /> Add material</Button></div>}
            <div className="overflow-x-auto rounded-md border border-border bg-white">
              <Table data-testid="materials-table">
                <TableHeader><TableRow><TableHead>Material</TableHead><TableHead>Category</TableHead><TableHead>Unit</TableHead><TableHead>On hand</TableHead><TableHead>Reorder at</TableHead><TableHead>Status</TableHead>{canManage && <TableHead />}</TableRow></TableHeader>
                <TableBody>
                  {materials.map((m) => (
                    <TableRow key={m.id} data-testid={`material-row-${m.id}`}>
                      <TableCell className="font-medium text-slate-900">{m.name}</TableCell>
                      <TableCell className="text-slate-500">{m.category || "—"}</TableCell>
                      <TableCell className="text-slate-500">{m.unit}</TableCell>
                      <TableCell className="tabular-nums font-medium">{m.quantity_on_hand}</TableCell>
                      <TableCell className="tabular-nums text-slate-500">{m.reorder_threshold}</TableCell>
                      <TableCell>{m.low_stock ? <Badge className="bg-amber-50 text-amber-700" variant="secondary" data-testid={`low-badge-${m.id}`}><AlertTriangle className="mr-1 h-3 w-3" /> Low</Badge> : <Badge variant="secondary" className="bg-green-50 text-green-700">OK</Badge>}</TableCell>
                      {canManage && <TableCell><Button size="sm" variant="outline" onClick={() => { setAdjTarget(m); setAdj({ delta: 0, reason: "correction" }); setAdjOpen(true); }} data-testid={`adjust-${m.id}`}>Adjust</Button></TableCell>}
                    </TableRow>
                  ))}
                  {materials.length === 0 && <TableRow><TableCell colSpan={7} className="text-center text-sm text-slate-400">No materials yet.</TableCell></TableRow>}
                </TableBody>
              </Table>
            </div>
          </TabsContent>

          <TabsContent value="pos" className="mt-6">
            {canManage && <div className="mb-4"><Button onClick={() => setPoOpen(true)} data-testid="create-po-button"><Plus className="h-4 w-4" /> Create purchase order</Button></div>}
            <div className="overflow-x-auto rounded-md border border-border bg-white">
              <Table data-testid="pos-table">
                <TableHeader><TableRow><TableHead>PO #</TableHead><TableHead>Supplier</TableHead><TableHead>Total</TableHead><TableHead>Expected</TableHead><TableHead>Status</TableHead>{canManage && <TableHead />}</TableRow></TableHeader>
                <TableBody>
                  {pos.map((po) => (
                    <TableRow key={po.id} data-testid={`po-row-${po.id}`}>
                      <TableCell className="font-medium text-slate-900">{po.number}</TableCell>
                      <TableCell className="text-slate-600">{po.supplier_name || "—"}</TableCell>
                      <TableCell className="tabular-nums">{money(po.total)}</TableCell>
                      <TableCell className="text-slate-500">{shortDate(po.expected_date)}</TableCell>
                      <TableCell>
                        {canManage ? (
                          <Select value={po.status} onValueChange={(v) => setPoStatus(po.id, v)}>
                            <SelectTrigger className="h-8 w-[160px]" data-testid={`po-status-${po.id}`}><Badge className={sc[po.status] || ""} variant="secondary">{po.status.replace("_", " ")}</Badge></SelectTrigger>
                            <SelectContent>{PO_STATUS.map((s) => <SelectItem key={s} value={s}>{s.replace("_", " ")}</SelectItem>)}</SelectContent>
                          </Select>
                        ) : <Badge className={sc[po.status] || ""} variant="secondary">{po.status.replace("_", " ")}</Badge>}
                      </TableCell>
                      {canManage && <TableCell><Button size="sm" variant="outline" disabled={po.status === "cancelled" || po.status === "received"} onClick={() => { setRecvPo(po); setRecvOpen(true); }} data-testid={`receive-${po.id}`}><PackageCheck className="h-4 w-4" /> Receive</Button></TableCell>}
                    </TableRow>
                  ))}
                  {pos.length === 0 && <TableRow><TableCell colSpan={6} className="text-center text-sm text-slate-400">No purchase orders yet.</TableCell></TableRow>}
                </TableBody>
              </Table>
            </div>
          </TabsContent>
        </Tabs>
      </div>

      <Dialog open={matOpen} onOpenChange={setMatOpen}>
        <DialogContent data-testid="material-dialog">
          <DialogHeader><DialogTitle>Add material</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5"><Label>Name</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="mat-name" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label>Category</Label><Input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} data-testid="mat-category" /></div>
              <div className="space-y-1.5"><Label>Unit</Label><Input value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} placeholder="bundle / roll / each" data-testid="mat-unit" /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label>Quantity on hand</Label><Input type="number" value={form.quantity_on_hand} onChange={(e) => setForm({ ...form, quantity_on_hand: e.target.value })} data-testid="mat-onhand" /></div>
              <div className="space-y-1.5"><Label>Reorder threshold</Label><Input type="number" value={form.reorder_threshold} onChange={(e) => setForm({ ...form, reorder_threshold: e.target.value })} data-testid="mat-threshold" /></div>
            </div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setMatOpen(false)}>Cancel</Button><Button onClick={createMaterial} disabled={busy} data-testid="mat-save">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Add material"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={adjOpen} onOpenChange={setAdjOpen}>
        <DialogContent data-testid="adjust-dialog">
          <DialogHeader><DialogTitle>Adjust — {adjTarget?.name}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-slate-500">On hand: <span className="font-medium">{adjTarget?.quantity_on_hand}</span>. Use a negative number to decrease.</p>
            <div className="space-y-1.5"><Label>Change (+/-)</Label><Input type="number" value={adj.delta} onChange={(e) => setAdj({ ...adj, delta: e.target.value })} data-testid="adjust-delta" /></div>
            <div className="space-y-1.5"><Label>Reason</Label><Input value={adj.reason} onChange={(e) => setAdj({ ...adj, reason: e.target.value })} data-testid="adjust-reason" /></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setAdjOpen(false)}>Cancel</Button><Button onClick={doAdjust} data-testid="adjust-save">Apply</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <PODialog open={poOpen} onOpenChange={setPoOpen} onCreated={load} />
      <ReceiveDialog open={recvOpen} onOpenChange={setRecvOpen} po={recvPo} onReceived={load} />
    </div>
  );
}

import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
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
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import PODialog from "@/components/PODialog";
import ReceiveDialog from "@/components/ReceiveDialog";
import AbcOrderPanel from "@/components/AbcOrderPanel";
import { Boxes, Plus, AlertTriangle, PackageCheck, Loader2, Send, PackageSearch, Upload, ChevronRight, Search } from "lucide-react";

const MANAGE = ["owner", "administrator", "office"];
const PO_STATUS = ["draft", "ordered", "partially_received", "received", "cancelled"];
const sc = { draft: "bg-slate-100 text-slate-600", ordered: "bg-blue-50 text-blue-700", partially_received: "bg-amber-50 text-amber-700", received: "bg-green-50 text-green-700", cancelled: "bg-red-50 text-red-500" };
const TXN_TYPES = ["initial_inventory", "receive_po", "job_reservation", "job_issue", "job_return", "supplier_return", "transfer", "damage", "waste", "loss", "cycle_count", "manual_correction"];
const txnLabel = (t) => t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export default function Inventory() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const canManage = MANAGE.includes(user?.role);
  const [materials, setMaterials] = useState([]);
  const [pos, setPos] = useState([]);
  const [matOpen, setMatOpen] = useState(false);
  const [form, setForm] = useState({ name: "", category: "", unit: "each", reorder_threshold: 0, quantity_on_hand: 0 });
  const [adjOpen, setAdjOpen] = useState(false);
  const [adjTarget, setAdjTarget] = useState(null);
  const [adj, setAdj] = useState({ delta: 0, reason: "manual_correction", note: "" });
  const [csvOpen, setCsvOpen] = useState(false);
  const [csvPreview, setCsvPreview] = useState(null);
  const [csvRows, setCsvRows] = useState([]);
  const [csvAck, setCsvAck] = useState(false);
  const [filters, setFilters] = useState({ q: "", category: "all", manufacturer: "all", supplier_id: "all", active: "all", low_stock: false });
  const [facets, setFacets] = useState({ categories: [], manufacturers: [], suppliers: [] });
  const [poOpen, setPoOpen] = useState(false);
  const [recvOpen, setRecvOpen] = useState(false);
  const [recvPo, setRecvPo] = useState(null);
  const [abcOpen, setAbcOpen] = useState(false);
  const [abcPo, setAbcPo] = useState(null);
  const [abcHistory, setAbcHistory] = useState([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    const p = {};
    if (filters.q) p.q = filters.q;
    if (filters.category !== "all") p.category = filters.category;
    if (filters.manufacturer !== "all") p.manufacturer = filters.manufacturer;
    if (filters.supplier_id !== "all") p.supplier_id = filters.supplier_id;
    if (filters.active !== "all") p.active = filters.active === "active";
    if (filters.low_stock) p.low_stock = true;
    api.get("/materials", { params: p }).then((r) => setMaterials(r.data)).catch((e) => toast.error(apiError(e)));
    api.get("/purchase-orders").then((r) => setPos(r.data)).catch(() => {});
  }, [filters]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.get("/materials/facets").then((r) => setFacets(r.data)).catch(() => {}); }, []);
  const loadAbcHistory = useCallback(() => {
    api.get("/integrations/abc/orders/history").then((r) => setAbcHistory(r.data.orders || [])).catch(() => setAbcHistory([]));
  }, []);

  const lowCount = materials.filter((m) => m.low_stock).length;

  const createMaterial = async () => {
    if (!form.name.trim()) { toast.error("Name is required"); return; }
    setBusy(true);
    try { await api.post("/materials", { ...form, reorder_threshold: Number(form.reorder_threshold) || 0, quantity_on_hand: Number(form.quantity_on_hand) || 0 }); toast.success("Material added"); setMatOpen(false); setForm({ name: "", category: "", unit: "each", reorder_threshold: 0, quantity_on_hand: 0 }); load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const doAdjust = async () => {
    try { await api.post(`/materials/${adjTarget.id}/adjust`, { delta: Number(adj.delta) || 0, reason: adj.reason, note: adj.note || null }); toast.success("Inventory adjusted"); setAdjOpen(false); load(); }
    catch (e) { toast.error(apiError(e)); }
  };
  const parseCsv = (text) => {
    const lines = text.split(/\r?\n/).filter((l) => l.trim());
    if (!lines.length) return [];
    const headers = lines[0].split(",").map((h) => h.trim().toLowerCase());
    return lines.slice(1).map((line) => {
      const cells = line.split(",");
      const row = {};
      headers.forEach((h, i) => { row[h] = (cells[i] || "").trim(); });
      return row;
    });
  };
  const onCsvFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    const rows = parseCsv(text);
    setCsvRows(rows);
    setCsvAck(false);
    try { const { data } = await api.post("/materials/import/preview", { rows }); setCsvPreview(data); }
    catch (err) { toast.error(apiError(err)); }
  };
  const commitCsv = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/materials/import/commit", { rows: csvRows, confirm_updates: true });
      toast.success(`Imported: ${data.created} created, ${data.updated} updated`);
      setCsvOpen(false); setCsvPreview(null); setCsvRows([]); load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
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
            <TabsTrigger value="abc-orders" data-testid="tab-abc-orders" onClick={loadAbcHistory}>ABC Supply Orders</TabsTrigger>
          </TabsList>

          <TabsContent value="materials" className="mt-6">
            {canManage && <div className="mb-4 flex flex-wrap items-center gap-2">
              <Button onClick={() => setMatOpen(true)} data-testid="add-material-button"><Plus className="h-4 w-4" /> Create custom</Button>
              <Button variant="outline" onClick={() => navigate("/inventory/abc-catalog")} data-testid="abc-catalog-button"><PackageSearch className="h-4 w-4" /> Search supplier catalog</Button>
              <Button variant="outline" onClick={() => { setCsvPreview(null); setCsvRows([]); setCsvOpen(true); }} data-testid="import-csv-button"><Upload className="h-4 w-4" /> Import CSV</Button>
            </div>}
            <div className="mb-4 flex flex-wrap items-center gap-2" data-testid="material-filters">
              <div className="relative w-64"><Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" /><Input value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} placeholder="Search name / SKU / mfr" className="pl-8" data-testid="material-search" /></div>
              <Select value={filters.category} onValueChange={(v) => setFilters({ ...filters, category: v })}><SelectTrigger className="w-40" data-testid="filter-category"><SelectValue placeholder="Category" /></SelectTrigger><SelectContent><SelectItem value="all">All categories</SelectItem>{facets.categories.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent></Select>
              <Select value={filters.manufacturer} onValueChange={(v) => setFilters({ ...filters, manufacturer: v })}><SelectTrigger className="w-40" data-testid="filter-manufacturer"><SelectValue placeholder="Manufacturer" /></SelectTrigger><SelectContent><SelectItem value="all">All manufacturers</SelectItem>{facets.manufacturers.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent></Select>
              <Select value={filters.supplier_id} onValueChange={(v) => setFilters({ ...filters, supplier_id: v })}><SelectTrigger className="w-40" data-testid="filter-supplier"><SelectValue placeholder="Supplier" /></SelectTrigger><SelectContent><SelectItem value="all">All suppliers</SelectItem>{facets.suppliers.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}</SelectContent></Select>
              <Select value={filters.active} onValueChange={(v) => setFilters({ ...filters, active: v })}><SelectTrigger className="w-32" data-testid="filter-active"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All</SelectItem><SelectItem value="active">Active</SelectItem><SelectItem value="inactive">Inactive</SelectItem></SelectContent></Select>
              <Button variant={filters.low_stock ? "default" : "outline"} size="sm" onClick={() => setFilters({ ...filters, low_stock: !filters.low_stock })} data-testid="filter-low-stock"><AlertTriangle className="h-4 w-4" /> Low stock</Button>
            </div>
            <div className="overflow-x-auto rounded-md border border-border bg-white">
              <Table data-testid="materials-table">
                <TableHeader><TableRow><TableHead>Material</TableHead><TableHead>SKU</TableHead><TableHead>Category</TableHead><TableHead>Primary supplier</TableHead><TableHead>Cost</TableHead><TableHead>On hand</TableHead><TableHead>Reserved</TableHead><TableHead>Available</TableHead><TableHead>On order</TableHead><TableHead>Status</TableHead>{canManage && <TableHead />}</TableRow></TableHeader>
                <TableBody>
                  {materials.map((m) => (
                    <TableRow key={m.id} data-testid={`material-row-${m.id}`} className="cursor-pointer hover:bg-slate-50" onClick={() => navigate(`/inventory/materials/${m.id}`)}>
                      <TableCell className="font-medium text-slate-900">{m.name}<ChevronRight className="ml-1 inline h-3.5 w-3.5 text-slate-300" /></TableCell>
                      <TableCell className="text-slate-500 font-mono text-xs">{m.sku || "—"}</TableCell>
                      <TableCell className="text-slate-500">{m.category || "—"}</TableCell>
                      <TableCell className="text-slate-600">{m.primary_supplier_name || "—"}</TableCell>
                      <TableCell className="tabular-nums text-slate-600">{m.primary_supplier_cost != null ? money(m.primary_supplier_cost) : (m.best_known_cost != null ? money(m.best_known_cost) : "—")}</TableCell>
                      <TableCell className="tabular-nums font-medium">{m.on_hand}</TableCell>
                      <TableCell className="tabular-nums text-slate-500">{m.reserved}</TableCell>
                      <TableCell className="tabular-nums font-medium">{m.available}</TableCell>
                      <TableCell className="tabular-nums text-slate-500">{m.on_order}</TableCell>
                      <TableCell>{!m.active ? <Badge variant="secondary" className="bg-slate-100 text-slate-500">Inactive</Badge> : m.low_stock ? <Badge className="bg-amber-50 text-amber-700" variant="secondary" data-testid={`low-badge-${m.id}`}><AlertTriangle className="mr-1 h-3 w-3" /> Low</Badge> : <Badge variant="secondary" className="bg-green-50 text-green-700">OK</Badge>}</TableCell>
                      {canManage && <TableCell><Button size="sm" variant="outline" onClick={(e) => { e.stopPropagation(); setAdjTarget(m); setAdj({ delta: 0, reason: "manual_correction", note: "" }); setAdjOpen(true); }} data-testid={`adjust-${m.id}`}>Adjust</Button></TableCell>}
                    </TableRow>
                  ))}
                  {materials.length === 0 && <TableRow><TableCell colSpan={11} className="text-center text-sm text-slate-400">No materials match.</TableCell></TableRow>}
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
                      {canManage && <TableCell><div className="flex gap-2">
                        {po.integration_provider === "abc_supply" && <Button size="sm" variant="outline" onClick={() => { setAbcPo(po); setAbcOpen(true); }} data-testid={`abc-order-${po.id}`}><Send className="h-4 w-4" /> {po.external_confirmation_number ? "ABC Order" : "Submit to ABC"}</Button>}
                        <Button size="sm" variant="outline" disabled={po.status === "cancelled" || po.status === "received"} onClick={() => { setRecvPo(po); setRecvOpen(true); }} data-testid={`receive-${po.id}`}><PackageCheck className="h-4 w-4" /> Receive</Button>
                      </div></TableCell>}
                    </TableRow>
                  ))}
                  {pos.length === 0 && <TableRow><TableCell colSpan={6} className="text-center text-sm text-slate-400">No purchase orders yet.</TableCell></TableRow>}
                </TableBody>
              </Table>
            </div>
          </TabsContent>

          <TabsContent value="abc-orders" className="mt-6" data-testid="abc-orders-tab">
            <div className="overflow-x-auto rounded-md border border-border bg-white">
              <Table data-testid="abc-orders-table">
                <TableHeader><TableRow><TableHead>Order #</TableHead><TableHead>Confirmation</TableHead><TableHead>PO #</TableHead><TableHead>Status</TableHead><TableHead>Delivery</TableHead><TableHead>Total</TableHead></TableRow></TableHeader>
                <TableBody>
                  {abcHistory.map((o, i) => (
                    <TableRow key={i} data-testid={`abc-order-row-${i}`}>
                      <TableCell className="font-medium text-slate-900">{o.orderNumber || "—"}</TableCell>
                      <TableCell className="text-slate-600">{o.confirmationNumber}</TableCell>
                      <TableCell className="text-slate-600">{o.purchaseOrder || "—"}</TableCell>
                      <TableCell><Badge className="bg-blue-50 text-blue-700" variant="secondary">{o.status}</Badge></TableCell>
                      <TableCell className="text-slate-500">{o.deliveryStatus || "—"}</TableCell>
                      <TableCell className="tabular-nums">{money(o.total || 0)}</TableCell>
                    </TableRow>
                  ))}
                  {abcHistory.length === 0 && <TableRow><TableCell colSpan={6} className="text-center text-sm text-slate-400">No ABC Supply orders yet. Submit an ABC purchase order to see it here.</TableCell></TableRow>}
                </TableBody>
              </Table>
            </div>
          </TabsContent>
        </Tabs>
      </div>

      <Dialog open={matOpen} onOpenChange={setMatOpen}>
        <DialogContent data-testid="material-dialog">
          <DialogHeader><DialogTitle>Add material</DialogTitle><DialogDescription>Add a new material to the inventory catalog.</DialogDescription></DialogHeader>
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
          <DialogHeader><DialogTitle>Adjust — {adjTarget?.name}</DialogTitle><DialogDescription>Record an inventory transaction. Reservations do not reduce physical on-hand.</DialogDescription></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-slate-500">On hand: <span className="font-medium">{adjTarget?.on_hand ?? adjTarget?.quantity_on_hand}</span>. Use a negative number to decrease.</p>
            <div className="space-y-1.5"><Label>Transaction type</Label>
              <Select value={adj.reason} onValueChange={(v) => setAdj({ ...adj, reason: v })}>
                <SelectTrigger data-testid="adjust-reason"><SelectValue /></SelectTrigger>
                <SelectContent>{TXN_TYPES.map((t) => <SelectItem key={t} value={t}>{txnLabel(t)}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5"><Label>Change (+/-)</Label><Input type="number" value={adj.delta} onChange={(e) => setAdj({ ...adj, delta: e.target.value })} data-testid="adjust-delta" /></div>
            <div className="space-y-1.5"><Label>Notes (optional)</Label><Input value={adj.note} onChange={(e) => setAdj({ ...adj, note: e.target.value })} data-testid="adjust-note" /></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setAdjOpen(false)}>Cancel</Button><Button onClick={doAdjust} data-testid="adjust-save">Apply</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={csvOpen} onOpenChange={setCsvOpen}>
        <DialogContent data-testid="csv-dialog" className="max-w-2xl">
          <DialogHeader><DialogTitle>Import materials (CSV)</DialogTitle><DialogDescription>Columns: sku, name, category, unit, manufacturer, description, reorder_threshold, quantity_on_hand. Matching SKUs are updated; new rows are created. Updates are shown below and must be confirmed.</DialogDescription></DialogHeader>
          <div className="space-y-3">
            <input type="file" accept=".csv,text/csv" onChange={onCsvFile} data-testid="csv-file" className="block text-sm" />
            {csvPreview && (
              <div className="rounded-md border border-border" data-testid="csv-preview">
                <div className="flex gap-4 border-b border-border p-2 text-sm"><span className="text-green-700" data-testid="csv-create-count">Create: {csvPreview.create_count}</span><span className="text-amber-700" data-testid="csv-update-count">Update: {csvPreview.update_count}</span><span className="text-red-600" data-testid="csv-error-count">Errors: {csvPreview.error_count}</span></div>
                <div className="max-h-64 overflow-y-auto">
                  <Table><TableHeader><TableRow><TableHead>#</TableHead><TableHead>Action</TableHead><TableHead>SKU</TableHead><TableHead>Name</TableHead><TableHead>Changes / errors</TableHead></TableRow></TableHeader>
                    <TableBody>{csvPreview.rows.map((r) => (
                      <TableRow key={r.row_number} data-testid={`csv-row-${r.row_number}`}>
                        <TableCell>{r.row_number}</TableCell>
                        <TableCell><Badge variant="secondary" className={r.action === "create" ? "bg-green-50 text-green-700" : r.action === "update" ? "bg-amber-50 text-amber-700" : "bg-red-50 text-red-600"}>{r.action}</Badge></TableCell>
                        <TableCell className="font-mono text-xs">{r.sku || "—"}</TableCell>
                        <TableCell>{r.name || "—"}</TableCell>
                        <TableCell className="text-xs text-slate-500">{r.errors?.length ? r.errors.join("; ") : Object.keys(r.changes || {}).map((k) => `${k}: ${r.changes[k].from ?? "∅"}→${r.changes[k].to}`).join(", ") || "—"}</TableCell>
                      </TableRow>
                    ))}</TableBody>
                  </Table>
                </div>
              </div>
            )}
          </div>
          <DialogFooter className="flex-col items-stretch gap-2 sm:flex-col sm:items-stretch">
            {csvPreview && csvPreview.update_count > 0 && (
              <label className="flex items-center gap-2 text-sm text-amber-700" data-testid="csv-confirm-updates">
                <input type="checkbox" checked={csvAck} onChange={(e) => setCsvAck(e.target.checked)} data-testid="csv-confirm-updates-checkbox" />
                I understand {csvPreview.update_count} existing material{csvPreview.update_count === 1 ? "" : "s"} will be updated.
              </label>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setCsvOpen(false)}>Cancel</Button>
              <Button onClick={commitCsv} disabled={busy || !csvPreview || (csvPreview.create_count + csvPreview.update_count === 0) || (csvPreview.update_count > 0 && !csvAck)} data-testid="csv-commit">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : `Confirm & import`}</Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <PODialog open={poOpen} onOpenChange={setPoOpen} onCreated={load} />
      <ReceiveDialog open={recvOpen} onOpenChange={setRecvOpen} po={recvPo} onReceived={load} />
      <AbcOrderPanel open={abcOpen} onOpenChange={setAbcOpen} po={abcPo} onChanged={load} />
    </div>
  );
}

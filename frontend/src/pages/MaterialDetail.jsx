import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { money, shortDate } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ArrowLeft, Loader2, Star, Pencil, SlidersHorizontal, Power, Trash2, Sparkles } from "lucide-react";

const MANAGE = ["owner", "administrator", "office"];
const TXN_TYPES = ["initial_inventory", "receive_po", "job_reservation", "job_issue", "job_return", "supplier_return", "transfer", "damage", "waste", "loss", "cycle_count", "manual_correction"];
const txnLabel = (t) => (t || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const costSourceLabel = (s) => ({ preferred_supplier: "Preferred Supplier", best_known_cost: "Best Known Cost", standard_cost: "Standard Cost", mwac: "Inventory Avg (MWAC)" }[s] || "—");

function Stat({ label, value, accent }) {
  return (
    <div className="rounded-md border border-border bg-white p-3" data-testid={`qty-${label.toLowerCase().replace(/ /g, "-")}`}>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-xl font-semibold tabular-nums ${accent || "text-slate-900"}`}>{value}</div>
    </div>
  );
}

function Sparkline({ points }) {
  if (!points || points.length < 2) return null;
  const w = 240, h = 40, pad = 4;
  const min = Math.min(...points), max = Math.max(...points);
  const span = max - min || 1;
  const step = (w - pad * 2) / (points.length - 1);
  const coords = points.map((v, i) => [pad + i * step, h - pad - ((v - min) / span) * (h - pad * 2)]);
  const d = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c[0].toFixed(1)},${c[1].toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-10 w-full" preserveAspectRatio="none" data-testid="price-sparkline">
      <path d={d} fill="none" stroke="#4f46e5" strokeWidth="1.5" />
      {coords.map((c, i) => <circle key={i} cx={c[0]} cy={c[1]} r="1.8" fill="#4f46e5" />)}
    </svg>
  );
}

export default function MaterialDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canManage = MANAGE.includes(user?.role);
  const [d, setD] = useState(null);
  const [balances, setBalances] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [form, setForm] = useState({});
  const [adjOpen, setAdjOpen] = useState(false);
  const [adj, setAdj] = useState({ delta: 0, reason: "manual_correction", note: "" });
  const [suppliers, setSuppliers] = useState([]);
  const [supOpen, setSupOpen] = useState(false);
  const [supForm, setSupForm] = useState({});
  const [supHistory, setSupHistory] = useState([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/materials/${id}/detail`); setD(data);
      const b = await api.get("/inventory/balances", { params: { material_id: id } }); setBalances(b.data.balances);
    }
    catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  }, [id]);
  useEffect(() => { load(); api.get("/suppliers", { params: { active: true } }).then((r) => setSuppliers(r.data)).catch(() => {}); }, [load]);

  const makePreferred = async (smId) => {
    try { await api.post(`/materials/${id}/suppliers/${smId}/prefer`); toast.success("Preferred supplier updated"); load(); }
    catch (e) { toast.error(apiError(e)); }
  };

  const openEdit = () => {
    const m = d.material;
    setForm({
      name: m.name || "", sku: m.sku || "", category: m.category || "", unit: m.unit || "each",
      manufacturer: m.manufacturer || "", brand: m.brand || "", description: m.description || "",
      reorder_threshold: m.reorder_threshold ?? 0,
      standard_cost: m.standard_cost ?? "", default_sell_price: m.default_sell_price ?? "",
    });
    setEditOpen(true);
  };
  const saveEdit = async () => {
    if (!form.name.trim()) { toast.error("Name is required"); return; }
    setBusy(true);
    try {
      await api.patch(`/materials/${id}`, {
        name: form.name.trim(), sku: form.sku || null, category: form.category || null, unit: form.unit || "each",
        manufacturer: form.manufacturer || null, brand: form.brand || null, description: form.description || null,
        reorder_threshold: Number(form.reorder_threshold) || 0,
        standard_cost: form.standard_cost === "" ? null : Number(form.standard_cost),
        default_sell_price: form.default_sell_price === "" ? null : Number(form.default_sell_price),
      });
      toast.success("Material updated"); setEditOpen(false); load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const toggleActive = async () => {
    const wasActive = d.material.active;
    try {
      await api.patch(`/materials/${id}`, { active: !wasActive });
      if (wasActive) {
        toast.success("Material deactivated", { action: { label: "Undo", onClick: async () => {
          try { await api.patch(`/materials/${id}`, { active: true }); toast.success("Reactivated"); load(); }
          catch (e) { toast.error(apiError(e)); }
        } } });
      } else { toast.success("Material reactivated"); }
      load();
    } catch (e) { toast.error(apiError(e)); }
  };
  const openAddSupplier = () => { setSupHistory([]); setSupForm({ sm_id: null, supplier_id: "", supplier_item_number: "", supplier_uom: "", current_cost: "" }); setSupOpen(true); };
  const openEditSupplier = (s) => {
    setSupHistory([]);
    setSupForm({ sm_id: s.id, supplier_id: s.supplier_id || "", supplier_name: s.supplier_name, supplier_item_number: s.supplier_item_number || "", supplier_uom: s.supplier_uom || "", current_cost: s.current_cost ?? "" });
    setSupOpen(true);
    api.get(`/supplier-materials/${s.id}/price-history`).then((r) => setSupHistory(r.data || [])).catch(() => setSupHistory([]));
  };
  const saveSupplier = async () => {
    if (!supForm.sm_id && !supForm.supplier_id) { toast.error("Select a supplier"); return; }
    setBusy(true);
    try {
      const body = { supplier_item_number: supForm.supplier_item_number || null, supplier_uom: supForm.supplier_uom || null,
        current_cost: supForm.current_cost === "" ? null : Number(supForm.current_cost) };
      if (supForm.sm_id) await api.patch(`/supplier-materials/${supForm.sm_id}`, body);
      else await api.post(`/supplier-materials`, { material_id: id, supplier_id: supForm.supplier_id, ...body });
      toast.success("Supplier pricing saved"); setSupOpen(false); load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const doAdjust = async () => {
    setBusy(true);
    try { await api.post(`/materials/${id}/adjust`, { delta: Number(adj.delta) || 0, reason: adj.reason, note: adj.note || null }); toast.success("Inventory adjusted"); setAdjOpen(false); setAdj({ delta: 0, reason: "manual_correction", note: "" }); load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const doDelete = async () => {
    if (!window.confirm(`Delete "${d.material.name}"? This cannot be undone.`)) return;
    try { await api.delete(`/materials/${id}`); toast.success("Material deleted"); navigate("/inventory"); }
    catch (e) { toast.error(apiError(e)); }
  };
  const resetToAuto = async () => {
    try { await api.patch(`/materials/${id}`, { default_sell_price: null }); toast.success("Price reset — now calculated from the Price Book"); load(); }
    catch (e) { toast.error(apiError(e)); }
  };

  if (loading || !d) return <div className="p-10 text-center text-slate-400" data-testid="material-detail-loading"><Loader2 className="mx-auto h-6 w-6 animate-spin" /></div>;
  const m = d.material; const q = d.quantities;

  return (
    <div>
      <PageHeader title={m.name} description={m.category || "Material"} testid="page-material-detail" />
      <div className="p-6 sm:p-8 space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Button variant="ghost" size="sm" onClick={() => navigate("/inventory")} data-testid="detail-back"><ArrowLeft className="h-4 w-4" /> Inventory</Button>
          {canManage && (
            <div className="flex flex-wrap items-center gap-2" data-testid="material-actions">
              <Button size="sm" variant="outline" onClick={openEdit} data-testid="edit-material-button"><Pencil className="h-4 w-4" /> Edit</Button>
              <Button size="sm" variant="outline" onClick={() => setAdjOpen(true)} data-testid="adjust-inventory-button"><SlidersHorizontal className="h-4 w-4" /> Adjust inventory</Button>
              <Button size="sm" variant="outline" onClick={toggleActive} data-testid="toggle-active-button"><Power className="h-4 w-4" /> {m.active ? "Deactivate" : "Reactivate"}</Button>
              <Button size="sm" variant="outline" className="text-red-600 hover:text-red-700" onClick={doDelete} data-testid="delete-material-button"><Trash2 className="h-4 w-4" /> Delete</Button>
            </div>
          )}
        </div>

        {/* Overview */}
        <section className="rounded-md border border-border bg-white p-4" data-testid="detail-overview">
          <h3 className="mb-3 text-sm font-semibold text-slate-700">Overview</h3>
          <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm sm:grid-cols-3">
            <div><span className="text-slate-400">SKU</span><div className="font-mono">{m.sku || "—"}</div></div>
            <div><span className="text-slate-400">Manufacturer</span><div>{m.manufacturer || "—"}</div></div>
            <div><span className="text-slate-400">Brand</span><div>{m.brand || "—"}</div></div>
            <div><span className="text-slate-400">Base unit</span><div>{m.unit}</div></div>
            <div><span className="text-slate-400">Reorder at</span><div className="tabular-nums">{m.reorder_threshold}</div></div>
            <div><span className="text-slate-400">Status</span><div>{m.active ? "Active" : "Inactive"}</div></div>
            <div className="col-span-2"><span className="text-slate-400">Best known cost</span> <span className="font-medium" data-testid="best-known-cost">{m.best_known_cost != null ? money(m.best_known_cost) : "—"}</span> <span className="text-xs text-slate-400">(lowest active supplier cost — not the preferred supplier)</span></div>
          </div>
        </section>

        {/* Cost & Price */}
        <section className="grid gap-3 sm:grid-cols-2" data-testid="detail-cost-price">
          {canManage && <div className="rounded-md border border-border bg-white p-4">
            <div className="text-xs uppercase tracking-wide text-slate-400">Cost</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900" data-testid="detail-effective-cost">{m.effective_cost != null ? money(m.effective_cost) : "—"}</div>
            <div className="mt-1 text-xs text-slate-500" data-testid="detail-cost-source">
              {m.effective_cost == null ? "Missing cost basis"
                : `Source: ${costSourceLabel(m.effective_cost_source)}${m.effective_cost_supplier_name ? ` — ${m.effective_cost_supplier_name}` : ""}`}
            </div>
          </div>}
          <div className="rounded-md border border-border bg-white p-4">
            <div className="flex items-center gap-2"><div className="text-xs uppercase tracking-wide text-slate-400">Price</div>{m.price_is_custom && <Badge variant="secondary" className="bg-amber-100 text-amber-700" data-testid="price-custom-badge">Custom</Badge>}</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums text-indigo-700" data-testid="detail-effective-price">{m.effective_price != null ? money(m.effective_price) : "—"}</div>
            <div className="mt-1 text-xs text-slate-500" data-testid="detail-price-source">
              {m.price_is_custom
                ? "Custom price — manual override (ignores Price Book)"
                : (m.effective_price == null
                  ? (!canManage ? "Price unavailable" : (m.effective_cost == null ? "No cost basis — price unavailable" : (m.price_book_id ? "No matching price rule" : "No default price book set")))
                  : `Price Book: ${m.price_book_name || "—"}${m.matched_rule_label ? ` · Rule: ${m.matched_rule_label}` : ""}`)}
            </div>
            {canManage && m.price_is_custom && (
              <Button size="sm" variant="outline" className="mt-2" onClick={resetToAuto} data-testid="reset-price-auto"><Sparkles className="h-3.5 w-3.5" /> Use Price Book price</Button>
            )}
          </div>
        </section>

        {/* Inventory quantities */}
        <section data-testid="detail-inventory">
          <h3 className="mb-3 text-sm font-semibold text-slate-700">Inventory</h3>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="On Hand" value={q.on_hand} />
            <Stat label="Reserved" value={q.reserved} accent="text-amber-600" />
            <Stat label="Available" value={q.available} accent={q.available < 0 ? "text-red-600" : "text-green-700"} />
            <Stat label="On Order" value={q.on_order} accent="text-blue-600" />
            <Stat label="Required" value={q.required} />
            <Stat label="Projected" value={q.projected} accent={q.projected < 0 ? "text-red-600" : "text-slate-900"} />
          </div>
          <div className="mt-4 rounded-md border border-border bg-white p-4" data-testid="detail-by-location">
            <h4 className="mb-2 text-xs font-semibold uppercase text-slate-400">Inventory by location</h4>
            <div className="max-w-sm space-y-1 text-sm">
              {balances.length === 0 ? <p className="text-slate-400">No stock on hand at any location.</p> : balances.map((b) => (
                <div key={b.location_id} className="flex items-center justify-between" data-testid={`loc-balance-${b.location_id}`}>
                  <span className="text-slate-700">{b.location_name} <span className="text-xs text-slate-400">({b.location_type})</span></span>
                  <span className="tabular-nums">{b.quantity_on_hand}</span>
                </div>
              ))}
              <div className="mt-1 flex items-center justify-between border-t border-border pt-1 font-semibold">
                <span>Total On Hand</span><span className="tabular-nums" data-testid="loc-balance-total">{Math.round(balances.reduce((s, b) => s + b.quantity_on_hand, 0) * 1000) / 1000}</span>
              </div>
            </div>
          </div>
        </section>

        {/* Supplier pricing */}
        <section className="rounded-md border border-border bg-white" data-testid="detail-suppliers">
          <div className="flex items-center justify-between border-b border-border p-3">
            <h3 className="text-sm font-semibold text-slate-700">Supplier pricing</h3>
            {canManage && <Button size="sm" variant="outline" onClick={openAddSupplier} data-testid="add-supplier-button"><Pencil className="h-3.5 w-3.5" /> Add supplier</Button>}
          </div>
          <Table>
            <TableHeader><TableRow><TableHead>Supplier</TableHead><TableHead>Item #</TableHead><TableHead>UoM</TableHead><TableHead>Cost</TableHead><TableHead>Availability</TableHead><TableHead>Preferred</TableHead>{canManage && <TableHead />}</TableRow></TableHeader>
            <TableBody>
              {d.suppliers.map((s) => (
                <TableRow key={s.id} data-testid={`supplier-row-${s.id}`}>
                  <TableCell className="font-medium">{s.supplier_name || s.integration_provider || "—"}</TableCell>
                  <TableCell className="font-mono text-xs">{s.supplier_item_number || "—"}</TableCell>
                  <TableCell>{s.supplier_uom || "—"}</TableCell>
                  <TableCell className="tabular-nums">{s.current_cost != null ? money(s.current_cost) : "—"}</TableCell>
                  <TableCell className="text-slate-500">{s.availability_status || "—"}</TableCell>
                  <TableCell>
                    {s.is_preferred
                      ? <Badge className="bg-indigo-50 text-indigo-700" variant="secondary" data-testid={`preferred-${s.id}`}><Star className="mr-1 h-3 w-3 fill-indigo-500 text-indigo-500" /> Preferred</Badge>
                      : (canManage && <Button size="sm" variant="outline" onClick={() => makePreferred(s.id)} data-testid={`prefer-${s.id}`}>Set preferred</Button>)}
                  </TableCell>
                  {canManage && <TableCell><Button size="sm" variant="ghost" onClick={() => openEditSupplier(s)} data-testid={`edit-supplier-${s.id}`}><Pencil className="h-3.5 w-3.5" /></Button></TableCell>}
                </TableRow>
              ))}
              {d.suppliers.length === 0 && <TableRow><TableCell colSpan={canManage ? 7 : 6} className="text-center text-sm text-slate-400">No supplier mappings.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </section>

        {/* Open POs */}
        <section className="rounded-md border border-border bg-white" data-testid="detail-open-pos">
          <h3 className="border-b border-border p-3 text-sm font-semibold text-slate-700">Open purchase orders</h3>
          <Table>
            <TableHeader><TableRow><TableHead>PO #</TableHead><TableHead>Status</TableHead><TableHead>Ordered</TableHead><TableHead>Received</TableHead><TableHead>Remaining</TableHead><TableHead>Unit cost</TableHead></TableRow></TableHeader>
            <TableBody>
              {d.open_po_lines.map((l, i) => (
                <TableRow key={i} data-testid={`open-po-${i}`}><TableCell className="font-medium">{l.po_number}</TableCell><TableCell><Badge variant="secondary">{l.status}</Badge></TableCell><TableCell className="tabular-nums">{l.quantity}</TableCell><TableCell className="tabular-nums">{l.received_quantity}</TableCell><TableCell className="tabular-nums font-medium">{l.remaining}</TableCell><TableCell className="tabular-nums">{money(l.unit_cost)}</TableCell></TableRow>
              ))}
              {d.open_po_lines.length === 0 && <TableRow><TableCell colSpan={6} className="text-center text-sm text-slate-400">No open POs.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </section>

        {/* Jobs */}
        <section className="rounded-md border border-border bg-white" data-testid="detail-jobs">
          <h3 className="border-b border-border p-3 text-sm font-semibold text-slate-700">Jobs requiring this material</h3>
          <Table>
            <TableHeader><TableRow><TableHead>Job</TableHead><TableHead>Planned qty</TableHead></TableRow></TableHeader>
            <TableBody>
              {d.jobs.map((j, i) => (<TableRow key={i} data-testid={`job-req-${i}`}><TableCell className="font-medium">{j.job_title}</TableCell><TableCell className="tabular-nums">{j.planned_quantity}</TableCell></TableRow>))}
              {d.jobs.length === 0 && <TableRow><TableCell colSpan={2} className="text-center text-sm text-slate-400">No active jobs require this material.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </section>

        {/* Transaction history */}
        <section className="rounded-md border border-border bg-white" data-testid="detail-transactions">
          <h3 className="border-b border-border p-3 text-sm font-semibold text-slate-700">Transaction history</h3>
          <Table>
            <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Type</TableHead><TableHead>Change</TableHead><TableHead>By</TableHead><TableHead>Reference</TableHead><TableHead>Notes</TableHead></TableRow></TableHeader>
            <TableBody>
              {d.transactions.map((t) => (
                <TableRow key={t.id} data-testid={`txn-${t.id}`}>
                  <TableCell className="text-slate-500">{shortDate(t.created_at)}</TableCell>
                  <TableCell><Badge variant="secondary">{txnLabel(t.txn_type)}</Badge></TableCell>
                  <TableCell className={`tabular-nums font-medium ${t.delta < 0 ? "text-red-600" : "text-green-700"}`}>{t.delta > 0 ? "+" : ""}{t.delta}</TableCell>
                  <TableCell className="text-slate-500">{t.created_by || "—"}</TableCell>
                  <TableCell className="text-xs text-slate-400">{t.po_id ? `PO ${t.po_id.slice(0, 8)}` : t.job_id ? `Job ${t.job_id.slice(0, 8)}` : "—"}</TableCell>
                  <TableCell className="text-slate-500">{t.note || "—"}</TableCell>
                </TableRow>
              ))}
              {d.transactions.length === 0 && <TableRow><TableCell colSpan={6} className="text-center text-sm text-slate-400">No transactions yet.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </section>
      </div>

      {/* Edit dialog */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="max-w-lg" data-testid="edit-material-dialog">
          <DialogHeader><DialogTitle>Edit material</DialogTitle><DialogDescription>Changing details here never alters past estimates, quotes, POs, or job costs.</DialogDescription></DialogHeader>
          <div className="max-h-[70vh] space-y-3 overflow-y-auto pr-1">
            <div className="space-y-1.5"><Label>Name</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="edit-name" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label>SKU</Label><Input value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} data-testid="edit-sku" /></div>
              <div className="space-y-1.5"><Label>Category</Label><Input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} data-testid="edit-category" /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label>Manufacturer</Label><Input value={form.manufacturer} onChange={(e) => setForm({ ...form, manufacturer: e.target.value })} data-testid="edit-manufacturer" /></div>
              <div className="space-y-1.5"><Label>Brand</Label><Input value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })} data-testid="edit-brand" /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label>Unit</Label><Input value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} placeholder="bundle / roll / each" data-testid="edit-unit" /></div>
              <div className="space-y-1.5"><Label>Reorder threshold</Label><Input type="number" value={form.reorder_threshold} onChange={(e) => setForm({ ...form, reorder_threshold: e.target.value })} data-testid="edit-threshold" /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label>Cost</Label><Input type="number" value={form.standard_cost} onChange={(e) => setForm({ ...form, standard_cost: e.target.value })} placeholder="—" data-testid="edit-standard-cost" /></div>
              <div className="space-y-1.5"><Label>Price</Label><Input type="number" value={form.default_sell_price} onChange={(e) => setForm({ ...form, default_sell_price: e.target.value })} placeholder="Auto from Price Book" data-testid="edit-sell-price" /></div>
            </div>
            <p className="text-xs text-slate-400 -mt-1">Leave <b>Price</b> blank to auto-calculate it from the Price Book applied to Cost. Entering a Price overrides the Price Book and is flagged <b>Custom</b>.</p>
            <div className="space-y-1.5"><Label>Description</Label><Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} data-testid="edit-description" /></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setEditOpen(false)}>Cancel</Button><Button onClick={saveEdit} disabled={busy} data-testid="edit-save">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save changes"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Adjust dialog */}
      <Dialog open={adjOpen} onOpenChange={setAdjOpen}>
        <DialogContent data-testid="detail-adjust-dialog">
          <DialogHeader><DialogTitle>Adjust — {m.name}</DialogTitle><DialogDescription>Record an inventory transaction. Reservations do not reduce physical on-hand.</DialogDescription></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-slate-500">On hand: <span className="font-medium">{q.on_hand}</span>. Use a negative number to decrease.</p>
            <div className="space-y-1.5"><Label>Transaction type</Label>
              <Select value={adj.reason} onValueChange={(v) => setAdj({ ...adj, reason: v })}>
                <SelectTrigger data-testid="detail-adjust-reason"><SelectValue /></SelectTrigger>
                <SelectContent>{TXN_TYPES.map((t) => <SelectItem key={t} value={t}>{txnLabel(t)}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5"><Label>Change (+/-)</Label><Input type="number" value={adj.delta} onChange={(e) => setAdj({ ...adj, delta: e.target.value })} data-testid="detail-adjust-delta" /></div>
            <div className="space-y-1.5"><Label>Notes (optional)</Label><Input value={adj.note} onChange={(e) => setAdj({ ...adj, note: e.target.value })} data-testid="detail-adjust-note" /></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setAdjOpen(false)}>Cancel</Button><Button onClick={doAdjust} disabled={busy} data-testid="detail-adjust-save">Apply</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Supplier pricing dialog */}
      <Dialog open={supOpen} onOpenChange={setSupOpen}>
        <DialogContent data-testid="supplier-dialog">
          <DialogHeader><DialogTitle>{supForm.sm_id ? `Edit supplier — ${supForm.supplier_name || ""}` : "Add supplier pricing"}</DialogTitle><DialogDescription>Supplier cost feeds the material's effective Cost (and Price via the Default Price Book).</DialogDescription></DialogHeader>
          <div className="space-y-3">
            {!supForm.sm_id && (
              <div className="space-y-1.5"><Label>Supplier</Label>
                <Select value={supForm.supplier_id || ""} onValueChange={(v) => setSupForm({ ...supForm, supplier_id: v })}>
                  <SelectTrigger data-testid="supplier-select"><SelectValue placeholder="Select supplier" /></SelectTrigger>
                  <SelectContent className="max-h-64">{suppliers.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label>Supplier item #</Label><Input value={supForm.supplier_item_number || ""} onChange={(e) => setSupForm({ ...supForm, supplier_item_number: e.target.value })} data-testid="supplier-item-number" /></div>
              <div className="space-y-1.5"><Label>UoM</Label><Input value={supForm.supplier_uom || ""} onChange={(e) => setSupForm({ ...supForm, supplier_uom: e.target.value })} data-testid="supplier-uom" /></div>
            </div>
            <div className="space-y-1.5"><Label>Unit cost</Label><Input type="number" value={supForm.current_cost} onChange={(e) => setSupForm({ ...supForm, current_cost: e.target.value })} placeholder="—" data-testid="supplier-cost" /></div>
            {supForm.sm_id && (
              <div className="rounded-md border border-border bg-slate-50 p-3" data-testid="supplier-price-history">
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Cost history</div>
                {supHistory.length === 0 ? <p className="text-xs text-slate-400">No recorded cost changes yet.</p> : (
                  <>
                    <Sparkline points={supHistory.map((h) => h.cost).filter((c) => c != null).reverse()} />
                    <div className="mt-2 max-h-32 space-y-1 overflow-y-auto">
                      {supHistory.map((h) => (
                        <div key={h.id} className="flex items-center justify-between text-xs" data-testid={`price-point-${h.id}`}>
                          <span className="text-slate-500">{shortDate(h.created_at)}{h.source ? ` · ${h.source}` : ""}</span>
                          <span className="font-medium tabular-nums text-slate-700">{h.cost != null ? money(h.cost) : "—"}</span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setSupOpen(false)}>Cancel</Button><Button onClick={saveSupplier} disabled={busy} data-testid="supplier-save">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

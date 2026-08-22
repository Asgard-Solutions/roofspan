import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { money } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Search, Plus, Loader2, Building2, Star } from "lucide-react";

const MANAGE = ["owner", "administrator", "office"];
const empty = { name: "", supplier_type: "distributor", account_number: "", contact_name: "", sales_rep: "", phone: "", email: "", ordering_email: "", website: "", payment_terms: "", default_branch: "", delivery_terms: "", notes: "" };

function PriceTag({ status, provider, updatedAt }) {
  const t = updatedAt ? new Date(updatedAt).toLocaleDateString() : null;
  const s = (status || "").toLowerCase();
  let label = null, cls = "bg-slate-100 text-slate-600";
  if (s === "priced" || s === "live") { label = "Live"; cls = "bg-green-50 text-green-700"; }
  else if (s === "cached") { label = "Cached"; cls = "bg-blue-50 text-blue-700"; }
  else if (s === "stale") { label = "Stale"; cls = "bg-amber-50 text-amber-700"; }
  else if (s === "unavailable") { label = "Unavailable"; cls = "bg-amber-50 text-amber-700"; }
  else if (s === "manual" || provider == null || provider === "manual") { label = "Manual"; }
  else if (provider) { label = "Cached"; cls = "bg-blue-50 text-blue-700"; }
  if (!label) return <span className="text-xs text-slate-300">—</span>;
  return <Badge variant="secondary" className={cls} title={t ? `Updated ${t}` : ""}>{label}{t ? ` · ${t}` : ""}</Badge>;
}

export default function Suppliers() {
  const { user } = useAuth();
  const canManage = MANAGE.includes(user?.role);
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState("");
  const [activeOnly, setActiveOnly] = useState(true);
  const [loading, setLoading] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [editing, setEditing] = useState(null);
  const [detail, setDetail] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = {}; if (q) p.q = q; if (activeOnly) p.active = true;
      const { data } = await api.get("/suppliers", { params: p });
      setRows(data);
    } catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  }, [q, activeOnly]);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    try {
      if (editing) { await api.patch(`/suppliers/${editing}`, form); toast.success("Supplier updated"); }
      else { await api.post("/suppliers", form); toast.success("Supplier added"); }
      setFormOpen(false); setForm(empty); setEditing(null); load();
    } catch (e) { toast.error(apiError(e)); }
  };
  const toggleActive = async (s) => {
    try { await api.post(`/suppliers/${s.id}/active?active=${!s.active}`); toast.success(s.active ? "Deactivated" : "Reactivated"); load(); }
    catch (e) { toast.error(apiError(e)); }
  };
  const openEdit = (s) => { setEditing(s.id); setForm({ ...empty, ...s }); setFormOpen(true); };
  const openAdd = () => { setEditing(null); setForm(empty); setFormOpen(true); };
  const openDetail = async (s) => {
    try { const { data } = await api.get(`/suppliers/${s.id}`); setDetail(data); } catch (e) { toast.error(apiError(e)); }
  };

  const F = (k, label, type = "text") => (
    <div className="space-y-1"><Label className="text-xs">{label}</Label><Input type={type} value={form[k] ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} data-testid={`supplier-${k}`} /></div>
  );

  return (
    <div>
      <PageHeader title="Suppliers" description="Manage supplier accounts, terms, and integrations." testid="page-suppliers" />
      <div className="p-6 sm:p-8">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {canManage && <Button onClick={openAdd} data-testid="add-supplier-button"><Plus className="h-4 w-4" /> Add manual supplier</Button>}
          <div className="relative w-64"><Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search suppliers" className="pl-8" data-testid="supplier-search" /></div>
          <Button variant={activeOnly ? "default" : "outline"} size="sm" onClick={() => setActiveOnly(!activeOnly)} data-testid="supplier-active-filter">{activeOnly ? "Active only" : "All"}</Button>
        </div>
        <div className="rounded-md border border-border bg-white">
          <Table data-testid="suppliers-table">
            <TableHeader><TableRow><TableHead>Supplier</TableHead><TableHead>Type</TableHead><TableHead>Integration</TableHead><TableHead>Terms</TableHead><TableHead>Status</TableHead>{canManage && <TableHead />}</TableRow></TableHeader>
            <TableBody>
              {rows.map((s) => (
                <TableRow key={s.id} data-testid={`supplier-row-${s.id}`} className="cursor-pointer hover:bg-slate-50" onClick={() => openDetail(s)}>
                  <TableCell className="font-medium text-slate-900"><Building2 className="mr-1 inline h-3.5 w-3.5 text-slate-400" />{s.name}</TableCell>
                  <TableCell className="text-slate-500">{s.supplier_type || "—"}</TableCell>
                  <TableCell>{s.integration_provider ? <Badge className="bg-blue-50 text-blue-700" variant="secondary">{s.integration_provider} · {s.capabilities?.length || 0} caps</Badge> : <Badge variant="secondary" className="bg-slate-100 text-slate-500">Manual</Badge>}</TableCell>
                  <TableCell className="text-slate-500">{s.payment_terms || "—"}</TableCell>
                  <TableCell>{s.active ? <Badge className="bg-green-50 text-green-700" variant="secondary">Active</Badge> : <Badge variant="secondary" className="bg-slate-100 text-slate-500">Inactive</Badge>}</TableCell>
                  {canManage && <TableCell className="text-right" onClick={(e) => e.stopPropagation()}><Button size="sm" variant="outline" onClick={() => openEdit(s)} data-testid={`edit-supplier-${s.id}`}>Edit</Button> <Button size="sm" variant="ghost" onClick={() => toggleActive(s)} data-testid={`toggle-supplier-${s.id}`}>{s.active ? "Deactivate" : "Reactivate"}</Button></TableCell>}
                </TableRow>
              ))}
              {!loading && rows.length === 0 && <TableRow><TableCell colSpan={6} className="py-8 text-center text-sm text-slate-400">No suppliers found.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
      </div>

      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent className="max-w-2xl" data-testid="supplier-form">
          <DialogHeader><DialogTitle>{editing ? "Edit supplier" : "Add manual supplier"}</DialogTitle><DialogDescription>Manual suppliers use stored pricing and manual ordering.</DialogDescription></DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            {F("name", "Name")}{F("supplier_type", "Type")}{F("account_number", "Account #")}{F("sales_rep", "Sales rep")}
            {F("contact_name", "Contact")}{F("phone", "Phone")}{F("email", "Email")}{F("ordering_email", "Ordering email")}
            {F("website", "Website")}{F("payment_terms", "Payment terms")}{F("default_branch", "Default branch")}{F("delivery_terms", "Delivery terms")}
            <div className="col-span-2">{F("notes", "Notes")}</div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setFormOpen(false)}>Cancel</Button><Button onClick={save} disabled={!form.name} data-testid="supplier-save">{editing ? "Save" : "Add"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto" data-testid="supplier-detail">
          <DialogHeader><DialogTitle>{detail?.supplier?.name}</DialogTitle><DialogDescription>{detail?.supplier?.integration_provider || "Manual supplier"} · {detail?.supplier?.integration_status}</DialogDescription></DialogHeader>
          {detail && <div className="space-y-5 text-sm">
            <div>
              <div className="mb-1.5 font-medium text-slate-700">Overview</div>
              <div className="grid grid-cols-2 gap-x-8 gap-y-1.5 sm:grid-cols-3">
                <div><span className="block text-xs text-slate-400">Type</span> {detail.supplier.supplier_type || "—"}</div>
                <div><span className="block text-xs text-slate-400">Account #</span> {detail.supplier.account_number || "—"}</div>
                <div><span className="block text-xs text-slate-400">Sales rep</span> {detail.supplier.sales_rep || "—"}</div>
                <div><span className="block text-xs text-slate-400">Contact</span> {detail.supplier.contact_name || "—"}</div>
                <div><span className="block text-xs text-slate-400">Phone</span> {detail.supplier.phone || "—"}</div>
                <div><span className="block text-xs text-slate-400">Email</span> {detail.supplier.email || "—"}</div>
                <div><span className="block text-xs text-slate-400">Ordering email</span> {detail.supplier.ordering_email || "—"}</div>
                <div><span className="block text-xs text-slate-400">Website</span> {detail.supplier.website || "—"}</div>
                <div><span className="block text-xs text-slate-400">Payment terms</span> {detail.supplier.payment_terms || "—"}</div>
                <div><span className="block text-xs text-slate-400">Default branch</span> {detail.supplier.default_branch || "—"}</div>
                <div><span className="block text-xs text-slate-400">Delivery terms</span> {detail.supplier.delivery_terms || "—"}</div>
                <div><span className="block text-xs text-slate-400">Minimum order</span> {detail.supplier.minimum_order != null ? money(detail.supplier.minimum_order) : "—"}</div>
                <div className="col-span-2 sm:col-span-3"><span className="block text-xs text-slate-400">Capabilities</span> {(detail.supplier.capabilities || []).join(", ") || "manual"}</div>
                {detail.supplier.freight_notes && <div className="col-span-2 sm:col-span-3"><span className="block text-xs text-slate-400">Freight notes</span> {detail.supplier.freight_notes}</div>}
                {detail.supplier.tax_notes && <div className="col-span-2 sm:col-span-3"><span className="block text-xs text-slate-400">Tax notes</span> {detail.supplier.tax_notes}</div>}
                {detail.supplier.notes && <div className="col-span-2 sm:col-span-3"><span className="block text-xs text-slate-400">Notes</span> {detail.supplier.notes}</div>}
              </div>
            </div>

            <div>
              <div className="mb-1 font-medium text-slate-700">Products ({detail.products.length})</div>
              <div className="max-h-56 overflow-y-auto rounded-md border border-border">
                <Table><TableHeader><TableRow><TableHead>Material</TableHead><TableHead>Item #</TableHead><TableHead>UOM</TableHead><TableHead>Cost</TableHead><TableHead>Price</TableHead><TableHead>Preferred</TableHead></TableRow></TableHeader>
                  <TableBody>{detail.products.map((p) => (
                    <TableRow key={p.id} data-testid={`supplier-product-${p.id}`}>
                      <TableCell>{p.material_name || "—"}</TableCell>
                      <TableCell className="font-mono text-xs">{p.supplier_item_number || "—"}</TableCell>
                      <TableCell className="text-xs text-slate-500">{p.supplier_uom || "—"}</TableCell>
                      <TableCell>{p.current_cost != null ? money(p.current_cost) : "—"}</TableCell>
                      <TableCell><PriceTag status={p.price_status} provider={detail.supplier.integration_provider} updatedAt={p.price_updated_at} /></TableCell>
                      <TableCell>{p.is_preferred && <Star className="h-3.5 w-3.5 fill-indigo-500 text-indigo-500" />}</TableCell>
                    </TableRow>
                  ))}{detail.products.length === 0 && <TableRow><TableCell colSpan={6} className="text-center text-slate-400">No linked products.</TableCell></TableRow>}</TableBody>
                </Table>
              </div>
            </div>

            <div>
              <div className="mb-1 font-medium text-slate-700">Recent purchase orders ({(detail.purchase_orders || []).length})</div>
              <div className="max-h-48 overflow-y-auto rounded-md border border-border">
                <Table><TableHeader><TableRow><TableHead>PO #</TableHead><TableHead>Status</TableHead><TableHead>Expected</TableHead><TableHead className="text-right">Total</TableHead></TableRow></TableHeader>
                  <TableBody>{(detail.purchase_orders || []).map((po) => (
                    <TableRow key={po.id} data-testid={`supplier-po-${po.id}`}>
                      <TableCell className="font-medium">{po.number}</TableCell>
                      <TableCell><Badge variant="secondary" className="bg-slate-100 text-slate-600">{po.status}</Badge></TableCell>
                      <TableCell className="text-xs text-slate-500">{po.expected_date ? new Date(po.expected_date).toLocaleDateString() : "—"}</TableCell>
                      <TableCell className="text-right tabular-nums">{money(po.total || 0)}</TableCell>
                    </TableRow>
                  ))}{(detail.purchase_orders || []).length === 0 && <TableRow><TableCell colSpan={4} className="text-center text-slate-400">No purchase orders yet.</TableCell></TableRow>}</TableBody>
                </Table>
              </div>
            </div>
          </div>}
        </DialogContent>
      </Dialog>
    </div>
  );
}

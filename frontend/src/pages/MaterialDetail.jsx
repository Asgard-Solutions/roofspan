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
import { ArrowLeft, Loader2, Star, CheckCircle2 } from "lucide-react";

const MANAGE = ["owner", "administrator", "office"];
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

export default function MaterialDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canManage = MANAGE.includes(user?.role);
  const [d, setD] = useState(null);
  const [balances, setBalances] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/materials/${id}/detail`); setD(data);
      const b = await api.get("/inventory/balances", { params: { material_id: id } }); setBalances(b.data.balances);
    }
    catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const makePreferred = async (smId) => {
    try { await api.post(`/materials/${id}/suppliers/${smId}/prefer`); toast.success("Preferred supplier updated"); load(); }
    catch (e) { toast.error(apiError(e)); }
  };

  if (loading || !d) return <div className="p-10 text-center text-slate-400" data-testid="material-detail-loading"><Loader2 className="mx-auto h-6 w-6 animate-spin" /></div>;
  const m = d.material; const q = d.quantities;

  return (
    <div>
      <PageHeader title={m.name} description={m.category || "Material"} testid="page-material-detail" />
      <div className="p-6 sm:p-8 space-y-6">
        <Button variant="ghost" size="sm" onClick={() => navigate("/inventory")} data-testid="detail-back"><ArrowLeft className="h-4 w-4" /> Inventory</Button>

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
            <div className="text-xs uppercase tracking-wide text-slate-400">Price</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums text-indigo-700" data-testid="detail-effective-price">{m.effective_price != null ? money(m.effective_price) : "—"}</div>
            <div className="mt-1 text-xs text-slate-500" data-testid="detail-price-source">
              {m.effective_price == null
                ? (!canManage ? "Price unavailable" : (m.effective_cost == null ? "No cost basis — price unavailable" : (m.price_book_id ? "No matching price rule" : "No default price book set")))
                : `Price Book: ${m.price_book_name || "—"}${m.matched_rule_label ? ` · Rule: ${m.matched_rule_label}` : ""}`}
            </div>
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
          <h3 className="border-b border-border p-3 text-sm font-semibold text-slate-700">Supplier pricing</h3>
          <Table>
            <TableHeader><TableRow><TableHead>Supplier</TableHead><TableHead>Item #</TableHead><TableHead>UoM</TableHead><TableHead>Cost</TableHead><TableHead>Availability</TableHead><TableHead>Preferred</TableHead></TableRow></TableHeader>
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
                </TableRow>
              ))}
              {d.suppliers.length === 0 && <TableRow><TableCell colSpan={6} className="text-center text-sm text-slate-400">No supplier mappings.</TableCell></TableRow>}
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
    </div>
  );
}

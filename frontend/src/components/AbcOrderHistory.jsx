import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Loader2, Search, ChevronLeft, ChevronRight, Truck, ExternalLink } from "lucide-react";

const norm = { processing: "bg-blue-50 text-blue-700", scheduled: "bg-indigo-50 text-indigo-700", shipped: "bg-violet-50 text-violet-700", delivered: "bg-green-50 text-green-700", invoiced: "bg-green-50 text-green-700", cancelled: "bg-red-50 text-red-500" };

export default function AbcOrderHistory() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState([]);
  const [pagination, setPagination] = useState({});
  const [loaded, setLoaded] = useState(false);
  const [filters, setFilters] = useState({ start_date: "", end_date: "" });
  const [page, setPage] = useState(1);
  const [detail, setDetail] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback((pg = page) => {
    setLoading(true);
    const params = { page_number: pg, items_per_page: 20 };
    if (filters.start_date) params.start_date = filters.start_date;
    if (filters.end_date) params.end_date = filters.end_date;
    api.get("/integrations/abc/orders/history", { params })
      .then((r) => { setItems(r.data.items || []); setPagination(r.data.pagination || {}); setLoaded(true); })
      .catch((e) => { setItems([]); toast.error(apiError(e)); })
      .finally(() => setLoading(false));
  }, [filters, page]);

  const applyFilters = () => { setPage(1); load(1); };
  const goPage = (pg) => { setPage(pg); load(pg); };

  const openDetail = async (identifier) => {
    setDetailOpen(true); setDetail(null); setDetailLoading(true);
    try { const { data } = await api.get(`/integrations/abc/orders/${identifier}`); setDetail(data); }
    catch (e) { toast.error(apiError(e)); setDetailOpen(false); }
    finally { setDetailLoading(false); }
  };

  const totalPages = pagination.totalPages || 1;

  return (
    <div data-testid="abc-order-history-panel">
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <div className="space-y-1"><Label className="text-xs">From</Label><Input type="date" value={filters.start_date} onChange={(e) => setFilters({ ...filters, start_date: e.target.value })} data-testid="abc-history-start-date" className="w-40" /></div>
        <div className="space-y-1"><Label className="text-xs">To</Label><Input type="date" value={filters.end_date} onChange={(e) => setFilters({ ...filters, end_date: e.target.value })} data-testid="abc-history-end-date" className="w-40" /></div>
        <Button onClick={applyFilters} data-testid="abc-history-search"><Search className="h-4 w-4" /> Search</Button>
        {!loaded && <Button variant="outline" onClick={() => load(1)} data-testid="abc-history-load">Load ABC Order History</Button>}
      </div>
      <p className="mb-2 text-xs text-slate-400">Account-wide ABC Supply order history. Orders placed through RoofSpan are matched to their purchase order; other orders were placed directly with ABC.</p>
      <div className="overflow-x-auto rounded-md border border-border bg-white">
        <Table data-testid="abc-orders-table">
          <TableHeader><TableRow><TableHead>Order #</TableHead><TableHead>Date</TableHead><TableHead>Type</TableHead><TableHead>Status</TableHead><TableHead>Branch</TableHead><TableHead>Items</TableHead><TableHead>RoofSpan PO</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={8} className="text-center text-sm text-slate-400"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" /> Loading…</TableCell></TableRow>}
            {!loading && items.map((o, i) => (
              <TableRow key={i} data-testid={`abc-order-row-${i}`}>
                <TableCell className="font-medium text-slate-900">{o.orderNumber || "—"}</TableCell>
                <TableCell className="text-slate-500">{o.invoiceDate || "—"}</TableCell>
                <TableCell className="text-slate-600">{o.orderType || "—"}</TableCell>
                <TableCell><Badge className="bg-blue-50 text-blue-700" variant="secondary">{o.orderStatus || "—"}</Badge></TableCell>
                <TableCell className="text-slate-500">{o.branchCityState || o.branch || "—"}</TableCell>
                <TableCell className="tabular-nums text-slate-600">{o.productQty ?? "—"}</TableCell>
                <TableCell>
                  {o.roofspan_matched
                    ? <button className="text-blue-700 hover:underline" onClick={() => navigate(`/purchase-orders/${o.roofspan_po_id}`)} data-testid={`abc-order-po-link-${i}`}>{o.roofspan_po_number}</button>
                    : <span className="text-xs text-slate-400" data-testid={`abc-order-external-${i}`}>Placed directly with ABC</span>}
                </TableCell>
                <TableCell className="text-right"><Button size="sm" variant="ghost" onClick={() => openDetail(o.orderNumber)} data-testid={`abc-order-view-${i}`}>View</Button></TableCell>
              </TableRow>
            ))}
            {!loading && loaded && items.length === 0 && <TableRow><TableCell colSpan={8} className="text-center text-sm text-slate-400">No ABC Supply orders found for this period.</TableCell></TableRow>}
            {!loaded && !loading && <TableRow><TableCell colSpan={8} className="text-center text-sm text-slate-400">Click “Load ABC Order History” to fetch orders from ABC Supply.</TableCell></TableRow>}
          </TableBody>
        </Table>
      </div>
      {loaded && (
        <div className="mt-3 flex items-center justify-end gap-2 text-sm text-slate-500">
          <span>{pagination.totalItems != null ? `${pagination.totalItems} orders` : ""}</span>
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => goPage(page - 1)} data-testid="abc-history-prev"><ChevronLeft className="h-4 w-4" /></Button>
          <span>Page {pagination.pageNumber || page} of {totalPages}</span>
          <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => goPage(page + 1)} data-testid="abc-history-next"><ChevronRight className="h-4 w-4" /></Button>
        </div>
      )}

      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-w-2xl" data-testid="abc-order-detail">
          <DialogHeader>
            <DialogTitle>ABC Order {detail?.order_number || ""}</DialogTitle>
            <DialogDescription>Confirmation {detail?.confirmation_number || "—"}{detail?.purchase_order ? ` · PO ${detail.purchase_order}` : ""}</DialogDescription>
          </DialogHeader>
          {detailLoading && <div className="p-6 text-sm text-slate-400"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" /> Loading…</div>}
          {detail && !detailLoading && (
            <div className="space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-2 rounded-md border border-border p-3">
                <div className="flex justify-between"><span className="text-slate-400">Status</span><Badge className={norm[detail.normalized_status] || "bg-slate-100 text-slate-600"} variant="secondary">{detail.abc_status || "—"}</Badge></div>
                <div className="flex justify-between"><span className="text-slate-400">Type</span><span>{detail.order_type || "—"}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Branch</span><span>{detail.branch_name || detail.branch_number || "—"}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Delivery</span><span>{detail.delivery_service || "—"}</span></div>
              </div>
              {detail.amounts && (
                <div className="rounded-md border border-border p-3" data-testid="abc-order-detail-amounts">
                  <div className="flex justify-between text-slate-600"><span>Subtotal</span><span className="tabular-nums">{money(detail.amounts.sub_total || 0)}</span></div>
                  <div className="flex justify-between text-slate-600"><span>Tax</span><span className="tabular-nums">{money(detail.amounts.tax || 0)}</span></div>
                  <div className="mt-1 flex justify-between border-t border-border pt-1 font-semibold"><span>Total</span><span className="tabular-nums">{money(detail.amounts.total || 0)}</span></div>
                </div>
              )}
              {detail.roofspan_matched && (
                <button className="flex items-center gap-1 text-sm text-blue-700 hover:underline" onClick={() => { setDetailOpen(false); navigate(`/purchase-orders/${detail.roofspan_po_id}`); }} data-testid="abc-order-detail-po-link">
                  <ExternalLink className="h-3.5 w-3.5" /> Open RoofSpan PO {detail.roofspan_po_number}
                </button>
              )}
              {detail.shipments?.length > 0 && (
                <div className="rounded-md border border-border p-3" data-testid="abc-order-detail-shipments">
                  <div className="mb-1 flex items-center gap-1 font-medium text-slate-700"><Truck className="h-4 w-4" /> Shipments</div>
                  {detail.shipments.map((s, i) => <div key={i} className="text-slate-500">{s.shipment_number}: {s.status}{s.latest_delivery_event ? ` · ${s.latest_delivery_event}` : ""}{s.delivered_on ? ` · delivered ${s.delivered_on}` : ""}</div>)}
                </div>
              )}
              {detail.lines?.length > 0 && (
                <div className="overflow-x-auto rounded-md border border-border">
                  <Table>
                    <TableHeader><TableRow><TableHead>Item</TableHead><TableHead>Qty</TableHead></TableRow></TableHeader>
                    <TableBody>
                      {detail.lines.map((l, i) => <TableRow key={i}><TableCell className="text-slate-700">{l.itemNumber || l.itemDescription}</TableCell><TableCell className="tabular-nums">{(l.orderedQty?.value ?? l.orderedQty) || "—"}</TableCell></TableRow>)}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
          )}
          <DialogFooter><Button variant="outline" onClick={() => setDetailOpen(false)}>Close</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

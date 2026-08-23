import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Loader2, FileText, ArrowRight, ChevronLeft, ChevronRight } from "lucide-react";

export default function AbcTemplatesPanel() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [templates, setTemplates] = useState([]);
  const [pagination, setPagination] = useState({ pageNumber: 1, itemsPerPage: 40 });
  const [page, setPage] = useState(1);
  const [detail, setDetail] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [converting, setConverting] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api.get("/integrations/abc/templates", { params: { page_number: page, items_per_page: 40 } })
      .then((r) => { setTemplates(r.data.templates || []); setPagination(r.data.pagination || {}); })
      .catch((e) => { setTemplates([]); toast.error(apiError(e)); })
      .finally(() => setLoading(false));
  }, [page]);
  useEffect(() => { load(); }, [load]);

  const openDetail = async (tid) => {
    setDetailOpen(true); setDetail(null); setDetailLoading(true);
    try { const { data } = await api.get(`/integrations/abc/templates/${tid}`); setDetail(data); }
    catch (e) { toast.error(apiError(e)); setDetailOpen(false); }
    finally { setDetailLoading(false); }
  };

  const convert = async (tid) => {
    setConverting(true);
    try {
      const { data } = await api.post("/purchase-orders/from-abc-template", { template_id: tid });
      toast.success(`Draft PO ${data.number} created from template — review pricing before submitting.`);
      setDetailOpen(false);
      navigate(`/purchase-orders/${data.id}`);
    } catch (e) { toast.error(apiError(e)); }
    finally { setConverting(false); }
  };

  return (
    <div data-testid="abc-templates-panel">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm text-slate-500">Reusable ABC Supply order templates for your account. Convert one into a draft RoofSpan purchase order — fresh ABC pricing is always applied before you submit.</p>
        <Button variant="outline" size="sm" onClick={load} data-testid="abc-templates-refresh">Refresh</Button>
      </div>
      <div className="overflow-x-auto rounded-md border border-border bg-white">
        <Table data-testid="abc-templates-table">
          <TableHeader><TableRow><TableHead>Template</TableHead><TableHead>Description</TableHead><TableHead>Account</TableHead><TableHead>Created</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={5} className="text-center text-sm text-slate-400"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" /> Loading templates…</TableCell></TableRow>}
            {!loading && templates.map((t, i) => (
              <TableRow key={t.templateId || i} data-testid={`abc-template-row-${i}`}>
                <TableCell className="font-medium text-slate-900"><FileText className="mr-1 inline h-4 w-4 text-slate-400" />{t.name || t.templateId}</TableCell>
                <TableCell className="text-slate-600">{t.description || "—"}</TableCell>
                <TableCell className="text-slate-600">{t.accountNumber || "—"}</TableCell>
                <TableCell className="text-slate-500">{t.createdDate ? new Date(t.createdDate).toLocaleDateString() : "—"}</TableCell>
                <TableCell className="text-right">
                  <Button size="sm" variant="ghost" onClick={() => openDetail(t.templateId)} data-testid={`abc-template-view-${i}`}>View</Button>
                  <Button size="sm" onClick={() => convert(t.templateId)} disabled={converting} data-testid={`abc-template-convert-${i}`}>Convert to PO <ArrowRight className="h-3.5 w-3.5" /></Button>
                </TableCell>
              </TableRow>
            ))}
            {!loading && templates.length === 0 && <TableRow><TableCell colSpan={5} className="text-center text-sm text-slate-400">No ABC order templates found for your account.</TableCell></TableRow>}
          </TableBody>
        </Table>
      </div>
      <div className="mt-3 flex items-center justify-end gap-2 text-sm text-slate-500">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))} data-testid="abc-templates-prev"><ChevronLeft className="h-4 w-4" /></Button>
        <span>Page {pagination.pageNumber || page}{pagination.totalPages ? ` of ${pagination.totalPages}` : ""}</span>
        <Button variant="outline" size="sm" disabled={pagination.totalPages ? page >= pagination.totalPages : (templates.length || 0) < (pagination.itemsPerPage || 40)} onClick={() => setPage((p) => p + 1)} data-testid="abc-templates-next"><ChevronRight className="h-4 w-4" /></Button>
      </div>

      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-w-2xl" data-testid="abc-template-detail">
          <DialogHeader>
            <DialogTitle>{detail?.name || "Order Template"}</DialogTitle>
            <DialogDescription>{detail?.description || ""}{detail?.branch?.name ? ` · Branch: ${detail.branch.name}` : ""}</DialogDescription>
          </DialogHeader>
          {detailLoading && <div className="p-6 text-sm text-slate-400"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" /> Loading…</div>}
          {detail && !detailLoading && (
            <div className="space-y-3">
              {detail.delivery_address?.line1 && (
                <div className="rounded-md border border-border p-3 text-sm text-slate-600" data-testid="abc-template-delivery">
                  <div className="mb-1 font-medium text-slate-700">Template Delivery Address</div>
                  <div>{detail.delivery_address.line1}</div>
                  <div>{detail.delivery_address.city}, {detail.delivery_address.state} {detail.delivery_address.postal}</div>
                </div>
              )}
              <div className="overflow-x-auto rounded-md border border-border">
                <Table>
                  <TableHeader><TableRow><TableHead>Item #</TableHead><TableHead>Description</TableHead><TableHead>Qty</TableHead><TableHead>UOM</TableHead><TableHead className="text-right">Template Price</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {(detail.lines || []).map((l, i) => (
                      <TableRow key={i} data-testid={`abc-template-line-${i}`}>
                        <TableCell className="font-medium text-slate-900">{l.item_number}</TableCell>
                        <TableCell className="text-slate-600">{l.description}</TableCell>
                        <TableCell className="tabular-nums">{l.quantity}</TableCell>
                        <TableCell className="text-slate-500">{l.uom}</TableCell>
                        <TableCell className="text-right tabular-nums">{l.unit_price != null ? money(l.unit_price) : "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <p className="text-xs text-slate-400">Template prices are only a reference. RoofSpan re-checks live ABC pricing before the order can be submitted.</p>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDetailOpen(false)}>Close</Button>
            {detail && <Button onClick={() => convert(detail.template_id)} disabled={converting} data-testid="abc-template-detail-convert">{converting ? <><Loader2 className="h-4 w-4 animate-spin" /> Converting…</> : <>Convert to RoofSpan PO <ArrowRight className="h-3.5 w-3.5" /></>}</Button>}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

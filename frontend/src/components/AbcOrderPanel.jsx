import { useState, useEffect, useCallback } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Loader2, Send, RefreshCw, AlertTriangle, CheckCircle2, XCircle, HelpCircle, Truck } from "lucide-react";

const norm = { processing: "bg-blue-50 text-blue-700", scheduled: "bg-indigo-50 text-indigo-700", shipped: "bg-violet-50 text-violet-700", delivered: "bg-green-50 text-green-700", invoiced: "bg-green-50 text-green-700", cancelled: "bg-red-50 text-red-500" };

export default function AbcOrderPanel({ open, onOpenChange, po, onChanged }) {
  const [loading, setLoading] = useState(false);
  const [review, setReview] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [subKey, setSubKey] = useState("");
  const [result, setResult] = useState(null);
  const [detail, setDetail] = useState(null);
  const [activity, setActivity] = useState({ events: [], invoices: [] });

  const submitted = !!po?.external_confirmation_number;
  const unknown = result?.status === "unknown";

  const loadActivity = useCallback(async () => {
    if (!po?.id) return;
    try { const { data } = await api.get(`/integrations/abc/notifications/events/${po.id}`); setActivity(data); } catch (e) { /* none */ }
  }, [po?.id]);

  const loadReview = useCallback(async () => {
    if (!po || submitted) return;
    setLoading(true); setReview(null);
    try {
      const { data } = await api.post(`/purchase-orders/${po.id}/abc-submit-review`, {});
      setReview(data);
      setSubKey(crypto.randomUUID());
    } catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  }, [po, submitted]);

  useEffect(() => { if (open && po && !submitted) loadReview(); }, [open, po, submitted, loadReview]);
  useEffect(() => { if (open && submitted) { refreshStatus(); loadActivity(); } /* eslint-disable-next-line */ }, [open, submitted]);

  const submit = async () => {
    setSubmitting(true); setResult(null);
    try {
      const { data } = await api.post(`/purchase-orders/${po.id}/abc-submit`, {
        submission_key: subKey,
        accept_price_changes: !!(review?.price_changes?.length),
        delivery: { name: po.number },
      });
      setResult(data);
      if (data.status === "confirmed" || data.status === "already_submitted") { toast.success(`Submitted to ABC — ${data.confirmation_number}`); onChanged && onChanged(); }
      else if (data.status === "price_changed") { toast.warning("ABC pricing changed — review the new prices."); setReview((r) => ({ ...r, price_changes: data.price_changes, previous_total: data.previous_total, updated_total: data.updated_total })); }
      else if (data.status === "validation_failed") toast.error("Order cannot be submitted — resolve the listed issues.");
      else if (data.status === "unknown") toast.error("Submission status unknown — verify the ABC order.");
      else if (data.status === "failed") toast.error(data.message || "ABC did not accept this order.");
    } catch (e) { toast.error(apiError(e)); } finally { setSubmitting(false); }
  };

  const refreshStatus = async () => {
    setLoading(true);
    try { const { data } = await api.post(`/purchase-orders/${po.id}/abc-refresh-status`); setDetail(data.detail); onChanged && onChanged(); }
    catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  };

  const reconcile = async () => {
    setLoading(true);
    try { const { data } = await api.post(`/purchase-orders/${po.id}/abc-reconcile`); toast[data.status === "reconciled" ? "success" : "message"](data.message || `Reconciled: ${data.confirmation_number}`); setResult(null); onChanged && onChanged(); }
    catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  };

  const changes = review?.price_changes || [];
  const errors = review?.errors || [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl" data-testid="abc-order-panel">
        <DialogHeader>
          <DialogTitle>ABC Supply Order — {po?.number}</DialogTitle>
          <DialogDescription>Ship-To {po?.abc_ship_to_number} · Branch {po?.abc_branch_number}</DialogDescription>
        </DialogHeader>

        {loading && <div className="p-6 text-sm text-slate-400"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" /> Working…</div>}

        {/* ---- Already submitted: status view ---- */}
        {submitted && !loading && (
          <div className="space-y-3" data-testid="abc-order-status">
            <div className="rounded-md border border-border bg-slate-50 p-4 text-sm">
              <div className="flex items-center justify-between"><span className="text-slate-400">ABC Confirmation</span><span className="font-medium">{po.external_confirmation_number}</span></div>
              {po.external_order_number && <div className="flex items-center justify-between"><span className="text-slate-400">Order #</span><span className="font-medium">{po.external_order_number}</span></div>}
              <div className="flex items-center justify-between"><span className="text-slate-400">Status</span><Badge className={norm[po.abc_normalized_status] || "bg-slate-100 text-slate-600"} variant="secondary">{po.abc_order_status || "Submitted"}</Badge></div>
              {po.abc_submitted_at && <div className="flex items-center justify-between"><span className="text-slate-400">Submitted</span><span>{new Date(po.abc_submitted_at).toLocaleString()}</span></div>}
              {po.abc_last_sync_at && <div className="flex items-center justify-between"><span className="text-slate-400">Last checked</span><span>{new Date(po.abc_last_sync_at).toLocaleString()}</span></div>}
            </div>
            {detail?.shipments?.length > 0 && (
              <div className="rounded-md border border-border p-3 text-sm" data-testid="abc-order-shipments">
                <div className="mb-1 flex items-center gap-1 font-medium text-slate-700"><Truck className="h-4 w-4" /> Shipments</div>
                {detail.shipments.map((s, i) => <div key={i} className="text-slate-500">{s.shipment_number}: {s.status}{s.latest_delivery_event ? ` · ${s.latest_delivery_event}` : ""}{s.delivered_on ? ` · delivered ${s.delivered_on}` : ""}</div>)}
              </div>
            )}
            <p className="text-xs text-slate-400">Updates are received automatically from ABC Supply. Editing this PO in RoofSpan does not modify the submitted ABC order. Receiving materials still uses the existing Receive workflow.</p>
            {activity.invoices?.length > 0 && (
              <div className="rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-800" data-testid="abc-invoice">
                <div className="font-medium">ABC Invoice</div>
                {activity.invoices.map((iv, i) => <div key={i}>Invoice #: {iv.invoice_number}{iv.invoice_date ? ` · ${iv.invoice_date}` : ""}{iv.is_credit_memo ? " · Credit memo" : ""}</div>)}
              </div>
            )}
            {activity.events?.length > 0 && (
              <div className="rounded-md border border-border p-3 text-sm" data-testid="abc-activity">
                <div className="mb-1 font-medium text-slate-700">ABC Activity</div>
                {activity.events.map((e, i) => <div key={i} className="text-slate-500">{new Date(e.received_at).toLocaleString()} — {e.event_type === "ORDER_INVOICED" ? "Invoiced" : (e.abc_status || "Order update")}</div>)}
              </div>
            )}
            <Button variant="outline" onClick={() => { refreshStatus(); loadActivity(); }} data-testid="abc-refresh-status"><RefreshCw className="h-4 w-4" /> Refresh ABC status</Button>
          </div>
        )}

        {/* ---- Not submitted: review + submit ---- */}
        {!submitted && !loading && review && (
          <div className="space-y-3">
            {errors.length > 0 && (
              <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700" data-testid="abc-order-errors">
                <div className="mb-1 flex items-center gap-1 font-medium"><XCircle className="h-4 w-4" /> Cannot submit yet</div>
                <ul className="list-inside list-disc">{errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
              </div>
            )}
            {changes.length > 0 && (
              <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800" data-testid="abc-price-changes">
                <div className="mb-2 flex items-center gap-1 font-medium"><AlertTriangle className="h-4 w-4" /> ABC Supply pricing has changed</div>
                {changes.map((c) => <div key={c.po_item_id} className="flex justify-between"><span>{c.description}</span><span className="tabular-nums">{money(c.previous_price)} → {money(c.current_price)} ({c.difference >= 0 ? "+" : ""}{money(c.difference)})</span></div>)}
                <div className="mt-2 flex justify-between border-t border-amber-200 pt-2 font-medium"><span>Updated ABC Total</span><span className="tabular-nums">{money(review.updated_total)}</span></div>
              </div>
            )}
            <div className="rounded-md border border-border p-3 text-sm" data-testid="abc-order-review">
              {(review.review?.lines || []).map((l, i) => (
                <div key={i} className="flex justify-between text-slate-600"><span>{l.abc_item_number} · {l.quantity} {l.uom}</span><span className="tabular-nums">{money(l.line_total)}</span></div>
              ))}
              <div className="mt-2 flex justify-between border-t border-border pt-2 font-semibold"><span>ABC Estimated Total</span><span className="tabular-nums" data-testid="abc-review-total">{money(review.review?.estimated_total || 0)}</span></div>
              <div className="mt-1 text-xs text-slate-400">Prices verified: {review.prices_verified_at ? new Date(review.prices_verified_at).toLocaleTimeString() : "—"}</div>
            </div>
            {result?.status === "failed" && <div className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-700"><XCircle className="mr-1 inline h-4 w-4" />{result.message}</div>}
            {result?.status === "unknown" && (
              <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800" data-testid="abc-unknown">
                <div className="flex items-center gap-1 font-medium"><HelpCircle className="h-4 w-4" /> Submission status unknown</div>
                <p className="mt-1">RoofSpan cannot determine whether ABC accepted this order. Do not submit again until verified.</p>
                <Button size="sm" variant="outline" className="mt-2" onClick={reconcile} data-testid="abc-verify-order"><RefreshCw className="h-4 w-4" /> Verify ABC order</Button>
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
          {!submitted && (
            <Button onClick={submit} disabled={submitting || loading || (review && errors.length > 0) || unknown} data-testid="abc-submit-order">
              {submitting ? <><Loader2 className="h-4 w-4 animate-spin" /> Submitting…</> : (changes.length ? <><Send className="h-4 w-4" /> Accept pricing &amp; submit</> : <><Send className="h-4 w-4" /> Submit to ABC Supply</>)}
            </Button>
          )}
          {result?.status === "confirmed" && <span className="flex items-center gap-1 text-sm text-green-700"><CheckCircle2 className="h-4 w-4" /> Submitted</span>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

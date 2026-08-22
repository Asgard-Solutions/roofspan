import { useState, useEffect, useCallback } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
  const [delivery, setDelivery] = useState(null);
  const [editOpen, setEditOpen] = useState(false);
  // Local authoritative copy of the PO so the panel can transition to the submitted view
  // immediately after submit (refetched from the backend) without a close/reopen.
  const [poState, setPoState] = useState(po);
  useEffect(() => { setPoState(po); }, [po]);

  const submitted = !!poState?.external_confirmation_number;
  const unknown = result?.status === "unknown";

  const refetchPO = useCallback(async () => {
    if (!po?.id) return null;
    const { data } = await api.get(`/purchase-orders/${po.id}`);
    setPoState(data);
    return data;
  }, [po?.id]);

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
      setDelivery(data.delivery || {});
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
        delivery: delivery || { name: po.number },
      });
      setResult(data);
      if (data.status === "confirmed" || data.status === "already_submitted") {
        toast.success(`Submitted to ABC — ${data.confirmation_number}`);
        // Refetch the persisted PO so the panel immediately renders the submitted-order view
        // (ABC identifiers + the exact stored delivery snapshot). Backend/PostgreSQL is authoritative.
        await refetchPO();
        onChanged && onChanged();
      }
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
          <DialogTitle>ABC Supply Order — {poState?.number}</DialogTitle>
          <DialogDescription>Ship-To {poState?.abc_ship_to_number} · Branch {poState?.abc_branch_number}</DialogDescription>
        </DialogHeader>

        {loading && <div className="p-6 text-sm text-slate-400"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" /> Working…</div>}

        {/* ---- Already submitted: status view ---- */}
        {submitted && !loading && (
          <div className="space-y-3" data-testid="abc-order-status">
            <div className="rounded-md border border-border bg-slate-50 p-4 text-sm">
              <div className="flex items-center justify-between"><span className="text-slate-400">ABC Confirmation</span><span className="font-medium" data-testid="abc-confirmation-number">{poState.external_confirmation_number}</span></div>
              {poState.external_order_number && <div className="flex items-center justify-between"><span className="text-slate-400">Order #</span><span className="font-medium" data-testid="abc-order-number">{poState.external_order_number}</span></div>}
              <div className="flex items-center justify-between"><span className="text-slate-400">Status</span><Badge className={norm[poState.abc_normalized_status] || "bg-slate-100 text-slate-600"} variant="secondary" data-testid="abc-order-status-badge">{poState.abc_order_status || "Submitted"}</Badge></div>
              {poState.abc_submitted_at && <div className="flex items-center justify-between"><span className="text-slate-400">Submitted</span><span>{new Date(poState.abc_submitted_at).toLocaleString()}</span></div>}
              {poState.abc_last_sync_at && <div className="flex items-center justify-between"><span className="text-slate-400">Last checked</span><span>{new Date(poState.abc_last_sync_at).toLocaleString()}</span></div>}
            </div>
            {poState.abc_delivery?.line1 ? (
              <div className="rounded-md border border-border p-3 text-sm" data-testid="abc-submitted-delivery">
                <div className="mb-1 font-medium text-slate-700">Delivery Address</div>
                <div className="text-slate-600">{poState.abc_delivery.name}</div>
                <div className="text-slate-600">{poState.abc_delivery.line1}{poState.abc_delivery.line2 ? `, ${poState.abc_delivery.line2}` : ""}</div>
                <div className="text-slate-600">{poState.abc_delivery.city}, {poState.abc_delivery.state} {poState.abc_delivery.postal}</div>
                <div className="mt-1 text-xs text-slate-400">This is the address sent to ABC. Changing RoofSpan job information does not modify the submitted ABC Supply order.</div>
              </div>
            ) : (
              <div className="rounded-md border border-border p-3 text-sm" data-testid="abc-submitted-delivery-default">
                <div className="mb-1 font-medium text-slate-700">Delivery Address</div>
                <div className="text-slate-500">No delivery override was supplied — this order ships to the ABC Ship-To account's default address.</div>
              </div>
            )}

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
            <div className="rounded-md border border-border p-3 text-sm" data-testid="abc-delivery-review">
              <div className="mb-1 flex items-center justify-between"><span className="font-medium text-slate-700">Deliver To</span><Button size="sm" variant="ghost" onClick={() => setEditOpen(true)} data-testid="abc-edit-delivery">Edit Delivery Address</Button></div>
              {delivery && (delivery.line1 ? (
                <div className="text-slate-600">
                  <div>{delivery.name}</div>
                  <div>{delivery.line1}{delivery.line2 ? `, ${delivery.line2}` : ""}</div>
                  <div>{delivery.city}{delivery.city ? ", " : ""}{delivery.state} {delivery.postal}</div>
                  {delivery.contact_name && <div className="mt-1 text-xs text-slate-400">Contact: {delivery.contact_name}{delivery.contact_phone ? ` · ${delivery.contact_phone}` : ""}</div>}
                  {delivery.instructions && <div className="text-xs text-slate-400">Instructions: {delivery.instructions}</div>}
                </div>
              ) : <div className="text-slate-500">No delivery override — materials ship to the ABC Ship-To account's default address. Click <span className="font-medium">Edit Delivery Address</span> to deliver elsewhere.</div>)}
            </div>
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

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="max-w-md" data-testid="abc-delivery-editor">
          <DialogHeader><DialogTitle>Edit Delivery Address</DialogTitle><DialogDescription>Where materials should physically be delivered. This does not change the ABC Ship-To account, job, or customer records.</DialogDescription></DialogHeader>
          <div className="grid grid-cols-2 gap-2">
            <div className="col-span-2 space-y-1"><Label className="text-xs">Delivery Name</Label><Input value={delivery?.name || ""} onChange={(e) => setDelivery({ ...delivery, name: e.target.value })} data-testid="delivery-name" /></div>
            <div className="col-span-2 space-y-1"><Label className="text-xs">Address Line 1</Label><Input value={delivery?.line1 || ""} onChange={(e) => setDelivery({ ...delivery, line1: e.target.value })} data-testid="delivery-line1" /></div>
            <div className="col-span-2 space-y-1"><Label className="text-xs">Address Line 2</Label><Input value={delivery?.line2 || ""} onChange={(e) => setDelivery({ ...delivery, line2: e.target.value })} data-testid="delivery-line2" /></div>
            <div className="space-y-1"><Label className="text-xs">City</Label><Input value={delivery?.city || ""} onChange={(e) => setDelivery({ ...delivery, city: e.target.value })} data-testid="delivery-city" /></div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1"><Label className="text-xs">State</Label><Input value={delivery?.state || ""} onChange={(e) => setDelivery({ ...delivery, state: e.target.value })} data-testid="delivery-state" /></div>
              <div className="space-y-1"><Label className="text-xs">ZIP</Label><Input value={delivery?.postal || ""} onChange={(e) => setDelivery({ ...delivery, postal: e.target.value })} data-testid="delivery-postal" /></div>
            </div>
            <div className="space-y-1"><Label className="text-xs">Contact Name</Label><Input value={delivery?.contact_name || ""} onChange={(e) => setDelivery({ ...delivery, contact_name: e.target.value })} data-testid="delivery-contact-name" /></div>
            <div className="space-y-1"><Label className="text-xs">Contact Phone</Label><Input value={delivery?.contact_phone || ""} onChange={(e) => setDelivery({ ...delivery, contact_phone: e.target.value })} data-testid="delivery-contact-phone" /></div>
            <div className="col-span-2 space-y-1"><Label className="text-xs">Delivery Instructions</Label><Input value={delivery?.instructions || ""} onChange={(e) => setDelivery({ ...delivery, instructions: e.target.value })} data-testid="delivery-instructions" /></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setEditOpen(false)}>Cancel</Button><Button onClick={() => setEditOpen(false)} data-testid="delivery-save">Use This Delivery Address</Button></DialogFooter>
        </DialogContent>
      </Dialog>

    </Dialog>
  );
}

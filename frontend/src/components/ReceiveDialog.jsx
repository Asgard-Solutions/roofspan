import { useState } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Loader2 } from "lucide-react";

export default function ReceiveDialog({ open, onOpenChange, po, onReceived }) {
  const [qty, setQty] = useState({});
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const items = Object.entries(qty)
      .map(([po_item_id, quantity]) => ({ po_item_id, quantity: Number(quantity) || 0 }))
      .filter((x) => x.quantity > 0);
    if (items.length === 0) { toast.error("Enter a quantity to receive"); return; }
    setBusy(true);
    try {
      const key = (window.crypto?.randomUUID && window.crypto.randomUUID()) || String(Date.now());
      await api.post(`/purchase-orders/${po.id}/receive`, { items }, { headers: { "Idempotency-Key": key } });
      toast.success("Materials received — inventory updated");
      onOpenChange(false);
      setQty({});
      onReceived && onReceived();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  if (!po) return null;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="receive-dialog">
        <DialogHeader><DialogTitle>Receive — {po.number}</DialogTitle><DialogDescription>Partial receiving is supported. Inventory increases on receipt.</DialogDescription></DialogHeader>
        <div className="space-y-2">
          <div className="grid grid-cols-[1fr_60px_60px_70px] gap-2 text-xs font-semibold uppercase text-slate-400"><span>Item</span><span>Ord</span><span>Recd</span><span>Receive</span></div>
          {po.items.map((it) => {
            const remaining = it.quantity - it.received_quantity;
            return (
              <div key={it.id} className="grid grid-cols-[1fr_60px_60px_70px] items-center gap-2 text-sm" data-testid={`receive-row-${it.id}`}>
                <span className="text-slate-700">{it.description}</span>
                <span className="tabular-nums text-slate-500">{it.quantity}</span>
                <span className="tabular-nums text-slate-500">{it.received_quantity}</span>
                <Input type="number" min={0} max={remaining} value={qty[it.id] ?? ""} onChange={(e) => setQty({ ...qty, [it.id]: e.target.value })} className="h-8" disabled={remaining <= 0} data-testid={`receive-qty-${it.id}`} />
              </div>
            );
          })}
        </div>
        <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={submit} disabled={busy} data-testid="receive-submit">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Receive"}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

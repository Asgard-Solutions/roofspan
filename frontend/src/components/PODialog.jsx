import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Plus, Trash2, Loader2 } from "lucide-react";

export default function PODialog({ open, onOpenChange, jobId, onCreated }) {
  const [materials, setMaterials] = useState([]);
  const [supplier, setSupplier] = useState("");
  const [expected, setExpected] = useState("");
  const [items, setItems] = useState([{ material_id: "", description: "", quantity: 1, unit: "each", unit_cost: 0 }]);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (open) api.get("/materials").then((r) => setMaterials(r.data)).catch(() => {}); }, [open]);

  const setItem = (i, patch) => setItems(items.map((it, idx) => (idx === i ? { ...it, ...patch } : it)));
  const pickMaterial = (i, mid) => {
    const m = materials.find((x) => x.id === mid);
    setItem(i, { material_id: mid, description: m?.name || "", unit: m?.unit || "each" });
  };
  const total = items.reduce((s, it) => s + (Number(it.quantity) || 0) * (Number(it.unit_cost) || 0), 0);

  const create = async () => {
    if (!supplier.trim()) { toast.error("Supplier name is required"); return; }
    setBusy(true);
    try {
      await api.post("/purchase-orders", {
        supplier_name: supplier, job_id: jobId || null,
        expected_date: expected ? new Date(expected).toISOString() : null,
        items: items.filter((it) => it.material_id || it.description).map((it) => ({ ...it, quantity: Number(it.quantity) || 0, unit_cost: Number(it.unit_cost) || 0 })),
      });
      toast.success("Purchase order created");
      onOpenChange(false);
      setSupplier(""); setExpected(""); setItems([{ material_id: "", description: "", quantity: 1, unit: "each", unit_cost: 0 }]);
      onCreated && onCreated();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl" data-testid="po-dialog">
        <DialogHeader><DialogTitle>New purchase order</DialogTitle><DialogDescription>Order materials from a supplier.</DialogDescription></DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5"><Label>Supplier</Label><Input value={supplier} onChange={(e) => setSupplier(e.target.value)} placeholder="ABC Supply Co." data-testid="po-supplier" /></div>
            <div className="space-y-1.5"><Label>Expected date</Label><Input type="date" value={expected} onChange={(e) => setExpected(e.target.value)} data-testid="po-expected" /></div>
          </div>
          <div className="space-y-2">
            {items.map((it, i) => (
              <div key={i} className="grid grid-cols-[1fr_60px_80px_28px] items-center gap-2">
                <Select value={it.material_id} onValueChange={(v) => pickMaterial(i, v)}>
                  <SelectTrigger className="h-8" data-testid={`po-material-${i}`}><SelectValue placeholder="Select material" /></SelectTrigger>
                  <SelectContent>{materials.map((m) => <SelectItem key={m.id} value={m.id}>{m.name} ({m.unit})</SelectItem>)}</SelectContent>
                </Select>
                <Input type="number" value={it.quantity} onChange={(e) => setItem(i, { quantity: e.target.value })} className="h-8" data-testid={`po-qty-${i}`} />
                <Input type="number" value={it.unit_cost} onChange={(e) => setItem(i, { unit_cost: e.target.value })} className="h-8" placeholder="cost" data-testid={`po-cost-${i}`} />
                <button onClick={() => setItems(items.filter((_, idx) => idx !== i))} className="text-slate-300 hover:text-red-500"><Trash2 className="h-4 w-4" /></button>
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={() => setItems([...items, { material_id: "", description: "", quantity: 1, unit: "each", unit_cost: 0 }])} data-testid="po-add-line"><Plus className="h-4 w-4" /> Add line</Button>
          </div>
          <div className="flex justify-between border-t border-border pt-2 font-semibold"><span>Total</span><span className="tabular-nums" data-testid="po-total">{money(total)}</span></div>
        </div>
        <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={create} disabled={busy} data-testid="po-save">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create PO"}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

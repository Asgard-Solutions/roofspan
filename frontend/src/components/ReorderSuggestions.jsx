import { useState } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Sparkles, Loader2 } from "lucide-react";

export default function ReorderSuggestions({ onCreated }) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const openDialog = async () => {
    setOpen(true); setLoading(true);
    try {
      const { data } = await api.get("/inventory/reorder-suggestions");
      setRows(data.suggestions.map((s) => ({ ...s, quantity: s.recommended_quantity, include: true })));
    } catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  };

  const createDraft = async () => {
    const picked = rows.filter((r) => r.include && Number(r.quantity) > 0 && r.preferred_supplier_id);
    if (!picked.length) { toast.error("No suggestions with a preferred supplier selected"); return; }
    setBusy(true);
    try {
      const { data: suppliers } = await api.get("/suppliers", { params: { active: true } });
      const provById = Object.fromEntries(suppliers.map((s) => [s.id, s.integration_provider]));
      const groups = {};
      picked.forEach((r) => { (groups[r.preferred_supplier_id] = groups[r.preferred_supplier_id] || []).push(r); });
      for (const [sid, lines] of Object.entries(groups)) {
        const isAbc = provById[sid] === "abc_supply";
        await api.post("/purchase-orders", { supplier_id: sid, integration_provider: isAbc ? "abc_supply" : null,
          items: lines.map((r) => ({ material_id: r.material_id, description: r.material_name, quantity: Number(r.quantity), unit: r.unit, unit_cost: r.best_known_cost || 0, integration_provider: isAbc ? "abc_supply" : null })) });
      }
      toast.success(`Created ${Object.keys(groups).length} draft PO(s)`); setOpen(false); onCreated && onCreated();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  return (
    <>
      <Button variant="outline" onClick={openDialog} data-testid="reorder-suggestions-button"><Sparkles className="h-4 w-4" /> Reorder Suggestions</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto" data-testid="reorder-dialog">
          <DialogHeader><DialogTitle>Reorder Suggestions</DialogTitle><DialogDescription>Materials whose projected quantity is below the reorder threshold (inbound On Order already accounted for). Turn selections into draft POs — nothing is auto-ordered.</DialogDescription></DialogHeader>
          {loading ? <div className="py-8 text-center"><Loader2 className="mx-auto h-5 w-5 animate-spin text-slate-400" /></div> : rows.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-400" data-testid="reorder-empty">No reorder needed — projected stock covers all thresholds.</p>
          ) : (
            <div className="rounded-md border border-border">
              <Table><TableHeader><TableRow><TableHead className="w-8" /><TableHead>Material</TableHead><TableHead className="text-right">Projected</TableHead><TableHead className="text-right">Threshold</TableHead><TableHead className="text-right w-24">Order Qty</TableHead><TableHead>Preferred</TableHead></TableRow></TableHeader>
                <TableBody>{rows.map((r, i) => (
                  <TableRow key={r.material_id} data-testid={`reorder-row-${r.material_id}`}>
                    <TableCell><input type="checkbox" checked={r.include} onChange={(e) => setRows((rs) => rs.map((x, idx) => idx === i ? { ...x, include: e.target.checked } : x))} data-testid={`reorder-include-${i}`} /></TableCell>
                    <TableCell className="font-medium text-slate-800">{r.material_name}</TableCell>
                    <TableCell className="text-right tabular-nums">{r.projected} {r.unit}</TableCell>
                    <TableCell className="text-right tabular-nums text-slate-500">{r.reorder_threshold}</TableCell>
                    <TableCell><Input type="number" value={r.quantity} onChange={(e) => setRows((rs) => rs.map((x, idx) => idx === i ? { ...x, quantity: e.target.value } : x))} className="h-8" data-testid={`reorder-qty-${i}`} /></TableCell>
                    <TableCell className="text-sm">{r.preferred_supplier || <span className="text-amber-600">none</span>}</TableCell>
                  </TableRow>
                ))}</TableBody>
              </Table>
            </div>
          )}
          <DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Close</Button><Button onClick={createDraft} disabled={busy || rows.length === 0} data-testid="reorder-create-po">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create draft PO(s)"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

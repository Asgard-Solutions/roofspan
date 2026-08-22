import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money } from "@/lib/format";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Boxes, Wand2, Lock, Unlock, ShoppingCart, Loader2, Eye, Star, AlertTriangle } from "lucide-react";

const READINESS = {
  ready: { label: "Ready", cls: "bg-green-50 text-green-700" },
  partially_ready: { label: "Partially Ready", cls: "bg-blue-50 text-blue-700" },
  waiting_on_materials: { label: "Waiting on Materials", cls: "bg-amber-50 text-amber-700" },
  backordered: { label: "Backordered", cls: "bg-red-50 text-red-700" },
};

function Readiness({ status, testid }) {
  const r = READINESS[status] || READINESS.waiting_on_materials;
  return <Badge variant="secondary" className={r.cls} data-testid={testid}>{r.label}</Badge>;
}

export default function JobMaterialPlan({ jobId, canManage }) {
  const navigate = useNavigate();
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [proposal, setProposal] = useState(null);

  const load = useCallback(async () => {
    try { const { data } = await api.get(`/jobs/${jobId}/material-plan`); setPlan(data); }
    catch (e) { toast.error(apiError(e)); }
  }, [jobId]);
  useEffect(() => { load(); }, [load]);

  const generate = async () => {
    setBusy(true);
    try { const { data } = await api.post(`/jobs/${jobId}/materials/generate`); toast.success(`Generated ${data.created} material line${data.created === 1 ? "" : "s"}${data.skipped ? `, ${data.skipped} already present` : ""}`); load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const reserve = async (jm) => { try { const { data } = await api.post(`/jobs/${jobId}/materials/${jm.id}/reserve`, {}); toast.success(`Reserved ${data.reserved} ${jm.unit}`); load(); } catch (e) { toast.error(apiError(e)); } };
  const release = async (jm) => { try { await api.post(`/jobs/${jobId}/materials/${jm.id}/release`); toast.success("Reservation released"); load(); } catch (e) { toast.error(apiError(e)); } };

  const openProposal = async () => {
    try {
      const { data } = await api.get(`/jobs/${jobId}/purchase-proposal`);
      if (!data.lines.length) { toast.info("No shortages to order"); return; }
      setProposal({ ...data, rows: data.lines.map((l) => ({ ...l, quantity: l.suggested_quantity,
        supplier_id: l.preferred?.supplier_id || l.best_known?.supplier_id || l.suppliers[0]?.supplier_id || "",
        include: true })) });
    } catch (e) { toast.error(apiError(e)); }
  };

  const createPOs = async () => {
    const rows = proposal.rows.filter((r) => r.include && r.supplier_id && Number(r.quantity) > 0);
    if (!rows.length) { toast.error("Select at least one line with a supplier"); return; }
    // group by supplier -> one draft PO each, linked to the job
    const groups = {};
    rows.forEach((r) => { (groups[r.supplier_id] = groups[r.supplier_id] || []).push(r); });
    setBusy(true);
    try {
      for (const [sid, lines] of Object.entries(groups)) {
        await api.post("/purchase-orders", { supplier_id: sid, job_id: jobId,
          items: lines.map((r) => { const opt = r.suppliers.find((o) => o.supplier_id === sid) || {};
            return { material_id: r.material_id, description: r.material_name, quantity: Number(r.quantity), unit: r.unit, unit_cost: opt.current_cost || 0 }; }) });
      }
      toast.success(`Created ${Object.keys(groups).length} draft PO(s)`); setProposal(null); load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  if (!plan) return <div className="py-4"><Loader2 className="h-4 w-4 animate-spin text-slate-400" /></div>;
  const anyShortage = plan.materials.some((m) => m.shortage > 0);

  return (
    <div data-testid="job-material-plan">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm text-slate-500">Job readiness: <Readiness status={plan.job_status} testid="job-readiness" /></div>
        {canManage && (
          <div className="flex flex-wrap gap-2">
            {plan.can_generate && <Button size="sm" variant="outline" onClick={generate} disabled={busy} data-testid="generate-materials"><Wand2 className="h-4 w-4" /> Generate from quote</Button>}
            {anyShortage && <Button size="sm" onClick={openProposal} data-testid="create-po-shortage"><ShoppingCart className="h-4 w-4" /> Create PO for shortages</Button>}
          </div>
        )}
      </div>

      {plan.materials.length === 0 ? (
        <p className="text-sm text-slate-500" data-testid="plan-empty">No material plan yet.{plan.can_generate ? " Generate it from the accepted quote." : " Add materials manually."}</p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-border bg-white">
          <Table data-testid="plan-table">
            <TableHeader><TableRow>
              <TableHead>Material</TableHead><TableHead className="text-right">Required</TableHead><TableHead className="text-right">Reserved</TableHead>
              <TableHead className="text-right">Available</TableHead><TableHead className="text-right">Shortage</TableHead>
              <TableHead className="text-right">Ordered</TableHead><TableHead className="text-right">Received</TableHead>
              <TableHead>Status</TableHead><TableHead />
            </TableRow></TableHeader>
            <TableBody>
              {plan.materials.map((m) => (
                <TableRow key={m.id} data-testid={`plan-row-${m.id}`}>
                  <TableCell>
                    <div className="cursor-pointer font-medium text-slate-800 hover:text-orange-600" onClick={() => navigate(`/inventory/materials/${m.material_id}`)} data-testid={`plan-material-${m.id}`}>{m.material_name}</div>
                    <div className="text-xs text-slate-400">{m.preferred_supplier ? <span className="inline-flex items-center gap-0.5"><Star className="h-2.5 w-2.5 fill-indigo-500 text-indigo-500" />{m.preferred_supplier}</span> : ""}{m.best_known_cost != null ? ` · best ${money(m.best_known_cost)}` : ""}</div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{m.required} {m.unit}</TableCell>
                  <TableCell className="text-right tabular-nums">{m.reserved}</TableCell>
                  <TableCell className="text-right tabular-nums">{m.available}</TableCell>
                  <TableCell className={`text-right tabular-nums ${m.shortage > 0 ? "font-semibold text-red-600" : "text-slate-400"}`} data-testid={`plan-shortage-${m.id}`}>{m.shortage}</TableCell>
                  <TableCell className="text-right tabular-nums">{m.ordered}</TableCell>
                  <TableCell className="text-right tabular-nums">{m.received}</TableCell>
                  <TableCell><Readiness status={m.status} testid={`plan-status-${m.id}`} /></TableCell>
                  <TableCell className="text-right">
                    {canManage && (m.reserved > 0
                      ? <Button size="sm" variant="ghost" onClick={() => release(m)} data-testid={`release-${m.id}`}><Unlock className="h-4 w-4" /> Release</Button>
                      : <Button size="sm" variant="ghost" disabled={m.available <= 0} onClick={() => reserve(m)} data-testid={`reserve-${m.id}`}><Lock className="h-4 w-4" /> Reserve</Button>)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={!!proposal} onOpenChange={(o) => !o && setProposal(null)}>
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto" data-testid="po-proposal-dialog">
          <DialogHeader><DialogTitle>Purchasing proposal — {proposal?.job_number}</DialogTitle><DialogDescription>Review shortages, choose a supplier per line, then create draft POs (grouped by supplier). Nothing is submitted automatically.</DialogDescription></DialogHeader>
          {proposal && <div className="space-y-2">
            {proposal.rows.map((r, i) => (
              <div key={r.job_material_id} className="grid grid-cols-[20px_1fr_90px_1fr] items-center gap-2 rounded border border-border p-2" data-testid={`proposal-row-${i}`}>
                <input type="checkbox" checked={r.include} onChange={(e) => setProposal((p) => ({ ...p, rows: p.rows.map((x, idx) => idx === i ? { ...x, include: e.target.checked } : x) }))} data-testid={`proposal-include-${i}`} />
                <div><div className="text-sm font-medium text-slate-800">{r.material_name}</div><div className="text-xs text-red-500">short {r.shortage} {r.unit}</div></div>
                <Input type="number" value={r.quantity} onChange={(e) => setProposal((p) => ({ ...p, rows: p.rows.map((x, idx) => idx === i ? { ...x, quantity: e.target.value } : x) }))} className="h-8" data-testid={`proposal-qty-${i}`} />
                <Select value={r.supplier_id} onValueChange={(v) => setProposal((p) => ({ ...p, rows: p.rows.map((x, idx) => idx === i ? { ...x, supplier_id: v } : x) }))}>
                  <SelectTrigger className="h-8" data-testid={`proposal-supplier-${i}`}><SelectValue placeholder="Supplier" /></SelectTrigger>
                  <SelectContent>{r.suppliers.map((o) => <SelectItem key={o.supplier_material_id} value={o.supplier_id}>{o.supplier_name}{o.is_preferred ? " ★" : ""}{o.current_cost != null ? ` · ${money(o.current_cost)}` : ""}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            ))}
            {proposal.rows.length === 0 && <p className="text-sm text-slate-400">No shortages.</p>}
          </div>}
          <DialogFooter><Button variant="outline" onClick={() => setProposal(null)}>Cancel</Button><Button onClick={createPOs} disabled={busy} data-testid="proposal-create-pos">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create draft PO(s)"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

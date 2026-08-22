import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money } from "@/lib/format";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Loader2, Plus, Trash2, AlertTriangle, Camera, TrendingUp, TrendingDown } from "lucide-react";

const CATEGORIES = ["labor", "equipment", "subcontract", "permits", "disposal", "other"];
const STATUS = {
  complete: { label: "Complete", cls: "bg-green-50 text-green-700" },
  partial: { label: "Partial", cls: "bg-blue-50 text-blue-700" },
  not_started: { label: "Not Started", cls: "bg-slate-100 text-slate-600" },
  missing_cost_basis: { label: "Missing Cost Basis", cls: "bg-amber-50 text-amber-700" },
  no_estimate_baseline: { label: "No Estimate Baseline", cls: "bg-red-50 text-red-700" },
};
const BASIS = {
  complete: { label: "Costed", cls: "bg-green-50 text-green-700" },
  missing_cost_basis: { label: "No cost basis", cls: "bg-amber-50 text-amber-700" },
  no_activity: { label: "No activity", cls: "bg-slate-100 text-slate-500" },
};

function Money({ value, signed = false, invert = false }) {
  const v = Number(value || 0);
  const good = invert ? v <= 0 : v >= 0;
  const cls = signed ? (good ? "text-green-700" : "text-red-600") : "text-slate-900";
  return <span className={`tabular-nums ${cls}`}>{signed && v > 0 ? "+" : ""}{money(v)}</span>;
}

function Stat({ label, children, testid }) {
  return (
    <div className="rounded-md border border-border bg-slate-50/60 p-3" data-testid={testid}>
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold">{children}</div>
    </div>
  );
}

export default function JobCosting({ jobId, canManage }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ category: "labor", description: "", amount: "", notes: "" });

  const load = useCallback(async () => {
    setLoading(true);
    try { const { data } = await api.get(`/jobs/${jobId}/costing`); setData(data); }
    catch (e) { toast.error(apiError(e)); }
    finally { setLoading(false); }
  }, [jobId]);
  useEffect(() => { load(); }, [load]);

  const addEntry = async () => {
    if (!(Number(form.amount) >= 0) || form.amount === "") { toast.error("Enter a valid amount"); return; }
    setBusy(true);
    try {
      await api.post(`/jobs/${jobId}/actual-costs`, {
        category: form.category, description: form.description, amount: Number(form.amount), notes: form.notes || null });
      toast.success("Cost added");
      setAddOpen(false); setForm({ category: "labor", description: "", amount: "", notes: "" });
      load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const delEntry = async (id) => {
    try { await api.delete(`/jobs/${jobId}/actual-costs/${id}`); toast.success("Removed"); load(); }
    catch (e) { toast.error(apiError(e)); }
  };

  const snapshot = async () => {
    setBusy(true);
    try { await api.post(`/jobs/${jobId}/cost-snapshots`, { trigger: "manual" }); toast.success("Snapshot captured"); load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  if (loading) return <div className="flex items-center gap-2 text-sm text-slate-500" data-testid="costing-loading"><Loader2 className="h-4 w-4 animate-spin" /> Loading costing…</div>;
  if (!data) return <p className="text-sm text-slate-500">Costing unavailable.</p>;

  const s = data.summary;
  const st = STATUS[s.costing_status] || STATUS.partial;
  const gpDown = Number(s.actual.gross_profit) < Number(s.estimated.gross_profit);

  return (
    <div className="space-y-5" data-testid="job-costing">
      {/* status + warnings */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">Costing status</span>
          <Badge variant="secondary" className={st.cls} data-testid="costing-status-badge">{st.label}</Badge>
        </div>
        <div className="flex items-center gap-2">
          {data.latest_snapshot_at && <span className="text-xs text-slate-400" data-testid="costing-last-snapshot">Snapshot: {new Date(data.latest_snapshot_at).toLocaleString()}</span>}
          {canManage && <Button size="sm" variant="outline" onClick={snapshot} disabled={busy} data-testid="costing-snapshot-btn"><Camera className="h-4 w-4" /> Capture snapshot</Button>}
        </div>
      </div>

      {s.costing_status === "no_estimate_baseline" && (
        <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700" data-testid="costing-warn-nobaseline">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>No estimate baseline — this job isn't linked to an accepted quote/estimate with historical cost, so estimated vs actual comparison isn't available.</span>
        </div>
      )}
      {data.material_actual.has_missing_cost_basis && (
        <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800" data-testid="costing-warn-basis">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>Some issued material has no cost basis (received without a recorded unit cost). Actual material cost is understated until those receipts are priced.</span>
        </div>
      )}

      {/* headline stats */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Revenue (sold)" testid="costing-revenue"><Money value={s.revenue} /></Stat>
        <Stat label="Actual cost" testid="costing-actual-total"><Money value={s.actual.total} /></Stat>
        <Stat label="Actual gross profit" testid="costing-actual-gp">
          <span className="flex items-center gap-1"><Money value={s.actual.gross_profit} signed />{gpDown ? <TrendingDown className="h-4 w-4 text-red-500" /> : <TrendingUp className="h-4 w-4 text-green-600" />}</span>
        </Stat>
        <Stat label="Actual margin" testid="costing-actual-margin">
          <span className={Number(s.actual.gross_margin_percent) >= 0 ? "text-slate-900" : "text-red-600"}>{Number(s.actual.gross_margin_percent).toFixed(1)}%</span>
        </Stat>
      </div>

      {/* estimated vs actual by category */}
      <div>
        <h4 className="mb-2 text-sm font-semibold text-slate-700">Estimated vs actual</h4>
        <Table data-testid="costing-summary-table">
          <TableHeader>
            <TableRow>
              <TableHead>Category</TableHead>
              <TableHead className="text-right">Estimated</TableHead>
              <TableHead className="text-right">Actual</TableHead>
              <TableHead className="text-right">Variance</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {["material", "labor", "equipment", "subcontract", "permits", "disposal", "other"].map((c) => (
              <TableRow key={c} data-testid={`costing-row-${c}`}>
                <TableCell className="capitalize">{c}</TableCell>
                <TableCell className="text-right"><Money value={s.estimated[c]} /></TableCell>
                <TableCell className="text-right"><Money value={s.actual[c]} /></TableCell>
                <TableCell className="text-right"><Money value={s.variance[c]} signed invert /></TableCell>
              </TableRow>
            ))}
            <TableRow className="font-semibold">
              <TableCell>Total</TableCell>
              <TableCell className="text-right"><Money value={s.estimated.total} /></TableCell>
              <TableCell className="text-right"><Money value={s.actual.total} /></TableCell>
              <TableCell className="text-right"><Money value={s.variance.total} signed invert /></TableCell>
            </TableRow>
            <TableRow className="font-semibold">
              <TableCell>Gross profit</TableCell>
              <TableCell className="text-right"><Money value={s.estimated.gross_profit} signed /></TableCell>
              <TableCell className="text-right"><Money value={s.actual.gross_profit} signed /></TableCell>
              <TableCell className="text-right"><Money value={s.variance.gross_profit} signed /></TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>

      {/* material variance detail */}
      {data.material_actual.lines.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-slate-700">Material variance</h4>
          <Table data-testid="costing-material-table">
            <TableHeader>
              <TableRow>
                <TableHead>Material</TableHead>
                <TableHead className="text-right">Est. cost</TableHead>
                <TableHead className="text-right">Issued</TableHead>
                <TableHead className="text-right">Waste</TableHead>
                <TableHead className="text-right">Actual cost</TableHead>
                <TableHead className="text-right">Variance</TableHead>
                <TableHead>Basis</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.material_actual.lines.map((l) => {
                const b = BASIS[l.cost_basis_status] || BASIS.no_activity;
                return (
                  <TableRow key={l.material_id} data-testid={`costing-mat-${l.material_id}`}>
                    <TableCell className="max-w-[220px] truncate">{l.material_name}</TableCell>
                    <TableCell className="text-right"><Money value={l.estimated_material_cost} /></TableCell>
                    <TableCell className="text-right tabular-nums">{l.issued_quantity}</TableCell>
                    <TableCell className="text-right tabular-nums">{l.waste_quantity}</TableCell>
                    <TableCell className="text-right"><Money value={l.actual_material_cost} /></TableCell>
                    <TableCell className="text-right"><Money value={l.variance} signed invert /></TableCell>
                    <TableCell><Badge variant="secondary" className={b.cls}>{b.label}</Badge></TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {/* manual actual costs */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-sm font-semibold text-slate-700">Manual actual costs</h4>
          {canManage && <Button size="sm" variant="outline" onClick={() => setAddOpen(true)} data-testid="costing-add-cost"><Plus className="h-4 w-4" /> Add cost</Button>}
        </div>
        {data.manual_actual.entries.length === 0 ? (
          <p className="text-sm text-slate-500">No labor, equipment, or subcontract costs recorded yet.</p>
        ) : (
          <Table data-testid="costing-manual-table">
            <TableHeader>
              <TableRow>
                <TableHead>Category</TableHead>
                <TableHead>Description</TableHead>
                <TableHead className="text-right">Amount</TableHead>
                {canManage && <TableHead className="w-10" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.manual_actual.entries.map((e) => (
                <TableRow key={e.id} data-testid={`costing-entry-${e.id}`}>
                  <TableCell className="capitalize">{e.category}</TableCell>
                  <TableCell className="max-w-[280px] truncate text-slate-600">{e.description || "—"}{e.notes ? ` · ${e.notes}` : ""}</TableCell>
                  <TableCell className="text-right"><Money value={e.amount} /></TableCell>
                  {canManage && <TableCell><Button size="icon" variant="ghost" onClick={() => delEntry(e.id)} data-testid={`costing-del-${e.id}`}><Trash2 className="h-4 w-4 text-red-500" /></Button></TableCell>}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent data-testid="costing-add-dialog">
          <DialogHeader><DialogTitle>Add actual cost</DialogTitle><DialogDescription>Record a labor, equipment, subcontract, permit, disposal or other cost for this job.</DialogDescription></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5"><Label>Category</Label>
              <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}>
                <SelectTrigger data-testid="costing-cat-select"><SelectValue /></SelectTrigger>
                <SelectContent>{CATEGORIES.map((c) => <SelectItem key={c} value={c} data-testid={`costing-cat-${c}`}><span className="capitalize">{c}</span></SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5"><Label>Description</Label><Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="e.g. Crew day 1" data-testid="costing-desc-input" /></div>
            <div className="space-y-1.5"><Label>Amount ($)</Label><Input type="number" min="0" step="0.01" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} data-testid="costing-amount-input" /></div>
            <div className="space-y-1.5"><Label>Notes</Label><Textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} data-testid="costing-notes-input" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button onClick={addEntry} disabled={busy} data-testid="costing-save-cost">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Add cost"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

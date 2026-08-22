import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ArrowLeft, ScrollText } from "lucide-react";

const TYPES = ["initial_inventory", "receipt", "job_reservation", "job_issue", "job_return", "transfer", "waste", "damage", "loss", "cycle_count", "adjustment"];

export default function InventoryTransactions() {
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [f, setF] = useState({ material_id: "all", location_id: "all", reason: "all" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = { limit: 200 };
      if (f.material_id !== "all") p.material_id = f.material_id;
      if (f.location_id !== "all") p.location_id = f.location_id;
      if (f.reason !== "all") p.reason = f.reason;
      const { data } = await api.get("/inventory/transactions", { params: p });
      setRows(data.transactions);
    } catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  }, [f]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api.get("/materials", { params: { active: true } }).then((r) => setMaterials(r.data)).catch(() => {});
    api.get("/inventory/locations").then((r) => setLocations(r.data)).catch(() => {});
  }, []);

  return (
    <div>
      <PageHeader title="Inventory Transactions" description="Immutable ledger of every physical inventory movement." testid="page-inventory-transactions" />
      <div className="p-6 sm:p-8">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => navigate("/inventory")} data-testid="txns-back"><ArrowLeft className="h-4 w-4" /> Inventory</Button>
          <Select value={f.material_id} onValueChange={(v) => setF({ ...f, material_id: v })}><SelectTrigger className="w-56" data-testid="txn-filter-material"><SelectValue placeholder="Material" /></SelectTrigger><SelectContent className="max-h-72"><SelectItem value="all">All materials</SelectItem>{materials.map((m) => <SelectItem key={m.id} value={m.id}>{m.name}</SelectItem>)}</SelectContent></Select>
          <Select value={f.location_id} onValueChange={(v) => setF({ ...f, location_id: v })}><SelectTrigger className="w-44" data-testid="txn-filter-location"><SelectValue placeholder="Location" /></SelectTrigger><SelectContent><SelectItem value="all">All locations</SelectItem>{locations.map((l) => <SelectItem key={l.id} value={l.id}>{l.name}</SelectItem>)}</SelectContent></Select>
          <Select value={f.reason} onValueChange={(v) => setF({ ...f, reason: v })}><SelectTrigger className="w-44" data-testid="txn-filter-type"><SelectValue placeholder="Type" /></SelectTrigger><SelectContent><SelectItem value="all">All types</SelectItem>{TYPES.map((t) => <SelectItem key={t} value={t}>{t.replace(/_/g, " ")}</SelectItem>)}</SelectContent></Select>
        </div>
        <div className="overflow-x-auto rounded-md border border-border bg-white">
          <Table data-testid="transactions-table">
            <TableHeader><TableRow><TableHead>When</TableHead><TableHead>Material</TableHead><TableHead className="text-right">Δ</TableHead><TableHead>Type</TableHead><TableHead>From</TableHead><TableHead>To</TableHead><TableHead>Job / PO</TableHead><TableHead>User</TableHead></TableRow></TableHeader>
            <TableBody>
              {rows.map((t) => (
                <TableRow key={t.id} data-testid={`txn-row-${t.id}`}>
                  <TableCell className="text-xs text-slate-500">{t.created_at ? new Date(t.created_at).toLocaleString() : "—"}</TableCell>
                  <TableCell className="font-medium text-slate-800">{t.material_name}</TableCell>
                  <TableCell className={`text-right tabular-nums ${t.delta > 0 ? "text-green-600" : t.delta < 0 ? "text-red-600" : "text-slate-400"}`}>{t.delta > 0 ? "+" : ""}{t.delta}</TableCell>
                  <TableCell><Badge variant="secondary" className="bg-slate-100 text-slate-600">{t.reason.replace(/_/g, " ")}</Badge></TableCell>
                  <TableCell className="text-xs text-slate-500">{t.source_location || "—"}</TableCell>
                  <TableCell className="text-xs text-slate-500">{t.destination_location || "—"}</TableCell>
                  <TableCell className="text-xs">{t.job_id ? <button className="text-orange-600 hover:underline" onClick={() => navigate(`/jobs/${t.job_id}`)}>job</button> : ""}{t.po_id ? <button className="ml-1 text-orange-600 hover:underline" onClick={() => navigate(`/purchase-orders/${t.po_id}`)}>PO</button> : ""}{!t.job_id && !t.po_id ? "—" : ""}</TableCell>
                  <TableCell className="text-xs text-slate-400">{t.created_by || "—"}</TableCell>
                </TableRow>
              ))}
              {!loading && rows.length === 0 && <TableRow><TableCell colSpan={8} className="py-8 text-center text-slate-400" data-testid="txns-empty">No transactions.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}

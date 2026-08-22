import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { money } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Loader2, Lock, BarChart3 } from "lucide-react";

const MANAGE = ["owner", "administrator", "office"];

function Money({ value, signed = false, invert = false }) {
  const v = Number(value || 0);
  const good = invert ? v <= 0 : v >= 0;
  const cls = signed ? (good ? "text-green-700" : "text-red-600") : "text-slate-900";
  return <span className={`tabular-nums ${cls}`}>{signed && v > 0 ? "+" : ""}{money(v)}</span>;
}

function useReport(path, enabled) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    if (!enabled) { setLoading(false); return; }
    setLoading(true);
    try { setData((await api.get(path)).data); }
    catch (e) { toast.error(apiError(e)); }
    finally { setLoading(false); }
  }, [path, enabled]);
  useEffect(() => { load(); }, [load]);
  return { data, loading };
}

function Loading() { return <div className="flex items-center gap-2 py-6 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>; }

function Profitability({ enabled }) {
  const { data, loading } = useReport("/reports/costing/profitability", enabled);
  if (loading) return <Loading />;
  if (!data) return null;
  return (
    <Table data-testid="report-profitability-table">
      <TableHeader><TableRow>
        <TableHead>Job</TableHead><TableHead>Status</TableHead>
        <TableHead className="text-right">Revenue</TableHead><TableHead className="text-right">Est. cost</TableHead>
        <TableHead className="text-right">Actual cost</TableHead><TableHead className="text-right">Gross profit</TableHead>
        <TableHead className="text-right">Margin</TableHead>
      </TableRow></TableHeader>
      <TableBody>
        {data.rows.length === 0 && <TableRow><TableCell colSpan={7} className="text-center text-slate-500">No costed jobs yet.</TableCell></TableRow>}
        {data.rows.map((r) => (
          <TableRow key={r.job_id} data-testid={`report-prof-${r.job_id}`}>
            <TableCell className="font-medium">{r.job_number}</TableCell>
            <TableCell><Badge variant="secondary" className="capitalize">{(r.costing_status || "").replace(/_/g, " ")}</Badge></TableCell>
            <TableCell className="text-right"><Money value={r.revenue} /></TableCell>
            <TableCell className="text-right"><Money value={r.estimated_cost} /></TableCell>
            <TableCell className="text-right"><Money value={r.actual_cost} /></TableCell>
            <TableCell className="text-right"><Money value={r.actual_gross_profit} signed /></TableCell>
            <TableCell className="text-right">{Number(r.actual_gross_margin_percent).toFixed(1)}%</TableCell>
          </TableRow>
        ))}
        {data.rows.length > 0 && (
          <TableRow className="font-semibold">
            <TableCell colSpan={2}>Totals</TableCell>
            <TableCell className="text-right"><Money value={data.totals.revenue} /></TableCell>
            <TableCell className="text-right"><Money value={data.totals.estimated_cost} /></TableCell>
            <TableCell className="text-right"><Money value={data.totals.actual_cost} /></TableCell>
            <TableCell className="text-right"><Money value={data.totals.actual_gross_profit} signed /></TableCell>
            <TableCell className="text-right">{Number(data.totals.actual_gross_margin_percent).toFixed(1)}%</TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  );
}

function MaterialVariance({ enabled }) {
  const { data, loading } = useReport("/reports/costing/material-variance", enabled);
  if (loading) return <Loading />;
  if (!data) return null;
  return (
    <Table data-testid="report-material-variance-table">
      <TableHeader><TableRow>
        <TableHead>Material</TableHead><TableHead className="text-right">Est. cost</TableHead>
        <TableHead className="text-right">Actual cost</TableHead><TableHead className="text-right">Variance</TableHead>
        <TableHead className="text-right">Waste cost</TableHead><TableHead>Basis</TableHead>
      </TableRow></TableHeader>
      <TableBody>
        {data.rows.length === 0 && <TableRow><TableCell colSpan={6} className="text-center text-slate-500">No material activity yet.</TableCell></TableRow>}
        {data.rows.map((r) => (
          <TableRow key={r.material_id} data-testid={`report-matvar-${r.material_id}`}>
            <TableCell className="max-w-[260px] truncate font-medium">{r.material_name}</TableCell>
            <TableCell className="text-right"><Money value={r.estimated_cost} /></TableCell>
            <TableCell className="text-right"><Money value={r.actual_cost} /></TableCell>
            <TableCell className="text-right"><Money value={r.variance} signed invert /></TableCell>
            <TableCell className="text-right"><Money value={r.waste_cost} /></TableCell>
            <TableCell>{r.missing_cost_basis ? <Badge variant="secondary" className="bg-amber-50 text-amber-700">Missing</Badge> : <Badge variant="secondary" className="bg-green-50 text-green-700">Costed</Badge>}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function Waste({ enabled }) {
  const { data, loading } = useReport("/reports/costing/waste", enabled);
  if (loading) return <Loading />;
  if (!data) return null;
  return (
    <>
      <div className="mb-3 text-sm text-slate-600">Total waste / damage / loss cost: <span className="font-semibold text-red-600">{money(data.total_waste_cost)}</span></div>
      <Table data-testid="report-waste-table">
        <TableHeader><TableRow><TableHead>Material</TableHead><TableHead className="text-right">Waste qty</TableHead><TableHead className="text-right">Waste cost</TableHead></TableRow></TableHeader>
        <TableBody>
          {data.rows.length === 0 && <TableRow><TableCell colSpan={3} className="text-center text-slate-500">No waste recorded.</TableCell></TableRow>}
          {data.rows.map((r) => (
            <TableRow key={r.material_id} data-testid={`report-waste-${r.material_id}`}>
              <TableCell className="max-w-[300px] truncate font-medium">{r.material_name}</TableCell>
              <TableCell className="text-right tabular-nums">{r.waste_quantity}</TableCell>
              <TableCell className="text-right"><Money value={r.waste_cost} /></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  );
}

function SupplierImpact({ enabled }) {
  const { data, loading } = useReport("/reports/costing/supplier-impact", enabled);
  if (loading) return <Loading />;
  if (!data) return null;
  return (
    <>
      <div className="mb-3 text-sm text-slate-600">Total received cost: <span className="font-semibold">{money(data.total_received_cost)}</span></div>
      <Table data-testid="report-supplier-table">
        <TableHeader><TableRow><TableHead>Supplier</TableHead><TableHead className="text-right">POs received</TableHead><TableHead className="text-right">Received cost</TableHead></TableRow></TableHeader>
        <TableBody>
          {data.rows.length === 0 && <TableRow><TableCell colSpan={3} className="text-center text-slate-500">No received purchase orders yet.</TableCell></TableRow>}
          {data.rows.map((r, i) => (
            <TableRow key={r.supplier_id || i} data-testid={`report-supplier-${r.supplier_id || i}`}>
              <TableCell className="font-medium">{r.supplier_name}</TableCell>
              <TableCell className="text-right tabular-nums">{r.po_count}</TableCell>
              <TableCell className="text-right"><Money value={r.received_cost} /></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  );
}

export default function Reports() {
  const { user } = useAuth();
  const canView = MANAGE.includes(user?.role);
  const [tab, setTab] = useState("profitability");

  if (!canView) {
    return (
      <div className="space-y-6">
        <PageHeader title="Reports" description="Cost & profitability reporting" />
        <div className="flex items-center gap-3 rounded-md border border-border bg-white p-6 text-sm text-slate-600" data-testid="reports-restricted">
          <Lock className="h-5 w-5 text-slate-400" />
          Cost and profitability reports are restricted to management roles.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="reports-page">
      <PageHeader title="Reports" description="Job cost & profitability" />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList data-testid="reports-tabs">
          <TabsTrigger value="profitability" data-testid="tab-profitability">Profitability</TabsTrigger>
          <TabsTrigger value="material-variance" data-testid="tab-material-variance">Material variance</TabsTrigger>
          <TabsTrigger value="waste" data-testid="tab-waste">Waste</TabsTrigger>
          <TabsTrigger value="supplier" data-testid="tab-supplier">Supplier impact</TabsTrigger>
        </TabsList>
        <div className="mt-4 rounded-md border border-border bg-white p-4">
          <TabsContent value="profitability"><Profitability enabled={tab === "profitability"} /></TabsContent>
          <TabsContent value="material-variance"><MaterialVariance enabled={tab === "material-variance"} /></TabsContent>
          <TabsContent value="waste"><Waste enabled={tab === "waste"} /></TabsContent>
          <TabsContent value="supplier"><SupplierImpact enabled={tab === "supplier"} /></TabsContent>
        </div>
      </Tabs>
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money, shortDate } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { FileText } from "lucide-react";
import InvoiceDocumentDialog from "@/components/InvoiceDocumentDialog";

const sc = { draft: "bg-slate-100 text-slate-600", issued: "bg-blue-50 text-blue-700", paid: "bg-green-50 text-green-700", void: "bg-slate-100 text-slate-500" };
const INV_STATUS = ["draft", "issued", "paid", "void"];
const FILTERS = [["open", "Balance due"], ["overdue", "Overdue"], ["paid", "Paid"], ["all", "All"]];

const isOverdue = (i) => i.status === "issued" && i.due_date && new Date(i.due_date) < new Date();

function Summary({ label, value, sub, tone, testid }) {
  return (
    <div className="rounded-md border border-border bg-white p-5" data-testid={testid}>
      <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</div>
      <div className={`mt-1.5 font-heading text-2xl font-bold ${tone || "text-slate-900"}`}>{value}</div>
      {sub && <div className="text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

export default function Billing() {
  const [invoices, setInvoices] = useState([]);
  const [filter, setFilter] = useState("open");
  const [viewId, setViewId] = useState(null);
  const load = () => api.get("/invoices").then((r) => setInvoices(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);

  const setStatus = async (id, status) => {
    try { await api.post(`/invoices/${id}/status`, { status }); toast.success("Invoice updated"); load(); }
    catch (e) { toast.error(apiError(e)); }
  };

  const open = invoices.filter((i) => i.status === "issued");
  const overdue = open.filter(isOverdue);
  const paid = invoices.filter((i) => i.status === "paid");
  const sum = (arr) => arr.reduce((s, i) => s + (Number(i.total) || 0), 0);
  const rows = useMemo(() => ({ open, overdue, paid, all: invoices }[filter]), [filter, invoices]); // eslint-disable-line

  return (
    <div>
      <PageHeader title="Billing" description="Invoices, balances due and payment status" testid="page-billing" />
      <div className="space-y-6 p-6 sm:p-8">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Summary label="Balance due" value={money(sum(open))} sub={`${open.length} open invoice${open.length === 1 ? "" : "s"}`} testid="billing-balance-due" />
          <Summary label="Overdue" value={money(sum(overdue))} sub={`${overdue.length} past due date`} tone={overdue.length ? "text-red-600" : ""} testid="billing-overdue" />
          <Summary label="Paid" value={money(sum(paid))} sub={`${paid.length} invoice${paid.length === 1 ? "" : "s"}`} tone="text-emerald-700" testid="billing-paid" />
        </div>
        <div className="flex flex-wrap gap-2" data-testid="billing-filters">
          {FILTERS.map(([k, l]) => (
            <Button key={k} size="sm" variant={filter === k ? "default" : "outline"} onClick={() => setFilter(k)} data-testid={`billing-filter-${k}`}>{l}</Button>
          ))}
        </div>
        <div className="overflow-x-auto rounded-md border border-border bg-white">
          <Table data-testid="invoices-table">
            <TableHeader><TableRow><TableHead>Invoice #</TableHead><TableHead>Amount</TableHead><TableHead>Issued</TableHead><TableHead>Due</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
            <TableBody>
              {rows.map((inv) => (
                <TableRow key={inv.id} data-testid={`fin-invoice-${inv.id}`}>
                  <TableCell className="font-medium text-slate-900">{inv.number}</TableCell>
                  <TableCell className="tabular-nums">{money(inv.total)}</TableCell>
                  <TableCell className="text-slate-500">{shortDate(inv.issue_date)}</TableCell>
                  <TableCell className={isOverdue(inv) ? "font-medium text-red-600" : "text-slate-500"} data-testid={`invoice-due-${inv.id}`}>{shortDate(inv.due_date)}{isOverdue(inv) ? " · overdue" : ""}</TableCell>
                  <TableCell>
                    <Select value={inv.status} onValueChange={(v) => setStatus(inv.id, v)}>
                      <SelectTrigger className="h-8 w-[120px]" data-testid={`invoice-status-${inv.id}`}><Badge className={sc[inv.status] || ""} variant="secondary">{inv.status}</Badge></SelectTrigger>
                      <SelectContent>{INV_STATUS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button variant="outline" size="sm" onClick={() => setViewId(inv.id)} data-testid={`invoice-view-${inv.id}`}><FileText className="h-3.5 w-3.5" /> View / Send</Button>
                  </TableCell>
                </TableRow>
              ))}
              {rows.length === 0 && <TableRow><TableCell colSpan={6} className="text-center text-sm text-slate-400">No invoices here.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
        <p className="text-xs text-slate-400">RoofSpan records invoices and payment status. Payments themselves are collected outside RoofSpan.</p>
      </div>
      <InvoiceDocumentDialog invoiceId={viewId} open={!!viewId} onOpenChange={(v) => { if (!v) setViewId(null); }} onSent={load} />
    </div>
  );
}

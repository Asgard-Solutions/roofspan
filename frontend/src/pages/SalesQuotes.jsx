import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { money, shortDate } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FileText } from "lucide-react";
import InvoiceDocumentDialog from "@/components/InvoiceDocumentDialog";

const sc = { draft: "bg-slate-100 text-slate-600", sent: "bg-blue-50 text-blue-700", accepted: "bg-green-50 text-green-700", declined: "bg-red-50 text-red-700", expired: "bg-slate-100 text-slate-500" };

export default function SalesQuotes() {
  const [quotes, setQuotes] = useState([]);
  const [viewId, setViewId] = useState(null);
  const load = () => api.get("/quotes").then((r) => setQuotes(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);
  const waiting = quotes.filter((q) => q.status === "sent").length;

  return (
    <div>
      <PageHeader title="Quotes & Proposals" description={waiting ? `${waiting} proposal${waiting === 1 ? "" : "s"} waiting on the customer` : "Every quote sent to a customer"} testid="page-sales-quotes" />
      <div className="p-6 sm:p-8">
        <div className="overflow-x-auto rounded-md border border-border bg-white">
          <Table data-testid="quotes-table">
            <TableHeader><TableRow><TableHead>Quote #</TableHead><TableHead>Status</TableHead><TableHead>Total</TableHead><TableHead>Issued</TableHead><TableHead>Expires</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
            <TableBody>
              {quotes.map((q) => (
                <TableRow key={q.id} data-testid={`sales-quote-${q.id}`}>
                  <TableCell className="font-medium text-slate-900">
                    {q.lead_id ? <Link to={`/leads/${q.lead_id}`} className="hover:text-orange-600 hover:underline" data-testid={`quote-lead-link-${q.id}`}>{q.number}</Link> : q.number}
                  </TableCell>
                  <TableCell><Badge className={sc[q.status] || ""} variant="secondary">{q.status}</Badge></TableCell>
                  <TableCell className="tabular-nums">{money(q.total)}</TableCell>
                  <TableCell className="text-slate-500">{shortDate(q.issue_date)}</TableCell>
                  <TableCell className="text-slate-500">{shortDate(q.expiration_date)}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="outline" size="sm" onClick={() => setViewId(q.id)} data-testid={`quote-view-${q.id}`}><FileText className="h-3.5 w-3.5" /> View / PDF</Button>
                  </TableCell>
                </TableRow>
              ))}
              {quotes.length === 0 && <TableRow><TableCell colSpan={6} className="text-center text-sm text-slate-400">No quotes yet. Build an estimate from a lead to create one.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
      </div>
      <InvoiceDocumentDialog docId={viewId} kind="quote" open={!!viewId} onOpenChange={(v) => { if (!v) setViewId(null); }} onSent={load} />
    </div>
  );
}

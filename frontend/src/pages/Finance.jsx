import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { money, shortDate } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { FileText } from "lucide-react";
import InvoiceDocumentDialog from "@/components/InvoiceDocumentDialog";

const sc = { draft: "bg-slate-100 text-slate-600", sent: "bg-blue-50 text-blue-700", accepted: "bg-green-50 text-green-700", declined: "bg-red-50 text-red-700", expired: "bg-slate-100 text-slate-500", issued: "bg-blue-50 text-blue-700", paid: "bg-green-50 text-green-700", void: "bg-slate-100 text-slate-500" };
const INV_STATUS = ["draft", "issued", "paid", "void"];

export default function Finance() {
  const { user } = useAuth();
  const isManage = ["owner", "administrator", "office"].includes(user?.role);
  const [quotes, setQuotes] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [viewInvoiceId, setViewInvoiceId] = useState(null);
  const [viewQuoteId, setViewQuoteId] = useState(null);

  const load = () => {
    api.get("/quotes").then((r) => setQuotes(r.data)).catch(() => {});
    if (isManage) api.get("/invoices").then((r) => setInvoices(r.data)).catch(() => {});
  };
  useEffect(() => { load(); }, []); // eslint-disable-line

  const setInvStatus = async (id, status) => {
    try { await api.post(`/invoices/${id}/status`, { status }); toast.success("Invoice updated"); load(); }
    catch (e) { toast.error(apiError(e)); }
  };

  return (
    <div>
      <PageHeader title="Finance" description="Quotes and invoice records (records only — RoofSpan is not a payment processor)" testid="page-finance" />
      <div className="p-6 sm:p-8">
        <Tabs defaultValue="quotes">
          <TabsList data-testid="finance-tabs">
            <TabsTrigger value="quotes" data-testid="tab-quotes">Quotes</TabsTrigger>
            {isManage && <TabsTrigger value="invoices" data-testid="tab-invoices">Invoices</TabsTrigger>}
          </TabsList>

          <TabsContent value="quotes" className="mt-6">
            <div className="overflow-x-auto rounded-md border border-border bg-white">
              <Table data-testid="quotes-table">
                <TableHeader><TableRow><TableHead>Quote #</TableHead><TableHead>Status</TableHead><TableHead>Total</TableHead><TableHead>Issued</TableHead><TableHead>Expires</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
                <TableBody>
                  {quotes.map((q) => (
                    <TableRow key={q.id} data-testid={`fin-quote-${q.id}`}>
                      <TableCell className="font-medium text-slate-900">{q.number}</TableCell>
                      <TableCell><Badge className={sc[q.status] || ""} variant="secondary">{q.status}</Badge></TableCell>
                      <TableCell className="tabular-nums">{money(q.total)}</TableCell>
                      <TableCell className="text-slate-500">{shortDate(q.issue_date)}</TableCell>
                      <TableCell className="text-slate-500">{shortDate(q.expiration_date)}</TableCell>
                      <TableCell className="text-right">
                        <Button variant="outline" size="sm" onClick={() => setViewQuoteId(q.id)} data-testid={`quote-view-${q.id}`}>
                          <FileText className="h-3.5 w-3.5" /> View / PDF
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                  {quotes.length === 0 && <TableRow><TableCell colSpan={6} className="text-center text-sm text-slate-400">No quotes.</TableCell></TableRow>}
                </TableBody>
              </Table>
            </div>
          </TabsContent>

          {isManage && (
            <TabsContent value="invoices" className="mt-6">
              <div className="overflow-x-auto rounded-md border border-border bg-white">
                <Table data-testid="invoices-table">
                  <TableHeader><TableRow><TableHead>Invoice #</TableHead><TableHead>Total</TableHead><TableHead>Issued</TableHead><TableHead>Due</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {invoices.map((inv) => (
                      <TableRow key={inv.id} data-testid={`fin-invoice-${inv.id}`}>
                        <TableCell className="font-medium text-slate-900">{inv.number}</TableCell>
                        <TableCell className="tabular-nums">{money(inv.total)}</TableCell>
                        <TableCell className="text-slate-500">{shortDate(inv.issue_date)}</TableCell>
                        <TableCell className="text-slate-500">{shortDate(inv.due_date)}</TableCell>
                        <TableCell>
                          <Select value={inv.status} onValueChange={(v) => setInvStatus(inv.id, v)}>
                            <SelectTrigger className="h-8 w-[120px]" data-testid={`invoice-status-${inv.id}`}>
                              <Badge className={sc[inv.status] || ""} variant="secondary">{inv.status}</Badge>
                            </SelectTrigger>
                            <SelectContent>{INV_STATUS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                          </Select>
                        </TableCell>
                        <TableCell className="text-right">
                          <Button variant="outline" size="sm" onClick={() => setViewInvoiceId(inv.id)} data-testid={`invoice-view-${inv.id}`}>
                            <FileText className="h-3.5 w-3.5" /> View / Send
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                    {invoices.length === 0 && <TableRow><TableCell colSpan={6} className="text-center text-sm text-slate-400">No invoices.</TableCell></TableRow>}
                  </TableBody>
                </Table>
              </div>
            </TabsContent>
          )}
        </Tabs>
      </div>
      <InvoiceDocumentDialog invoiceId={viewInvoiceId} open={!!viewInvoiceId}
        onOpenChange={(v) => { if (!v) setViewInvoiceId(null); }} onSent={load} />
      <InvoiceDocumentDialog docId={viewQuoteId} kind="quote" open={!!viewQuoteId}
        onOpenChange={(v) => { if (!v) setViewQuoteId(null); }} onSent={load} />
    </div>
  );
}

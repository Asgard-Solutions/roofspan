import { useState, useEffect } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money, shortDate } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Loader2, Printer, FileDown, Mail } from "lucide-react";

export default function InvoiceDocumentDialog({ invoiceId, open, onOpenChange, onSent }) {
  const [doc, setDoc] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    if (!open || !invoiceId) return;
    setLoading(true);
    api.get(`/invoices/${invoiceId}/document`).then((r) => setDoc(r.data))
      .catch((e) => { toast.error(apiError(e)); onOpenChange(false); })
      .finally(() => setLoading(false));
  }, [open, invoiceId]); // eslint-disable-line

  const pdfBlob = async () => {
    const r = await api.get(`/invoices/${invoiceId}/pdf`, { responseType: "blob" });
    return window.URL.createObjectURL(new Blob([r.data], { type: "application/pdf" }));
  };

  const downloadPdf = async () => {
    setBusy("pdf");
    try {
      const url = await pdfBlob();
      const a = document.createElement("a");
      a.href = url; a.download = `Invoice-${doc?.invoice?.number || invoiceId}.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => window.URL.revokeObjectURL(url), 4000);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(""); }
  };

  const printInvoice = async () => {
    setBusy("print");
    try {
      const url = await pdfBlob();
      const w = window.open(url);
      if (w) { w.addEventListener("load", () => { try { w.focus(); w.print(); } catch (e) { /* noop */ } }); }
      else { toast.info("Allow pop-ups to print, or use Download PDF."); }
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(""); }
  };

  const emailInvoice = async () => {
    const email = doc?.customer?.email;
    if (!email) { toast.error("This invoice's customer has no email address on file."); return; }
    if (!window.confirm(`Email invoice ${doc?.invoice?.number} to ${email}?`)) return;
    setBusy("email");
    try {
      const r = await api.post(`/invoices/${invoiceId}/send`);
      if (r.data.stubbed) toast.info(r.data.message || "Email delivery isn't switched on yet — use Print or Download PDF.");
      else toast.success(`Invoice emailed to ${r.data.to}.`);
      onSent && onSent();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(""); }
  };

  const inv = doc?.invoice; const co = doc?.company || {}; const cust = doc?.customer || {};

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl" data-testid="invoice-document-dialog">
        <DialogHeader><DialogTitle>Invoice {inv?.number || ""}</DialogTitle></DialogHeader>
        {loading && <div className="p-8 text-center text-sm text-slate-400"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" /> Loading invoice…</div>}
        {inv && !loading && (
          <div className="max-h-[60vh] overflow-y-auto rounded-md border border-border bg-white p-6 text-sm" data-testid="invoice-preview">
            <div className="flex items-start justify-between">
              <div className="text-slate-600">
                <div className="text-base font-semibold text-slate-900">{co.name || "RoofSpan Roofing Co."}</div>
                {co.address && <div>{co.address}</div>}
                <div>{[co.phone, co.email].filter(Boolean).join(" · ")}</div>
                {co.website && <div>{co.website}</div>}
              </div>
              <div className="text-right">
                <div className="text-2xl font-bold tracking-tight text-slate-900">INVOICE</div>
                <div className="mt-1 text-slate-500">{inv.number}</div>
              </div>
            </div>
            <div className="mt-6 flex justify-between">
              <div className="text-slate-600">
                <div className="text-xs font-semibold uppercase text-slate-400">Bill To</div>
                <div className="font-medium text-slate-800">{cust.name || "—"}</div>
                {doc.property_address && <div>{doc.property_address}</div>}
                {cust.billing_address && <div>{cust.billing_address}</div>}
                <div>{[cust.phone, cust.email].filter(Boolean).join(" · ")}</div>
              </div>
              <div className="text-right text-slate-600">
                <div><span className="text-slate-400">Status: </span>{String(inv.status).toUpperCase()}</div>
                <div><span className="text-slate-400">Issued: </span>{shortDate(inv.issue_date)}</div>
                <div><span className="text-slate-400">Due: </span>{shortDate(inv.due_date)}</div>
              </div>
            </div>
            <table className="mt-6 w-full text-left">
              <thead><tr className="bg-slate-900 text-white">
                <th className="p-2">Description</th><th className="p-2 text-right">Qty</th><th className="p-2">Unit</th>
                <th className="p-2 text-right">Unit Price</th><th className="p-2 text-right">Amount</th>
              </tr></thead>
              <tbody>
                {(inv.items || []).map((it, i) => (
                  <tr key={i} className="border-b border-border">
                    <td className="p-2 text-slate-700">{it.description}</td>
                    <td className="p-2 text-right tabular-nums">{it.quantity}</td>
                    <td className="p-2 text-slate-500">{it.unit}</td>
                    <td className="p-2 text-right tabular-nums">{money(it.unit_price)}</td>
                    <td className="p-2 text-right tabular-nums">{money(it.line_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-4 flex justify-end">
              <div className="w-56 text-slate-600">
                <div className="flex justify-between"><span>Subtotal</span><span className="tabular-nums">{money(inv.subtotal)}</span></div>
                <div className="flex justify-between"><span>Tax ({Number(inv.tax_rate || 0).toFixed(2)}%)</span><span className="tabular-nums">{money(inv.tax)}</span></div>
                <div className="mt-1 flex justify-between border-t border-slate-900 pt-1 font-semibold text-slate-900"><span>Total Due</span><span className="tabular-nums">{money(inv.total)}</span></div>
              </div>
            </div>
            {inv.notes && <div className="mt-4 whitespace-pre-line text-slate-600"><span className="font-semibold">Notes: </span>{inv.notes}</div>}
            <p className="mt-4 text-xs text-slate-400">RoofSpan is not a payment processor — please contact us to arrange payment.</p>
          </div>
        )}
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={printInvoice} disabled={!inv || !!busy} data-testid="invoice-print-btn">
            {busy === "print" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Printer className="h-4 w-4" />} Print
          </Button>
          <Button variant="outline" onClick={downloadPdf} disabled={!inv || !!busy} data-testid="invoice-pdf-btn">
            {busy === "pdf" ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />} Download PDF
          </Button>
          <Button onClick={emailInvoice} disabled={!inv || !!busy} data-testid="invoice-email-btn">
            {busy === "email" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />} Email to customer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

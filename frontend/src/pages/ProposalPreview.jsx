import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, Download, Loader2, CheckCircle2 } from "lucide-react";

function Items({ lines, subtotal, tax, total, testid }) {
  return (
    <div data-testid={testid}>
      <Table>
        <TableHeader><TableRow>
          <TableHead>Description</TableHead><TableHead className="text-right">Qty</TableHead>
          <TableHead>Unit</TableHead><TableHead className="text-right">Price</TableHead><TableHead className="text-right">Amount</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {lines.map((l, i) => (
            <TableRow key={i}>
              <TableCell>{l.description || "—"}</TableCell>
              <TableCell className="text-right tabular-nums">{l.quantity}</TableCell>
              <TableCell>{l.unit || ""}</TableCell>
              <TableCell className="text-right tabular-nums">{money(l.unit_price)}</TableCell>
              <TableCell className="text-right tabular-nums">{money(l.line_total)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="mt-2 flex flex-col items-end gap-0.5 text-sm">
        <div className="flex w-56 justify-between"><span className="text-slate-500">Subtotal</span><span className="tabular-nums">{money(subtotal)}</span></div>
        <div className="flex w-56 justify-between"><span className="text-slate-500">Tax</span><span className="tabular-nums">{money(tax)}</span></div>
        <div className="flex w-56 justify-between font-semibold text-orange-600"><span>Total</span><span className="tabular-nums">{money(total)}</span></div>
      </div>
    </div>
  );
}

export default function ProposalPreview() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try { setData((await api.get(`/quotes/${id}/proposal`)).data); }
    catch (e) { toast.error(apiError(e)); }
    finally { setLoading(false); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const download = async () => {
    try {
      const res = await api.get(`/quotes/${id}/proposal.pdf`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (e) { toast.error(apiError(e)); }
  };

  if (loading) return <div className="flex items-center gap-2 p-8 text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading proposal…</div>;
  if (!data) return <p className="p-8 text-slate-500">Proposal unavailable.</p>;
  const c = data.company; const q = data.quote;

  return (
    <div className="space-y-4" data-testid="proposal-preview">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={() => navigate(-1)}><ArrowLeft className="h-4 w-4" /> Back</Button>
        <Button size="sm" onClick={download} data-testid="proposal-download-pdf"><Download className="h-4 w-4" /> Download PDF</Button>
      </div>

      <div className="mx-auto max-w-3xl rounded-lg border border-border bg-white p-8 shadow-sm">
        <div className="flex items-start justify-between border-b border-slate-100 pb-4">
          <div>
            {c.logo_url ? <img src={c.logo_url} alt={c.name} className="mb-2 h-12 object-contain" data-testid="proposal-logo" /> : null}
            <h1 className="text-xl font-bold text-slate-900">{c.name}</h1>
            <div className="text-xs text-slate-500">{[c.phone, c.email, c.website].filter(Boolean).join(" · ")}</div>
            {c.address ? <div className="text-xs text-slate-500">{c.address}</div> : null}
            {c.license_number ? <div className="text-xs text-slate-400">License #{c.license_number}</div> : null}
          </div>
          <div className="text-right">
            <div className="text-lg font-semibold text-orange-600" data-testid="proposal-number">Proposal {q.number}</div>
            {q.issue_date ? <div className="text-xs text-slate-500">Issued {q.issue_date}</div> : null}
            {q.expiration_date ? <div className="text-xs text-slate-500">Valid until {q.expiration_date}</div> : null}
            <Badge variant="secondary" className="mt-1 capitalize">{q.status}</Badge>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 py-4 text-sm">
          {data.customer ? <div><div className="text-xs uppercase text-slate-400">Prepared for</div><div className="font-medium">{data.customer.name}</div></div> : <div />}
          {data.property?.address ? <div><div className="text-xs uppercase text-slate-400">Property</div><div className="font-medium">{data.property.address}</div></div> : null}
        </div>

        {q.multi_package && data.packages.length > 0 ? (
          <div className="space-y-6">
            {data.packages.map((p) => (
              <div key={p.id} className={`rounded-md border p-3 ${p.accepted ? "border-green-300 bg-green-50/50" : "border-border"}`} data-testid={`proposal-package-${p.id}`}>
                <div className="mb-2 flex items-center gap-2 font-semibold text-slate-800">{p.name}{p.accepted ? <Badge variant="secondary" className="bg-green-100 text-green-700"><CheckCircle2 className="mr-1 h-3 w-3" />Selected</Badge> : null}</div>
                <Items lines={p.lines} subtotal={p.subtotal} tax={p.tax} total={p.total} testid={`proposal-items-${p.id}`} />
              </div>
            ))}
          </div>
        ) : (
          <Items lines={data.lines} subtotal={q.subtotal} tax={q.tax} total={q.total} testid="proposal-items" />
        )}

        {(q.terms || c.proposal_terms_text) ? (
          <div className="mt-6 border-t border-slate-100 pt-4">
            <div className="text-xs font-semibold uppercase text-slate-500">Terms</div>
            <p className="whitespace-pre-line text-xs text-slate-500">{q.terms || c.proposal_terms_text}</p>
          </div>
        ) : null}

        {q.accepted_at ? (
          <div className="mt-4 rounded-md bg-green-50 p-3 text-sm text-green-700" data-testid="proposal-accepted">
            Accepted by {q.acceptance_name || q.accepted_by || "customer"} on {q.accepted_at}
          </div>
        ) : null}

        {c.proposal_footer_text ? <p className="mt-6 text-center text-xs text-slate-400">{c.proposal_footer_text}</p> : null}
      </div>
    </div>
  );
}

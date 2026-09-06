import { useEffect, useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { API_BASE, apiError } from "@/lib/api";
import { money } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Download, Loader2, CheckCircle2, Map } from "lucide-react";

// Public, no-login axios (never carries the office auth token, never redirects to /login).
const pub = axios.create({ baseURL: API_BASE });

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

export default function PublicProposal() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [name, setName] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [pkgId, setPkgId] = useState("");
  const [accepting, setAccepting] = useState(false);
  const [accepted, setAccepted] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try { const r = await pub.get(`/public/proposals/${token}`); setData(r.data); if (r.data?.share?.status === "accepted") setAccepted(true); }
    catch (e) { setError(apiError(e)); }
    finally { setLoading(false); }
  }, [token]);
  useEffect(() => { load(); }, [load]);

  const downloadPdf = async (kind) => {
    try {
      const r = await pub.get(`/public/proposals/${token}/${kind}`, { responseType: "blob" });
      const url = URL.createObjectURL(r.data); const a = document.createElement("a");
      a.href = url; a.download = kind === "site-plan.pdf" ? "site-plan.pdf" : "proposal.pdf";
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1500);
    } catch (e) { toast.error("Could not download that document"); }
  };

  const accept = async () => {
    if (!name.trim()) { toast.error("Please type your full name to accept."); return; }
    if (!agreed) { toast.error("Please agree to the terms to accept."); return; }
    setAccepting(true);
    try {
      const r = await pub.post(`/public/proposals/${token}/accept`, { acceptance_name: name.trim(), agreed, package_id: pkgId || null });
      setAccepted(true);
      toast.success(r.data?.message || "Thank you — your proposal has been accepted.");
    } catch (e) { toast.error(apiError(e)); } finally { setAccepting(false); }
  };

  if (loading) return <div className="flex min-h-screen items-center justify-center gap-2 bg-slate-50 text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading proposal…</div>;
  if (error) return <div className="flex min-h-screen items-center justify-center bg-slate-50 p-8 text-center text-slate-500" data-testid="public-proposal-error">{error}</div>;
  if (!data) return null;
  const c = data.company || {}; const q = data.quote || {}; const share = data.share || {};
  const multi = q.multi_package && (data.packages || []).length > 0;

  return (
    <div className="min-h-screen bg-slate-50 py-6 sm:py-10" data-testid="public-proposal">
      <div className="mx-auto max-w-3xl px-4">
        <div className="mb-3 flex flex-wrap items-center justify-end gap-2">
          {data.site_plan_available && <Button variant="outline" size="sm" onClick={() => downloadPdf("site-plan.pdf")} data-testid="public-site-plan-pdf"><Map className="h-4 w-4" /> Site Plan PDF</Button>}
          <Button variant="outline" size="sm" onClick={() => downloadPdf("proposal.pdf")} data-testid="public-download-pdf"><Download className="h-4 w-4" /> Download PDF</Button>
        </div>

        <div className="rounded-lg border border-border bg-white p-6 shadow-sm sm:p-8">
          <div className="flex items-start justify-between border-b border-slate-100 pb-4">
            <div>
              {c.logo_url ? <img src={c.logo_url} alt={c.name} className="mb-2 h-12 object-contain" data-testid="public-logo" /> : null}
              <h1 className="text-xl font-bold text-slate-900">{c.name}</h1>
              <div className="text-xs text-slate-500">{[c.phone, c.email, c.website].filter(Boolean).join(" · ")}</div>
              {c.address ? <div className="text-xs text-slate-500">{c.address}</div> : null}
              {c.license_number ? <div className="text-xs text-slate-400">License #{c.license_number}</div> : null}
            </div>
            <div className="text-right">
              <div className="text-lg font-semibold text-orange-600" data-testid="public-proposal-number">Proposal {q.number}</div>
              {q.issue_date ? <div className="text-xs text-slate-500">Issued {q.issue_date}</div> : null}
              {q.expiration_date ? <div className="text-xs text-slate-500">Valid until {q.expiration_date}</div> : null}
              <Badge variant="secondary" className="mt-1 capitalize">{share.status}</Badge>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 py-4 text-sm">
            {data.customer ? <div><div className="text-xs uppercase text-slate-400">Prepared for</div><div className="font-medium">{data.customer.name}</div></div> : <div />}
            {data.property?.address ? <div><div className="text-xs uppercase text-slate-400">Property</div><div className="font-medium">{data.property.address}</div></div> : null}
          </div>

          {multi ? (
            <div className="space-y-6">
              {data.packages.map((p) => (
                <label key={p.id} className={`block cursor-pointer rounded-md border p-3 ${pkgId === p.id ? "border-orange-400 ring-1 ring-orange-300" : p.accepted ? "border-green-300 bg-green-50/50" : "border-border"}`} data-testid={`public-package-${p.id}`}>
                  <div className="mb-2 flex items-center gap-2 font-semibold text-slate-800">
                    {!accepted && share.can_accept && <input type="radio" name="pkg" checked={pkgId === p.id} onChange={() => setPkgId(p.id)} data-testid={`public-package-select-${p.id}`} />}
                    {p.name}{p.accepted ? <Badge variant="secondary" className="bg-green-100 text-green-700"><CheckCircle2 className="mr-1 h-3 w-3" />Selected</Badge> : null}
                  </div>
                  <Items lines={p.lines} subtotal={p.subtotal} tax={p.tax} total={p.total} testid={`public-items-${p.id}`} />
                </label>
              ))}
            </div>
          ) : (
            <Items lines={data.lines} subtotal={q.subtotal} tax={q.tax} total={q.total} testid="public-items" />
          )}

          {(q.terms || c.proposal_terms_text) ? (
            <div className="mt-6 border-t border-slate-100 pt-4">
              <div className="text-xs font-semibold uppercase text-slate-500">Terms</div>
              <p className="whitespace-pre-line text-xs text-slate-500">{q.terms || c.proposal_terms_text}</p>
            </div>
          ) : null}

          {accepted ? (
            <div className="mt-6 rounded-md border border-green-200 bg-green-50 p-5 text-center" data-testid="public-accepted">
              <CheckCircle2 className="mx-auto mb-2 h-8 w-8 text-green-600" />
              <div className="text-lg font-semibold text-green-800">Thank you — your proposal is accepted!</div>
              <p className="mt-1 text-sm text-green-700">{c.name} has been notified and will be in touch about next steps.</p>
            </div>
          ) : share.can_accept ? (
            <div className="mt-6 rounded-md border border-slate-200 bg-slate-50 p-5" data-testid="public-accept-form">
              <div className="mb-3 text-sm font-semibold text-slate-800">Accept this proposal</div>
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label className="text-xs">Type your full name to sign</Label>
                  <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your full name" data-testid="public-accept-name" className="max-w-sm bg-white" />
                </div>
                <label className="flex items-start gap-2 text-sm text-slate-600">
                  <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} className="mt-0.5" data-testid="public-accept-agree" />
                  <span>I agree to the terms of this proposal and authorize {c.name || "the company"} to proceed.</span>
                </label>
                <Button onClick={accept} disabled={accepting || !name.trim() || !agreed || (multi && !pkgId)} data-testid="public-accept-btn">
                  {accepting ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} Accept Proposal
                </Button>
                {multi && !pkgId ? <p className="text-xs text-slate-400">Select an option above to accept.</p> : null}
              </div>
            </div>
          ) : (
            <div className="mt-6 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800" data-testid="public-not-acceptable">
              {share.status === "accepted" ? "This proposal has already been accepted." :
               share.expired ? "This proposal has expired. Please contact us for an updated proposal." :
               "This proposal is not currently available to accept online. Please contact us."}
            </div>
          )}

          {c.proposal_footer_text ? <p className="mt-6 text-center text-xs text-slate-400">{c.proposal_footer_text}</p> : null}
        </div>
        <p className="mt-4 text-center text-xs text-slate-400">Powered by RoofSpan</p>
      </div>
    </div>
  );
}

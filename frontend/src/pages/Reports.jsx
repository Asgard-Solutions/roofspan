import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Contact, Hammer, Wallet, Boxes, Loader2 } from "lucide-react";

const money = (n) => `$${Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const cap = (s) => (s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

function Card({ title, icon: Icon, children, testid }) {
  return (
    <div className="rounded-md border border-border bg-white p-5" data-testid={testid}>
      <div className="mb-3 flex items-center gap-2">
        <Icon className="h-4 w-4 text-orange-600" />
        <h2 className="font-heading text-base font-semibold text-slate-900">{title}</h2>
      </div>
      {children}
    </div>
  );
}

function Rows({ obj }) {
  const entries = Object.entries(obj || {});
  if (entries.length === 0) return <p className="text-sm text-slate-400">No data yet.</p>;
  return (
    <div className="divide-y divide-border">
      {entries.map(([k, v]) => (
        <div key={k} className="flex items-center justify-between py-1.5">
          <span className="text-sm capitalize text-slate-600">{cap(k)}</span>
          <span className="text-sm font-semibold text-slate-900">{typeof v === "object" ? v.count : v}</span>
        </div>
      ))}
    </div>
  );
}

function Big({ label, value, testid }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</div>
      <div className="mt-1 font-heading text-2xl font-bold text-slate-900" data-testid={testid}>{value}</div>
    </div>
  );
}

export default function Reports() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    api.get("/reports/summary").then((r) => setData(r.data)).catch(() => setErr(true));
  }, []);

  if (err) {
    return (
      <div>
        <PageHeader title="Reports" testid="page-reports" />
        <div className="p-6 text-sm text-slate-500">Reports are unavailable right now.</div>
      </div>
    );
  }
  if (!data) {
    return (
      <div>
        <PageHeader title="Reports" testid="page-reports" />
        <div className="flex justify-center p-10"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="Reports" description="A live snapshot of your RoofSpan operations" testid="page-reports" />
      <div className="grid grid-cols-1 gap-5 p-6 sm:p-8 lg:grid-cols-2">
        <Card title="Sales Pipeline" icon={Contact} testid="report-pipeline">
          <div className="mb-4 grid grid-cols-3 gap-4">
            <Big label="Total leads" value={data.pipeline.total_leads} testid="report-total-leads" />
            <Big label="Active" value={data.pipeline.active_leads} testid="report-active-leads" />
            <Big label="Converted" value={data.pipeline.converted_leads} testid="report-converted-leads" />
          </div>
          <Rows obj={data.pipeline.by_status} />
        </Card>

        <Card title="Jobs" icon={Hammer} testid="report-jobs">
          <div className="mb-4"><Big label="Total jobs" value={data.jobs.total_jobs} testid="report-total-jobs" /></div>
          <Rows obj={data.jobs.by_status} />
        </Card>

        {data.finance && (
          <Card title="Revenue & Invoices" icon={Wallet} testid="report-finance">
            <div className="mb-4 grid grid-cols-3 gap-4">
              <Big label="Invoiced" value={money(data.finance.total_invoiced)} testid="report-invoiced" />
              <Big label="Paid" value={money(data.finance.paid)} testid="report-paid" />
              <Big label="Outstanding" value={money(data.finance.outstanding)} testid="report-outstanding" />
            </div>
            <div className="divide-y divide-border">
              {Object.entries(data.finance.by_status).map(([s, v]) => (
                <div key={s} className="flex items-center justify-between py-1.5">
                  <span className="text-sm capitalize text-slate-600">{cap(s)} <span className="text-slate-400">({v.count})</span></span>
                  <span className="text-sm font-semibold text-slate-900">{money(v.total)}</span>
                </div>
              ))}
            </div>
          </Card>
        )}

        <Card title="Inventory — Low Stock" icon={Boxes} testid="report-inventory">
          <div className="mb-3"><Big label="Materials at/under reorder point" value={data.inventory.low_stock_count} testid="report-lowstock-count" /></div>
          {data.inventory.low_stock.length === 0 ? (
            <p className="text-sm text-slate-400">Everything is above its reorder threshold.</p>
          ) : (
            <div className="divide-y divide-border">
              {data.inventory.low_stock.map((m) => (
                <div key={m.id} className="flex items-center justify-between py-1.5">
                  <span className="text-sm text-slate-600">{m.name}</span>
                  <span className="text-sm font-semibold text-orange-600">{m.quantity_on_hand} / {m.reorder_threshold} {m.unit}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

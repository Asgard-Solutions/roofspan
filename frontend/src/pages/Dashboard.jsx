import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Users2, Activity, Contact, Map, Hammer, ArrowRight, Boxes, PackageOpen, ShoppingCart, Truck as TruckIcon, AlertTriangle, Warehouse, DatabaseBackup } from "lucide-react";
import { money } from "@/lib/format";

function BackupHealthBadge() {
  const [h, setH] = useState(null);
  useEffect(() => { api.get("/admin/backups/health").then((r) => setH(r.data)).catch(() => {}); }, []);
  if (!h) return null;
  const styles = {
    ok: "border-emerald-200 bg-emerald-50 text-emerald-800",
    warn: "border-amber-200 bg-amber-50 text-amber-800",
    error: "border-red-200 bg-red-50 text-red-800",
  };
  const dot = { ok: "bg-emerald-500", warn: "bg-amber-500", error: "bg-red-500" };
  return (
    <Link
      to="/admin/backups"
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors hover:opacity-90 ${styles[h.level] || styles.warn}`}
      data-testid="dashboard-backup-badge"
      title="View backups"
    >
      <span className={`h-2 w-2 rounded-full ${dot[h.level] || dot.warn}`} />
      <DatabaseBackup className="h-3.5 w-3.5" />
      <span data-testid="dashboard-backup-badge-label">{h.label}</span>
    </Link>
  );
}

function Stat({ label, value, icon: Icon, testid }) {
  return (
    <div className="rounded-md border border-border bg-white p-5" data-testid={testid}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</span>
        <Icon className="h-4 w-4 text-slate-400" />
      </div>
      <div className="mt-2 font-heading text-3xl font-bold text-slate-900">{value}</div>
    </div>
  );
}

function PurchasingIntelligence() {
  const [d, setD] = useState(null);
  useEffect(() => { api.get("/dashboard/purchasing").then((r) => setD(r.data)).catch(() => {}); }, []);
  if (!d) return null;
  const c = d.cards;
  const card = (label, value, Icon, tid, sub) => (
    <div className="rounded-md border border-border bg-white p-4" data-testid={tid}>
      <div className="flex items-center justify-between"><span className="text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</span><Icon className="h-4 w-4 text-slate-400" /></div>
      <div className="mt-1.5 font-heading text-2xl font-bold text-slate-900">{value}</div>
      {sub ? <div className="text-xs text-slate-400">{sub}</div> : null}
    </div>
  );
  const sevCls = { warn: "text-amber-600", info: "text-blue-600", error: "text-red-600" };
  return (
    <div className="space-y-4" data-testid="purchasing-intelligence">
      <h2 className="font-heading text-lg font-semibold text-slate-900">Purchasing & Inventory</h2>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {d.cost_visible && card("Inventory Value", money(c.inventory_value), Warehouse, "card-inventory-value", "Operational (MWAC)")}
        {card("Low Stock", c.low_stock_items, Boxes, "card-low-stock")}
        {card("Reserved", c.reserved_quantity, PackageOpen, "card-reserved", d.cost_visible ? money(c.reserved_value) : null)}
        {card("Open POs", c.open_purchase_orders, ShoppingCart, "card-open-pos", d.cost_visible ? `${money(c.open_po_committed_value)} committed` : null)}
        {card("Incoming (7d)", c.incoming_this_week, TruckIcon, "card-incoming")}
        {card("Jobs Short", c.jobs_needing_materials, Hammer, "card-jobs-short")}
        {card("Backordered", c.backordered_items, AlertTriangle, "card-backordered")}
      </div>
      <div>
        <h3 className="mb-2 text-sm font-semibold text-slate-700">Action required</h3>
        <div className="rounded-md border border-border bg-white" data-testid="action-required">
          {(d.action_required || []).length === 0 && <div className="p-4 text-sm text-slate-400">Nothing needs attention right now.</div>}
          {(d.action_required || []).slice(0, 25).map((a, i) => (
            <Link key={i} to={a.link} className="flex items-center justify-between border-b border-border px-4 py-2.5 last:border-0 hover:bg-slate-50" data-testid={`action-${a.type}-${i}`}>
              <div className="flex items-center gap-2"><AlertTriangle className={`h-4 w-4 ${sevCls[a.severity] || "text-slate-400"}`} /><span className="text-sm text-slate-700">{a.message}</span></div>
              <ArrowRight className="h-4 w-4 text-slate-300" />
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}

const QUICK = [
  { to: "/leads", label: "Leads", icon: Contact },
  { to: "/map", label: "Property Map", icon: Map },
  { to: "/jobs", label: "Jobs", icon: Hammer },
];

export default function Dashboard() {
  const { user, isSensitive } = useAuth();
  const [data, setData] = useState(null);

  useEffect(() => {
    api.get("/dashboard/summary").then((r) => setData(r.data)).catch(() => {});
  }, []);

  const firstName = (user?.full_name || user?.email || "").split(" ")[0];

  return (
    <div>
      <PageHeader
        title={`Welcome, ${firstName}`}
        description={data?.phase || "Office Phase 1 — Foundation"}
        testid="page-dashboard"
        actions={isSensitive ? <BackupHealthBadge /> : null}
      />
      <div className="space-y-6 p-6 sm:p-8">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Stat label="Active Users" value={data?.users?.active ?? "—"} icon={Users2} testid="stat-active-users" />
          {isSensitive && (
            <Stat label="Total Users" value={data?.users?.total ?? "—"} icon={Users2} testid="stat-total-users" />
          )}
          {isSensitive && (
            <Stat label="Audit Entries" value={data?.audit_total ?? "—"} icon={Activity} testid="stat-audit-total" />
          )}
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <h2 className="mb-3 font-heading text-lg font-semibold text-slate-900">Go to</h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {QUICK.map((q) => (
                <Link
                  key={q.to}
                  to={q.to}
                  className="group flex items-center justify-between rounded-md border border-border bg-white p-4 transition-colors hover:border-slate-300"
                  data-testid={`quick-${q.label.toLowerCase().replace(/\s/g, "-")}`}
                >
                  <div className="flex items-center gap-3">
                    <q.icon className="h-5 w-5 text-orange-600" />
                    <span className="text-sm font-medium text-slate-900">{q.label}</span>
                  </div>
                  <ArrowRight className="h-4 w-4 text-slate-300 transition-colors group-hover:text-slate-600" />
                </Link>
              ))}
            </div>
          </div>

          {isSensitive && (
            <div>
              <h2 className="mb-3 font-heading text-lg font-semibold text-slate-900">Recent activity</h2>
              <div className="rounded-md border border-border bg-white" data-testid="recent-activity">
                {(data?.recent_activity || []).length === 0 && (
                  <div className="p-4 text-sm text-slate-400">No recent activity.</div>
                )}
                {(data?.recent_activity || []).map((a, i) => (
                  <div key={i} className="flex items-center justify-between border-b border-border px-4 py-2.5 last:border-0">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-slate-800">{a.action}</div>
                      <div className="truncate text-xs text-slate-400">{a.user_email}</div>
                    </div>
                    <div className="whitespace-nowrap pl-3 text-xs text-slate-400">
                      {new Date(a.timestamp).toLocaleString()}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <PurchasingIntelligence />
      </div>
    </div>
  );
}

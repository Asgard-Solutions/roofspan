import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Users2, Activity, Contact, Map, Hammer, ArrowRight } from "lucide-react";

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
      </div>
    </div>
  );
}

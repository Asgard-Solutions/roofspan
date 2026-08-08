import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { RefreshCw, CheckCircle2, XCircle, MinusCircle } from "lucide-react";

function StatusRow({ label, item, hint }) {
  const ok = item?.ok;
  const none = !item || item.status === "NONE";
  const Icon = none ? MinusCircle : ok ? CheckCircle2 : XCircle;
  const color = none ? "text-slate-400" : ok ? "text-emerald-600" : "text-red-600";
  const badge = none ? "Not run yet" : ok ? item.status : "FAILED";
  const badgeCls = none
    ? "bg-slate-100 text-slate-500"
    : ok
    ? "bg-emerald-50 text-emerald-700"
    : "bg-red-50 text-red-700";
  return (
    <div className="flex items-center justify-between border-b border-border py-3 last:border-0" data-testid={`backup-row-${label.toLowerCase().replace(/[^a-z]+/g, "-")}`}>
      <div>
        <div className="text-sm font-medium text-slate-900">{label}</div>
        {hint && <div className="text-xs text-slate-400">{hint}</div>}
      </div>
      <div className="flex items-center gap-3">
        <span className="text-xs text-slate-500" data-testid="backup-timestamp">
          {item?.timestamp ? new Date(item.timestamp).toLocaleString() : "—"}
        </span>
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${badgeCls}`}>
          <Icon className={`h-3.5 w-3.5 ${color}`} /> {badge}
        </span>
      </div>
    </div>
  );
}

export default function BackupStatus() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api
      .get("/admin/backup-status")
      .then((r) => setData(r.data))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <PageHeader
        title="Backups"
        description="Operational backup health (read-only)"
        testid="page-backups"
        actions={
          <Button variant="outline" size="sm" onClick={load} data-testid="backups-refresh">
            <RefreshCw className="h-4 w-4" /> Refresh
          </Button>
        }
      />
      <div className="p-6 sm:p-8">
        <div className="max-w-2xl rounded-md border border-border bg-white p-5" data-testid="backup-status-card">
          <StatusRow label="Last local backup" item={data?.local_backup} hint="Nightly pg_dump on the persistent volume" />
          <StatusRow label="Last off-site copy" item={data?.offsite_copy} hint="Copied to Emergent object storage (off-pod)" />
          <StatusRow label="Last off-site restore drill" item={data?.offsite_restore_drill} hint="Retrieve off-site backup → restore → verify" />
          <div className="mt-4 flex items-center justify-between text-xs text-slate-400">
            <span data-testid="backup-count">Local backups retained: {data?.local_backup_count ?? "—"}</span>
            <span>{loading ? "Loading…" : data?.backup_dir}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

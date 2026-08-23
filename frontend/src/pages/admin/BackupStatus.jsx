import { useEffect, useState, useCallback, useRef } from "react";
import { api, apiError, API_BASE, getToken } from "@/lib/api";
import { toast } from "sonner";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  RefreshCw, CheckCircle2, XCircle, MinusCircle, DatabaseBackup,
  Download, Upload, RotateCcw, Loader2, HardDriveDownload, CloudUpload, Cloud, AlertTriangle,
  CalendarClock, Play,
} from "lucide-react";

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

function fmtSize(n) {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function StatusRow({ label, item, hint }) {
  const ok = item?.ok;
  const none = !item || item.status === "NONE";
  const Icon = none ? MinusCircle : ok ? CheckCircle2 : XCircle;
  const color = none ? "text-slate-400" : ok ? "text-emerald-600" : "text-red-600";
  const badge = none ? "Not run yet" : ok ? item.status : "FAILED";
  const badgeCls = none ? "bg-slate-100 text-slate-500" : ok ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700";
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
  const [backups, setBackups] = useState([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [restoreTarget, setRestoreTarget] = useState(null);
  const [restoring, setRestoring] = useState(false);
  const [offsiting, setOffsiting] = useState(null);
  const [schedule, setSchedule] = useState({ enabled: false, time: "02:00" });
  const [schedState, setSchedState] = useState({});
  const [savingSched, setSavingSched] = useState(false);
  const [runningNow, setRunningNow] = useState(false);
  const fileRef = useRef(null);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.get("/admin/backup-status").then((r) => setData(r.data)).catch(() => {}),
      api.get("/admin/backups").then((r) => setBackups(r.data.backups || [])).catch(() => {}),
      api.get("/admin/backups/schedule").then((r) => { setSchedule(r.data.schedule); setSchedState(r.data.state || {}); }).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const createBackup = async () => {
    setCreating(true);
    try {
      const r = await api.post("/admin/backups/create");
      toast.success(`Backup created (${fmtSize(r.data.size_bytes)})`);
      load();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setCreating(false);
    }
  };

  const downloadBackup = async (filename) => {
    try {
      const res = await fetch(`${API_BASE}/admin/backups/download/${encodeURIComponent(filename)}`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!res.ok) throw new Error(`Download failed (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("Backup downloaded — store it somewhere safe.");
    } catch (e) {
      toast.error(e.message || "Download failed");
    }
  };

  const onUploadFile = async (e) => {
    const file = e.target.files?.[0];
    if (fileRef.current) fileRef.current.value = "";
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api.post("/admin/backups/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(`Backup imported (${fmtSize(r.data.size_bytes)}) — ready to restore.`);
      load();
    } catch (err) {
      toast.error(apiError(err));
    } finally {
      setUploading(false);
    }
  };

  const saveSchedule = async (next) => {
    const body = next || schedule;
    setSavingSched(true);
    try {
      const r = await api.put("/admin/backups/schedule", body);
      setSchedule(r.data.schedule);
      setSchedState(r.data.state || {});
      toast.success(body.enabled ? `Automatic backup scheduled for ${body.time} daily.` : "Automatic backup turned off.");
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSavingSched(false);
    }
  };

  const runScheduledNow = async () => {
    setRunningNow(true);
    try {
      const r = await api.post("/admin/backups/schedule/run-now");
      setSchedState(r.data.state || {});
      if (r.data.state?.last_status === "OK") toast.success("Automatic backup ran successfully.");
      else toast.error(`Backup failed: ${r.data.state?.last_error || "unknown error"}`);
      load();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setRunningNow(false);
    }
  };

  const copyOffsite = async (filename) => {    setOffsiting(filename);
    try {
      await api.post("/admin/backups/offsite", { filename });
      toast.success("Backup copied off-site.");
      load();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setOffsiting(null);
    }
  };

  const doRestore = async () => {    if (!restoreTarget) return;
    setRestoring(true);
    try {
      await api.post("/admin/backups/restore", { filename: restoreTarget });
      toast.success("Database restored. Reloading…");
      setRestoreTarget(null);
      setTimeout(() => window.location.reload(), 1500);
    } catch (e) {
      toast.error(apiError(e));
      setRestoring(false);
    }
  };

  const newest = backups[0]?.created_at ? new Date(backups[0].created_at).getTime() : null;
  const ageMs = newest ? Date.now() - newest : null;
  const stale = !loading && (newest === null || (ageMs != null && ageMs > WEEK_MS));
  const staleDays = ageMs != null ? Math.floor(ageMs / (24 * 60 * 60 * 1000)) : null;

  return (
    <div>
      <PageHeader
        title="Backups"
        description="Create a full local backup, download it anywhere, and restore all data when needed."
        testid="page-backups"
        actions={
          <Button variant="outline" size="sm" onClick={load} data-testid="backups-refresh">
            <RefreshCw className="h-4 w-4" /> Refresh
          </Button>
        }
      />
      <div className="space-y-6 p-6 sm:p-8">
        {stale && (
          <div className="flex max-w-3xl items-start justify-between gap-4 rounded-md border border-amber-200 bg-amber-50 p-4" data-testid="backup-stale-banner">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
              <div>
                <div className="text-sm font-semibold text-amber-900">
                  {newest === null ? "You have no backups yet" : `Your last backup is ${staleDays} day${staleDays === 1 ? "" : "s"} old`}
                </div>
                <div className="text-xs text-amber-700">
                  We recommend creating a fresh backup at least once a week so you never lose recent work.
                </div>
              </div>
            </div>
            <Button size="sm" onClick={createBackup} disabled={creating} className="shrink-0 bg-amber-600 hover:bg-amber-700" data-testid="backup-stale-create">
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <DatabaseBackup className="h-4 w-4" />}
              {creating ? "Creating…" : "Create backup now"}
            </Button>
          </div>
        )}
        {/* Create + Import actions */}
        <div className="max-w-3xl rounded-md border border-border bg-white p-5" data-testid="backup-actions-card">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <DatabaseBackup className="h-4 w-4 text-slate-500" /> Full backup
          </div>
          <p className="mt-1 text-xs text-slate-500">
            A backup is a single portable file containing all of your RoofSpan data. Create one, then download and keep it wherever you like (external drive, cloud folder, etc.).
          </p>
          <div className="mt-4 flex flex-wrap gap-3">
            <Button onClick={createBackup} disabled={creating} data-testid="create-backup-button">
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <DatabaseBackup className="h-4 w-4" />}
              {creating ? "Creating…" : "Create backup now"}
            </Button>
            <input ref={fileRef} type="file" accept=".dump" className="hidden" onChange={onUploadFile} data-testid="upload-backup-input" />
            <Button variant="outline" onClick={() => fileRef.current?.click()} disabled={uploading} data-testid="import-backup-button">
              {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              {uploading ? "Importing…" : "Import backup file"}
            </Button>
          </div>
        </div>

        {/* Scheduled automatic backups */}
        <div className="max-w-3xl rounded-md border border-border bg-white p-5" data-testid="backup-schedule-card">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <CalendarClock className="h-4 w-4 text-slate-500" /> Automatic backups
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Run a full backup automatically every day at a time you choose. We'll show whether the last automatic backup succeeded or failed.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <Switch checked={schedule.enabled} onCheckedChange={(v) => saveSchedule({ ...schedule, enabled: v })} disabled={savingSched} data-testid="schedule-enabled-switch" />
              {schedule.enabled ? "On" : "Off"}
            </label>
            <div className="flex items-center gap-2">
              <span className="text-sm text-slate-500">Daily at</span>
              <Input type="time" value={schedule.time} onChange={(e) => setSchedule({ ...schedule, time: e.target.value })} className="w-32" data-testid="schedule-time-input" />
              <Button variant="outline" size="sm" onClick={() => saveSchedule()} disabled={savingSched} data-testid="schedule-save-button">
                {savingSched ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Save time
              </Button>
            </div>
            <Button variant="outline" size="sm" onClick={runScheduledNow} disabled={runningNow} data-testid="schedule-run-now-button">
              {runningNow ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Run now
            </Button>
          </div>
          {/* Last automatic backup status — stays "failed" until a successful run */}
          {schedState.last_status ? (
            <div className={`mt-4 flex items-start gap-2 rounded-md border p-3 text-sm ${schedState.last_status === "OK" ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50"}`} data-testid="schedule-status">
              {schedState.last_status === "OK"
                ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />}
              <div>
                <div className={`font-semibold ${schedState.last_status === "OK" ? "text-emerald-800" : "text-red-800"}`} data-testid="schedule-status-label">
                  {schedState.last_status === "OK" ? "Last automatic backup succeeded" : "Last automatic backup FAILED"}
                </div>
                <div className="text-xs text-slate-500">
                  {schedState.last_run_at ? new Date(schedState.last_run_at).toLocaleString() : ""}
                  {schedState.last_file ? ` · ${schedState.last_file}` : ""}
                </div>
                {schedState.last_status !== "OK" && schedState.last_error && (
                  <div className="mt-1 text-xs text-red-700">{schedState.last_error} — please try "Run now" until it succeeds.</div>
                )}
              </div>
            </div>
          ) : (
            <div className="mt-4 text-xs text-slate-400" data-testid="schedule-status-none">No automatic backup has run yet.</div>
          )}
        </div>

        {/* Backups list */}
        <div className="max-w-3xl rounded-md border border-border bg-white p-5" data-testid="backups-list-card">
          <div className="mb-3 flex items-center justify-between">
            <div className="text-sm font-semibold text-slate-900">Available backups</div>
            <span className="text-xs text-slate-400" data-testid="backups-count">{backups.length} file{backups.length === 1 ? "" : "s"}</span>
          </div>
          {backups.length === 0 ? (
            <div className="py-8 text-center text-sm text-slate-400" data-testid="backups-empty">
              {loading ? "Loading…" : "No backups yet. Create one above to get started."}
            </div>
          ) : (
            <div className="divide-y divide-border">
              {backups.map((b) => (
                <div key={b.filename} className="flex flex-wrap items-center justify-between gap-3 py-3" data-testid={`backup-item-${b.filename}`}>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-mono text-xs font-medium text-slate-900" data-testid="backup-filename">{b.filename}</span>
                      {b.offsite && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700" data-testid={`offsite-badge-${b.filename}`}>
                          <Cloud className="h-3 w-3" /> Off-site
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-400">{new Date(b.created_at).toLocaleString()} · {fmtSize(b.size_bytes)}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" onClick={() => downloadBackup(b.filename)} data-testid={`download-backup-${b.filename}`}>
                      <Download className="h-4 w-4" /> Download
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => copyOffsite(b.filename)} disabled={offsiting === b.filename} data-testid={`offsite-backup-${b.filename}`}>
                      {offsiting === b.filename ? <Loader2 className="h-4 w-4 animate-spin" /> : <CloudUpload className="h-4 w-4" />}
                      {b.offsite ? "Re-copy off-site" : "Copy off-site"}
                    </Button>
                    <Button variant="outline" size="sm" className="border-red-200 text-red-700 hover:bg-red-50" onClick={() => setRestoreTarget(b.filename)} data-testid={`restore-backup-${b.filename}`}>
                      <RotateCcw className="h-4 w-4" /> Restore
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Operational status (existing) */}
        <div className="max-w-3xl rounded-md border border-border bg-white p-5" data-testid="backup-status-card">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-900">
            <HardDriveDownload className="h-4 w-4 text-slate-500" /> Automatic backup health
          </div>
          <StatusRow label="Last local backup" item={data?.local_backup} hint="Nightly pg_dump on the persistent volume" />
          <StatusRow label="Last off-site copy" item={data?.offsite_copy} hint="Copied to off-pod object storage" />
          <StatusRow label="Last off-site restore drill" item={data?.offsite_restore_drill} hint="Retrieve off-site backup → restore → verify" />
          <div className="mt-4 flex items-center justify-between text-xs text-slate-400">
            <span data-testid="backup-count">Local backups retained: {data?.local_backup_count ?? "—"}</span>
            <span>{loading ? "Loading…" : data?.backup_dir}</span>
          </div>
        </div>
      </div>

      <AlertDialog open={!!restoreTarget} onOpenChange={(o) => { if (!o && !restoring) setRestoreTarget(null); }}>
        <AlertDialogContent data-testid="restore-confirm-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Restore from backup?</AlertDialogTitle>
            <AlertDialogDescription>
              This will replace <span className="font-mono text-xs">all current data</span> with the contents of
              <span className="font-mono text-xs"> {restoreTarget}</span>. Anything not in this backup will be lost.
              You will be signed out and the app will reload when it finishes.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={restoring} data-testid="restore-cancel">Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={(e) => { e.preventDefault(); doRestore(); }} disabled={restoring} className="bg-red-600 hover:bg-red-700" data-testid="restore-confirm">
              {restoring ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Restoring…</> : "Restore now"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

import { useState } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ArrowLeft, CheckCircle2, FolderOpen, Loader2, Upload } from "lucide-react";

const CodeStep = ({ onVerified }) => {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { data } = await api.post("/setup/recover/verify", { recovery_code: code.trim() });
      onVerified(data);
    } catch (err) {
      toast.error(apiError(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="mt-6 space-y-4" data-testid="restore-code-form">
      <div className="space-y-1.5">
        <Label>Company recovery code</Label>
        <Input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="XXXXX-XXXXX-XXXXX-XXXXX"
          className="font-mono tracking-widest"
          autoFocus
          data-testid="restore-code-input"
        />
      </div>
      <Button type="submit" className="w-full" disabled={busy || code.trim().length < 8} data-testid="restore-code-submit">
        {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null} Verify code
      </Button>
    </form>
  );
};

const BackupStep = ({ company, onRestored }) => {
  const [folder, setFolder] = useState("");
  const [backups, setBackups] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async (fn) => {
    setBusy(true);
    try {
      await fn();
    } catch (err) {
      toast.error(apiError(err));
    } finally {
      setBusy(false);
    }
  };
  const list = () => run(async () => setBackups((await api.post("/setup/recover/backups", { folder })).data.backups));
  const restoreFrom = (filename) =>
    run(async () => onRestored((await api.post("/setup/recover/restore-folder", { folder, filename })).data));
  const upload = (file) =>
    run(async () => {
      const form = new FormData();
      form.append("file", file);
      onRestored((await api.post("/setup/recover/restore-upload", form)).data);
    });

  return (
    <div className="mt-6 space-y-5" data-testid="restore-backup-step">
      <div className="flex items-start gap-2 rounded-md bg-emerald-50 p-3 text-sm text-emerald-800" data-testid="restore-company-found">
        <CheckCircle2 className="mt-0.5 h-4 w-4" />
        <span>
          <b>{company.company_name}</b> is now connected to this computer. Your previous computer has been disconnected.
          Now import your last backup.
        </span>
      </div>
      <div className="space-y-1.5">
        <Label>Backup copy folder (USB drive or network share)</Label>
        <div className="flex gap-2">
          <Input value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="E:\RoofSpan Backups" data-testid="restore-folder-input" />
          <Button type="button" variant="outline" disabled={busy || !folder.trim()} onClick={list} data-testid="restore-folder-list">
            <FolderOpen className="mr-1 h-4 w-4" /> Find backups
          </Button>
        </div>
      </div>
      {backups && (
        <ul className="max-h-48 space-y-2 overflow-y-auto" data-testid="restore-backup-list">
          {backups.length === 0 && <li className="text-sm text-slate-500">No RoofSpan backups in that folder.</li>}
          {backups.map((b, i) => (
            <li key={b.filename} className="flex items-center justify-between rounded-md border p-2 text-sm">
              <span>
                {new Date(b.created_at).toLocaleString()} · {(b.size_bytes / 1048576).toFixed(1)} MB{i === 0 ? " · newest" : ""}
              </span>
              <Button size="sm" disabled={busy} onClick={() => restoreFrom(b.filename)} data-testid={`restore-backup-${i}`}>
                Restore
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="border-t pt-4">
        <Label className="mb-1.5 block">Or upload a backup file (.dump)</Label>
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-slate-50">
          <Upload className="h-4 w-4" /> Choose backup file
          <input type="file" accept=".dump" className="hidden" disabled={busy}
            onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} data-testid="restore-upload-input" />
        </label>
      </div>
      {busy && (
        <div className="flex items-center gap-2 text-sm text-slate-600" data-testid="restore-busy">
          <Loader2 className="h-4 w-4 animate-spin" /> Working… large backups can take a few minutes.
        </div>
      )}
    </div>
  );
};

export const RestoreCompany = ({ onBack, onDone }) => {
  const [company, setCompany] = useState(null);
  return (
    <div data-testid="restore-company">
      <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900">Restore my company</h1>
      <p className="mt-1 text-sm text-slate-500">
        Moving to a new or reinstalled computer? Enter the recovery code you saved when RoofSpan was first set up.
      </p>
      {company ? <BackupStep company={company} onRestored={onDone} /> : <CodeStep onVerified={setCompany} />}
      {!company && (
        <button type="button" onClick={onBack} className="mt-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800" data-testid="restore-back">
          <ArrowLeft className="h-4 w-4" /> Set up a new company instead
        </button>
      )}
    </div>
  );
};

import { useState } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { Download, Loader2, AlertTriangle, CheckCircle2 } from "lucide-react";

export default function ImportDialog({ open, onOpenChange, territory, onComplete }) {
  const [maxRecords] = useState(250);  // only used for sample mode / preview; real RentCast import pulls ALL
  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [job, setJob] = useState(null);
  const [running, setRunning] = useState(false);

  const reset = () => {
    setPreview(null);
    setJob(null);
    setRunning(false);
  };

  const runPreview = async () => {
    setPreviewing(true);
    setPreview(null);
    setJob(null);
    try {
      const { data } = await api.post(`/territories/${territory.id}/import/preview`, { max_records: maxRecords });
      setPreview(data);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setPreviewing(false);
    }
  };

  const confirmImport = async () => {
    setRunning(true);
    try {
      const { data } = await api.post(`/territories/${territory.id}/import`, { max_records: maxRecords });
      setJob(data);
      // poll
      let done = false;
      for (let i = 0; i < 120 && !done; i++) {
        await new Promise((r) => setTimeout(r, 700));
        const { data: j } = await api.get(`/imports/${data.id}`);
        setJob(j);
        if (j.status === "completed" || j.status === "failed") done = true;
      }
      const { data: fin } = await api.get(`/imports/${data.id}`);
      if (fin.status === "completed") {
        toast.success(`Imported ${fin.created_count} new, updated ${fin.updated_count}`);
        onComplete && onComplete();
      } else if (fin.status === "failed") {
        toast.error(`Import failed: ${fin.error || "unknown error"}`);
      }
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setRunning(false);
    }
  };

  const pct = job && job.total ? Math.round((job.processed / job.total) * 100) : job && job.status === "running" ? 5 : 0;

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!running) { onOpenChange(v); if (!v) reset(); } }}>
      <DialogContent data-testid="import-dialog">
        <DialogHeader>
          <DialogTitle>Import properties</DialogTitle>
          <DialogDescription>Territory: {territory?.name}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {territory?.zip_code && (
            <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800" data-testid="import-zip-note">
              Exact ZIP pull: RentCast will fetch addresses for ZIP <strong>{territory.zip_code}</strong>, filtered to this boundary.
            </div>
          )}
          <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600" data-testid="import-all-note">
            This imports <strong>all</strong> properties RentCast has for this {territory?.zip_code ? "ZIP" : "territory"} (paged automatically) and saves them locally, so you won't re-pull unless you import again.
          </div>

          {!preview && !job && (
            <Button onClick={runPreview} disabled={previewing} className="w-full" data-testid="import-preview-button">
              {previewing ? <Loader2 className="h-4 w-4 animate-spin" /> : "Preview import"}
            </Button>
          )}

          {preview && !job && (
            <div className="space-y-3 rounded-md border border-border bg-slate-50 p-4" data-testid="import-preview-result">
              {preview.mode === "sample" && (
                <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-2.5 text-sm text-amber-800">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>Sample data (RentCast not configured). Demo properties will be generated inside this territory.</span>
                </div>
              )}
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><div className="text-slate-400">Estimated properties</div><div className="font-heading text-lg font-bold text-slate-900" data-testid="preview-est-properties">{preview.estimated_properties}</div></div>
                <div><div className="text-slate-400">RentCast requests</div><div className="font-heading text-lg font-bold text-slate-900" data-testid="preview-est-requests">{preview.estimated_requests}</div></div>
              </div>
              <p className="text-xs text-slate-500">{preview.note}</p>
              {preview.sample?.length > 0 && (
                <div className="max-h-32 overflow-y-auto rounded border border-border bg-white text-xs">
                  {preview.sample.map((s, i) => (
                    <div key={i} className="border-b border-border px-2 py-1 last:border-0 text-slate-600">{s.formatted_address}</div>
                  ))}
                </div>
              )}
            </div>
          )}

          {job && (
            <div className="space-y-2" data-testid="import-progress">
              <Progress value={pct} />
              <div className="flex justify-between text-xs text-slate-500">
                <span>{job.status === "completed" ? <span className="inline-flex items-center gap-1 text-green-600"><CheckCircle2 className="h-3.5 w-3.5" /> Completed</span> : job.status}</span>
                <span>{job.processed}/{job.total || "—"} · +{job.created_count} new</span>
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={running}>Close</Button>
          {preview && (!job || job.status === "completed" || job.status === "failed") && (
            <Button onClick={confirmImport} disabled={running || preview.estimated_properties === 0} data-testid="import-confirm-button">
              {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Download className="h-4 w-4" /> Confirm import</>}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

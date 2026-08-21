import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { CheckCircle2, Loader2, AlertTriangle } from "lucide-react";

export default function LocationResolutionProgress() {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    let alive = true;
    let timer;

    const load = async () => {
      try {
        const { data } = await api.get("/location-resolution/progress");
        if (alive) setStatus(data);
      } catch {
        // Progress reporting must never interfere with the map itself.
      } finally {
        if (alive) timer = window.setTimeout(load, 2000);
      }
    };

    load();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  if (!status || !status.total) return null;

  const percent = Math.max(0, Math.min(100, Number(status.percent || 0)));
  const verified = Number(status.resolved || 0) + Number(status.address_only || 0);
  const unresolved = Number(status.unresolved || 0);
  const retries = Number(status.retry_pending || 0);
  const processing = status.state === "processing";
  const completeWithRetries = status.state === "complete_with_retries";

  return (
    <div
      className="fixed top-3 z-40 w-[min(520px,calc(100vw-2rem))] -translate-x-1/2 rounded-lg border border-slate-200 bg-white/95 px-4 py-3 shadow-lg backdrop-blur md:left-[calc(50%+8rem)] left-1/2"
      data-testid="location-resolution-progress"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          {processing ? (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-blue-600" />
          ) : completeWithRetries ? (
            <AlertTriangle className="h-4 w-4 shrink-0 text-amber-500" />
          ) : (
            <CheckCircle2 className="h-4 w-4 shrink-0 text-green-600" />
          )}
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-slate-900">
              {processing ? "Verifying property locations" : completeWithRetries ? "Location verification pass complete" : "Property locations checked"}
            </div>
            <div className="text-xs text-slate-500">
              {Number(status.attempted || 0).toLocaleString()} of {Number(status.total || 0).toLocaleString()} checked
            </div>
          </div>
        </div>
        <div className="shrink-0 text-sm font-semibold text-slate-700">{percent.toFixed(percent % 1 ? 1 : 0)}%</div>
      </div>

      <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-200">
        <div className="h-full rounded-full bg-blue-600 transition-[width] duration-500" style={{ width: `${percent}%` }} />
      </div>

      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500">
        <span><strong className="text-slate-700">{verified.toLocaleString()}</strong> verified</span>
        <span><strong className="text-slate-700">{unresolved.toLocaleString()}</strong> not verified</span>
        {retries > 0 && <span><strong className="text-amber-700">{retries.toLocaleString()}</strong> retry pending</span>}
        {processing && <span><strong className="text-slate-700">{Number(status.pending || 0).toLocaleString()}</strong> remaining</span>}
      </div>
    </div>
  );
}

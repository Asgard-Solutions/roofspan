import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "@/lib/api";
import { CheckCircle2, Loader2, AlertTriangle } from "lucide-react";

const REASON_LABELS = {
  no_result: "No Mapbox address result",
  house_number_mismatch: "Different house number",
  street_mismatch: "Different street",
  city_mismatch: "Different city",
  state_mismatch: "Different state",
  zip_mismatch: "Different ZIP",
  low_confidence: "Mapbox match confidence too low",
  insufficient_precision: "Result not property-level",
  provider_http_error: "Provider HTTP error",
  provider_request_error: "Provider request error",
  single_result_missing: "Single result missing",
  batch_result_missing: "Batch result missing",
  batch_result_count_mismatch: "Unexpected batch result count",
  queued_after_rentcast_import: "Waiting for location lookup",
  unknown: "Other / unknown",
};

const ACCURACY_LABELS = {
  rooftop: "Rooftop",
  parcel: "Parcel",
  point: "Address point",
  interpolated: "Interpolated",
  approximate: "Approximate",
  unknown: "Other",
};

export default function LocationResolutionProgress() {
  const [status, setStatus] = useState(null);
  const [target, setTarget] = useState(null);

  useEffect(() => {
    let alive = true;
    let timer;
    const findTarget = () => {
      if (!alive) return;
      const node = document.querySelector('[data-testid="territory-panel"]');
      if (node) setTarget(node);
      else timer = window.setTimeout(findTarget, 100);
    };
    findTarget();
    return () => { alive = false; if (timer) window.clearTimeout(timer); };
  }, []);

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
    return () => { alive = false; if (timer) window.clearTimeout(timer); };
  }, []);

  if (!target || !status || !status.total) return null;

  const percent = Math.max(0, Math.min(100, Number(status.percent || 0)));
  const resolved = Number(status.resolved || 0);
  const unresolved = Number(status.unresolved || 0);
  const retries = Number(status.retry_pending || 0);
  const cached = Number(status.cached || 0);
  const processing = status.state === "processing";
  const providerRequired = status.state === "provider_required";
  const completeWithRetries = status.state === "complete_with_retries";
  const reasons = (status.rejection_breakdown || []).filter((r) => Number(r.count || 0) > 0).slice(0, 6);
  const accuracies = (status.accuracy_breakdown || []).filter((r) => Number(r.count || 0) > 0);

  return createPortal(
    <div className="border-t border-border bg-slate-50 px-4 py-3" data-testid="location-resolution-progress">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          {processing ? <Loader2 className="h-4 w-4 shrink-0 animate-spin text-blue-600" /> : providerRequired || completeWithRetries ? <AlertTriangle className="h-4 w-4 shrink-0 text-amber-500" /> : <CheckCircle2 className="h-4 w-4 shrink-0 text-green-600" />}
          <div className="min-w-0">
            <div className="text-xs font-semibold text-slate-900">
              {providerRequired ? "Mapbox key required" : processing ? "Locating properties" : completeWithRetries ? "Location pass complete" : "Property locations checked"}
            </div>
            <div className="text-[11px] text-slate-500">
              {providerRequired ? `${Number(status.pending || 0).toLocaleString()} waiting` : `${Number(status.attempted || 0).toLocaleString()} of ${Number(status.total || 0).toLocaleString()} checked`}
            </div>
          </div>
        </div>
        {!providerRequired && <div className="shrink-0 text-xs font-semibold text-slate-700">{percent.toFixed(percent % 1 ? 1 : 0)}%</div>}
      </div>

      {!providerRequired && <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-200"><div className="h-full rounded-full bg-blue-600 transition-[width] duration-500" style={{ width: `${percent}%` }} /></div>}

      <div className="mt-2 flex flex-wrap gap-x-2 gap-y-1 text-[10px] text-slate-500">
        <span><strong className="text-slate-700">{resolved.toLocaleString()}</strong> located</span>
        <span><strong className="text-slate-700">{unresolved.toLocaleString()}</strong> unresolved</span>
        <span><strong className="text-slate-700">{cached.toLocaleString()}</strong> cached</span>
        {retries > 0 && <span><strong className="text-amber-700">{retries.toLocaleString()}</strong> retry</span>}
        {processing && <span><strong className="text-slate-700">{Number(status.pending || 0).toLocaleString()}</strong> remaining</span>}
      </div>

      {providerRequired && <div className="mt-2 text-[11px] text-slate-600">Add and enable a Mapbox access token under Settings → Integrations.</div>}

      {accuracies.length > 0 && <div className="mt-2 flex flex-wrap gap-x-2 gap-y-1 border-t border-slate-200 pt-2 text-[10px] text-slate-500" data-testid="location-accuracy-breakdown">{accuracies.map((item) => <span key={item.accuracy_type}><strong className="text-slate-700">{Number(item.count || 0).toLocaleString()}</strong> {ACCURACY_LABELS[item.accuracy_type] || item.accuracy_type}</span>)}</div>}

      {reasons.length > 0 && <div className="mt-2 border-t border-slate-200 pt-2" data-testid="location-rejection-breakdown"><div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Why unresolved</div><div className="space-y-0.5 text-[10px] text-slate-500">{reasons.map((item) => <div key={item.reason} className="flex items-center justify-between gap-2"><span className="truncate" title={item.reason}>{REASON_LABELS[item.reason] || item.reason}</span><strong className="shrink-0 text-slate-700">{Number(item.count || 0).toLocaleString()}</strong></div>)}</div></div>}
    </div>,
    target
  );
}

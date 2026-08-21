import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { CheckCircle2, Loader2, AlertTriangle } from "lucide-react";

const REASON_LABELS = {
  no_result: "No MapTiler result",
  not_address_result: "Road/place only",
  no_house_number: "House number not located",
  house_number_mismatch: "Different house number",
  street_mismatch: "Different street",
  city_mismatch: "Different city",
  state_mismatch: "Different state",
  zip_mismatch: "Different ZIP",
  returned_street_missing: "Street missing",
  returned_city_missing: "City missing",
  returned_state_missing: "State missing",
  returned_zip_missing: "ZIP missing",
  low_relevance: "Search result too weak",
  invalid_relevance: "Invalid relevance",
  invalid_coordinates: "Invalid coordinates",
  provider_http_error: "Provider HTTP error",
  provider_request_error: "Provider request error",
  single_request_exception: "Provider request exception",
  single_result_count_mismatch: "Unexpected result count",
  outside_territory: "Located outside territory",
  unknown: "Other / unknown",
};

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
  const resolved = Number(status.resolved || 0) + Number(status.address_only || 0);
  const unresolved = Number(status.unresolved || 0);
  const retries = Number(status.retry_pending || 0);
  const processing = status.state === "processing";
  const completeWithRetries = status.state === "complete_with_retries";
  const reasons = (status.rejection_breakdown || []).filter((r) => Number(r.count || 0) > 0).slice(0, 8);

  return (
    <div
      className="fixed top-3 z-40 w-[min(560px,calc(100vw-2rem))] -translate-x-1/2 rounded-lg border border-slate-200 bg-white/95 px-4 py-3 shadow-lg backdrop-blur md:left-[calc(50%+8rem)] left-1/2"
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
              {processing ? "Locating properties with MapTiler" : completeWithRetries ? "Property location pass complete" : "Property locations checked"}
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
        <span><strong className="text-slate-700">{resolved.toLocaleString()}</strong> located</span>
        <span><strong className="text-slate-700">{unresolved.toLocaleString()}</strong> unresolved</span>
        {retries > 0 && <span><strong className="text-amber-700">{retries.toLocaleString()}</strong> retry pending</span>}
        {processing && <span><strong className="text-slate-700">{Number(status.pending || 0).toLocaleString()}</strong> remaining</span>}
      </div>

      {reasons.length > 0 && (
        <div className="mt-2 border-t border-slate-200 pt-2" data-testid="location-rejection-breakdown">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Why locations remain unresolved</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px] text-slate-500">
            {reasons.map((item) => (
              <div key={item.reason} className="flex items-center justify-between gap-2">
                <span className="truncate" title={item.reason}>{REASON_LABELS[item.reason] || item.reason}</span>
                <strong className="shrink-0 text-slate-700">{Number(item.count || 0).toLocaleString()}</strong>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

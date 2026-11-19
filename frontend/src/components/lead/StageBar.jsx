import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export const STAGE_LABELS = {
  overview: "Overview",
  inspection: "Inspection & Measurements",
  estimate: "Estimate & Proposal",
  production: "Production",
  billing: "Billing",
};

export function StageBar({ stages, current, viewing, onSelect }) {
  const ci = stages.indexOf(current);
  return (
    <ol className="grid grid-cols-5 gap-1.5" data-testid="lead-stage-bar">
      {stages.map((s, i) => {
        const state = i < ci ? "done" : i === ci ? "current" : "upcoming";
        const open = s === viewing;
        return (
          <li key={s}>
            <button
              type="button"
              onClick={() => onSelect(s)}
              data-testid={`stage-${s}`}
              data-state={state}
              aria-current={state === "current" ? "step" : undefined}
              className={cn(
                "group flex w-full flex-col items-start gap-1.5 rounded-md border px-3 py-2.5 text-left transition-colors",
                open ? "border-slate-900 bg-white shadow-sm" : "border-transparent hover:bg-white/70"
              )}
            >
              <span className={cn("h-1.5 w-full rounded-full", state === "done" ? "bg-emerald-500" : state === "current" ? "bg-orange-500" : "bg-slate-200")} />
              <span className="flex items-center gap-1.5">
                <span className={cn("flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold",
                  state === "done" ? "bg-emerald-500 text-white" : state === "current" ? "bg-orange-500 text-white" : "bg-slate-200 text-slate-500")}>
                  {state === "done" ? <Check className="h-3 w-3" /> : i + 1}
                </span>
                <span className={cn("hidden text-xs font-semibold sm:inline", state === "upcoming" ? "text-slate-400" : "text-slate-800")}>{STAGE_LABELS[s]}</span>
              </span>
              {state === "current" && <span className="hidden text-[11px] font-medium uppercase tracking-wide text-orange-600 sm:inline" data-testid="stage-current-label">Current stage</span>}
            </button>
          </li>
        );
      })}
    </ol>
  );
}

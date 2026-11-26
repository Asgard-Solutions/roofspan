import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export function NextActionBanner({ action, onGo, viewing, navigateToJob }) {
  const go = action.jobId && action.stage === "production" && viewing === "production"
    ? { label: "Open job", fn: navigateToJob }
    : viewing !== action.stage ? { label: "Go there", fn: () => onGo(action.stage) } : null;
  return (
    <div className={`flex flex-wrap items-center justify-between gap-3 rounded-md border px-4 py-3 ${action.done ? "border-emerald-200 bg-emerald-50" : "border-orange-200 bg-orange-50"}`} data-testid="lead-next-action">
      <div>
        <div className={`text-[11px] font-semibold uppercase tracking-wider ${action.done ? "text-emerald-700" : "text-orange-700"}`}>Next step</div>
        <div className="text-sm font-medium text-slate-900" data-testid="lead-next-action-text">{action.text}</div>
      </div>
      {go && <Button size="sm" onClick={go.fn} data-testid="lead-next-action-go">{go.label} <ArrowRight className="h-4 w-4" /></Button>}
    </div>
  );
}

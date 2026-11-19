import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

// Next action derived from the calculated stage + facts (never from the stage the user is viewing).
export function nextAction(wf, isManage) {
  const f = wf.facts;
  switch (wf.stage) {
    case "overview":
      return { text: "Create the customer record to start the sale.", stage: "overview" };
    case "inspection":
      if (!f.inspections) return { text: "Record the roof inspection.", stage: "inspection" };
      if (!f.has_measurements) return { text: "Measure the roof.", stage: "inspection" };
      return { text: "Build the estimate.", stage: "estimate" };
    case "estimate":
      if (!f.quotes) return { text: "Turn the estimate into a proposal.", stage: "estimate" };
      if (f.quotes_sent) return { text: isManage ? "Waiting on the customer. Follow up, or record their decision." : "Waiting on the customer. Follow up with them.", stage: "estimate" };
      if (f.quotes_draft) return { text: "Send the proposal to the customer.", stage: "estimate" };
      return { text: "Proposal declined. Revise the estimate or close the lead.", stage: "estimate" };
    case "production":
      if (!f.jobs_scheduled) return { text: "Schedule the job.", stage: "production", jobId: f.first_job_id };
      return { text: "Job is underway. Track it on the job page.", stage: "production", jobId: f.first_job_id };
    default:
      if (!f.invoices) return { text: isManage ? "Create the invoice." : "Work complete. The office handles invoicing.", stage: "billing" };
      if (f.invoices_paid < f.invoices) return { text: "Collect the balance due.", stage: "billing" };
      return { text: "Paid in full. Nothing left to do.", stage: "billing", done: true };
  }
}

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

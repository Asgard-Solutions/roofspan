import { CheckCircle2, AlertCircle, CalendarDays, Users, Hammer, Boxes, UserCog } from "lucide-react";
import { dayOnly } from "@/lib/format";
import { rangeLabel } from "@/components/DateRangePicker";

const ICON = { schedule: CalendarDays, crew: Users, materials: Boxes };

function Fact({ icon: Icon, label, value, warn, testid }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-slate-400"><Icon className="h-3.5 w-3.5" />{label}</div>
      <div className={`mt-0.5 truncate text-sm font-medium ${warn ? "text-amber-700" : "text-slate-900"}`} data-testid={testid}>{value}</div>
    </div>
  );
}

export function ReadyPanel({ job }) {
  const r = job.readiness || { ready: null, reasons: [] };
  const closed = r.ready === null;
  const short = r.reasons.some((x) => x.code === "materials");
  const range = { from: dayOnly(job.scheduled_start), to: dayOnly(job.scheduled_end) };
  const tone = closed ? "border-slate-200 bg-slate-50" : r.ready ? "border-green-200 bg-green-50" : "border-amber-200 bg-amber-50";
  return (
    <div className={`rounded-md border p-4 ${tone}`} data-testid="job-ready-panel">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex items-center gap-2" data-testid="job-ready-state">
          {closed ? <Hammer className="h-5 w-5 text-slate-500" /> : r.ready ? <CheckCircle2 className="h-5 w-5 text-green-600" /> : <AlertCircle className="h-5 w-5 text-amber-600" />}
          <span className="font-heading text-base font-semibold text-slate-900">
            {closed ? `Job ${job.status.replace("_", " ")}` : r.ready ? "Ready to install" : "Not ready to install"}
          </span>
        </div>
        {!closed && !r.ready && (
          <div className="flex flex-wrap gap-2" data-testid="job-ready-reasons">
            {r.reasons.map((x) => {
              const I = ICON[x.code] || AlertCircle;
              return <span key={x.code} className="inline-flex items-center gap-1 rounded-full bg-white px-2.5 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-amber-200" data-testid={`job-ready-reason-${x.code}`}><I className="h-3 w-3" />{x.label}</span>;
            })}
          </div>
        )}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Fact icon={UserCog} label="Job manager" value={job.assigned_user_name || "Unassigned"} warn={!job.assigned_user_name} testid="job-fact-manager" />
        <Fact icon={Users} label="Crew" value={job.crew_name || "No crew"} warn={!job.crew_name && !closed} testid="job-fact-crew" />
        <Fact icon={CalendarDays} label="Scheduled" value={rangeLabel(range)} warn={!range.from && !closed} testid="job-fact-schedule" />
        <Fact icon={Boxes} label="Materials" value={short ? "Short" : job.materials?.length ? "Ready" : "Not planned"} warn={short} testid="job-fact-materials" />
      </div>
    </div>
  );
}

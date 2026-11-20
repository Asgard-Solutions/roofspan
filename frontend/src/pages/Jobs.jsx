import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { money, shortDay } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Hammer } from "lucide-react";

const sc = { created: "bg-slate-100 text-slate-600", pending: "bg-amber-50 text-amber-700", scheduled: "bg-blue-50 text-blue-700", in_progress: "bg-orange-50 text-orange-700", completed: "bg-green-50 text-green-700", cancelled: "bg-slate-100 text-slate-500" };
const FILTERS = [["active", "Active"], ["unscheduled", "Needs scheduling"], ["ready", "Ready to install"], ["not_ready", "Not ready"], ["completed", "Completed"], ["all", "All"]];
const ACTIVE = ["created", "pending", "scheduled", "in_progress"];
const MAT = {
  ready: { cls: "bg-green-50 text-green-700", label: "Ready" },
  short: { cls: "bg-red-50 text-red-700", label: "Short" },
  none: { cls: "bg-slate-100 text-slate-500", label: "Not planned" },
};

function Ready({ r }) {
  if (!r || r.ready === null) return <span className="text-slate-400">—</span>;
  if (r.ready) return <Badge variant="secondary" className="bg-green-50 text-green-700">Ready</Badge>;
  return <span className="text-xs text-amber-700">{r.reasons.map((x) => x.label).join(" · ")}</span>;
}

const match = (f, j) => ({
  active: ACTIVE.includes(j.status),
  unscheduled: ACTIVE.includes(j.status) && !j.scheduled_start,
  ready: j.readiness?.ready === true,
  not_ready: j.readiness?.ready === false,
  completed: j.status === "completed",
  all: true,
}[f]);

export default function Jobs() {
  const [jobs, setJobs] = useState([]);
  const [filter, setFilter] = useState("active");
  useEffect(() => { api.get("/jobs").then((r) => setJobs(r.data)).catch(() => {}); }, []);
  const rows = jobs.filter((j) => match(filter, j));
  const short = jobs.filter((j) => ACTIVE.includes(j.status) && j.material_status === "short").length;

  return (
    <div>
      <PageHeader title="Jobs" description={short ? `${short} active job${short === 1 ? "" : "s"} short on material` : "Sold work, schedule and crew"} testid="page-jobs" />
      <div className="space-y-4 p-6 sm:p-8">
        {jobs.length === 0 ? (
          <div className="flex max-w-xl items-start gap-4 rounded-md border border-dashed border-border bg-white p-8">
            <Hammer className="mt-0.5 h-6 w-6 text-orange-500" />
            <div>
              <h3 className="font-heading text-lg font-semibold text-slate-900">No jobs yet</h3>
              <p className="mt-1 text-sm text-slate-500">When a customer accepts a proposal, the job shows up here ready to schedule.</p>
            </div>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap gap-2" data-testid="jobs-filters">
              {FILTERS.map(([k, l]) => (
                <Button key={k} size="sm" variant={filter === k ? "default" : "outline"} onClick={() => setFilter(k)} data-testid={`jobs-filter-${k}`}>{l}</Button>
              ))}
            </div>
            <div className="overflow-x-auto rounded-md border border-border bg-white">
              <Table data-testid="jobs-table">
                <TableHeader><TableRow><TableHead>Job #</TableHead><TableHead>Customer / Property</TableHead><TableHead>Status</TableHead><TableHead>Install dates</TableHead><TableHead>Job manager</TableHead><TableHead>Crew</TableHead><TableHead>Ready to install</TableHead><TableHead>Materials</TableHead><TableHead className="text-right">Value</TableHead></TableRow></TableHeader>
                <TableBody>
                  {rows.map((j) => {
                    const m = MAT[j.material_status] || MAT.none;
                    return (
                      <TableRow key={j.id} data-testid={`job-row-${j.id}`}>
                        <TableCell className="font-medium text-slate-900"><Link to={`/jobs/${j.id}`} className="hover:text-orange-600 hover:underline" data-testid={`job-link-${j.id}`}>{j.number}</Link></TableCell>
                        <TableCell className="max-w-[260px]">
                          <div className="truncate text-slate-900">{j.customer_name || j.scope || "—"}</div>
                          {j.property_address && <div className="truncate text-xs text-slate-500">{j.property_address}</div>}
                        </TableCell>
                        <TableCell><Badge className={sc[j.status] || ""} variant="secondary">{j.status.replace("_", " ")}</Badge></TableCell>
                        <TableCell className={j.scheduled_start ? "text-slate-700" : "text-amber-600"} data-testid={`job-scheduled-${j.id}`}>{j.scheduled_start ? `${shortDay(j.scheduled_start)}${j.scheduled_end && j.scheduled_end.slice(0, 10) !== j.scheduled_start.slice(0, 10) ? ` – ${shortDay(j.scheduled_end)}` : ""}` : "Not scheduled"}</TableCell>
                        <TableCell className="text-slate-600" data-testid={`job-manager-${j.id}`}>{j.assigned_user_name || <span className="text-slate-400">Unassigned</span>}</TableCell>
                        <TableCell className="text-slate-600" data-testid={`job-crew-${j.id}`}>{j.crew_name || <span className="text-slate-400">No crew</span>}</TableCell>
                        <TableCell data-testid={`job-ready-${j.id}`}><Ready r={j.readiness} /></TableCell>
                        <TableCell><Badge className={m.cls} variant="secondary" data-testid={`job-materials-${j.id}`}>{m.label}</Badge></TableCell>
                        <TableCell className="text-right tabular-nums">{money(j.total)}</TableCell>
                      </TableRow>
                    );
                  })}
                  {rows.length === 0 && <TableRow><TableCell colSpan={9} className="text-center text-sm text-slate-400">No jobs match this filter.</TableCell></TableRow>}
                </TableBody>
              </Table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

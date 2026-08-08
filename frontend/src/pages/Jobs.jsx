import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { money, shortDate } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Hammer } from "lucide-react";

export default function Jobs() {
  const [jobs, setJobs] = useState([]);
  useEffect(() => { api.get("/jobs").then((r) => setJobs(r.data)).catch(() => {}); }, []);

  return (
    <div>
      <PageHeader title="Jobs" description={`${jobs.length} job${jobs.length === 1 ? "" : "s"} — created from accepted quotes`} testid="page-jobs" />
      <div className="p-6 sm:p-8">
        {jobs.length === 0 ? (
          <div className="flex max-w-xl items-start gap-4 rounded-md border border-dashed border-border bg-white p-8">
            <Hammer className="mt-0.5 h-6 w-6 text-orange-500" />
            <div>
              <h3 className="font-heading text-lg font-semibold text-slate-900">No jobs yet</h3>
              <p className="mt-1 text-sm text-slate-500">Accept a quote from a lead to create a job. Full scheduling & operations arrive in Phase 4.</p>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-md border border-border bg-white">
            <Table data-testid="jobs-table">
              <TableHeader><TableRow><TableHead>Job #</TableHead><TableHead>Scope</TableHead><TableHead>Status</TableHead><TableHead>Value</TableHead><TableHead>Created</TableHead></TableRow></TableHeader>
              <TableBody>
                {jobs.map((j) => (
                  <TableRow key={j.id} data-testid={`job-row-${j.id}`}>
                    <TableCell className="font-medium text-slate-900">{j.number}</TableCell>
                    <TableCell className="text-slate-600">{j.scope || "—"}</TableCell>
                    <TableCell><Badge variant="secondary">{j.status}</Badge></TableCell>
                    <TableCell className="tabular-nums">{money(j.total)}</TableCell>
                    <TableCell className="text-slate-500">{shortDate(j.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  );
}

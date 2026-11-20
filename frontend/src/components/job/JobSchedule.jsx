import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { dayOnly, dayToIso } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DateRangePicker } from "@/components/DateRangePicker";
import { Save, Loader2 } from "lucide-react";

const STATUSES = ["created", "pending", "scheduled", "in_progress", "completed", "cancelled"];

const fromJob = (j) => ({ status: j.status || "created", range: { from: dayOnly(j.scheduled_start), to: dayOnly(j.scheduled_end) }, notes: j.schedule_notes || "" });

export function JobSchedule({ job, canManage, onSaved }) {
  const [s, setS] = useState(() => fromJob(job));
  const [busy, setBusy] = useState(false);
  useEffect(() => { setS(fromJob(job)); }, [job.id, job.status, job.scheduled_start, job.scheduled_end, job.schedule_notes]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    setBusy(true);
    try {
      const body = { status: s.status, schedule_notes: s.notes };
      const start = dayToIso(s.range.from), end = dayToIso(s.range.to || s.range.from);
      const same = (iso, saved) => (iso || "").slice(0, 10) === (saved || "").slice(0, 10);
      if (!same(start, job.scheduled_start) || !same(end, job.scheduled_end)) Object.assign(body, { scheduled_start: start, scheduled_end: end });
      const { data } = await api.patch(`/jobs/${job.id}`, body);
      toast.success("Schedule saved"); onSaved(data);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[160px_1fr]">
        <div className="space-y-1.5"><Label>Status</Label>
          <Select value={s.status} onValueChange={(v) => setS({ ...s, status: v })} disabled={!canManage}>
            <SelectTrigger data-testid="job-status-select"><SelectValue /></SelectTrigger>
            <SelectContent>{STATUSES.map((x) => <SelectItem key={x} value={x}>{x.replace("_", " ")}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5"><Label>Install dates</Label>
          <DateRangePicker value={s.range} onChange={(range) => setS({ ...s, range })} disabled={!canManage} testid="job-dates" />
        </div>
      </div>
      <div className="space-y-1.5"><Label>Scheduling notes</Label><Textarea value={s.notes} onChange={(e) => setS({ ...s, notes: e.target.value })} disabled={!canManage} data-testid="job-schednotes" /></div>
      {canManage && <Button onClick={save} disabled={busy} data-testid="save-schedule">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Save className="h-4 w-4" /> Save schedule</>}</Button>}
    </div>
  );
}

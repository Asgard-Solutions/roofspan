import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { Label } from "@/components/ui/label";
import { UserSearchPicker } from "@/components/UserSearchPicker";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const NONE = "__none__";

export function JobPeople({ job, canManage, onChange }) {
  const [crews, setCrews] = useState([]);
  const [busy, setBusy] = useState(null);

  useEffect(() => {
    if (!canManage) return;
    api.get("/crews", { params: { active: true } }).then((r) => setCrews(r.data)).catch(() => {});
  }, [canManage]);

  const save = async (kind, value) => {
    setBusy(kind);
    try {
      const id = !value || value === NONE ? null : value;
      const { data } = kind === "manager"
        ? await api.put(`/jobs/${job.id}/assign`, { user_id: id })
        : await api.patch(`/jobs/${job.id}`, { crew_id: id });
      onChange(data);
      const name = kind === "manager" ? data.assigned_user_name : data.crew_name;
      toast.success(name ? `${kind === "manager" ? "Job manager" : "Crew"}: ${name}` : `${kind === "manager" ? "Job manager" : "Crew"} cleared`);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(null); }
  };

  if (!canManage) {
    return (
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div><Label>Job manager</Label><p className="mt-1.5 text-slate-700" data-testid="job-manager-readonly">{job.assigned_user_name || "Unassigned"}</p></div>
        <div><Label>Crew</Label><p className="mt-1.5 text-slate-700" data-testid="job-crew-readonly">{job.crew_name || "No crew"}</p></div>
      </div>
    );
  }

  const crewOptions = job.crew_id && !crews.some((c) => c.id === job.crew_id)
    ? [...crews, { id: job.crew_id, name: job.crew_active === false ? `${job.crew_name} (inactive)` : job.crew_name }] : crews;

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div className="space-y-1.5">
        <Label>Job manager</Label>
        <UserSearchPicker valueId={job.assigned_user_id} valueLabel={job.assigned_user_name} onSelect={(id) => save("manager", id)}
          disabled={busy === "manager"} testid="job-manager-picker" />
        <p className="text-xs text-slate-400">Owns the job. A salesperson manager can see it in Office and the Field app.</p>
      </div>
      <div className="space-y-1.5">
        <Label>Crew</Label>
        <Select value={job.crew_id || NONE} onValueChange={(v) => save("crew", v)} disabled={busy === "crew"}>
          <SelectTrigger data-testid="job-crew-select"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE} data-testid="job-crew-none">No crew</SelectItem>
            {crewOptions.map((c) => <SelectItem key={c.id} value={c.id} data-testid={`job-crew-${c.id}`}>{c.name}</SelectItem>)}
          </SelectContent>
        </Select>
        <p className="text-xs text-slate-400">Does the install. <Link to="/settings/crews" className="text-orange-600 hover:underline" data-testid="job-manage-crews-link">Manage crews</Link></p>
      </div>
    </div>
  );
}

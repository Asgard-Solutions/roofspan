import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ChevronLeft, Plus, Pencil, Trash2, Check, X, Loader2 } from "lucide-react";

function CrewRow({ c, onSaved, onDelete }) {
  const [edit, setEdit] = useState(false);
  const [name, setName] = useState(c.name);
  const put = async (body) => {
    try { await api.put(`/crews/${c.id}`, body); setEdit(false); onSaved(); } catch (e) { toast.error(apiError(e)); }
  };
  return (
    <TableRow data-testid={`crew-row-${c.id}`}>
      <TableCell>
        {edit ? (
          <div className="flex items-center gap-1">
            <Input value={name} onChange={(e) => setName(e.target.value)} className="h-8 max-w-xs" autoFocus data-testid={`crew-name-input-${c.id}`} onKeyDown={(e) => e.key === "Enter" && put({ name })} />
            <Button size="sm" variant="ghost" onClick={() => put({ name })} data-testid={`crew-save-${c.id}`}><Check className="h-4 w-4" /></Button>
            <Button size="sm" variant="ghost" onClick={() => { setEdit(false); setName(c.name); }}><X className="h-4 w-4" /></Button>
          </div>
        ) : <span className={c.active ? "font-medium text-slate-900" : "text-slate-400"} data-testid={`crew-name-${c.id}`}>{c.name}</span>}
      </TableCell>
      <TableCell className="tabular-nums text-slate-600" data-testid={`crew-jobs-${c.id}`}>{c.active_job_count} active · {c.job_count} total</TableCell>
      <TableCell>
        <div className="flex items-center gap-2">
          <Switch checked={c.active} onCheckedChange={(v) => put({ active: v })} data-testid={`crew-active-${c.id}`} />
          <Badge variant="secondary" className={c.active ? "bg-green-50 text-green-700" : ""}>{c.active ? "Active" : "Inactive"}</Badge>
        </div>
      </TableCell>
      <TableCell className="text-right">
        <Button size="sm" variant="ghost" onClick={() => setEdit(true)} data-testid={`crew-edit-${c.id}`}><Pencil className="h-4 w-4" /></Button>
        {c.job_count === 0 && <Button size="sm" variant="ghost" onClick={() => onDelete(c)} data-testid={`crew-delete-${c.id}`}><Trash2 className="h-4 w-4" /></Button>}
      </TableCell>
    </TableRow>
  );
}

export default function Crews() {
  const [crews, setCrews] = useState(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api.get("/crews").then((r) => setCrews(r.data)).catch((e) => toast.error(apiError(e))), []);
  useEffect(() => { load(); }, [load]);

  const add = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try { await api.post("/crews", { name }); setName(""); toast.success("Crew added"); load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const remove = async (c) => {
    try { await api.delete(`/crews/${c.id}`); toast.success("Crew deleted"); load(); } catch (e) { toast.error(apiError(e)); }
  };

  return (
    <div>
      <PageHeader title="Crews" description="The install crews you assign to jobs. Inactive crews stay on past jobs but can't be picked for new work." testid="page-crews" />
      <div className="max-w-3xl space-y-4 p-6 sm:p-8">
        <Link to="/settings" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-900" data-testid="crews-back-link"><ChevronLeft className="h-4 w-4" /> Settings</Link>
        <div className="flex gap-2">
          <Input placeholder="New crew name, e.g. Crew B" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} className="max-w-sm" data-testid="crew-new-name" />
          <Button onClick={add} disabled={busy || !name.trim()} data-testid="crew-add-btn"><Plus className="h-4 w-4" /> Add crew</Button>
        </div>
        <div className="rounded-md border border-border bg-white">
          {!crews ? <div className="p-6"><Loader2 className="h-4 w-4 animate-spin text-slate-400" /></div> : (
            <Table data-testid="crews-table">
              <TableHeader><TableRow><TableHead>Crew</TableHead><TableHead>Jobs</TableHead><TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
              <TableBody>
                {crews.map((c) => <CrewRow key={c.id} c={c} onSaved={load} onDelete={remove} />)}
                {crews.length === 0 && <TableRow><TableCell colSpan={4} className="text-center text-sm text-slate-400" data-testid="crews-empty">No crews yet. Add your first crew above.</TableCell></TableRow>}
              </TableBody>
            </Table>
          )}
        </div>
      </div>
    </div>
  );
}

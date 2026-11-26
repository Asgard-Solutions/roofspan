import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { FollowUpDialog } from "@/components/lead/FollowUpDialog";
import { kindLabel, whenOf, WHEN_STYLE, WHEN_LABEL, dateTime } from "@/lib/followups";
import { BellRing, Plus, MessageSquarePlus, Check, CalendarClock, X, History } from "lucide-react";

const VISIT_LABEL = { no_answer: "No answer", not_interested: "Not interested", interested: "Interested", callback: "Callback requested", appointment: "Appointment set", do_not_knock: "Do Not Knock" };

function OpenItem({ f, onAct }) {
  const w = whenOf(f.due_at);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-border p-2.5 text-sm" data-testid={`followup-${f.id}`}>
      <div className="min-w-0">
        <div className="flex items-center gap-2"><Badge variant="secondary" className={WHEN_STYLE[w]} data-testid={`followup-when-${f.id}`}>{WHEN_LABEL[w]}</Badge>
          <span className="font-medium text-slate-900">{kindLabel(f.kind)}</span><span className="text-xs text-slate-500">{dateTime(f.due_at)}</span></div>
        {f.note && <div className="mt-1 text-slate-600">{f.note}</div>}
      </div>
      <div className="flex gap-1">
        <Button size="sm" variant="outline" onClick={() => onAct("complete", f)} data-testid={`followup-done-${f.id}`}><Check className="h-3.5 w-3.5" /> Done</Button>
        <Button size="sm" variant="ghost" onClick={() => onAct("reschedule", f)} title="Reschedule" aria-label="Reschedule" data-testid={`followup-reschedule-${f.id}`}><CalendarClock className="h-3.5 w-3.5" /></Button>
        <Button size="sm" variant="ghost" className="text-slate-400 hover:text-red-600" onClick={() => onAct("cancel", f)} title="Cancel follow-up" aria-label="Cancel follow-up" data-testid={`followup-cancel-${f.id}`}><X className="h-3.5 w-3.5" /></Button>
      </div>
    </div>
  );
}

function Activity({ items }) {
  if (!items.length) return <p className="text-sm text-slate-500" data-testid="lead-activity-empty">No contact logged yet.</p>;
  return (
    <ul className="space-y-1.5" data-testid="lead-activity">
      {items.map((a) => (
        <li key={a.key} className="flex gap-3 text-sm" data-testid={`activity-${a.key}`}>
          <span className="w-28 shrink-0 text-xs text-slate-400">{dateTime(a.at)}</span>
          <span className="text-slate-700"><span className="font-medium">{a.title}</span>{a.text ? ` · ${a.text}` : ""}{a.by ? <span className="text-slate-400"> · {a.by}</span> : null}</span>
        </li>
      ))}
    </ul>
  );
}

// Follow-ups + contact history for one lead. Shown above the stage panels so it's visible at every stage.
export function FollowUpsPanel({ leadId, leadStatus, visits, onChanged }) {
  const closed = leadStatus === "won" || leadStatus === "lost";
  const [rows, setRows] = useState([]);
  const [mode, setMode] = useState(null);
  const [target, setTarget] = useState(null);
  const [showAll, setShowAll] = useState(false);
  const load = useCallback(() => api.get(`/leads/${leadId}/follow-ups`).then((r) => setRows(r.data)).catch((e) => toast.error(apiError(e))), [leadId]);
  useEffect(() => { load(); }, [load]);

  const act = async (m, f) => {
    if (m !== "cancel") { setTarget(f || null); setMode(m); return; }
    setRows((prev) => prev.filter((x) => x.id !== f.id));
    const t = setTimeout(async () => {
      try { await api.patch(`/follow-ups/${f.id}`, { status: "cancelled" }); onChanged?.(); } catch (e) { toast.error(apiError(e)); }
      load();
    }, 5000);
    toast("Follow-up cancelled", { duration: 5000, action: { label: "Undo", onClick: () => { clearTimeout(t); load(); } } });
  };
  const open = rows.filter((r) => r.status === "open").sort((a, b) => new Date(a.due_at) - new Date(b.due_at));
  const history = [
    ...rows.filter((r) => r.status !== "open").map((r) => ({ key: `f-${r.id}`, at: r.completed_at || r.due_at, by: r.completed_by,
      title: r.status === "cancelled" ? `${kindLabel(r.kind)} cancelled` : kindLabel(r.kind), text: [r.note, r.outcome].filter(Boolean).join(" → ") })),
    ...(visits || []).map((v) => ({ key: `v-${v.id}`, at: v.visited_at, by: v.user_email, title: `Door visit: ${VISIT_LABEL[v.outcome] || v.outcome}`, text: v.notes })),
  ].sort((a, b) => new Date(b.at) - new Date(a.at));

  return (
    <div className="rounded-md border border-border bg-white" data-testid="section-follow-ups">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2"><BellRing className="h-4 w-4 text-orange-600" /><h3 className="font-heading font-semibold text-slate-900">Follow-ups</h3>
          <span className="text-xs text-slate-500" data-testid="followup-open-count">{open.length} open</span></div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => act("log")} data-testid="log-contact-button"><MessageSquarePlus className="h-4 w-4" /> Log contact</Button>
          {!closed && <Button size="sm" onClick={() => act("schedule")} data-testid="schedule-followup-button"><Plus className="h-4 w-4" /> Follow-up</Button>}
        </div>
      </div>
      <div className="grid gap-4 p-4 lg:grid-cols-2">
        <div className="space-y-2">
          {open.length === 0 ? <p className="text-sm text-slate-500" data-testid="followup-none">{closed ? `Lead is ${leadStatus}. Change the status to reopen it and schedule follow-ups.` : "Nothing scheduled. Add a follow-up so this lead doesn't go quiet."}</p>
            : open.map((f) => <OpenItem key={f.id} f={f} onAct={act} />)}
        </div>
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-slate-400"><History className="h-3.5 w-3.5" /> Contact history</div>
          <Activity items={showAll ? history : history.slice(0, 5)} />
          {history.length > 5 && <button type="button" className="mt-2 text-xs font-medium text-orange-700 hover:underline" onClick={() => setShowAll(!showAll)} data-testid="activity-toggle">{showAll ? "Show less" : `Show all ${history.length}`}</button>}
        </div>
      </div>
      <FollowUpDialog mode={mode} leadId={leadId} target={target} closed={closed} onClose={() => setMode(null)} onSaved={() => { load(); onChanged?.(); }} />
    </div>
  );
}

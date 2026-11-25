import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DateTimeField } from "@/components/lead/DateTimeField";
import { KINDS, kindLabel, quickPicks, toLocalInput } from "@/lib/followups";
import { Loader2 } from "lucide-react";

const TITLES = { schedule: "Schedule a follow-up", log: "Log a contact", complete: "Mark follow-up done", reschedule: "Reschedule follow-up" };
const iso = (local) => (local ? new Date(local).toISOString() : null);

function KindSelect({ value, onChange, testid }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger data-testid={testid}><SelectValue /></SelectTrigger>
      <SelectContent>{KINDS.map((k) => <SelectItem key={k.value} value={k.value}>{k.label}</SelectItem>)}</SelectContent>
    </Select>
  );
}

// One dialog for every follow-up action: schedule, log a contact, complete (with optional next one), reschedule.
export function FollowUpDialog({ mode, leadId, target, onClose, onSaved }) {
  const [kind, setKind] = useState("call");
  const [when, setWhen] = useState("");
  const [note, setNote] = useState("");
  const [outcome, setOutcome] = useState("");
  const [next, setNext] = useState(false);
  const [nextWhen, setNextWhen] = useState("");
  const [nextNote, setNextNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!mode) return;
    setKind(target?.kind || "call"); setNote(target?.note || ""); setOutcome(""); setNextNote("");
    setWhen(target?.due_at ? toLocalInput(new Date(target.due_at)) : toLocalInput(quickPicks()[1].date));
    setNext(mode === "log" || mode === "complete"); setNextWhen(toLocalInput(quickPicks()[2].date));
  }, [mode, target]);

  const save = async () => {
    setBusy(true);
    try {
      if (mode === "schedule") await api.post(`/leads/${leadId}/follow-ups`, { kind, due_at: iso(when), note: note || null });
      if (mode === "reschedule") await api.patch(`/follow-ups/${target.id}`, { due_at: iso(when), note: note || null }, { headers: { "If-Match": target.if_match } });
      if (mode === "log") await api.post(`/leads/${leadId}/follow-ups`, { kind, status: "done", note: note || null });
      if (mode === "complete") await api.patch(`/follow-ups/${target.id}`, { status: "done", outcome: outcome || null });
      if ((mode === "log" || mode === "complete") && next) {
        await api.post(`/leads/${leadId}/follow-ups`, { kind: "call", due_at: iso(nextWhen), note: nextNote || null });
      }
      toast.success({ schedule: "Follow-up scheduled", reschedule: "Follow-up moved", log: "Contact logged", complete: "Follow-up done" }[mode]);
      onSaved(); onClose();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const needsWhen = mode === "schedule" || mode === "reschedule";
  return (
    <Dialog open={!!mode} onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="followup-dialog">
        <DialogHeader>
          <DialogTitle>{TITLES[mode]}</DialogTitle>
          {mode === "complete" && target && <DialogDescription>{kindLabel(target.kind)}{target.note ? ` · ${target.note}` : ""}</DialogDescription>}
        </DialogHeader>
        <div className="space-y-3">
          {(mode === "schedule" || mode === "log") && <div className="space-y-1.5"><Label>{mode === "log" ? "How did you reach them?" : "Type"}</Label><KindSelect value={kind} onChange={setKind} testid="followup-kind" /></div>}
          {needsWhen && <div className="space-y-1.5"><Label>When</Label><DateTimeField value={when} onChange={setWhen} testid="followup-when" /></div>}
          {mode !== "complete" && <div className="space-y-1.5"><Label>{mode === "log" ? "What happened?" : "Note"}</Label><Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder={mode === "log" ? "Talked to homeowner, wants pricing" : "Call about the proposal"} data-testid="followup-note" /></div>}
          {mode === "complete" && <div className="space-y-1.5"><Label>Outcome (optional)</Label><Textarea value={outcome} onChange={(e) => setOutcome(e.target.value)} placeholder="Left voicemail" data-testid="followup-outcome" /></div>}
          {(mode === "log" || mode === "complete") && (
            <div className="space-y-2 rounded-md border border-border p-3">
              <label className="flex items-center gap-2 text-sm font-medium text-slate-800"><Checkbox checked={next} onCheckedChange={(v) => setNext(!!v)} data-testid="followup-next-toggle" /> Schedule the next follow-up</label>
              {next && <><DateTimeField value={nextWhen} onChange={setNextWhen} testid="followup-next-when" />
                <Textarea value={nextNote} onChange={(e) => setNextNote(e.target.value)} placeholder="What's the next step?" data-testid="followup-next-note" /></>}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={busy || (needsWhen && !when) || (next && (mode === "log" || mode === "complete") && !nextWhen)} data-testid="followup-save">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

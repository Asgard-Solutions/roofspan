import { useState } from "react";
import { CalendarDays } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { quickPicks, toLocalInput } from "@/lib/followups";

const pad = (n) => String(n).padStart(2, "0");
const TIMES = Array.from({ length: 96 }, (_, i) => `${pad(Math.floor(i / 4))}:${pad((i % 4) * 15)}`);
const timeLabel = (hm) => { const [h, m] = hm.split(":").map(Number); return new Date(2000, 0, 1, h, m).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }); };
const dayLabel = (d) => d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" });

// Same RoofSpan popover calendar as Job scheduling (single day) + a time list. Value stays the local
// "YYYY-MM-DDTHH:mm" string the follow-up dialogs already use, so storage/time-zone handling is unchanged.
export function DateTimeField({ value, onChange, testid }) {
  const [open, setOpen] = useState(false);
  const cur = value ? new Date(value) : null;
  const hm = cur ? `${pad(cur.getHours())}:${pad(cur.getMinutes())}` : "09:00";
  const times = TIMES.includes(hm) ? TIMES : [...TIMES, hm].sort();
  // new Date(y, m, d, h, min) builds wall-clock local time; on a DST-gap time the browser moves it forward.
  const set = (day, t) => { const [h, m] = t.split(":").map(Number); onChange(toLocalInput(new Date(day.getFullYear(), day.getMonth(), day.getDate(), h, m))); };
  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <Button type="button" variant="outline" data-testid={`${testid}-date-trigger`}
              className={`flex-1 justify-start gap-2 font-normal ${cur ? "text-slate-900" : "text-slate-400"}`}>
              <CalendarDays className="h-4 w-4 shrink-0 text-orange-600" />
              <span className="truncate" data-testid={`${testid}-date-label`}>{cur ? dayLabel(cur) : "Pick a day"}</span>
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start" data-testid={`${testid}-popover`}>
            <Calendar mode="single" defaultMonth={cur || new Date()} selected={cur || undefined}
              onSelect={(d) => { if (d) { set(d, hm); setOpen(false); } }} />
          </PopoverContent>
        </Popover>
        <Select value={hm} onValueChange={(t) => set(cur || new Date(), t)}>
          <SelectTrigger className="w-[130px]" data-testid={`${testid}-time`}><SelectValue /></SelectTrigger>
          <SelectContent className="max-h-64">
            {times.map((t) => <SelectItem key={t} value={t} data-testid={`${testid}-time-${t.replace(":", "")}`}>{timeLabel(t)}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {quickPicks().map((q) => (
          <Button key={q.label} type="button" size="sm" variant="outline" className="h-7 rounded-full px-3 text-xs"
            onClick={() => onChange(toLocalInput(q.date))} data-testid={`${testid}-pick-${q.label.toLowerCase().replace(/\s+/g, "-")}`}>
            {q.label}
          </Button>
        ))}
      </div>
    </div>
  );
}

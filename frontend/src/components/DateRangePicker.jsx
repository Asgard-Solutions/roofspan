import { useEffect, useState } from "react";
import { CalendarDays, X } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import { Button } from "@/components/ui/button";
import { dayCount } from "@/lib/format";

const fmt = (d) => d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

function useWide() {
  const q = "(min-width: 768px)";
  const [wide, setWide] = useState(() => window.matchMedia(q).matches);
  useEffect(() => {
    const m = window.matchMedia(q);
    const on = () => setWide(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return wide;
}

export function rangeLabel({ from, to }) {
  if (!from) return "Not scheduled";
  if (to && to < from) return `${fmt(from)} – ${fmt(to)} · end is before start`;
  const days = dayCount(from, to);
  return `${fmt(from)}${to && +to !== +from ? ` – ${fmt(to)}` : ""} · ${days} day${days === 1 ? "" : "s"}`;
}

export function DateRangePicker({ value, onChange, disabled, testid = "date-range" }) {
  const [open, setOpen] = useState(false);
  const [fresh, setFresh] = useState(false);
  const openChange = (o) => { setOpen(o); setFresh(o); };
  const select = (r, day) => {
    if (fresh) { setFresh(false); onChange({ from: day, to: null }); return; }
    onChange({ from: r?.from || null, to: r?.to || null });
  };
  const wide = useWide();
  const days = dayCount(value.from, value.to);
  return (
    <Popover open={open} onOpenChange={openChange}>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" disabled={disabled} data-testid={`${testid}-trigger`}
          className={`w-full justify-start gap-2 font-normal ${value.from ? "text-slate-900" : "text-slate-400"}`}>
          <CalendarDays className="h-4 w-4 shrink-0 text-orange-600" />
          <span className="truncate">{rangeLabel(value)}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start" data-testid={`${testid}-popover`}>
        <Calendar mode="range" numberOfMonths={wide ? 2 : 1} defaultMonth={value.from || new Date()}
          selected={value.from && !(value.to && value.to < value.from) ? { from: value.from, to: value.to || undefined } : undefined}
          onSelect={select} />
        <div className="flex items-center justify-between gap-3 border-t border-border px-3 py-2">
          <span className="text-xs text-slate-500" data-testid={`${testid}-days`}>
            {!value.from ? "Pick the start day, then the end day" : days < 1 ? "The saved end date is before the start. Pick the dates again." : `${days} scheduled day${days === 1 ? "" : "s"}`}
          </span>
          <div className="flex gap-2">
            {value.from && <Button size="sm" variant="ghost" onClick={() => onChange({ from: null, to: null })} data-testid={`${testid}-clear`}><X className="h-3.5 w-3.5" /> Clear</Button>}
            <Button size="sm" onClick={() => openChange(false)} data-testid={`${testid}-done`}>Done</Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}

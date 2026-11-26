export const LEAD_STATUSES = [
  { value: "new", label: "New" },
  { value: "contacted", label: "Contacted" },
  { value: "qualified", label: "Qualified" },
  { value: "won", label: "Won" },
  { value: "lost", label: "Lost" },
];
export const OPEN_STATUSES = ["new", "contacted", "qualified"];
export const LEAD_STATUS_COLOR = {
  new: "bg-blue-50 text-blue-700", contacted: "bg-amber-50 text-amber-700", qualified: "bg-violet-50 text-violet-700",
  won: "bg-green-50 text-green-700", lost: "bg-slate-100 text-slate-500", archived: "bg-slate-100 text-slate-400",
};
export const KINDS = [
  { value: "call", label: "Call" }, { value: "text", label: "Text" }, { value: "email", label: "Email" },
  { value: "visit", label: "Visit" }, { value: "meeting", label: "Meeting" }, { value: "other", label: "Other" },
];
export const kindLabel = (k) => (KINDS.find((x) => x.value === k) || { label: "Follow up" }).label;

const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
export function whenOf(due) {
  if (!due) return "none";
  const d = new Date(due), s = startOfDay(new Date());
  const e = new Date(s.getFullYear(), s.getMonth(), s.getDate() + 1); // next local midnight (DST-safe: 23/25h days)
  return d < s ? "overdue" : d < e ? "today" : "upcoming";
}
export const WHEN_STYLE = { overdue: "bg-red-50 text-red-700", today: "bg-orange-50 text-orange-700", upcoming: "bg-slate-100 text-slate-600" };
export const WHEN_LABEL = { overdue: "Overdue", today: "Today", upcoming: "Upcoming" };

export const dateTime = (d) => (d ? new Date(d).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—");

// <input type="datetime-local"> wants local "YYYY-MM-DDTHH:mm"
export function toLocalInput(d) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
export function quickPicks() {
  const at = (days, h) => { const d = startOfDay(new Date()); d.setDate(d.getDate() + days); d.setHours(h, 0, 0, 0); return d; };
  return [
    { label: "Later today", date: (() => { const d = new Date(); d.setMinutes(0, 0, 0); d.setHours(d.getHours() + 2); return d; })() },
    { label: "Tomorrow 9am", date: at(1, 9) },
    { label: "In 3 days", date: at(3, 9) },
    { label: "Next week", date: at(7, 9) },
  ];
}
export const tz = () => Intl.DateTimeFormat().resolvedOptions().timeZone;

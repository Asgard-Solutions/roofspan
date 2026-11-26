// Shared Field follow-up helpers (pure, Node-testable). Due/overdue is worked out on the device from
// due_at so My Day stays correct offline even when the cached copy is from yesterday.
const KIND_LABELS = { call: "Call", text: "Text", email: "Email", visit: "Visit", meeting: "Meeting", other: "Follow up" };
const LEAD_STATUSES = ["new", "contacted", "qualified", "won", "lost"];
const OPEN_STATUSES = ["new", "contacted", "qualified"];
const DAY_PICKS = [["Today", 0], ["Tomorrow", 1], ["In 3 days", 3], ["Next week", 7]];
const TIME_PICKS = [["9 AM", 9], ["12 PM", 12], ["3 PM", 15], ["5 PM", 17]];

function startOfDay(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }

function whenOf(due, now = new Date()) {
  if (!due) return "none";
  const d = new Date(due);
  const s = startOfDay(now);
  const e = new Date(s.getTime() + 86400000);
  return d < s ? "overdue" : d < e ? "today" : "upcoming";
}

function pickDate(dayOffset, hour, now = new Date()) {
  const d = startOfDay(now);
  d.setDate(d.getDate() + dayOffset);
  d.setHours(hour, 0, 0, 0);
  return d;
}

function kindLabel(k) { return KIND_LABELS[k] || "Follow up"; }

function fmt(due) {
  if (!due) return "";
  const d = new Date(due);
  return `${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })} ${d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`;
}

// Re-derive the My Day lists from the cached server copy using the device clock.
function myDayView(md, now = new Date()) {
  const fus = ((md && md.follow_ups && md.follow_ups.items) || []).map((i) => ({ ...i, when: whenOf(i.date, now) }))
    .filter((i) => i.when !== "upcoming");
  const insp = ((md && md.inspections && md.inspections.items) || []).map((i) => ({ ...i, when: whenOf(i.date, now) }));
  return {
    overdue: fus.filter((i) => i.when === "overdue"),
    today: fus.filter((i) => i.when === "today"),
    inspections: insp,
    proposals: (md && md.proposals && md.proposals.items) || [],
    noFollowUp: (md && md.no_follow_up) || { count: 0, items: [] },
  };
}

// Optimistically reflect a queued follow-up change in the cached My Day copy.
function applyToMyDay(md, lead, fu) {
  if (!md || !md.follow_ups) return md;
  const items = (md.follow_ups.items || []).filter((i) => i.id !== fu.id);
  if (fu.status === "open") {
    items.push({ id: fu.id, lead_id: lead.id, title: lead.name, subtitle: `${kindLabel(fu.kind)}${fu.note ? ": " + fu.note : ""}`,
      date: fu.due_at, kind: fu.kind, _pending: true });
    items.sort((a, b) => new Date(a.date) - new Date(b.date));
  }
  return { ...md, follow_ups: { ...md.follow_ups, items } };
}

// Next action wording when offline: earliest open follow-up first, otherwise the server's cached suggestion.
function nextActionOf(lead) {
  const open = ((lead && lead.follow_ups) || []).filter((f) => f.status === "open").sort((a, b) => new Date(a.due_at) - new Date(b.due_at));
  if (open[0]) return { text: `${kindLabel(open[0].kind)}${open[0].note ? ": " + open[0].note : ""}`, due_at: open[0].due_at, when: whenOf(open[0].due_at) };
  return (lead && lead.next_action) || null;
}

module.exports = { KIND_LABELS, LEAD_STATUSES, OPEN_STATUSES, DAY_PICKS, TIME_PICKS, whenOf, pickDate, kindLabel, fmt, myDayView, applyToMyDay, nextActionOf };

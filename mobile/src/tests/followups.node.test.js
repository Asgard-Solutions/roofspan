/*
 * RoofSpan Field — follow-up helpers (pure Node, no device).
 * Run: node src/tests/followups.node.test.js
 */
const f = require("../followups");

let failures = 0;
function ok(cond, msg) {
  if (cond) console.log("  \u2713", msg);
  else { console.error("  \u2717 FAIL:", msg); failures++; }
}

const now = new Date(2026, 5, 10, 14, 0, 0);
ok(f.whenOf(new Date(2026, 5, 9, 23, 0), now) === "overdue", "yesterday is overdue");
ok(f.whenOf(new Date(2026, 5, 10, 8, 0), now) === "today", "earlier today is due today, not overdue");
ok(f.whenOf(new Date(2026, 5, 10, 23, 59), now) === "today", "late today is due today");
ok(f.whenOf(new Date(2026, 5, 11, 0, 0), now) === "upcoming", "tomorrow is upcoming");
ok(f.whenOf(null, now) === "none", "no date is none");

const p = f.pickDate(1, 9, now);
ok(p.getDate() === 11 && p.getHours() === 9 && p.getMinutes() === 0, "Tomorrow 9 AM pick");
ok(f.pickDate(7, 15, now).getDate() === 17, "Next week pick");

ok(JSON.stringify(f.LEAD_STATUSES) === JSON.stringify(["new", "contacted", "qualified", "won", "lost"]), "shared status list matches Office");

// A cached My Day from yesterday: yesterday's 'today' item must now show as overdue, tomorrow's appears as today.
const cached = { follow_ups: { items: [
  { id: "a", lead_id: "L1", date: new Date(2026, 5, 9, 10).toISOString(), when: "today" },
  { id: "b", lead_id: "L2", date: new Date(2026, 5, 10, 16).toISOString(), when: "upcoming" },
  { id: "c", lead_id: "L3", date: new Date(2026, 5, 12, 9).toISOString(), when: "upcoming" },
] }, inspections: { items: [] }, proposals: { items: [{ id: "q" }] }, no_follow_up: { count: 2, items: [] } };
const v = f.myDayView(cached, now);
ok(v.overdue.map((i) => i.id).join() === "a", "stale 'today' item recomputed as overdue offline");
ok(v.today.map((i) => i.id).join() === "b", "item due later today shows under Due today");
ok(!v.overdue.concat(v.today).some((i) => i.id === "c"), "future follow-up is not on My Day");
ok(v.proposals.length === 1 && v.noFollowUp.count === 2, "proposals and no-follow-up carried through");

// Offline create / complete reflect in the cached My Day.
const lead = { id: "L9", name: "Pat" };
const added = f.applyToMyDay(cached, lead, { id: "n", kind: "call", note: "pricing", due_at: new Date(2026, 5, 10, 15).toISOString(), status: "open" });
ok(added.follow_ups.items.some((i) => i.id === "n" && i._pending && i.subtitle === "Call: pricing"), "offline follow-up appears as pending");
const done = f.applyToMyDay(added, lead, { id: "n", status: "done" });
ok(!done.follow_ups.items.some((i) => i.id === "n"), "completed follow-up leaves My Day");
ok(f.applyToMyDay(null, lead, { id: "x" }) === null, "no cached My Day is left alone");

const na = f.nextActionOf({ follow_ups: [
  { id: 1, status: "done", kind: "call", due_at: "2026-06-01T10:00:00Z" },
  { id: 2, status: "open", kind: "text", note: "send photos", due_at: "2026-06-20T10:00:00Z" },
  { id: 3, status: "open", kind: "call", note: "first", due_at: "2026-06-15T10:00:00Z" },
], next_action: { text: "server" } });
ok(na.text === "Call: first", "next action = earliest open follow-up");
ok(f.nextActionOf({ follow_ups: [], next_action: { text: "Book the inspection" } }).text === "Book the inspection", "falls back to server suggestion");

if (failures) { console.error(`\n${failures} failure(s)`); process.exit(1); }
console.log("\nall follow-up helper checks passed");

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

// DST (run with TZ=America/Chicago): Nov 1 2026 is a 25h day, Mar 8 2026 is 23h.
const fallBack = new Date(2026, 10, 1, 12, 0);
ok(f.whenOf(new Date(2026, 10, 1, 23, 30), fallBack) === "today", "23:30 on the fall-back day is still today");
ok(f.whenOf(new Date(2026, 10, 2, 0, 0), fallBack) === "upcoming", "next midnight after fall-back is upcoming");
const spring = new Date(2026, 2, 8, 12, 0);
ok(f.whenOf(new Date(2026, 2, 8, 23, 30), spring) === "today", "23:30 on the spring-forward day is today");
ok(f.whenOf(new Date(2026, 2, 9, 0, 30), spring) === "upcoming", "00:30 after spring-forward is upcoming (not today)");
ok(f.pickDate(1, 9, new Date(2026, 2, 7, 12)).getHours() === 9, "Tomorrow 9 AM across spring-forward stays 9 AM");

// Offline overlay: queued create shows; queued done/cancel never reappears as open; other leads untouched.
const server = [{ id: "s1", status: "open", due_at: "2026-06-10T15:00:00Z" }, { id: "s2", status: "open", due_at: "2026-06-11T15:00:00Z" }];
const muts = [
  { kind: "follow_up", state: "pending", body: { id: "p1", lead_id: "L", kind: "call", due_at: "2026-06-12T15:00:00Z" } },
  { kind: "follow_up_update", state: "failed", client_id: f.updateClientId("s1"), body: { status: "done", lead_id: "L" } },
  { kind: "follow_up_update", state: "synced", client_id: f.updateClientId("s2"), body: { status: "cancelled", lead_id: "L" } },
  { kind: "follow_up", state: "pending", body: { id: "x", lead_id: "OTHER" } },
];
const ov = f.overlayPending(server, muts, "L");
ok(ov.find((x) => x.id === "p1" && x._pending), "pending offline create is shown");
ok(ov.find((x) => x.id === "s1").status === "done", "queued done is not shown as open again");
ok(ov.find((x) => x.id === "s2").status === "open", "already-synced change defers to server copy");
ok(!ov.find((x) => x.id === "x"), "other lead's queued follow-up is not mixed in");
ok(f.overlayPending([{ id: "p1", status: "open" }], muts, "L").filter((x) => x.id === "p1").length === 1, "no duplicate once the create has synced");
ok(f.overlayPending([{ id: "s1", status: "cancelled" }], muts, "L")[0].status === "cancelled", "server terminal state is never overwritten by a queued change");

const conf = f.followUpConflicts([
  { kind: "follow_up_update", state: "conflict", client_id: f.updateClientId("a"), body: { status: "done", lead_id: "L" }, serverValue: { status: "open", if_match: "t" } },
  { kind: "follow_up_update", state: "conflict", client_id: f.updateClientId("b"), body: { status: "done", lead_id: "L" }, serverValue: { status: "cancelled" } },
], "L");
ok(conf.length === 2 && conf[0].fid === "a" && conf[0].canApplyMine && !conf[1].canApplyMine, "conflicts: apply-mine only while Office still has it open");
ok(f.nextActionOf({ follow_ups: [], next_action: { type: "follow_up", text: "Call: old", fallback: { text: "Book or record the roof inspection." } } }).text === "Book or record the roof inspection.",
  "after completing the last follow-up offline, next action falls back to the stage guidance (not the stale follow-up)");

if (failures) { console.error(`\n${failures} failure(s)`); process.exit(1); }
console.log("\nall follow-up helper checks passed");

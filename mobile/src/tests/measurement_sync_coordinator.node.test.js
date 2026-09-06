/* RoofSpan Field — central lead-aware measurement sync coordinator (pure Node). */
const { createMeasurementSyncCoordinator, parseInvalidation } = require("../measurementSyncCoordinator");

let failures = 0;
function ok(cond, msg) { if (cond) console.log("  \u2713", msg); else { console.error("  \u2717 FAIL:", msg); failures++; } }

// ---------------- invalidation event parsing ----------------
const p = parseInvalidation({ lead_id: "L1", measurement_set_id: "S1", revision_id: "R1", updated_at: "t2" });
ok(p.leadScope.lead_id === "L1" && p.measurementSetId === "S1" && p.revisionId === "R1" && p.updatedAt === "t2", "parses a full measurement_changed event into scope + watermark");
ok(parseInvalidation({ property_id: "P1" }).leadScope.property_id === "P1", "parses a property-scoped invalidation");
ok(parseInvalidation({}).leadScope === null, "an event with no scope yields no lead scope");

// ---------------- active-lead registry (lead-aware, not screen-owned) ----------------
let clock = 1000;
const co = createMeasurementSyncCoordinator({ now: () => clock, minIntervalMs: 4000 });
co.registerActiveLead({ lead_id: "L1" });
co.registerActiveLead({ property_id: "P9" });
ok(co.activeLeads().length === 2, "tracks multiple active leads independently");
ok(co.isActive({ lead_id: "L1" }) && !co.isActive({ lead_id: "LX" }), "knows which leads are active");
ok(co.leadKeyOf({ inspection_id: "I3" }) === "inspection:I3", "derives a stable lead key for inspection scope");

// ---------------- watermarks + staleness (no draft guessing) ----------------
co.noteRevisionWatermark("R1", "2026-06-01T10:00:00Z");
ok(co.isRevisionStale("R1", "2026-06-01T09:00:00Z") === true, "cached revision behind the watermark → stale");
ok(co.isRevisionStale("R1", "2026-06-01T10:00:00Z") === false, "cached revision at the watermark → current");
ok(co.isRevisionStale("R1", null) === true, "known server version but nothing cached → stale");
ok(co.isRevisionStale("RX", "anything") === false, "unknown revision watermark → not provably stale");
co.noteRevisionWatermark("R1", "2026-05-01T00:00:00Z"); // out-of-order OLDER event
ok(co.revisionWatermark("R1") === "2026-06-01T10:00:00Z", "an out-of-order older watermark never regresses the known latest");

co.noteSketchWatermark("R1", "ST1", 5);
ok(co.isSketchStale("R1", "ST1", 4) === true && co.isSketchStale("R1", "ST1", 5) === false, "sketch staleness compares document_version");
ok(co.sketchVersion("R1", "ST1") === 5, "exposes the known authoritative sketch version");

// ---------------- trigger coalescing ----------------
ok(co.shouldRefresh("lead_open", { lead_id: "L1" }) === true, "FORCE trigger (lead_open) always refreshes");
ok(co.shouldRefresh("acknowledgement", { lead_id: "L1" }) === true, "acknowledgement always refreshes");
ok(co.shouldRefresh("office_invalidation", { lead_id: "L1" }) === true, "office invalidation always refreshes");
co.markRefreshed({ lead_id: "L1" });                 // now clean, lastRefreshAt = clock
ok(co.shouldRefresh("foreground", { lead_id: "L1" }) === false, "a plain foreground trigger is throttled right after a refresh");
clock += 5000;
ok(co.shouldRefresh("foreground", { lead_id: "L1" }) === true, "after the min interval a foreground trigger refreshes again");

// invalidate marks the lead dirty → next plain trigger refreshes immediately
co.markRefreshed({ lead_id: "L1" });
const inv = co.invalidate({ lead_id: "L1", revision_id: "R1", updated_at: "2026-07-01T00:00:00Z" });
ok(inv && inv.leadScope.lead_id === "L1", "invalidate returns the parsed scope");
ok(co.revisionWatermark("R1") === "2026-07-01T00:00:00Z", "invalidate adopts the newer watermark");
ok(co.shouldRefresh("foreground", { lead_id: "L1" }) === true, "an invalidated (dirty) lead refreshes on the next trigger even within the interval");

if (failures) { console.error(`\nMEASUREMENT SYNC COORDINATOR: ${failures} failure(s)`); process.exit(1); }
console.log("\nMEASUREMENT SYNC COORDINATOR: all passed");

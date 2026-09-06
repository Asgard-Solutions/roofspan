/* RoofSpan Field — sketch editor OPEN decision: Office discovery + 4-way validation (pure Node). */
const { resolveInitialSketch } = require("../roofSketchFieldController");

let failures = 0;
function ok(cond, msg) { if (cond) console.log("  \u2713", msg); else { console.error("  \u2717 FAIL:", msg); failures++; } }

const docA = { edit_mode: "connected_graph", vertices: [{ id: "v1", x: 0, y: 0 }, { id: "v2", x: 10, y: 0 }], edges: [{ id: "e1", a: "v1", b: "v2" }], facets: [], penetrations: [] };
const docB = { edit_mode: "connected_graph", vertices: [{ id: "v1", x: 0, y: 0 }, { id: "v2", x: 20, y: 0 }], edges: [{ id: "e1", a: "v1", b: "v2" }], facets: [], penetrations: [] };
const draft = (document, document_version, edit_generation = 3) => ({ document, document_version, edit_generation, base_server_document: document, edit_mode: "connected_graph" });
const server = (document, document_version) => ({ document, document_version, edit_mode: "connected_graph" });

// (4) No local work → Office wins.
let r = resolveInitialSketch({ server: server(docA, 5), structureId: "s1" });
ok(r.source === "server" && r.decision === "office" && r.documentVersion === 5, "no local draft → Office version wins");

// (2) Active unsynced local edit → local remains authoritative even though an Office copy exists.
r = resolveInitialSketch({ draft: draft(docB, 5), server: server(docA, 5), structureId: "s1", hasActiveMutation: true });
ok(r.source === "local_draft" && r.decision === "local_active" && !r.retireObsoleteDraft, "active unsynced local edit stays authoritative");

// (1) No active work, identical content at the SAME version → retire the obsolete draft, Office wins.
r = resolveInitialSketch({ draft: draft(docA, 5), server: server(docA, 5), structureId: "s1", hasActiveMutation: false });
ok(r.source === "server" && r.decision === "office_identical" && r.retireObsoleteDraft === true, "obsolete draft identical to Office at same version → retired");

// (3) Office version advanced past the draft → conflict review (local preserved, not overwritten).
r = resolveInitialSketch({ draft: draft(docB, 4), server: server(docA, 7), structureId: "s1", hasActiveMutation: false });
ok(r.source === "local_draft" && r.decision === "conflict" && r.conflict === true && r.serverDetail.document_version === 7, "Office advanced → conflict review with the Office copy attached");
ok(!r.retireObsoleteDraft, "Office-advanced conflict never silently retires local work");

// No active work, same version but DIFFERENT content (edits never queued) → preserve local (never lose work).
r = resolveInitialSketch({ draft: draft(docB, 5), server: server(docA, 5), structureId: "s1", hasActiveMutation: false });
ok(r.source === "local_draft" && r.decision === "local" && !r.retireObsoleteDraft, "same version but different content, no active mutation → preserve local");

// Draft with no server copy at all → local (offline / brand-new Office).
r = resolveInitialSketch({ draft: draft(docA, 2), structureId: "s1" });
ok(r.source === "local_draft" && r.decision === "local", "draft with no Office copy → local preserved");

// No draft and no server → fresh document.
r = resolveInitialSketch({ structureId: "s1" });
ok(r.source === "new" && r.decision === "new", "no draft + no server → new document");

if (failures) { console.error(`\nSKETCH OPEN DECISION: ${failures} failure(s)`); process.exit(1); }
console.log("\nSKETCH OPEN DECISION: all passed");

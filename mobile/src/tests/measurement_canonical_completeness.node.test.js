/* RoofSpan Field — COMPLETE canonical comparator: every editable field must be detected so startup
 * recovery never erases a legitimate unsaved edit. One test per omitted field group (paranoid on purpose). */
const { canonicalEqual, canonicalFingerprint, classifyOrphanWorkingDraft } = require("../measurementRecovery");

let failures = 0;
function ok(c, m) { if (c) console.log("  \u2713", m); else { console.error("  \u2717 FAIL:", m); failures++; } }

// A rich baseline working draft touching every field group.
const base = () => ({
  working: true,
  base: { id: "R1", if_match: "t1" },
  structures: [{ ref: "s1", name: "Main", structure_type: "main_house", included_in_scope: true, stories: 2, approx_height_ft: 18, attachment: "attached", notes: "front porch" }],
  facets: [{ ref: "f1", facet_label: "F1", pitch_rise: 6, area_sqft: 800, width_ft: 40, length_ft: 20, position_offset_ft: 0, structure_id: "s1", roof_material: "shingle", orientation_azimuth: 180, geometry: { points: [[0, 0], [40, 0]] }, notes: "steep" }],
  edges: [{ ref: "e1", edge_type: "hip", length_ft: 25, label: "H1", notes: "long hip", facet_id: "f1", facet_id_secondary: "f2" }],
  pens: [{ ref: "p1", pen_type: "skylight", quantity: 1, facet_id: "f1", diameter_in: 24, width_in: 30, length_in: 48, notes: "leaky" }],
  summary: { existing_covering_type: "shingle", layers: 1 },
});
// The recorded baseline fingerprint (what recovery compares an unsaved draft against).
const baseFp = canonicalFingerprint(base());
const baseRevision = { id: "R1", updated_at: "t1", structures: base().structures, facets: base().facets, edges: base().edges, penetrations: base().pens, summary: base().summary };

// A single-field edit must be DETECTED (canonicalEqual → false) AND preserved (classifier → keep, never clear).
function editPreserved(label, mutate) {
  const wd = base(); wd.base_fingerprint = baseFp; mutate(wd);
  const detected = canonicalFingerprint(wd) !== baseFp && !canonicalEqual(wd, baseRevision);
  const decision = classifyOrphanWorkingDraft({ wd, hasActiveMutation: false, baseRevision });
  ok(detected && decision.action === "keep", `edit to ${label} is detected and the draft is preserved (never cleared)`);
}

editPreserved("structure notes", (wd) => { wd.structures[0].notes = "CHANGED"; });
editPreserved("roof-plane structure assignment", (wd) => { wd.facets[0].structure_id = "s2"; });
editPreserved("roof material", (wd) => { wd.facets[0].roof_material = "metal"; });
editPreserved("roof-plane notes", (wd) => { wd.facets[0].notes = "CHANGED"; });
editPreserved("orientation (azimuth)", (wd) => { wd.facets[0].orientation_azimuth = 90; });
editPreserved("roof-plane geometry", (wd) => { wd.facets[0].geometry = { points: [[0, 0], [50, 0]] }; });
editPreserved("roof-line primary plane assignment", (wd) => { wd.edges[0].facet_id = "f3"; });
editPreserved("roof-line secondary plane assignment", (wd) => { wd.edges[0].facet_id_secondary = "f9"; });
editPreserved("roof-line label", (wd) => { wd.edges[0].label = "H2"; });
editPreserved("roof-line notes", (wd) => { wd.edges[0].notes = "CHANGED"; });
editPreserved("penetration plane assignment", (wd) => { wd.pens[0].facet_id = "f7"; });
editPreserved("penetration diameter", (wd) => { wd.pens[0].diameter_in = 36; });
editPreserved("penetration width", (wd) => { wd.pens[0].width_in = 99; });
editPreserved("penetration length", (wd) => { wd.pens[0].length_in = 99; });
editPreserved("penetration notes", (wd) => { wd.pens[0].notes = "CHANGED"; });

// The genuinely-unchanged draft (only a temporary React key differs) still clears — base_fingerprint path.
const unchanged = base(); unchanged.base_fingerprint = baseFp; unchanged.facets[0].ref = "NEW-REACT-KEY";
ok(canonicalFingerprint(unchanged) === baseFp, "a temporary React key change does NOT alter the fingerprint (non-business metadata ignored)");
ok(classifyOrphanWorkingDraft({ wd: unchanged, hasActiveMutation: false, baseRevision }).action === "clear", "a truly-unchanged draft (base token matches, no active mutation) is cleared");

// Base token advanced → even an unchanged-looking draft is a conflict, never a silent clear.
const advanced = base(); advanced.base_fingerprint = baseFp;
ok(classifyOrphanWorkingDraft({ wd: advanced, hasActiveMutation: false, baseRevision: { ...baseRevision, updated_at: "t2" } }).action === "conflict", "Office token advanced → conflict (never silently cleared)");

// Active mutation → always keep.
ok(classifyOrphanWorkingDraft({ wd: base(), hasActiveMutation: true, baseRevision }).action === "keep", "an active mutation is always preserved");

if (failures) { console.error(`\nCANONICAL COMPLETENESS: ${failures} failure(s)`); process.exit(1); }
console.log("\nCANONICAL COMPLETENESS: all passed");

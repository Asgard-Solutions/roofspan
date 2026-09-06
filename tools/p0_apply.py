#!/usr/bin/env python3
"""Apply the final P0 merge-shape correction and verified repository cleanup.

The temporary GitHub Actions runner executes this against a complete Linux checkout. It deliberately
changes no workflow files so its verified commit can be pushed with the job token; permanent workflow
updates are applied separately through the repository connector. This script removes itself before commit.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
MOBILE_TEST = ROOT / "mobile/src/tests/measurement_durable_merge_base.node.test.js"
RECONCILE = ROOT / "mobile/src/measurementReconcile.js"
RECOVERY = ROOT / "mobile/src/measurementRecovery.js"


def run(*cmd: str, cwd: Path | None = None, env: dict | None = None) -> None:
    subprocess.run(cmd, cwd=cwd or ROOT, env=env, check=True)


def run_expected_failure(*cmd: str) -> None:
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    print(result.stdout, flush=True)
    print(result.stderr, flush=True)
    if result.returncode == 0:
        raise RuntimeError("Identity-preservation regression unexpectedly passed before normalization")


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old[:140]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# RED: the authoritative Office document must be converted to the exact Field
# write contract before a three-way merge can select any Office-owned group.
# ---------------------------------------------------------------------------
MOBILE_TEST.write_text(
    '''"use strict";\nconst assert = require("assert");\nconst Q = require("../queue");\nconst M = require("../measurementReconcile");\nconst R = require("../measurementRecovery");\n\nfunction clone(v) { return JSON.parse(JSON.stringify(v)); }\nfunction detail() {\n  return {\n    id: "R1", updated_at: "2026-09-06T10:00:00Z", source: "office",\n    provider: "provider-a", report_id: "report-a", reported_area_sqft: 1000, notes: "base notes",\n    structures: [{ id: "S1", name: "House", structure_type: "main_house", included_in_scope: true, sort: 0 }],\n    facets: [{ id: "F1", structure_id: "S1", facet_label: "F1", pitch_rise: 6, area_sqft: 100, sort: 0 }],\n    edges: [{ id: "E1", facet_id: "F1", edge_type: "ridge", length_ft: 40, sort: 0 }],\n    penetrations: [{ id: "P1", facet_id: "F1", pen_type: "pipe_boot", quantity: 1, sort: 0 }],\n    summary: { existing_layers: 1 },\n  };\n}\n\n(function authoritative_output_is_normalized_to_identity_preserving_write_shape() {\n  const body = M.measurementDocumentFromRevision(detail());\n  assert.strictEqual(body.source, "office");\n  assert.strictEqual(body.structures[0].ref, "S1");\n  assert.strictEqual(body.structures[0].id, undefined);\n  assert.strictEqual(body.facets[0].ref, "F1");\n  assert.strictEqual(body.facets[0].structure_ref, "S1");\n  assert.strictEqual(body.facets[0].structure_id, undefined);\n  assert.strictEqual(body.edges[0].ref, "E1");\n  assert.strictEqual(body.edges[0].facet_ref, "F1");\n  assert.strictEqual(body.edges[0].facet_id, undefined);\n  assert.strictEqual(body.penetrations[0].ref, "P1");\n  assert.strictEqual(body.penetrations[0].facet_ref, "F1");\n  assert.strictEqual(body.penetrations[0].facet_id, undefined);\n})();\n\n(function durable_row_survives_working_draft_clear_and_merges_disjoint_changes() {\n  const baseDetail = detail();\n  const baseBody = M.measurementDocumentFromRevision(baseDetail);\n  const fieldBody = { ...clone(baseBody), lead_id: "L1", mark_field_complete: false };\n  fieldBody.edges[0].length_ft = 45;\n  const mutation = Q.makeMutation({\n    kind: "measurement_update", method: "put", path: "/mobile/measurements/R1",\n    body: fieldBody, ifMatch: baseDetail.updated_at, baseBody, baseToken: baseDetail.updated_at,\n  });\n  assert.deepStrictEqual(mutation.base_body, baseBody);\n  assert.strictEqual(mutation.base_token, baseDetail.updated_at);\n\n  const office = clone(baseDetail);\n  office.updated_at = "2026-09-06T10:05:00Z";\n  office.source = "import";\n  office.facets[0].area_sqft = 110;\n  office.facets.push({\n    id: "F2", structure_id: "S1", facet_label: "F2", pitch_rise: 8, area_sqft: 75, sort: 1,\n  });\n  office.notes = "Office-only note";\n  const inputs = M.measurementConflictMergeInputs({ ...mutation, state: "conflict" }, office);\n  assert.strictEqual(inputs.ok, true);\n  assert.strictEqual(inputs.office.facets[0].ref, "F1");\n  assert.strictEqual(inputs.office.facets[0].structure_ref, "S1");\n  assert.strictEqual(inputs.office.facets[1].ref, "F2");\n  const merged = R.threeWayMergeMeasurement(inputs.base, inputs.field, inputs.office);\n  assert.strictEqual(merged.clean, true);\n  const next = M.buildMergedMeasurementBody(mutation.body, merged.merged);\n  assert.strictEqual(next.facets.length, 2, "Office-only plane addition must survive");\n  assert.strictEqual(next.facets[0].area_sqft, 110, "Office-only plane change must survive");\n  assert.strictEqual(next.facets[0].ref, "F1", "existing plane UUID must be sent as ref");\n  assert.strictEqual(next.facets[0].structure_ref, "S1", "plane relationship must stay linked");\n  assert.strictEqual(next.facets[1].ref, "F2", "Office-added plane UUID must be retained");\n  assert.strictEqual(next.edges[0].length_ft, 45, "Field-only roof-line change must survive");\n  assert.strictEqual(next.edges[0].ref, "E1", "existing line UUID must be sent as ref");\n  assert.strictEqual(next.edges[0].facet_ref, "F1", "line-to-plane relationship must stay linked");\n  assert.strictEqual(next.source, "import", "Office-only source change must survive");\n  assert.strictEqual(next.notes, "Office-only note", "Office-only hidden metadata must survive");\n  assert.strictEqual(next.lead_id, "L1", "routing scope remains from the Field mutation");\n})();\n\n(function repeated_local_save_keeps_the_original_pending_base() {\n  const base = detail();\n  const original = M.measurementDocumentFromRevision(base);\n  const pending = Q.makeMutation({\n    kind: "measurement_update", method: "put", path: "/mobile/measurements/R1", body: original,\n    ifMatch: base.updated_at, baseBody: original, baseToken: base.updated_at,\n  });\n  const optimistic = clone(base);\n  optimistic.updated_at = base.updated_at;\n  optimistic.facets[0].area_sqft = 999;\n  const chosen = M.chooseDurableMeasurementBase(optimistic, pending);\n  assert.strictEqual(chosen.ok, true);\n  assert.deepStrictEqual(chosen.baseBody, original);\n  assert.strictEqual(chosen.baseToken, base.updated_at);\n})();\n\n(function legacy_or_mismatched_rows_cannot_blindly_keep_mine() {\n  const base = detail();\n  const body = M.measurementDocumentFromRevision(base);\n  const legacy = Q.makeMutation({\n    kind: "measurement_update", method: "put", path: "/mobile/measurements/R1",\n    body, ifMatch: base.updated_at,\n  });\n  assert.strictEqual(M.measurementConflictMergeInputs({ ...legacy, state: "conflict" }, base).ok, false);\n  assert.strictEqual(M.chooseDurableMeasurementBase(base, legacy).ok, false);\n\n  const mismatch = { ...legacy, base_body: body, base_token: "older-token" };\n  const result = M.measurementConflictMergeInputs(mismatch, base);\n  assert.strictEqual(result.ok, false);\n  assert.strictEqual(result.reason, "base_token_mismatch");\n})();\n\n(function pre_normalization_durable_rows_are_healed_when_read() {\n  const rawServerShape = detail();\n  const pending = Q.makeMutation({\n    kind: "measurement_update", method: "put", path: "/mobile/measurements/R1",\n    body: M.measurementDocumentFromRevision(rawServerShape), ifMatch: rawServerShape.updated_at,\n    baseBody: rawServerShape, baseToken: rawServerShape.updated_at,\n  });\n  const chosen = M.chooseDurableMeasurementBase(rawServerShape, pending);\n  assert.strictEqual(chosen.ok, true);\n  assert.strictEqual(chosen.baseBody.structures[0].ref, "S1");\n  assert.strictEqual(chosen.baseBody.facets[0].structure_ref, "S1");\n})();\n\n(function superseded_create_conversion_uses_the_acknowledged_server_as_its_new_base() {\n  const server = detail();\n  server.updated_at = "2026-09-06T10:10:00Z";\n  const newerCreate = Q.makeMutation({ kind: "measurement", method: "post", path: "/mobile/measurements", body: { lead_id: "L1", structures: [] } });\n  const converted = M.buildConvertedUpdateMutation(newerCreate, "R1", server.updated_at, server);\n  assert.strictEqual(converted.kind, "measurement_update");\n  assert.strictEqual(converted.base_token, server.updated_at);\n  assert.deepStrictEqual(converted.base_body, M.measurementDocumentFromRevision(server));\n  assert.deepStrictEqual(converted.body, newerCreate.body);\n})();\n\nconsole.log("measurement durable merge-base tests passed");\n''',
    encoding="utf-8",
)
run_expected_failure("node", "mobile/src/tests/measurement_durable_merge_base.node.test.js")

# ---------------------------------------------------------------------------
# GREEN: normalize server-output rows and already-durable rows into the exact
# MeasurementRevisionIn child contract. Existing UUIDs become `ref`; all child
# relationships become *_ref. Include `source` in the metadata merge.
# ---------------------------------------------------------------------------
old_document = '''function _cloneJson(value) { return value == null ? value : JSON.parse(JSON.stringify(value)); }
function measurementDocumentFromRevision(src) {
  if (!src || typeof src !== "object") return null;
  const out = {
    structures: _cloneJson(src.structures || []),
    facets: _cloneJson(src.facets || []),
    edges: _cloneJson(src.edges || []),
    penetrations: _cloneJson(src.penetrations != null ? src.penetrations : (src.pens || [])),
    summary: _cloneJson(src.summary || {}),
  };
  for (const key of ["provider", "report_id", "reported_area_sqft", "notes"]) {
    if (Object.prototype.hasOwnProperty.call(src, key)) out[key] = _cloneJson(src[key]);
  }
  return out;
}'''
new_document = '''function _cloneJson(value) { return value == null ? value : JSON.parse(JSON.stringify(value)); }
function _ref(row, preferred, fallback) {
  const value = row && row[preferred] != null ? row[preferred] : (row && row[fallback] != null ? row[fallback] : null);
  return value == null || value === "" ? null : String(value);
}
function measurementDocumentFromRevision(src) {
  if (!src || typeof src !== "object") return null;
  const structures = (src.structures || []).map((row, index) => ({
    ref: _ref(row, "ref", "id"),
    name: row.name || "",
    structure_type: row.structure_type || "main_house",
    included_in_scope: row.included_in_scope !== false,
    stories: row.stories == null ? null : row.stories,
    approx_height_ft: row.approx_height_ft == null ? null : row.approx_height_ft,
    attachment: row.attachment == null ? null : row.attachment,
    notes: row.notes == null ? null : row.notes,
    sort: row.sort == null ? index : row.sort,
  }));
  const facets = (src.facets || []).map((row, index) => ({
    ref: _ref(row, "ref", "id"),
    structure_ref: _ref(row, "structure_ref", "structure_id"),
    facet_label: row.facet_label || "",
    pitch_rise: row.pitch_rise == null ? null : row.pitch_rise,
    area_sqft: row.area_sqft == null ? 0 : row.area_sqft,
    width_ft: row.width_ft == null ? null : row.width_ft,
    length_ft: row.length_ft == null ? null : row.length_ft,
    position_offset_ft: row.position_offset_ft == null ? null : row.position_offset_ft,
    orientation_azimuth: row.orientation_azimuth == null ? null : row.orientation_azimuth,
    roof_material: row.roof_material == null ? null : row.roof_material,
    notes: row.notes == null ? null : row.notes,
    geometry: row.geometry == null ? null : _cloneJson(row.geometry),
    sort: row.sort == null ? index : row.sort,
  }));
  const edges = (src.edges || []).map((row, index) => ({
    ref: _ref(row, "ref", "id"),
    edge_type: row.edge_type || "eave",
    length_ft: row.length_ft == null ? 0 : row.length_ft,
    facet_ref: _ref(row, "facet_ref", "facet_id"),
    facet_ref_secondary: _ref(row, "facet_ref_secondary", "facet_id_secondary"),
    label: row.label == null ? null : row.label,
    notes: row.notes == null ? null : row.notes,
    sort: row.sort == null ? index : row.sort,
  }));
  const sourcePenetrations = src.penetrations != null ? src.penetrations : (src.pens || []);
  const penetrations = sourcePenetrations.map((row, index) => ({
    ref: _ref(row, "ref", "id"),
    pen_type: row.pen_type || "pipe_boot",
    quantity: row.quantity == null ? 1 : row.quantity,
    facet_ref: _ref(row, "facet_ref", "facet_id"),
    diameter_in: row.diameter_in == null ? null : row.diameter_in,
    width_in: row.width_in == null ? null : row.width_in,
    length_in: row.length_in == null ? null : row.length_in,
    notes: row.notes == null ? null : row.notes,
    sort: row.sort == null ? index : row.sort,
  }));
  const out = {
    structures,
    facets,
    edges,
    penetrations,
    summary: _cloneJson(src.summary || {}),
  };
  for (const key of ["source", "provider", "report_id", "reported_area_sqft", "notes"]) {
    if (Object.prototype.hasOwnProperty.call(src, key)) out[key] = _cloneJson(src[key]);
  }
  return out;
}'''
replace_once(RECONCILE, old_document, new_document)
replace_once(
    RECONCILE,
    '''    return { ok: true, baseBody: _cloneJson(pending.base_body), baseToken: String(pending.base_token) };''',
    '''    const normalizedBase = measurementDocumentFromRevision(pending.base_body);
    if (!normalizedBase) return { ok: false, reason: "missing_durable_base" };
    return { ok: true, baseBody: normalizedBase, baseToken: String(pending.base_token) };''',
)
replace_once(
    RECONCILE,
    '''    base: _cloneJson(mutation.base_body),
    field: _cloneJson(mutation.body || {}),
    office,''',
    '''    base: measurementDocumentFromRevision(mutation.base_body),
    field: measurementDocumentFromRevision(mutation.body || {}),
    office,''',
)
replace_once(
    RECONCILE,
    '''function buildMergedMeasurementBody(fieldBody, merged) {
  const next = _cloneJson(fieldBody || {}) || {};
  next.structures = _cloneJson(merged.structures || []);
  next.facets = _cloneJson(merged.facets || []);
  next.edges = _cloneJson(merged.edges || []);
  next.penetrations = _cloneJson(merged.pens != null ? merged.pens : (merged.penetrations || []));
  next.summary = _cloneJson(merged.summary || {});
  for (const key of ["provider", "report_id", "reported_area_sqft", "notes"]) {
    if (Object.prototype.hasOwnProperty.call(merged, key)) next[key] = _cloneJson(merged[key]);
  }
  return next;
}''',
    '''function buildMergedMeasurementBody(fieldBody, merged) {
  const next = _cloneJson(fieldBody || {}) || {};
  const normalized = measurementDocumentFromRevision(merged) || {
    structures: [], facets: [], edges: [], penetrations: [], summary: {},
  };
  next.structures = normalized.structures;
  next.facets = normalized.facets;
  next.edges = normalized.edges;
  next.penetrations = normalized.penetrations;
  next.summary = normalized.summary;
  for (const key of ["source", "provider", "report_id", "reported_area_sqft", "notes"]) {
    if (Object.prototype.hasOwnProperty.call(normalized, key)) next[key] = _cloneJson(normalized[key]);
  }
  return next;
}''',
)
replace_once(
    RECOVERY,
    '''for (const key of ["provider", "report_id", "reported_area_sqft", "notes"]) {''',
    '''for (const key of ["source", "provider", "report_id", "reported_area_sqft", "notes"]) {''',
)

# Install the workspace once, run the complete measurement contract, parse every changed mobile module,
# and prove Metro can produce a production Android bundle with the corrected shapes.
run("npm", "ci")
run("npm", "--prefix", "mobile", "run", "test:measurements")
run(
    "node", "-e",
    "const b=require('@babel/core'); for (const f of ['mobile/src/measurementReconcile.js','mobile/src/measurementRecovery.js','mobile/src/measurementConflict.js','mobile/src/storage.js','mobile/src/sync.js','mobile/src/screens/Measurements.js']) b.transformFileSync(f,{presets:['babel-preset-expo']}); console.log('Final P0 Babel parse passed');",
)
run(
    "npx", "expo", "export", "--platform", "android",
    "--output-dir", "/tmp/roofspan-p0-final-export", cwd=ROOT / "mobile",
)

# Remove any tracked path that Windows cannot create. Operate on Git's raw byte paths because the known
# corrupt filename is not safely representable through a normal Windows or UTF-8 text API.
def windows_unsafe(path_bytes: bytes) -> bool:
    if any(value < 0x20 or value == 0x7F for value in path_bytes):
        return True
    try:
        decoded = path_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return True
    reserved = set('<>:"|?*')
    for segment in decoded.split("/"):
        if any(char in reserved for char in segment) or segment.endswith((".", " ")):
            return True
    return False


raw_paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
unsafe = [value for value in raw_paths.split(b"\x00") if value and windows_unsafe(value)]
for raw_path in unsafe:
    print(f"Removing Windows-unsafe tracked path: {raw_path!r}", flush=True)
    subprocess.run([b"git", b"rm", b"-f", b"--", raw_path], cwd=os.fsencode(ROOT), check=True)
remaining = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
remaining_unsafe = [value for value in remaining.split(b"\x00") if value and windows_unsafe(value)]
if remaining_unsafe:
    raise RuntimeError(f"Windows-unsafe tracked paths remain: {remaining_unsafe!r}")

# Regenerate the stale Office lockfile, then prove the exact frozen install and production build used by CI.
run("npm", "install", "--global", "yarn@1.22.22")
run("yarn", "install", "--network-timeout", "600000", cwd=FRONTEND)
run("yarn", "install", "--frozen-lockfile", "--network-timeout", "600000", cwd=FRONTEND)
build_env = os.environ.copy()
build_env["CI"] = "false"
run("yarn", "build", cwd=FRONTEND, env=build_env)

# Remove only temporary implementation scripts. The temporary workflow is deleted afterward through the
# repository connector, which has the required workflow-file permission.
for temporary in ("tools/p0_apply.py", "tools/p0_apply_retry.py"):
    candidate = ROOT / temporary
    if candidate.exists():
        run("git", "rm", "-f", "--", temporary)
run("git", "diff", "--check")

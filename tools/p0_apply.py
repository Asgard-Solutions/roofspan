#!/usr/bin/env python3
"""Apply and verify P0-4: durable three-way-merge bases for Field measurements."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one replacement, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def run(*cmd: str, cwd: str | None = None) -> None:
    subprocess.run(cmd, cwd=ROOT / cwd if cwd else ROOT, check=True)


def run_expected_failure(*cmd: str) -> None:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    print(proc.stdout, flush=True)
    print(proc.stderr, flush=True)
    if proc.returncode == 0:
        raise RuntimeError("Regression test unexpectedly passed before the P0-4 production change")


# ---------------------------------------------------------------------------
# RED: after Save clears the transient working draft, the durable queue row
# must still carry the exact Base document/token needed for a safe 3-way merge.
# ---------------------------------------------------------------------------
write(
    "mobile/src/tests/measurement_durable_merge_base.node.test.js",
    '''"use strict";\nconst assert = require("assert");\nconst Q = require("../queue");\nconst M = require("../measurementReconcile");\nconst R = require("../measurementRecovery");\n\nfunction clone(v) { return JSON.parse(JSON.stringify(v)); }\nfunction detail() {\n  return {\n    id: "R1", updated_at: "2026-09-06T10:00:00Z", source: "office",\n    provider: "provider-a", report_id: "report-a", reported_area_sqft: 1000, notes: "base notes",\n    structures: [{ id: "S1", name: "House", structure_type: "main_house", included_in_scope: true }],\n    facets: [{ id: "F1", structure_id: "S1", facet_label: "F1", pitch_rise: 6, area_sqft: 100 }],\n    edges: [{ id: "E1", facet_id: "F1", edge_type: "ridge", length_ft: 40 }],\n    penetrations: [], summary: { total_area_sqft: 100 },\n  };\n}\n\n(function durable_row_survives_working_draft_clear_and_merges_disjoint_changes() {\n  const baseDetail = detail();\n  const baseBody = M.measurementDocumentFromRevision(baseDetail);\n  const fieldBody = { ...clone(baseBody), lead_id: "L1", source: "field", mark_field_complete: false };\n  fieldBody.edges[0].length_ft = 45;\n  const mutation = Q.makeMutation({\n    kind: "measurement_update", method: "put", path: "/mobile/measurements/R1",\n    body: fieldBody, ifMatch: baseDetail.updated_at, baseBody, baseToken: baseDetail.updated_at,\n  });\n  assert.deepStrictEqual(mutation.base_body, baseBody);\n  assert.strictEqual(mutation.base_token, baseDetail.updated_at);\n\n  const office = clone(baseDetail);\n  office.updated_at = "2026-09-06T10:05:00Z";\n  office.facets[0].area_sqft = 110;\n  office.notes = "Office-only note";\n  const inputs = M.measurementConflictMergeInputs({ ...mutation, state: "conflict" }, office);\n  assert.strictEqual(inputs.ok, true);\n  const merged = R.threeWayMergeMeasurement(inputs.base, inputs.field, inputs.office);\n  assert.strictEqual(merged.clean, true);\n  const next = M.buildMergedMeasurementBody(mutation.body, merged.merged);\n  assert.strictEqual(next.facets[0].area_sqft, 110, "Office-only plane change must survive");\n  assert.strictEqual(next.edges[0].length_ft, 45, "Field-only roof-line change must survive");\n  assert.strictEqual(next.notes, "Office-only note", "Office-only hidden metadata must survive");\n  assert.strictEqual(next.lead_id, "L1", "routing scope remains from the Field mutation");\n})();\n\n(function repeated_local_save_keeps_the_original_pending_base() {\n  const base = detail();\n  const original = M.measurementDocumentFromRevision(base);\n  const pending = Q.makeMutation({\n    kind: "measurement_update", method: "put", path: "/mobile/measurements/R1", body: original,\n    ifMatch: base.updated_at, baseBody: original, baseToken: base.updated_at,\n  });\n  const optimistic = clone(base);\n  optimistic.updated_at = base.updated_at;\n  optimistic.facets[0].area_sqft = 999;\n  const chosen = M.chooseDurableMeasurementBase(optimistic, pending);\n  assert.strictEqual(chosen.ok, true);\n  assert.deepStrictEqual(chosen.baseBody, original);\n  assert.strictEqual(chosen.baseToken, base.updated_at);\n})();\n\n(function legacy_or_mismatched_rows_cannot_blindly_keep_mine() {\n  const base = detail();\n  const body = M.measurementDocumentFromRevision(base);\n  const legacy = Q.makeMutation({\n    kind: "measurement_update", method: "put", path: "/mobile/measurements/R1",\n    body, ifMatch: base.updated_at,\n  });\n  assert.strictEqual(M.measurementConflictMergeInputs({ ...legacy, state: "conflict" }, base).ok, false);\n  assert.strictEqual(M.chooseDurableMeasurementBase(base, legacy).ok, false);\n\n  const mismatch = { ...legacy, base_body: body, base_token: "older-token" };\n  const result = M.measurementConflictMergeInputs(mismatch, base);\n  assert.strictEqual(result.ok, false);\n  assert.strictEqual(result.reason, "base_token_mismatch");\n})();\n\n(function superseded_create_conversion_uses_the_acknowledged_server_as_its_new_base() {\n  const server = detail();\n  server.updated_at = "2026-09-06T10:10:00Z";\n  const newerCreate = Q.makeMutation({ kind: "measurement", method: "post", path: "/mobile/measurements", body: { lead_id: "L1", structures: [] } });\n  const converted = M.buildConvertedUpdateMutation(newerCreate, "R1", server.updated_at, server);\n  assert.strictEqual(converted.kind, "measurement_update");\n  assert.strictEqual(converted.base_token, server.updated_at);\n  assert.deepStrictEqual(converted.base_body, M.measurementDocumentFromRevision(server));\n  assert.deepStrictEqual(converted.body, newerCreate.body);\n})();\n\nconsole.log("measurement durable merge-base tests passed");\n''',
)
replace_once(
    "mobile/package.json",
    "node src/tests/measurement_three_way_merge.node.test.js && node src/tests/sync_status.node.test.js",
    "node src/tests/measurement_three_way_merge.node.test.js && node src/tests/measurement_durable_merge_base.node.test.js && node src/tests/sync_status.node.test.js",
)
run_expected_failure("node", "mobile/src/tests/measurement_durable_merge_base.node.test.js")

# ---------------------------------------------------------------------------
# GREEN: persist a complete Base in every measurement_update, preserve it when
# local edits coalesce, and consume only a trusted durable Base on conflict.
# ---------------------------------------------------------------------------
replace_once(
    "mobile/src/queue.js",
    '''function makeMutation({ kind, method, path, body, ifMatch = null, label = "", scope = null, photo = null, clientId = null, mutationGeneration = 1, localEditGeneration = null }) {''',
    '''function makeMutation({ kind, method, path, body, ifMatch = null, baseBody = null, baseToken = null, label = "", scope = null, photo = null, clientId = null, mutationGeneration = 1, localEditGeneration = null }) {''',
)
replace_once(
    "mobile/src/queue.js",
    '''    body: body || {},\n    ifMatch,\n    label,''',
    '''    body: body || {},\n    ifMatch,\n    // Durable 3-way-merge lineage for full-document measurement PUTs. This survives Save clearing the\n    // transient working draft and is never sent to the backend.\n    base_body: baseBody == null ? null : JSON.parse(JSON.stringify(baseBody)),\n    base_token: baseToken == null ? null : String(baseToken),\n    label,''',
)

helpers = '''\n// Extract the complete editable measurement document from an authoritative revision detail. Routing and\n// command fields stay on the mutation body; these are the values that must participate in conflict merge.\nfunction _cloneJson(value) { return value == null ? value : JSON.parse(JSON.stringify(value)); }\nfunction measurementDocumentFromRevision(src) {\n  if (!src || typeof src !== "object") return null;\n  const out = {\n    structures: _cloneJson(src.structures || []),\n    facets: _cloneJson(src.facets || []),\n    edges: _cloneJson(src.edges || []),\n    penetrations: _cloneJson(src.penetrations != null ? src.penetrations : (src.pens || [])),\n    summary: _cloneJson(src.summary || {}),\n  };\n  for (const key of ["provider", "report_id", "reported_area_sqft", "notes"]) {\n    if (Object.prototype.hasOwnProperty.call(src, key)) out[key] = _cloneJson(src[key]);\n  }\n  return out;\n}\n\n// Coalescing rule: once a measurement_update is pending, every later local edit retains that row's ORIGINAL\n// base. Falling back to the current optimistic cache would manufacture a false base and permit data loss.\nfunction chooseDurableMeasurementBase(authoritative, pending) {\n  if (pending && pending.kind === "measurement_update") {\n    if (!pending.base_body || pending.base_token == null || pending.base_token === "") {\n      return { ok: false, reason: "missing_durable_base" };\n    }\n    return { ok: true, baseBody: _cloneJson(pending.base_body), baseToken: String(pending.base_token) };\n  }\n  const token = authoritative && (authoritative.base_token || authoritative.updated_at || authoritative.if_match);\n  const body = authoritative && authoritative.base_body\n    ? _cloneJson(authoritative.base_body)\n    : measurementDocumentFromRevision(authoritative);\n  if (!body || token == null || token === "") return { ok: false, reason: "missing_authoritative_base" };\n  return { ok: true, baseBody: body, baseToken: String(token) };\n}\n\n// A Keep-Mine merge is legal only when the durable base token is exactly the token used by the failed PUT.\n// Legacy rows are preserved for explicit review rather than blindly re-sending an entire stale snapshot.\nfunction measurementConflictMergeInputs(mutation, serverDetail) {\n  if (!mutation || mutation.kind !== "measurement_update") return { ok: false, reason: "not_measurement_update" };\n  if (!mutation.base_body || mutation.base_token == null || mutation.base_token === "") {\n    return { ok: false, reason: "missing_durable_base" };\n  }\n  if (String(mutation.base_token) !== String(mutation.ifMatch || "")) {\n    return { ok: false, reason: "base_token_mismatch" };\n  }\n  const office = measurementDocumentFromRevision(serverDetail);\n  if (!office || !serverDetail || serverDetail.updated_at == null) {\n    return { ok: false, reason: "missing_office_detail" };\n  }\n  return {\n    ok: true,\n    base: _cloneJson(mutation.base_body),\n    field: _cloneJson(mutation.body || {}),\n    office,\n    officeToken: String(serverDetail.updated_at),\n  };\n}\n\nfunction buildMergedMeasurementBody(fieldBody, merged) {\n  const next = _cloneJson(fieldBody || {}) || {};\n  next.structures = _cloneJson(merged.structures || []);\n  next.facets = _cloneJson(merged.facets || []);\n  next.edges = _cloneJson(merged.edges || []);\n  next.penetrations = _cloneJson(merged.pens != null ? merged.pens : (merged.penetrations || []));\n  next.summary = _cloneJson(merged.summary || {});\n  for (const key of ["provider", "report_id", "reported_area_sqft", "notes"]) {\n    if (Object.prototype.hasOwnProperty.call(merged, key)) next[key] = _cloneJson(merged[key]);\n  }\n  return next;\n}\n'''
replace_once(
    "mobile/src/measurementReconcile.js",
    '''function measScopeFromBody(body) {\n  if (!body) return null;\n  if (body.lead_id) return { lead_id: body.lead_id };\n  if (body.property_id) return { property_id: body.property_id };\n  if (body.inspection_id) return { inspection_id: body.inspection_id };\n  return null;\n}\n\n// A newer local edit''',
    '''function measScopeFromBody(body) {\n  if (!body) return null;\n  if (body.lead_id) return { lead_id: body.lead_id };\n  if (body.property_id) return { property_id: body.property_id };\n  if (body.inspection_id) return { inspection_id: body.inspection_id };\n  return null;\n}\n''' + helpers + '''\n// A newer local edit''',
)
replace_once(
    "mobile/src/measurementReconcile.js",
    '''function buildConvertedUpdateMutation(m, revisionId, ifMatch) {\n  const cid = `measurement-update:${String(revisionId)}`;''',
    '''function buildConvertedUpdateMutation(m, revisionId, ifMatch, serverBase) {\n  const cid = `measurement-update:${String(revisionId)}`;\n  const authoritativeBase = measurementDocumentFromRevision(serverBase);''',
)
replace_once(
    "mobile/src/measurementReconcile.js",
    '''    path: `/mobile/measurements/${String(revisionId)}`,\n    ifMatch,\n    server_id:''',
    '''    path: `/mobile/measurements/${String(revisionId)}`,\n    ifMatch,\n    base_body: authoritativeBase,\n    base_token: ifMatch == null ? null : String(ifMatch),\n    server_id:''',
)
replace_once(
    "mobile/src/measurementReconcile.js",
    '''  measScopeFromBody,\n  isSupersededAck,''',
    '''  measScopeFromBody,\n  measurementDocumentFromRevision,\n  chooseDurableMeasurementBase,\n  measurementConflictMergeInputs,\n  buildMergedMeasurementBody,\n  isSupersededAck,''',
)

replace_once(
    "mobile/src/measurementRecovery.js",
    '''  merged.summary = ms;\n  return { merged, conflicts, clean: conflicts.length === 0 };''',
    '''  merged.summary = ms;\n  // Hidden/import metadata is part of the backend's full-document replacement contract too. Merge it\n  // independently so a Field roof-line edit cannot revert an Office-only provider/report/note change.\n  for (const key of ["provider", "report_id", "reported_area_sqft", "notes"]) {\n    const has = (obj) => Object.prototype.hasOwnProperty.call(obj, key);\n    if (!has(base) && !has(field) && !has(office)) continue;\n    const bv = JSON.stringify(base[key]), fv = JSON.stringify(field[key]), ov = JSON.stringify(office[key]);\n    const fCh = bv !== fv, oCh = bv !== ov;\n    if (fCh && oCh && fv !== ov) { conflicts.push(key); merged[key] = field[key]; }\n    else if (fCh) merged[key] = field[key];\n    else merged[key] = has(office) ? office[key] : base[key];\n  }\n  return { merged, conflicts, clean: conflicts.length === 0 };''',
)

replace_once(
    "mobile/src/storage.js",
    '''import { buildConvertedUpdateMutation } from "./measurementReconcile";''',
    '''import { buildConvertedUpdateMutation, measurementDocumentFromRevision } from "./measurementReconcile";''',
)
replace_once(
    "mobile/src/storage.js",
    '''export async function convertSupersededCreateToUpdate(oldClientId, newRevisionId, newIfMatch) {''',
    '''export async function convertSupersededCreateToUpdate(oldClientId, newRevisionId, newIfMatch, serverBase) {''',
)
replace_once(
    "mobile/src/storage.js",
    '''    const converted = buildConvertedUpdateMutation(m, newRevisionId, newIfMatch);''',
    '''    const converted = buildConvertedUpdateMutation(m, newRevisionId, newIfMatch, serverBase);''',
)
replace_once(
    "mobile/src/storage.js",
    '''export async function rebasePendingMeasurementIfMatch(client_id, newIfMatch) {''',
    '''export async function rebasePendingMeasurementIfMatch(client_id, newIfMatch, serverBase) {''',
)
replace_once(
    "mobile/src/storage.js",
    '''    if (String(m.ifMatch || "") === String(newIfMatch || "")) return { updated: false, reason: "already_rebased" };\n    m.ifMatch = newIfMatch;\n    await d.runAsync(''',
    '''    const base = measurementDocumentFromRevision(serverBase);\n    if (!base || newIfMatch == null || newIfMatch === "") return { updated: false, reason: "missing_authoritative_base" };\n    m.ifMatch = newIfMatch;\n    m.base_body = base;\n    m.base_token = String(newIfMatch);\n    await d.runAsync(''',
)

replace_once(
    "mobile/src/sync.js",
    '''import { upsertRevision, retireCreateDraft, planMeasurementWorkingAck, measScopeFromBody, isSupersededAck, rebaseWorkingDraftToRevision } from "./measurementReconcile";''',
    '''import { upsertRevision, retireCreateDraft, planMeasurementWorkingAck, measScopeFromBody, isSupersededAck, rebaseWorkingDraftToRevision, measurementDocumentFromRevision } from "./measurementReconcile";''',
)
replace_once(
    "mobile/src/sync.js",
    '''await rebasePendingMeasurementIfMatch(m.client_id, rev.updated_at);''',
    '''await rebasePendingMeasurementIfMatch(m.client_id, rev.updated_at, rev);''',
)
replace_once(
    "mobile/src/sync.js",
    '''await convertSupersededCreateToUpdate(m.client_id, revisionId, rev.updated_at);''',
    '''await convertSupersededCreateToUpdate(m.client_id, revisionId, rev.updated_at, rev);''',
)
replace_once(
    "mobile/src/sync.js",
    '''export async function rebaseMeasurementUpdate(revisionId, newIfMatch, mergedBody) {\n  const id = `measurement-update:${String(revisionId)}`;\n  const all = await loadAllMutations();\n  const m = all.find((x) => x.client_id === id);\n  if (!m) return { action: "noop" };\n  const body = mergedBody ? { ...m.body, ...mergedBody } : m.body;\n  await saveMutation({ ...m, body, ifMatch: newIfMatch, state: "pending", error: null });\n  _emit({ type: "queued" });\n  runSync().catch(() => {});\n  return { action: "keep_local" };\n}''',
    '''export async function rebaseMeasurementUpdate(revisionId, newIfMatch, mergedBody, newBaseDetail) {\n  const id = `measurement-update:${String(revisionId)}`;\n  const all = await loadAllMutations();\n  const m = all.find((x) => x.client_id === id);\n  if (!m) return { action: "noop" };\n  const base = measurementDocumentFromRevision(newBaseDetail);\n  if (!mergedBody || !base || newIfMatch == null || newIfMatch === "") {\n    return { action: "review_required", reason: "missing_or_untrusted_base" };\n  }\n  await saveMutation({\n    ...m, body: mergedBody, ifMatch: newIfMatch,\n    base_body: base, base_token: String(newIfMatch),\n    state: "pending", error: null, errorCode: null, serverValue: null,\n  });\n  _emit({ type: "queued" });\n  runSync().catch(() => {});\n  return { action: "keep_local" };\n}''',
)

replace_once(
    "mobile/src/screens/Measurements.js",
    '''import { resolveMeasurementView, measurementSyncState } from "../measurementReconcile";''',
    '''import { resolveMeasurementView, measurementSyncState, measurementDocumentFromRevision, chooseDurableMeasurementBase, measurementConflictMergeInputs, buildMergedMeasurementBody } from "../measurementReconcile";''',
)
replace_once(
    "mobile/src/screens/Measurements.js",
    '''        provider: full.provider ?? null, report_id: full.report_id ?? null,\n        reported_area_sqft: full.reported_area_sqft ?? null, notes: full.notes ?? null,\n      });''',
    '''        provider: full.provider ?? null, report_id: full.report_id ?? null,\n        reported_area_sqft: full.reported_area_sqft ?? null, notes: full.notes ?? null,\n        base_body: measurementDocumentFromRevision(full), base_token: full.updated_at,\n      });''',
)
replace_once(
    "mobile/src/screens/Measurements.js",
    '''    if (existing) {\n      const optimistic = {''',
    '''    if (existing) {\n      const pending = await currentMeasurementMutation(existing.id);\n      const base = chooseDurableMeasurementBase(existing, pending && pending.state !== "synced" ? pending : null);\n      if (!base.ok) {\n        Alert.alert("Cannot safely save", "This older local edit has no trustworthy Office base. Use the Office version, reopen it, and reapply the change.");\n        return;\n      }\n      const writeToken = pending && pending.state !== "synced" && pending.ifMatch\n        ? pending.ifMatch\n        : (existing.if_match || base.baseToken);\n      const optimistic = {''',
)
replace_once(
    "mobile/src/screens/Measurements.js",
    '''        body, ifMatch: existing.if_match, label: "Roof measurement",\n      });''',
    '''        body, ifMatch: writeToken, baseBody: base.baseBody, baseToken: base.baseToken,\n        label: "Roof measurement",\n      });''',
)
replace_once(
    "mobile/src/screens/Measurements.js",
    '''  const onKeepMine = useCallback(async () => {\n    if (!conflict || !conflict.serverDetail) return;\n    // Three-way merge (base vs Field vs Office): apply Field-only changes, preserve Office-only changes.\n    // If a group changed on BOTH sides, keep the conflict for explicit review — never silently overwrite.\n    let mergedBody = null;\n    try {\n      const wd = await loadMeasurementWorkingDraft(scope);\n      if (wd && wd.base_body) {\n        const field = { structures: wd.structures, facets: wd.facets, edges: wd.edges, pens: wd.pens, summary: wd.summary };\n        const r = threeWayMergeMeasurement(wd.base_body, field, conflict.serverDetail);\n        if (!r.clean) { setConflict({ ...conflict, mergeConflicts: r.conflicts }); return; }\n        mergedBody = { structures: r.merged.structures, facets: r.merged.facets, edges: r.merged.edges, penetrations: r.merged.pens, summary: r.merged.summary };\n      }\n    } catch (e) { mergedBody = null; }\n    await rebaseMeasurementUpdate(conflict.revisionId, conflict.serverDetail.updated_at, mergedBody);\n    setConflict(null);\n    await load();\n  }, [conflict, scope, load]);''',
    '''  const onKeepMine = useCallback(async () => {\n    if (!conflict || !conflict.serverDetail) return;\n    // The transient working draft is intentionally cleared by Save. The durable mutation is therefore the\n    // only legal Base/Field lineage for conflict resolution. Legacy rows without it stay in review.\n    const mutation = await currentMeasurementMutation(conflict.revisionId);\n    const inputs = measurementConflictMergeInputs(mutation, conflict.serverDetail);\n    if (!inputs.ok) {\n      setConflict({ ...conflict, mergeUnavailable: inputs.reason });\n      Alert.alert("Review required", "This older saved change does not contain a trustworthy merge base. Use the Office version, then reapply your change.");\n      return;\n    }\n    const r = threeWayMergeMeasurement(inputs.base, inputs.field, inputs.office);\n    if (!r.clean) { setConflict({ ...conflict, mergeConflicts: r.conflicts }); return; }\n    const mergedBody = buildMergedMeasurementBody(mutation.body, r.merged);\n    const decision = await rebaseMeasurementUpdate(\n      conflict.revisionId, conflict.serverDetail.updated_at, mergedBody, conflict.serverDetail\n    );\n    if (decision.action !== "keep_local") {\n      setConflict({ ...conflict, mergeUnavailable: decision.reason || "review_required" });\n      return;\n    }\n    setConflict(null);\n    await load();\n  }, [conflict, load]);''',
)

replace_once(
    "mobile/src/screens/RoofSketch.js",
    '''import * as RECON from "../roofProposalReconcile";''',
    '''import * as RECON from "../roofProposalReconcile";\nimport { chooseDurableMeasurementBase } from "../measurementReconcile";''',
)
replace_once(
    "mobile/src/screens/RoofSketch.js",
    '''    const res = await cache.measurement(revision_id);\n    const current = res && res.data ? res.data : measDetail;\n    const upd = RECON.buildAcceptedMeasurementUpdate(current, { targetType: row.target_type, relationalId: row.relational_id, metric: row.metric, proposedValue: row.proposed });\n    if (upd.changed) {\n      await cacheMeasurementDetail(upd.nextDetail);\n      await queueMutation({ kind: "measurement_update", method: "put", path: `/mobile/measurements/${revision_id}`, body: upd.body, ifMatch: upd.ifMatch, label: "Roof measurement" });\n    }''',
    '''    const res = await cache.measurement(revision_id);\n    const authoritative = res && res.data ? res.data : measDetail;\n    const pending = await currentMeasurementMutation(revision_id);\n    const current = pending && pending.state !== "synced" && pending.body\n      ? { ...authoritative, ...pending.body, id: revision_id, updated_at: pending.ifMatch }\n      : authoritative;\n    const base = chooseDurableMeasurementBase(authoritative, pending && pending.state !== "synced" ? pending : null);\n    if (!base.ok) {\n      Alert.alert("Review required", "This older local measurement change has no trustworthy Office base. Resolve it before accepting another proposed value.");\n      return;\n    }\n    const upd = RECON.buildAcceptedMeasurementUpdate(current, { targetType: row.target_type, relationalId: row.relational_id, metric: row.metric, proposedValue: row.proposed });\n    if (upd.changed) {\n      await cacheMeasurementDetail(upd.nextDetail);\n      await queueMutation({\n        kind: "measurement_update", method: "put", path: `/mobile/measurements/${revision_id}`,\n        body: upd.body, ifMatch: pending && pending.state !== "synced" ? pending.ifMatch : upd.ifMatch,\n        baseBody: base.baseBody, baseToken: base.baseToken, label: "Roof measurement",\n      });\n    }''',
)

run("npm", "--prefix", "mobile", "run", "test:measurements")
run("node", "mobile/src/tests/roof_proposal_reconcile.node.test.js")
run(
    "node", "-e",
    "const b=require('@babel/core'); for (const f of ['mobile/src/screens/Measurements.js','mobile/src/screens/RoofSketch.js','mobile/src/sync.js','mobile/src/storage.js']) b.transformFileSync(f,{presets:['babel-preset-expo']}); console.log('P0-4 Babel parse passed');",
)
run(
    "npx", "expo", "export", "--platform", "android", "--output-dir", "/tmp/roofspan-p0-4-export",
    cwd="mobile",
)

Path("/tmp/p0_commit_message").write_text(
    "fix: persist measurement conflict merge base\n",
    encoding="utf-8",
)

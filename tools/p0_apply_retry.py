#!/usr/bin/env python3
"""Run the P0-5 implementation with canonical measurement-list replacement semantics."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
source = (root / "tools/p0_apply.py").read_text(encoding="utf-8")
replacements = [
    (
        '    assert.deepStrictEqual(list.find((x) => x.id === "R1"), officeDetail());',
        '    const listItem = list.find((x) => x.id === "R1");\n'
        '    assert.strictEqual(listItem.total_area_sqft, 1800);\n'
        '    assert.strictEqual(listItem.total_squares, 18);\n'
        '    assert.strictEqual(listItem.notes, undefined, "list cache is a canonical list item, not stale merged detail");',
    ),
    (
        'const { measScopeFromBody, upsertRevision } = require("./measurementReconcile");',
        'const { measScopeFromBody } = require("./measurementReconcile");',
    ),
    (
        'function buildMeasurementUseOfficeReview(mutation, scope, serverDetail) {',
        '''function measurementListItemFromDetail(detail) {
  const totals = detail && detail.totals && typeof detail.totals === "object" ? detail.totals : {};
  const rawArea = Number(totals.total_area_sqft);
  const area = Number.isFinite(rawArea) ? rawArea : 0;
  const rawSquares = Number(totals.total_squares);
  return {
    id: String(detail.id), set_id: detail.set_id == null ? null : String(detail.set_id),
    revision_number: detail.revision_number, status: detail.status, source: detail.source,
    is_immutable: !!detail.is_immutable, total_area_sqft: area,
    total_squares: Number.isFinite(rawSquares) ? rawSquares : Math.round((area / 100) * 100) / 100,
    created_by: detail.created_by == null ? null : detail.created_by,
    created_at: detail.created_at == null ? null : detail.created_at,
    verified_at: detail.verified_at == null ? null : detail.verified_at,
    supersedes_revision_id: detail.supersedes_revision_id == null ? null : String(detail.supersedes_revision_id),
  };
}
function replaceRevisionInList(list, detail) {
  const rows = Array.isArray(list) ? list.filter(Boolean) : [];
  const item = measurementListItemFromDetail(detail);
  let found = false;
  const next = rows.map((row) => {
    if (row && String(row.id) === item.id) { found = true; return item; }
    return row;
  });
  if (!found) next.push(item);
  return next;
}
function buildMeasurementUseOfficeReview(mutation, scope, serverDetail) {''',
    ),
    (
        '  await tx.writeCache(reviewed.listKey, upsertRevision(currentList, reviewed.serverDetail));',
        '  await tx.writeCache(reviewed.listKey, replaceRevisionInList(currentList, reviewed.serverDetail));',
    ),
    (
        '  isFullOfficeRevision,\n  buildMeasurementUseOfficeReview,',
        '  isFullOfficeRevision,\n  measurementListItemFromDetail,\n  replaceRevisionInList,\n  buildMeasurementUseOfficeReview,',
    ),
]
for old, new in replacements:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"P0-5 retry replacement expected once, found {count}: {old[:100]!r}")
    source = source.replace(old, new, 1)

retry = root / "tools/.p0_apply_retry_exec.py"
retry.write_text(source, encoding="utf-8")
try:
    subprocess.run(["python", str(retry)], cwd=root, check=True)
finally:
    retry.unlink(missing_ok=True)

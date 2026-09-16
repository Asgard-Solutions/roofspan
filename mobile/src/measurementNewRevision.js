"use strict";
const { detailKey, scopeKey, workingKey } = require('./measurementCache');
const { workingDraftHasContent } = require('./measurementDraftPriority');
const { upsertRevision } = require('./measurementReconcile');
const requestKey = revisionId => `measurement-new-revision:${revisionId}`;

// Persist an operation key before the POST. If Office committed but its response was lost, retrying
// (even after restarting Field) asks for the same clone instead of creating another revision.
async function createFieldRevision({ revisionId, scope, request, getCache, mutateCache, putCache }) {
  if (!revisionId) throw new Error('measurement_revision_required');
  const listKey = scopeKey(scope);
  // Field has one working-draft slot per scope. Resolve its contents before adopting another revision.
  const working = await getCache(workingKey(scope));
  if (working?.working && workingDraftHasContent(working)) {
    const error = new Error('Save or resolve your unsaved measurements on the Roof measurements page before creating a new revision.');
    error.code = 'unsaved_measurements';
    throw error;
  }
  const operation = await mutateCache(requestKey(revisionId), prior => prior || {
    idempotency_key: `new-revision-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`,
  });
  const response = await request({ method: 'POST', url: `/mobile/measurements/${revisionId}/new-revision`,
    headers: { 'Idempotency-Key': operation.idempotency_key } });
  const revision = response?.data;
  if (!revision?.id || revision.id === revisionId || !revision.editable || !Array.isArray(revision.structures)) {
    throw new Error('The new editable revision could not be loaded. Try again.');
  }
  await putCache(detailKey(revision.id), revision);
  await mutateCache(listKey, rows => upsertRevision(rows || [], revision));
  return revision;
}

// Clear the operation only after the caller has adopted/navigated to the acknowledged revision.
async function finishFieldRevision(revisionId, putCache) { await putCache(requestKey(revisionId), null); }
module.exports = { createFieldRevision, finishFieldRevision };

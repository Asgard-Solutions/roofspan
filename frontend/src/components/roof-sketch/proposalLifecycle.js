// Proposal acceptance lifecycle + editor-session rollback bookkeeping (pure, Node-testable).
//
// CORE RULE: clicking "Accept Proposed" NEVER makes a decision "accepted". It (A) updates the
// Worksheet DRAFT via the parent, and (B) records the sketch decision as "pending_accept". A decision
// becomes "accepted" ONLY after the authoritative Measurement Worksheet PUT succeeds AND the persisted
// relational value actually matches the proposed value. The Worksheet is the single measurement-save
// authority; the editor never PUTs relational facts itself.

export const PENDING = "pending_accept";
export const ACCEPTED = "accepted";
export const KEEP = "keep_current";

const TOL = { area_sqft: 0.5, length_ft: 0.05, pitch_rise: 0.01 };
export function valuesMatch(metric, a, b) {
  if (a == null || b == null) return false;
  const tol = TOL[metric] ?? 0.01;
  return Math.abs(Number(a) - Number(b)) <= tol;
}

const key = (t, id, m) => `${t}::${id}::${m}`;

// ---- editor session change tracking (for safe Discard rollback) ----
// Records, per (target,metric), the ORIGINAL worksheet value before the editor first touched it and
// the most recent value the editor applied. Enables Discard to restore original ONLY when the field is
// still exactly what the editor last set (i.e. the user did not manually edit it afterward).
export function makeSession() {
  return { changes: {} };
}

export function recordEditorChange(session, { target_type, target_id, metric, originalValue, appliedValue }) {
  const k = key(target_type, target_id, metric);
  const existing = session.changes[k];
  const changes = {
    ...session.changes,
    [k]: {
      target_type, target_id, metric,
      original_value: existing ? existing.original_value : originalValue, // keep the FIRST original
      editor_applied_value: appliedValue,
    },
  };
  return { ...session, changes };
}

// Returns [{ target_type, target_id, metric, restore_value }] for fields whose current worksheet value
// still equals what the editor last applied. Fields the user manually changed afterward are left alone.
export function rollbackPlan(session, currentValueOf) {
  const plan = [];
  for (const k of Object.keys(session.changes)) {
    const c = session.changes[k];
    const cur = currentValueOf(c.target_type, c.target_id, c.metric);
    if (valuesMatch(c.metric, cur, c.editor_applied_value)) {
      plan.push({ target_type: c.target_type, target_id: c.target_id, metric: c.metric, restore_value: c.original_value });
    }
  }
  return plan;
}

// ---- decisions on the canonical sketch document ----
function upsertDecision(decisions, dec) {
  const others = (decisions || []).filter(
    (x) => !(x.target_type === dec.target_type && x.target_id === dec.target_id && x.metric === dec.metric),
  );
  return [...others, dec];
}

export function decisionFor(decisions, target_type, target_id, metric) {
  return (decisions || []).find((x) => x.target_type === target_type && x.target_id === target_id && x.metric === metric) || null;
}

// ACCEPT: returns the next proposal_decisions array (status pending_accept) + the worksheet draft change
// to apply through the parent. `relationalTargetId` MUST be the mapped Measurement UUID (accept is only
// allowed when mapped). `currentValue` is the worksheet value before this accept (for session original).
export function acceptProposed({ decisions, session }, { target_type, relationalTargetId, metric, proposedValue, currentValue }) {
  const dec = {
    target_type, target_id: relationalTargetId, metric,
    proposed_value: proposedValue, value: proposedValue, decision: PENDING, at: new Date().toISOString(),
  };
  const nextSession = recordEditorChange(session, {
    target_type, target_id: relationalTargetId, metric, originalValue: currentValue, appliedValue: proposedValue,
  });
  return {
    decisions: upsertDecision(decisions, dec),
    session: nextSession,
    draftChange: { target_type, target_id: relationalTargetId, metric, value: proposedValue },
  };
}

// KEEP CURRENT: records the decision, changes NO measurement value. `targetId` may be a relational id
// (when mapped) or the sketch id (when unmapped) — keep_current is purely local provenance.
export function keepCurrent({ decisions }, { target_type, targetId, metric }) {
  const dec = { target_type, target_id: targetId, metric, decision: KEEP, at: new Date().toISOString() };
  return { decisions: upsertDecision(decisions, dec), draftChange: null };
}

// APPLY a persisted pending decision to the worksheet draft on reopen. Stays pending_accept; records the
// change into the session so Discard can safely undo it.
export function applyPendingToDraft({ session }, dec, currentValue) {
  const nextSession = recordEditorChange(session, {
    target_type: dec.target_type, target_id: dec.target_id, metric: dec.metric,
    originalValue: currentValue, appliedValue: dec.proposed_value ?? dec.value,
  });
  return {
    session: nextSession,
    draftChange: { target_type: dec.target_type, target_id: dec.target_id, metric: dec.metric, value: dec.proposed_value ?? dec.value },
  };
}

// FINALIZE after a successful authoritative Worksheet save. Promotes pending_accept -> accepted ONLY
// where the persisted authoritative value matches the proposed value. `savedValueOf(type,id,metric)`
// reads the just-persisted MeasurementRevision. Returns { decisions, promoted:[keys], changed }.
export function finalizeAfterSave(decisions, savedValueOf) {
  let changed = false;
  const promoted = [];
  const next = (decisions || []).map((d) => {
    if (d.decision !== PENDING) return d;
    const saved = savedValueOf(d.target_type, d.target_id, d.metric);
    if (valuesMatch(d.metric, saved, d.proposed_value ?? d.value)) {
      changed = true;
      promoted.push(key(d.target_type, d.target_id, d.metric));
      return { ...d, decision: ACCEPTED, accepted_value: saved, finalized_at: new Date().toISOString() };
    }
    return d; // mismatch -> stays pending (do not guess)
  });
  return { decisions: next, promoted, changed };
}

// A sketch mapping is invalid if it references a relational id that no longer exists in the current
// scoped set. Invalid mappings block acceptance and must be shown as unmapped (never silently remapped).
export function isMappingValid(relationalId, validIdSet) {
  return relationalId != null && validIdSet.has(String(relationalId));
}

// A persisted pending decision may only be applied to the Worksheet draft if its relational target still
// exists in the current scoped set. A stale/invalid target must NEVER be silently redirected or applied.
export function canApplyPending(dec, validIdSet) {
  return !!dec && dec.decision === PENDING && isMappingValid(dec.target_id, validIdSet);
}

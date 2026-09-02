"use strict";
// Decides whether a persisted Field "working draft" holds genuine in-progress edits. Only a draft WITH
// content may shadow the authoritative Office measurement; an empty/orphaned draft must be dropped so the
// Field shows exactly what Office has (fixes "Saved on device" showing nothing while Office has data).
function workingDraftHasContent(wd) {
  if (!wd) return false;
  const s = wd.structures || [], f = wd.facets || [], e = wd.edges || [], p = wd.pens || [];
  if (s.length > 0 || f.length > 0 || e.length > 0) return true;
  if (p.some((x) => (parseInt(x.quantity, 10) || 0) > 0)) return true;
  const summ = wd.summary || {};
  return Object.keys(summ).some((k) => {
    const v = summ[k];
    return v !== null && v !== "" && v !== false && v !== undefined && typeof v !== "object";
  });
}

module.exports = { workingDraftHasContent };

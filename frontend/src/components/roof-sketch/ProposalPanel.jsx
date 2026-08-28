import { compareProposal } from "@roofspan/roof-sketch-core";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { fById, eById } from "./commands";
import { decisionFor, PENDING, ACCEPTED, KEEP } from "./proposalLifecycle";

const fmt = (n, unit) => (n == null ? "—" : `${Number(n).toFixed(unit === "SF" ? 0 : 1)} ${unit}`);
const STATUS = {
  [PENDING]: ["Pending accept", "bg-amber-100 text-amber-800"],
  [ACCEPTED]: ["Accepted", "bg-emerald-100 text-emerald-800"],
  [KEEP]: ["Kept current", "bg-slate-200 text-slate-700"],
};

// Geometry proposals vs confirmed relational facts. Acceptance is ALWAYS explicit, requires an explicit
// relational mapping, and only ever creates a pending_accept decision (never "accepted" directly).
export default function ProposalPanel({ doc, proposals, relFacetsById, relEdgesById = {}, onAccept, onKeep, readOnly }) {
  const dimensional = proposals.filter((p) => p.decision === "proposal");
  const discrepancies = proposals.filter((p) => p.decision === "discrepancy");
  const notice = proposals.find((p) => p.code === "scale_unresolved");

  if (notice) {
    return <div className="p-3 text-sm text-slate-500" data-testid="proposal-panel-unscaled">
      <b>Unscaled sketch.</b> Calibrate a known edge length to generate LF/SF proposals. The drawing is still valid.
    </div>;
  }
  if (!dimensional.length && !discrepancies.length) {
    return <div className="p-3 text-sm text-slate-500" data-testid="proposal-panel-empty">No proposals yet. Draw facets/edges to compare against confirmed measurements.</div>;
  }

  return <div className="space-y-2 p-1" data-testid="proposal-panel">
    {dimensional.map((p) => {
      const isFacet = p.target_type === "facet";
      const unit = p.metric === "area_sqft" ? "SF" : "LF";
      const sketchEntity = isFacet ? fById(doc, p.target_id) : eById(doc, p.target_id);
      const relId = isFacet ? sketchEntity?.measurement_facet_id : sketchEntity?.measurement_edge_id;
      const rel = relId ? (isFacet ? relFacetsById[relId] : relEdgesById[relId]) : null;
      const mapped = !!rel; // valid mapping present in the current structure
      const currentConfirmed = mapped ? (isFacet ? Number(rel.area_sqft) || 0 : Number(rel.length_ft) || 0) : p.confirmed;
      const cmp = compareProposal(currentConfirmed, p.proposed);
      const dec = mapped ? decisionFor(doc.proposal_decisions, p.target_type, String(relId), p.metric) : null;
      const status = dec ? STATUS[dec.decision] : null;
      const label = isFacet ? (rel?.facet_label || sketchEntity?.label || p.target_id) : (rel?.edge_type || sketchEntity?.type || p.target_id);
      return <div key={`${p.target_type}-${p.target_id}-${p.metric}`} className="rounded border border-slate-200 p-2 text-sm" data-testid={`proposal-${p.target_id}`}>
        <div className="flex items-center justify-between">
          <div className="font-medium text-slate-700">{isFacet ? "Facet" : "Edge"} {label}</div>
          {!mapped && <Badge variant="outline" className="text-amber-700" data-testid={`proposal-unmapped-${p.target_id}`}>Unmapped</Badge>}
          {status && <Badge className={status[1]} data-testid={`proposal-status-${p.target_id}`}>{status[0]}</Badge>}
        </div>
        <div className="mt-1 grid grid-cols-3 gap-2 text-xs text-slate-600">
          <div>Current<div className="text-sm font-semibold text-slate-800">{fmt(cmp.confirmed, unit)}</div></div>
          <div>Sketch proposes<div className="text-sm font-semibold text-slate-800">{fmt(cmp.proposed, unit)}</div></div>
          <div>Difference<div className={`text-sm font-semibold ${cmp.difference > 0 ? "text-emerald-700" : cmp.difference < 0 ? "text-rose-700" : "text-slate-800"}`}>{cmp.difference == null ? "—" : `${cmp.difference > 0 ? "+" : ""}${cmp.difference} ${unit}`}</div></div>
        </div>
        {!readOnly && <div className="mt-2 flex gap-2">
          <Button size="sm" disabled={!mapped} onClick={() => onAccept(p)} data-testid={`accept-proposed-${p.target_id}`}>Accept Proposed</Button>
          <Button size="sm" variant="outline" onClick={() => onKeep(p)} data-testid={`keep-current-${p.target_id}`}>Keep Current</Button>
        </div>}
        {!mapped && <div className="mt-1 text-[11px] text-amber-700" data-testid={`proposal-precondition-${p.target_id}`}>Map this sketch {isFacet ? "facet to a Measurement Facet" : "edge to a Measurement Edge"} before accepting this proposal.</div>}
      </div>;
    })}
    {discrepancies.map((p) => (
      <div key={`disc-${p.target_id}`} className="rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900" data-testid={`discrepancy-${p.target_id}`}>
        <b>Locked edge {p.target_id}</b> — confirmed {fmt(p.confirmed, "LF")}; sketch geometry {fmt(p.proposed, "LF")} (Δ {p.difference > 0 ? "+" : ""}{p.difference} LF). Confirmed value kept.
      </div>
    ))}
  </div>;
}

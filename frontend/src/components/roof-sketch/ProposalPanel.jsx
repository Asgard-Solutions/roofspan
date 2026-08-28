import { compareProposal } from "@roofspan/roof-sketch-core";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { fById, decisionFor } from "./commands";

const fmt = (n, unit) => (n == null ? "—" : `${Number(n).toFixed(unit === "SF" ? 0 : 1)} ${unit}`);

// Renders geometry proposals vs current confirmed relational facts. Acceptance is ALWAYS explicit and
// never touches unmapped relational records.
export default function ProposalPanel({ doc, proposals, relFacetsById, onAccept, onKeep, readOnly }) {
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
      const sketchFacet = isFacet ? fById(doc, p.target_id) : null;
      const mfid = sketchFacet?.measurement_facet_id || null;
      const rel = isFacet && mfid ? relFacetsById[mfid] : null;
      const mapped = isFacet ? !!rel : false; // Task 4: only facet<->MeasurementFacet mapping accepts to worksheet
      const currentConfirmed = isFacet ? (rel ? Number(rel.area_sqft) || 0 : null) : p.confirmed;
      const cmp = compareProposal(currentConfirmed, p.proposed);
      const dec = decisionFor(doc, p.target_type, p.target_id, p.metric);
      const label = isFacet ? (rel?.facet_label || sketchFacet?.label || p.target_id) : (p.target_id);
      return <div key={`${p.target_type}-${p.target_id}-${p.metric}`} className="rounded border border-slate-200 p-2 text-sm" data-testid={`proposal-${p.target_id}`}>
        <div className="flex items-center justify-between">
          <div className="font-medium text-slate-700">{isFacet ? "Facet" : "Edge"} {label}</div>
          {!mapped && <Badge variant="outline" className="text-amber-700" data-testid={`proposal-unmapped-${p.target_id}`}>Unmapped</Badge>}
          {dec && <Badge className={dec.decision === "accepted" ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-700"}>{dec.decision === "accepted" ? "Accepted" : "Kept current"}</Badge>}
        </div>
        <div className="mt-1 grid grid-cols-3 gap-2 text-xs text-slate-600">
          <div>Current<div className="text-sm font-semibold text-slate-800">{fmt(cmp.confirmed, unit)}</div></div>
          <div>Sketch proposes<div className="text-sm font-semibold text-slate-800">{fmt(cmp.proposed, unit)}</div></div>
          <div>Difference<div className={`text-sm font-semibold ${cmp.difference > 0 ? "text-emerald-700" : cmp.difference < 0 ? "text-rose-700" : "text-slate-800"}`}>{cmp.difference == null ? "—" : `${cmp.difference > 0 ? "+" : ""}${cmp.difference} ${unit}`}</div></div>
        </div>
        {!readOnly && <div className="mt-2 flex gap-2">
          <Button size="sm" disabled={!mapped} onClick={() => onAccept(p, { measurementFacetId: mfid })} data-testid={`accept-proposed-${p.target_id}`}>Accept Proposed</Button>
          <Button size="sm" variant="outline" onClick={() => onKeep(p)} data-testid={`keep-current-${p.target_id}`}>Keep Current</Button>
        </div>}
        {!mapped && isFacet && <div className="mt-1 text-[11px] text-amber-700">Not linked to a Worksheet facet — accepting will not change any measurement.</div>}
      </div>;
    })}
    {discrepancies.map((p) => (
      <div key={`disc-${p.target_id}`} className="rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900" data-testid={`discrepancy-${p.target_id}`}>
        <b>Locked edge {p.target_id}</b> — confirmed {fmt(p.confirmed, "LF")}; sketch geometry {fmt(p.proposed, "LF")} (Δ {p.difference > 0 ? "+" : ""}{p.difference} LF). Confirmed value kept.
      </div>
    ))}
  </div>;
}

import { useState } from "react";
import { EDGE_TYPES, distance } from "@roofspan/roof-sketch-core";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { vById, eById, fById } from "./commands";

const EDGE_LABEL = { eave: "Eave", rake: "Rake", ridge: "Ridge", hip: "Hip", valley: "Valley", sidewall: "Sidewall", headwall: "Headwall", transition: "Transition", unclassified: "Unclassified" };
const PEN_TYPES = [["pipe_boot", "Pipe boot"], ["vent", "Vent"], ["chimney", "Chimney"], ["skylight", "Skylight"], ["hvac", "HVAC"], ["other", "Other"]];

function Section({ title, children, testid }) {
  return <div className="rounded border border-slate-200 p-2" data-testid={testid}>
    <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>
    <div className="space-y-2">{children}</div>
  </div>;
}

export default function SketchInspector({ doc, selection, cmd, readOnly, relFacets = [], relEdges = [] }) {
  const [calFeet, setCalFeet] = useState("");
  const fpu = doc.scale?.resolved ? Number(doc.scale.feetPerUnit) : null;
  const sel = selection || {};
  const edge = sel.type === "edge" ? eById(doc, sel.id) : null;
  const facet = sel.type === "facet" ? fById(doc, sel.id) : null;
  const pen = sel.type === "penetration" ? (doc.penetrations || []).find((p) => p.id === sel.id) : null;

  const edgeLenUnits = edge ? distance([vById(doc, edge.v1)?.x, vById(doc, edge.v1)?.y], [vById(doc, edge.v2)?.x, vById(doc, edge.v2)?.y]) : 0;
  const edgeLenFt = fpu ? edgeLenUnits * fpu : null;

  // one-to-one: MeasurementFacet/Edge ids already used by OTHER sketch entities are disabled.
  const usedFacetIds = new Set((doc.facets || []).filter((f) => f.measurement_facet_id).map((f) => String(f.measurement_facet_id)));
  const usedEdgeIds = new Set((doc.edges || []).filter((e) => e.measurement_edge_id).map((e) => String(e.measurement_edge_id)));
  const facetValid = facet?.measurement_facet_id && relFacets.some((rf) => String(rf.id) === String(facet.measurement_facet_id));
  const edgeValid = edge?.measurement_edge_id && relEdges.some((re) => String(re.id) === String(edge.measurement_edge_id));

  return <div className="space-y-3" data-testid="sketch-inspector">
    <Section title="Scale" testid="inspector-scale">
      <div className="flex items-center gap-2 text-sm">
        {doc.scale?.resolved
          ? <Badge className="bg-emerald-100 text-emerald-800" data-testid="scale-status">Scaled · {Number(doc.scale.feetPerUnit).toFixed(4)} ft/unit</Badge>
          : <Badge variant="outline" className="text-amber-700" data-testid="scale-status">Unscaled</Badge>}
      </div>
      {!readOnly && (edge
        ? <div className="flex items-end gap-2">
            <div className="flex-1"><div className="text-[11px] text-slate-400">Known length of selected edge (ft)</div>
              <Input type="number" step="0.1" value={calFeet} onChange={(e) => setCalFeet(e.target.value)} placeholder="24.5" data-testid="calibrate-input" /></div>
            <Button size="sm" disabled={!(Number(calFeet) > 0)} onClick={() => { cmd.calibrate(edge.id, Number(calFeet)); setCalFeet(""); }} data-testid="calibrate-btn">Calibrate Scale</Button>
          </div>
        : <div className="text-xs text-slate-400">Select an edge, then enter its real length to calibrate.</div>)}
    </Section>

    {edge && <Section title="Edge" testid="inspector-edge">
      <div className="flex items-center gap-2">
        <Select value={edge.type || "unclassified"} disabled={readOnly} onValueChange={(v) => cmd.setEdgeType(edge.id, v)}>
          <SelectTrigger className="w-40" data-testid="edge-type-select"><SelectValue /></SelectTrigger>
          <SelectContent>{EDGE_TYPES.map((t) => <SelectItem key={t} value={t}>{EDGE_LABEL[t] || t}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      <div data-testid="edge-mapping">
        <div className="text-[11px] text-slate-400">Measurement Edge</div>
        <Select value={edge.measurement_edge_id || "none"} disabled={readOnly} onValueChange={(v) => cmd.setEdgeLink(edge.id, v === "none" ? null : v)}>
          <SelectTrigger className="w-full" data-testid="edge-map-select"><SelectValue placeholder="Unmapped" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="none">Unmapped</SelectItem>
            {relEdges.map((re) => {
              const taken = usedEdgeIds.has(String(re.id)) && String(re.id) !== String(edge.measurement_edge_id);
              return <SelectItem key={re.id} value={re.id} disabled={taken}>{(EDGE_LABEL[re.edge_type] || re.edge_type || "Edge")} — {Number(re.length_ft || 0).toFixed(1)} LF{taken ? " (mapped)" : ""}</SelectItem>;
            })}
          </SelectContent>
        </Select>
        {edge.measurement_edge_id && !edgeValid && <div className="mt-1 rounded bg-amber-50 px-2 py-1 text-[11px] text-amber-800" data-testid="edge-map-invalid">Linked measurement edge no longer exists in this structure — treated as Unmapped. Pick a valid edge.</div>}
      </div>
      <div className="text-xs text-slate-500">Geometry: {edgeLenFt == null ? `${edgeLenUnits.toFixed(1)} units (unscaled)` : `${edgeLenFt.toFixed(1)} ft`}</div>
      <div className="flex items-end gap-2">
        <div className="flex-1"><div className="text-[11px] text-slate-400">Confirmed length (ft)</div>
          <Input type="number" step="0.1" value={edge.confirmed_length_ft ?? ""} disabled={readOnly} onChange={(e) => cmd.setConfirmedEdgeLength(edge.id, e.target.value)} data-testid="edge-confirmed-input" /></div>
        <label className="flex items-center gap-1 pb-2 text-sm"><input type="checkbox" checked={!!edge.locked} disabled={readOnly} onChange={(e) => (e.target.checked ? cmd.lockEdge(edge.id) : cmd.unlockEdge(edge.id))} data-testid="edge-lock-toggle" />Lock</label>
      </div>
      {edge.locked && edge.confirmed_length_ft != null && edgeLenFt != null && Math.abs(edgeLenFt - Number(edge.confirmed_length_ft)) > 0.05 &&
        <div className="rounded bg-amber-50 p-1 text-[11px] text-amber-800" data-testid="edge-discrepancy">Confirmed {Number(edge.confirmed_length_ft).toFixed(1)} LF · Sketch {edgeLenFt.toFixed(1)} LF · Δ {(edgeLenFt - Number(edge.confirmed_length_ft)).toFixed(1)} LF (confirmed kept)</div>}
      {!readOnly && <Button size="sm" variant="outline" className="text-rose-600" onClick={() => cmd.deleteEdge(edge.id)} data-testid="edge-delete">Delete edge</Button>}
    </Section>}

    {facet && <Section title="Facet" testid="inspector-facet">
      <Input value={facet.label || ""} disabled={readOnly} onChange={(e) => cmd.setFacetLabel(facet.id, e.target.value)} placeholder="F1 — Main Front" data-testid="facet-label-input" />
      <div data-testid="facet-mapping">
        <div className="text-[11px] text-slate-400">Measurement Facet</div>
        <Select value={facet.measurement_facet_id || "none"} disabled={readOnly} onValueChange={(v) => cmd.setFacetLink(facet.id, v === "none" ? null : v)}>
          <SelectTrigger className="w-full" data-testid="facet-map-select"><SelectValue placeholder="Unmapped" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="none">Unmapped</SelectItem>
            {relFacets.map((rf) => {
              const taken = usedFacetIds.has(String(rf.id)) && String(rf.id) !== String(facet.measurement_facet_id);
              return <SelectItem key={rf.id} value={rf.id} disabled={taken}>{rf.facet_label || "Facet"} — {Number(rf.area_sqft || 0).toFixed(0)} sf{rf.pitch_rise != null ? ` — ${rf.pitch_rise}/12` : ""}{taken ? " (mapped)" : ""}</SelectItem>;
            })}
          </SelectContent>
        </Select>
        {facet.measurement_facet_id && !facetValid && <div className="mt-1 rounded bg-amber-50 px-2 py-1 text-[11px] text-amber-800" data-testid="facet-map-invalid">Linked measurement facet no longer exists in this structure — treated as Unmapped. Pick a valid facet.</div>}
      </div>
      <div className="flex items-center gap-2">
        <div className="flex-1"><div className="text-[11px] text-slate-400">Pitch (rise / 12)</div>
          <Input type="number" step="0.5" value={facet.pitch_rise ?? 0} disabled={readOnly} onChange={(e) => cmd.setFacetPitch(facet.id, e.target.value)} data-testid="facet-pitch-input" /></div>
        <div className="flex-1"><div className="text-[11px] text-slate-400">Orientation</div>
          <Input value={facet.orientation || ""} disabled={readOnly} onChange={(e) => cmd.setFacetOrientation(facet.id, e.target.value)} placeholder="N / SE" data-testid="facet-orientation-input" /></div>
      </div>
      <div className="text-xs text-slate-500" data-testid="facet-area-readout">{fpu ? "Area proposal appears in the Proposals panel below." : "Unscaled — no SF until you calibrate."}</div>
      {!readOnly && <Button size="sm" variant="outline" className="text-rose-600" onClick={() => cmd.deleteFacet(facet.id)} data-testid="facet-delete">Delete facet</Button>}
    </Section>}

    {pen && <Section title="Penetration" testid="inspector-penetration">
      <Select value={pen.pen_type || "pipe_boot"} disabled={readOnly} onValueChange={(v) => cmd.setPenetrationType(pen.id, v)}>
        <SelectTrigger className="w-40" data-testid="pen-type-select"><SelectValue /></SelectTrigger>
        <SelectContent>{PEN_TYPES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
      </Select>
      {pen.measurement_penetration_id && <div className="text-[11px] text-slate-400">Linked to measurement penetration</div>}
      {!readOnly && <Button size="sm" variant="outline" className="text-rose-600" onClick={() => cmd.deletePenetration(pen.id)} data-testid="pen-delete">Delete penetration</Button>}
    </Section>}

    {!edge && !facet && !pen && <div className="rounded border border-dashed border-slate-200 p-3 text-xs text-slate-400" data-testid="inspector-empty">Select a vertex, edge, facet or penetration to edit its properties.</div>}
  </div>;
}

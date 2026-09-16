import React from 'react';
import Svg, { G, Polygon, Line } from 'react-native-svg';
import * as RS from '@roofspan/roof-sketch-core';
import { fitToViewport, documentPoints } from '../roofSketchView';

const EDGE_COLOR = { ridge: '#0f172a', hip: '#2563eb', valley: '#dc2626', dead_valley: '#b91c1c', eave: '#0f766e', rake: '#a16207' };

// Identical model coordinates/colors at both sizes. Pan, zoom and fitting change only this SVG group.
export default function RoofPreviewDrawing({ document, width, height, view }) {
  if (!document) return null;
  const v = view || fitToViewport(documentPoints(document), { width, height, padding: 8, min: 0.000001, max: 10000 });
  const vertices = Object.fromEntries(document.vertices.map(p => [p.id, p]));
  return (
    <Svg width={width} height={height}>
      <G transform={`translate(${v.tx}, ${v.ty}) scale(${v.scale})`}>
        {document.facets.map(f => {
          const boundary = RS.resolveFacetBoundary(document, f);
          return <Polygon key={f.id} points={(boundary.points || []).map(p => p.join(',')).join(' ')} fill="rgba(148,163,184,0.14)" />;
        })}
        {document.edges.map(e => {
          const a = vertices[e.v1], b = vertices[e.v2];
          return a && b ? <Line key={e.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={EDGE_COLOR[e.type] || '#94a3b8'} strokeWidth={1.4 / v.scale} strokeLinecap="round" /> : null;
        })}
      </G>
    </Svg>
  );
}

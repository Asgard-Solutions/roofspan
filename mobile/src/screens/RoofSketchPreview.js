import React, { useEffect, useMemo, useRef, useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, PanResponder } from 'react-native';
import RoofPreviewDrawing from '../components/RoofPreviewDrawing';
import SketchMeasurementsPanel from '../components/SketchMeasurementsPanel';
import NewMeasurementRevisionButton from '../components/NewMeasurementRevisionButton';
import { matchesPreviewRoute } from '../measurementRoofPreview';
import * as VIEW from '../roofSketchView';
import { applyTwoTouchView } from '../roofSketchFieldWiring';

export default function RoofSketchPreview({ route, navigation }) {
  const { measurement_preview: preview, revision_id, structure_id, editable, measurement_scope: scope } = route.params || {};
  const [size, setSize] = useState({ width: 320, height: 320 });
  const [offset, setOffset] = useState(null);
  const gesture = useRef(null);
  const valid = matchesPreviewRoute(preview, revision_id, structure_id) && preview.status === 'ok' && !!preview.document;
  const fitted = useMemo(() => VIEW.fitToViewport(VIEW.documentPoints(valid ? preview.document : null), { ...size, padding: 24, min: 0.000001, max: 10000 }), [preview, valid, size]);
  useEffect(() => { setOffset(null); gesture.current = null; }, [preview]);
  const view = offset || fitted;
  const current = useRef(view); current.current = view;
  const touches = evt => {
    const t = evt.nativeEvent.touches;
    if (t.length >= 2) {
      const a = [t[0].locationX, t[0].locationY], b = [t[1].locationX, t[1].locationY];
      return { mid: VIEW.touchMidpoint(a, b), dist: VIEW.touchDistance(a, b) };
    }
    return { point: [evt.nativeEvent.locationX, evt.nativeEvent.locationY] };
  };
  const pan = PanResponder.create({
    onStartShouldSetPanResponder: () => true, onMoveShouldSetPanResponder: () => true,
    onPanResponderGrant: e => { gesture.current = touches(e); },
    onPanResponderMove: e => {
      const before = gesture.current, now = touches(e);
      let next = current.current;
      if (before?.mid && now.mid) next = applyTwoTouchView(next, before, now, { min: fitted.scale / 4, max: fitted.scale * 20 });
      else if (before?.point && now.point) next = VIEW.pan(next, now.point[0] - before.point[0], now.point[1] - before.point[1]);
      current.current = next; setOffset(next); gesture.current = now;
    },
    onPanResponderRelease: () => { gesture.current = null; },
    onPanResponderTerminate: () => { gesture.current = null; },
  });
  if (!valid) return <View style={s.container}><Text style={s.note}>Preview unavailable. Return to Roof measurements and open the drawing again.</Text></View>;
  return (
    <View style={s.container} testID="roof-measurement-preview">
      <View style={s.header}>
        <Text style={s.title}>{preview.structure_name}</Text>
        <Text style={s.note}>Roof measurements · Revision {preview.revision_number}{preview.stale ? ' · Offline/cached' : ''}</Text>
        {!editable && <Text style={s.note}>This revision is locked.</Text>}
      </View>
      <View testID="roof-preview-canvas" style={s.canvas} {...pan.panHandlers}
        onLayout={e => { const { width, height } = e.nativeEvent.layout; if (width > 0 && height > 0) { setSize({ width, height }); setOffset(null); } }}>
        <RoofPreviewDrawing document={preview.document} width={size.width} height={size.height} view={view} />
      </View>
      <View style={s.controls}>
        <Text style={s.note}>Drag to pan · Pinch to zoom</Text>
        <TouchableOpacity testID="roof-preview-fit" onPress={() => setOffset(null)} style={s.fit}><Text style={s.fitText}>Fit roof</Text></TouchableOpacity>
      </View>
      <SketchMeasurementsPanel measDetail={preview.measurement_detail} structureId={structure_id} />
      {!editable && scope && <NewMeasurementRevisionButton revisionId={revision_id} scope={scope}
        onCreated={revision => navigation.navigate('Measurements', { ...scope, revision_id: revision.id }, { pop: true })} />}
    </View>
  );
}
const s = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f8fafc' }, header: { padding: 16 },
  title: { fontSize: 22, fontWeight: '800', color: '#0f172a' }, note: { fontSize: 14, color: '#475569', marginTop: 6 },
  canvas: { flex: 1, marginHorizontal: 12, backgroundColor: '#fff', borderColor: '#e2e8f0', borderWidth: 1, borderRadius: 12, overflow: 'hidden' },
  controls: { padding: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  fit: { padding: 12 }, fitText: { color: '#c2410c', fontWeight: '700' },
});

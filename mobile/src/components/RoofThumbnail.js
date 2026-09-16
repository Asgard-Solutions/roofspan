import React, { useMemo } from 'react';
import { View, Text } from 'react-native';
import RoofPreviewDrawing from './RoofPreviewDrawing';
import { buildMeasurementRoofPreview } from '../measurementRoofPreview';

export default function RoofThumbnail({ preview, structure, facets = [], edges = [], testID }) {
  const drawing = useMemo(() => preview || buildMeasurementRoofPreview({ structure, facets, edges }), [preview, structure, facets, edges]);
  return (
    <View testID={testID} style={{ width: 128, height: 84, borderRadius: 6, borderWidth: 1, borderColor: '#e2e8f0', backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' }}>
      {drawing.status === 'ok' ? <RoofPreviewDrawing document={drawing.document} width={128} height={84} /> :
        <Text style={{ fontSize: 10, color: '#64748b' }}>{drawing.status === 'empty' ? 'No roof planes yet' : 'Preview needs review'}</Text>}
    </View>
  );
}

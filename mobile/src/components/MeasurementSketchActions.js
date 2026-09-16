import React, { useMemo } from 'react';
import { View, Text, TouchableOpacity } from 'react-native';
import { buildMeasurementRoofPreview } from '../measurementRoofPreview';
import RoofThumbnail from './RoofThumbnail';

export default function MeasurementSketchActions({ revision, structure, facets, edges, penetrations, readonly, stale, scope, navigation, index, styles }) {
  const preview = useMemo(() => buildMeasurementRoofPreview({ revisionId: revision.id, revisionNumber: revision.revision_number,
    updatedAt: revision.if_match, structure, facets, edges, penetrations, stale }), [revision, structure, facets, edges, penetrations, stale]);
  const params = { revision_id: revision.id, structure_id: structure.id, structure_name: structure.name || 'Roof', editable: !readonly };
  return (
    <View>
      <RoofThumbnail preview={preview} testID={`meas-structure-thumbnail-${index}`} />
      <TouchableOpacity testID={`sketch-roof-${index}`} disabled={preview.status !== 'ok'}
        style={[styles.sketchBtn, preview.status !== 'ok' && { opacity: 0.45 }]}
        onPress={() => navigation.navigate('RoofSketch', { ...params, measurement_preview: preview, measurement_scope: scope })}>
        <Text style={styles.sketchBtnText}>View Roof Sketch</Text>
      </TouchableOpacity>
      {!readonly && <TouchableOpacity testID={`edit-saved-sketch-${index}`} style={{ paddingVertical: 12 }}
        onPress={() => navigation.navigate('RoofSketch', params)}>
        <Text style={{ color: '#c2410c', textAlign: 'center', fontWeight: '700' }}>{structure.has_sketch ? 'Edit Saved Sketch' : 'Create Saved Sketch'}</Text>
      </TouchableOpacity>}
    </View>
  );
}

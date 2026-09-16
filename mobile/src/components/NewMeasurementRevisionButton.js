import React, { useRef, useState } from 'react';
import { Text, TouchableOpacity, Alert } from 'react-native';
import { api } from '../api';
import { getCache, mutateCache, putCacheSerialized } from '../storage';
import { createFieldRevision, finishFieldRevision } from '../measurementNewRevision';

export default function NewMeasurementRevisionButton({ revisionId, scope, onCreated }) {
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  const create = async () => {
    if (running.current) return;
    running.current = true; setBusy(true);
    try {
      const revision = await createFieldRevision({ revisionId, scope, request: api.request, getCache, mutateCache, putCache: putCacheSerialized });
      await onCreated(revision);
      // A failure to clear this receipt must not report that an already-adopted clone failed.
      try { await finishFieldRevision(revisionId, putCacheSerialized); } catch (_) { /* next retry remains idempotent */ }
    } catch (e) {
      const detail = e?.response?.data?.detail;
      const message = typeof detail === 'string' ? detail : detail?.message;
      Alert.alert('Could not open a new revision', message || (e?.code === 'unsaved_measurements' ? e.message : 'Connect to RoofSpan Office and try again.'));
    } finally { running.current = false; setBusy(false); }
  };
  return (
    <TouchableOpacity testID="create-measurement-revision" accessibilityRole="button" disabled={busy} onPress={create}
      style={{ margin: 12, padding: 14, borderRadius: 10, backgroundColor: '#ea580c', opacity: busy ? 0.5 : 1 }}>
      <Text style={{ textAlign: 'center', color: '#fff', fontWeight: '800', fontSize: 16 }}>{busy ? 'Creating revision…' : 'Create New Revision & Edit'}</Text>
    </TouchableOpacity>
  );
}

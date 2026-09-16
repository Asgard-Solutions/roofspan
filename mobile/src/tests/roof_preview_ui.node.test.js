// Run with the isolated tooling installed by .github/workflows/field-roof-preview.yml.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { React, boundary, render, press, textOf, unmount, renderer } = require('./helpers/renderField');
const revision = {
  id: 'R3', revision_number: 3, status: 'locked', editable: false, updated_at: '2026-09-16T19:00:00Z',
  structures: [{ id: 'HOUSE', name: 'House', has_sketch: true }, { id: 'GARAGE', name: 'Garage', has_sketch: true }],
  facets: [
    { id: 'FRONT', structure_id: 'HOUSE', facet_label: 'Front', pitch_rise: 6, width_ft: 18, length_ft: 40, area_sqft: 720 },
    { id: 'BACK', structure_id: 'HOUSE', facet_label: 'Back', pitch_rise: 6, width_ft: 18, length_ft: 40, area_sqft: 720 },
    { id: 'G1', structure_id: 'GARAGE', facet_label: 'Garage', pitch_rise: 4, width_ft: 10, length_ft: 20, area_sqft: 200 },
  ], edges: [{ id: 'RIDGE', edge_type: 'ridge', length_ft: 40, facet_id: 'FRONT', facet_id_secondary: 'BACK' }],
  penetrations: [{ id:'P1', facet_id:'FRONT', pen_type:'pipe_boot', quantity:2 },
    { id:'P2', facet_id:'G1', pen_type:'skylight', quantity:1 }], summary: {},
};
const stray = { revision_id: 'R3', structure_id: 'HOUSE', document_version: 3, document: {
  edit_mode: 'connected_graph', vertices: [{ id: 'a', x: 0, y: 0 }, { id: 'b', x: 23.8, y: 0 }],
  edges: [{ id: 'stray', v1: 'a', v2: 'b' }], facets: [], penetrations: [] } };
let sketchReads = 0, writes = 0, queueFails = false, measurementMissing = false, navigated, clonedRevision = null, offline = false;
let workingDraft = null;
const deviceCache = new Map();
const syncListeners = new Set();
const no = async () => null;
const sync = new Proxy({
  currentMeasurementMutation: async () => { if (queueFails) throw Error('queue read failed'); return null; },
  isSyncing: () => false, onSyncChange: fn => { syncListeners.add(fn); return () => syncListeners.delete(fn); }, registerActiveLead: () => {},
}, { get: (obj, key) => obj[key] || no });
boundary('sync', sync);
boundary('storage', { getCache: async k => deviceCache.get(k) || null, putCacheSerialized: async (k,v) => { writes++; deviceCache.set(k,v); }, mutateCache: async (k, fn) => { writes++; const v=fn(deviceCache.get(k)); deviceCache.set(k,v); return v; } });
boundary('api', { api: { request: async req => { writes++; assert.match(req.url, /new-revision$/); if (clonedRevision) return {data:clonedRevision}; throw Error('No network writes expected'); } } });
boundary('cache', new Proxy({
  loadMeasurementWorkingDraft: async () => workingDraft,
  saveMeasurementWorkingDraft: async (_, value) => { workingDraft = JSON.parse(JSON.stringify(value)); return true; },
  clearMeasurementWorkingDraft: async () => { workingDraft = null; },
  cache: {
  measurements: async () => ({ data: [revision], stale: offline }),
  measurement: async id => measurementMissing ? { data: null, stale: true, error: Error('offline') } : { data: clonedRevision?.id === id ? clonedRevision : revision, stale: offline },
  sketch: async () => { sketchReads++; return { data: stray, stale: false }; },
}}, { get: (obj, key) => obj[key] || no }));
boundary('components/PhotoSection', { __esModule: true, default: () => null });
const Measurements = require('../screens/Measurements').default;
const RoofSketch = require('../screens/RoofSketch').default;
const navigation = { navigate: (name, params) => { navigated = { name, params }; } };
function geometry(tree) {
  return {
    polygons: tree.findAllByType('Polygon').map(n => n.props.points),
    lines: tree.findAllByType('Line').map(n => [n.props.x1, n.props.y1, n.props.x2, n.props.y2, n.props.stroke]),
  };
}

test('View Roof Sketch opens the displayed House drawing despite a different saved sketch, without reading or writing sketches', async () => {
  let page, viewer;
  sketchReads = writes = 0;
  try {
    page = await render(Measurements, { route: { params: { lead_id: 'L1' } }, navigation });
    const thumb = page.root.findAll(n => n.type === 'View' && n.props.testID === 'meas-structure-thumbnail-0')[0];
    const shown = geometry(thumb);
    assert.equal(shown.polygons.length, 2, 'fixture is a two-plane House roof');
    await press(page, 'sketch-roof-0');
    assert.equal(navigated.name, 'RoofSketch');
    viewer = await render(RoofSketch, { route: { params: navigated.params }, navigation });
    assert.equal(viewer.root.findAllByType('Polygon').length, 2, 'opened drawing must contain the same two House planes, not the saved stray line');
    assert.deepEqual(geometry(viewer.root), shown, 'only the viewport transform may change');
    assert.equal(sketchReads, 0, 'viewing the preview must not substitute saved or cached sketch data');
    assert.equal(writes, 0, 'opening a preview cannot alter a saved sketch or enqueue work');
    assert.match(textOf(viewer), /1440/);
    assert.doesNotMatch(textOf(viewer), /Accept Proposed|Save Sketch/);
    await press(viewer, 'sketch-meas-toggle');
    assert.match(textOf(viewer), /Pipe Boot/);
    assert.doesNotMatch(textOf(viewer), /Skylight/);
  } finally { await unmount(viewer); await unmount(page); }
});

test('saved-sketch measurement panel keeps successfully loaded measurements when the queue lookup fails', async () => {
  let viewer; queueFails = true;
  try {
    viewer = await render(RoofSketch, { route: { params: { revision_id: 'R3', structure_id: 'HOUSE', editable: false } }, navigation });
    assert.match(textOf(viewer), /1440/, 'valid measurement result must reach the panel independently of optional queue metadata');
  } finally { queueFails = false; await unmount(viewer); }
});

test('missing measurement data displays unavailable with retry instead of zero totals', async () => {
  let viewer; measurementMissing = true;
  try {
    viewer = await render(RoofSketch, { route: { params: { revision_id: 'R3', structure_id: 'HOUSE', editable: false } }, navigation });
    assert.match(textOf(viewer), /Measurements unavailable/);
    assert.doesNotMatch(textOf(viewer), /0\.00/);
    measurementMissing = false;
    await press(viewer, 'sketch-meas-retry');
    assert.match(textOf(viewer), /1440/);
  } finally { measurementMissing = false; await unmount(viewer); }
});

test('Garage view stays scoped and works offline without a saved sketch', async () => {
  let page, viewer;
  const old = revision.structures[1].has_sketch;
  revision.structures[1].has_sketch = false; offline = true;
  try {
    page = await render(Measurements, { route: { params: { lead_id: 'L1' } }, navigation });
    await press(page, 'sketch-roof-1');
    viewer = await render(RoofSketch, { route: { params: navigated.params }, navigation });
    assert.equal(viewer.root.findAllByType('Polygon').length, 1);
    assert.match(textOf(viewer), /200/);
    assert.equal(navigated.params.structure_id, 'GARAGE');
    assert.match(textOf(viewer), /Offline\/cached/);
  } finally { offline = false; revision.structures[1].has_sketch = old; await unmount(viewer); await unmount(page); }
});

test('invalid preview identity cannot fall through to another saved sketch', async () => {
  let viewer; const reads = sketchReads;
  try {
    viewer = await render(RoofSketch, { route: { params: { revision_id: 'R3', structure_id: 'GARAGE',
      measurement_preview: { revision_id: 'R3', structure_id: 'HOUSE', status: 'ok', document: stray.document } } }, navigation });
    assert.match(textOf(viewer), /Preview unavailable/);
    assert.equal(sketchReads, reads);
    assert.equal(viewer.root.findAllByType('Polygon').length, 0);
  } finally { await unmount(viewer); }
});

test('pan, pinch, layout changes and Fit roof never change preview geometry', async () => {
  let page, viewer;
  try {
    page = await render(Measurements, { route: { params: { lead_id: 'L1' } }, navigation });
    await press(page, 'sketch-roof-0');
    const snapshot = JSON.stringify(navigated.params.measurement_preview);
    viewer = await render(RoofSketch, { route: { params: navigated.params }, navigation });
    const canvas = () => viewer.root.findAll(n => n.type === 'View' && n.props.testID === 'roof-preview-canvas')[0];
    const shape = geometry(viewer.root);
    const transform = () => viewer.root.findAllByType('G')[0].props.transform;
    await renderer.act(async () => canvas().props.onLayout({ nativeEvent: { layout: { width: 320, height: 460 } } }));
    const fitted = transform();
    const event = (x,y) => ({ nativeEvent: { locationX:x, locationY:y, touches:[{ locationX:x,locationY:y }] } });
    await renderer.act(async () => canvas().props.onPanResponderGrant(event(10,10)));
    await renderer.act(async () => canvas().props.onPanResponderMove(event(50,40)));
    assert.notEqual(transform(), fitted);
    const pair = d => ({ nativeEvent: { touches: [{locationX:50,locationY:50},{locationX:50+d,locationY:50}] } });
    await renderer.act(async () => canvas().props.onPanResponderGrant(pair(10)));
    const panned = transform();
    await renderer.act(async () => canvas().props.onPanResponderMove(pair(20)));
    assert.notEqual(transform(), panned);
    await press(viewer, 'roof-preview-fit');
    assert.equal(transform(), fitted);
    await renderer.act(async () => canvas().props.onLayout({ nativeEvent: { layout: { width: 460, height: 220 } } }));
    assert.notEqual(transform(), fitted, 'orientation/layout change refits the roof');
    assert.deepEqual(geometry(viewer.root), shape);
    assert.equal(JSON.stringify(navigated.params.measurement_preview), snapshot);
  } finally { await unmount(viewer); await unmount(page); }
});


test('new revision action opens the returned editable revision even when the list still contains the locked source', async () => {
  let page;
  clonedRevision = { ...revision, id: 'R4', revision_number: 4, editable: true, status: 'draft',
    structures: [{ id:'NEW-HOUSE', name:'Cloned House', has_sketch:true }], facets:[], edges:[] };
  const props = { route:{params:{lead_id:'L1'}}, navigation:{
    ...navigation, setParams: values => page.update(React.createElement(Measurements, { ...props, route:{params:{lead_id:'L1',...values}} }))
  }};
  try {
    page = await render(Measurements, props);
    await press(page, 'create-measurement-revision');
    await renderer.act(async () => { for (const cb of syncListeners) cb({type:'sync_end'}); });
    assert.match(textOf(page), /Cloned House/);
    assert.equal(page.root.findAll(n => n.type === 'TextInput' && n.props.value === 'Cloned House')[0].props.editable, true);
    assert.doesNotMatch(textOf(page), /This revision is locked/);
    assert.equal(revision.status, 'locked');
    assert.equal(deviceCache.get('measurement_detail:R4').id,'R4');
  } finally { await unmount(page); clonedRevision=null; deviceCache.clear(); workingDraft=null; }
});

test('opening another revision preserves unsaved source work through edits and reload', async () => {
  let page;
  workingDraft = { working:true, base:{...revision, id:'R2', revision_number:2, editable:true},
    structures:[{id:'SOURCE',ref:'SOURCE',name:'Unsaved source',notes:'Keep these notes'}], facets:[], edges:[], pens:[], summary:{} };
  clonedRevision = {...revision, id:'R4', editable:true, structures:[{id:'CLONE',name:'Clone'}]};
  const props = {route:{params:{lead_id:'L1',revision_id:'R4'}},navigation};
  try {
    page = await render(Measurements, props);
    assert.match(textOf(page), /Unsaved source/);
    assert.match(textOf(page), /Unsaved measurements restored/);
    const name = page.root.findAll(n => n.type === 'TextInput' && n.props.testID === 'meas-structure-name-0')[0];
    await renderer.act(async () => name.props.onChangeText('Source edited again'));
    await unmount(page); page=null;
    assert.equal(workingDraft.base.id,'R2');
    assert.equal(workingDraft.structures[0].notes,'Keep these notes');
    page = await render(Measurements, props);
    assert.match(textOf(page), /Source edited again/);
    assert.match(textOf(page), /Keep these notes/);
  } finally { await unmount(page); workingDraft=null; clonedRevision=null; }
});

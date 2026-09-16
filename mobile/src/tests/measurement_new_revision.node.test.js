const assert = require('node:assert/strict');
const { test } = require('node:test');
test('new-revision retry reuses the persisted key after a lost response and caches the acknowledged revision', async () => {
  const { createFieldRevision } = require('../measurementNewRevision');
  const store = new Map(); let attempts = 0; const keys = [];
  const newRev = { id: 'R4', revision_number: 4, editable: true, structures: [{id:'NEW-HOUSE'}] };
  const deps = { revisionId:'R3', scope:{lead_id:'L1'},
    getCache: async k => store.get(k),
    mutateCache: async (k,fn) => { const v=fn(store.get(k)); store.set(k,v); return v; },
    putCache: async (k,v) => { store.set(k,v); },
    request: async req => { assert.equal(req.url,'/mobile/measurements/R3/new-revision');
      assert.equal(req.method,'POST'); keys.push(req.headers['Idempotency-Key']); attempts++;
      if (attempts === 1) throw Error('lost response'); return {data:newRev}; },
  };
  await assert.rejects(createFieldRevision(deps), /lost response/);
  const result=await createFieldRevision(deps);
  assert.equal(result.id,'R4');
  assert.ok(keys[0]); assert.equal(keys[1],keys[0]);
  assert.equal(store.get('measurement_detail:R4').id,'R4');
  assert.equal(store.get('measurement_scope:lead:L1')[0].id,'R4');
});

test('a failed durable key write stops creation before a network request', async () => {
  const { createFieldRevision } = require('../measurementNewRevision'); let sends=0;
  await assert.rejects(createFieldRevision({ revisionId:'R3',scope:{lead_id:'L1'},
    getCache: async()=>null,
    mutateCache: async()=>{throw Error('disk full');}, request:async()=>{sends++;}, putCache:async()=>{} }), /disk full/);
  assert.equal(sends,0);
});

test('unsaved measurements stop revision creation without replacing the working draft', async () => {
  const { createFieldRevision } = require('../measurementNewRevision');
  const draft = {working:true, base:{id:'R2'}, structures:[{notes:'Unsaved work'}]};
  let sends=0, writes=0;
  await assert.rejects(createFieldRevision({ revisionId:'R3',scope:{lead_id:'L1'},
    getCache: async k => {assert.equal(k,'measurement_working:measurement_scope:lead:L1'); return draft;},
    mutateCache:async()=>{writes++; return {};}, putCache:async()=>{writes++;}, request:async()=>{sends++;}
  }), /Save or resolve your unsaved measurements/);
  assert.equal(sends,0); assert.equal(writes,0);
  assert.equal(draft.structures[0].notes,'Unsaved work');
});

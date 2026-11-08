const test = require('node:test');
const assert = require('node:assert/strict');
const { summarize } = require('../operations-transfers.js');

test('transfer status ignores only tiny LP feasibility residue and keeps the raw ratio', () => {
  const edges=[{edge_id:'A-B',from:'A',to:'B',limit_mw:1000}];
  const state={edges:{'A-B':{flow_mw:1000.0001,limit_mw:1000,loading_frac:1.0000001,tripped:false}}};
  assert.equal(summarize(edges,state).rows[0].status,'warning');
  assert.equal(summarize(edges,state).rows[0].loading,1.0000001);
  state.edges['A-B'].loading_frac=1.001;
  assert.equal(summarize(edges,state).rows[0].status,'overloaded');
});

const topology = [
  { edge_id: 'A-B', from: 'A', to: 'B', limit_mw: 100 },
  { edge_id: 'B-C', from: 'B', to: 'C', limit_mw: 80 },
  { edge_id: 'C-D', from: 'C', to: 'D', limit_mw: 200 }
];
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} differs from ${expected}`);

test('signed transfers reverse source/target and account only corridors connected to the selected zone', () => {
  const result = summarize(topology, { edges: {
    'A-B': { flow_mw: -60, limit_mw: 100, loading_frac: .6, tripped: false },
    'B-C': { flow_mw: -30, limit_mw: 80, loading_frac: .375, tripped: false },
    'C-D': { flow_mw: 150, limit_mw: 200, loading_frac: .75, tripped: false }
  } }, 'B');
  assert.equal(result.rows[0].source, 'B');
  assert.equal(result.rows[0].target, 'A');
  assert.equal(result.rows[0].flowMw, -60);
  assert.equal(result.rows[0].magnitudeMw, 60);
  assert.equal(result.incomingMw, 30);
  assert.equal(result.outgoingMw, 60);
  assert.equal(result.netImportMw, -30);
  assert.equal(result.incomplete, false);
  assert.deepEqual(result.incomingRows.map(row => row.id), ['B-C']);
  assert.deepEqual(result.outgoingRows.map(row => row.id), ['A-B']);
  assert.deepEqual(result.zoneRows.map(row => row.id), ['A-B', 'B-C']);
});

test('transfers conserve net imports over connected zones without being counted as generation', () => {
  const snapshot = { edges: {
    'A-B': { flow_mw: 50, limit_mw: 100 },
    'B-C': { flow_mw: -25, limit_mw: 80 },
    'C-D': { flow_mw: 10, limit_mw: 200 }
  } };
  const results = ['A', 'B', 'C', 'D'].map(zone => summarize(topology, snapshot, zone));
  assert.equal(results.reduce((sum, result) => sum + result.netImportMw, 0), 0);
  assert.equal(results[1].incomingMw, 75);
  assert.equal(results[1].outgoingMw, 0);
  assert.ok(!Object.hasOwn(results[1], 'generationMw'));
});

test('fully out corridors carry no active flow even when the raw snapshot contains a stale flow', () => {
  const result = summarize([topology[0]], { edges: { 'A-B': { flow_mw: 75, limit_mw: 0, loading_frac: 1.5, tripped: true } } }, 'B');
  const row = result.rows[0];
  assert.equal(row.status, 'out');
  assert.equal(row.available, false);
  assert.equal(row.active, false);
  assert.equal(row.flowMw, 75, 'Raw observations remain available for inspection');
  assert.equal(row.effectiveMw, 0);
  assert.equal(row.inconsistent, true);
  assert.equal(result.incomingMw, 0);
  assert.equal(result.netImportMw, 0);
  assert.deepEqual(result.incomingRows, []);
});

test('partial trips remain available and overloads are retained above 100 percent', () => {
  const overloaded = summarize([topology[0]], { edges: { 'A-B': { flow_mw: -90, limit_mw: 50, tripped: true } } }, 'A').rows[0];
  assert.equal(overloaded.status, 'overloaded');
  assert.equal(overloaded.loading, 1.8);
  assert.equal(overloaded.available, true);
  assert.equal(overloaded.active, true);
  assert.equal(overloaded.limitMw, 50);
  assert.equal(overloaded.nameplateLimitMw, 100);
  const derated = summarize([topology[0]], { edges: { 'A-B': { flow_mw: 25, limit_mw: 50, loading_frac: .5, tripped: true } } }, 'B').rows[0];
  assert.equal(derated.status, 'tripped');
  assert.equal(derated.effectiveMw, 25);
});

test('missing flow makes selected-zone totals unknown while retaining clearly named known subtotals', () => {
  const result = summarize(topology, { edges: {
    'A-B': { limit_mw: 100 }, 'B-C': { flow_mw: -25, limit_mw: 80 }
  } }, 'B');
  assert.equal(result.rows[0].known, false);
  assert.equal(result.rows[0].flowMw, null);
  assert.equal(result.rows[0].magnitudeMw, null);
  assert.equal(result.rows[0].source, null);
  assert.equal(result.rows[0].status, 'unknown');
  assert.equal(result.incomplete, true);
  assert.equal(result.incomingMw, null);
  assert.equal(result.outgoingMw, null);
  assert.equal(result.netImportMw, null);
  assert.equal(result.knownIncomingMw, 25);
});

test('unknown capacity does not replace the current limit with nameplate or discard measured flow', () => {
  const result = summarize([topology[0]], { edges: { 'A-B': { flow_mw: 110, loading_frac: 1.1 } } }, 'B');
  const row = result.rows[0];
  assert.equal(row.limitMw, null);
  assert.equal(row.nameplateLimitMw, 100);
  assert.equal(row.available, null);
  assert.equal(row.loadingSource, 'reported');
  assert.equal(row.status, 'overloaded');
  assert.equal(result.incomingMw, 110);
  assert.equal(result.incomplete, false);
});

test('zero and near-zero flows are idle without fabricating zero for absent measurements', () => {
  const result = summarize(topology, { edges: {
    'A-B': { flow_mw: 0, limit_mw: 100 },
    'B-C': { flow_mw: -.04, limit_mw: 80 },
    'C-D': { flow_mw: .05, limit_mw: 200 }
  } }, 'B');
  assert.equal(result.rows[0].status, 'idle');
  assert.equal(result.rows[0].source, null);
  assert.equal(result.rows[1].status, 'idle');
  assert.equal(result.rows[1].active, false);
  assert.equal(result.rows[2].active, true);
  close(result.incomingMw, .04);
  close(result.netImportMw, .04);
  assert.deepEqual(result.incomingRows, []);
});

test('zero-capacity absence is known even if the unavailable corridor has no flow observation', () => {
  const result = summarize([topology[0]], { edges: { 'A-B': { limit_mw: 0, tripped: true } } }, 'B');
  assert.equal(result.rows[0].flowMw, null);
  assert.equal(result.rows[0].status, 'out');
  assert.equal(result.netImportMw, 0);
  assert.equal(result.incomplete, false);
});

test('missing snapshots and unrecognised selections do not assert a fabricated zero balance', () => {
  const missing = summarize(topology, null, 'B');
  assert.equal(missing.incomplete, true);
  assert.equal(missing.incomingMw, null);
  const noZone = summarize(topology, null);
  assert.equal(noZone.netImportMw, null);
  assert.deepEqual(noZone.zoneRows, []);
  assert.equal(summarize(topology, null, 'not-in-topology').netImportMw, null);
});

test('invalid observations and duplicate edges fail explicitly without mutating inputs', () => {
  const frozen = Object.freeze([Object.freeze({ ...topology[0] })]);
  const snapshot = Object.freeze({ edges: Object.freeze({ 'A-B': Object.freeze({ flow_mw: -20, limit_mw: 100 }) }) });
  assert.equal(summarize(frozen, snapshot, 'B').outgoingMw, 20);
  assert.throws(() => summarize([topology[0], topology[0]], snapshot, 'B'), /Duplicate/);
  assert.throws(() => summarize(topology, { edges: { 'A-B': { flow_mw: '20' } } }, 'B'), TypeError);
  assert.throws(() => summarize(topology, { edges: { 'A-B': { limit_mw: -1 } } }, 'B'), RangeError);
  assert.throws(() => summarize(topology, { edges: { 'A-B': { loading_frac: -1 } } }, 'B'), RangeError);
  assert.throws(() => summarize(topology, { edges: { 'A-B': { flow_mw: Infinity } } }, 'B'), TypeError);
});

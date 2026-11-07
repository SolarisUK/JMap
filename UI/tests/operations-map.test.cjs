const test = require('node:test');
const assert = require('node:assert/strict');
const { corridorState, zoneColour, unservedLabel } = require('../operations-map.js');
const edge = { from: 'A', to: 'B', limit_mw: 6000 };

test('signed flow reverses direction without changing absolute loading', () => {
  const result = corridorState({ flow_mw: -4500, limit_mw: 6000, tripped: false }, edge);
  assert.equal(result.loading, .75);
  assert.equal(result.band, 'warning');
  assert.equal(result.from, 'B'); assert.equal(result.to, 'A');
  assert.equal(result.arrow, true);
});

test('exact thermal limit is amber; overload remains red during a partial trip', () => {
  assert.equal(corridorState({ flow_mw: 6000, limit_mw: 6000 }, edge).band, 'warning');
  const result = corridorState({ flow_mw: 3300, limit_mw: 3000, loading_frac: 1.1, tripped: true }, edge);
  assert.equal(result.band, 'overload'); assert.equal(result.dashed, true);
  assert.equal(result.colour, '#ba3437'); assert.equal(result.arrow, true);
});

test('fully tripped corridor is out, never healthy or carrying an arrow', () => {
  const result = corridorState({ flow_mw: 0, limit_mw: 0, loading_frac: 0, tripped: true }, edge);
  assert.equal(result.band, 'out'); assert.equal(result.unavailable, true);
  assert.equal(result.dashed, true); assert.equal(result.arrow, false);
});

test('reduced frames preserve measured loading without inventing a current limit', () => {
  const result = corridorState({ flow_mw: -100, loading_frac: .8, tripped: true }, edge);
  assert.equal(result.limitMW, null); assert.equal(result.nameplateMW, 6000);
  assert.equal(result.band, 'warning'); assert.equal(result.unavailable, false);
  assert.equal(result.arrow, true);
});

test('missing fields remain unknown, not zero or healthy', () => {
  const result = corridorState({}, edge);
  assert.equal(result.flowMW, null); assert.equal(result.loading, null);
  assert.equal(result.tripped, null); assert.equal(result.band, 'unknown');
  assert.equal(result.arrow, false);
  assert.notEqual(zoneColour(undefined), zoneColour(0));
  assert.notEqual(zoneColour(1), zoneColour(0));
  assert.equal(corridorState(null, null).band, 'unknown');
});

test('zero flow carries no arrow and zone colour saturates at the fixed 1000 MW scale', () => {
  assert.equal(corridorState({ flow_mw: 0, limit_mw: 1000, loading_frac: 0, tripped: false }, edge).arrow, false);
  assert.equal(zoneColour(1000), zoneColour(10000));
  assert.equal(zoneColour(NaN), zoneColour(undefined));
});

test('display tolerance distinguishes numerical residue from meaningful unserved demand', () => {
  assert.equal(zoneColour(1.8189894035458565e-12), zoneColour(0));
  assert.equal(zoneColour(.049999), zoneColour(0));
  assert.notEqual(zoneColour(.05), zoneColour(0));
  assert.notEqual(zoneColour(.1), zoneColour(0));
  assert.equal(unservedLabel(1.8189894035458565e-12), '<0.1 MW unmet');
  assert.equal(unservedLabel(.049999), '<0.1 MW unmet');
  assert.equal(unservedLabel(.05), '0.1 MW unmet');
  assert.equal(unservedLabel(0), '0 MW unmet');
  assert.equal(unservedLabel(null), 'Data unavailable');
});

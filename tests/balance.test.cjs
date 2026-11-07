const test = require('node:test');
const assert = require('node:assert/strict');
const { analyseRegion, analyseRegions } = require('../UI/balance.js');

const region = Object.freeze({ key: 'example', name: 'Example nation', generationTWh: 80, consumptionTWh: 100, year: 2024 });
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} is not close to ${expected}`);

test('annual balance distinguishes deficits, surpluses, and equal generation and use', () => {
  const deficit = analyseRegion(region);
  assert.equal(deficit.balanceTWh, -20);
  assert.equal(deficit.coveragePercent, 80);
  assert.equal(deficit.shortfallPercent, 20);
  assert.equal(deficit.status, 'annual-deficit');
  const surplus = analyseRegion({ ...region, generationTWh: 150 });
  assert.equal(surplus.balanceTWh, 50);
  assert.equal(surplus.coveragePercent, 150);
  assert.equal(surplus.shortfallPercent, 0);
  assert.equal(surplus.status, 'annual-surplus');
  const balanced = analyseRegion({ ...region, generationTWh: 100 });
  assert.equal(balanced.balanceTWh, 0);
  assert.equal(balanced.coveragePercent, 100);
  assert.equal(balanced.status, 'balanced');
});

test('missing generation or use remains unknown instead of becoming zero', () => {
  for (const field of ['generationTWh', 'consumptionTWh']) {
    for (const missing of [null, undefined]) {
      const result = analyseRegion({ ...region, [field]: missing });
      assert.equal(result[field], null);
      assert.equal(result.balanceTWh, null);
      assert.equal(result.coveragePercent, null);
      assert.equal(result.shortfallPercent, null);
      assert.equal(result.status, 'unknown');
    }
  }
});

test('zero use has a known balance and an unavailable ratio', () => {
  const result = analyseRegion({ ...region, consumptionTWh: 0 });
  assert.equal(result.balanceTWh, 80);
  assert.equal(result.coveragePercent, null);
  assert.equal(result.shortfallPercent, null);
  assert.equal(result.status, 'annual-surplus');
  const empty = analyseRegion({ key: 'empty', generationTWh: 0, consumptionTWh: 0 });
  assert.equal(empty.balanceTWh, 0);
  assert.equal(empty.status, 'balanced');
  const noGeneration = analyseRegion({ ...region, generationTWh: 0 });
  assert.equal(noGeneration.coveragePercent, 0);
  assert.equal(noGeneration.shortfallPercent, 100);
});

test('annual scenarios scale generation and demand independently without altering inputs', () => {
  const result = analyseRegion(region, { generationChangePercent: -25, demandChangePercent: 20 });
  assert.equal(result.generationTWh, 60);
  assert.equal(result.consumptionTWh, 120);
  assert.equal(result.balanceTWh, -60);
  assert.equal(result.coveragePercent, 50);
  assert.equal(result.shortfallPercent, 50);
  assert.equal(result.baselineGenerationTWh, 80);
  assert.equal(result.baselineConsumptionTWh, 100);
  assert.equal(result.year, 2024);
  assert.equal(region.generationTWh, 80);
  assert.equal(region.consumptionTWh, 100);
});

test('greater demand or lower generation cannot improve coverage or annual balance', () => {
  const baseline = analyseRegion(region);
  const higherDemand = analyseRegion(region, { demandChangePercent: 15 });
  const lowerGeneration = analyseRegion(region, { generationChangePercent: -15 });
  for (const result of [higherDemand, lowerGeneration]) {
    assert.ok(result.coveragePercent < baseline.coveragePercent);
    assert.ok(result.balanceTWh < baseline.balanceTWh);
    assert.ok(result.shortfallPercent > baseline.shortfallPercent);
  }
  close(higherDemand.coveragePercent, 80 / 115 * 100);
});

test('scenario endpoints handle removal of annual generation or demand', () => {
  const noGeneration = analyseRegion(region, { generationChangePercent: -100 });
  assert.equal(noGeneration.generationTWh, 0);
  assert.equal(noGeneration.coveragePercent, 0);
  const noDemand = analyseRegion(region, { demandChangePercent: -100 });
  assert.equal(noDemand.consumptionTWh, 0);
  assert.equal(noDemand.coveragePercent, null);
  assert.equal(noDemand.balanceTWh, 80);
  assert.equal(analyseRegion(region, { demandChangePercent: 100 }).consumptionTWh, 200);
});

test('region ranking uses coverage then balance with stable keys and unavailable ratios last', () => {
  const rows = Object.freeze([
    Object.freeze({ key: 'deficit', generationTWh: 50, consumptionTWh: 100 }),
    Object.freeze({ key: 'b', generationTWh: 150, consumptionTWh: 100 }),
    Object.freeze({ key: 'unknown' }),
    Object.freeze({ key: 'a', generationTWh: 150, consumptionTWh: 100 }),
    Object.freeze({ key: 'larger', generationTWh: 300, consumptionTWh: 200 }),
    Object.freeze({ key: 'zero-demand', generationTWh: 1000, consumptionTWh: 0 })
  ]);
  assert.deepEqual(analyseRegions(rows).map(row => row.key), ['larger', 'a', 'b', 'deficit', 'zero-demand', 'unknown']);
  assert.equal(rows[0].key, 'deficit');
  assert.deepEqual(analyseRegions([]), []);
});

test('invalid energy inputs and ambiguous duplicate nations fail explicitly', () => {
  for (const invalid of ['80', NaN, Infinity, -Infinity, true]) {
    assert.throws(() => analyseRegion({ ...region, generationTWh: invalid }), TypeError);
    assert.throws(() => analyseRegion({ ...region, consumptionTWh: invalid }), TypeError);
  }
  assert.throws(() => analyseRegion({ ...region, generationTWh: -1 }), RangeError);
  assert.throws(() => analyseRegion(null), TypeError);
  assert.throws(() => analyseRegion({ generationTWh: 80, consumptionTWh: 100 }), TypeError);
  assert.throws(() => analyseRegion({ key: ' ' }), TypeError);
  assert.throws(() => analyseRegions(null), TypeError);
  assert.throws(() => analyseRegions([region, region]), RangeError);
});

test('invalid scenarios and numeric overflow fail without emitting NaN or Infinity', () => {
  for (const field of ['demandChangePercent', 'generationChangePercent']) {
    for (const invalid of [null, NaN, Infinity, '20', true]) {
      assert.throws(() => analyseRegion(region, { [field]: invalid }), TypeError);
    }
    for (const outside of [-101, 101]) {
      assert.throws(() => analyseRegion(region, { [field]: outside }), RangeError);
    }
  }
  assert.throws(() => analyseRegion(region, null), TypeError);
  assert.throws(() => analyseRegion(region, []), TypeError);
  assert.throws(() => analyseRegion({ ...region, generationTWh: Number.MAX_VALUE }, { generationChangePercent: 100 }), RangeError);
  assert.throws(() => analyseRegion({ ...region, generationTWh: Number.MAX_VALUE, consumptionTWh: Number.MIN_VALUE }), RangeError);
});

test('browser build exposes the same immutable API as CommonJS', () => {
  const fs = require('node:fs');
  const vm = require('node:vm');
  const browser = {};
  vm.runInNewContext(fs.readFileSync(require.resolve('../UI/balance.js'), 'utf8'), browser);
  assert.equal(typeof browser.JMapBalance.analyseRegions, 'function');
  assert.equal(browser.JMapBalance.analyseRegion(region).balanceTWh, -20);
  assert.ok(Object.isFrozen(browser.JMapBalance));
});

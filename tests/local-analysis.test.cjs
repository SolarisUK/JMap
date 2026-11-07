const test = require('node:test');
const assert = require('node:assert/strict');
const A = require('../UI/local-analysis.js');
const data = require('../UI/assets/local-energy.js');

test('local summary weights household use by meters and separates capacity from consumption', () => {
  const rows = [
    { consumptionGWh: 3, domesticGWh: 1, nonDomesticGWh: 2, domesticMeters: 1000, renewableCapacityMW: 100 },
    { consumptionGWh: 4, domesticGWh: 3, nonDomesticGWh: 1, domesticMeters: 2000, renewableCapacityMW: 0 }
  ];
  const summary = A.summary(rows);
  assert.equal(summary.consumptionGWh, 7);
  assert.equal(summary.meanDomesticMWh, 4 / 3);
  assert.equal(summary.domesticShare, 4 / 7 * 100);
  assert.equal(summary.renewableCapacityMW, 100);
  assert.equal(summary.capacityKnownCount, 2);
  assert.equal(A.value({ meanDomesticKWh: 4000 }, 'perMeter'), 4);
});

test('unavailable use stays unknown even when renewable capacity is available', () => {
  const rows = data.areas.filter(row => row.nation === 'northern-ireland');
  const summary = A.summary(rows);
  assert.equal(summary.measuredCount, 0);
  assert.equal(summary.consumptionGWh, null);
  assert.equal(summary.domesticShare, null);
  assert.equal(summary.meanDomesticMWh, null);
  assert.ok(summary.renewableCapacityMW > 0);
  assert.equal(A.value({ renewableCapacityMW: 0 }, 'capacity'), 0);
  assert.equal(A.value({ renewableGWh: null }, 'renewable'), null);
  assert.equal(A.summary([]).consumptionGWh, null);
});

test('source-wide colour scales exclude unknowns and retain exact extreme values', () => {
  const demand = A.scale(data.areas, 'demand');
  assert.equal(demand.knownCount, 350);
  assert.ok(demand.max > 0 && demand.observedMax >= demand.max);
  const largest = data.areas.reduce((best, row) => (row.consumptionGWh ?? -1) > (best.consumptionGWh ?? -1) ? row : best);
  assert.equal(A.value(largest, 'demand'), demand.observedMax);
  assert.equal(A.scale(data.areas, 'renewable').knownCount, 40);
});

const test = require('node:test');
const assert = require('node:assert/strict');
const data = require('../UI/assets/regions.js');

test('official context covers all four nations in the same annual period', () => {
  assert.equal(data.year, 2025);
  assert.equal(data.published, '2026-09-29');
  assert.deepEqual(data.regions.map(row => row.key).sort(), ['england', 'northern-ireland', 'scotland', 'wales']);
  assert.ok(data.sources.every(source => /^https:\/\//.test(source.url)));
  data.regions.forEach(row => {
    assert.equal(row.year, data.year);
    ['generationTWh', 'consumptionTWh', 'finalConsumptionTWh', 'windTWh', 'solarTWh'].forEach(key => assert.ok(Number.isFinite(row[key]) && row[key] > 0));
    assert.equal(row.demandTWh, row.consumptionTWh);
    assert.ok(row.finalConsumptionTWh < row.consumptionTWh, 'Gross demand must include losses and own use.');
    assert.ok(row.windTWh + row.solarTWh <= row.renewableTWh);
    assert.ok(row.renewableTWh <= row.generationTWh);
  });
});

test('annual demand uses net transfers rather than mislabelling final-use differences as exports', () => {
  data.regions.forEach(row => {
    assert.ok(Math.abs((row.generationTWh - row.consumptionTWh) + row.netImportsTWh) < 1e-10);
    assert.notEqual(row.consumptionTWh, row.finalConsumptionTWh);
  });
  const sum = key => data.regions.reduce((total, row) => total + row[key], 0);
  assert.ok(Math.abs(sum('generationTWh') - 293.5618184) < 1e-8);
  assert.ok(Math.abs(sum('netImportsTWh') - 29.7297571) < 1e-8);
  assert.ok(Math.abs(sum('consumptionTWh') - 323.2915755) < 1e-8);
  assert.ok(data.regions.find(row => row.key === 'england').netImportsTWh > 0);
  assert.ok(data.regions.find(row => row.key === 'scotland').netImportsTWh < 0);
});

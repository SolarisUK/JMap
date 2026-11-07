const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const data = require('../UI/assets/local-energy.js');

test('local data covers 350 measured GB authorities and 11 explicitly missing NI districts', () => {
  assert.equal(data.year, 2024);
  assert.equal(data.geographyYear, 2025);
  assert.equal(data.areas.length, 361);
  assert.equal(new Set(data.areas.map(area => area.key)).size, 361);
  const expected = { england: 296, scotland: 32, wales: 22, 'northern-ireland': 11 };
  Object.entries(expected).forEach(([nation, count]) => assert.equal(data.areas.filter(area => area.nation === nation).length, count));
  data.areas.forEach(area => {
    assert.match(area.key, /^(?:E0[6-9]|W06|S12|N09)\d{6}$/);
    assert.ok(area.name && area.region);
    if (area.nation === 'northern-ireland') {
      ['consumptionGWh', 'domesticGWh', 'nonDomesticGWh', 'meters', 'meanDomesticKWh'].forEach(field => assert.equal(area[field], null));
    } else {
      ['consumptionGWh', 'domesticGWh', 'nonDomesticGWh', 'meanDomesticKWh', 'medianDomesticKWh'].forEach(field => assert.ok(Number.isFinite(area[field]) && area[field] >= 0));
      assert.ok(Number.isInteger(area.meters) && area.meters > 0);
      assert.equal(area.domesticMeters + area.nonDomesticMeters, area.meters);
      assert.ok(Math.abs(area.domesticGWh + area.nonDomesticGWh - area.consumptionGWh) < 1e-7);
      assert.ok(Math.abs(area.domesticGWh * 1e6 / area.domesticMeters - area.meanDomesticKWh) < 1e-6);
    }
  });
});

test('mapped totals reconcile to official GB consumption only after unallocated consumption is included', () => {
  const mapped = data.areas.reduce((sum, area) => sum + (area.consumptionGWh ?? 0), 0);
  assert.ok(Math.abs(mapped - data.totals.mappedConsumptionGWh) < 1e-7);
  assert.ok(Math.abs(mapped + data.totals.unallocatedConsumptionGWh - data.totals.gbConsumptionGWh) < 1e-7);
  assert.ok(data.totals.unallocatedConsumptionGWh > 0);
  const hartlepool = data.areas.find(area => area.key === 'E06000001');
  assert.equal(hartlepool.sourceRow, 25);
  assert.equal(hartlepool.consumptionGWh, 396.80636032779307);
  assert.equal(hartlepool.meters, 47797);
});

test('confidential renewable generation remains unknown rather than becoming a fabricated total', () => {
  assert.equal(data.coverage.renewableCapacityAreaCount, 359);
  assert.equal(data.areas.filter(area => area.renewableGWh !== null).length, data.coverage.completeRenewableGenerationAreaCount);
  data.areas.forEach(area => {
    if (area.renewableSourceRow === null) {
      ['renewableCapacityMW', 'reportedRenewableGWh', 'renewableGWh', 'renewableGenerationSuppressed'].forEach(field => assert.equal(area[field], null));
      return;
    }
    assert.ok(Number.isFinite(area.renewableCapacityMW) && area.renewableCapacityMW >= 0);
    assert.ok(Number.isFinite(area.reportedRenewableGWh) && area.reportedRenewableGWh >= 0);
    if (area.renewableGenerationSuppressed) assert.equal(area.renewableGWh, null);
    else assert.equal(area.renewableGWh, area.reportedRenewableGWh);
  });
  assert.ok(data.areas.filter(area => area.renewableGenerationSuppressed).length > 300);
});

test('changed boundaries remain unmatched instead of silently reassigning renewable values', () => {
  const unmatched = data.areas.filter(area => area.renewableSourceRow === null);
  assert.deepEqual(unmatched.map(area => area.key), ['E08000038', 'E08000039']);
  assert.deepEqual(unmatched.map(area => area.name), ['Barnsley', 'Sheffield']);
  unmatched.forEach(area => {
    assert.ok(area.consumptionGWh > 0);
    assert.equal(area.renewableCapacityMW, null);
  });
  assert.ok(!data.areas.some(area => ['E08000016', 'E08000019'].includes(area.key)));
});

test('the data works offline as a browser script with the same complete dataset', () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../UI/assets/local-energy.js'), 'utf8'), context);
  assert.equal(context.JMAP_LOCAL_ENERGY.areas.length, 361);
  assert.equal(context.JMAP_LOCAL_ENERGY.year, 2024);
  assert.ok(Object.isFrozen(context.JMAP_LOCAL_ENERGY.areas));
  assert.ok(data.sources.every(source => source.url.startsWith('https://')));
});

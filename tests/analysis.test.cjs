const test = require('node:test');
const assert = require('node:assert/strict');
const { summarise, aggregateByTechnology, aggregateByRegion } = require('../UI/analysis.js');

const sites = Object.freeze([
  { id: 'wind', type: 'wind', region: 'england', capacity: 1000, output: 250 },
  { id: 'gas', type: 'gas', region: 'england', capacity: 500, output: 400 },
  { id: 'nuclear', type: 'nuclear', region: 'scotland', capacity: 2000, output: 1800 },
  { id: 'battery', type: 'storage', region: 'wales', capacity: 100, output: 50 },
  { id: 'connector', type: 'interconnector', region: 'northern-ireland', capacity: 300, output: 210 },
  { id: 'biomass', type: 'biomass', region: 'wales', capacity: 200, output: 100 }
].map(Object.freeze));

function close(actual, expected) {
  assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} is not close to ${expected}`);
}

test('supplied power separates generation, storage discharge, and imports', () => {
  const summary = summarise(sites);
  assert.equal(summary.siteCount, 6);
  assert.equal(summary.capacity, 4100);
  assert.equal(summary.output, 2810);
  assert.equal(summary.generation, 2550);
  assert.equal(summary.storage, 50);
  assert.equal(summary.imports, 210);
  assert.equal(summary.output, summary.generation + summary.storage + summary.imports);
});

test('low-carbon share excludes storage, imports, and biomass from its numerator', () => {
  const summary = summarise(sites);
  assert.equal(summary.lowCarbon, 2050);
  close(summary.lowCarbonShare, 2050 / 2550 * 100);
  assert.equal(summarise(sites.filter(site => site.type === 'biomass')).lowCarbonShare, 0);
  assert.equal(summarise(sites.filter(site => site.type === 'interconnector')).lowCarbonShare, null);
});

test('utilisation is weighted by capacity rather than averaged across sites', () => {
  const summary = summarise(sites);
  close(summary.utilisation, 2810 / 4100 * 100);
  const simpleMean = sites.reduce((sum, site) => sum + site.output / site.capacity * 100, 0) / sites.length;
  assert.notEqual(summary.utilisation, simpleMean);
});

test('technology groups sort by output, preserve original records, and sum to the portfolio', () => {
  const before = sites.map(site => site.id);
  const groups = aggregateByTechnology(sites);
  assert.deepEqual(groups.map(group => group.key), ['nuclear', 'gas', 'wind', 'interconnector', 'biomass', 'storage']);
  assert.deepEqual(sites.map(site => site.id), before);
  assert.equal(groups.reduce((sum, group) => sum + group.output, 0), summarise(sites).output);
  assert.equal(groups.reduce((sum, group) => sum + group.capacity, 0), summarise(sites).capacity);
  close(groups.reduce((sum, group) => sum + group.share, 0), 100);
  close(groups.find(group => group.key === 'wind').share, 250 / 2810 * 100);
});

test('regional groups include all four nations and additive summaries after filtering', () => {
  const filtered = sites.filter(site => site.region !== 'england');
  const regions = aggregateByRegion(filtered);
  assert.deepEqual(regions.map(region => region.key), ['scotland', 'northern-ireland', 'wales', 'england']);
  const emptyEngland = regions.find(region => region.key === 'england');
  assert.equal(emptyEngland.siteCount, 0);
  assert.equal(emptyEngland.share, 0);
  assert.equal(emptyEngland.lowCarbonShare, null);
  const totals = summarise(filtered);
  for (const field of ['siteCount', 'capacity', 'output', 'generation', 'storage', 'imports', 'lowCarbon']) {
    assert.equal(regions.reduce((sum, region) => sum + region[field], 0), totals[field]);
  }
  close(regions.reduce((sum, region) => sum + region.share, 0), 100);
});

test('empty and zero-output portfolios distinguish no denominator from zero utilisation', () => {
  const empty = summarise([]);
  assert.equal(empty.output, 0);
  assert.equal(empty.utilisation, null);
  assert.equal(empty.lowCarbonShare, null);
  assert.deepEqual(aggregateByTechnology([]), []);
  assert.equal(aggregateByRegion([]).length, 4);
  assert.ok(aggregateByRegion([]).every(region => region.share === 0));
  const zero = [{ type: 'wind', region: 'england', capacity: 100, output: 0 }];
  assert.equal(summarise(zero).utilisation, 0);
  assert.equal(aggregateByTechnology(zero)[0].share, 0);
});

test('region dictionaries work and unassigned geography never silently drops output', () => {
  const extra = [{ type: 'wind', capacity: 20, output: 10 }];
  const rows = aggregateByRegion(extra, { england: 'England', scotland: 'Scotland' });
  assert.equal(rows.find(row => row.key === 'unknown').output, 10);
  assert.equal(rows.length, 3);
  assert.equal(rows.reduce((sum, row) => sum + row.output, 0), 10);
});

test('invalid telemetry fails explicitly without converting missing fields to NaN', () => {
  for (const bad of [undefined, null, '20', NaN, Infinity]) {
    assert.throws(() => summarise([{ type: 'wind', capacity: 100, output: bad }]), TypeError);
    assert.throws(() => aggregateByTechnology([{ type: 'wind', capacity: bad, output: 10 }]), TypeError);
  }
  assert.throws(() => aggregateByRegion([{ type: 'wind', capacity: 100, output: -1 }]), RangeError);
  assert.throws(() => summarise(null), TypeError);
  assert.throws(() => summarise([null]), TypeError);
  assert.throws(() => summarise([{ capacity: 10, output: 1 }]), TypeError);
  assert.throws(() => summarise([
    { type: 'gas', capacity: Number.MAX_VALUE, output: 1 },
    { type: 'gas', capacity: Number.MAX_VALUE, output: 1 }
  ]), RangeError);
});

'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { aggregateRegions, REFERENCE_CAPACITY_MW, referenceCapacityMW } = require('../generation-overview.js');
const catalogue = require('../assets/generation-sites.js');
const near = (actual, expected, tolerance = 1e-7) => assert.ok(Math.abs(actual - expected) < tolerance, `${actual} != ${expected}`);

test('source aliases merge into stable named groups and include storage capacity', () => {
  const sites = [
    { id: 'a', region: 'Eastern', capacityMW: 120, type: 'gas', lat: 52, lon: 0 },
    { id: 'b', region: 'East of England', capacityMW: 80, type: 'storage', lat: 53, lon: 1 },
    { id: 'c', region: 'Yorkshire and Humber', capacityMW: 30 },
    { id: 'd', region: 'Yorkshire and the Humber', capacityMW: 10 }
  ];
  sites.forEach(Object.freeze); Object.freeze(sites);
  const groups = aggregateRegions(sites);
  assert.deepEqual(groups.map(group => group.id), ['east-of-england', 'yorkshire-and-the-humber']);
  assert.equal(groups[0].name, 'East of England');
  assert.equal(groups[0].capacityMW, 200);
  assert.equal(groups[0].knownCapacityMW, 200);
  assert.equal(groups[0].siteCount, 2);
  assert.equal(groups[0].sites[0], sites[0]);
  assert.equal(groups[0].sites[1], sites[1]);
  near(groups[0].lat, 52.4);
  near(groups[0].lon, .4);
  assert.equal(groups[1].capacityMW, 40);
  assert.equal(groups[1].lat, null);
  assert.equal(groups[1].lon, null);
});

test('unknown capacities remain unknown while known values are accounted for', () => {
  const group = aggregateRegions([
    { region: 'Scotland', capacityMW: 100, lat: 56, lon: -4 },
    { region: 'Scotland', capacityMW: null, lat: 58, lon: -3 },
    { region: 'Scotland', capacityMW: '30', lat: 57, lon: -2 },
    { region: 'Scotland', capacityMW: -10 },
    { region: 'Scotland', capacityMW: Number.NaN }
  ])[0];
  assert.equal(group.capacityMW, null);
  assert.equal(group.knownCapacityMW, 100);
  assert.equal(group.knownCapacityCount, 1);
  assert.equal(group.unknownCapacityCount, 4);
  assert.equal(group.lat, 56);
  assert.equal(group.lon, -4);
  const unknown = aggregateRegions([{ region: 'Wales', lat: 51, lon: -3 }, { region: 'Wales', lat: 53, lon: -5 }])[0];
  assert.equal(unknown.capacityMW, null);
  assert.equal(unknown.knownCapacityMW, null);
  assert.equal(unknown.lat, 52);
  assert.equal(unknown.lon, -4);
});

test('zero capacity is observed zero and invalid coordinates do not invent a location', () => {
  const [group] = aggregateRegions([
    { region: 'London', capacityMW: 0, lat: 51.5, lon: -.1 },
    { region: 'London', capacityMW: 0, lat: 51.7, lon: .1 },
    { region: 'London', capacityMW: 0, lat: 900, lon: 0 }
  ]);
  assert.equal(group.capacityMW, 0);
  assert.equal(group.unknownCapacityCount, 0);
  near(group.lat, 51.6);
  near(group.lon, 0);
  const [missing] = aggregateRegions([{ region: 'North East', capacityMW: 20, lat: null, lon: null }]);
  assert.equal(missing.lat, null);
  assert.equal(missing.lon, null);
});

test('offshore is explicitly UK-wide and unknown source regions conserve records', () => {
  const source = [
    { region: 'Offshore', country: 'England', capacityMW: 100, lat: 54, lon: 2 },
    { region: 'Offshore', country: 'Scotland', capacityMW: 300, lat: 58, lon: -1 },
    { region: 'Unpublished district', country: 'England', capacityMW: 5 },
    { capacityMW: 7 }
  ];
  const [offshore, unassigned] = aggregateRegions(source);
  assert.equal(offshore.id, 'offshore');
  assert.equal(offshore.name, 'Offshore sites');
  assert.equal(offshore.country, 'United Kingdom');
  assert.equal(offshore.isOffshore, true);
  assert.match(offshore.note, /UK-wide/);
  near(offshore.lat, 57);
  near(offshore.lon, -.25);
  assert.equal(unassigned.id, 'unassigned');
  assert.equal(unassigned.country, null);
  assert.equal(unassigned.siteCount, 2);
  assert.equal(unassigned.capacityMW, 12);
  assert.equal(aggregateRegions(source).reduce((sum, group) => sum + group.siteCount, 0), source.length);
});

test('the published catalogue forms 13 groups, conserving every record and MW', () => {
  const groups = aggregateRegions(catalogue.sites);
  assert.equal(groups.length, 13);
  assert.equal(new Set(groups.map(group => group.id)).size, 13);
  assert.ok(groups.every(group => group.capacityMW > 0 && group.unknownCapacityCount === 0));
  assert.equal(groups.reduce((sum, group) => sum + group.siteCount, 0), catalogue.sites.length);
  const inputIds = catalogue.sites.map(site => site.id).sort();
  const groupedIds = groups.flatMap(group => group.sites.map(site => site.id)).sort();
  assert.deepEqual(groupedIds, inputIds);
  near(groups.reduce((sum, group) => sum + group.capacityMW, 0), catalogue.sites.reduce((sum, site) => sum + site.capacityMW, 0));
  const offshore = groups.find(group => group.id === 'offshore');
  assert.equal(offshore.siteCount, 55);
  assert.equal(groups.find(group => group.id === 'east-of-england').siteCount, 339);
  assert.equal(groups.find(group => group.id === 'yorkshire-and-the-humber').siteCount, 175);
  assert.ok(groups.every(group => Number.isFinite(group.lat) && Number.isFinite(group.lon)));
  assert.ok(Math.max(...groups.map(group => group.capacityMW)) < REFERENCE_CAPACITY_MW);
  assert.equal(referenceCapacityMW, REFERENCE_CAPACITY_MW);
});

test('filters preserve canonical IDs and input ordering cannot change group order', () => {
  const full = aggregateRegions(catalogue.sites);
  const subset = aggregateRegions(catalogue.sites.filter(site => site.country === 'Scotland'));
  assert.deepEqual(subset.map(group => group.id), ['scotland', 'offshore']);
  assert.ok(subset.every(group => full.some(original => original.id === group.id)));
  const reversed = aggregateRegions([...catalogue.sites].reverse());
  assert.deepEqual(reversed.map(group => group.id), full.map(group => group.id));
  for (const group of reversed) {
    const expected = full.find(item => item.id === group.id);
    near(group.capacityMW, expected.capacityMW);
    near(group.lat, expected.lat);
    near(group.lon, expected.lon);
  }
});

test('empty input has no invented groups and invalid record collections fail explicitly', () => {
  assert.deepEqual(aggregateRegions([]), []);
  assert.throws(() => aggregateRegions(null), TypeError);
  assert.throws(() => aggregateRegions([null]), TypeError);
  assert.throws(() => aggregateRegions([[]]), TypeError);
});

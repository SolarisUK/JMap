const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const vm = require('node:vm');
const catalog = require('../assets/generation-sites.js');

const countries = new Set(['England', 'Scotland', 'Wales', 'Northern Ireland']);
const technologies = new Set(['wind_onshore', 'wind_offshore', 'solar', 'hydro', 'biomass', 'waste', 'gas', 'nuclear', 'storage', 'other']);
const countBy = key => catalog.sites.reduce((counts, site) => {
  counts[site[key]] = (counts[site[key]] || 0) + 1;
  return counts;
}, {});

test('official catalogue contains thousands of uniquely identified operational assets with valid published capacities and locations', () => {
  assert.ok(catalog.sites.length > 3000);
  assert.equal(new Set(catalog.sites.map(site => site.id)).size, catalog.sites.length);
  catalog.sites.forEach(site => {
    assert.equal(site.status, 'Operational', `${site.id}: only published operational records belong on this map`);
    assert.ok(site.name.trim() && site.operator.trim());
    assert.ok(technologies.has(site.type), `${site.id}: unknown technology ${site.type}`);
    assert.ok(countries.has(site.country));
    assert.ok(Number.isFinite(site.capacityMW) && site.capacityMW > 0, `${site.id}: capacity must be a known positive MW value`);
    assert.ok(Number.isFinite(site.lat) && site.lat >= 49 && site.lat <= 61.5, `${site.id}: latitude outside UK/offshore bounds`);
    assert.ok(Number.isFinite(site.lon) && site.lon >= -11 && site.lon <= 5, `${site.id}: longitude outside UK/offshore bounds`);
    assert.ok(site.sourceId && Number.isInteger(site.sourceRow) && site.sourceRow > 0);
    assert.ok(site.originalTechnology);
    assert.match(site.sourceDate, /^\d{4}-\d{2}-\d{2}$/);
    assert.match(site.sourceUrl, /^https:\/\/www\.gov\.uk\//);
  });
});

test('capacity records contain no invented output, current power or capacity-factor fields', () => {
  assert.equal(catalog.coverage.outputAvailable, false);
  assert.equal(catalog.coverage.bmUnitMatchesAvailable, false);
  const inventedFields = ['output', 'outputMW', 'output_mw', 'generationMW', 'generation_mw', 'currentMW', 'current_mw', 'currentOutput', 'utilisation', 'capacityFactor', 'bmUnit', 'elexonBmUnit'];
  catalog.sites.forEach(site => inventedFields.forEach(field => {
    assert.equal(Object.hasOwn(site, field), false, `${site.id}: ${field} would imply unverified output or a BM-unit linkage`);
  }));
});

test('provenance uses the retained original REPD and DUKES publications with matching SHA-256 hashes', () => {
  assert.deepEqual(catalog.sources.map(source => source.id).sort(), ['DUKES', 'REPD']);
  const sourceFiles = {
    REPD: 'REPD_Publication_Q2_2026.csv',
    DUKES: 'DUKES_5.11_2026.xlsx'
  };
  catalog.sources.forEach(source => {
    const bytes = fs.readFileSync(path.join(__dirname, '../data/raw', sourceFiles[source.id]));
    assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), source.sha256, `${source.id}: retained raw source changed`);
    assert.match(source.downloadUrl, /^https:\/\/assets\.publishing\.service\.gov\.uk\//);
    assert.match(source.url, /^https:\/\/www\.gov\.uk\//);
    assert.match(source.published, /^\d{4}-\d{2}-\d{2}$/);
    assert.ok(source.period);
  });
  const sources = new Map(catalog.sources.map(source => [source.id, source]));
  catalog.sites.forEach(site => {
    const source = sources.get(site.source);
    assert.ok(source, `${site.id}: source must be a declared official publication`);
    assert.equal(site.sourceDate, source.published);
    assert.equal(site.sourceUrl, source.url);
    if (site.source === 'REPD') assert.equal(site.id, `repd-${site.sourceId}`);
    else {
      assert.equal(site.sourceSheet, '5.11 Full list');
      assert.ok(site.originalTechnology.startsWith('Fossil Fuel /') || site.originalTechnology.startsWith('Nuclear /'));
    }
  });
});

test('included source counts, exclusions, countries and technologies reconcile without counting planned projects', () => {
  const coverage = catalog.coverage;
  assert.equal(coverage.siteCount, catalog.sites.length);
  const sourceCounts = countBy('source');
  assert.equal(sourceCounts.REPD, coverage.REPD.included);
  assert.equal(sourceCounts.DUKES, coverage.DUKES.included);
  assert.equal(coverage.REPD.included + coverage.DUKES.included, catalog.sites.length);
  assert.deepEqual(countBy('country'), coverage.byCountry);
  assert.deepEqual(countBy('type'), coverage.byType);
  const repdExcluded = coverage.REPD.excluded;
  const invalidOperational = Object.entries(repdExcluded).filter(([reason]) => reason !== 'notOperational').reduce((sum, [, count]) => sum + count, 0);
  assert.equal(coverage.REPD.included + invalidOperational, coverage.REPD.sourceOperationalRecords);
  assert.equal(coverage.REPD.sourceOperationalRecords + repdExcluded.notOperational, coverage.REPD.sourceRecords);
  assert.ok(repdExcluded.notOperational > 0, 'Planned, cancelled and decommissioned records must have been excluded.');
  const rejectedConventional = Object.entries(coverage.DUKES.excluded).filter(([reason]) => reason !== 'renewableOrStorageAlreadyCoveredByREPD').reduce((sum, [, count]) => sum + count, 0);
  assert.equal(coverage.DUKES.included + rejectedConventional, coverage.DUKES.conventionalCandidates);
  assert.ok(coverage.DUKES.excluded.renewableOrStorageAlreadyCoveredByREPD > 0, 'Renewable DUKES records must not duplicate REPD capacity.');
});

test('all five published nuclear stations and correctly projected Northern Ireland conventional stations are present', () => {
  const nuclear = catalog.sites.filter(site => site.type === 'nuclear');
  assert.deepEqual(nuclear.map(site => site.name).sort(), ['Hartlepool', 'Heysham 1', 'Heysham 2', 'Sizewell B', 'Torness']);
  assert.ok(nuclear.every(site => site.source === 'DUKES'));
  assert.equal(nuclear.find(site => site.name === 'Torness').country, 'Scotland');
  const ballylumford = catalog.sites.find(site => site.name === 'EP Ballylumford CCGT');
  assert.ok(ballylumford);
  assert.equal(ballylumford.country, 'Northern Ireland');
  assert.equal(ballylumford.type, 'gas');
  assert.ok(Math.abs(ballylumford.lat - 54.845) < .01);
  assert.ok(Math.abs(ballylumford.lon - (-5.787)) < .01);
  assert.match(ballylumford.coordinateSource, /EPSG:27700/);
  const oil = catalog.sites.filter(site => site.source === 'DUKES' && site.originalTechnology.includes('Diesel/Gas Oil'));
  assert.ok(oil.length > 0);
  assert.ok(oil.every(site => site.type === 'other'), 'Oil-fired units must not be relabelled as natural gas.');
});

test('the bundled data loads directly as a browser global and retains correct source text encoding', () => {
  const source = fs.readFileSync(path.join(__dirname, '../assets/generation-sites.js'), 'utf8');
  const context = vm.createContext({});
  vm.runInContext(source, context);
  assert.equal(context.JMAP_GENERATION_SITES.sites.length, catalog.sites.length);
  assert.ok(Object.isFrozen(context.JMAP_GENERATION_SITES.sites));
  assert.equal(source.includes('\uFFFD'), false, 'Source names must not contain decoding replacement characters.');
  assert.ok(catalog.asOf && catalog.asOfLabel);
  assert.ok(catalog.coverage.notes.some(note => note.includes('not a live')));
});

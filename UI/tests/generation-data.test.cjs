const test = require('node:test');
const assert = require('node:assert/strict');
const D = require('../generation-data.js');

const sites = Object.freeze([
  Object.freeze({ id: 'a', name: 'Gwynt y Môr', type: 'wind_offshore', capacityMW: 576, country: 'Wales', operator: 'RWE', status: 'Operational' }),
  Object.freeze({ id: 'b', name: 'Highland Wind', type: 'wind_onshore', capacityMW: 150, country: 'Scotland', operator: 'Example operator', status: 'Operational' }),
  Object.freeze({ id: 'c', name: 'Unspecified Solar', type: 'solar', capacityMW: null, country: 'England', operator: null, status: 'Operational' }),
  Object.freeze({ id: 'd', name: 'Measured-zero capacity', type: 'solar', capacityMW: 0, country: 'England', status: 'Operational' })
]);

test('catalogue filters combine human-readable technology, accent-insensitive query and country without mutating rows', () => {
  assert.deepEqual(D.filterSites(sites, { query: 'gwynt mor rwe' }).map(site => site.id), ['a']);
  assert.deepEqual(D.filterSites(sites, { query: 'offshore wind', country: 'WALES', type: 'wind_offshore' }).map(site => site.id), ['a']);
  assert.deepEqual(D.filterSites(sites, { query: 'wind', country: 'Scotland' }).map(site => site.id), ['b']);
  assert.deepEqual(D.filterSites(sites, { country: 'England', type: 'wind_onshore' }), []);
  assert.equal(D.filterSites(sites)[0], sites[0]);
  assert.equal(sites[0].name, 'Gwynt y Môr');
});

test('catalogue summaries distinguish known capacity, unknown capacity and unavailable output', () => {
  assert.deepEqual(D.summarizeSites(sites), { count: 4, capacityKnownSumMW: 726, capacityKnownCount: 3, capacityUnknownCount: 1 });
  assert.deepEqual(D.summarizeSites([]), { count: 0, capacityKnownSumMW: 0, capacityKnownCount: 0, capacityUnknownCount: 0 });
  const unknown = D.summarizeSites([{ capacityMW: '100' }, { capacityMW: -10 }, { capacityMW: Infinity }, {}]);
  assert.equal(unknown.capacityUnknownCount, 4);
  assert.equal(unknown.capacityKnownSumMW, 0);
  assert.ok(!Object.hasOwn(D.summarizeSites(sites), 'outputMW'), 'Capacity must never become invented output');
  assert.ok(sites.every(site => !Object.hasOwn(site, 'outputMW')));
});

test('technology aggregation reconciles counts and known capacity while retaining unknown groups', () => {
  const rows = D.aggregateByType([...sites, { id: 'missing-type', capacityMW: null }]);
  assert.deepEqual(rows.map(row => row.type), ['wind_offshore', 'wind_onshore', 'solar', 'unknown']);
  assert.equal(rows.reduce((sum, row) => sum + row.count, 0), 5);
  assert.equal(rows.reduce((sum, row) => sum + row.capacityKnownSumMW, 0), 726);
  assert.equal(rows.find(row => row.type === 'solar').capacityUnknownCount, 1);
  assert.equal(D.TYPE_LABELS.wind_offshore, 'Offshore wind');
  assert.throws(() => D.filterSites(null), TypeError);
  assert.throws(() => D.summarizeSites([null]), TypeError);
});

const startTime = '2026-11-07T17:10:00Z';
const publishTime = '2026-11-07T17:15:00Z';
const now = Date.parse('2026-11-07T17:18:00Z');
const row = (fuelType, generation, extra = {}) => ({ dataset: 'FUELINST', fuelType, generation, startTime, publishTime, ...extra });
const allRows = () => [...D.FUELS.map(fuel => row(fuel.code, 100)), ...D.INTERCONNECTOR_CODES.map((code, index) => row(code, index % 2 ? -100 : 200))];

test('national fuel output and signed interconnector transfers remain separate coherent measurements', () => {
  const snapshot = D.parseNationalSnapshot({ data: allRows() }, now);
  assert.equal(snapshot.complete, true);
  assert.equal(snapshot.generationComplete, true);
  assert.equal(snapshot.transfersComplete, true);
  assert.equal(snapshot.generationMW, 1000);
  assert.equal(snapshot.netDomesticMW, 1000);
  assert.equal(snapshot.importsMW, 1000);
  assert.equal(snapshot.exportsMW, 500);
  assert.equal(snapshot.netImportsMW, 500);
  assert.equal(snapshot.storageDischargeMW, 100);
  assert.equal(snapshot.mix.length, 10);
  assert.ok(snapshot.mix.every(fuel => !fuel.code.startsWith('INT')));
  assert.equal(snapshot.interconnectors.find(link => link.code === 'INTGRNL').mw, -100);
  assert.ok(!Object.hasOwn(snapshot, 'demandMW'));
  assert.match(snapshot.coverage, /not UK demand/);
});

test('negative pumped storage and other fuel observations retain absorption instead of becoming output', () => {
  const records = allRows().map(value => value.fuelType === 'PS' ? { ...value, generation: -50 } : value.fuelType === 'OTHER' ? { ...value, generation: -20 } : value);
  const snapshot = D.parseNationalSnapshot({ data: records }, now);
  assert.equal(snapshot.mix.find(fuel => fuel.code === 'PS').mw, -50);
  assert.equal(snapshot.mix.find(fuel => fuel.code === 'OTHER').mw, -20);
  assert.equal(snapshot.generationMW, 800);
  assert.equal(snapshot.netDomesticMW, 730);
  assert.equal(snapshot.storageDischargeMW, 0);
  assert.equal(snapshot.storageChargingMW, 50);
  assert.deepEqual(snapshot.negativeDomesticCodes, ['PS', 'OTHER']);
  assert.equal(snapshot.complete, true);
});

test('a partial latest interval never borrows older fuels or transfers to manufacture completeness', () => {
  const snapshot = D.parseNationalSnapshot({ data: [
    ...allRows().map(value => ({ ...value, startTime: '2026-11-07T17:05:00Z' })), row('CCGT', 50)
  ] }, now);
  assert.equal(snapshot.startTime, '2026-11-07T17:10:00.000Z');
  assert.equal(snapshot.measuredFuelCount, 1);
  assert.equal(snapshot.knownGenerationMW, 50);
  assert.equal(snapshot.generationMW, null);
  assert.equal(snapshot.netDomesticMW, null);
  assert.equal(snapshot.netImportsMW, null);
  assert.equal(snapshot.mix.find(fuel => fuel.code === 'WIND').mw, null);
  assert.equal(snapshot.missingFuelCodes.length, 9);
  assert.equal(snapshot.missingInterconnectorCodes.length, 10);
  assert.equal(snapshot.complete, false);
});

test('latest publication revisions win, including missing newer values and conflicting revisions', () => {
  const revised = D.parseNationalSnapshot({ data: [...allRows(), row('CCGT', 250, { publishTime: '2026-11-07T17:16:00Z' })] }, now);
  assert.equal(revised.generationMW, 1150);
  assert.equal(revised.publishTime, '2026-11-07T17:16:00.000Z');
  const missing = D.parseNationalSnapshot({ data: [...allRows(), row('CCGT', null, { publishTime: '2026-11-07T17:16:00Z' })] }, now);
  assert.equal(missing.generationMW, null);
  assert.equal(missing.mix.find(fuel => fuel.code === 'CCGT').mw, null);
  const conflict = D.parseNationalSnapshot({ data: [...allRows(), row('CCGT', 250)] }, now);
  assert.deepEqual(conflict.conflictingCodes, ['CCGT']);
  assert.equal(conflict.generationMW, null);
  assert.equal(D.parseNationalSnapshot({ data: [...allRows(), row('CCGT', 100)] }, now).complete, true);
});

test('missing observations do not become zero and partial transfer coverage does not invalidate known generation', () => {
  const records = allRows().filter(value => value.fuelType !== 'INTNSL').map(value => value.fuelType === 'COAL' ? { ...value, generation: 0 } : value);
  const snapshot = D.parseNationalSnapshot({ data: records }, now);
  assert.equal(snapshot.mix.find(fuel => fuel.code === 'COAL').mw, 0);
  assert.equal(snapshot.measuredFuelCount, 10);
  assert.equal(snapshot.generationMW, 900);
  assert.equal(snapshot.generationComplete, true);
  assert.equal(snapshot.transfersComplete, false);
  assert.equal(snapshot.importsMW, null);
  assert.equal(snapshot.netImportsMW, null);
  assert.deepEqual(snapshot.missingInterconnectorCodes, ['INTNSL']);
  assert.equal(snapshot.knownImportsMW, 1000);
  assert.equal(snapshot.knownExportsMW, 400);
});

test('new unsupported fuel or interconnector codes explicitly prevent false complete totals', () => {
  const fuel = D.parseNationalSnapshot({ data: [...allRows(), row('NEWFUEL', 50)] }, now);
  assert.deepEqual(fuel.unknownCodes, ['NEWFUEL']);
  assert.equal(fuel.generationComplete, false);
  assert.equal(fuel.generationMW, null);
  assert.equal(fuel.knownGenerationMW, 1000);
  const connector = D.parseNationalSnapshot({ data: [...allRows(), row('INTNEW', -50)] }, now);
  assert.equal(connector.generationComplete, true);
  assert.equal(connector.transfersComplete, false);
  assert.equal(connector.netImportsMW, null);
});

test('malformed, empty and future intervals fail without a synthetic fallback', () => {
  assert.throws(() => D.parseNationalSnapshot({ rows: [] }, now), /unexpected/);
  assert.throws(() => D.parseNationalSnapshot({ data: [] }, now), /No national/);
  assert.throws(() => D.parseNationalSnapshot({ data: [row('CCGT', 100, { startTime: '2026-11-07T18:00:00Z' })] }, now), /future observation/);
  const invalid = D.parseNationalSnapshot({ data: allRows().map(value => value.fuelType === 'CCGT' ? { ...value, generation: '100' } : value) }, now);
  assert.equal(invalid.mix.find(fuel => fuel.code === 'CCGT').mw, null);
  assert.equal(invalid.generationMW, null);
});

test('freshness uses the end of the five-minute sample and explicitly marks unavailable timestamps', () => {
  const snapshot = D.parseNationalSnapshot({ data: allRows() }, now);
  assert.deepEqual(D.freshness(snapshot, now), { state: 'fresh', ageMinutes: 3 });
  assert.equal(D.freshness(snapshot, now + 20*60000).state, 'stale');
  assert.deepEqual(D.freshness({ endTime: 'invalid' }, now), { state: 'unavailable', ageMinutes: null });
  assert.deepEqual(D.freshness(null, now), { state: 'unavailable', ageMinutes: null });
});

test('live request uses a bounded one-hour public CORS request without credentials or error substitution', async () => {
  const url = new URL(D.buildNationalUrl(now));
  assert.match(url.pathname, /datasets\/FUELINST$/);
  assert.equal(Date.parse(url.searchParams.get('publishDateTimeTo')) - Date.parse(url.searchParams.get('publishDateTimeFrom')), 3600000);
  let request;
  const controller = new AbortController();
  const snapshot = await D.fetchNationalSnapshot({ now, signal: controller.signal, fetchImpl: async (address, options) => {
    request = { address, options }; return { ok: true, json: async () => ({ data: allRows() }) };
  } });
  assert.equal(snapshot.generationMW, 1000);
  assert.equal(request.options.mode, 'cors');
  assert.equal(request.options.credentials, 'omit');
  assert.equal(request.options.signal, controller.signal);
  await assert.rejects(() => D.fetchNationalSnapshot({ now, fetchImpl: async () => ({ ok: false, status: 503 }) }), /HTTP 503/);
  await assert.rejects(() => D.fetchNationalSnapshot({ now, fetchImpl: async () => { throw new Error('network blocked'); } }), /network blocked/);
  assert.throws(() => D.buildNationalUrl(null), TypeError);
});

test('browser catalogue helpers expose the same frozen API without needing a backend', () => {
  const fs = require('node:fs'), vm = require('node:vm');
  const browser = {};
  vm.runInNewContext(fs.readFileSync(require.resolve('../generation-data.js'), 'utf8'), browser);
  assert.ok(Object.isFrozen(browser.JMapGenerationData));
  assert.equal(browser.JMapGenerationData.summarizeSites(sites).capacityKnownSumMW, 726);
});

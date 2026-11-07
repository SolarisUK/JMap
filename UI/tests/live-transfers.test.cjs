const test = require('node:test');
const assert = require('node:assert/strict');
const D = require('../live-transfers.js');

const startTime = '2026-11-07T16:05:00Z';
const publishTime = '2026-11-07T16:10:00Z';
const now = Date.parse('2026-11-07T16:13:00Z');
function row(fuelType, generation, overrides = {}) {
  return { dataset: 'FUELINST', fuelType, generation, startTime, publishTime, ...overrides };
}
function allRows() { return D.LINKS.map((link, index) => row(link.id, index % 2 ? -100 : 200)); }

test('all ten verified codes include Greenlink and retain signed import/export flows', () => {
  assert.equal(D.LINKS.length, 10);
  assert.ok(D.LINKS.some(link => link.id === 'INTGRNL' && link.name === 'Greenlink'));
  const snapshot = D.parseSnapshot({ data: allRows() }, now);
  assert.equal(snapshot.measuredCount, 10);
  assert.equal(snapshot.complete, true);
  assert.equal(snapshot.importsMw, 1000);
  assert.equal(snapshot.exportsMw, 500);
  assert.equal(snapshot.netImportsMw, 500);
  assert.equal(snapshot.links.find(link => link.id === 'INTIFA2').direction, 'export');
  assert.equal(snapshot.links.find(link => link.id === 'INTIFA2').mw, -100);
  assert.equal(snapshot.links.find(link => link.id === 'INTIFA2').absoluteMw, 100);
});

test('a partial newest interval never borrows older link values to complete totals', () => {
  const snapshot = D.parseSnapshot({ data: [
    ...allRows().map(value => ({ ...value, startTime: '2026-11-07T16:00:00Z' })),
    row('INTNSL', 1400)
  ] }, now);
  assert.equal(snapshot.measuredCount, 1);
  assert.equal(snapshot.complete, false);
  assert.equal(snapshot.importsMw, 1400);
  assert.equal(snapshot.links.find(link => link.id === 'INTGRNL').mw, null);
  assert.equal(snapshot.links.find(link => link.id === 'INTGRNL').direction, 'unknown');
});

test('true measured zero remains distinct from null, strings and missing observations', () => {
  const snapshot = D.parseSnapshot({ data: [row('INTNSL', 0), row('INTFR', null), row('INTELEC', '123')] }, now);
  assert.equal(snapshot.links.find(link => link.id === 'INTNSL').direction, 'idle');
  assert.equal(snapshot.links.find(link => link.id === 'INTFR').mw, null);
  assert.equal(snapshot.links.find(link => link.id === 'INTELEC').mw, null);
  assert.equal(snapshot.measuredCount, 1);
  assert.equal(snapshot.netImportsMw, 0);
  const empty = D.parseSnapshot({ data: [row('INTNSL', null)] }, now);
  assert.equal(empty.measuredCount, 0);
  assert.equal(empty.netImportsMw, null);
  assert.equal(empty.importsMw, null);
  assert.equal(empty.exportsMw, null);
});

test('the latest publication revision wins without filling invalid revisions from older records', () => {
  const snapshot = D.parseSnapshot({ data: [row('INTFR', 100), row('INTFR', -240, { publishTime: '2026-11-07T16:11:00Z' })] }, now);
  assert.equal(snapshot.links.find(link => link.id === 'INTFR').mw, -240);
  const missing = D.parseSnapshot({ data: [row('INTFR', 100), row('INTFR', null, { publishTime: '2026-11-07T16:11:00Z' })] }, now);
  assert.equal(missing.links.find(link => link.id === 'INTFR').mw, null);
});

test('unmapped interconnector codes mark coverage incomplete instead of silently claiming complete totals', () => {
  const snapshot = D.parseSnapshot({ data: [...allRows(), row('INTNEW', 50)] }, now);
  assert.deepEqual(snapshot.unmappedCodes, ['INTNEW']);
  assert.equal(snapshot.complete, false);
  assert.equal(snapshot.measuredCount, 10);
  assert.equal(snapshot.netImportsMw, 500);
});

test('freshness is measured from the end of the five-minute sample and uses an explicit stale threshold', () => {
  const snapshot = D.parseSnapshot({ data: allRows() }, now);
  assert.deepEqual(D.freshness(snapshot, now), { state: 'fresh', ageMinutes: 3 });
  assert.equal(D.freshness(snapshot, now + 20 * 60 * 1000).state, 'stale');
  assert.equal(D.freshness(null, now).state, 'unavailable');
});

test('invalid, empty and future observations are rejected', () => {
  assert.throws(() => D.parseSnapshot({ rows: [] }, now), /unexpected/);
  assert.throws(() => D.parseSnapshot({ data: [] }, now), /No interconnector/);
  assert.throws(() => D.parseSnapshot({ data: [row('INTFR', 100, { startTime: '2026-11-07T17:00:00Z' })] }, now), /future observation/);
});

test('the request uses the signed public dataset with a bounded recent window and no credentials', async () => {
  const expected = new URL(D.buildUrl(now));
  assert.match(expected.pathname, /datasets\/FUELINST$/);
  assert.equal(Date.parse(expected.searchParams.get('publishDateTimeTo')) - Date.parse(expected.searchParams.get('publishDateTimeFrom')), 60 * 60 * 1000);
  let request;
  const snapshot = await D.fetchSnapshot({ now, fetchImpl: async (url, options) => { request = { url, options }; return { ok: true, json: async () => ({ data: allRows() }) }; } });
  assert.equal(request.options.credentials, 'omit');
  assert.equal(request.options.mode, 'cors');
  assert.equal(snapshot.measuredCount, 10);
  await assert.rejects(() => D.fetchSnapshot({ now, fetchImpl: async () => ({ ok: false, status: 503 }) }), /HTTP 503/);
});

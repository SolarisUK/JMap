const test = require('node:test');
const assert = require('node:assert/strict');
const operations = require('../UI/operations-analysis.js');

function forecast(issue = '2026-10-25T00:00:00Z') {
  return {
    zone_id: 'SELECTED_ZONE', issue_time_utc: issue, unit: 'MW', quantiles: ['p10', 'p50', 'p90'],
    timestamps_utc: Array.from({ length: 48 }, (_, index) => new Date(Date.parse(issue) + index * 30 * 60 * 1000).toISOString()),
    forecast: Array.from({ length: 48 }, (_, index) => [900 + index * 10, 1000 + index * 10, 1100 + index * 10]),
    explanation: ['Colder weather increases demand.', 'Recent demand is elevated.', 'An evening peak is approaching.']
  };
}

test('live KPI values read cumulative episode totals, never instantaneous zone costs or MW', () => {
  const snapshot = {
    zones: { first: { cost_gbp: 10, unserved_mw: 200 }, second: { cost_gbp: 20, unserved_mw: 300 } },
    totals: { cost_gbp: 4500, unserved_mwh: 750, carbon_t: 125, curtailed_mwh: 600 }
  };
  assert.deepEqual(operations.totalKpis(snapshot), { unserved_mwh: 750, cost_gbp: 4500, carbon_t: 125, curtailed_mwh: 600 });
});

test('reduced series snapshots and missing cumulative fields remain unknown rather than zero', () => {
  assert.deepEqual(operations.totalKpis({ zones: { first: { cost_gbp: 10 } } }), { unserved_mwh: null, cost_gbp: null, carbon_t: null, curtailed_mwh: null });
  assert.deepEqual(operations.totalKpis({ totals: { cost_gbp: 0, unserved_mwh: null } }), { unserved_mwh: null, cost_gbp: 0, carbon_t: null, curtailed_mwh: null });
  assert.equal(operations.totalKpis(null).cost_gbp, null);
  assert.throws(() => operations.totalKpis({ totals: { cost_gbp: '4500' } }), TypeError);
  assert.throws(() => operations.totalKpis({ totals: [] }), TypeError);
});

test('snapshot validation preserves signed flows, overloads, importing zones and fully tripped corridors', () => {
  const snapshot = {
    timestamp_utc: '2026-11-07T12:00:00+00:00',
    zones: { arbitrary_zone_id: { demand_mw: 1000, generation_mw: 100, unserved_mw: 0 } },
    edges: {
      arbitrary_edge_id: { flow_mw: -1500, limit_mw: 1000, loading_frac: 1.5, tripped: false },
      disconnected: { flow_mw: 0, limit_mw: 0, loading_frac: 0, tripped: true }
    }, incidents: []
  };
  assert.equal(operations.validateSnapshot(snapshot), snapshot);
  assert.equal(snapshot.edges.arbitrary_edge_id.flow_mw, -1500);
  assert.equal(snapshot.edges.arbitrary_edge_id.loading_frac, 1.5);
  assert.equal(snapshot.edges.disconnected.tripped, true);
  assert.equal(snapshot.zones.arbitrary_zone_id.unserved_mw, 0);
  assert.throws(() => operations.validateSnapshot({ ...snapshot, edges: { bad: { flow_mw: Infinity } } }), TypeError);
});

test('forecast accepts the exact 48-row UTC half-hour quantile contract without mutation', () => {
  const payload = forecast();
  const before = JSON.stringify(payload);
  assert.equal(operations.validateForecast(payload), payload);
  assert.equal(JSON.stringify(payload), before);
  assert.equal(payload.timestamps_utc[47], '2026-10-25T23:30:00.000Z');
});

test('forecast validation rejects misaligned timestamps, shape drift and swapped quantiles', () => {
  const short = forecast(); short.forecast.pop();
  assert.throws(() => operations.validateForecast(short), RangeError);
  const shifted = forecast(); shifted.timestamps_utc[2] = '2026-10-25T01:00:01Z';
  assert.throws(() => operations.validateForecast(shifted), /timestamp 2/);
  const reordered = forecast(); reordered.quantiles = ['p50', 'p10', 'p90'];
  assert.throws(() => operations.validateForecast(reordered), /quantiles/);
  const crossed = forecast(); crossed.forecast[7] = [1200, 1100, 1300];
  assert.throws(() => operations.validateForecast(crossed), /out of order/);
  const row = forecast(); row.forecast[4] = [1000, 1100];
  assert.throws(() => operations.validateForecast(row), /row 4/);
  const missing = forecast(); missing.forecast[4][1] = null;
  assert.throws(() => operations.validateForecast(missing), /unavailable quantile/);
  const units = forecast(); units.unit = 'MWh';
  assert.throws(() => operations.validateForecast(units), /MW/);
  const explanation = forecast(); explanation.explanation = ['Only one reason'];
  assert.throws(() => operations.validateForecast(explanation), /three/);
});

test('Europe/London display disambiguates repeated autumn hours and observes summer time', () => {
  assert.equal(operations.formatTime('2026-10-25T00:30:00Z'), '01:30 BST');
  assert.equal(operations.formatTime('2026-10-25T01:30:00Z'), '01:30 GMT');
  assert.equal(operations.formatTime('2026-07-01T12:00:00Z'), '13:00 BST');
  assert.equal(operations.formatTime('2026-01-01T12:00:00Z'), '12:00 GMT');
  assert.match(operations.formatTime('2026-07-01T12:00:00Z', { includeDate: true }), /01 Jul/);
  assert.throws(() => operations.formatTime('2026-10-25T01:30:00'), /UTC/);
  assert.throws(() => operations.formatTime('2026-02-30T00:00:00Z'), /valid UTC/);
});

function comparison(none, optimiser, agents, placeholder = false) {
  return { scenario: 'dynamic-test', agents_is_placeholder: placeholder, strategies: { none, optimiser, agents } };
}

test('the optimiser can beat trained agents and the headline uses actual arithmetic', () => {
  const result = operations.compareResults(comparison(
    { unserved_mwh: 100, cost_gbp: 1000 },
    { unserved_mwh: 20, cost_gbp: 900 },
    { unserved_mwh: 40, cost_gbp: 800 }
  ));
  assert.equal(result.bestStrategy, 'optimiser');
  assert.equal(result.reductionPercent, 80);
  assert.match(result.headline, /Optimiser reduced unserved energy by 80\.0%/);
  assert.equal(result.rows.find(row => row.key === 'agents').reductionPercent, 60);
  assert.equal(result.rows.find(row => row.key === 'optimiser').unservedAvoidedMWh, 80);
  assert.equal(result.rows.find(row => row.key === 'optimiser').costChangeGbp, -100);
});

test('trained agents win only when their reported results are actually best', () => {
  const result = operations.compareResults(comparison(
    { unserved_mwh: 100, cost_gbp: 1000 },
    { unserved_mwh: 30, cost_gbp: 700 },
    { unserved_mwh: 10, cost_gbp: 900 }
  ));
  assert.equal(result.bestStrategy, 'agents');
  assert.equal(result.reductionPercent, 90);
  assert.match(result.headline, /^Agents reduced/);
});

test('placeholder agents cannot win and copied figures are withheld from every returned metric', () => {
  const result = operations.compareResults(comparison(
    { unserved_mwh: 100, cost_gbp: 1000 },
    { unserved_mwh: 30, cost_gbp: 700 },
    { unserved_mwh: 0, cost_gbp: 0, carbon_t: 0, curtailed_mwh: 0 }, true
  ));
  assert.equal(result.bestStrategy, 'optimiser');
  const agents = result.rows.find(row => row.key === 'agents');
  assert.equal(agents.isPlaceholder, true);
  assert.match(agents.label, /not yet trained/);
  assert.ok(Object.values(agents.totals).every(value => value === null));
  assert.equal(agents.reductionPercent, null);
  assert.equal(agents.unservedAvoidedMWh, null);
  assert.equal(agents.costChangeGbp, null);
});

test('strategies worse than no response retain negative changes instead of a winning story', () => {
  const result = operations.compareResults(comparison(
    { unserved_mwh: 10, cost_gbp: 100 },
    { unserved_mwh: 15, cost_gbp: 90 },
    { unserved_mwh: 20, cost_gbp: 80 }
  ));
  assert.equal(result.bestStrategy, 'none');
  assert.match(result.headline, /^No response has the lowest/);
  assert.equal(result.rows.find(row => row.key === 'optimiser').reductionPercent, -50);
  assert.equal(result.rows.find(row => row.key === 'agents').reductionPercent, -100);
});

test('unknown totals and a zero baseline never manufacture percentage improvements', () => {
  const unknown = operations.compareResults(comparison({}, { unserved_mwh: 10 }, {}));
  assert.equal(unknown.bestStrategy, 'optimiser');
  assert.equal(unknown.reductionPercent, null);
  assert.match(unknown.headline, /unavailable/);
  const zero = operations.compareResults(comparison({ unserved_mwh: 0, cost_gbp: 20 }, { unserved_mwh: 0, cost_gbp: 10 }, {}));
  assert.equal(zero.bestStrategy, 'optimiser');
  assert.ok(zero.rows.every(row => row.reductionPercent === null));
  assert.equal(operations.compareResults({ strategies: {} }).bestStrategy, null);
});

test('ties use cost only when every tied strategy reports it, and reference order stays intact', () => {
  const payload = comparison({ unserved_mwh: 100 }, { unserved_mwh: 20, cost_gbp: 50 }, { unserved_mwh: 20 });
  const result = operations.compareResults(payload, { strategies: ['agents', 'none', 'optimiser'] });
  assert.deepEqual(result.rows.map(row => row.key), ['agents', 'none', 'optimiser']);
  assert.equal(result.bestStrategy, null);
  assert.deepEqual(result.winnerKeys, ['agents', 'optimiser']);
  payload.strategies.agents.cost_gbp = 40;
  assert.equal(operations.compareResults(payload).bestStrategy, 'agents');
});

test('tiny simulator residuals retain exact totals without a percentage-saving headline', () => {
  const payload = comparison(
    { unserved_mwh: .017, cost_gbp: 1000 },
    { unserved_mwh: .014, cost_gbp: 900 },
    { unserved_mwh: .014, cost_gbp: 900 }, true
  );
  const result = operations.compareResults(payload);
  assert.equal(result.materialUnserved, false);
  assert.equal(result.bestStrategy, 'optimiser');
  assert.equal(result.reductionPercent, null);
  assert.ok(result.rows.every(row => row.reductionPercent === null));
  const optimiser = result.rows.find(row => row.key === 'optimiser');
  assert.equal(optimiser.totals.unserved_mwh, .014);
  assert.equal(optimiser.unservedAvoidedMWh, .017 - .014);
  assert.match(result.headline, /lowest reported cost/);
  assert.match(result.headline, /below 1 MWh/);
  assert.ok(!result.headline.includes('%'));
});

test('lower numerical residual cannot make a more expensive optimiser the winner', () => {
  const result = operations.compareResults(comparison(
    { unserved_mwh: .017, cost_gbp: 1000 },
    { unserved_mwh: .014, cost_gbp: 1100 },
    {}, true
  ));
  assert.equal(result.bestStrategy, 'none');
  assert.equal(result.materialUnserved, false);
  assert.match(result.headline, /^No response has the lowest reported cost/);
  assert.equal(result.rows.find(row => row.key === 'optimiser').costChangeGbp, 100);
});

test('a cost winner with slightly more unserved energy is reported honestly within tolerance', () => {
  const result = operations.compareResults(comparison(
    { unserved_mwh: 10, cost_gbp: 1000 },
    { unserved_mwh: 10.05, cost_gbp: 900 },
    {}, true
  ));
  assert.equal(result.bestStrategy, 'optimiser');
  assert.equal(result.materialUnserved, true);
  assert.ok(result.reductionPercent < 0);
  assert.match(result.headline, /unserved energy is higher than baseline/);
});

test('reporting thresholds are configurable without altering raw simulator metrics', () => {
  const payload = comparison({ unserved_mwh: .5, cost_gbp: 100 }, { unserved_mwh: .4, cost_gbp: 200 }, {}, true);
  const result = operations.compareResults(payload, undefined, { minBaselineMWh: .1, energyToleranceMWh: .01 });
  assert.equal(result.bestStrategy, 'optimiser');
  assert.equal(result.materialUnserved, true);
  assert.ok(Math.abs(result.reductionPercent - 20) < 1e-10);
  assert.equal(payload.strategies.none.unserved_mwh, .5);
  assert.throws(() => operations.compareResults(payload, undefined, { energyToleranceMWh: -1 }), RangeError);
  assert.throws(() => operations.compareResults(payload, undefined, { minBaselineMWh: Infinity }), RangeError);
});

test('SVG chart draws aligned P10–P90 band and P50 line with readable units and accessible context', () => {
  class SvgNode {
    constructor(tag, document) { this.tagName = tag; this.ownerDocument = document; this.attributes = {}; this.children = []; }
    setAttribute(key, value) { this.attributes[key] = value; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
  }
  const document = { createElementNS: (namespace, tag) => new SvgNode(tag, document) };
  const element = new SvgNode('svg', document);
  const payload = forecast();
  assert.equal(operations.renderForecast(element, payload), payload);
  assert.equal(element.attributes.role, 'img');
  assert.equal(element.attributes.viewBox, '0 0 360 240');
  assert.match(element.attributes['aria-label'], /P50 median with P10 to P90 uncertainty band/);
  const [title, description, chart] = element.children;
  assert.match(title.textContent, /SELECTED_ZONE/);
  assert.match(description.textContent, /not observed demand/);
  assert.match(description.textContent, /Peak median 1,470 MW/);
  const band = chart.children.find(child => child.attributes.class === 'forecast-band');
  const median = chart.children.find(child => child.attributes.class === 'forecast-median');
  assert.ok(band.attributes.d.endsWith('Z'));
  assert.ok(!median.attributes.d.endsWith('Z'));
  assert.equal(chart.children.filter(child => child.tagName === 'circle').length, 48);
  assert.ok(chart.children.some(child => child.textContent === 'Demand · MW'));
  assert.ok(chart.children.some(child => child.textContent === 'Europe/London · half-hour starting'));
});

test('browser and CommonJS builds expose the same immutable operations API', () => {
  const fs = require('node:fs');
  const vm = require('node:vm');
  const browser = {};
  vm.runInNewContext(fs.readFileSync(require.resolve('../UI/operations-analysis.js'), 'utf8'), browser);
  assert.ok(Object.isFrozen(browser.JMapOperations));
  assert.equal(browser.JMapOperations.totalKpis({ totals: { cost_gbp: 42 } }).cost_gbp, 42);
  assert.equal(browser.JMapOperations.formatTime('2026-10-25T01:30:00Z'), '01:30 GMT');
});

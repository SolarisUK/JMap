const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function client(href, {config, bundle, fetch} = {}) {
  const context = vm.createContext({
    location: new URL(href), URL, URLSearchParams, structuredClone,
    window: {JMAP_OPERATIONS_CONFIG: config, JMAP_SIMULATION_STUBS: bundle},
    fetch: fetch || (() => { throw new Error('Unexpected network request'); })
  });
  vm.runInContext(fs.readFileSync(require.resolve('../operations-api.js'),'utf8'),context);
  return new context.window.OperationsApi();
}

test('static HTTP and file previews work from the UI bundle without a backend', async () => {
  const bundle = {reference:{zone_order:['A']}};
  for (const href of ['http://localhost:8765/operations.html','file:///C:/JMap/UI/operations.html']) {
    const api = client(href,{bundle});
    assert.equal(api.mode,'bundled');
    assert.deepEqual(await api.reference(),bundle.reference);
  }
});

test('bundle reads are isolated from mutations by inspectors and controls', async () => {
  const bundle = {edges:{edges:[{edge_id:'A-B'}]}};
  const api = client('http://localhost/operations.html',{bundle});
  (await api.edges()).edges[0].edge_id = 'changed';
  assert.equal((await api.edges()).edges[0].edge_id,'A-B');
  assert.equal(bundle.edges.edges[0].edge_id,'A-B');
});

test('an explicit API base preserves scenario, strategy and timestamp query values', async () => {
  const requests = [];
  const api = client('http://localhost/operations.html?api=https%3A%2F%2Fgrid.example',{
    fetch: async (url,options) => { requests.push({url,options}); return {ok:true,json:async () => ({ok:true})}; }
  });
  await api.state('cold snap','optimiser','2026-11-07T16:00:00+00:00',32);
  assert.equal(api.mode,'api');
  const url = new URL(requests[0].url);
  assert.equal(url.origin,'https://grid.example');
  assert.equal(url.pathname,'/state');
  assert.equal(url.searchParams.get('scenario'),'cold snap');
  assert.equal(url.searchParams.get('strategy'),'optimiser');
  assert.equal(url.searchParams.get('t'),'2026-11-07T16:00:00+00:00');
});

test('configured API failures remain errors and never return a bundled replacement', async () => {
  const api = client('http://localhost/operations.html',{
    config:{mode:'api',apiBase:'https://grid.example'},
    bundle:{reference:{silentlyReplaced:true}},
    fetch:async () => ({ok:false,status:503,statusText:'Unavailable',json:async () => ({detail:'Telemetry unavailable'})})
  });
  await assert.rejects(api.reference(),/Telemetry unavailable/);
  assert.equal(api.mode,'api');
});

test('bundled mode cannot post custom incidents or invent absent scenarios', async () => {
  const api = client('http://localhost/operations.html',{bundle:{series:{}}});
  assert.throws(() => api.incident('cold_snap',{}),/requires the API/);
  await assert.rejects(api.series('absent','agents'),/No bundled episode/);
});

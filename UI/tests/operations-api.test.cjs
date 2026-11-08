const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function client(href, {config, archive, fetch} = {}) {
  const context = vm.createContext({
    location: new URL(href), URL, URLSearchParams,
    window: {JMAP_OPERATIONS_CONFIG: config, JMAP_SIMULATION_STUBS: archive},
    fetch: fetch || (() => { throw new Error('Unexpected network request'); })
  });
  vm.runInContext(fs.readFileSync(require.resolve('../operations-api.js'),'utf8'),context);
  return new context.window.OperationsApi();
}

test('local file and HTTP entry points use the runtime API even when an archive exists', async () => {
  for (const href of ['http://localhost:8765/operations.html','file:///C:/JMap/UI/operations.html','http://localhost/operations.html?mode=bundled']) {
    const requests=[];
    const api=client(href,{archive:{reference:{stale:true}},fetch:async url=>{
      requests.push(url);return {ok:true,json:async()=>({runtime:true})};
    }});
    assert.equal(api.mode,'api');
    assert.deepEqual(await api.reference(),{runtime:true});
    assert.equal(requests[0],'http://127.0.0.1:8000/reference');
  }
});

test('remote deployments use same-origin endpoints unless an API base is configured', () => {
  assert.equal(client('https://dashboard.example/operations.html').baseUrl,'https://dashboard.example');
  assert.equal(client('https://dashboard.example/operations.html',{config:{apiBase:'https://grid.example'}}).baseUrl,'https://grid.example');
});

test('endpoint names and scenario, strategy, zone and UTC query fields are preserved', async () => {
  const requests=[];
  const api=client('http://localhost/operations.html?api=https%3A%2F%2Fgrid.example',{
    fetch:async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>({runtime:true})};}
  });
  await api.reference();await api.zones();await api.edges();await api.scenarios();
  await api.series('cold snap','none');await api.series('cold snap','optimiser');
  await api.state('cold snap','optimiser','2026-11-07T16:00:00+00:00',32);
  await api.compare('cold snap');await api.forecast('LOND','2026-11-07T00:00:00Z','cold snap');
  assert.deepEqual(requests.map(r=>new URL(r.url).pathname),[
    '/reference','/zones','/edges','/scenarios','/state/series','/state/series','/state','/compare','/forecast/LOND'
  ]);
  const state=new URL(requests[6].url),forecast=new URL(requests[8].url);
  assert.equal(state.searchParams.get('scenario'),'cold snap');
  assert.equal(state.searchParams.get('strategy'),'optimiser');
  assert.equal(state.searchParams.get('t'),'2026-11-07T16:00:00+00:00');
  assert.equal(forecast.searchParams.get('scenario'),'cold snap');
  assert.equal(forecast.searchParams.get('issue_time'),'2026-11-07T00:00:00Z');
});

test('API failures never substitute archived measurements', async () => {
  const api=client('file:///C:/JMap/UI/operations.html',{
    archive:{reference:{stale:true}},
    fetch:async()=>({ok:false,status:503,statusText:'Unavailable',json:async()=>({detail:'API unavailable'})})
  });
  await assert.rejects(api.reference(),/API unavailable/);
});

test('incident fields and HTTP method are unchanged', async () => {
  let sent;
  const api=client('http://localhost/operations.html',{fetch:async(url,options)=>{
    sent={url,options};return {ok:true,json:async()=>({ok:true})};
  }});
  const incident={type:'line_trip',target:'SSCO-NORT',start_step:34,duration_steps:14,magnitude:1};
  await api.incident('test',incident);
  assert.equal(sent.options.method,'POST');
  assert.deepEqual(JSON.parse(sent.options.body),incident);
  assert.equal(new URL(sent.url).pathname,'/incident');
});

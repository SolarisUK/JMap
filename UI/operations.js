/* Operations dashboard. Endpoint and enumeration contract: LEONARD_SPEC.md. */
(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const A = window.JMapOperations;
  const T = window.JMapTransfers;
  const params = new URL(location.href).searchParams;
  const state = { scenario: params.get('scenario') || '', strategy: 'optimiser', zone: params.get('zone') || '', edge: params.get('edge') || null, focus: params.get('focus') === 'zone' ? 'zone' : params.get('edge') ? 'edge' : null, step: Number(params.get('step') ?? 38), split: params.get('view') !== 'single', tab: ['transfers','inspect','forecast','results'].includes(params.get('tab')) ? params.get('tab') : 'transfers', showValues: params.get('values') !== '0', animate: params.get('motion') !== '0', reference: null, zones: null, edges: [], scenarios: [], series: null, comparison: null, baseline: null, response: null, forecast: null, playing: false, busy: false };
  let api, baselineMap, responseMap, timer, episodeVersion = 0, frameVersion = 0, forecastVersion = 0;
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const number = (value, digits = 1) => finite(value) ? value.toLocaleString('en-GB', { maximumFractionDigits: digits }) : '—';
  const energy = value => finite(value) ? `${number(value)} MWh` : '—';
  const power = value => finite(value) ? `${number(value)} MW` : '—';
  const money = value => !finite(value) ? '—' : Math.abs(value) >= 1e6 ? `£${number(value / 1e6, 2)}m` : `£${number(value, 0)}`;
  const percent = value => finite(value) ? `${number(value * 100)}%` : '—';
  const node = (tag, className, text) => { const element = document.createElement(tag); if (className) element.className = className; if (text !== undefined) element.textContent = text; return element; };
  const announce = text => { $('#announcement').textContent = text; };
  function readOnlyData() { return state.reference?.backend_mode === 'stubs'; }
  function responseName() { return 'Optimiser'; }
  function zoneName(key) { return state.zones?.features.find(feature => feature.properties.zone_id === key)?.properties.name || key; }
  function syncUrl() {
    const url = new URL(location.href);
    url.searchParams.set('mode','api');
    [['scenario',state.scenario],['strategy',state.strategy],['zone',state.zone],['step',state.step],['tab',state.tab]].forEach(([key,value]) => url.searchParams.set(key,value));
    if (state.split) url.searchParams.delete('view'); else url.searchParams.set('view','single');
    if (state.showValues) url.searchParams.delete('values'); else url.searchParams.set('values','0');
    url.searchParams.set('motion', state.animate ? '1' : '0');
    if (state.focus) url.searchParams.set('focus',state.focus); else url.searchParams.delete('focus');
    if (state.focus === 'edge' && state.edge) url.searchParams.set('edge',state.edge); else url.searchParams.delete('edge');
    if (url.href !== location.href) history.replaceState(null,'',url.href);
  }
  function showError(error) {
    pause(); $('#error-message').textContent = `Data could not be loaded: ${error.message || error}`; $('#error-banner').hidden = false;
    $('#export-episode').disabled = true; $('#export-results').disabled = true; $('#export-transfers').disabled = true; document.body.classList.add('data-error');
    $('#loading-state').textContent = '';
    announce(`Data error. ${error.message || error}`);
  }
  function loading(value, text = 'Loading…') { state.busy = value; $('#loading-state').textContent = value ? text : ''; $('#scenario').disabled = value || !state.reference; $('#strategy').disabled = value || !state.reference; $('#play').disabled = value || !state.series; $('#time-step').disabled = value || !state.series; $('#open-incidents').disabled = value || !state.series; }
  function fillOptions(select, values) {
    select.replaceChildren(); values.forEach(([value,label]) => { const option = node('option','',label); option.value = value; select.append(option); });
  }
  function makeMaps() {
    baselineMap?.destroy(); responseMap?.destroy();
    baselineMap = new window.SimulationMap({ element: $('#baseline-map'), geography: window.JMAP_GEOGRAPHY, onZoneSelect: selectZone, onEdgeSelect: selectEdge, onClearSelect: clearSelection, onViewChange: view => responseMap?.setView(view,{silent:true}) });
    responseMap = new window.SimulationMap({ element: $('#response-map'), geography: window.JMAP_GEOGRAPHY, onZoneSelect: selectZone, onEdgeSelect: selectEdge, onClearSelect: clearSelection, onViewChange: view => baselineMap?.setView(view,{silent:true}) });
    baselineMap.setTopology(state.zones,{edges:state.edges}); responseMap.setTopology(state.zones,{edges:state.edges});
    applyTransferOptions();
  }
  function applyTransferOptions() {
    $('#show-transfer-values').checked = state.showValues; $('#animate-transfers').checked = state.animate;
    [baselineMap,responseMap].forEach(map => map?.setTransferOptions({showValues:state.showValues,animate:state.animate}));
  }
  function syncMapFocus() {
    [baselineMap,responseMap].forEach(map => {
      if (!map) return;
      if (state.focus === 'zone') { map.selectEdge(null); map.selectZone(state.zone); }
      else { map.selectZone(null); map.selectEdge(state.focus === 'edge' ? state.edge : null); }
    });
    $('#clear-map-selection').hidden = !state.focus;
  }
  function syncZoneControl() {
    const overview = $('#zone').querySelector('option[value=""]');
    if (overview) overview.disabled = state.tab !== 'transfers';
    $('#zone').value = state.tab === 'transfers' && state.focus !== 'zone' ? '' : state.zone;
  }
  function applyView() {
    $('#maps').classList.toggle('single-view',!state.split); $('#split-view').setAttribute('aria-pressed',String(state.split)); $('#single-view').setAttribute('aria-pressed',String(!state.split));
    document.querySelectorAll('[data-tab]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.tab === state.tab)));
    ['transfers','inspect','forecast','results'].forEach(tab => { $(`#panel-${tab}`).hidden = state.tab !== tab; });
    $('#zone-selector').hidden = state.tab === 'results';
    syncZoneControl();
    syncUrl();
  }
  function renderModelStatus() {
    const ref = state.reference || {};
    const scenario = state.scenarios.find(item => item.name === state.scenario);
    const synthetic = scenario?.data_is_synthetic ?? ref.data_is_synthetic;
    $('#data-status').textContent = `${ref.backend_mode === 'stubs' ? 'Read-only stubs API' : 'Simulation API'}${synthetic === true ? ' · synthetic demand' : synthetic === false ? '' : ' · source provenance unconfirmed'}`;
    $('#model-status').textContent = 'Response layer: optimisation engine';
    $('#response-heading').textContent = 'Optimiser';
    $('#response-chip').textContent = responseName();
    $('#snapshot-scope').textContent = `${responseName()} · cumulative totals at selected half-hour`;
    $('#geometry-status').textContent = ref.geometry_is_placeholder !== false ? 'Schematic zones · simulated flows' : 'Zone geometry from /zones';
    const paragraphs = [
      `This dashboard consumes ${readOnlyData() ? 'read-only generated stubs' : 'the simulation API'} at ${api.baseUrl}. These are simulated episodes, not live grid telemetry.`,
      synthetic === true ? 'The supplied canonical demand and weather data is synthetic demonstration input. The results are model output, not observations.' : synthetic === false ? 'The backend reports non-synthetic source data. Forecast/model provenance is provided with each endpoint.' : 'The source data has not been identified as synthetic or observed. These results remain simulated model output, not live grid measurements.',
      'The response layer is the optimisation engine. Strategy rankings use the full-episode totals returned by the API, including cases where no response has a lower reported value.',
      ref.forecast_is_placeholder !== false ? 'No trained demand model is loaded. Forecasts use historical-week/persistence demand with illustrative, uncalibrated uncertainty ranges. Explanations are labelled as illustrative and are not SHAP attributions.' : 'Forecasts come from the configured provider; the forecast response identifies its model and explanation provenance.',
      ref.geometry_is_placeholder !== false ? 'The contract supplies schematic zones. Markers locate the network endpoints; they do not claim surveyed service boundaries. Detailed zone measurements are shown in the side panel.' : 'Network polygons are provided by the configured backend.'
    ];
    paragraphs.push('Zone colours use a display tolerance of 0.05 MW so floating-point residuals do not appear as red zero-demand shortages. Positive residuals below that threshold are labelled below 0.1 MW; tooltips and API values retain full precision.');
    paragraphs.push('Routes are drawn as schematic curves between their declared endpoints. A fixed width scale represents absolute MW consistently across both maps and every half-hour; colour represents loading against current capacity. Only the hovered, keyboard-focused or selected corridor shows an inline MW value. All signed measurements and limits remain available in the panel and CSV.');
    $('#data-notes').replaceChildren(...paragraphs.map(text => node('p','',text)));
    $('#incident-mode-note').textContent = readOnlyData() ? 'Read-only preview loads the corresponding pre-generated scenario. Start the API in simulation mode to inject incidents with the start and duration below.' : 'Incidents are posted to the API and applied to every strategy in this scenario. Existing scripted incidents remain active.';
    $('#open-incidents').textContent = readOnlyData() ? 'Incident scenarios' : 'Inject incident +';
    $('#incident-title').textContent = readOnlyData() ? 'Load an incident scenario' : 'Inject an incident';
    $('.incident-settings').hidden = readOnlyData();
  }
  async function init() {
    pause(); loading(true,'Loading topology…'); $('#error-banner').hidden = true;
    try {
      api = new window.OperationsApi();
      const [reference,zones,edgePayload,scenarioPayload] = await Promise.all([api.reference(),api.zones(),api.edges(),api.scenarios()]);
      if (!Array.isArray(reference.zone_order) || !Array.isArray(reference.edge_order) || !Array.isArray(reference.strategies) || !Array.isArray(reference.fuel_order)) throw new Error('/reference is missing canonical enumerations.');
      if (!Array.isArray(zones.features) || new Set(zones.features.map(feature => feature.properties.zone_id)).size !== reference.zone_order.length || reference.zone_order.some(key => !zones.features.some(feature => feature.properties.zone_id === key))) throw new Error('/zones does not match the canonical zone IDs.');
      const edges = Array.isArray(edgePayload) ? edgePayload : edgePayload.edges;
      if (!Array.isArray(edges) || edges.length !== reference.edge_order.length || reference.edge_order.some(key => !edges.some(edge => edge.edge_id === key))) throw new Error('/edges does not match the canonical corridor IDs.');
      state.reference = reference; state.zones = zones; state.edges = edges;
      state.scenarios = Array.isArray(scenarioPayload) ? scenarioPayload : scenarioPayload.scenarios;
      if (!state.scenarios?.length) throw new Error('No scenarios are available.');
      if (!state.scenarios.some(scenario => scenario.name === state.scenario)) state.scenario = state.scenarios[0].name;
      if (!['none','optimiser'].every(key => reference.strategies.includes(key))) throw new Error('/reference must provide none and optimiser strategies.');
      if (!reference.zone_order.includes(state.zone)) state.zone = reference.zone_order.find(key => /london/i.test(zoneName(key))) || reference.zone_order[0];
      if (!reference.edge_order.includes(state.edge)) { state.edge = null; if (state.focus === 'edge') state.focus = null; }
      fillOptions($('#scenario'),state.scenarios.map(scenario => [scenario.name,scenario.name.replaceAll('_',' ').replace(/^./,character=>character.toUpperCase())]));
      [...$('#scenario').options].forEach(option=>option.title=state.scenarios.find(item=>item.name===option.value)?.description||option.textContent);
      fillOptions($('#strategy'),[['optimiser','Optimiser']]);
      fillOptions($('#zone'),[['','All zones'],...reference.zone_order.map(key => [key,`${key} · ${zoneName(key)}`])]);
      $('#scenario').value = state.scenario; $('#strategy').value = state.strategy; $('#zone').value = state.zone; $('#zone').disabled = false;
      makeMaps(); applyView(); await loadEpisode();
    } catch (error) { loading(false); showError(error); }
  }
  function validateSeries(series) {
    if (!Array.isArray(series.frames) || series.frames.length !== 48) throw new Error('An episode must contain exactly 48 half-hour frames.');
    series.frames.forEach((frame,index) => {
      const time = Date.parse(frame.timestamp_utc);
      if (!Number.isFinite(time) || (index && time - Date.parse(series.frames[index-1].timestamp_utc) !== 1800000)) throw new Error('Episode timestamps must be consecutive half-hours.');
      if (state.reference.zone_order.some(key => !frame.zones?.[key]) || state.reference.edge_order.some(key => !frame.edges?.[key])) throw new Error('An episode frame has missing zones or corridors.');
    });
    return series;
  }
  async function loadEpisode() {
    pause(); const version = ++episodeVersion; ++frameVersion; ++forecastVersion; state.series = null; state.comparison = null; state.forecast = null;
    $('#forecast-chart').replaceChildren(); $('#forecast-explanation').replaceChildren(); $('#forecast-issued').textContent = ''; $('#forecast-note').textContent = ''; $('#forecast-status').textContent = 'Waiting for episode…';
    $('#export-episode').disabled = true; $('#export-results').disabled = true; $('#export-transfers').disabled = true; $('#zone').disabled = true;
    loading(true,'Loading episode…'); $('#error-banner').hidden = true; document.body.classList.remove('data-error');
    try {
      const [baseline,response,comparison] = await Promise.all([api.series(state.scenario,'none'),api.series(state.scenario,'optimiser'),api.compare(state.scenario)]);
      if (version !== episodeVersion) return;
      validateSeries(baseline); validateSeries(response);
      if (baseline.scenario !== state.scenario || baseline.strategy !== 'none' || response.scenario !== state.scenario || comparison.scenario !== state.scenario || response.strategy !== 'optimiser') throw new Error('The returned episode identity does not match the selected scenario and strategy.');
      if (baseline.frames.some((frame,index) => frame.timestamp_utc !== response.frames[index].timestamp_utc)) throw new Error('Baseline and response timelines do not align.');
      state.series = {baseline,response}; state.comparison = comparison;
      state.step = Math.max(0,Math.min(47,Number.isInteger(state.step) ? state.step : 0));
      $('#scenario-description').textContent = state.scenarios.find(scenario => scenario.name === state.scenario)?.description || state.scenario;
      $('#scenario-description').title = $('#scenario-description').textContent;
      $('#episode-range').textContent = `${A.formatTime(baseline.frames[0].timestamp_utc,{includeDate:true})} — ${A.formatTime(baseline.frames[47].timestamp_utc,{includeDate:true})}`;
      $('#time-step').max = baseline.frames.length - 1;
      $('#results-scope').textContent = `Full episode \u00b7 ${baseline.frames.length} half-hours`;
      renderModelStatus(); renderResults(); const accepted = await seek(state.step);
      if (version === episodeVersion) { loading(false); $('#export-episode').disabled = !accepted; $('#export-results').disabled = !accepted; $('#zone').disabled = !accepted; }
      return accepted;
    } catch (error) { if (version === episodeVersion) { loading(false); showError(error); } return false; }
  }
  async function seek(step) {
    if (!state.series) return false;
    state.step = Math.max(0,Math.min(state.series.baseline.frames.length - 1,step));
    $('#export-transfers').disabled = true;
    const version = ++frameVersion; const timestamp = state.series.baseline.frames[state.step].timestamp_utc;
    $('#time-step').value = state.step; $('#frame-time').textContent = A.formatTime(timestamp,{includeDate:true}); $('#time-step').setAttribute('aria-valuetext',`${A.formatTime(timestamp,{includeDate:true})}, half-hour ${state.step+1} of 48`); $('#frame-count').textContent = `${state.step+1} / ${state.series.baseline.frames.length}`;
    $('#incident-start').value = state.step; $('#previous-frame').disabled = state.step === 0; $('#next-frame').disabled = state.step === 47;
    try {
      const [baseline,response] = await Promise.all([api.state(state.scenario,'none',timestamp,state.step),api.state(state.scenario,'optimiser',timestamp,state.step)]);
      if (version !== frameVersion) return false;
      A.validateSnapshot(baseline); A.validateSnapshot(response);
      if (baseline.timestamp_utc !== timestamp || response.timestamp_utc !== timestamp) throw new Error('Snapshot time does not match the selected frame.');
      state.baseline = baseline; state.response = response;
      baselineMap.setState(baseline); responseMap.setState(response);
      renderSnapshot(); syncUrl();
      $('#export-transfers').disabled = false;
      if (state.tab === 'forecast') await loadForecast();
      return true;
    } catch (error) { if (version === frameVersion) showError(error); return false; }
  }
  function renderSnapshot() {
    const totals = A.totalKpis(state.response); const baselineTotals = A.totalKpis(state.baseline);
    const cards = [['unserved',totals.unserved_mwh,energy,baselineTotals.unserved_mwh],['cost',totals.cost_gbp,money,baselineTotals.cost_gbp],['penalty',totals.penalty_gbp,money,baselineTotals.penalty_gbp],['carbon',totals.carbon_t,value => finite(value) ? `${number(value)} tCO₂` : '—',baselineTotals.carbon_t],['curtailed',totals.curtailed_mwh,energy,baselineTotals.curtailed_mwh]];
    cards.forEach(([key,value,format,baseline]) => { $(`#kpi-${key}`).textContent = format(value); $(`#kpi-${key}`).closest('article').title = `${responseName()}: ${format(value)}. No response: ${format(baseline)}. Cumulative to selected half-hour.${key === 'penalty' ? ' Model penalty for overloads and spilled surplus; excluded from real episode cost.' : ''}`; });
    const unmet = snapshot => { const values = state.reference.zone_order.map(key => snapshot.zones[key]?.unserved_mw); return values.every(finite) ? values.reduce((total,value) => total + value,0) : null; };
    $('#baseline-summary').textContent = `${power(unmet(state.baseline))} unmet now`; $('#response-summary').textContent = `${power(unmet(state.response))} unmet now`;
    renderZone(); renderCorridors(); renderTransfers(); renderIncidents(); syncMapFocus();
  }
  function facts(target, rows) {
    target.replaceChildren(...rows.map(([label,value]) => { const row = node('div'); row.append(node('dt','',label),node('dd','',value)); return row; }));
  }
  function renderZone() {
    const row = state.response?.zones[state.zone]; if (!row) return;
    syncZoneControl(); $('#detail-title').textContent = zoneName(state.zone);
    facts($('#zone-facts'),[['Demand',power(row.demand_mw)],['Generation + storage',power(row.generation_mw)],['Unmet demand',power(row.unserved_mw)],['Storage state of charge',percent(row.storage_soc)],['Demand response called',power(row.dr_called_mw)],['Curtailed power',power(row.curtailed_mw)],['Cost this half-hour',money(row.cost_gbp)],['Carbon this half-hour',finite(row.carbon_t) ? `${number(row.carbon_t)} tCO₂` : '—']]);
    facts($('#forecast-zone-facts'),[['Demand',power(row.demand_mw)],['Generation + storage',power(row.generation_mw)],['Unmet demand',power(row.unserved_mw)],['Storage state of charge',percent(row.storage_soc)]]);
  }
  function edgeValues(edge) {
    const row = state.response?.edges[edge.edge_id] || {};
    const out = row.limit_mw === 0; const loading = finite(row.loading_frac) ? row.loading_frac : null;
    return { row, out, loading, status: out ? 'out' : loading > 1 ? 'overloaded' : row.tripped ? 'tripped' : loading >= .75 ? 'warning' : loading === null ? 'unknown' : 'healthy' };
  }
  function transferButton(row) {
    const button = node('button','transfer-row'); button.type = 'button'; button.dataset.transferEdge = row.id; button.dataset.status = row.status;
    button.setAttribute('aria-pressed',String(state.edge === row.id));
    const direction = row.available === false ? `${row.from} — ${row.to}` : !row.known ? `${row.from} ↔ ${row.to}` : row.active ? `${row.source} → ${row.target}` : `${row.from} ↔ ${row.to}`;
    const value = row.available === false ? 'OUT' : power(row.magnitudeMw);
    const description = row.available === false ? 'Out of service' : !row.known ? 'Flow unavailable' : !row.active ? 'No material transfer' : row.status === 'unknown' ? 'Loading unavailable' : row.status === 'tripped' ? 'Derated / tripped' : row.status === 'overloaded' ? 'Overloaded' : row.status === 'warning' ? 'High loading' : 'In service';
    const title = node('span','transfer-route',direction); const amount = node('strong','transfer-mw',row.available === false ? 'OUT' : number(row.magnitudeMw,0));
    const load = node('span','transfer-loading',row.available === false ? '—' : percent(row.loading));
    button.append(title,amount,load);
    button.title = `${zoneName(row.from)} / ${zoneName(row.to)}. ${value}; ${description}. Signed measurement ${power(row.flowMw)}. Current limit ${power(row.limitMw)}.`;
    button.setAttribute('aria-label',`${direction}, ${value}, ${description}, ${row.available === false ? 'out of service' : `${percent(row.loading)} loading`}`);
    button.addEventListener('click',() => selectEdge(row.id)); return button;
  }
  function renderTransferList(target, rows) {
    const focused = document.activeElement?.dataset.transferEdge; const scroll = target.scrollTop;
    target.replaceChildren(...rows.map(transferButton)); target.scrollTop = scroll;
    if (focused) target.querySelector(`[data-transfer-edge="${focused}"]`)?.focus({preventScroll:true});
  }
  function renderTransfers() {
    if (!state.response) return;
    const summary = T.summarize(state.edges,state.response,state.zone);
    const shortages = state.reference.zone_order.map(key => state.response.zones[key]?.unserved_mw);
    const knownShortages = shortages.filter(finite);
    const unmet = knownShortages.length === shortages.length ? knownShortages.reduce((total,value) => total+value,0) : null;
    const affected = knownShortages.filter(value => value >= .05).length;
    facts($('#network-state-summary'),[['Unmet now',power(unmet)],['Zones affected',knownShortages.length === shortages.length ? `${affected} / ${shortages.length}` : `${affected} confirmed`]]);
    $('#network-state-summary').dataset.shortage = String(affected > 0);
    $('#transfer-snapshot-time').textContent = A.formatTime(state.response.timestamp_utc);
    $('#transfer-zone-detail').hidden = state.focus !== 'zone';
    $('#transfer-zone-title').textContent = `${zoneName(state.zone)} transfers`;
    const zone = state.response.zones[state.zone];
    facts($('#transfer-zone-facts'),[['Demand',power(zone?.demand_mw)],['Generation + storage',power(zone?.generation_mw)],['Unmet demand',power(zone?.unserved_mw)]]);
    const net = summary.netImportMw;
    facts($('#transfer-zone-totals'),[['Incoming',power(summary.incomingMw)],['Outgoing',power(summary.outgoingMw)],[net === null ? 'Net transfer' : net < -.05 ? 'Net export' : net > .05 ? 'Net import' : 'Net transfer',power(finite(net) ? Math.abs(net) : null)]]);
    $('#transfer-zone-note').textContent = summary.incomplete ? 'Flow measurements unavailable; zone totals are incomplete.' : '';
    $('#transfer-zone-note').hidden=!summary.incomplete;
    $('#zone-corridor-count').textContent = `${summary.zoneRows.length} links`;
    renderTransferList($('#zone-transfer-list'),summary.zoneRows);
    const ranking = {out:0,overloaded:1,tripped:2,warning:3,unknown:4,healthy:5,idle:6};
    const ranked = [...summary.rows].sort((a,b) => ranking[a.status] - ranking[b.status] || (b.magnitudeMw ?? -1) - (a.magnitudeMw ?? -1));
    renderTransferList($('#network-transfer-list'),ranked);
    const out = summary.rows.filter(row => row.available === false).length;
    const overloaded = summary.rows.filter(row => row.status === 'overloaded').length;
    $('#transfer-network-status').textContent = `${out} out · ${overloaded} overloaded`;
    $('#transfer-edge-detail').hidden = state.focus !== 'edge' || !state.edge;
    const selected = summary.rows.find(row => row.id === state.edge);
    if (selected) {
      $('#transfer-edge-title').textContent = `${selected.id} corridor`;
      facts($('#transfer-edge-facts'),[['From / to',selected.available === false ? 'Out of service' : !selected.known ? 'Direction unavailable' : selected.active ? `${zoneName(selected.source)} → ${zoneName(selected.target)}` : 'No active direction'],['Effective transfer',power(selected.effectiveMw)],['Signed measurement',power(selected.flowMw)],['Available limit',power(selected.limitMw)],['Nameplate limit',power(selected.nameplateLimitMw)],['Loading',selected.available === false ? 'Out of service' : percent(selected.loading)],['Status',selected.status]]);
    }
  }
  function renderCorridors() {
    const focused = document.activeElement.dataset.edge; const list = $('#corridor-list'); const scroll = list.scrollTop; list.replaceChildren();
    let overloaded = 0;
    state.reference.edge_order.forEach(key => {
      const edge = state.edges.find(item => item.edge_id === key); const {row,out,loading,status} = edgeValues(edge); if (status === 'overloaded') overloaded++;
      const button = node('button','corridor-row'); button.type = 'button'; button.dataset.edge = key; button.dataset.status = status; button.setAttribute('aria-pressed',String(state.edge === key));
      button.append(node('span','',key),node('span','',out ? 'OUT' : percent(loading)),node('small','',`${power(row.flow_mw)} signed · ${out ? 'No available circuit' : row.tripped ? 'Tripped / derated' : status}`));
      button.addEventListener('click',() => selectEdge(key)); list.append(button);
    });
    $('#corridor-count').textContent = `${overloaded} overloaded / ${state.edges.length}`; list.scrollTop = scroll;
    if (focused) document.querySelector(`[data-edge="${focused}"]`)?.focus({preventScroll:true});
    $('#edge-detail').hidden = !state.edge;
    if (state.edge) {
      const edge = state.edges.find(item => item.edge_id === state.edge); if (!edge) return;
      const {row,out,status} = edgeValues(edge); const reversed = finite(row.flow_mw) && row.flow_mw < 0;
      $('#edge-title').textContent = state.edge;
      facts($('#edge-facts'),[['Direction',out ? 'Out of service' : `${reversed ? edge.to : edge.from} → ${reversed ? edge.from : edge.to}`],['Signed flow',power(row.flow_mw)],['Current limit',power(row.limit_mw)],['Nameplate limit',power(edge.limit_mw)],['Loading',out ? 'Out of service' : percent(row.loading_frac)],['State',status]]);
    }
  }
  function renderIncidents() {
    const incidents = state.response?.incidents || [];
    $('#active-incidents').replaceChildren(...(incidents.length ? incidents.map(incident => {
      const row = node('div','incident-row',`${incident.type.replaceAll('_',' ')} · ${incident.target}`); row.append(node('small','',`Steps ${incident.start_step}–${incident.start_step+incident.duration_steps-1} · magnitude ${number(incident.magnitude,2)}`)); return row;
    }) : [node('p','muted','No active incidents at this half-hour.')]));
  }
  function renderResults() {
    const comparison = A.compareResults(state.comparison,state.reference); const best = comparison.rows.find(row => row.key === comparison.bestStrategy);
    $('#result-headline').textContent = comparison.materialUnserved === false ? 'Near-zero unserved energy' : best && best.reductionPercent > 0 && best.unservedAvoidedMWh > .1 ? `${number(best.reductionPercent)}% less unserved energy` : comparison.bestStrategy === 'none' ? 'No response ranks first' : comparison.winnerKeys.length > 1 ? 'Results tied' : 'Episode comparison';
    $('#result-description').textContent = comparison.headline;
    const body = $('#results-body'); body.replaceChildren();
    const metrics = [
      ['unserved_mwh','Unserved energy',energy], ['cost_gbp','Episode cost',money],
      ['penalty_gbp','Model penalty',money],
      ['carbon_t','Carbon',value => finite(value) ? `${number(value)} tCO\u2082` : '\u2014'],
      ['curtailed_mwh','Curtailed energy',energy]
    ];
    metrics.forEach(([key,label,format]) => {
      const tr = node('tr'); tr.dataset.metric = key;
      comparison.rows.forEach(row => {
        const cell = node('td'); cell.dataset.strategy = row.key;
        cell.dataset.winner = String(comparison.winnerKeys.includes(row.key));
        cell.append(document.createTextNode(label),node('br'),node('span','',format(row.totals[key])));
        if (key === 'penalty_gbp') cell.title = 'Model penalty, excluded from real episode cost.';
        tr.append(cell);
      });
      body.append(tr);
    });
    facts($('#result-other-metrics'),best ? [['Unserved energy avoided',energy(best.unservedAvoidedMWh)],['Cost change vs baseline',finite(best.costChangeGbp) ? `${best.costChangeGbp < 0 ? '−' : '+'}${money(Math.abs(best.costChangeGbp))}` : '—']] : []);
  }
  async function loadForecast() {
    if (!state.response || !state.series || state.tab !== 'forecast') return;
    const version = ++forecastVersion; $('#forecast-status').textContent = 'Loading forecast…';
    try {
      const scenario = state.scenarios.find(item => item.name === state.scenario);
      const recordedIssue = scenario?.episode_start_utc || scenario?.start_timestamp_utc || state.reference.episode_start_utc || state.series.baseline.frames[0].timestamp_utc;
      const issueTime = readOnlyData() ? recordedIssue : state.response.timestamp_utc;
      const zone = state.zone;
      const payload = await api.forecast(zone,issueTime,state.scenario); if (version !== forecastVersion) return;
      if (payload.zone_id !== zone || Date.parse(payload.issue_time_utc) !== Date.parse(issueTime)) throw new Error('Forecast identity or issue time does not match the selected scenario.');
      A.renderForecast($('#forecast-chart'),payload); state.forecast = payload;
      const placeholder = payload.forecast_is_placeholder !== false || state.reference.forecast_is_placeholder === true;
      $('#forecast-status').textContent = placeholder ? 'Illustrative baseline · MW' : 'P10 / P50 / P90 · MW';
      $('#forecast-issued').textContent = `Issued ${A.formatTime(payload.issue_time_utc,{includeDate:true})} · 24-hour horizon`;
      $('#forecast-explanation').replaceChildren(...payload.explanation.map(text => node('li','',text)));
      $('#explanation-title').textContent = payload.explanation_is_shap === true ? 'Model explanation · SHAP' : 'Illustrative forecast factors';
      $('#forecast-note').textContent = `${placeholder ? 'Illustrative, uncalibrated ranges.' : 'Model forecast.'}${readOnlyData() ? ' Recorded issue time.' : ''}`;
    } catch (error) { if (version === forecastVersion) { state.forecast = null; $('#forecast-status').textContent = 'Forecast unavailable'; $('#forecast-issued').textContent = ''; $('#forecast-chart').replaceChildren(); $('#forecast-explanation').replaceChildren(); $('#forecast-note').textContent = error.message; } }
  }
  function clearSelection() { state.focus = null; state.edge = null; syncMapFocus(); renderZone(); renderCorridors(); renderTransfers(); syncUrl(); announce('Whole network. Focus cleared.'); }
  function selectZone(key) { if (!state.reference?.zone_order.includes(key)) return; state.zone = key; state.edge = null; state.focus = 'zone'; renderZone(); renderCorridors(); renderTransfers(); syncMapFocus(); syncUrl(); if (state.tab === 'results') { state.tab = 'transfers'; applyView(); } if (state.tab === 'forecast') loadForecast(); announce(`${zoneName(key)} selected.`); }
  function selectEdge(key) { if (!state.reference?.edge_order.includes(key)) return; state.edge = key; state.focus = 'edge'; if (state.tab !== 'inspect') state.tab = 'transfers'; applyView(); renderCorridors(); renderTransfers(); syncMapFocus(); announce(`${key} corridor selected.`); }
  function pause() { clearInterval(timer); timer = undefined; state.playing = false; $('#play').textContent = 'Play'; $('#play').setAttribute('aria-pressed','false'); }
  function play() { if (state.playing) { pause(); return; } if (!state.series) return; if (state.step === 47) seek(0); state.playing = true; $('#play').textContent = 'Pause'; $('#play').setAttribute('aria-pressed','true'); timer = setInterval(() => { if (state.step >= 47) { pause(); return; } seek(state.step+1); },1000); }
  async function injectPreset(kind) {
    pause(); const status = $('#incident-status'); const buttons = [...document.querySelectorAll('[data-preset]')]; buttons.forEach(button => button.disabled = true);
    try {
      if (readOnlyData()) {
        const presetScenarios = { boundary:'b6_trip_windy_peak',cold:'cold_snap',nuclear:'nuclear_outage_low_wind' };
        const name = presetScenarios[kind]; if (!state.scenarios.some(scenario => scenario.name === name)) throw new Error('This pre-generated scenario is unavailable.');
        state.scenario = name; $('#scenario').value = name; state.step = kind === 'boundary' ? 38 : 34;
        if (!await loadEpisode()) throw new Error('The scenario could not be loaded. See the data error above.'); status.textContent = 'Loaded the corresponding generated scenario. No custom incident was posted.'; $('#incident-dialog').close(); announce(status.textContent); return;
      }
      const start = Number($('#incident-start').value); const duration = Number($('#incident-duration').value);
      if (!Number.isInteger(start) || start < 0 || start > 47 || !Number.isInteger(duration) || duration < 1 || duration > 48) throw new Error('Start must be 0–47 and duration 1–48 whole half-hours.');
      const target = kind === 'boundary' ? 'SSCO-NORT' : 'EAST';
      if (kind === 'boundary' && !state.reference.edge_order.includes(target)) throw new Error('The specified boundary is absent from the backend reference.');
      if (kind === 'nuclear' && !state.reference.zone_order.includes(target)) throw new Error('The specified outage zone is absent from the backend reference.');
      status.textContent = 'Applying incident…';
      if (kind === 'cold') for (const key of state.reference.zone_order) await api.incident(state.scenario,{ type:'demand_spike',target:key,start_step:start,duration_steps:duration,magnitude:1.18 });
      else await api.incident(state.scenario,{type:kind === 'boundary' ? 'line_trip' : 'generator_outage',target,start_step:start,duration_steps:duration,magnitude:kind === 'boundary' ? 1 : .9});
      state.step = start; if (!await loadEpisode()) throw new Error('The incident was posted, but refreshed results could not be loaded. Retry the episode.'); $('#incident-dialog').close(); announce('Incident applied to the selected scenario and all strategy series regenerated.');
    } catch (error) { status.textContent = error.message || String(error); }
    finally { buttons.forEach(button => button.disabled = false); }
  }
  function download(rows,name) {
    const content = rows.map(row => row.map(value => `"${String(value ?? '').replaceAll('"','""')}"`).join(',')).join('\r\n'); const url = URL.createObjectURL(new Blob(['\uFEFF'+content],{type:'text/csv;charset=utf-8;'})); const link = node('a'); link.href = url; link.download = name; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url),1000);
  }
  $('#scenario').addEventListener('change',event => { state.scenario = event.target.value; state.edge = null; state.focus = null; loadEpisode(); });
  $('#strategy').addEventListener('change',() => { state.strategy = 'optimiser'; loadEpisode(); });
  $('#zone').addEventListener('change',event => event.target.value ? selectZone(event.target.value) : clearSelection());
  $('#clear-map-selection').addEventListener('click',clearSelection);
  $('#time-step').addEventListener('input',event => { pause(); seek(Number(event.target.value)); });
  $('#previous-frame').addEventListener('click',() => { pause(); seek(state.step-1); }); $('#next-frame').addEventListener('click',() => { pause(); seek(state.step+1); }); $('#play').addEventListener('click',play);
  $('#split-view').addEventListener('click',() => { state.split = true; applyView(); }); $('#single-view').addEventListener('click',() => { state.split = false; applyView(); });
  $('#show-transfer-values').addEventListener('change',event => { state.showValues = event.target.checked; applyTransferOptions(); syncUrl(); });
  $('#animate-transfers').addEventListener('change',event => { state.animate = event.target.checked; applyTransferOptions(); syncUrl(); });
  $('#zoom-in').addEventListener('click',() => responseMap?.zoomBy(1.35)); $('#zoom-out').addEventListener('click',() => responseMap?.zoomBy(1/1.35)); $('#reset-map').addEventListener('click',() => responseMap?.reset());
  document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click',() => { state.tab = button.dataset.tab; applyView(); if (state.tab === 'forecast') loadForecast(); }));
  $('#open-incidents').addEventListener('click',() => { $('#incident-status').textContent = ''; $('#incident-dialog').showModal(); }); $('#open-notes').addEventListener('click',() => $('#notes-dialog').showModal());
  document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click',() => document.getElementById(button.dataset.close).close()));
  document.querySelectorAll('[data-preset]').forEach(button => button.addEventListener('click',() => injectPreset(button.dataset.preset)));
  $('#retry').addEventListener('click',() => init());
  $('#export-episode').addEventListener('click',() => { if (!state.series || !state.comparison) return; const episode = state.series.response; download([['JMap simulated episode',episode.scenario],['Strategy',episode.strategy],['Data mode',api.mode],[],['Timestamp UTC','Zone','Demand MW','Generation MW','Unserved MW','Storage SOC'],...episode.frames.flatMap(frame => state.reference.zone_order.map(key => [frame.timestamp_utc,key,frame.zones[key].demand_mw,frame.zones[key].generation_mw,frame.zones[key].unserved_mw,frame.zones[key].storage_soc]))],`jmap-${episode.scenario}-${episode.strategy}-episode.csv`); });
  $('#export-results').addEventListener('click',() => { if (!state.comparison) return; const comparison = A.compareResults(state.comparison,state.reference); download([['JMap simulated strategy comparison',comparison.scenario],[],['Strategy','Unserved MWh','Cost GBP','Penalty GBP (model)','Carbon tonnes','Curtailed MWh'],...comparison.rows.map(row => [row.key,row.totals.unserved_mwh,row.totals.cost_gbp,row.totals.penalty_gbp,row.totals.carbon_t,row.totals.curtailed_mwh])],`jmap-${comparison.scenario}-comparison.csv`); });
  $('#export-transfers').addEventListener('click',() => {
    if (!state.response || !state.series || $('#export-transfers').disabled) return;
    const summary = T.summarize(state.edges,state.response,state.zone);
    download([['JMap simulated transfers',state.series.response.scenario],['Strategy',state.series.response.strategy],['Timestamp UTC',state.response.timestamp_utc],['Data mode',api.mode],[],['Corridor','Topology from','Topology to','Flow source','Flow destination','Signed MW','Effective transfer MW','Current limit MW','Loading fraction','Status'],...summary.rows.map(row => [row.id,row.from,row.to,row.active ? row.source : '',row.active ? row.target : '',row.flowMw,row.effectiveMw,row.limitMw,row.loading,row.status])],`jmap-${state.series.response.scenario}-transfers-${state.step+1}.csv`);
  });
  window.addEventListener('pagehide',pause);
  init();
})();

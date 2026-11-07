/* UK energy explorer. All operational figures are an illustrative sample. */
(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const A = window.JMapAnalysis;
  const sites = window.JMAP_SITES || [];
  const technologies = {
    wind: { label: 'Wind', symbol: '⊙' }, solar: { label: 'Solar', symbol: '▪' },
    nuclear: { label: 'Nuclear', symbol: '◆' }, gas: { label: 'Gas', symbol: '▲' },
    hydro: { label: 'Hydro', symbol: '◊' }, biomass: { label: 'Biomass', symbol: '⊕' },
    storage: { label: 'Storage', symbol: '□' }, interconnector: { label: 'Interconnectors', symbol: '◇' }
  };
  const regions = { england: 'England', scotland: 'Scotland', wales: 'Wales', 'northern-ireland': 'Northern Ireland' };
  const presets = { all: Object.keys(technologies), 'low-carbon': ['wind', 'solar', 'nuclear', 'hydro'], flexible: ['storage', 'interconnector'] };
  const maxima = { output: Math.max(1, ...sites.map(s => s.output)), capacity: Math.max(1, ...sites.map(s => s.capacity)), utilisation: 100 };
  const number = value => value.toLocaleString('en-GB', { maximumFractionDigits: 1 });
  const fixed = value => value.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const gw = value => `${fixed(value / 1000)} GW`;
  const power = value => value >= 1000 ? gw(value) : `${number(value)} MW`;
  const percent = value => value === null ? '—' : value > 0 && value < .1 ? '<0.1%' : `${value.toFixed(1)}%`;
  const utilisation = site => site.capacity > 0 ? site.output / site.capacity * 100 : null;
  const state = { selectedTypes: new Set(presets.all), query: '', region: 'all', mode: 'output', view: 'map', analysis: 'mix', rank: 'output', sort: 'output', labels: false, selectedId: null, compared: [], filtered: [], summary: null };
  let map;
  let detailTrigger;

  function node(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = content;
    return element;
  }
  function announce(message) { $('#announcement').textContent = message; }
  function symbol(type) {
    const wrapper = node('span', 'tech-symbol');
    wrapper.setAttribute('aria-hidden', 'true');
    wrapper.append(window.EnergyMap?.createSymbol(type) || node('span', '', technologies[type].symbol));
    return wrapper;
  }
  function scope() { return state.region === 'all' ? 'United Kingdom' : regions[state.region]; }
  function readLocation() {
    const params = new URL(window.location.href).searchParams;
    state.region = Object.hasOwn(regions, params.get('region')) ? params.get('region') : 'all';
    state.query = params.get('q') || '';
    state.selectedTypes = new Set(params.has('types') ? params.get('types').split(',').filter(t => Object.hasOwn(technologies, t)) : presets.all);
    state.mode = ['output', 'capacity', 'utilisation'].includes(params.get('measure')) ? params.get('measure') : 'output';
    state.analysis = ['mix', 'regions', 'leaders'].includes(params.get('analysis')) ? params.get('analysis') : 'mix';
    state.rank = ['output', 'capacity', 'utilisation'].includes(params.get('rank')) ? params.get('rank') : 'output';
    state.sort = ['output', 'capacity', 'utilisation', 'name'].includes(params.get('sort')) ? params.get('sort') : 'output';
    state.labels = params.get('names') === '1';
    state.compared = [...new Set((params.get('compare') || '').split(','))].filter(id => sites.some(site => site.id === id)).slice(0, 3);
    state.view = window.location.hash === '#directory' ? 'list' : 'map';
  }
  function syncUrl() {
    const url = new URL(window.location.href);
    const set = (key, value, defaultValue) => { if (value === defaultValue) url.searchParams.delete(key); else url.searchParams.set(key, value); };
    set('region', state.region, 'all'); set('q', state.query, '');
    set('types', Object.keys(technologies).filter(t => state.selectedTypes.has(t)).join(','), presets.all.join(','));
    set('measure', state.mode, 'output'); set('analysis', state.analysis, 'mix');
    set('rank', state.rank, 'output'); set('sort', state.sort, 'output');
    set('names', state.labels ? '1' : '', ''); set('compare', state.compared.join(','), '');
    if (state.view === 'list') url.hash = 'directory';
    else if (url.hash === '#directory') url.hash = '';
    if (url.href !== window.location.href) history.replaceState(null, '', url.href);
  }
  function sameTypes(types) { return state.selectedTypes.size === types.length && types.every(t => state.selectedTypes.has(t)); }
  function makeFilters() {
    Object.entries(technologies).forEach(([type, technology]) => {
      const label = node('label', 'filter-row');
      const input = node('input'); input.type = 'checkbox'; input.value = type; input.checked = state.selectedTypes.has(type); input.setAttribute('aria-label', technology.label);
      const count = node('span', 'filter-count'); count.id = `count-${type}`;
      label.append(input, symbol(type), node('span', '', technology.label), count);
      input.addEventListener('change', () => { if (input.checked) state.selectedTypes.add(type); else state.selectedTypes.delete(type); render(); });
      $('#technology-list').append(label);
    });
  }
  function matchesSearch(site) {
    const text = `${site.name} ${technologies[site.type].label} ${site.type} ${regions[site.region]}`.toLocaleLowerCase('en-GB');
    return state.query.toLocaleLowerCase('en-GB').split(/\s+/).filter(Boolean).every(term => text.includes(term));
  }
  function setTypes(types) {
    const focusedType = document.activeElement.dataset.technology;
    state.selectedTypes = new Set(types);
    document.querySelectorAll('.filter-row input').forEach(input => { input.checked = state.selectedTypes.has(input.value); });
    render();
    if (focusedType) document.querySelector(`[data-technology="${focusedType}"]`)?.focus({ preventScroll: true });
  }
  function setRegion(region) {
    const focusedRegion = document.activeElement.dataset.region;
    state.region = region; $('#region').value = region;
    render(); setView('map'); map?.focusRegion(region);
    if (focusedRegion) document.querySelector(`[data-region="${focusedRegion}"]`)?.focus({ preventScroll: true });
    announce(`${scope()} selected. ${state.filtered.length} matching sites.`);
  }
  function render() {
    const candidates = sites.filter(site => (state.region === 'all' || site.region === state.region) && matchesSearch(site));
    state.filtered = candidates.filter(site => state.selectedTypes.has(site.type));
    state.summary = A.summarise(state.filtered);
    Object.keys(technologies).forEach(type => { $(`#count-${type}`).textContent = candidates.filter(site => site.type === type).length; });
    document.querySelectorAll('[data-preset]').forEach(button => button.setAttribute('aria-pressed', String(sameTypes(presets[button.dataset.preset]))));
    $('#total-output').textContent = fixed(state.summary.output / 1000);
    $('#total-capacity').textContent = fixed(state.summary.capacity / 1000);
    $('#low-carbon').textContent = state.summary.lowCarbonShare === null ? '—' : Math.round(state.summary.lowCarbonShare);
    $('#total-sites').textContent = state.filtered.length.toString().padStart(2, '0'); $('#all-sites').textContent = sites.length;
    $('#summary-scope').textContent = scope(); $('#map-scope').textContent = scope();
    $('#results-label').textContent = `${state.filtered.length} of ${sites.length} sites`;
    $('#map-empty').hidden = state.filtered.length > 0; $('#directory-empty').hidden = state.filtered.length > 0;
    const typeSummary = sameTypes(presets.all) ? 'All technologies' : state.selectedTypes.size === 0 ? 'No technologies' : state.selectedTypes.size === 1 ? technologies[[...state.selectedTypes][0]].label : `${state.selectedTypes.size} technologies`;
    $('#filter-summary').textContent = `${typeSummary} / ${scope()}${state.query ? ' / Search active' : ''}`;
    $('#mobile-filter-count').textContent = typeSummary;
    $('#export-sites').disabled = !state.filtered.length; $('#fit-results').disabled = !state.filtered.length || !map;
    if (!state.filtered.some(site => site.id === state.selectedId)) closeDetails(false);
    map?.setSites(state.filtered, state.mode);
    renderDirectory(); renderAnalysis(); renderComparison(); renderLegend();
    if (state.selectedId) fillDetails(sites.find(site => site.id === state.selectedId));
    syncUrl();
  }

  function bar(value) { const track = node('span', 'analysis-bar'); const fill = node('span'); fill.style.width = `${Math.max(0, Math.min(100, value))}%`; track.append(fill); return track; }
  function renderAnalysis() {
    $('#analysis-scope').textContent = state.analysis === 'regions' ? 'UK comparison / current search & technologies' : `${scope()} / ${state.filtered.length} filtered sites`;
    $('#supply-generation').textContent = gw(state.summary.generation); $('#supply-storage').textContent = gw(state.summary.storage); $('#supply-imports').textContent = gw(state.summary.imports);
    const mix = $('#mix-breakdown'); mix.replaceChildren();
    A.aggregateByTechnology(state.filtered).forEach(row => {
      const button = node('button', 'mix-row'); button.type = 'button'; button.dataset.technology = row.key;
      button.setAttribute('aria-label', `Focus ${technologies[row.key].label}, ${power(row.output)}, ${percent(row.share)} of filtered supply`);
      const top = node('span', 'mix-row-top'); top.append(symbol(row.key), node('span', '', technologies[row.key].label), node('span', 'mix-value', power(row.output)));
      const foot = node('span', 'mix-row-foot'); foot.append(node('span', '', `${row.siteCount} ${row.siteCount === 1 ? 'site' : 'sites'}`), node('span', '', percent(row.share)));
      button.append(top, bar(row.share), foot); button.addEventListener('click', () => setTypes([row.key])); mix.append(button);
    });
    $('#mix-reset').disabled = sameTypes(presets.all);
    // Compare nations with the same technology/search selection across the UK,
    // independently of the geographic focus used by the map and headline totals.
    const nationwide = sites.filter(site => state.selectedTypes.has(site.type) && matchesSearch(site));
    const regionContainer = $('#region-breakdown'); regionContainer.replaceChildren();
    A.aggregateByRegion(nationwide).forEach(row => {
      const button = node('button', 'nation-row'); button.type = 'button'; button.dataset.region = row.key; button.disabled = !row.siteCount;
      const top = node('span', 'nation-top'); top.append(node('span', '', regions[row.key]), node('strong', '', gw(row.output)));
      const foot = node('small'); foot.append(node('span', '', `${row.siteCount} sites / ${percent(row.share)} of UK sample`), node('span', '', `Util. ${percent(row.utilisation)}`));
      button.append(top, bar(row.share), foot); button.addEventListener('click', () => setRegion(row.key)); regionContainer.append(button);
    });
    const leaders = $('#top-sites'); leaders.replaceChildren();
    sortedSites(state.filtered, state.rank).slice(0, 5).forEach((site, index) => {
      const button = node('button', 'leader-row'); button.type = 'button'; button.dataset.leader = site.id;
      const content = node('span'); content.append(node('span', 'leader-name', site.name));
      const meta = node('span', 'leader-meta'); meta.append(node('span', '', technologies[site.type].label), node('strong', '', state.rank === 'utilisation' ? percent(utilisation(site)) : power(site[state.rank]))); content.append(meta);
      button.append(node('span', 'leader-index', String(index + 1).padStart(2, '0')), content);
      button.addEventListener('click', () => { setView('map'); selectSite(site.id, button); map?.focusSite(site.id); }); leaders.append(button);
    });
    $('#analysis-empty').hidden = state.filtered.length > 0 || state.analysis === 'regions';
    applyAnalysisTab();
  }
  function applyAnalysisTab() {
    document.querySelectorAll('[data-analysis]').forEach(button => {
      const active = button.dataset.analysis === state.analysis;
      button.classList.toggle('selected', active); button.setAttribute('aria-pressed', String(active));
    });
    ['mix', 'regions', 'leaders'].forEach(key => { $(`#analysis-${key}`).hidden = state.analysis !== key; });
  }
  function renderLegend() {
    const labels = { output: ['Site output', 'Same scale across every filter.'], capacity: ['Site capacity', 'Same scale across every filter.'], utilisation: ['Capacity utilisation', 'Output ÷ capacity. Not efficiency.'] };
    $('#legend-title').textContent = labels[state.mode][0]; $('#legend-description').textContent = labels[state.mode][1];
    const values = state.mode === 'utilisation' ? [25, 50, 100] : [100, 1000, maxima[state.mode]];
    $('#legend-scale').replaceChildren();
    values.forEach(value => {
      const item = node('span', 'legend-benchmark'); const circle = node('span');
      const radius = window.EnergyMap?.radiusForValue(value, maxima[state.mode]) || 4;
      circle.style.width = `${radius * 2}px`; circle.style.height = `${radius * 2}px`;
      item.append(circle, node('small', '', state.mode === 'utilisation' ? `${value}%` : value < 1000 ? `${number(value)} MW` : `${(value / 1000).toFixed(value === 1000 ? 0 : 2)} GW`));
      $('#legend-scale').append(item);
    });
  }
  function sortedSites(list, key) {
    return [...list].sort((a, b) => key === 'name' ? a.name.localeCompare(b.name, 'en-GB') : key === 'utilisation' ? (utilisation(b) ?? -1) - (utilisation(a) ?? -1) || a.name.localeCompare(b.name) : b[key] - a[key] || a.name.localeCompare(b.name));
  }
  function renderDirectory() {
    const body = $('#directory-body'); body.replaceChildren();
    sortedSites(state.filtered, state.sort).forEach(site => {
      const row = node('tr'); const nameCell = node('td'); nameCell.append(node('span', 'site-row-name', site.name), node('span', 'site-row-region', regions[site.region]));
      row.append(nameCell, node('td', '', technologies[site.type].label), node('td', '', `${number(site.output)} MW`), node('td', '', `${number(site.capacity)} MW`), node('td', '', percent(utilisation(site))));
      const actions = node('td'); const group = node('span', 'directory-actions');
      const locate = node('button', '', 'Locate ↗'); locate.type = 'button'; locate.setAttribute('aria-label', `Locate ${site.name} on map`);
      locate.addEventListener('click', () => { setView('map'); selectSite(site.id, $('#list-view')); map?.focusSite(site.id); $('#workspace').scrollIntoView({ block: 'nearest' }); $('#close-detail').focus({ preventScroll: true }); });
      const compare = node('button', '', state.compared.includes(site.id) ? 'Added ✓' : 'Compare +'); compare.type = 'button'; compare.dataset.compare = site.id; compare.setAttribute('aria-pressed', String(state.compared.includes(site.id))); compare.setAttribute('aria-label', `Compare ${site.name}`);
      compare.disabled = state.compared.length >= 3 && !state.compared.includes(site.id);
      compare.addEventListener('click', () => toggleCompare(site.id)); group.append(locate, compare); actions.append(group); row.append(actions); body.append(row);
    });
  }
  function fillDetails(site) {
    if (!site) return;
    $('#detail-type').textContent = `${technologies[site.type].label} / ${regions[site.region]}`;
    $('#detail-name').textContent = site.name; $('#detail-location').textContent = `${regions[site.region]} · United Kingdom`;
    $('#detail-output-label').textContent = site.type === 'interconnector' ? 'Illustrative imports' : site.type === 'storage' ? 'Illustrative discharge' : 'Illustrative generation';
    $('#detail-output').textContent = number(site.output); $('#detail-utilisation').textContent = percent(utilisation(site));
    $('#utilisation-fill').style.width = `${Math.min(100, utilisation(site) || 0)}%`;
    $('#detail-capacity').textContent = `${number(site.capacity)} MW`; $('#detail-operator').textContent = site.operator;
    $('#detail-share').textContent = state.summary.output ? percent(site.output / state.summary.output * 100) : '—';
    $('#detail-coordinates').textContent = `${Math.abs(site.lat).toFixed(2)}° ${site.lat >= 0 ? 'N' : 'S'}, ${Math.abs(site.lon).toFixed(2)}° ${site.lon >= 0 ? 'E' : 'W'}`;
    $('#detail-note').textContent = site.note;
    const added = state.compared.includes(site.id); const button = $('#compare-site'); button.setAttribute('aria-pressed', String(added));
    button.firstChild.textContent = added ? 'Remove from comparison ' : state.compared.length >= 3 ? 'Comparison full (3 sites) ' : 'Add to comparison ';
    button.lastElementChild.textContent = added ? '−' : '+'; button.disabled = !added && state.compared.length >= 3;
  }
  function selectSite(id, trigger) {
    if (id === null) { closeDetails(false); return; }
    const site = state.filtered.find(item => item.id === id); if (!site) return;
    detailTrigger = trigger || document.querySelector(`[data-site-id="${id}"]`) || $('#energy-map'); state.selectedId = id;
    map?.selectSite(id); fillDetails(site); $('#analysis-content').hidden = true; $('#site-detail').hidden = false;
    announce(`${site.name}. ${number(site.output)} megawatts sample output. ${percent(utilisation(site))} utilisation. Details opened.`);
    if (window.matchMedia('(max-width: 1000px)').matches) requestAnimationFrame(() => $('#site-detail').scrollIntoView({ block: 'nearest', behavior: 'instant' }));
  }
  function closeDetails(restoreFocus = true) {
    const wasOpen = !$('#site-detail').hidden; state.selectedId = null; $('#site-detail').hidden = true; $('#analysis-content').hidden = false; map?.selectSite(null);
    if (restoreFocus && wasOpen) {
      const target = detailTrigger?.isConnected && !detailTrigger.closest('[hidden]') ? detailTrigger : $('#energy-map');
      target.focus({ preventScroll: !window.matchMedia('(max-width: 1000px)').matches }); announce('Site details closed. Analysis restored.');
    }
  }
  function toggleCompare(id) {
    const focusedCompare = document.activeElement.dataset.compare;
    const focusedRemove = document.activeElement.dataset.removeComparison;
    if (state.compared.includes(id)) state.compared = state.compared.filter(item => item !== id);
    else if (state.compared.length < 3) state.compared.push(id);
    else { announce('You can compare up to three sites. Remove one to add another.'); return; }
    renderComparison(); renderDirectory(); if (state.selectedId) fillDetails(sites.find(site => site.id === state.selectedId)); syncUrl();
    if (focusedCompare) document.querySelector(`[data-compare="${focusedCompare}"]`)?.focus({ preventScroll: true });
    else if (focusedRemove) ($('#comparison-body button') || $('#list-view')).focus({ preventScroll: true });
    announce(`${state.compared.length} of three comparison slots used. Comparison is below the map.`);
  }
  function comparisonRows(members) {
    return [
      ['Technology', ...members.map(s => technologies[s.type].label)], ['Nation', ...members.map(s => regions[s.region])],
      ['Sample output', ...members.map(s => `${number(s.output)} MW`)], ['Capacity', ...members.map(s => `${number(s.capacity)} MW`)],
      ['Utilisation', ...members.map(s => percent(utilisation(s)))]
    ];
  }
  function renderComparison() {
    $('#comparison').hidden = state.compared.length === 0; $('#comparison-body').replaceChildren();
    $('#jump-comparison').hidden = state.compared.length === 0; $('#comparison-count').textContent = state.compared.length;
    if (!state.compared.length) return;
    const members = state.compared.map(id => sites.find(s => s.id === id));
    $('#comparison-caption').textContent = `${members.length} of 3 sites selected. ${members.length === 1 ? 'Add another site to compare.' : 'Selections stay pinned when filters change.'}`;
    const wrap = node('div', 'comparison-table-scroll'); const table = node('table', 'comparison-table'); const head = node('thead'); const headRow = node('tr');
    const first = node('th', '', 'Site'); first.scope = 'col'; headRow.append(first);
    members.forEach(site => {
      const th = node('th'); th.scope = 'col'; th.append(node('span', '', site.name));
      if (!state.filtered.some(s => s.id === site.id)) th.append(node('span', 'comparison-badge', 'Outside current filters'));
      const remove = node('button', '', 'Remove ×'); remove.type = 'button'; remove.dataset.removeComparison = site.id; remove.setAttribute('aria-label', `Remove ${site.name} from comparison`); remove.addEventListener('click', () => toggleCompare(site.id)); th.append(remove); headRow.append(th);
    });
    head.append(headRow); const body = node('tbody');
    comparisonRows(members).forEach(([label, ...values]) => { const row = node('tr'); const heading = node('th', '', label); heading.scope = 'row'; row.append(heading, ...values.map(value => node('td', '', value))); body.append(row); });
    table.append(head, body); wrap.append(table); $('#comparison-body').append(wrap);
  }
  function setView(view) {
    state.view = view; $('#map-stage').hidden = view !== 'map'; $('#directory').hidden = view !== 'list'; $('.map-measures').hidden = view !== 'map';
    ['map', 'list'].forEach(key => { $(`#${key}-view`).classList.toggle('selected', view === key); $(`#${key}-view`).setAttribute('aria-pressed', String(view === key)); });
    $('#size-mode').disabled = view !== 'map'; $('#fit-results').disabled = !state.filtered.length || !map;
    $('#visible-sites').hidden = view !== 'map'; $('#zoom-label').hidden = view !== 'map';
    if (view === 'list') renderDirectory(); syncUrl();
  }
  function resetFilters() {
    state.query = ''; state.region = 'all'; $('#site-search').value = ''; $('#region').value = 'all';
    closeDetails(false); setTypes(presets.all); map?.reset(); announce('Filters reset. All UK sample sites selected.');
  }
  function downloadCsv(rows, filename) {
    const csv = rows.map(row => row.map(value => `"${String(value ?? '').replaceAll('"', '""')}"`).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })); const link = node('a'); link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function exportAnalysis() {
    if (!state.filtered.length) return;
    const summary = state.summary;
    const nationwide = sites.filter(site => state.selectedTypes.has(site.type) && matchesSearch(site));
    const rows = [['JMap UK energy sample — illustrative data, not live telemetry or national totals'], ['Filtered summary and site scope', scope()], ['Search', state.query], ['Output unit', 'MW'], [], ['Filtered supply', 'MW'], ['Generation', summary.generation], ['Storage discharge', summary.storage], ['Imports', summary.imports], ['Total supplied', summary.output], [], ['Technology', 'Sites', 'Output (MW)', 'Capacity (MW)', 'Share of filtered supply (%)'], ...A.aggregateByTechnology(state.filtered).map(r => [technologies[r.key].label, r.siteCount, r.output, r.capacity, r.share]), [], ['Nation comparison — UK with current search and technologies', 'Sites', 'Output (MW)', 'Capacity (MW)', 'Share of matching UK output (%)'], ...A.aggregateByRegion(nationwide).map(r => [regions[r.key], r.siteCount, r.output, r.capacity, r.share]), [], ['Sites', 'Technology', 'Nation', 'Illustrative output (MW)', 'Capacity (MW)', 'Utilisation (%)', 'Latitude', 'Longitude', 'Operator'], ...state.filtered.map(s => [s.name, technologies[s.type].label, regions[s.region], s.output, s.capacity, utilisation(s), s.lat, s.lon, s.operator])];
    downloadCsv(rows, `jmap-${state.region}-sample-analysis.csv`); announce(`Exported analysis and ${state.filtered.length} sample sites.`);
  }
  function showDialog(kind) {
    const body = $('#dialog-body'); body.replaceChildren();
    if (kind === 'guide') {
      $('#dialog-title').textContent = 'From points to perspective.';
      body.append(node('p', '', 'Start with a nation or a technology preset. Use Fit results to bring every matching site into view. Site names can be switched on above the map.'), node('p', '', 'Shape identifies technology. The measured circles in the legend explain marker size; the scale stays fixed when you filter. Utilisation is output divided by capacity, not plant efficiency.'), node('p', '', 'Energy mix explains the filtered supply. Nations compares the same technologies and search across all four nations. Top sites ranks the filtered sites. Select a site and add up to three to the comparison below the map.'));
      const shortcuts = node('dl');
      [['/', 'Find a site'], ['+ / −', 'Zoom the focused map'], ['Arrow keys', 'Pan the focused map'], ['Home', 'Whole UK view'], ['Tab, Enter', 'Explore and select sites'], ['Esc', 'Close site details or this guide']].forEach(([key, action]) => { const row = node('div'); row.append(node('dt', '', key), node('dd', '', action)); shortcuts.append(row); });
      body.append(shortcuts, node('p', '', 'Drag to pan, scroll to zoom, or use two fingers to pinch on a touch screen. Use the directory for closely located sites.'));
    } else {
      $('#dialog-title').textContent = 'Understand the scope.';
      body.append(node('p', '', `This curated sample contains ${sites.length} sites across England, Scotland, Wales, and Northern Ireland. Outputs are synthetic examples. Capacities, coordinates, and operator labels are approximate. The sample does not describe national totals or a single UK electricity balance.`), node('p', '', 'Power supplied adds generation, storage discharge, and interconnector imports. Stored energy is not counted as new generation. The low-carbon share is wind, solar, nuclear, and conventional hydro output divided by generation output; storage and imports are excluded.'), node('p', '', 'The map shows where assets are located. It contains no demand, transmission flows, cross-border transfers, network constraints, or real-time measurements. Regional shares describe the selected sample and do not measure regional self-sufficiency.'), node('p', '', 'Headlines, energy mix, and rankings follow your filters, independently of map zoom. Nations compares your search and technologies across all four nations. Pinned comparison sites remain available outside current filters.'));
      const paragraph = node('p'); const link = node('a', '', 'Geography: Natural Earth (public domain) ↗'); link.href = 'https://www.naturalearthdata.com/about/terms-of-use/'; link.target = '_blank'; link.rel = 'noreferrer'; paragraph.append(link); body.append(paragraph);
    }
    $('#info-dialog').showModal();
  }

  readLocation(); makeFilters();
  $('#site-search').value = state.query; $('#region').value = state.region; $('#size-mode').value = state.mode; $('#site-labels').checked = state.labels; $('#rank-by').value = state.rank; $('#sort-sites').value = state.sort;
  $('#energy-map').addEventListener('mapviewchange', event => { $('#zoom-label').textContent = Math.abs(event.detail.zoom - 1) < .05 ? 'UK view' : `${event.detail.zoom.toFixed(1)}× zoom`; $('#visible-sites').textContent = `${event.detail.visibleSiteIds.length} on map`; });
  if (window.EnergyMap && window.JMAP_GEOGRAPHY) {
    map = new window.EnergyMap({ element: $('#energy-map'), geography: window.JMAP_GEOGRAPHY, scaleMaxima: maxima, onSelect: id => selectSite(id) });
    map.setLabelVisibility(state.labels);
  } else { state.view = 'list'; $('#map-view').disabled = true; announce('Map could not load. Use the directory and analysis panels.'); }
  render(); setView(state.view); if (state.region !== 'all') map?.focusRegion(state.region);
  if (state.view === 'list') requestAnimationFrame(() => $('#workspace').scrollIntoView({ block: 'start' }));
  $('#site-search').addEventListener('input', event => { state.query = event.target.value.trim(); render(); });
  $('#region').addEventListener('change', event => setRegion(event.target.value));
  $('#size-mode').addEventListener('change', event => { state.mode = event.target.value; map?.setSites(state.filtered, state.mode); renderLegend(); syncUrl(); });
  $('#site-labels').addEventListener('change', event => { state.labels = event.target.checked; map?.setLabelVisibility(state.labels); syncUrl(); });
  $('#sort-sites').addEventListener('change', event => { state.sort = event.target.value; renderDirectory(); syncUrl(); });
  $('#rank-by').addEventListener('change', event => { state.rank = event.target.value; renderAnalysis(); syncUrl(); });
  document.querySelectorAll('[data-preset]').forEach(button => button.addEventListener('click', () => setTypes(presets[button.dataset.preset])));
  document.querySelectorAll('[data-analysis]').forEach(button => button.addEventListener('click', () => { closeDetails(false); state.analysis = button.dataset.analysis; renderAnalysis(); syncUrl(); }));
  $('#select-all').addEventListener('click', () => setTypes(presets.all)); $('#clear-types').addEventListener('click', () => setTypes([])); $('#mix-reset').addEventListener('click', () => setTypes(presets.all));
  $('#reset-filters').addEventListener('click', resetFilters); $('#empty-reset').addEventListener('click', resetFilters);
  $('#toggle-filters').addEventListener('click', event => { const open = $('.sidebar').classList.toggle('is-open'); event.currentTarget.setAttribute('aria-expanded', String(open)); });
  $('#zoom-in').addEventListener('click', () => map?.zoomBy(1.35)); $('#zoom-out').addEventListener('click', () => map?.zoomBy(1 / 1.35)); $('#reset-map').addEventListener('click', () => map?.reset());
  $('#fit-results').addEventListener('click', () => { setView('map'); map?.fitSites(state.filtered); announce(`${state.filtered.length} matching sites framed on the map.`); });
  $('#focus-site').addEventListener('click', () => { setView('map'); map?.focusSite(state.selectedId); if (window.matchMedia('(max-width: 1000px)').matches) $('#map-stage').scrollIntoView({ block: 'nearest' }); });
  $('#close-detail').addEventListener('click', () => closeDetails()); $('#back-analysis').addEventListener('click', () => { closeDetails(false); $('[data-analysis].selected').focus(); });
  $('#compare-site').addEventListener('click', () => toggleCompare(state.selectedId));
  $('#clear-comparison').addEventListener('click', () => { state.compared = []; renderComparison(); renderDirectory(); if (state.selectedId) fillDetails(sites.find(s => s.id === state.selectedId)); syncUrl(); ($('#site-detail').hidden ? $('#list-view') : $('#compare-site')).focus({ preventScroll: true }); announce('Comparison cleared.'); });
  $('#jump-comparison').addEventListener('click', () => { $('#comparison').scrollIntoView({ block: 'start' }); $('#comparison-title').focus({ preventScroll: true }); });
  $('#export-comparison').addEventListener('click', () => { const members = state.compared.map(id => sites.find(s => s.id === id)); downloadCsv([['JMap illustrative sample site comparison'], ['Measure', ...members.map(s => s.name)], ...comparisonRows(members)], 'jmap-sample-comparison.csv'); announce('Comparison exported.'); });
  $('#map-view').addEventListener('click', () => setView('map')); $('#list-view').addEventListener('click', () => setView('list'));
  $('#directory-nav').addEventListener('click', event => { event.preventDefault(); setView('list'); $('#workspace').scrollIntoView({ block: 'start' }); $('#list-view').focus({ preventScroll: true }); });
  window.addEventListener('hashchange', () => setView(window.location.hash === '#directory' ? 'list' : 'map'));
  $('#export-sites').addEventListener('click', exportAnalysis); $('#about-data').addEventListener('click', () => showDialog('data')); $('#coverage-details').addEventListener('click', () => showDialog('data')); $('#keyboard-help').addEventListener('click', () => showDialog('guide'));
  $('#close-dialog').addEventListener('click', () => $('#info-dialog').close()); $('#dialog-done').addEventListener('click', () => $('#info-dialog').close());
  $('#info-dialog').addEventListener('click', event => { if (event.target !== event.currentTarget) return; const b = event.target.getBoundingClientRect(); if (event.clientX < b.left || event.clientX > b.right || event.clientY < b.top || event.clientY > b.bottom) event.target.close(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('#info-dialog').open) closeDetails(); if (event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey && !$('#info-dialog').open && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) { event.preventDefault(); $('#site-search').focus(); } });
})();

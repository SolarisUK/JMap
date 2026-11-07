/* Official annual electricity context. Independent of the illustrative site map. */
(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const data = window.JMAP_REGIONS;
  const balance = window.JMapBalance;
  const known = value => typeof value === 'number' && Number.isFinite(value);
  const number = value => !known(value) ? '—' : value.toLocaleString('en-GB', { maximumFractionDigits: 2, minimumFractionDigits: 2 });
  const percentage = value => !known(value) ? '—' : `${value.toFixed(1)}%`;
  const signed = value => value === null ? '—' : `${value > 0 ? '+' : value < 0 ? '−' : ''}${number(Math.abs(value))}`;
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  if (!data?.regions?.length || !balance) {
    $('#balance-data-error').hidden = false;
    $('#export-balance').disabled = true;
    return;
  }
  const initial = new URL(window.location.href).searchParams;
  const sliderValue = key => {
    const value = Number(initial.get(key) || 0);
    return Number.isFinite(value) ? Math.round(Math.min(40, Math.max(0, value)) / 5) * 5 : 0;
  };
  const sortModes = ['coverage', 'deficit', 'generation', 'name'];
  const state = {
    demand: sliderValue('demandIncrease'),
    reduction: sliderValue('generationReduction'),
    sort: sortModes.includes(initial.get('balanceSort')) ? initial.get('balanceSort') : 'coverage'
  };
  const baseline = balance.analyseRegions(data.regions);
  const baselineMax = Math.max(1, ...baseline.map(row => Math.abs(row.balanceTWh)));
  const isScenario = () => state.demand !== 0 || state.reduction !== 0;
  const results = () => balance.analyseRegions(data.regions, { demandChangePercent: state.demand, generationChangePercent: -state.reduction });
  const compareKnown = (a, b, field, direction = 1) => {
    if (!known(a[field])) return known(b[field]) ? 1 : a.key.localeCompare(b.key);
    if (!known(b[field])) return -1;
    return (a[field] - b[field]) * direction || a.key.localeCompare(b.key);
  };
  function sortedResults() {
    const rows = results();
    if (state.sort === 'deficit') rows.sort((a, b) => compareKnown(a, b, 'balanceTWh'));
    if (state.sort === 'generation') rows.sort((a, b) => compareKnown(a, b, 'generationTWh', -1));
    if (state.sort === 'name') rows.sort((a, b) => a.name.localeCompare(b.name, 'en-GB'));
    return rows;
  }

  function syncUrl() {
    const url = new URL(window.location.href);
    [['demandIncrease', state.demand, 0], ['generationReduction', state.reduction, 0], ['balanceSort', state.sort, 'coverage']].forEach(([key, value, defaultValue]) => {
      if (value === defaultValue) url.searchParams.delete(key);
      else url.searchParams.set(key, value);
    });
    if (url.href !== window.location.href) history.replaceState(null, '', url.href);
  }
  function insight(title, value, detail) {
    const link = node('a'); link.href = '#regional-balance';
    link.append(node('span', 'insight-title', title), node('span', 'insight-value', value), node('span', 'insight-detail', detail), node('span', 'insight-source', `${data.year} official annual data · View balance ↓`));
    return link;
  }
  const highest = baseline.find(row => row.coveragePercent !== null);
  const largestDeficit = [...baseline].filter(row => row.balanceTWh < 0).sort((a, b) => a.balanceTWh - b.balanceTWh)[0];
  const largestGenerator = [...baseline].sort((a, b) => b.generationTWh - a.generationTWh)[0];
  const insights = $('#distribution-insights');
  if (highest) insights.append(insight('Most generation relative to demand', highest.name, `${percentage(highest.coveragePercent)} of gross annual demand`));
  if (largestDeficit) insights.append(insight('Largest annual deficit', `${number(-largestDeficit.balanceTWh)} TWh`, `${largestDeficit.name} · covered by net imports`));
  if (largestGenerator) insights.append(insight('Largest electricity generator', largestGenerator.name, `${number(largestGenerator.generationTWh)} TWh generated over the year`));

  function render() {
    const scenario = isScenario();
    const rows = sortedResults();
    $('#balance-data-year').textContent = scenario ? `Scenario · ${data.year} baseline` : `${data.year} · DESNZ official data`;
    $('#balance-data-year').classList.toggle('is-scenario', scenario);
    $('#balance-context').textContent = scenario
      ? `Illustrative annual scenario: demand +${state.demand}%, generation −${state.reduction}%. Sample site filters do not apply.`
      : 'Annual energy in TWh. Gross demand includes losses and own use. Sample site filters do not apply.';
    $('#balance-table-caption').textContent = scenario
      ? `Illustrative annual scenario based on ${data.year}: demand up ${state.demand} percent, generation down ${state.reduction} percent. Not an outage forecast.`
      : `DESNZ ${data.year} annual gross generation, gross demand, annual balance and generation to demand ratio.`;
    $('#scenario-status').textContent = scenario ? 'Scenario results shown in the table. Not a shortage forecast.' : 'Showing the published baseline.';
    $('#demand-change-value').textContent = `+${state.demand}%`;
    $('#generation-change-value').textContent = `−${state.reduction}%`;
    $('#reset-scenario').disabled = !scenario;
    const body = $('#balance-rows'); body.replaceChildren();
    const maximum = Math.max(baselineMax, ...rows.map(row => Math.abs(row.balanceTWh || 0)));
    rows.forEach(row => {
      const tr = node('tr'); tr.dataset.nation = row.key;
      const name = node('th', '', row.name); name.scope = 'row';
      const explore = node('button', 'nation-explore', 'Explore sample sites ↗'); explore.type = 'button';
      explore.setAttribute('aria-label', `Explore ${row.name} sample sites on the map`);
      explore.addEventListener('click', () => document.dispatchEvent(new CustomEvent('jmapregionfocus', { detail: row.key })));
      name.append(explore);
      const generation = node('td', '', number(row.generationTWh));
      const renewable = known(row.renewableTWh) && row.baselineGenerationTWh > 0 ? row.renewableTWh / row.baselineGenerationTWh * 100 : null;
      generation.append(node('span', 'coverage-context', renewable === null ? 'Renewable share unavailable' : `${percentage(renewable)} renewable${scenario ? ' in baseline' : ''}`));
      const demand = node('td', '', number(row.consumptionTWh));
      const cell = node('td'); const deficit = row.balanceTWh < 0;
      cell.append(node('strong', `balance-number${deficit ? ' is-deficit' : ''}`, `${signed(row.balanceTWh)} TWh`));
      const track = node('div', 'balance-track'); track.setAttribute('aria-hidden', 'true');
      const fill = node('span', `balance-fill${deficit ? ' is-deficit' : ''}`);
      const width = Math.abs(row.balanceTWh || 0) / maximum * 50;
      fill.style.width = `${width}%`; fill.style.left = `${deficit ? 50 - width : 50}%`; track.append(fill);
      cell.append(track, node('span', 'balance-status', row.status === 'annual-deficit' ? 'Annual deficit' : row.status === 'annual-surplus' ? 'Annual surplus' : row.status === 'balanced' ? 'Balanced' : 'Unknown'));
      const coverage = node('td'); coverage.append(node('span', 'coverage-ratio', percentage(row.coveragePercent)));
      coverage.append(node('span', 'coverage-context', row.coveragePercent === null ? 'Ratio unavailable' : deficit ? `${percentage(row.shortfallPercent)} annual gap` : row.status === 'balanced' ? 'Matches annual demand' : 'Above annual demand'));
      tr.append(name, generation, demand, cell, coverage); body.append(tr);
    });
    const mostDependent = [...rows].filter(row => row.shortfallPercent > 0).sort((a, b) => b.shortfallPercent - a.shortfallPercent)[0];
    $('#balance-risk-insight').textContent = mostDependent
      ? scenario
        ? `In this scenario, ${mostDependent.name} has the largest relative generation gap: ${percentage(mostDependent.shortfallPercent)} of gross demand. This does not model whether transfers could cover it.`
        : `In ${data.year}, ${mostDependent.name} had the greatest net import reliance relative to demand: ${percentage(mostDependent.shortfallPercent)}. Those imports covered the annual deficit.`
      : rows.every(row => row.balanceTWh !== null && row.balanceTWh >= 0)
        ? 'All four nations generate at least their gross annual demand in this scenario. Hourly shortages and network constraints remain unassessed.'
        : 'There is not enough annual data to compare reliance on supply from elsewhere. Local shortage risk remains unassessed.';
    syncUrl();
    document.dispatchEvent(new CustomEvent('jmapbalancechange', { detail: { rows, scenario } }));
  }
  function sources() {
    const target = $('#balance-sources');
    const date = new Intl.DateTimeFormat('en-GB', { dateStyle: 'long', timeZone: 'UTC' }).format(new Date(`${data.published}T00:00:00Z`));
    target.append(node('p', '', `${data.publisher}. Reference year: ${data.year}. Published ${date}. Data is bundled for offline use; it does not refresh automatically.`));
    const links = node('p');
    data.sources.forEach((source, index) => {
      if (index) links.append(document.createTextNode(' · '));
      const link = node('a', '', source.title); link.href = source.url; link.target = '_blank'; link.rel = 'noreferrer'; links.append(link);
    });
    target.append(links);
    ['generationTWh', 'consumptionTWh', 'balanceTWh', 'coverage', 'renewableTWh', 'scenario'].forEach(key => target.append(node('p', '', data.definitions[key])));
    target.append(node('p', '', 'Annual balance bars share a zero at the centre. Orange extends left for a deficit; teal extends right for a surplus. Both sides use the same TWh scale, including every nation regardless of row sorting.'));
    target.append(node('p', '', 'Final-user consumption is a separate measure: ' + data.regions.map(row => `${row.name} ${number(row.finalConsumptionTWh)} TWh`).join('; ') + '. It excludes demand components such as network losses and is not the denominator in this table.'));
    data.limitations.forEach(text => target.append(node('p', '', text)));
  }
  function exportCsv() {
    const scenario = isScenario();
    const rows = [
      [`JMap ${scenario ? 'illustrative annual scenario' : 'official annual electricity balance'} — ${data.year}`],
      ['Source', data.sourceUrl], ['Published', data.published], ['Unit', 'TWh per year'],
      ['Demand definition', data.definitions.consumptionTWh],
      ['Demand increase (%)', state.demand], ['Generation reduction (%)', state.reduction],
      ['Interpretation', 'Annual deficit is not unmet demand or an outage forecast. Sample site filters do not apply.'], [],
      ['Nation', 'Reference year', 'Generation (TWh)', 'Gross demand (TWh)', 'Balance (TWh)', 'Generation / demand (%)', 'Annual gap (%)', 'Status', 'Baseline generation (TWh)', 'Baseline gross demand (TWh)', 'Baseline final consumption (TWh)', 'Baseline renewable generation (TWh)'],
      ...sortedResults().map(row => [row.name, data.year, row.generationTWh, row.consumptionTWh, row.balanceTWh, row.coveragePercent, row.shortfallPercent, row.status, row.baselineGenerationTWh, row.baselineConsumptionTWh, row.finalConsumptionTWh, row.renewableTWh])
    ];
    const content = rows.map(row => row.map(value => `"${String(value ?? '').replaceAll('"', '""')}"`).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob(['\uFEFF' + content], { type: 'text/csv;charset=utf-8;' }));
    const link = node('a'); link.href = url; link.download = `jmap-${data.year}-annual-${scenario ? 'scenario' : 'balance'}.csv`;
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    $('#announcement').textContent = `Exported ${data.year} annual ${scenario ? 'scenario' : 'balance'} for all four nations.`;
  }
  $('#balance-sort').value = state.sort;
  $('#demand-change').value = state.demand; $('#generation-change').value = state.reduction;
  if (isScenario()) $('.scenario-controls').open = true;
  $('#balance-sort').addEventListener('change', event => { state.sort = event.target.value; render(); });
  $('#demand-change').addEventListener('input', event => { state.demand = Number(event.target.value); render(); });
  $('#generation-change').addEventListener('input', event => { state.reduction = Number(event.target.value); render(); });
  $('#reset-scenario').addEventListener('click', () => { state.demand = 0; state.reduction = 0; $('#demand-change').value = 0; $('#generation-change').value = 0; render(); });
  $('#export-balance').addEventListener('click', exportCsv);
  sources(); render();
})();

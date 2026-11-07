/* The explorer deliberately uses a local, illustrative dataset. */
(() => {
  'use strict';

  const $ = selector => document.querySelector(selector);
  const number = value => Math.round(value).toLocaleString('en-GB');
  const technologies = {
    wind: { label: 'Wind', symbol: '⊙', description: 'Hollow circle with centre dot' },
    solar: { label: 'Solar', symbol: '▪', description: 'Grey square' },
    nuclear: { label: 'Nuclear', symbol: '◆', description: 'Black diamond' },
    gas: { label: 'Gas', symbol: '▲', description: 'Grey triangle' },
    hydro: { label: 'Hydro', symbol: '♧', description: 'Pale droplet' },
    biomass: { label: 'Biomass', symbol: '⊕', description: 'Grey circle with cross' },
    storage: { label: 'Storage', symbol: '□', description: 'Hollow square' },
    interconnector: { label: 'Interconnectors', symbol: '◇', description: 'Dark diamond' }
  };
  const regions = { england: 'England', scotland: 'Scotland', wales: 'Wales' };
  const lowCarbonTypes = new Set(['wind', 'solar', 'nuclear', 'hydro']);
  const sites = window.JMAP_SITES || [];
  const state = { selectedTypes: new Set(Object.keys(technologies)), query: '', region: 'all', mode: 'output', view: 'map', selectedId: null, sort: 'output', filtered: [] };
  let map;
  let detailTrigger;

  function node(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = content;
    return element;
  }

  function announce(message) { $('#announcement').textContent = message; }
  function utilisation(site) { return site.capacity ? Math.round(site.output / site.capacity * 100) : 0; }

  function makeFilters() {
    const container = $('#technology-list');
    Object.entries(technologies).forEach(([type, technology]) => {
      const label = node('label', 'filter-row');
      const input = node('input');
      input.type = 'checkbox';
      input.checked = true;
      input.value = type;
      input.setAttribute('aria-label', technology.label);
      const symbol = node('span', 'tech-symbol', technology.symbol);
      symbol.setAttribute('aria-hidden', 'true');
      label.title = `${technology.label} · ${technology.description}`;
      const count = node('span', 'filter-count', sites.filter(site => site.type === type).length);
      count.id = `count-${type}`;
      label.append(input, symbol, node('span', '', technology.label), count);
      input.addEventListener('change', () => {
        if (input.checked) state.selectedTypes.add(type);
        else state.selectedTypes.delete(type);
        render();
      });
      container.append(label);
    });
  }

  function matchesSearch(site) {
    const haystack = `${site.name} ${technologies[site.type].label} ${site.type} ${regions[site.region]}`.toLocaleLowerCase('en-GB');
    return state.query.toLocaleLowerCase('en-GB').split(/\s+/).filter(Boolean).every(term => haystack.includes(term));
  }

  function render() {
    const candidates = sites.filter(site => (state.region === 'all' || site.region === state.region) && matchesSearch(site));
    state.filtered = candidates.filter(site => state.selectedTypes.has(site.type));
    Object.keys(technologies).forEach(type => {
      $(`#count-${type}`).textContent = candidates.filter(site => site.type === type).length;
    });
    const totalOutput = state.filtered.reduce((total, site) => total + site.output, 0);
    const totalCapacity = state.filtered.reduce((total, site) => total + site.capacity, 0);
    const generation = state.filtered.filter(site => !['storage', 'interconnector'].includes(site.type));
    const generationOutput = generation.reduce((total, site) => total + site.output, 0);
    const lowCarbon = generation.filter(site => lowCarbonTypes.has(site.type)).reduce((total, site) => total + site.output, 0);
    $('#total-output').textContent = (totalOutput / 1000).toFixed(2);
    $('#total-capacity').textContent = (totalCapacity / 1000).toFixed(2);
    $('#low-carbon').textContent = generationOutput ? Math.round(lowCarbon / generationOutput * 100) : '—';
    $('#total-sites').textContent = state.filtered.length.toString().padStart(2, '0');
    $('#all-sites').textContent = sites.length;
    $('#results-label').textContent = `${state.filtered.length} of ${sites.length} sites`;
    $('#map-empty').hidden = state.filtered.length > 0;
    $('#directory-empty').hidden = state.filtered.length > 0;
    const typeSummary = state.selectedTypes.size === Object.keys(technologies).length ? 'All technologies' : state.selectedTypes.size === 0 ? 'No technologies selected' : state.selectedTypes.size === 1 ? technologies[[...state.selectedTypes][0]].label : `${state.selectedTypes.size} technologies`;
    $('#filter-summary').textContent = `${typeSummary}${state.region === 'all' ? '' : ` / ${regions[state.region]}`}`;
    if (!state.filtered.some(site => site.id === state.selectedId)) closeDetails(false);
    map?.setSites(state.filtered, state.mode);
    renderDirectory();
    $('#export-sites').disabled = state.filtered.length === 0;
    $('#export-sites').title = state.filtered.length ? 'Download filtered sites as CSV' : 'No matching sites to export';
  }

  function renderDirectory() {
    const body = $('#directory-body');
    body.replaceChildren();
    const sorted = [...state.filtered].sort((a, b) => state.sort === 'name' ? a.name.localeCompare(b.name, 'en-GB') : b[state.sort] - a[state.sort]);
    sorted.forEach(site => {
      const row = node('tr');
      const nameCell = node('td');
      nameCell.append(node('span', 'site-row-name', site.name), node('span', 'site-row-region', regions[site.region]));
      row.append(nameCell, node('td', '', technologies[site.type].label), node('td', '', `${number(site.output)} MW`), node('td', '', `${number(site.capacity)} MW`), node('td', '', `${utilisation(site)}%`));
      const actionCell = node('td');
      const button = node('button', '', 'Locate ↗');
      button.type = 'button';
      button.setAttribute('aria-label', `Locate ${site.name} on map`);
      button.addEventListener('click', () => {
        setView('map');
        selectSite(site.id, $('#map-view'));
        map?.focusSite(site.id);
        $('#map-stage').scrollIntoView({ block: 'nearest', behavior: 'instant' });
        $('#close-detail').focus({ preventScroll: true });
      });
      actionCell.append(button);
      row.append(actionCell);
      body.append(row);
    });
  }

  function selectSite(id, trigger) {
    if (id === null) { closeDetails(false); return; }
    const site = state.filtered.find(item => item.id === id);
    if (!site) return;
    detailTrigger = trigger || document.querySelector(`[data-site-id="${id}"]`) || $('#energy-map');
    state.selectedId = id;
    map?.selectSite(id);
    $('#detail-type').textContent = `${technologies[site.type].label} / ${site.type === 'interconnector' ? 'Import connection' : site.type === 'storage' ? 'Storage asset' : 'Generation site'}`;
    $('#detail-name').textContent = site.name;
    $('#detail-location').textContent = `${regions[site.region]} · Great Britain`;
    $('#detail-output').textContent = number(site.output);
    $('#detail-utilisation').textContent = `${utilisation(site)}%`;
    $('#utilisation-fill').style.width = `${Math.min(100, utilisation(site))}%`;
    $('#detail-capacity').textContent = `${number(site.capacity)} MW`;
    $('#detail-operator').textContent = site.operator;
    const latitude = `${Math.abs(site.lat).toFixed(2)}° ${site.lat >= 0 ? 'N' : 'S'}`;
    const longitude = `${Math.abs(site.lon).toFixed(2)}° ${site.lon >= 0 ? 'E' : 'W'}`;
    $('#detail-coordinates').textContent = `${latitude}, ${longitude}`;
    $('#detail-note').textContent = site.note;
    $('#site-detail').hidden = false;
    announce(`${site.name}. ${number(site.output)} megawatts illustrative output. ${utilisation(site)} percent utilisation. Site details opened.`);
  }

  function closeDetails(restoreFocus = true) {
    const wasOpen = !$('#site-detail').hidden;
    $('#site-detail').hidden = true;
    state.selectedId = null;
    map?.selectSite(null);
    if (restoreFocus && wasOpen) {
      const target = detailTrigger?.isConnected && !detailTrigger.closest('[hidden]') ? detailTrigger : $('#energy-map');
      target.focus({ preventScroll: true });
      announce('Site details closed.');
    }
  }

  function setView(view) {
    state.view = view;
    $('#map-stage').hidden = view !== 'map';
    $('#directory').hidden = view !== 'list';
    $('#map-view').classList.toggle('selected', view === 'map');
    $('#list-view').classList.toggle('selected', view === 'list');
    $('#map-view').setAttribute('aria-pressed', String(view === 'map'));
    $('#list-view').setAttribute('aria-pressed', String(view === 'list'));
    $('#size-mode').disabled = view !== 'map';
    if (view === 'list') renderDirectory();
    const url = new URL(window.location.href);
    if (view === 'list') url.hash = 'directory';
    else if (url.hash === '#directory') url.hash = '';
    if (url.href !== window.location.href) history.replaceState(null, '', url.href);
  }

  function resetFilters() {
    state.query = '';
    state.region = 'all';
    state.selectedTypes = new Set(Object.keys(technologies));
    $('#site-search').value = '';
    $('#region').value = 'all';
    document.querySelectorAll('.filter-row input').forEach(input => { input.checked = true; });
    closeDetails(false);
    map?.reset();
    render();
    announce('Filters reset. All sites shown.');
  }

  function exportSites() {
    if (!state.filtered.length) return;
    const rows = [
      ['JMap sample dataset — illustrative output, not live telemetry'],
      ['Capacity and coordinates are approximate. Storage output means discharge; interconnector output means imports.'],
      ['Site', 'Technology', 'Region', 'Illustrative output (MW)', 'Capacity (MW)', 'Utilisation (%)', 'Latitude', 'Longitude', 'Operator'],
      ...state.filtered.map(site => [site.name, technologies[site.type].label, regions[site.region], site.output, site.capacity, utilisation(site), site.lat, site.lon, site.operator])
    ];
    const csv = rows.map(row => row.map(value => `"${String(value).replaceAll('"', '""')}"`).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' }));
    const link = node('a');
    link.href = url;
    link.download = `jmap-${state.region}-sample-sites.csv`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    announce(`Exported ${state.filtered.length} sample sites as CSV.`);
  }

  function showDialog(kind) {
    const body = $('#dialog-body');
    body.replaceChildren();
    if (kind === 'keyboard') {
      $('#dialog-title').textContent = 'A few useful shortcuts.';
      const shortcuts = node('dl');
      [['/', 'Search sites'], ['+ / −', 'Zoom in / out on the map'], ['Arrow keys', 'Pan the focused map'], ['Home', 'Reset the focused map'], ['Tab, then Enter', 'Select a site or control'], ['Esc', 'Close details or this dialog']].forEach(([key, action]) => {
        const row = node('div');
        row.append(node('dt', '', key), node('dd', '', action));
        shortcuts.append(row);
      });
      body.append(shortcuts, node('p', '', 'On a touch screen, drag with one finger to pan and pinch with two fingers to zoom.'));
    } else {
      $('#dialog-title').textContent = 'A map. A starting point.';
      body.append(
        node('p', '', 'This is a curated sample of 40 British generation, storage, and interconnector sites. Output figures are illustrative examples, not live readings. Locations, capacities, and operator labels are approximate.'),
        node('p', '', 'Power supplied includes generation, storage discharge, and interconnector imports. Low-carbon share covers wind, solar, nuclear, and conventional hydro output as a share of generation; it excludes storage and imports. All summaries follow your filters, independently of map zoom.'),
        node('p', '', 'Marker shape identifies technology; size represents the selected measure. At closely located sites, zoom in or use the site directory to select each asset.'),
        node('p', '', 'Geography is provided by Natural Earth (public domain). The map and sample data are bundled locally, so exploration works without a map service or API key.')
      );
      const sources = node('p', '');
      const attribution = node('a', '', 'Natural Earth geography & terms ↗');
      attribution.href = 'https://www.naturalearthdata.com/about/terms-of-use/';
      attribution.target = '_blank';
      attribution.rel = 'noreferrer';
      sources.append(attribution);
      body.append(sources);
    }
    $('#info-dialog').showModal();
  }

  makeFilters();
  if (window.EnergyMap && window.JMAP_GEOGRAPHY) {
    map = new window.EnergyMap({ element: $('#energy-map'), geography: window.JMAP_GEOGRAPHY, onSelect: id => selectSite(id) });
  } else {
    setView('list');
    $('#map-view').disabled = true;
    $('#size-mode').disabled = true;
    announce('Map files could not be loaded. Use the site directory to browse available data.');
  }
  render();
  if (window.location.hash === '#directory') {
    setView('list');
    requestAnimationFrame(() => $('#workspace').scrollIntoView({ block: 'start' }));
  }

  $('#site-search').addEventListener('input', event => { state.query = event.target.value.trim(); render(); });
  $('#region').addEventListener('change', event => { state.region = event.target.value; render(); });
  $('#size-mode').addEventListener('change', event => {
    state.mode = event.target.value;
    const labels = { output: ['Power supplied', 'Larger marker, more power'], capacity: ['Network capacity', 'Larger marker, more capacity'], utilisation: ['Capacity utilisation', 'Larger marker, higher utilisation'] };
    $('#legend-title').textContent = labels[state.mode][0];
    $('#legend-description').textContent = labels[state.mode][1];
    map?.setSites(state.filtered, state.mode);
  });
  $('#sort-sites').addEventListener('change', event => { state.sort = event.target.value; renderDirectory(); });
  $('#select-all').addEventListener('click', () => {
    state.selectedTypes = new Set(Object.keys(technologies));
    document.querySelectorAll('.filter-row input').forEach(input => { input.checked = true; });
    render();
  });
  $('#clear-types').addEventListener('click', () => {
    state.selectedTypes.clear();
    document.querySelectorAll('.filter-row input').forEach(input => { input.checked = false; });
    render();
  });
  $('#reset-filters').addEventListener('click', resetFilters);
  $('#empty-reset').addEventListener('click', resetFilters);
  $('#zoom-in').addEventListener('click', () => map?.zoomBy(1.35));
  $('#zoom-out').addEventListener('click', () => map?.zoomBy(1 / 1.35));
  $('#reset-map').addEventListener('click', () => map?.reset());
  $('#close-detail').addEventListener('click', () => closeDetails());
  $('#focus-site').addEventListener('click', () => map?.focusSite(state.selectedId));
  $('#map-view').addEventListener('click', () => setView('map'));
  $('#list-view').addEventListener('click', () => setView('list'));
  $('#directory-nav').addEventListener('click', event => {
    event.preventDefault();
    setView('list');
    $('#workspace').scrollIntoView({ block: 'start', behavior: 'smooth' });
    $('#list-view').focus({ preventScroll: true });
  });
  window.addEventListener('hashchange', () => setView(window.location.hash === '#directory' ? 'list' : 'map'));
  $('#export-sites').addEventListener('click', exportSites);
  $('#about-data').addEventListener('click', () => showDialog('data'));
  $('#keyboard-help').addEventListener('click', () => showDialog('keyboard'));
  $('#close-dialog').addEventListener('click', () => $('#info-dialog').close());
  $('#dialog-done').addEventListener('click', () => $('#info-dialog').close());
  $('#info-dialog').addEventListener('click', event => { if (event.target === $('#info-dialog')) {
    const bounds = event.target.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) event.target.close();
  } });
  $('#energy-map').addEventListener('mapviewchange', event => { $('#zoom-label').textContent = Math.abs(event.detail.zoom - 1) < .05 ? 'National view' : `${event.detail.zoom.toFixed(1)}× zoom`; });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !$('#info-dialog').open) closeDetails();
    if (event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey && !$('#info-dialog').open && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
      event.preventDefault();
      $('#site-search').focus();
    }
  });
})();

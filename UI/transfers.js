/* Interactive live-transfer view. No simulator data or stored sample fallback. */
(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const D = window.JMapLiveTransfers;
  const NS = 'http://www.w3.org/2000/svg';
  const number = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 });
  const timeFormatter = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', hour: '2-digit', minute: '2-digit' });
  const dateFormatter = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', day: 'numeric', month: 'short', year: 'numeric' });
  const zoneFormatter = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', timeZoneName: 'short', hour: '2-digit' });
  const state = { snapshot: null, selected: 'INTNSL', fetching: false, error: null, controller: null, lastChecked: null };
  const view = { scale: 1, x: 0, y: 0, width: 1000, height: 720 };
  const map = $('#transfer-map');
  const camera = new window.JMapMotion.Camera({
    element: map, inverseZoom: false,
    read: () => ({ scale: view.scale, x: view.x, y: view.y }),
    write: value => { Object.assign(view, value); transformScene(); }
  });
  const flowMotion = new window.JMapMotion.Flow(map);
  const routeNodes = new Map();
  const rows = new Map();
  let scene;
  let labelLayer;
  const placeLabels = [];
  let suppressClick = false;

  function svgNode(tag, attributes = {}, text) {
    const element = document.createElementNS(NS, tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function node(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = content;
    return element;
  }
  function time(value) { return value ? timeFormatter.format(new Date(value)) : '—'; }
  function zone(value) { return zoneFormatter.formatToParts(new Date(value)).find(part => part.type === 'timeZoneName')?.value || 'UK'; }
  function period(snapshot) { return snapshot ? `${time(snapshot.startTime)}–${time(snapshot.endTime)} ${zone(snapshot.endTime)}` : '—'; }
  function linkState(id) { return state.snapshot?.links.find(link => link.id === id) || { ...D.LINKS.find(link => link.id === id), mw: null, absoluteMw: null, direction: 'unknown', publishTime: null }; }
  function direction(link) { return ({ import: 'Into GB', export: 'Out of GB', idle: 'Zero flow', unknown: 'Unknown' })[link.direction]; }
  function setPower(id, value) {
    const element = $(id);
    element.replaceChildren(document.createTextNode(value === null ? '—' : number.format(value)));
    if (value !== null) element.append(node('small', '', 'MW'));
  }

  function createRows() {
    const body = $('#links-body');
    D.LINKS.forEach(link => {
      const row = node('tr');
      row.dataset.link = link.id;
      const name = node('td');
      const button = node('button', '', link.name);
      button.type = 'button';
      button.addEventListener('click', () => selectLink(link.id));
      name.append(button, node('small', '', link.country));
      const flow = node('td', 'flow-unknown', 'Unknown');
      const value = node('td', '', '—');
      row.append(name, flow, value);
      row.addEventListener('click', event => { if (!event.target.closest('button')) selectLink(link.id); });
      body.append(row);
      rows.set(link.id, { row, button, flow, value });
    });
  }

  function projectFactory(width, height) {
    const mercator = latitude => Math.log(Math.tan(Math.PI / 4 + latitude * Math.PI / 360)) * 180 / Math.PI;
    const bounds = { west: -10.7, east: 11, north: mercator(60.8), south: mercator(48.0) };
    const scale = Math.min((width - 65) / (bounds.east - bounds.west), (height - 65) / (bounds.north - bounds.south));
    const centreX = (bounds.west + bounds.east) / 2;
    const centreY = (bounds.north + bounds.south) / 2;
    return ([longitude, latitude]) => [width / 2 + (longitude - centreX) * scale, height / 2 - (mercator(latitude) - centreY) * scale];
  }
  function transformScene() {
    scene?.setAttribute('transform', `translate(${view.width / 2 + view.x} ${view.height / 2 + view.y}) scale(${view.scale}) translate(${-view.width / 2} ${-view.height / 2})`);
    routeNodes.forEach(({ terminals }) => {
      terminals.forEach(terminal => terminal.setAttribute('r', 3.2 / view.scale));
    });
    layoutLabels();
    layoutRouteArrows();
  }
  function screenPoint([x, y]) {
    return [view.width / 2 + view.x + (x - view.width / 2) * view.scale, view.height / 2 + view.y + (y - view.height / 2) * view.scale];
  }
  function drawMap() {
    const rect = map.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) return;
    camera.cancel();
    view.width = rect.width;
    view.height = rect.height;
    map.setAttribute('viewBox', `0 0 ${view.width} ${view.height}`);
    map.replaceChildren();
    routeNodes.clear();
    placeLabels.length = 0;
    const project = projectFactory(view.width, view.height);
    scene = svgNode('g', { class: 'transfer-geometry-layer' });
    labelLayer = svgNode('g', { class: 'transfer-label-layer', 'aria-hidden': 'true' });
    map.append(scene, labelLayer);
    const graticule = svgNode('g', { 'aria-hidden': 'true' });
    for (let lon = -10; lon <= 10; lon += 5) {
      const [x1, y1] = project([lon, 46]); const [x2, y2] = project([lon, 64]);
      graticule.append(svgNode('path', { d: `M${x1},${y1}L${x2},${y2}`, class: 'grid-line' }));
    }
    for (let lat = 50; lat <= 60; lat += 5) {
      const [x1, y1] = project([-15, lat]); const [x2, y2] = project([16, lat]);
      graticule.append(svgNode('path', { d: `M${x1},${y1}L${x2},${y2}`, class: 'grid-line' }));
    }
    scene.append(graticule);
    (window.JMAP_GEOGRAPHY?.features || []).forEach(feature => {
      const path = feature.polygons.map(ring => ring.map((point, index) => `${index ? 'L' : 'M'}${project(point).join(',')}`).join('') + 'Z').join('');
      scene.append(svgNode('path', { d: path, class: `land${feature.name === 'United Kingdom' ? ' uk' : ''}`, 'aria-hidden': 'true', 'fill-rule': 'evenodd' }));
    });
    const labels = [ ['GREAT BRITAIN', [-3.2, 56.0]], ['IRELAND', [-8.1, 53.5]], ['FRANCE', [2.0, 48.5]], ['BELGIUM', [4.6, 50.6]], ['NETHERLANDS', [5.5, 52.55]], ['DENMARK', [9.0, 56.6]], ['NORWAY', [7.0, 60.2]] ];
    labels.forEach(([name, point]) => {
      const label = svgNode('text', { x: 0, y: 0, class: 'country-label' }, name);
      labelLayer.append(label);
      placeLabels.push({ label, anchor: project(point) });
    });
    [['North Sea', [2.4, 56.3]], ['Irish Sea', [-5.5, 53.8]], ['English Channel', [-2.3, 49.7]]].forEach(([name, point]) => {
      const label = svgNode('text', { x: 0, y: 0, class: 'sea-label' }, name);
      labelLayer.append(label);
      placeLabels.push({ label, anchor: project(point) });
    });
    D.LINKS.forEach(link => {
      const group = svgNode('g', { class: 'route unknown', tabindex: 0, role: 'button', 'data-link': link.id, 'aria-label': `${link.name}, ${link.country}, no observation` });
      const start = project(link.gb); const end = project(link.other);
      const middle = [(start[0] + end[0]) / 2 + link.bend, (start[1] + end[1]) / 2 - link.bend * .35];
      const d = `M${start.join(',')}Q${middle.join(',')} ${end.join(',')}`;
      const halo = svgNode('path', { d, class: 'route-halo' });
      const line = svgNode('path', { d, class: 'route-path' });
      group.append(halo, line, svgNode('path', { d, class: 'route-hit' }));
      const arrows = svgNode('g', { 'aria-hidden': 'true' });
      group.append(arrows);
      const terminals = [start, end].map(([cx, cy]) => svgNode('circle', { cx, cy, r: 3.2 / view.scale, class: 'terminal' }));
      terminals.forEach(terminal => group.append(terminal));
      const position = [(start[0] + 2 * middle[0] + end[0]) / 4, (start[1] + 2 * middle[1] + end[1]) / 4];
      const labelGroup = svgNode('g', { class: 'route-label-group unknown', 'data-link': link.id });
      const label = svgNode('text', { x: 0, y: 0, class: 'route-label' });
      label.append(svgNode('tspan', { x: 0, dy: 0 }, link.name));
      const value = svgNode('tspan', { x: 0, dy: 13, class: 'route-label-value' }, '—');
      label.append(value); labelGroup.append(label); labelLayer.append(labelGroup);
      const title = svgNode('title', {}, `${link.name}: waiting for an observation`); group.prepend(title);
      group.addEventListener('click', event => { if (event.detail === 0 || !suppressClick) selectLink(link.id); });
      group.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectLink(link.id); } });
      scene.append(group);
      routeNodes.set(link.id, { group, line, arrows, value, title, label, labelGroup, anchor: position, offset: link.label, terminals });
    });
    transformScene();
    updateRoutes();
  }

  function updateRoutes() {
    D.LINKS.forEach(link => {
      const current = linkState(link.id);
      const nodes = routeNodes.get(link.id);
      if (!nodes) return;
      nodes.group.setAttribute('class', `route ${current.direction}${state.selected === link.id ? ' selected' : ''}`);
      nodes.labelGroup.setAttribute('class', `route-label-group ${current.direction}${state.selected === link.id ? ' selected' : ''}`);
      nodes.group.setAttribute('aria-pressed', String(state.selected === link.id));
      const description = `${link.name}, ${link.country}, ${current.mw === null ? 'no observation' : `${number.format(current.absoluteMw)} megawatts, ${direction(current)}`}`;
      nodes.group.setAttribute('aria-label', description);
      nodes.title.textContent = description;
      nodes.value.textContent = current.mw === null ? '—' : `${number.format(current.absoluteMw)} MW`;
      nodes.direction = current.direction;
    });
    layoutLabels();
    layoutRouteArrows();
  }

  function visibleRouteSegments(line, margin = 16) {
    const length = line.getTotalLength();
    const steps = Math.max(24, Math.min(400, Math.ceil(length * view.scale / 14)));
    const segments = [];
    let segment = [];
    for (let index = 0; index <= steps; index++) {
      const at = length * index / steps;
      const point = line.getPointAtLength(at);
      const [x, y] = screenPoint([point.x, point.y]);
      if (x >= margin && x <= view.width - margin && y >= margin && y <= view.height - margin) {
        segment.push({ at, point, x, y });
      } else if (segment.length) {
        segments.push(segment); segment = [];
      }
    }
    if (segment.length) segments.push(segment);
    return segments;
  }

  function layoutRouteArrows() {
    const mapRect = map.getBoundingClientRect();
    const labelBounds = [...routeNodes.values()].filter(({ labelGroup, label }) => labelGroup.style.display !== 'none' && getComputedStyle(label).display !== 'none').map(({ label }) => {
      const box = label.getBoundingClientRect();
      return { left: box.left - mapRect.left - 10, right: box.right - mapRect.left + 10, top: box.top - mapRect.top - 10, bottom: box.bottom - mapRect.top + 10 };
    });
    const animatedRoutes = [];
    routeNodes.forEach(({ line, arrows, direction: flow }) => {
      arrows.replaceChildren();
      if (flow !== 'import' && flow !== 'export') return;
      const segments = visibleRouteSegments(line);
      segments.sort((first, second) => (second.at(-1).at - second[0].at) - (first.at(-1).at - first[0].at));
      const points = segments[0];
      if (!points || points.length < 2) return;
      const first = points[0].at, last = points.at(-1).at;
      const fractions = (last - first) * view.scale >= 160 ? [.32, .70] : [.5];
      const clear = points.filter(({ x, y }) => !labelBounds.some(box => x >= box.left && x <= box.right && y >= box.top && y <= box.bottom));
      const available = clear.length ? clear : points;
      const placed = [];
      const markers = [];
      fractions.forEach(fraction => {
        const target = first + (last - first) * fraction;
        const candidates = available.filter(point => placed.every(other => Math.hypot(point.x - other.x, point.y - other.y) >= 45));
        candidates.sort((a, b) => Math.abs(a.at - target) - Math.abs(b.at - target));
        const chosen = candidates[0];
        if (!chosen) return;
        const marker = svgNode('path', { d: 'M-5,-3.8L2,0L-5,3.8L-2,0Z', class: 'flow-chevron' });
        arrows.append(marker);
        markers.push({ element: marker, at: chosen.at });
        placed.push(chosen);
      });
      if (markers.length) animatedRoutes.push({
        path: line, length: line.getTotalLength(), start: first, end: last,
        scale: view.scale, reverse: flow === 'import', markers,
        obscured: point => {
          const [x, y] = screenPoint([point.x, point.y]);
          return labelBounds.some(box => x >= box.left && x <= box.right && y >= box.top && y <= box.bottom);
        }
      });
    });
    flowMotion.setRoutes(animatedRoutes);
  }

  function layoutLabels() {
    if (!labelLayer) return;
    const occupied = [];
    const candidates = [[0, 0], [0, -25], [0, 25], [0, -50], [0, 50], [30, 0], [-30, 0], [30, 25], [-30, -25], [0, 75], [0, -75]];
    const ordered = [...routeNodes.entries()].sort(([first], [second]) => Number(second === state.selected) - Number(first === state.selected));
    ordered.forEach(([, { label, labelGroup, anchor, offset, line }]) => {
      labelGroup.style.display = '';
      if (getComputedStyle(label).display === 'none') return;
      let [x, y] = screenPoint(anchor);
      // The label follows its route in the camera, while its type and offset
      // remain screen-sized. Never pin off-screen route names to the viewport.
      if (x < -20 || x > view.width + 20 || y < -20 || y > view.height + 20) {
        // At close zoom the midpoint may leave the viewport while part of the
        // route remains visible. Attach its label to an actual visible point.
        const visible = visibleRouteSegments(line, 35).flat().map(({ x: px, y: py }) => [px, py]);
        if (!visible.length) { labelGroup.style.display = 'none'; return; }
        visible.sort((a, b) => Math.hypot(a[0] - view.width / 2, a[1] - view.height / 2) - Math.hypot(b[0] - view.width / 2, b[1] - view.height / 2));
        [x, y] = visible[0];
      }
      const box = label.getBBox();
      for (const [dx, dy] of candidates) {
        const labelX = x + offset[0] + dx;
        const labelY = y + offset[1] + dy;
        const bounds = { x: box.x + labelX - 4, y: box.y + labelY - 3, width: box.width + 8, height: box.height + 6 };
        const outside = bounds.x < 4 || bounds.y < 4 || bounds.x + bounds.width > view.width - 4 || bounds.y + bounds.height > view.height - 8;
        const overlap = occupied.some(other => bounds.x < other.x + other.width && bounds.x + bounds.width > other.x && bounds.y < other.y + other.height && bounds.y + bounds.height > other.y);
        if (!outside && !overlap) {
          labelGroup.setAttribute('transform', `translate(${labelX} ${labelY})`);
          occupied.push(bounds);
          return;
        }
      }
      labelGroup.style.display = 'none';
    });
    // Place names are secondary to route values and disappear if they cannot
    // fit at their projected location. Font sizes never inherit camera scale.
    placeLabels.forEach(({ label, anchor }) => {
      label.style.display = '';
      const [x, y] = screenPoint(anchor);
      const box = label.getBBox();
      const bounds = { x: x + box.x - 3, y: y + box.y - 2, width: box.width + 6, height: box.height + 4 };
      const outside = bounds.x < 4 || bounds.y < 4 || bounds.x + bounds.width > view.width - 4 || bounds.y + bounds.height > view.height - 8;
      const overlap = occupied.some(other => bounds.x < other.x + other.width && bounds.x + bounds.width > other.x && bounds.y < other.y + other.height && bounds.y + bounds.height > other.y);
      if (outside || overlap) label.style.display = 'none';
      else { label.setAttribute('transform', `translate(${x} ${y})`); occupied.push(bounds); }
    });
  }

  function selectLink(id, announce = true) {
    state.selected = id;
    updateRoutes(); updateDetails();
    rows.forEach(({ row, button }, key) => { row.setAttribute('aria-selected', String(key === id)); button.setAttribute('aria-pressed', String(key === id)); });
    if (announce) $('#announcement').textContent = `${linkState(id).name} selected. ${direction(linkState(id))}.`;
  }
  function updateDetails() {
    const link = linkState(state.selected);
    $('#detail-name').textContent = link.name;
    $('#detail-country').textContent = `${link.country} ↔ Great Britain`;
    $('#detail-code').textContent = link.id;
    $('#detail-direction').textContent = link.mw === null ? 'No observation for this interval' : link.direction === 'import' ? `Importing from ${link.country} into GB` : link.direction === 'export' ? `Exporting from GB to ${link.country}` : 'Measured zero flow in this interval';
    $('#detail-value').replaceChildren(document.createTextNode(link.mw === null ? '—' : number.format(link.absoluteMw)), node('span', '', 'MW'));
    $('#detail-value').className = `detail-value ${link.direction}`;
    $('#detail-gb').textContent = link.gbTerminal; $('#detail-other').textContent = link.otherTerminal;
    $('#detail-period').textContent = period(state.snapshot);
    $('#detail-published').textContent = link.publishTime ? `${time(link.publishTime)} ${zone(link.publishTime)}` : '—';
    $('#detail-source').href = link.sourceUrl;
  }
  function renderSnapshot() {
    const snapshot = state.snapshot;
    const net = snapshot?.netImportsMw ?? null;
    $('#net-label').textContent = (net !== null && net < 0 ? 'Net exports from GB' : 'Net imports to GB') + (snapshot && !snapshot.complete ? ' · partial' : '');
    setPower('#net-value', net === null ? null : Math.abs(net)); setPower('#imports-value', snapshot?.importsMw ?? null); setPower('#exports-value', snapshot?.exportsMw ?? null);
    $('#coverage-value').textContent = `${snapshot?.measuredCount ?? '—'} / 10`;
    $('#coverage-note').textContent = !snapshot ? 'Waiting for live observations. Missing values remain unknown.' : snapshot.complete ? 'All ten links · one coherent 5-minute observation · MW' : `Partial totals: ${snapshot.measuredCount}/10 links report in this interval.${snapshot.unmappedCodes.length ? ` Unmapped source codes: ${snapshot.unmappedCodes.join(', ')}.` : ''}`;
    if (snapshot) {
      $('#observation-time').textContent = `${dateFormatter.format(new Date(snapshot.startTime))} · ${period(snapshot)}`;
      $('#observation-time').title = `Interval starts ${snapshot.startTime}; published ${snapshot.publishTime || 'unknown'}. Display: Europe/London.`;
      $('#map-loading').hidden = true;
    }
    rows.forEach(({ row, button, flow, value }, id) => {
      const link = linkState(id);
      flow.textContent = `${link.direction === 'import' ? '↙ ' : link.direction === 'export' ? '↗ ' : ''}${direction(link)}`;
      flow.className = `flow-${link.direction}`; value.textContent = link.mw === null ? '—' : number.format(link.absoluteMw);
      button.setAttribute('aria-label', `${link.name}, ${link.country}, ${direction(link)}${link.mw === null ? '' : `, ${number.format(link.absoluteMw)} megawatts`}`);
      row.title = `${period(snapshot)}${link.publishTime ? ` · published ${time(link.publishTime)} ${zone(link.publishTime)}` : ''}`;
    });
    updateRoutes(); updateDetails(); updateStatus(); selectLink(state.selected, false);
  }
  function updateStatus() {
    const status = D.freshness(state.snapshot);
    const badge = $('#feed-badge');
    const failed = !!state.error;
    badge.className = `feed-badge ${failed ? 'unavailable' : status.state}`;
    badge.textContent = state.fetching ? 'Checking Elexon…' : failed ? 'Update failed' : !state.snapshot ? 'Waiting for data' : status.state === 'stale' ? `Delayed · ${Math.floor(status.ageMinutes)} min old` : state.snapshot.complete ? 'Live observation · Elexon' : `Partial observation · ${state.snapshot.measuredCount}/10`;
    $('#mobile-feed-status').textContent = badge.textContent;
    $('#mobile-feed-status').className = `mobile-feed-status ${failed ? 'unavailable' : status.state}`;
    $('#error-banner').hidden = !failed && status.state !== 'stale';
    if (failed) $('#error-message').textContent = `${state.error} ${state.snapshot ? `Showing the last received observation (${period(state.snapshot)}).` : 'No live values are available. Routes remain unknown.'}`;
    else if (status.state === 'stale') $('#error-message').textContent = `The latest observation ended ${Math.floor(status.ageMinutes)} minutes ago. Values are delayed; the map shows its recorded time.`;
    $('#refresh-note').textContent = state.lastChecked ? `Checked ${time(state.lastChecked)} ${zone(state.lastChecked)} · refresh every 60s` : 'Checks every 60 seconds';
    if (!state.snapshot && failed) $('#map-loading').textContent = 'Live feed unavailable. Use Retry connection.';
  }

  async function refresh() {
    if (state.fetching) return;
    state.fetching = true; state.controller = new AbortController();
    $('#refresh').disabled = true; $('#retry').disabled = true; updateStatus();
    const timeout = setTimeout(() => state.controller?.abort(), 15000);
    try {
      const snapshot = await D.fetchSnapshot({ signal: state.controller.signal });
      // A late response must never replace a newer observation already received.
      if (!state.snapshot || Date.parse(snapshot.startTime) >= Date.parse(state.snapshot.startTime)) state.snapshot = snapshot;
      state.error = null; state.lastChecked = new Date().toISOString();
      renderSnapshot();
    } catch (error) {
      state.error = error.name === 'AbortError' ? 'The Elexon request timed out.' : error.message || 'Could not connect to Elexon.';
      state.lastChecked = new Date().toISOString();
    } finally {
      clearTimeout(timeout); state.fetching = false; state.controller = null;
      $('#refresh').disabled = false; $('#retry').disabled = false; updateStatus();
    }
  }

  function zoom(factor, point) {
    const target = camera.target();
    const next = Math.max(.8, Math.min(7, target.scale * factor));
    const ratio = next / target.scale;
    const anchor = point || [view.width / 2, view.height / 2];
    target.x = (anchor[0] - view.width / 2) - ((anchor[0] - view.width / 2) - target.x) * ratio;
    target.y = (anchor[1] - view.height / 2) - ((anchor[1] - view.height / 2) - target.y) * ratio;
    target.scale = next; camera.to(target);
  }
  function resetMap() { camera.to({ scale: 1, x: 0, y: 0 }); }
  $('#zoom-in').addEventListener('click', () => zoom(1.35)); $('#zoom-out').addEventListener('click', () => zoom(1 / 1.35)); $('#reset-map').addEventListener('click', resetMap);
  map.addEventListener('wheel', event => {
    if (event.ctrlKey || event.metaKey) return;
    event.preventDefault();
    const rect = map.getBoundingClientRect();
    const pixels = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? view.height : 1);
    zoom(Math.exp(-Math.max(-120, Math.min(120, pixels)) * .002), [event.clientX - rect.left, event.clientY - rect.top]);
  }, { passive: false });
  const pointers = new Map();
  let gesture = null;
  function capturePointer(id) {
    try { if (!map.hasPointerCapture(id)) map.setPointerCapture(id); } catch (_) { /* Pointer may already be cancelled. */ }
  }
  function releasePointer(id) {
    try { if (map.hasPointerCapture(id)) map.releasePointerCapture(id); } catch (_) { /* Pointer may already be released. */ }
  }
  function startGesture() {
    const active = [...pointers.values()];
    if (active.length >= 2) {
      const rect = map.getBoundingClientRect();
      const midpoint = [(active[0].x + active[1].x) / 2 - rect.left, (active[0].y + active[1].y) / 2 - rect.top];
      gesture = { type: 'pinch', distance: Math.max(1, Math.hypot(active[1].x - active[0].x, active[1].y - active[0].y)), scale: view.scale, world: [view.width / 2 + (midpoint[0] - view.width / 2 - view.x) / view.scale, view.height / 2 + (midpoint[1] - view.height / 2 - view.y) / view.scale] };
      suppressClick = true;
      map.classList.add('is-panning');
      pointers.forEach((_, id) => capturePointer(id));
    } else if (active.length === 1) {
      gesture = { type: 'pan', id: active[0].id, x: active[0].x, y: active[0].y, panX: view.x, panY: view.y };
    } else {
      gesture = null;
      map.classList.remove('is-panning');
    }
  }
  map.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    if (pointers.size === 0) suppressClick = false;
    pointers.set(event.pointerId, { id: event.pointerId, x: event.clientX, y: event.clientY });
    startGesture();
  });
  map.addEventListener('pointermove', event => {
    if (!pointers.has(event.pointerId) || !gesture) return;
    pointers.set(event.pointerId, { id: event.pointerId, x: event.clientX, y: event.clientY });
    const active = [...pointers.values()];
    if (gesture.type === 'pinch' && active.length >= 2) {
      const rect = map.getBoundingClientRect();
      const midpoint = [(active[0].x + active[1].x) / 2 - rect.left, (active[0].y + active[1].y) / 2 - rect.top];
      const distance = Math.hypot(active[1].x - active[0].x, active[1].y - active[0].y);
      view.scale = Math.max(.8, Math.min(7, gesture.scale * distance / gesture.distance));
      view.x = midpoint[0] - view.width / 2 - (gesture.world[0] - view.width / 2) * view.scale;
      view.y = midpoint[1] - view.height / 2 - (gesture.world[1] - view.height / 2) * view.scale;
      event.preventDefault(); transformScene();
      return;
    }
    if (gesture.type !== 'pan' || gesture.id !== event.pointerId) return;
    const dx = event.clientX - gesture.x, dy = event.clientY - gesture.y;
    if (Math.hypot(dx, dy) > 4) suppressClick = true;
    if (suppressClick) {
      capturePointer(event.pointerId);
      map.classList.add('is-panning');
      view.x = gesture.panX + dx; view.y = gesture.panY + dy;
      event.preventDefault(); transformScene();
    }
  });
  function finishPointer(event) {
    if (!pointers.has(event.pointerId)) return;
    pointers.delete(event.pointerId);
    releasePointer(event.pointerId);
    if (event.type !== 'pointerup') suppressClick = true;
    startGesture();
  }
  function cancelGestures() {
    const ids = [...pointers.keys()];
    pointers.clear(); gesture = null; suppressClick = true;
    ids.forEach(releasePointer);
    map.classList.remove('is-panning');
  }
  window.addEventListener('pointerup', finishPointer, true);
  window.addEventListener('pointercancel', finishPointer, true);
  map.addEventListener('lostpointercapture', event => { if (event.target === map) finishPointer(event); });
  map.addEventListener('pointerleave', event => { if (!map.hasPointerCapture(event.pointerId)) finishPointer(event); });
  window.addEventListener('blur', cancelGestures);
  map.addEventListener('click', event => {
    if (suppressClick && event.detail !== 0) { event.preventDefault(); event.stopImmediatePropagation(); }
  }, true);
  map.addEventListener('keydown', event => {
    if (event.target !== map) return;
    const keys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', '+', '=', '-', 'Home'];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'Home') resetMap(); else if (event.key === '+' || event.key === '=') zoom(1.35); else if (event.key === '-') zoom(1 / 1.35); else {
      const target = camera.target();
      target.x += event.key === 'ArrowLeft' ? 35 : event.key === 'ArrowRight' ? -35 : 0;
      target.y += event.key === 'ArrowUp' ? 35 : event.key === 'ArrowDown' ? -35 : 0;
      camera.to(target);
    }
  });
  $('#refresh').addEventListener('click', refresh); $('#retry').addEventListener('click', refresh);
  $('#animate-live-transfers').addEventListener('change', event => flowMotion.setEnabled(event.target.checked));
  $('#open-method').addEventListener('click', () => $('#method-dialog').showModal()); $('#close-method').addEventListener('click', () => $('#method-dialog').close());
  $('#method-dialog').addEventListener('click', event => { if (event.target === $('#method-dialog')) { const rect = event.target.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) event.target.close(); } });
  let refreshTimer;
  let statusTimer;
  function startTimers() {
    clearInterval(refreshTimer); clearInterval(statusTimer);
    refreshTimer = setInterval(() => { if (!document.hidden) refresh(); }, 60000);
    statusTimer = setInterval(updateStatus, 15000);
  }
  startTimers();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { updateStatus(); refresh(); } });
  window.addEventListener('pagehide', () => { cancelGestures(); state.controller?.abort(); clearInterval(refreshTimer); clearInterval(statusTimer); });
  window.addEventListener('pageshow', event => { if (event.persisted) { startTimers(); updateStatus(); refresh(); } });
  createRows(); drawMap(); renderSnapshot();
  new ResizeObserver(drawMap).observe($('#map-stage'));
  refresh();
})();

/* Simulator topology and half-hour state. Colours never infer shortage from
 * generation minus demand. This module also exports its pure state helpers. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SimulationMap = api.SimulationMap;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const DEG = Math.PI / 180;
  const BOUNDS = [[-8.7, 49.3], [3.4, 61.1]];
  const REPORTING_TOLERANCE_MW = .05;
  const COLOURS = Object.freeze({ healthy: '#17816b', warning: '#b47b13', overload: '#ba3437', out: '#8c9796', unknown: '#8c9796' });
  const DISPLAY_COLOURS = Object.freeze({ healthy: 'var(--accent, #83cdb7)', warning: 'var(--ops-warning-text, #e8c483)', overload: 'var(--ops-danger-text, #ff9c9f)', out: 'var(--muted, #a8b8bf)', unknown: 'var(--muted, #a8b8bf)' });
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const format = value => finite(value) ? value.toLocaleString('en-GB', { maximumFractionDigits: 1 }) : 'Unavailable';

  function corridorState(state = {}, topology = {}) {
    state = state && typeof state === 'object' ? state : {};
    topology = topology && typeof topology === 'object' ? topology : {};
    const flowMW = finite(state.flow_mw) ? state.flow_mw : null;
    const limitMW = finite(state.limit_mw) && state.limit_mw >= 0 ? state.limit_mw : null;
    const nameplateMW = finite(topology.limit_mw) && topology.limit_mw >= 0 ? topology.limit_mw : null;
    const loading = finite(state.loading_frac) && state.loading_frac >= 0 ? state.loading_frac
      : flowMW !== null && limitMW > 0 ? Math.abs(flowMW) / limitMW : null;
    const tripped = typeof state.tripped === 'boolean' ? state.tripped : null;
    const unavailable = limitMW === 0;
    const band = unavailable ? 'out' : loading === null ? 'unknown' : loading > 1 ? 'overload' : loading >= .75 ? 'warning' : 'healthy';
    const reverse = flowMW !== null && flowMW < 0;
    return {
      flowMW, limitMW, nameplateMW, loading, tripped, unavailable, band, reverse,
      arrow: !unavailable && flowMW !== null && flowMW !== 0,
      dashed: unavailable || tripped === true,
      colour: tripped === true && band === 'healthy' ? COLOURS.warning : COLOURS[band],
      from: reverse ? topology.to : topology.from,
      to: reverse ? topology.from : topology.to
    };
  }

  function zoneColour(unservedMW) {
    if (!finite(unservedMW) || unservedMW < 0) return '#d8ddda';
    if (unservedMW < REPORTING_TOLERANCE_MW) return '#d4eae1';
    const amount = Math.min(1, unservedMW / 1000);
    const low = [250, 213, 201], high = [174, 40, 47];
    return `rgb(${low.map((value, i) => Math.round(value + (high[i] - value) * amount)).join(',')})`;
  }

  function unservedLabel(value) {
    if (!finite(value) || value < 0) return 'Data unavailable';
    if (value > 0 && value < REPORTING_TOLERANCE_MW) return '<0.1 MW unmet';
    return `${format(value)} MW unmet`;
  }

  function flowWidth(flowMW) {
    return 1.1 + 4.4 * Math.sqrt(finite(flowMW) ? Math.min(Math.abs(flowMW), 5000) / 5000 : 0);
  }

  function curvePoint(a, control, b, t) {
    const u = 1 - t;
    return { x: u * u * a.x + 2 * u * t * control.x + t * t * b.x, y: u * u * a.y + 2 * u * t * control.y + t * t * b.y };
  }

  function svg(tag, attributes = {}, text) {
    const element = document.createElementNS(NS, tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function project(lon, lat) {
    const latitude = Math.max(-85, Math.min(85, lat));
    return { x: lon * DEG, y: -Math.log(Math.tan(Math.PI / 4 + latitude * DEG / 2)) };
  }
  function polygonRings(geometry) {
    if (geometry?.type === 'Polygon') return geometry.coordinates || [];
    if (geometry?.type === 'MultiPolygon') return (geometry.coordinates || []).flat();
    return [];
  }
  function pathFor(rings) {
    return rings.filter(ring => ring.length >= 3).map(ring => ring.map(([lon, lat], index) => {
      const p = project(lon, lat);
      return `${index ? 'L' : 'M'}${p.x.toFixed(6)},${p.y.toFixed(6)}`;
    }).join('') + 'Z').join('');
  }
  function centreFor(rings) {
    const points = rings.flat().filter(point => point.length >= 2 && point.every(finite));
    if (!points.length) return null;
    const west = Math.min(...points.map(p => p[0])), east = Math.max(...points.map(p => p[0]));
    const south = Math.min(...points.map(p => p[1])), north = Math.max(...points.map(p => p[1]));
    return project((west + east) / 2, (south + north) / 2);
  }
  function overlap(a, b) { return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top; }

  class SimulationMap {
    constructor({ element, geography, onZoneSelect = () => {}, onEdgeSelect = () => {}, onViewChange = () => {}, onClearSelect = () => {} }) {
      if (!element) throw new TypeError('SimulationMap requires an SVG element.');
      this.element = element; this.onZoneSelect = onZoneSelect; this.onEdgeSelect = onEdgeSelect; this.onViewChange = onViewChange;
      this.onClearSelect = onClearSelect;
      this.zoneNodes = new Map(); this.edgeNodes = new Map(); this.listeners = []; this.pointers = new Map();
      this.state = {}; this.zoom = 1; this.selectedZone = null; this.selectedEdge = null;
      this.networkExtent = null;
      this.transferOptions = { showValues: true, animate: false, showAreas: false };
      this.hoveredEdge = null; this.focusedEdge = null; this.idLabelBoxes = []; this.focusTarget = null;
      const southWest = project(...BOUNDS[0]), northEast = project(...BOUNDS[1]);
      this.initialCentre = { x: (southWest.x + northEast.x) / 2, y: (southWest.y + northEast.y) / 2 };
      this.centre = { ...this.initialCentre };
      this.camera = new window.JMapMotion.Camera({ element,
        read: () => ({ zoom: this.zoom, x: this.centre.x, y: this.centre.y }),
        write: value => { this.zoom = value.zoom; this.centre = { x: value.x, y: value.y }; this.render(true); }
      });
      this.flowMotion = new window.JMapMotion.Flow(element);
      element.setAttribute('role', 'group'); element.setAttribute('tabindex', '0');
      element.setAttribute('aria-label', 'Simulation network. Zone colour shows unserved demand. Tab to inspect zones and corridors. Drag to pan, scroll or plus and minus to zoom, Home to reset.');
      element.style.touchAction = 'none'; element.style.cursor = 'grab';
      this.land = svg('g', { fill: 'var(--map-land, #152129)', stroke: 'var(--map-coast, #465d68)', 'stroke-width': .65, 'pointer-events': 'none' });
      for (const feature of geography?.features || []) this.land.append(svg('path', { d: pathFor(feature.polygons || []), 'vector-effect': 'non-scaling-stroke' }));
      this.zones = svg('g', { class: 'simulation-zones', display: 'none' });
      this.edges = svg('g', { class: 'simulation-edges' });
      this.zoneLabels = svg('g', { class: 'simulation-zone-labels' });
      this.transferLeaders = svg('g', { class: 'simulation-transfer-leaders', display: 'none', 'pointer-events': 'none' });
      this.transferLabels = svg('g', { class: 'simulation-transfer-labels' });
      this.reticle = svg('path', { class: 'simulation-selection-reticle', fill: 'none', stroke: 'var(--accent, #dedede)', 'stroke-width': 1.2, 'stroke-opacity': .8, 'vector-effect': 'non-scaling-stroke', 'pointer-events': 'none', 'aria-hidden': 'true', display: 'none' });
      element.replaceChildren(svg('rect', { width: '100%', height: '100%', fill: 'var(--map-sea, #1f2d35)' }), this.land, this.zones, this.edges, this.transferLeaders, this.zoneLabels, this.transferLabels, this.reticle);
      this.bindEvents();
      this.resizeObserver = new ResizeObserver(() => this.resize()); this.resizeObserver.observe(element); this.resize();
    }

    static corridorState(state, topology) { return corridorState(state, topology); }
    static zoneColour(value) { return zoneColour(value); }
    static unservedLabel(value) { return unservedLabel(value); }
    static flowWidth(value) { return flowWidth(value); }

    listen(target, type, handler, options) {
      target.addEventListener(type, handler, options);
      this.listeners.push(() => target.removeEventListener(type, handler, options));
    }
    resize() {
      const box = this.element.getBoundingClientRect();
      if (!box.width || !box.height) return;
      this.width = box.width; this.height = box.height;
      this.element.setAttribute('viewBox', `0 0 ${this.width} ${this.height}`);
      this.updateFitScale();
      this.render(false);
    }

    updateFitScale() {
      const sw = project(...BOUNDS[0]), ne = project(...BOUNDS[1]);
      const extent = (this.transferOptions.showAreas ? this.areaExtent : this.nodeExtent) || this.networkExtent || { left: sw.x, right: ne.x, top: ne.y, bottom: sw.y };
      this.initialCentre = { x: (extent.left + extent.right) / 2, y: (extent.top + extent.bottom) / 2 };
      if (!this.width || !this.height) return;
      // Hidden schematic boxes must not determine the camera. Frame the actual
      // node endpoints, leaving room for the adjacent IDs and map controls.
      const verticalPadding = Math.min(40, this.height * .09);
      const horizontalPadding = this.width < 420 ? 30 : 38;
      const availableWidth = Math.max(this.width * .45, this.width - horizontalPadding * 2);
      const availableHeight = Math.max(40, this.height - verticalPadding * 2);
      this.baseScale = .98 * Math.min(availableWidth / Math.max(1e-6, extent.right - extent.left), availableHeight / Math.max(1e-6, extent.bottom - extent.top));
    }

    bindSelectable(element, kind, id) {
      element.style.cursor = 'pointer';
      element.addEventListener('focus', () => { this.focusTarget = element; this.renderReticle(); });
      element.addEventListener('blur', () => { if (this.focusTarget === element) this.focusTarget = null; this.renderReticle(); });
      element.addEventListener('keydown', event => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault(); event.stopPropagation(); this.choose(kind, id);
      });
      element.addEventListener('click', event => { if (event.detail === 0) { event.stopPropagation(); this.choose(kind, id); } });
      if (kind === 'edge') {
        element.addEventListener('mouseenter', () => { this.hoveredEdge = id; this.updateSelection(); });
        element.addEventListener('mouseleave', event => {
          if (event.relatedTarget?.closest?.('[data-edge-id]')?.getAttribute('data-edge-id') === id) return;
          if (this.hoveredEdge === id) this.hoveredEdge = null;
          this.updateSelection();
        });
        element.addEventListener('focus', () => { this.focusedEdge = id; this.updateSelection(); });
        element.addEventListener('blur', () => { if (this.focusedEdge === id) this.focusedEdge = null; this.updateSelection(); });
      }
    }

    setTopology(zonesGeoJSON, edgesPayload = { edges: [] }) {
      const wasDefault = this.zoom === 1 && Math.abs(this.centre.x - this.initialCentre.x) < 1e-8 && Math.abs(this.centre.y - this.initialCentre.y) < 1e-8;
      this.zones.replaceChildren(); this.edges.replaceChildren(); this.zoneLabels.replaceChildren(); this.transferLeaders.replaceChildren(); this.transferLabels.replaceChildren();
      this.zoneNodes.clear(); this.edgeNodes.clear();
      this.hoveredEdge = null; this.focusedEdge = null;
      const edges = Array.isArray(edgesPayload) ? edgesPayload : edgesPayload.edges || [];
      const positions = new Map();
      const extent = { left: Infinity, right: -Infinity, top: Infinity, bottom: -Infinity };
      const nodeExtent = { ...extent };
      const extend = (point, bounds = extent) => {
        bounds.left = Math.min(bounds.left, point.x); bounds.right = Math.max(bounds.right, point.x);
        bounds.top = Math.min(bounds.top, point.y); bounds.bottom = Math.max(bounds.bottom, point.y);
      };
      edges.forEach(edge => {
        if (finite(edge.from_lon) && finite(edge.from_lat)) positions.set(edge.from, project(edge.from_lon, edge.from_lat));
        if (finite(edge.to_lon) && finite(edge.to_lat)) positions.set(edge.to, project(edge.to_lon, edge.to_lat));
      });
      positions.forEach(point => extend(point));
      for (const feature of zonesGeoJSON?.features || []) {
        const id = feature.properties?.zone_id; if (!id) continue;
        const rings = polygonRings(feature.geometry), world = positions.get(id) || centreFor(rings); if (!world) continue;
        extend(world, nodeExtent);
        rings.forEach(ring => ring.forEach(([lon, lat]) => { if (finite(lon) && finite(lat)) extend(project(lon, lat)); }));
        const shape = svg('path', { d: pathFor(rings), 'data-zone-id': id, class: 'simulation-zone', fill: '#d8ddda', 'fill-opacity': .08, stroke: '#9eafa5', 'stroke-opacity': .25, 'stroke-width': .6, 'fill-rule': 'evenodd', 'vector-effect': 'non-scaling-stroke', role: 'button', tabindex: -1 });
        const title = svg('title'); shape.append(title); this.bindSelectable(shape, 'zone', id); this.zones.append(shape);
        const label = svg('g', { 'data-zone-id': id, class: 'simulation-zone-label', role: 'button', tabindex: 0 });
        const nodeTitle = svg('title');
        const leader = svg('path', { display: 'none', 'pointer-events': 'none' });
        const box = svg('rect', { display: 'none' });
        const selection = svg('circle', { r: 8.5, fill: 'none', stroke: 'var(--ink, #e4edf0)', 'stroke-width': 1.7, class: 'simulation-zone-selection', display: 'none', 'pointer-events': 'none' });
        const dot = svg('circle', { r: 4.5, fill: '#d8ddda', stroke: '#739083', 'stroke-width': 1.5, class: 'simulation-zone-node' });
        const hit = svg('circle', { r: 13, fill: 'transparent', class: 'simulation-zone-hit' });
        const name = svg('text', { x: 9, y: -7, 'text-anchor': 'start', fill: 'var(--map-label, #c9d8dd)', 'font-size': 11, 'font-family': 'Arial, sans-serif', 'font-weight': 600, 'paint-order': 'stroke', stroke: 'var(--map-sea, #1f2d35)', 'stroke-width': 3.4, 'stroke-linejoin': 'round', class: 'simulation-zone-id' }, id);
        const value = svg('text', { display: 'none', 'aria-hidden': 'true' });
        label.append(nodeTitle, leader, box, selection, dot, hit, name, value); this.bindSelectable(label, 'zone', id); this.zoneLabels.append(label);
        this.zoneNodes.set(id, { shape, title, nodeTitle, label, leader, box, name, value, dot, selection, world, properties: feature.properties });
      }
      for (const edge of edges) {
        const id = edge.edge_id; if (!id) continue;
        const from = positions.get(edge.from) || this.zoneNodes.get(edge.from)?.world;
        const to = positions.get(edge.to) || this.zoneNodes.get(edge.to)?.world;
        if (!from || !to) continue;
        const prominent = edge.highlight === true || id === 'SSCO-NORT';
        const group = svg('g', { 'data-edge-id': id, class: 'simulation-edge', role: 'button', tabindex: 0 });
        const title = svg('title');
        const halo = svg('path', { fill: 'none', stroke: 'var(--map-sea, #1f2d35)', 'stroke-width': prominent ? 7 : 5, 'stroke-opacity': .95, 'pointer-events': 'none' });
        const line = svg('path', { fill: 'none', stroke: COLOURS.unknown, 'stroke-width': prominent ? 4.3 : 2.7, 'stroke-linecap': 'round', 'pointer-events': 'none' });
        const arrow = svg('path', { 'pointer-events': 'none' });
        const particle = svg('path', { d: 'M-7,-3L2,0L-7,3L-4,0Z', fill: '#eeeeee', stroke: COLOURS.healthy, 'stroke-width': .6, 'pointer-events': 'none', 'aria-hidden': 'true', class: 'simulation-flow-particle', display: 'none' });
        const hit = svg('path', { fill: 'none', stroke: 'transparent', 'stroke-width': 20 });
        const transferLabel = svg('g', { 'data-edge-id': id, class: 'simulation-transfer-label', role: 'presentation', tabindex: -1, 'pointer-events': 'none', 'aria-hidden': 'true' });
        const transferTitle = svg('title');
        const badgeLeader = svg('path', { display: 'none', 'pointer-events': 'none' });
        const badgeBox = svg('rect', { display: 'none' });
        const badge = svg('text', { y: 4, fill: 'var(--map-label, #c9d8dd)', 'font-family': 'Arial, sans-serif', 'font-size': 11, 'font-weight': 600, 'text-anchor': 'middle', 'paint-order': 'stroke', stroke: 'var(--map-sea, #1f2d35)', 'stroke-width': 4, 'stroke-linejoin': 'round', class: 'simulation-transfer-value' });
        const badgeMeta = svg('text', { display: 'none', 'aria-hidden': 'true', class: 'simulation-transfer-direction' });
        transferLabel.append(transferTitle, badgeBox, badge, badgeMeta); this.transferLeaders.append(badgeLeader); this.transferLabels.append(transferLabel);
        group.append(title, halo, line, arrow, particle, hit); this.bindSelectable(group, 'edge', id); this.edges.append(group);
        const dx = to.x - from.x, dy = to.y - from.y;
        const sign = [...id].reduce((sum, letter) => sum + letter.charCodeAt(0), 0) % 2 ? 1 : -1;
        const bend = finite(edge.curvature) ? Math.max(-.3, Math.min(.3, edge.curvature)) : sign * .16;
        const control = { x: (from.x + to.x) / 2 - dy * bend, y: (from.y + to.y) / 2 + dx * bend };
        transferLabel.setAttribute('visibility', 'hidden'); transferLabel.setAttribute('tabindex', -1);
        this.edgeNodes.set(id, { group, title, halo, line, arrow, hit, badge, badgeMeta, badgeLeader, badgeBox, transferLabel, transferTitle, particle, topology: edge, prominent, from, to, control });
      }
      this.areaExtent = Number.isFinite(extent.left) && extent.right > extent.left && extent.bottom > extent.top ? extent : null;
      this.nodeExtent = Number.isFinite(nodeExtent.left) && nodeExtent.right > nodeExtent.left && nodeExtent.bottom > nodeExtent.top ? nodeExtent : null;
      this.networkExtent = this.nodeExtent || this.areaExtent;
      this.updateFitScale();
      if (wasDefault) this.centre = { ...this.initialCentre };
      this.setState(this.state); return this;
    }

    setState(snapshot) {
      this.state = snapshot && typeof snapshot === 'object' ? snapshot : {};
      this.zoneNodes.forEach((entry, id) => {
        const data = this.state.zones?.[id] || {}, missing = !finite(data.unserved_mw) || data.unserved_mw < 0;
        const rawUnserved = finite(data.unserved_mw) ? String(data.unserved_mw) : 'Unavailable';
        const description = `${id} — ${entry.properties.name || id}. Unserved demand: ${rawUnserved} MW. Demand: ${format(data.demand_mw)} MW. Generation: ${format(data.generation_mw)} MW. Storage state of charge: ${finite(data.storage_soc) ? format(data.storage_soc * 100) + '%' : 'Unavailable'}.`;
        entry.shape.setAttribute('fill', zoneColour(data.unserved_mw));
        entry.dot.setAttribute('fill', zoneColour(data.unserved_mw));
        entry.dot.setAttribute('stroke', missing ? DISPLAY_COLOURS.unknown : data.unserved_mw >= REPORTING_TOLERANCE_MW ? DISPLAY_COLOURS.overload : DISPLAY_COLOURS.healthy);
        entry.shape.setAttribute('stroke-dasharray', missing ? '3 3' : 'none');
        entry.title.textContent = description; entry.nodeTitle.textContent = description; entry.shape.setAttribute('aria-label', description); entry.label.setAttribute('aria-label', description);
        entry.value.textContent = unservedLabel(data.unserved_mw);
      });
      this.edgeNodes.forEach((entry, id) => {
        entry.status = corridorState(this.state.edges?.[id], entry.topology);
        const s = entry.status;
        const direction = s.flowMW === null ? 'Flow unavailable' : s.flowMW === 0 ? 'No power flow' : `${s.from} → ${s.to}`;
        const description = `${id}. ${s.unavailable ? 'OUT OF SERVICE. ' : ''}${direction}. Signed flow: ${s.flowMW === null ? 'Unavailable' : String(s.flowMW)} MW. Current limit: ${format(s.limitMW)} MW. Nameplate limit: ${format(s.nameplateMW)} MW. Loading: ${s.loading === null ? 'Unavailable' : format(s.loading * 100) + '%'}. ${s.tripped === true ? 'Tripped or reduced capacity.' : s.tripped === null ? 'Trip status unavailable.' : 'No trip reported.'}`;
        entry.title.textContent = description; entry.group.setAttribute('aria-label', description);
        entry.transferTitle.textContent = description; entry.transferLabel.setAttribute('aria-label', description);
        entry.group.setAttribute('data-band', s.band); entry.group.setAttribute('data-reverse', String(s.reverse));
        entry.width = flowWidth(s.unavailable ? 0 : s.flowMW);
        const displayColour = s.tripped === true && s.band === 'healthy' ? DISPLAY_COLOURS.warning : DISPLAY_COLOURS[s.band];
        entry.line.setAttribute('stroke', displayColour); entry.line.setAttribute('stroke-dasharray', s.unavailable ? '2 6' : s.dashed ? '6 4' : 'none');
        entry.line.setAttribute('opacity', s.unavailable ? .55 : 1); entry.arrow.setAttribute('fill', displayColour);
        entry.particle.setAttribute('stroke', displayColour);
        const amount = s.flowMW === null ? 'Flow unavailable' : s.flowMW !== 0 && Math.abs(s.flowMW) < REPORTING_TOLERANCE_MW ? '<0.1 MW' : `${format(Math.abs(s.flowMW))} MW`;
        entry.badge.textContent = s.unavailable ? 'OUT' : amount;
        entry.badge.setAttribute('fill', s.unavailable ? 'var(--muted, #a8b8bf)' : 'var(--map-label, #c9d8dd)');
        const endpoints = s.arrow ? `${s.from}→${s.to}` : `${entry.topology.from}↔${entry.topology.to}`;
        entry.badgeMeta.textContent = s.unavailable ? `${endpoints} · no flow` : `${endpoints} · ${s.loading === null ? '?%' : format(s.loading * 100) + '%'} load`;
      });
      this.updateSelection(); this.render(false); return this;
    }

    choose(kind, id) {
      if (kind === 'zone') { this.hoveredEdge = null; this.focusedEdge = null; this.selectZone(id); this.onZoneSelect(id); }
      else if (kind === 'edge') { this.selectEdge(id); this.onEdgeSelect(id); }
    }
    selectZone(id) { this.selectedZone = id || null; if (id) this.selectedEdge = null; this.updateSelection(); this.render(false); return this; }
    selectEdge(id) { this.selectedEdge = id || null; if (id) this.selectedZone = null; this.updateSelection(); this.render(false); return this; }
    activeEdgeId() { return this.hoveredEdge || this.focusedEdge || this.selectedEdge; }
    clearSelection({ silent = false } = {}) {
      this.selectedZone = null; this.selectedEdge = null; this.hoveredEdge = null; this.focusedEdge = null;
      if (this.element.contains(document.activeElement)) this.element.focus({ preventScroll: true });
      this.updateSelection();
      if (!silent) this.onClearSelect();
      return this;
    }
    updateSelection() {
      const active = this.activeEdgeId(), activeEntry = this.edgeNodes.get(active);
      this.zoneNodes.forEach((entry, id) => {
        const selected = id === this.selectedZone;
        const endpoint = activeEntry && (activeEntry.topology.from === id || activeEntry.topology.to === id);
        entry.selection.setAttribute('display', selected || endpoint ? 'inline' : 'none');
        entry.selection.setAttribute('stroke', selected ? 'var(--ink, #e4edf0)' : 'var(--accent, #83cdb7)');
        entry.name.setAttribute('font-weight', selected || endpoint ? 700 : 500);
        entry.label.setAttribute('opacity', activeEntry && !endpoint ? .48 : 1);
        entry.dot.setAttribute('r', selected ? 5.2 : 4.5);
        entry.shape.setAttribute('aria-pressed', String(selected)); entry.label.setAttribute('aria-pressed', String(selected));
      });
      this.edgeNodes.forEach((entry, id) => {
        const selected = id === this.selectedEdge, highlighted = id === active;
        entry.group.setAttribute('aria-pressed', String(selected));
        entry.group.setAttribute('data-focused', String(highlighted));
        entry.group.setAttribute('opacity', activeEntry && !highlighted ? .22 : .95);
        entry.transferLabel.setAttribute('aria-pressed', String(selected));
        const width = entry.width || flowWidth(null);
        entry.line.setAttribute('stroke-width', width + (highlighted ? .7 : 0));
        entry.halo.setAttribute('stroke', highlighted ? 'var(--surface-hover, #253943)' : 'var(--map-sea, #1f2d35)');
        entry.halo.setAttribute('stroke-width', width + (highlighted ? 4 : 2.4));
      });
      this.renderTransfers();
      this.renderReticle();
    }

    renderReticle() {
      const target = this.focusTarget?.isConnected ? this.focusTarget : this.edgeNodes.get(this.selectedEdge)?.group || this.zoneNodes.get(this.selectedZone)?.label;
      this.reticle.setAttribute('display', 'none');
      if (!target || !this.width || !this.height) return;
      // Use the corridor itself rather than its hit area or animated particle.
      const geometry = target.classList.contains('simulation-edge') ? this.edgeNodes.get(target.dataset.edgeId)?.line : target;
      const rootMatrix = this.element.getScreenCTM(), targetMatrix = geometry?.getScreenCTM();
      if (!rootMatrix || !targetMatrix) return;
      const box = geometry.getBBox(), matrix = rootMatrix.inverse().multiply(targetMatrix);
      const points = [[box.x,box.y],[box.x+box.width,box.y],[box.x,box.y+box.height],[box.x+box.width,box.y+box.height]].map(([x,y]) => new DOMPoint(x,y).matrixTransform(matrix));
      const xs = points.map(point=>point.x), ys = points.map(point=>point.y);
      const x1 = Math.min(...xs)-12, x2 = Math.max(...xs)+12, y1 = Math.min(...ys)-12, y2 = Math.max(...ys)+12;
      if (x2<4 || x1>this.width-4 || y2<4 || y1>this.height-4) return;
      const left = Math.max(4,x1), right = Math.min(this.width-4,x2), top = Math.max(4,y1), bottom = Math.min(this.height-4,y2);
      const arm = Math.min(12,(right-left)/3,(bottom-top)/3);
      // Four screen-sized corner brackets; no solid enclosing rectangle.
      this.reticle.setAttribute('d', `M${left} ${top+arm}V${top}H${left+arm} M${right-arm} ${top}H${right}V${top+arm} M${right} ${bottom-arm}V${bottom}H${right-arm} M${left+arm} ${bottom}H${left}V${bottom-arm}`);
      this.reticle.setAttribute('display', 'inline');
    }

    setTransferOptions(options = {}) {
      const wasDefault = this.zoom === 1 && Math.abs(this.centre.x - this.initialCentre.x) < 1e-8 && Math.abs(this.centre.y - this.initialCentre.y) < 1e-8;
      if (typeof options.showValues === 'boolean') this.transferOptions.showValues = options.showValues;
      if (typeof options.animate === 'boolean') this.transferOptions.animate = options.animate;
      if (typeof options.showAreas === 'boolean') this.transferOptions.showAreas = options.showAreas;
      if (typeof options.showAreas === 'boolean') { this.updateFitScale(); if (wasDefault) this.centre = { ...this.initialCentre }; }
      this.render(false); return this;
    }

    screen(world) { const scale = this.baseScale * this.zoom; return { x: (world.x - this.centre.x) * scale + this.width / 2, y: (world.y - this.centre.y) * scale + this.height / 2 }; }
    render(emit = false) {
      if (!this.baseScale) return;
      const scale = this.baseScale * this.zoom;
      const matrix = `matrix(${scale} 0 0 ${scale} ${this.width / 2 - this.centre.x * scale} ${this.height / 2 - this.centre.y * scale})`;
      const animatedRoutes = [];
      this.land.setAttribute('transform', matrix); this.zones.setAttribute('transform', matrix);
      this.zones.setAttribute('display', this.transferOptions.showAreas ? 'inline' : 'none');
      this.edgeNodes.forEach(entry => {
        const a = this.screen(entry.from), b = this.screen(entry.to), control = this.screen(entry.control), s = entry.status || corridorState();
        const d = `M${a.x},${a.y}Q${control.x},${control.y} ${b.x},${b.y}`;
        [entry.halo, entry.line, entry.hit].forEach(line => line.setAttribute('d', d));
        const dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy) || 1;
        const middle = curvePoint(a, control, b, .5);
        entry.screen = { a, b, control, middle, nx: -dy / length, ny: dx / length };
        const arrows = length > 210 ? [.36, .72] : [.56];
        entry.arrow.setAttribute('d', s.arrow ? arrows.map(t => {
          const { x, y } = curvePoint(a, control, b, t);
          const tx = 2 * (1 - t) * (control.x - a.x) + 2 * t * (b.x - control.x);
          const ty = 2 * (1 - t) * (control.y - a.y) + 2 * t * (b.y - control.y);
          const tangentLength = Math.hypot(tx, ty) || 1, direction = s.reverse ? -1 : 1;
          const ux = tx / tangentLength * direction, uy = ty / tangentLength * direction;
          const tip = Math.max(7, (entry.width || 1) * 1.6), side = Math.max(3.5, (entry.width || 1) * .66);
          return `M${x + ux * tip},${y + uy * tip}L${x - ux * 3 - uy * side},${y - uy * 3 + ux * side}L${x - ux * 3 + uy * side},${y - uy * 3 - ux * side}Z`;
        }).join('') : '');
        const animate = this.transferOptions.animate && s.arrow;
        entry.particle.setAttribute('display', animate ? 'inline' : 'none');
        if (animate) {
          const pathLength = entry.line.getTotalLength();
          if (pathLength > 24 && Math.max(a.x,b.x,control.x) >= 0 && Math.min(a.x,b.x,control.x) <= this.width && Math.max(a.y,b.y,control.y) >= 0 && Math.min(a.y,b.y,control.y) <= this.height) {
            animatedRoutes.push({ path: entry.line, length: pathLength, start: 8, end: pathLength - 8, reverse: s.reverse,
              markers: [{ element: entry.particle, at: pathLength * .47 }] });
          } else entry.particle.setAttribute('display', 'none');
        }
      });
      this.flowMotion.setRoutes(animatedRoutes);
      const occupied = [];
      const banner = this.element.parentElement?.querySelector('.placeholder-banner');
      const mapBox = banner && !banner.hidden ? this.element.getBoundingClientRect() : null;
      const bannerBox = mapBox ? banner.getBoundingClientRect() : null;
      const labelBottom = bannerBox?.height ? Math.max(70, Math.min(this.height, bannerBox.top - mapBox.top - 4)) : this.height;
      [...this.zoneNodes.values()].map(entry => ({ entry, p: this.screen(entry.world) })).sort((a, b) => a.p.y - b.p.y).forEach(({ entry, p }) => {
        const width = String(entry.properties.zone_id).length * 6.8 + 2;
        const candidates = [[9, -7, 'start'], [9, 15, 'start'], [-9, -7, 'end'], [-9, 15, 'end'], [0, -12, 'middle'], [0, 22, 'middle']];
        let placement = null;
        for (const [x, y, anchor] of candidates) {
          const left = p.x + x - (anchor === 'end' ? width : anchor === 'middle' ? width / 2 : 0);
          const box = { left: left - 2, right: left + width + 2, top: p.y + y - 11, bottom: p.y + y + 3 };
          if (box.left < 3 || box.right > this.width - 3 || box.top < 3 || box.bottom > labelBottom - 3 || occupied.some(other => overlap(box, other))) continue;
          placement = { x, y, anchor, box }; break;
        }
        placement ||= { x: 9, y: -7, anchor: 'start' };
        const visible = p.x > -8 && p.x < this.width + 8 && p.y > -8 && p.y < this.height + 8;
        if (visible && placement.box) occupied.push(placement.box);
        // The circle always stays at the API endpoint; only the adjacent ID
        // chooses a nearby text anchor. There are no remote zone callouts.
        entry.label.setAttribute('transform', `translate(${p.x} ${p.y})`);
        entry.label.setAttribute('visibility', visible ? 'visible' : 'hidden'); entry.label.setAttribute('tabindex', visible ? 0 : -1);
        entry.name.setAttribute('x', placement.x); entry.name.setAttribute('y', placement.y); entry.name.setAttribute('text-anchor', placement.anchor);
      });
      this.idLabelBoxes = occupied; this.labelBottom = labelBottom;
      this.updateSelection();
      if (emit) this.onViewChange(this.getView());
    }

    renderTransfers() {
      this.transferLabels.setAttribute('display', this.transferOptions.showValues ? 'inline' : 'none');
      this.transferLeaders.setAttribute('display', 'none');
      this.edgeNodes.forEach(entry => {
        entry.transferLabel.setAttribute('visibility', 'hidden'); entry.transferLabel.setAttribute('tabindex', -1);
      });
      if (!this.transferOptions.showValues) return;
      const entry = this.edgeNodes.get(this.activeEdgeId()); if (!entry?.screen || !this.width) return;
      const { a, b, control, nx, ny } = entry.screen;
      if (Math.max(a.x, b.x, control.x) < 0 || Math.min(a.x, b.x, control.x) > this.width || Math.max(a.y, b.y, control.y) < 0 || Math.min(a.y, b.y, control.y) > this.height) return;
      const halfWidth = Math.max(26, entry.badge.textContent.length * 3.2), bottom = this.labelBottom || this.height;
      let placement, bestOverlap = Infinity;
      findPlacement: for (const t of [.5, .35, .65, .22, .78]) {
        for (const offset of [-15, 15, -24, 24, -32, 32]) {
          const point = curvePoint(a, control, b, t);
          const x = Math.max(halfWidth + 5, Math.min(this.width - halfWidth - 5, point.x + nx * offset));
          const y = Math.max(15, Math.min(bottom - 14, point.y + ny * offset));
          const box = { left: x - halfWidth, right: x + halfWidth, top: y - 10, bottom: y + 9 };
          const collisions = this.idLabelBoxes.filter(other => overlap(box, other)).length;
          if (collisions < bestOverlap) { bestOverlap = collisions; placement = { x, y }; }
          if (!collisions) break findPlacement;
        }
      }
      entry.transferLabel.setAttribute('transform', `translate(${placement.x} ${placement.y})`);
      entry.transferLabel.setAttribute('visibility', 'visible'); entry.transferLabel.setAttribute('tabindex', -1);
    }

    getView() { return { zoom: this.zoom, centre: { ...this.centre }, pan: { x: 0, y: 0 } }; }
    setView(view, { silent = true } = {}) {
      if (!view || !finite(view.zoom) || !finite(view.centre?.x) || !finite(view.centre?.y)) return this;
      this.camera.cancel();
      this.zoom = Math.max(.8, Math.min(12, view.zoom)); this.centre = { ...view.centre }; this.render(!silent); return this;
    }
    reset() { this.onViewChange(this.getView()); this.camera.to({ zoom: 1, ...this.initialCentre }); return this; }
    zoomBy(factor, anchor = { x: this.width / 2, y: this.height / 2 }) {
      if (!this.baseScale || !finite(factor) || factor <= 0) return this;
      const target = this.camera.target();
      const old = this.baseScale * target.zoom, next = Math.max(.8, Math.min(12, target.zoom * factor)), scale = this.baseScale * next;
      target.x += (anchor.x - this.width / 2) * (1 / old - 1 / scale);
      target.y += (anchor.y - this.height / 2) * (1 / old - 1 / scale);
      target.zoom = next; this.onViewChange(this.getView()); this.camera.to(target, { immediate: this.pointers.size > 1 }); return this;
    }
    point(event) { const box = this.element.getBoundingClientRect(); return { x: (event.clientX - box.left) * this.width / box.width, y: (event.clientY - box.top) * this.height / box.height }; }
    bindEvents() {
      this.listen(this.element, 'wheel', event => {
        if (event.ctrlKey || event.metaKey) return;
        event.preventDefault();
        const delta = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaMode === 2 ? event.deltaY * this.height : event.deltaY;
        this.zoomBy(Math.exp(-Math.max(-120, Math.min(120, delta)) * .002), this.point(event));
      }, { passive: false });
      this.listen(this.element, 'keydown', event => {
        const actions = { '+': () => this.zoomBy(1.3), '=': () => this.zoomBy(1.3), '-': () => this.zoomBy(1 / 1.3), Home: () => this.reset(), Escape: () => this.clearSelection(), ArrowLeft: () => this.panBy(40, 0), ArrowRight: () => this.panBy(-40, 0), ArrowUp: () => this.panBy(0, 40), ArrowDown: () => this.panBy(0, -40) };
        if (actions[event.key]) { event.preventDefault(); actions[event.key](); }
      });
      this.listen(this.element, 'pointerdown', event => {
        if (event.button !== 0) return;
        this.onViewChange(this.getView());
        const p = this.point(event); this.pointers.set(event.pointerId, p);
        if (this.pointers.size === 1) {
          this.start = p; this.last = p; this.moved = false;
          const target = event.target.closest('[data-zone-id], [data-edge-id]');
          this.tap = target?.hasAttribute('data-edge-id') ? ['edge', target.getAttribute('data-edge-id')] : target ? ['zone', target.getAttribute('data-zone-id')] : null;
        } else { this.moved = true; const [a, b] = [...this.pointers.values()]; this.pinch = Math.hypot(a.x - b.x, a.y - b.y); }
        this.element.setPointerCapture(event.pointerId); this.element.style.cursor = 'grabbing';
      });
      this.listen(this.element, 'pointermove', event => {
        if (!this.pointers.has(event.pointerId)) return;
        const p = this.point(event); this.pointers.set(event.pointerId, p);
        if (this.pointers.size > 1) {
          const [a, b] = [...this.pointers.values()], distance = Math.hypot(a.x - b.x, a.y - b.y);
          if (this.pinch > 0) this.zoomBy(distance / this.pinch, { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }); this.pinch = distance; return;
        }
        if (Math.hypot(p.x - this.start.x, p.y - this.start.y) > 4) this.moved = true;
        if (this.moved) this.panBy(p.x - this.last.x, p.y - this.last.y, true);
        this.last = p;
      });
      const release = (event, cancelled = false) => {
        if (!this.pointers.has(event.pointerId)) return;
        const single = this.pointers.size === 1; this.pointers.delete(event.pointerId);
        if (this.element.hasPointerCapture(event.pointerId)) this.element.releasePointerCapture(event.pointerId);
        if (!cancelled && single && !this.moved) {
          if (this.tap) this.choose(...this.tap); else this.clearSelection();
        }
        if (this.pointers.size === 1) { this.last = [...this.pointers.values()][0]; this.start = this.last; this.moved = true; }
        if (!this.pointers.size) this.element.style.cursor = 'grab';
      };
      this.listen(this.element, 'pointerup', event => release(event)); this.listen(this.element, 'pointercancel', event => release(event, true));
      this.listen(this.element,'lostpointercapture',event=>release(event,true));
      const cancelGesture = () => {
        for (const pointerId of [...this.pointers.keys()]) release({pointerId},true);
        this.moved = true; this.tap = null; this.pinch = 0; this.element.style.cursor = 'grab';
      };
      this.listen(window,'blur',cancelGesture);
      this.listen(window,'pagehide',cancelGesture);
      this.listen(document,'visibilitychange',()=>{if(document.hidden)cancelGesture();});
    }
    panBy(dx, dy, immediate = false) { if (this.baseScale) { const target = this.camera.target(), scale = this.baseScale * target.zoom; target.x -= dx / scale; target.y -= dy / scale; this.onViewChange(this.getView()); this.camera.to(target, { immediate }); } return this; }
    destroy() { this.camera.destroy(); this.flowMotion.destroy(); this.resizeObserver.disconnect(); this.listeners.forEach(remove => remove()); this.element.replaceChildren(); }
  }

  return Object.freeze({ SimulationMap, corridorState, zoneColour, unservedLabel, flowWidth });
});

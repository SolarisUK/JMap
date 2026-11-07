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
    constructor({ element, geography, onZoneSelect = () => {}, onEdgeSelect = () => {}, onViewChange = () => {} }) {
      if (!element) throw new TypeError('SimulationMap requires an SVG element.');
      this.element = element; this.onZoneSelect = onZoneSelect; this.onEdgeSelect = onEdgeSelect; this.onViewChange = onViewChange;
      this.zoneNodes = new Map(); this.edgeNodes = new Map(); this.listeners = []; this.pointers = new Map();
      this.state = {}; this.zoom = 1; this.selectedZone = null; this.selectedEdge = null;
      const southWest = project(...BOUNDS[0]), northEast = project(...BOUNDS[1]);
      this.initialCentre = { x: (southWest.x + northEast.x) / 2, y: (southWest.y + northEast.y) / 2 };
      this.centre = { ...this.initialCentre };
      element.setAttribute('role', 'group'); element.setAttribute('tabindex', '0');
      element.setAttribute('aria-label', 'Simulation network. Zone colour shows unserved demand. Tab to inspect zones and corridors. Drag to pan, scroll or plus and minus to zoom, Home to reset.');
      element.style.touchAction = 'none'; element.style.cursor = 'grab';
      this.land = svg('g', { fill: '#eef1ec', stroke: '#d4dbd3', 'stroke-width': .65, 'pointer-events': 'none' });
      for (const feature of geography?.features || []) this.land.append(svg('path', { d: pathFor(feature.polygons || []), 'vector-effect': 'non-scaling-stroke' }));
      this.zones = svg('g', { class: 'simulation-zones' });
      this.edges = svg('g', { class: 'simulation-edges' });
      this.zoneLabels = svg('g', { class: 'simulation-zone-labels' });
      element.replaceChildren(svg('rect', { width: '100%', height: '100%', fill: '#f8faf7' }), this.land, this.zones, this.edges, this.zoneLabels);
      this.bindEvents();
      this.resizeObserver = new ResizeObserver(() => this.resize()); this.resizeObserver.observe(element); this.resize();
    }

    static corridorState(state, topology) { return corridorState(state, topology); }
    static zoneColour(value) { return zoneColour(value); }
    static unservedLabel(value) { return unservedLabel(value); }

    listen(target, type, handler, options) {
      target.addEventListener(type, handler, options);
      this.listeners.push(() => target.removeEventListener(type, handler, options));
    }
    resize() {
      const box = this.element.getBoundingClientRect();
      if (!box.width || !box.height) return;
      this.width = box.width; this.height = box.height;
      this.element.setAttribute('viewBox', `0 0 ${this.width} ${this.height}`);
      const sw = project(...BOUNDS[0]), ne = project(...BOUNDS[1]);
      this.baseScale = .9 * Math.min(this.width / (ne.x - sw.x), this.height / (sw.y - ne.y));
      this.render(false);
    }

    bindSelectable(element, kind, id) {
      element.style.cursor = 'pointer';
      element.addEventListener('keydown', event => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault(); event.stopPropagation(); this.choose(kind, id);
      });
      element.addEventListener('click', event => { if (event.detail === 0) { event.stopPropagation(); this.choose(kind, id); } });
    }

    setTopology(zonesGeoJSON, edgesPayload = { edges: [] }) {
      this.zones.replaceChildren(); this.edges.replaceChildren(); this.zoneLabels.replaceChildren();
      this.zoneNodes.clear(); this.edgeNodes.clear();
      const edges = Array.isArray(edgesPayload) ? edgesPayload : edgesPayload.edges || [];
      const positions = new Map();
      edges.forEach(edge => {
        if (finite(edge.from_lon) && finite(edge.from_lat)) positions.set(edge.from, project(edge.from_lon, edge.from_lat));
        if (finite(edge.to_lon) && finite(edge.to_lat)) positions.set(edge.to, project(edge.to_lon, edge.to_lat));
      });
      for (const feature of zonesGeoJSON?.features || []) {
        const id = feature.properties?.zone_id; if (!id) continue;
        const rings = polygonRings(feature.geometry), world = positions.get(id) || centreFor(rings); if (!world) continue;
        const shape = svg('path', { d: pathFor(rings), 'data-zone-id': id, class: 'simulation-zone', fill: '#d8ddda', 'fill-opacity': .64, stroke: '#90a49a', 'stroke-width': 1, 'fill-rule': 'evenodd', 'vector-effect': 'non-scaling-stroke', role: 'button', tabindex: 0 });
        const title = svg('title'); shape.append(title); this.bindSelectable(shape, 'zone', id); this.zones.append(shape);
        const label = svg('g', { 'data-zone-id': id, class: 'simulation-zone-label', role: 'button', tabindex: 0 });
        const leader = svg('path', { fill: 'none', stroke: '#788c81', 'stroke-width': .8, 'pointer-events': 'none' });
        const box = svg('rect', { x: -36, y: -16, width: 72, height: 32, rx: 3, fill: '#ffffff', 'fill-opacity': .94, stroke: '#8aa296', 'stroke-width': .8 });
        const name = svg('text', { y: -3, 'text-anchor': 'middle', fill: '#263e34', 'font-size': 10, 'font-family': 'Arial, sans-serif', 'font-weight': 700 }, id);
        const value = svg('text', { y: 10, 'text-anchor': 'middle', fill: '#5d7065', 'font-size': 9, 'font-family': 'Arial, sans-serif' });
        label.append(leader, box, name, value); this.bindSelectable(label, 'zone', id); this.zoneLabels.append(label);
        this.zoneNodes.set(id, { shape, title, label, leader, box, value, world, properties: feature.properties });
      }
      for (const edge of edges) {
        const id = edge.edge_id; if (!id) continue;
        const from = positions.get(edge.from) || this.zoneNodes.get(edge.from)?.world;
        const to = positions.get(edge.to) || this.zoneNodes.get(edge.to)?.world;
        if (!from || !to) continue;
        const prominent = edge.highlight === true || id === 'SSCO-NORT';
        const group = svg('g', { 'data-edge-id': id, class: 'simulation-edge', role: 'button', tabindex: 0 });
        const title = svg('title');
        const halo = svg('path', { fill: 'none', stroke: '#ffffff', 'stroke-width': prominent ? 7 : 5, 'stroke-opacity': .8, 'pointer-events': 'none' });
        const line = svg('path', { fill: 'none', stroke: COLOURS.unknown, 'stroke-width': prominent ? 4.3 : 2.7, 'stroke-linecap': 'round', 'pointer-events': 'none' });
        const arrow = svg('path', { 'pointer-events': 'none' });
        const hit = svg('path', { fill: 'none', stroke: 'transparent', 'stroke-width': 15 });
        const badge = svg('text', { fill: '#3f5147', 'font-family': 'Arial, sans-serif', 'font-size': 9, 'text-anchor': 'middle', 'paint-order': 'stroke', stroke: '#ffffff', 'stroke-width': 3, 'stroke-linejoin': 'round', 'pointer-events': 'none' });
        group.append(title, halo, line, arrow, hit, badge); this.bindSelectable(group, 'edge', id); this.edges.append(group);
        this.edgeNodes.set(id, { group, title, halo, line, arrow, hit, badge, topology: edge, prominent, from, to });
      }
      this.setState(this.state); return this;
    }

    setState(snapshot) {
      this.state = snapshot && typeof snapshot === 'object' ? snapshot : {};
      this.zoneNodes.forEach((entry, id) => {
        const data = this.state.zones?.[id] || {}, missing = !finite(data.unserved_mw) || data.unserved_mw < 0;
        const rawUnserved = finite(data.unserved_mw) ? String(data.unserved_mw) : 'Unavailable';
        const description = `${id} — ${entry.properties.name || id}. Unserved demand: ${rawUnserved} MW. Demand: ${format(data.demand_mw)} MW. Generation: ${format(data.generation_mw)} MW. Storage state of charge: ${finite(data.storage_soc) ? format(data.storage_soc * 100) + '%' : 'Unavailable'}.`;
        entry.shape.setAttribute('fill', zoneColour(data.unserved_mw));
        entry.shape.setAttribute('stroke-dasharray', missing ? '3 3' : 'none');
        entry.title.textContent = description; entry.shape.setAttribute('aria-label', description); entry.label.setAttribute('aria-label', description);
        entry.value.textContent = unservedLabel(data.unserved_mw);
        entry.value.setAttribute('fill', !missing && data.unserved_mw >= REPORTING_TOLERANCE_MW ? '#a12c30' : '#4d6759');
      });
      this.edgeNodes.forEach((entry, id) => {
        entry.status = corridorState(this.state.edges?.[id], entry.topology);
        const s = entry.status;
        const direction = s.flowMW === null ? 'Flow unavailable' : s.flowMW === 0 ? 'No power flow' : `${s.from} → ${s.to}`;
        const description = `${id}. ${s.unavailable ? 'OUT OF SERVICE. ' : ''}${direction}. Signed flow: ${format(s.flowMW)} MW. Current limit: ${format(s.limitMW)} MW. Nameplate limit: ${format(s.nameplateMW)} MW. Loading: ${s.loading === null ? 'Unavailable' : format(s.loading * 100) + '%'}. ${s.tripped === true ? 'Tripped or reduced capacity.' : s.tripped === null ? 'Trip status unavailable.' : 'No trip reported.'}`;
        entry.title.textContent = description; entry.group.setAttribute('aria-label', description);
        entry.group.setAttribute('data-band', s.band); entry.group.setAttribute('data-reverse', String(s.reverse));
        entry.line.setAttribute('stroke', s.colour); entry.line.setAttribute('stroke-dasharray', s.unavailable ? '2 6' : s.dashed ? '6 4' : 'none');
        entry.line.setAttribute('opacity', s.unavailable ? .55 : 1); entry.arrow.setAttribute('fill', s.colour);
        entry.badge.textContent = s.unavailable ? 'OUT' : entry.prominent ? s.loading === null ? 'Loading unknown' : `${format(s.loading * 100)}%` : '';
      });
      this.updateSelection(); this.render(false); return this;
    }

    choose(kind, id) {
      if (kind === 'zone') { this.selectZone(id); this.onZoneSelect(id); }
      else if (kind === 'edge') { this.selectEdge(id); this.onEdgeSelect(id); }
    }
    selectZone(id) { this.selectedZone = id; this.selectedEdge = null; this.updateSelection(); return this; }
    selectEdge(id) { this.selectedEdge = id; this.selectedZone = null; this.updateSelection(); return this; }
    updateSelection() {
      this.zoneNodes.forEach((entry, id) => {
        const selected = id === this.selectedZone;
        entry.shape.setAttribute('stroke-width', selected ? 2.4 : 1); entry.shape.setAttribute('stroke', selected ? '#173e55' : '#90a49a');
        entry.box.setAttribute('stroke-width', selected ? 2 : .8); entry.box.setAttribute('stroke', selected ? '#173e55' : '#8aa296');
        entry.shape.setAttribute('aria-pressed', String(selected)); entry.label.setAttribute('aria-pressed', String(selected));
      });
      this.edgeNodes.forEach((entry, id) => {
        const selected = id === this.selectedEdge;
        entry.group.setAttribute('aria-pressed', String(selected)); entry.halo.setAttribute('stroke', selected ? '#29445b' : '#ffffff');
      });
    }

    screen(world) { const scale = this.baseScale * this.zoom; return { x: (world.x - this.centre.x) * scale + this.width / 2, y: (world.y - this.centre.y) * scale + this.height / 2 }; }
    render(emit = false) {
      if (!this.baseScale) return;
      const scale = this.baseScale * this.zoom;
      const matrix = `matrix(${scale} 0 0 ${scale} ${this.width / 2 - this.centre.x * scale} ${this.height / 2 - this.centre.y * scale})`;
      this.land.setAttribute('transform', matrix); this.zones.setAttribute('transform', matrix);
      this.edgeNodes.forEach(entry => {
        const a = this.screen(entry.from), b = this.screen(entry.to), s = entry.status || corridorState();
        const d = `M${a.x},${a.y}L${b.x},${b.y}`;
        [entry.halo, entry.line, entry.hit].forEach(line => line.setAttribute('d', d));
        const dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy) || 1;
        const direction = s.reverse ? -1 : 1, ux = dx / length * direction, uy = dy / length * direction;
        const middle = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
        entry.arrow.setAttribute('d', s.arrow ? `M${middle.x + ux * 6},${middle.y + uy * 6}L${middle.x - ux * 4 - uy * 4},${middle.y - uy * 4 + ux * 4}L${middle.x - ux * 4 + uy * 4},${middle.y - uy * 4 - ux * 4}Z` : '');
        entry.badge.setAttribute('x', middle.x + uy * 12); entry.badge.setAttribute('y', middle.y - ux * 12);
      });
      const occupied = [];
      const banner = this.element.parentElement?.querySelector('.placeholder-banner');
      const mapBox = banner && !banner.hidden ? this.element.getBoundingClientRect() : null;
      const bannerBox = mapBox ? banner.getBoundingClientRect() : null;
      const labelBottom = bannerBox?.height ? Math.max(70, Math.min(this.height, bannerBox.top - mapBox.top - 4)) : this.height;
      [...this.zoneNodes.values()].map(entry => ({ entry, p: this.screen(entry.world) })).sort((a, b) => a.p.y - b.p.y).forEach(({ entry, p }) => {
        const candidates = [[0, 0], [-48, 0], [48, 0], [0, -36], [0, 36], [-56, -26], [56, -26], [-56, 26], [56, 26], [-84, 0], [84, 0]];
        let placement = null;
        for (const [dx, dy] of candidates) {
          const x = p.x + dx, y = p.y + dy, box = { left: x - 38, right: x + 38, top: y - 18, bottom: y + 18 };
          if (box.left < 4 || box.right > this.width - 4 || box.top < 4 || box.bottom > labelBottom - 4 || occupied.some(other => overlap(box, other))) continue;
          placement = { x, y, box }; break;
        }
        // Compact split maps can exhaust the preferred offsets around London
        // and the South. Find the nearest free callout slot instead of placing
        // the last label on top of another zone or the policy-status banner.
        if (!placement) {
          let distance = Infinity;
          for (let y = 22; y <= labelBottom - 22; y += 18) {
            for (let x = 40; x <= this.width - 40; x += 38) {
              const box = { left: x - 38, right: x + 38, top: y - 18, bottom: y + 18 };
              const candidateDistance = (x - p.x) ** 2 + (y - p.y) ** 2;
              if (candidateDistance >= distance || occupied.some(other => overlap(box, other))) continue;
              distance = candidateDistance; placement = { x, y, box };
            }
          }
        }
        const visible = p.x > -30 && p.x < this.width + 30 && p.y > -30 && p.y < this.height + 30;
        placement ||= { x: Math.max(40, Math.min(this.width - 40, p.x)), y: Math.max(20, Math.min(labelBottom - 20, p.y)) };
        if (placement.box) occupied.push(placement.box);
        entry.label.setAttribute('transform', `translate(${placement.x} ${placement.y})`);
        entry.label.setAttribute('visibility', visible ? 'visible' : 'hidden'); entry.label.setAttribute('tabindex', visible ? 0 : -1);
        entry.leader.setAttribute('d', Math.hypot(placement.x - p.x, placement.y - p.y) > 2 ? `M0,0L${p.x - placement.x},${p.y - placement.y}` : '');
      });
      if (emit) this.onViewChange(this.getView());
    }

    getView() { return { zoom: this.zoom, centre: { ...this.centre }, pan: { x: 0, y: 0 } }; }
    setView(view, { silent = true } = {}) {
      if (!view || !finite(view.zoom) || !finite(view.centre?.x) || !finite(view.centre?.y)) return this;
      this.zoom = Math.max(.8, Math.min(12, view.zoom)); this.centre = { ...view.centre }; this.render(!silent); return this;
    }
    reset() { this.zoom = 1; this.centre = { ...this.initialCentre }; this.render(true); return this; }
    zoomBy(factor, anchor = { x: this.width / 2, y: this.height / 2 }) {
      if (!this.baseScale || !finite(factor) || factor <= 0) return this;
      const old = this.baseScale * this.zoom, next = Math.max(.8, Math.min(12, this.zoom * factor)), scale = this.baseScale * next;
      this.centre.x += (anchor.x - this.width / 2) * (1 / old - 1 / scale);
      this.centre.y += (anchor.y - this.height / 2) * (1 / old - 1 / scale);
      this.zoom = next; this.render(true); return this;
    }
    point(event) { const box = this.element.getBoundingClientRect(); return { x: (event.clientX - box.left) * this.width / box.width, y: (event.clientY - box.top) * this.height / box.height }; }
    bindEvents() {
      this.listen(this.element, 'wheel', event => { event.preventDefault(); this.zoomBy(Math.exp(-Math.max(-120, Math.min(120, event.deltaY)) * .002), this.point(event)); }, { passive: false });
      this.listen(this.element, 'keydown', event => {
        const actions = { '+': () => this.zoomBy(1.3), '=': () => this.zoomBy(1.3), '-': () => this.zoomBy(1 / 1.3), Home: () => this.reset(), ArrowLeft: () => this.panBy(40, 0), ArrowRight: () => this.panBy(-40, 0), ArrowUp: () => this.panBy(0, 40), ArrowDown: () => this.panBy(0, -40) };
        if (actions[event.key]) { event.preventDefault(); actions[event.key](); }
      });
      this.listen(this.element, 'pointerdown', event => {
        if (event.button !== 0) return;
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
        if (this.moved) this.panBy(p.x - this.last.x, p.y - this.last.y);
        this.last = p;
      });
      const release = (event, cancelled = false) => {
        if (!this.pointers.has(event.pointerId)) return;
        const single = this.pointers.size === 1; this.pointers.delete(event.pointerId);
        if (this.element.hasPointerCapture(event.pointerId)) this.element.releasePointerCapture(event.pointerId);
        if (!cancelled && single && !this.moved && this.tap) this.choose(...this.tap);
        if (this.pointers.size === 1) { this.last = [...this.pointers.values()][0]; this.start = this.last; this.moved = true; }
        if (!this.pointers.size) this.element.style.cursor = 'grab';
      };
      this.listen(this.element, 'pointerup', event => release(event)); this.listen(this.element, 'pointercancel', event => release(event, true));
    }
    panBy(dx, dy) { if (this.baseScale) { const scale = this.baseScale * this.zoom; this.centre.x -= dx / scale; this.centre.y -= dy / scale; this.render(true); } return this; }
    destroy() { this.resizeObserver.disconnect(); this.listeners.forEach(remove => remove()); this.element.replaceChildren(); }
  }

  return Object.freeze({ SimulationMap, corridorState, zoneColour, unservedLabel });
});

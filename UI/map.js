/* Offline SVG geography, interaction, and site markers. No mapping service required. */
(() => {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  const DEG = Math.PI / 180;
  const cities = [
    ['Edinburgh', -3.1883, 55.9533], ['Glasgow', -4.2518, 55.8642],
    ['Newcastle', -1.6178, 54.9783], ['Manchester', -2.2426, 53.4808],
    ['Birmingham', -1.8904, 52.4862], ['London', -0.1276, 51.5072],
    ['Cardiff', -3.1791, 51.4816], ['Belfast', -5.9301, 54.5973],
    ['Dublin', -6.2603, 53.3498], ['Aberdeen', -2.0943, 57.1497],
    ['Inverness', -4.2247, 57.4778], ['Plymouth', -4.1427, 50.3755]
  ];
  const seas = [
    ['N O R T H   S E A', 1.35, 56.3],
    ['I R I S H   S E A', -5.5, 53.35],
    ['A T L A N T I C', -9.4, 56.8],
    ['E N G L I S H   C H A N N E L', -2.2, 49.85]
  ];
  const fills = { wind: '#fafaf8', solar: '#b8b8b2', nuclear: '#202020', gas: '#777772', hydro: '#deded8', biomass: '#a0a09a', storage: '#fafaf8', interconnector: '#42423f' };

  function svg(tag, attributes = {}, text) {
    const node = document.createElementNS(NS, tag);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function project(lon, lat) {
    const safeLat = Math.max(-85, Math.min(85, lat));
    return { x: lon * DEG, y: -Math.log(Math.tan(Math.PI / 4 + safeLat * DEG / 2)) };
  }

  class EnergyMap {
    constructor({ element, geography, onSelect = () => {} }) {
      if (!element) throw new Error('EnergyMap requires an SVG element.');
      this.element = element;
      this.onSelect = onSelect;
      this.sites = [];
      this.mode = 'output';
      this.selectedId = null;
      this.zoom = 1;
      this.pan = { x: 0, y: 0 };
      this.pointers = new Map();
      this.markerNodes = new Map();
      this.listeners = [];
      this.initialCentre = project(-3.7, 54.9);
      this.centre = { ...this.initialCentre };
      element.setAttribute('tabindex', '0');
      element.setAttribute('role', 'group');
      element.setAttribute('aria-label', 'Electricity generation map. Drag to pan. Use plus and minus to zoom, arrow keys to pan, and Home to reset. Tab to explore generation sites.');
      element.style.touchAction = 'none';
      element.style.cursor = 'grab';
      this.background = svg('rect', { width: '100%', height: '100%', fill: '#f7f7f4' });
      this.land = svg('g', { class: 'map-land', fill: '#e7e7e2', stroke: '#c5c5bf', 'stroke-width': 0.8, 'stroke-linejoin': 'round' });
      this.labels = svg('g', { class: 'map-labels', 'pointer-events': 'none' });
      this.markers = svg('g', { class: 'map-markers' });
      element.append(this.background, this.land, this.labels, this.markers);
      this.drawGeography(geography);
      this.drawLabels();
      this.bindEvents();
      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(element);
      this.resize();
    }

    listen(target, type, callback, options) {
      target.addEventListener(type, callback, options);
      this.listeners.push(() => target.removeEventListener(type, callback, options));
    }

    resize() {
      const bounds = this.element.getBoundingClientRect();
      this.width = Math.max(1, bounds.width || 1000);
      this.height = Math.max(1, bounds.height || 720);
      this.element.setAttribute('viewBox', `0 0 ${this.width} ${this.height}`);
      const west = project(-10, 49.5);
      const east = project(3, 59.5);
      this.baseScale = Math.min(this.width / (east.x - west.x), this.height / (west.y - east.y)) * 0.94;
      this.updateView();
    }

    drawGeography(geography) {
      for (const feature of geography?.features || []) {
        const segments = [];
        for (const ring of feature.polygons || []) {
          if (ring.length < 3) continue;
          segments.push(ring.map(([lon, lat], index) => {
            const p = project(lon, lat);
            return `${index ? 'L' : 'M'}${p.x.toFixed(6)},${p.y.toFixed(6)}`;
          }).join('') + 'Z');
        }
        const path = svg('path', { d: segments.join(''), 'vector-effect': 'non-scaling-stroke' });
        path.append(svg('title', {}, feature.name || 'Land'));
        this.land.append(path);
      }
    }

    drawLabels() {
      this.labelNodes = [];
      for (const [name, lon, lat] of cities) {
        const node = svg('g');
        node.append(
          svg('circle', { r: 1.7, fill: '#94948e' }),
          svg('text', { x: 6, y: 3, fill: '#65655f', 'font-family': 'Arial, Helvetica, sans-serif', 'font-size': 10, 'paint-order': 'stroke', stroke: '#f2f2ee', 'stroke-width': 3, 'stroke-linejoin': 'round' }, name)
        );
        this.labels.append(node);
        this.labelNodes.push({ node, world: project(lon, lat), city: true });
      }
      for (const [name, lon, lat] of seas) {
        const node = svg('text', { fill: '#71716b', 'font-family': 'Arial, Helvetica, sans-serif', 'font-size': 9, 'text-anchor': 'middle' }, name);
        this.labels.append(node);
        this.labelNodes.push({ node, world: project(lon, lat), city: false });
      }
    }

    valueFor(site) {
      if (this.mode === 'utilisation') return site.capacity > 0 ? Math.max(0, site.output / site.capacity * 100) : 0;
      return Math.max(0, Number(site[this.mode === 'capacity' ? 'capacity' : 'output']) || 0);
    }

    markerShape(type, radius, attributes = {}) {
      if (type === 'solar' || type === 'storage') return svg('rect', { x: -radius * 0.85, y: -radius * 0.85, width: radius * 1.7, height: radius * 1.7, rx: type === 'storage' ? 2 : 0, ...attributes });
      if (type === 'gas') return svg('path', { d: `M0 ${-radius * 1.1} L${radius} ${radius * 0.8} L${-radius} ${radius * 0.8} Z`, ...attributes });
      if (type === 'nuclear' || type === 'interconnector') return svg('path', { d: `M0 ${-radius * 1.15} L${radius} 0 L0 ${radius * 1.15} L${-radius} 0Z`, ...attributes });
      if (type === 'hydro') return svg('path', { d: `M0 ${-radius * 1.1}C${radius * 1.7} ${radius * 0.4} ${radius * 0.8} ${radius} 0 ${radius}S${-radius * 1.7} ${radius * 0.4} 0 ${-radius * 1.1}Z`, ...attributes });
      return svg('circle', { r: radius, ...attributes });
    }

    setSites(sites, mode = this.mode) {
      this.sites = Array.isArray(sites) ? sites : [];
      this.mode = mode;
      this.markers.replaceChildren();
      this.markerNodes.clear();
      const maximum = this.mode === 'utilisation' ? 100 : Math.max(1, ...this.sites.map(site => this.valueFor(site)));
      // Draw large sites first so nearby smaller sites remain available to click.
      [...this.sites].sort((a, b) => this.valueFor(b) - this.valueFor(a)).forEach(site => {
        const radius = 3.2 + Math.sqrt(this.valueFor(site) / maximum) * 8.8;
        const group = svg('g', { class: 'map-marker', 'data-site-id': site.id, 'data-type': site.type, role: 'button', tabindex: 0, 'aria-label': `${site.name}, ${site.type}, ${Math.round(site.output).toLocaleString('en-GB')} megawatts output`, 'aria-pressed': 'false' });
        group.style.cursor = 'pointer';
        group.append(svg('title', {}, `${site.name} · ${site.type} · ${Math.round(site.output).toLocaleString('en-GB')} MW`));
        const selection = svg('circle', { r: radius + 6, fill: 'none', stroke: '#171716', 'stroke-width': 1.25, class: 'map-selection-ring', visibility: 'hidden' });
        group.append(selection);
        group.append(this.markerShape(site.type, radius, { fill: '#fff', stroke: '#fff', 'stroke-width': 4.5, 'stroke-linejoin': 'round' }));
        group.append(this.markerShape(site.type, radius, { fill: fills[site.type] || '#fff', stroke: '#242423', 'stroke-width': 1.1, 'stroke-linejoin': 'round', class: 'map-marker-shape' }));
        if (site.type === 'wind') group.append(svg('circle', { r: 1.8, fill: '#242423' }));
        if (site.type === 'biomass') group.append(svg('path', { d: `M${-radius * 0.45} 0H${radius * 0.45}M0 ${-radius * 0.45}V${radius * 0.45}`, stroke: '#fff', 'stroke-width': 1.2 }));
        group.append(svg('circle', { r: Math.max(radius + 7, 14), fill: 'transparent', class: 'map-marker-hit' }));
        const tooltip = svg('g', { visibility: 'hidden', 'pointer-events': 'none', class: 'map-marker-tooltip' });
        const labelWidth = Math.min(280, site.name.length * 5.9 + 22);
        tooltip.append(svg('rect', { x: radius + 10, y: -12, width: labelWidth, height: 25, fill: '#fff', stroke: '#d0d0ca', 'stroke-width': 1, rx: 2 }));
        tooltip.append(svg('text', { x: radius + 20, y: 4, fill: '#252524', 'font-family': 'Arial, Helvetica, sans-serif', 'font-size': 10, 'font-weight': 500 }, site.name));
        group.append(tooltip);
        group.addEventListener('mouseenter', () => { tooltip.setAttribute('visibility', 'visible'); this.markers.append(group); });
        group.addEventListener('mouseleave', () => tooltip.setAttribute('visibility', 'hidden'));
        group.addEventListener('focus', () => tooltip.setAttribute('visibility', 'visible'));
        group.addEventListener('blur', () => tooltip.setAttribute('visibility', 'hidden'));
        group.addEventListener('keydown', event => {
          if (event.key !== 'Enter' && event.key !== ' ') return;
          event.preventDefault();
          event.stopPropagation();
          this.choose(site.id);
        });
        group.addEventListener('click', event => {
          // Pointer taps are handled on pointerup, including captured touches.
          if (event.detail === 0) { event.stopPropagation(); this.choose(site.id); }
        });
        this.markers.append(group);
        this.markerNodes.set(site.id, { group, selection, tooltip, radius, world: project(site.lon, site.lat) });
      });
      this.updateView();
      this.selectSite(this.selectedId);
    }

    choose(id) {
      this.selectSite(id);
      this.onSelect(id);
    }

    selectSite(id) {
      this.selectedId = id;
      this.markerNodes.forEach(({ group, selection }, siteId) => {
        const selected = id === siteId;
        selection.setAttribute('visibility', selected ? 'visible' : 'hidden');
        group.setAttribute('aria-pressed', String(selected));
        group.classList.toggle('is-selected', selected);
        if (selected && this.markers.lastElementChild !== group) {
          const focused = document.activeElement === group;
          this.markers.append(group);
          if (focused) group.focus({ preventScroll: true });
        }
      });
    }

    focusSite(id) {
      const site = this.sites.find(item => item.id === id);
      if (!site) return;
      this.centre = project(site.lon, site.lat);
      this.pan = { x: 0, y: 0 };
      this.zoom = Math.max(this.zoom, 2);
      this.selectSite(id);
      this.updateView();
    }

    screen(world) {
      const scale = this.baseScale * this.zoom;
      return { x: (world.x - this.centre.x) * scale + this.width / 2 + this.pan.x, y: (world.y - this.centre.y) * scale + this.height / 2 + this.pan.y };
    }

    updateView() {
      if (!this.baseScale) return;
      const scale = this.baseScale * this.zoom;
      this.land.setAttribute('transform', `matrix(${scale} 0 0 ${scale} ${this.width / 2 + this.pan.x - this.centre.x * scale} ${this.height / 2 + this.pan.y - this.centre.y * scale})`);
      this.labelNodes?.forEach(({ node, world, city }) => {
        const p = this.screen(world);
        node.setAttribute('transform', `translate(${p.x.toFixed(2)} ${p.y.toFixed(2)})`);
        node.setAttribute('opacity', city ? 1 : Math.max(0, 1 - (this.zoom - 1) * 0.4));
      });
      this.markerNodes.forEach(({ group, world }) => {
        const p = this.screen(world);
        group.setAttribute('transform', `translate(${p.x.toFixed(2)} ${p.y.toFixed(2)})`);
        // Off-screen sites leave the tab order until brought back into view.
        group.setAttribute('tabindex', p.x > -15 && p.y > -15 && p.x < this.width + 15 && p.y < this.height + 15 ? '0' : '-1');
      });
      this.element.dispatchEvent(new CustomEvent('mapviewchange', { detail: { zoom: this.zoom }, bubbles: true }));
    }

    zoomBy(factor, anchor = { x: this.width / 2, y: this.height / 2 }) {
      const next = Math.max(0.8, Math.min(8, this.zoom * factor));
      const ratio = next / this.zoom;
      this.pan.x = anchor.x - this.width / 2 - (anchor.x - this.width / 2 - this.pan.x) * ratio;
      this.pan.y = anchor.y - this.height / 2 - (anchor.y - this.height / 2 - this.pan.y) * ratio;
      this.zoom = next;
      this.updateView();
    }

    reset() {
      this.zoom = 1;
      this.pan = { x: 0, y: 0 };
      this.centre = { ...this.initialCentre };
      this.updateView();
    }

    point(event) {
      const bounds = this.element.getBoundingClientRect();
      return { x: (event.clientX - bounds.left) * this.width / bounds.width, y: (event.clientY - bounds.top) * this.height / bounds.height };
    }

    nearestSite(point) {
      let nearestId = null;
      let nearestDistance = Infinity;
      this.markerNodes.forEach(({ world, radius }, id) => {
        const centre = this.screen(world);
        const distance = Math.hypot(point.x - centre.x, point.y - centre.y);
        // Select the nearest actual site rather than whichever overlapping
        // transparent touch target happens to paint above its neighbours.
        if (distance <= Math.max(radius + 7, 14) && distance < nearestDistance) {
          nearestId = id;
          nearestDistance = distance;
        }
      });
      return nearestId;
    }

    bindEvents() {
      this.listen(this.element, 'wheel', event => {
        event.preventDefault();
        this.zoomBy(Math.exp(-Math.max(-120, Math.min(120, event.deltaY)) * 0.002), this.point(event));
      }, { passive: false });
      this.listen(this.element, 'dblclick', event => {
        if (event.target.closest('[data-site-id]')) return;
        event.preventDefault();
        this.zoomBy(1.6, this.point(event));
      });
      this.listen(this.element, 'keydown', event => {
        const actions = {
          '+': () => this.zoomBy(1.3), '=': () => this.zoomBy(1.3),
          '-': () => this.zoomBy(1 / 1.3), '_': () => this.zoomBy(1 / 1.3),
          Home: () => this.reset(),
          ArrowLeft: () => { this.pan.x += 45; this.updateView(); },
          ArrowRight: () => { this.pan.x -= 45; this.updateView(); },
          ArrowUp: () => { this.pan.y += 45; this.updateView(); },
          ArrowDown: () => { this.pan.y -= 45; this.updateView(); }
        };
        if (!actions[event.key]) return;
        event.preventDefault();
        actions[event.key]();
      });
      this.listen(this.element, 'pointerdown', event => {
        if (event.button !== 0) return;
        const p = this.point(event);
        this.pointers.set(event.pointerId, p);
        if (this.pointers.size === 1) {
          this.dragStart = p;
          this.lastPointer = p;
          this.dragMoved = false;
          this.tapId = this.nearestSite(p);
        } else {
          this.dragMoved = true;
          const points = [...this.pointers.values()];
          this.pinchDistance = Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
        }
        this.element.setPointerCapture(event.pointerId);
        this.element.style.cursor = 'grabbing';
      });
      this.listen(this.element, 'pointermove', event => {
        if (!this.pointers.has(event.pointerId)) return;
        const p = this.point(event);
        this.pointers.set(event.pointerId, p);
        if (this.pointers.size >= 2) {
          const [first, second] = [...this.pointers.values()];
          const distance = Math.hypot(first.x - second.x, first.y - second.y);
          if (this.pinchDistance > 0) this.zoomBy(distance / this.pinchDistance, { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 });
          this.pinchDistance = distance;
          return;
        }
        if (Math.hypot(p.x - this.dragStart.x, p.y - this.dragStart.y) > 4) this.dragMoved = true;
        if (this.dragMoved) {
          this.pan.x += p.x - this.lastPointer.x;
          this.pan.y += p.y - this.lastPointer.y;
          this.updateView();
        }
        this.lastPointer = p;
      });
      const release = (event, cancelled = false) => {
        if (!this.pointers.has(event.pointerId)) return;
        const wasSingle = this.pointers.size === 1;
        this.pointers.delete(event.pointerId);
        if (this.element.hasPointerCapture(event.pointerId)) this.element.releasePointerCapture(event.pointerId);
        if (!cancelled && wasSingle && !this.dragMoved) this.choose(this.tapId);
        if (this.pointers.size === 1) {
          this.lastPointer = [...this.pointers.values()][0];
          this.dragStart = this.lastPointer;
          this.dragMoved = true;
        }
        if (!this.pointers.size) this.element.style.cursor = 'grab';
      };
      this.listen(this.element, 'pointerup', event => release(event));
      this.listen(this.element, 'pointercancel', event => release(event, true));
    }

    destroy() {
      this.resizeObserver.disconnect();
      this.listeners.forEach(remove => remove());
      this.element.replaceChildren();
    }
  }

  window.EnergyMap = EnergyMap;
})();

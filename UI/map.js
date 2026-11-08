/* Offline SVG geography, interaction, and site markers. No mapping service required. */
(() => {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  const DEG = Math.PI / 180;
  // Keep SVG geometry near viewport-sized units. Tiny radian paths under huge
  // transforms make native focus/stroke rasterisation fragile in Chrome.
  const GEOMETRY_SCALE = 8192;
  const regionLabelPositions = {
    england: [-1.0, 53.0], scotland: [-4.2, 57.2], wales: [-5.3, 51.6], 'northern-ireland': [-6.75, 54.7]
  };
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
    ['I R I S H   S E A', -5.1, 53.7],
    ['A T L A N T I C', -9.4, 56.8],
    ['E N G L I S H   C H A N N E L', -2.2, 49.85]
  ];
  const fills = { wind: '#fafaf8', solar: '#b8b8b2', nuclear: '#202020', gas: '#777772', hydro: '#deded8', biomass: '#a0a09a', storage: '#fafaf8', interconnector: '#42423f' };
  const nationalBounds = [[-9.0, 49.7], [3.4, 61.05]];
  const regionalBounds = {
    england: [[-6.0, 49.8], [3.1, 55.9]],
    scotland: [[-8.6, 54.5], [0.5, 61.05]],
    wales: [[-5.7, 51.2], [-2.5, 53.8]],
    'northern-ireland': [[-8.4, 54.0], [-5.3, 55.5]],
    northern_ireland: [[-8.4, 54.0], [-5.3, 55.5]],
    northernireland: [[-8.4, 54.0], [-5.3, 55.5]]
  };

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

  function projectedBounds(bounds) {
    const southWest = project(bounds[0][0], bounds[0][1]);
    const northEast = project(bounds[1][0], bounds[1][1]);
    return { left: southWest.x, right: northEast.x, top: northEast.y, bottom: southWest.y };
  }

  function shortName(name) {
    const compact = String(name).replace(/\b(Offshore Wind Farm|Wind Farm|Power Station|Solar Farm|Solar Park|Interconnector|Battery)\b/gi, '').replace(/\s+/g, ' ').trim();
    return compact.length > 27 ? `${compact.slice(0, 25)}…` : compact;
  }

  class EnergyMap {
    constructor({ element, geography, onSelect = () => {}, onRegionSelect = () => {}, onRegionHover = () => {}, onClearSelect = () => {}, scaleMaxima }) {
      if (!element) throw new Error('EnergyMap requires an SVG element.');
      this.element = element;
      this.onSelect = onSelect;
      this.onRegionSelect = onRegionSelect;
      this.onRegionHover = onRegionHover;
      this.onClearSelect = onClearSelect;
      this.sites = [];
      this.mode = 'output';
      this.scaleMaxima = { output: 1, capacity: 1, utilisation: 100 };
      this.fixedScale = false;
      this.showSiteLabels = false;
      this.showRegions = false;
      this.regionNodes = new Map();
      this.regionGeometryCache = new WeakMap();
      this.regionalGeography = null;
      this.regionLabelMode = 'all';
      this.hoveredRegionKey = null;
      this.selectedId = null;
      this.zoom = 1;
      this.pan = { x: 0, y: 0 };
      this.pointers = new Map();
      this.markerNodes = new Map();
      this.listeners = [];
      const initial = projectedBounds(nationalBounds);
      this.initialCentre = { x: (initial.left + initial.right) / 2, y: (initial.top + initial.bottom) / 2 };
      this.centre = { ...this.initialCentre };
      this.camera = new window.JMapMotion.Camera({ element,
        read: () => ({ zoom: this.zoom, x: this.centre.x, y: this.centre.y, panX: this.pan.x, panY: this.pan.y }),
        write: value => { this.zoom = value.zoom; this.centre = { x: value.x, y: value.y }; this.pan = { x: value.panX, y: value.panY }; this.updateView(); },
        inverseZoom: false
      });
      element.setAttribute('tabindex', '0');
      element.setAttribute('role', 'group');
      element.setAttribute('aria-label', 'Electricity generation map. Drag to pan. Use plus and minus to zoom, arrow keys to pan, and Home to reset. Tab to explore generation sites.');
      element.style.touchAction = 'none';
      element.style.cursor = 'grab';
      this.background = svg('rect', { width: '100%', height: '100%', fill: 'var(--map-sea, #080808)' });
      this.land = svg('g', { class: 'map-land', fill: 'var(--map-land, #141414)', stroke: 'var(--map-coast, #343434)', 'stroke-width': 0.8, 'stroke-linejoin': 'round' });
      this.regionalLayer = svg('g', { class: 'map-regions', visibility: 'hidden' });
      this.regionalLabels = svg('g', { class: 'map-region-labels', visibility: 'hidden' });
      this.labels = svg('g', { class: 'map-labels', 'pointer-events': 'none' });
      this.markers = svg('g', { class: 'map-markers' });
      this.siteLabels = svg('g', { class: 'map-site-labels', 'pointer-events': 'none' });
      this.tooltips = svg('g', { class: 'map-tooltips', 'pointer-events': 'none', 'aria-hidden': 'true' });
      element.append(this.background, this.land, this.regionalLayer, this.labels, this.markers, this.siteLabels, this.regionalLabels, this.tooltips);
      if (scaleMaxima) this.setScaleMaxima(scaleMaxima);
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
      // A hidden list/map switch has no dimensions. Retain the existing camera
      // until ResizeObserver sees the map's visible dimensions again.
      if (!bounds.width || !bounds.height) return;
      this.width = Math.max(1, bounds.width || 1000);
      this.height = Math.max(1, bounds.height || 720);
      const readout = this.element.parentElement?.querySelector('.area-hover')?.getBoundingClientRect();
      // The fixed hover readout occupies the bottom of the map. Fit and reset
      // the geography within the clear camera area so it cannot cover Cornwall.
      const coveredBottom = readout?.height && readout.top < bounds.bottom && readout.bottom > bounds.top
        ? this.height - (readout.top - bounds.top) * this.height / bounds.height + 8 : 0;
      this.cameraHeight = this.height - Math.min(this.height * .25, Math.max(0, coveredBottom));
      this.element.setAttribute('viewBox', `0 0 ${this.width} ${this.height}`);
      const initial = projectedBounds(nationalBounds);
      this.baseScale = Math.min(this.width / (initial.right - initial.left), this.cameraHeight / (initial.bottom - initial.top)) * 0.90;
      this.updateView();
    }

    drawGeography(geography) {
      for (const feature of geography?.features || []) {
        const segments = [];
        for (const ring of feature.polygons || []) {
          if (ring.length < 3) continue;
          segments.push(ring.map(([lon, lat], index) => {
            const p = this.geometryPoint(project(lon, lat));
            return `${index ? 'L' : 'M'}${p.x.toFixed(6)},${p.y.toFixed(6)}`;
          }).join('') + 'Z');
        }
        const path = svg('path', { d: segments.join(''), 'vector-effect': 'non-scaling-stroke' });
        path.append(svg('title', {}, feature.name || 'Land'));
        this.land.append(path);
      }
    }

    geometryPoint(world) {
      return { x: (world.x - this.initialCentre.x) * GEOMETRY_SCALE, y: (world.y - this.initialCentre.y) * GEOMETRY_SCALE };
    }

    regionalGeometry(geography) {
      if (!geography || typeof geography !== 'object') return [];
      if (this.regionGeometryCache.has(geography)) return this.regionGeometryCache.get(geography);
      const shapes = (geography.features || []).map(feature => {
        let west = Infinity, east = -Infinity, south = Infinity, north = -Infinity;
        const segments = (feature.polygons || []).filter(ring => ring.length >= 3).map(ring => ring.map(([lon, lat], index) => {
          west = Math.min(west, lon); east = Math.max(east, lon);
          south = Math.min(south, lat); north = Math.max(north, lat);
          const p = this.geometryPoint(project(lon, lat));
          return `${index ? 'L' : 'M'}${p.x.toFixed(6)},${p.y.toFixed(6)}`;
        }).join('') + 'Z');
        const bounds = Number.isFinite(west) ? [[west, south], [east, north]] : null;
        const position = feature.labelPosition || regionLabelPositions[feature.key] || (bounds ? [(west + east) / 2, (south + north) / 2] : null);
        return { key: feature.key, name: feature.name || feature.key, d: segments.join(''), bounds, world: position ? project(...position) : null };
      });
      this.regionGeometryCache.set(geography, shapes);
      return shapes;
    }

    bindRegionalNode(node, key) {
      node.style.cursor = 'pointer';
      // This also protects the geometry when an older stylesheet is cached.
      // Keyboard focus is indicated by the boundary/label stroke, never a filter.
      node.style.filter = 'none';
      node.style.outline = 'none';
      node.addEventListener('keydown', event => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault(); event.stopPropagation(); this.chooseRegion(key);
      });
      node.addEventListener('click', event => {
        if (event.detail === 0) { event.stopPropagation(); this.chooseRegion(key); }
      });
      node.addEventListener('mouseenter', () => { if (!this.pointers.size) this.hoverRegion(key); });
      node.addEventListener('mouseleave', () => this.hoverRegion(null));
      node.addEventListener('focus', () => this.hoverRegion(key));
      node.addEventListener('blur', () => this.hoverRegion(null));
    }

    setRegions(geography, rows = [], options = {}) {
      // Project boundaries once per geography object. Scenario, metric and
      // selection updates retain paths and focus, changing only their styling.
      const focusedKey = this.element.contains(document.activeElement) ? document.activeElement.getAttribute('data-region-key') : null;
      const focusedLabel = focusedKey && document.activeElement.getAttribute('data-label-for-region');
      const values = new Map(rows.map(row => [row.key, row]));
      const shapes = this.regionalGeometry(geography);
      this.regionLabelMode = options.labels || (shapes.length > 20 ? 'selected' : 'all');
      if (this.regionalGeography !== geography) {
        this.hoverRegion(null);
        this.regionalLayer.replaceChildren();
        this.regionalLabels.replaceChildren();
        this.regionNodes.clear();
        shapes.forEach(shape => {
          const path = svg('path', { d: shape.d, class: 'map-region', 'data-region-key': shape.key, 'stroke-linejoin': 'round', 'fill-rule': 'evenodd', 'vector-effect': 'non-scaling-stroke', role: 'button', tabindex: -1 });
          const title = svg('title'); path.append(title);
          this.bindRegionalNode(path, shape.key);
          this.regionalLayer.append(path);
          this.regionNodes.set(shape.key, { ...shape, path, title, label: null, labelWidth: 0 });
        });
        this.regionalGeography = geography;
      }
      const detailed = shapes.length > 20;
      let selectedPath = null;
      this.regionNodes.forEach(entry => {
        const row = values.get(entry.key) || { label: entry.name, valueLabel: 'No data', description: 'No published value for this area.' };
        const selected = options.selectedKey !== undefined ? options.selectedKey === entry.key : Boolean(row.selected);
        const name = row.label || entry.name;
        const accessible = `${name}: ${row.valueLabel || ''}. ${row.description || ''}`.trim();
        const { path, title } = entry;
        path.setAttribute('fill', row.fill || '#e0e4e2');
        path.setAttribute('stroke', selected ? 'var(--accent, #dedede)' : 'var(--map-coast, #343434)');
        path.setAttribute('stroke-width', selected ? (detailed ? 2.2 : 3) : (detailed ? .45 : 1.7));
        path.setAttribute('aria-label', accessible);
        path.setAttribute('aria-pressed', String(selected));
        title.textContent = accessible;
        if (selected) selectedPath = path;
        const showLabel = entry.world && (this.regionLabelMode === 'all' || selected);
        if (!showLabel && entry.label) { entry.label.remove(); entry.label = null; }
        if (showLabel) {
          const width = Math.max(74, Math.max(name.length * 5.8, String(row.valueLabel || '').length * 7.1) + 16);
          entry.labelWidth = width;
          if (!entry.label) {
            entry.label = svg('g', { class: 'map-region-label', 'data-label-for-region': entry.key, 'data-region-key': entry.key, role: 'button', tabindex: -1, 'pointer-events': 'all' });
            entry.labelBox = svg('rect', { y: -20, height: 41, rx: 3, fill: 'var(--surface-raised, #121212)', 'fill-opacity': .94 });
            entry.labelName = svg('text', { x: 0, y: -6, 'text-anchor': 'middle', fill: 'var(--muted, #a0a0a0)', 'font-family': 'Arial, Helvetica, sans-serif', 'font-size': 10 });
            entry.labelValue = svg('text', { x: 0, y: 12, 'text-anchor': 'middle', fill: 'var(--ink, #eeeeee)', 'font-family': 'Arial, Helvetica, sans-serif', 'font-size': 14, 'font-weight': 600 });
            entry.label.append(entry.labelBox, entry.labelName, entry.labelValue);
            this.bindRegionalNode(entry.label, entry.key);
            this.regionalLabels.append(entry.label);
          }
          entry.label.setAttribute('aria-label', `Select ${accessible}`);
          entry.label.setAttribute('aria-pressed', String(selected));
          entry.labelBox.setAttribute('x', -width / 2);
          entry.labelBox.setAttribute('width', width);
          entry.labelBox.setAttribute('stroke', selected ? 'var(--accent, #dedede)' : 'var(--map-coast, #343434)');
          entry.labelBox.setAttribute('stroke-width', selected ? 1.5 : .8);
          entry.labelName.textContent = name;
          entry.labelValue.textContent = row.valueLabel || '';
        }
      });
      // Draw the selected outline above its neighbours without rebuilding it.
      if (selectedPath && selectedPath !== this.regionalLayer.lastElementChild) this.regionalLayer.append(selectedPath);
      this.updateView();
      if (focusedKey && this.showRegions) {
        const selectedNode = this.regionNodes.get(focusedKey);
        (focusedLabel && selectedNode?.label ? selectedNode.label : selectedNode?.path)?.focus({ preventScroll: true });
      }
      return this;
    }

    setRegionalVisibility(visible) {
      this.showRegions = Boolean(visible);
      if (!this.showRegions) this.hoverRegion(null);
      this.regionalLayer.setAttribute('visibility', this.showRegions ? 'visible' : 'hidden');
      this.regionalLabels.setAttribute('visibility', this.showRegions ? 'visible' : 'hidden');
      [this.labels, this.markers, this.siteLabels, this.tooltips].forEach(layer => layer.setAttribute('display', this.showRegions ? 'none' : 'inline'));
      this.element.classList.toggle('has-regions', this.showRegions);
      this.element.setAttribute('aria-label', this.showRegions ? 'Annual electricity by region. Tab to select an area. Drag to pan, plus and minus to zoom, arrow keys to pan, Home to reset.' : 'Electricity site map. Tab to explore sites. Drag to pan, plus and minus to zoom, arrow keys to pan, Home to reset.');
      this.updateView();
      return this;
    }

    chooseRegion(key) {
      if (!key) { this.onClearSelect(); return; }
      if (key && this.regionNodes.has(key)) this.onRegionSelect(key);
    }

    hoverRegion(key) {
      const next = this.showRegions && key && this.regionNodes.has(key) ? key : null;
      if (next === this.hoveredRegionKey) return;
      this.hoveredRegionKey = next;
      this.onRegionHover(next);
    }

    fitRegion(key) {
      const bounds = this.regionNodes.get(key)?.bounds;
      return bounds ? this.fitBounds(bounds, { padding: 60 }) : this;
    }

    drawLabels() {
      this.labelNodes = [];
      for (const [name, lon, lat] of cities) {
        const node = svg('g');
        const leftAligned = name === 'Glasgow' || name === 'Dublin';
        const text = svg('text', { x: leftAligned ? -6 : 6, y: 3, 'text-anchor': leftAligned ? 'end' : 'start', fill: '#65655f', 'font-family': 'Arial, Helvetica, sans-serif', 'font-size': 10, 'paint-order': 'stroke', stroke: '#f2f2ee', 'stroke-width': 3, 'stroke-linejoin': 'round' }, name);
        node.append(
          svg('circle', { r: 1.7, fill: '#94948e' }),
          text
        );
        this.labels.append(node);
        const width = text.getComputedTextLength() || name.length * 5.5;
        const box = { left: leftAligned ? -8 - width : 4, right: leftAligned ? -4 : 8 + width, top: -9, bottom: 6 };
        this.labelNodes.push({ node, name, box, world: project(lon, lat), city: true });
      }
      for (const [name, lon, lat] of seas) {
        const node = svg('text', { fill: '#71716b', 'font-family': 'Arial, Helvetica, sans-serif', 'font-size': 9, 'text-anchor': 'middle' }, name);
        this.labels.append(node);
        const width = node.getComputedTextLength() || name.length * 5;
        const box = { left: -width / 2 - 2, right: width / 2 + 2, top: -10, bottom: 3 };
        this.labelNodes.push({ node, box, world: project(lon, lat), city: false });
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

    static radiusForValue(value, maximum) {
      return Math.max(3.2, 12 * Math.sqrt(Math.min(1, Math.max(0, Number(value) || 0) / Math.max(1, Number(maximum) || 1))));
    }

    static createSymbol(type, size = 18) {
      const symbol = svg('svg', { viewBox: '-12 -12 24 24', width: size, height: size, 'aria-hidden': 'true', focusable: 'false' });
      symbol.append(EnergyMap.prototype.markerShape(type, 7, { fill: fills[type] || '#fff', stroke: '#242423', 'stroke-width': 1.25, 'stroke-linejoin': 'round' }));
      if (type === 'wind') symbol.append(svg('circle', { r: 1.8, fill: '#242423' }));
      if (type === 'biomass') symbol.append(svg('path', { d: 'M-3.2 0H3.2M0-3.2V3.2', stroke: '#fff', 'stroke-width': 1.2 }));
      return symbol;
    }

    setScaleMaxima(maxima) {
      for (const mode of ['output', 'capacity', 'utilisation']) {
        const maximum = Number(maxima?.[mode]);
        if (Number.isFinite(maximum) && maximum > 0) this.scaleMaxima[mode] = maximum;
      }
      this.fixedScale = true;
      if (this.markerNodes.size) this.setSites(this.sites, this.mode);
      return this;
    }

    setLabelVisibility(visible) {
      this.showSiteLabels = Boolean(visible);
      this.updateView();
      return this;
    }

    setSites(sites, mode = this.mode) {
      this.sites = Array.isArray(sites) ? sites : [];
      this.mode = mode;
      this.markers.replaceChildren();
      this.siteLabels.replaceChildren();
      this.tooltips.replaceChildren();
      this.markerNodes.clear();
      if (!this.fixedScale) {
        this.scaleMaxima.output = Math.max(this.scaleMaxima.output, ...this.sites.map(site => Math.max(0, Number(site.output) || 0)));
        this.scaleMaxima.capacity = Math.max(this.scaleMaxima.capacity, ...this.sites.map(site => Math.max(0, Number(site.capacity) || 0)));
      }
      const maximum = this.scaleMaxima[this.mode] || this.scaleMaxima.output;
      // Draw large sites first so nearby smaller sites remain available to click.
      [...this.sites].sort((a, b) => this.valueFor(b) - this.valueFor(a)).forEach(site => {
        const radius = EnergyMap.radiusForValue(this.valueFor(site), maximum);
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
        const tooltip = svg('g', { visibility: 'hidden', 'pointer-events': 'none', class: 'map-marker-tooltip', 'data-tooltip-for': site.id });
        const labelWidth = Math.min(280, site.name.length * 5.9 + 22);
        tooltip.append(svg('rect', { x: radius + 10, y: -12, width: labelWidth, height: 25, fill: '#fff', stroke: '#d0d0ca', 'stroke-width': 1, rx: 2 }));
        tooltip.append(svg('text', { x: radius + 20, y: 4, fill: '#252524', 'font-family': 'Arial, Helvetica, sans-serif', 'font-size': 10, 'font-weight': 500 }, site.name));
        this.tooltips.append(tooltip);
        const labelText = shortName(site.name);
        const label = svg('text', { class: 'map-site-label', x: radius + 6, y: 3, fill: '#42453c', 'font-family': 'Arial, Helvetica, sans-serif', 'font-size': 10, 'paint-order': 'stroke', stroke: '#f7f7f4', 'stroke-width': 3, 'stroke-linejoin': 'round', visibility: 'hidden' }, labelText);
        this.siteLabels.append(label);
        // Keep marker nodes in place: reparenting a hovered SVG group can lose
        // its mouseleave event. A separate layer keeps labels above the map.
        group.addEventListener('mouseenter', () => this.showTooltip(site.id));
        group.addEventListener('mouseleave', () => tooltip.setAttribute('visibility', 'hidden'));
        group.addEventListener('focus', () => { if (group.matches(':focus-visible')) this.showTooltip(site.id); });
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
        this.markerNodes.set(site.id, { group, selection, tooltip, label, labelText, radius, output: site.output, world: project(site.lon, site.lat) });
      });
      this.updateView();
      this.selectSite(this.selectedId);
    }

    choose(id) {
      this.selectSite(id);
      this.onSelect(id);
    }

    showTooltip(id) {
      this.markerNodes.forEach(({ tooltip }, siteId) => tooltip.setAttribute('visibility', siteId === id ? 'visible' : 'hidden'));
    }

    hideTooltips() {
      this.markerNodes.forEach(({ tooltip }) => tooltip.setAttribute('visibility', 'hidden'));
    }

    selectSite(id) {
      this.selectedId = id;
      this.markerNodes.forEach(({ group, selection }, siteId) => {
        const selected = id === siteId;
        selection.setAttribute('visibility', selected ? 'visible' : 'hidden');
        group.setAttribute('aria-pressed', String(selected));
        group.classList.toggle('is-selected', selected);
      });
    }

    focusSite(id) {
      this.camera.cancel();
      const site = this.sites.find(item => item.id === id);
      if (!site) return;
      this.centre = project(site.lon, site.lat);
      this.pan = { x: 0, y: 0 };
      this.zoom = Math.max(this.zoom, 2);
      this.selectSite(id);
      this.updateView();
    }

    fitBounds(bounds, { padding = 42 } = {}) {
      this.camera.cancel();
      if (!this.baseScale || !Array.isArray(bounds) || bounds.length !== 2 || !bounds.every(point => Array.isArray(point) && point.length === 2 && point.every(Number.isFinite))) return this;
      const extent = projectedBounds(bounds);
      const worldWidth = Math.abs(extent.right - extent.left);
      const worldHeight = Math.abs(extent.bottom - extent.top);
      if (!worldWidth || !worldHeight) return this;
      const availableWidth = Math.max(40, this.width - Math.min(padding * 2, this.width * 0.35));
      const availableHeight = Math.max(40, this.cameraHeight - Math.min(padding * 2, this.cameraHeight * 0.35));
      this.centre = { x: (extent.left + extent.right) / 2, y: (extent.top + extent.bottom) / 2 };
      this.pan = { x: 0, y: 0 };
      this.zoom = Math.max(0.8, Math.min(this.maximumZoom(), Math.min(availableWidth / worldWidth, availableHeight / worldHeight) / this.baseScale));
      this.updateView();
      return this;
    }

    fitSites(sites = this.sites) {
      this.camera.cancel();
      const positioned = (Array.isArray(sites) ? sites : []).filter(site => Number.isFinite(site.lon) && Number.isFinite(site.lat));
      if (!positioned.length) return this;
      if (positioned.length === 1) {
        this.centre = project(positioned[0].lon, positioned[0].lat);
        this.pan = { x: 0, y: 0 };
        this.zoom = 3;
        this.updateView();
        return this;
      }
      const west = Math.min(...positioned.map(site => site.lon));
      const east = Math.max(...positioned.map(site => site.lon));
      const south = Math.min(...positioned.map(site => site.lat));
      const north = Math.max(...positioned.map(site => site.lat));
      return this.fitBounds([[west - 0.2, south - 0.18], [east + 0.2, north + 0.18]]);
    }

    focusRegion(region) {
      if (!region || region === 'all') { this.reset(); return this; }
      const bounds = regionalBounds[region];
      if (bounds) return this.fitBounds(bounds);
      return this.fitSites(this.sites.filter(site => site.region === region));
    }

    screen(world) {
      const scale = this.baseScale * this.zoom;
      return { x: (world.x - this.centre.x) * scale + this.width / 2 + this.pan.x, y: (world.y - this.centre.y) * scale + this.cameraHeight / 2 + this.pan.y };
    }

    updateView() {
      if (!this.baseScale) return;
      const scale = this.baseScale * this.zoom;
      const geometryScale = scale / GEOMETRY_SCALE;
      this.land.setAttribute('transform', `matrix(${geometryScale} 0 0 ${geometryScale} ${this.width / 2 + this.pan.x + (this.initialCentre.x - this.centre.x) * scale} ${this.cameraHeight / 2 + this.pan.y + (this.initialCentre.y - this.centre.y) * scale})`);
      this.regionalLayer.setAttribute('transform', this.land.getAttribute('transform'));
      const legendBounds = this.showRegions ? this.element.parentElement?.querySelector('.map-legend')?.getBoundingClientRect() : null;
      const mapBounds = legendBounds ? this.element.getBoundingClientRect() : null;
      const legend = legendBounds?.width && mapBounds?.width ? {
        left: (legendBounds.left - mapBounds.left) * this.width / mapBounds.width,
        right: (legendBounds.right - mapBounds.left) * this.width / mapBounds.width,
        top: (legendBounds.top - mapBounds.top) * this.height / mapBounds.height,
        bottom: (legendBounds.bottom - mapBounds.top) * this.height / mapBounds.height
      } : null;
      this.regionNodes.forEach(({ path, label, labelWidth, world, bounds }) => {
        let regionVisible = this.showRegions;
        if (bounds) {
          const sw = this.screen(project(bounds[0][0],bounds[0][1]));
          const ne = this.screen(project(bounds[1][0],bounds[1][1]));
          regionVisible = regionVisible && ne.x >= 0 && sw.x <= this.width && sw.y >= 0 && ne.y <= this.height;
        }
        path.setAttribute('tabindex', regionVisible ? '0' : '-1');
        if (!label || !world) return;
        const p = this.screen(world);
        const visible = p.x > 0 && p.x < this.width && p.y > 0 && p.y < this.height;
        if (visible) p.x = Math.max(labelWidth / 2 + 6, Math.min(this.width - labelWidth / 2 - 6, p.x));
        // Keep numeric callouts clear of the fixed legend on narrow screens.
        // Move an obstructed callout just above its left edge, away from the
        // England label on the right, while leaving geographic fills fixed.
        if (visible && legend && p.x + labelWidth / 2 > legend.left && p.x - labelWidth / 2 < legend.right && p.y + 21 > legend.top && p.y - 20 < legend.bottom) {
          p.x = Math.max(labelWidth / 2 + 6, Math.min(this.width - labelWidth / 2 - 6, legend.left + labelWidth / 2 + 5));
          p.y = Math.max(25, legend.top - 27);
        }
        label.setAttribute('transform', `translate(${p.x.toFixed(2)} ${p.y.toFixed(2)})`);
        label.setAttribute('visibility', visible ? 'visible' : 'hidden');
        label.setAttribute('tabindex', this.showRegions && visible ? '0' : '-1');
      });
      const labelBoxes = [];
      this.labelNodes?.forEach(({ node, box: localBox, world, city }) => {
        const p = this.screen(world);
        node.setAttribute('transform', `translate(${p.x.toFixed(2)} ${p.y.toFixed(2)})`);
        const opacity = city ? 1 : Math.max(0, 1 - (this.zoom - 1) * 0.4);
        node.setAttribute('opacity', opacity);
        const box = { left: p.x + localBox.left, right: p.x + localBox.right, top: p.y + localBox.top, bottom: p.y + localBox.bottom };
        // City labels take priority over sea names. The occupied rectangles use
        // actual text widths and anchors, including labels placed left of cities.
        const collides = !city && labelBoxes.some(other => box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top);
        node.setAttribute('visibility', collides ? 'hidden' : 'visible');
        if (!collides && opacity > 0.05 && box.right > 0 && box.bottom > 0 && box.left < this.width && box.top < this.height) labelBoxes.push(box);
      });
      const visibleSiteIds = [];
      this.markerNodes.forEach(({ group, label, tooltip, world }) => {
        const p = this.screen(world);
        group.setAttribute('transform', `translate(${p.x.toFixed(2)} ${p.y.toFixed(2)})`);
        label.setAttribute('transform', `translate(${p.x.toFixed(2)} ${p.y.toFixed(2)})`);
        tooltip.setAttribute('transform', `translate(${p.x.toFixed(2)} ${p.y.toFixed(2)})`);
        label.setAttribute('visibility', 'hidden');
        if (p.x >= 0 && p.y >= 0 && p.x <= this.width && p.y <= this.height) visibleSiteIds.push(group.getAttribute('data-site-id'));
        // Off-screen sites leave the tab order until brought back into view.
        group.setAttribute('tabindex', p.x > -15 && p.y > -15 && p.x < this.width + 15 && p.y < this.height + 15 ? '0' : '-1');
      });
      if (this.showSiteLabels) {
        // Prioritise the selected site, then larger output. Hide colliding labels
        // rather than obscuring other sites and place names at national scale.
        [...this.markerNodes.entries()].sort(([idA, a], [idB, b]) => Number(idB === this.selectedId) - Number(idA === this.selectedId) || b.output - a.output).forEach(([, { label, labelText, radius, world }]) => {
          const p = this.screen(world);
          const box = { left: p.x + radius + 4, right: p.x + radius + 12 + labelText.length * 5.6, top: p.y - 9, bottom: p.y + 8 };
          if (box.left < 5 || box.top < 5 || box.right > this.width - 5 || box.bottom > this.height - 5) return;
          if (labelBoxes.some(other => box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top)) return;
          label.setAttribute('visibility', 'visible');
          labelBoxes.push(box);
        });
      }
      this.element.dispatchEvent(new CustomEvent('mapviewchange', { detail: { zoom: this.zoom, visibleSiteIds }, bubbles: true }));
    }

    zoomBy(factor, anchor = { x: this.width / 2, y: this.cameraHeight / 2 }) {
      const target = this.camera.target();
      const next = Math.max(0.8, Math.min(this.maximumZoom(), target.zoom * factor));
      const ratio = next / target.zoom;
      target.panX = anchor.x - this.width / 2 - (anchor.x - this.width / 2 - target.panX) * ratio;
      target.panY = anchor.y - this.cameraHeight / 2 - (anchor.y - this.cameraHeight / 2 - target.panY) * ratio;
      target.zoom = next;
      this.camera.to(target, { immediate: this.pointers.size > 1 });
    }

    maximumZoom() { return this.showRegions && this.regionNodes.size > 20 ? 256 : 8; }

    reset() {
      this.camera.to({ zoom: 1, ...this.initialCentre, panX: 0, panY: 0 });
    }

    panBy(dx, dy) {
      const target = this.camera.target(); target.panX += dx; target.panY += dy; this.camera.to(target);
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
      this.listen(this.element, 'mouseleave', () => { this.hideTooltips(); this.hoverRegion(null); });
      this.listen(this.element, 'wheel', event => {
        if (event.ctrlKey || event.metaKey) return;
        event.preventDefault();
        this.hideTooltips();
        const delta = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaMode === 2 ? event.deltaY * this.height : event.deltaY;
        this.zoomBy(Math.exp(-Math.max(-120, Math.min(120, delta)) * 0.002), this.point(event));
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
          Escape: () => this.onClearSelect(),
          ArrowLeft: () => this.panBy(45, 0),
          ArrowRight: () => this.panBy(-45, 0),
          ArrowUp: () => this.panBy(0, 45),
          ArrowDown: () => this.panBy(0, -45)
        };
        if (!actions[event.key]) return;
        event.preventDefault();
        if (event.key === 'Escape') event.stopPropagation();
        actions[event.key]();
      });
      this.listen(this.element, 'pointerdown', event => {
        if (event.button !== 0) return;
        this.hideTooltips();
        this.hoverRegion(null);
        const p = this.point(event);
        this.pointers.set(event.pointerId, p);
        if (this.pointers.size === 1) {
          this.dragStart = p;
          this.lastPointer = p;
          this.dragMoved = false;
          this.tapId = this.showRegions ? null : this.nearestSite(p);
          this.tapRegionKey = this.showRegions ? event.target.closest('[data-region-key]')?.getAttribute('data-region-key') : null;
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
        if (cancelled) this.hideTooltips();
        if (!this.pointers.has(event.pointerId)) return;
        const wasSingle = this.pointers.size === 1;
        this.pointers.delete(event.pointerId);
        if (this.element.hasPointerCapture(event.pointerId)) this.element.releasePointerCapture(event.pointerId);
        if (!cancelled && wasSingle && !this.dragMoved) {
          if (this.showRegions) this.chooseRegion(this.tapRegionKey);
          else if (this.tapId) this.choose(this.tapId);
          else this.onClearSelect();
        }
        if (this.pointers.size === 1) {
          this.lastPointer = [...this.pointers.values()][0];
          this.dragStart = this.lastPointer;
          this.dragMoved = true;
        }
        if (!this.pointers.size) this.element.style.cursor = 'grab';
      };
      this.listen(this.element, 'pointerup', event => release(event));
      this.listen(this.element, 'pointercancel', event => release(event, true));
      this.listen(this.element, 'lostpointercapture', event => release(event, true));
      const cancelGesture = () => {
        for (const pointerId of [...this.pointers.keys()]) release({pointerId},true);
        this.dragMoved = true; this.tapId = null; this.tapRegionKey = null; this.pinchDistance = 0;
        this.element.style.cursor = 'grab';
      };
      this.listen(window,'blur',cancelGesture);
      this.listen(window,'pagehide',cancelGesture);
      this.listen(document,'visibilitychange',()=>{if(document.hidden)cancelGesture();});
    }

    destroy() {
      this.camera.destroy();
      this.resizeObserver.disconnect();
      this.listeners.forEach(remove => remove());
      this.element.replaceChildren();
    }
  }

  window.EnergyMap = EnergyMap;
})();

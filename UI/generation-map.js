/* Installed-capacity maps: named source-region overview and site exploration.
 * All bubbles encode MW; record counts belong in the inspection panel. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else { root.GenerationMap = api.GenerationMap; root.GENERATION_TECH_COLOURS = api.TECH_COLOURS; }
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const DEG = Math.PI / 180;
  const REFERENCE_MW = 25000;
  const OVERVIEW_REFERENCE_MW = 25000;
  const BOUNDS = [[-11, 49.5], [4, 61.3]];
  const TECH_COLOURS = Object.freeze({ wind_onshore: '#53bba5', wind_offshore: '#4fa7cf', solar: '#d5b85c', hydro: '#8c99d7', biomass: '#97b76d', waste: '#aaa779', gas: '#df927a', nuclear: '#bc92c7', storage: '#ce9fc3', other: '#9aafb4' });
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const clamp = (value, minimum, maximum) => Math.max(minimum, Math.min(maximum, value));

  function project(lon, lat) { return { x: lon * DEG, y: -Math.log(Math.tan(Math.PI / 4 + clamp(lat, -85, 85) * DEG / 2)) }; }
  function markerRadius(capacityMW, zoom = 1) {
    const z = clamp(finite(zoom) ? zoom : 1, .35, 64);
    const factor = z <= 1 ? Math.sqrt(z) : 1 + (22 / 18 - 1) * Math.log2(z) / 6;
    const minimum = z <= 1 ? 2 : Math.min(6, 2 * Math.sqrt(z));
    const capacity = finite(capacityMW) ? clamp(capacityMW, 0, REFERENCE_MW) : 0;
    return clamp(18 * Math.sqrt(capacity / REFERENCE_MW) * factor, minimum, 22);
  }
  function overviewRadius(capacityMW, zoom = 1) {
    const z = clamp(finite(zoom) ? zoom : 1, .35, 64);
    const factor = z <= 1 ? Math.sqrt(z) : 1 + .12 * Math.log2(z);
    return clamp(20 * Math.sqrt(Math.max(0,finite(capacityMW)?capacityMW:0) / OVERVIEW_REFERENCE_MW) * factor,2,24);
  }

  // x/y are projected screen units before camera translation. Anchoring the
  // grid in world space prevents a pan from changing cluster membership.
  function clusterSites(points, cellSize = 28) {
    const size = finite(cellSize) && cellSize > 0 ? cellSize : 28;
    const bins = new Map();
    for (const point of points || []) {
      if (!finite(point.x) || !finite(point.y)) continue;
      const column = Math.floor(point.x / size), row = Math.floor(point.y / size), key = `${column}:${row}`;
      if (!bins.has(key)) bins.set(key, { key, count: 0, x: 0, y: 0, gridX: (column + .5) * size, gridY: (row + .5) * size, members: [] });
      const bin = bins.get(key); bin.count++; bin.x += point.x; bin.y += point.y; bin.members.push(point);
    }
    return [...bins.values()].map(bin => ({ ...bin, x: bin.x / bin.count, y: bin.y / bin.count })).sort((a, b) => a.key.localeCompare(b.key));
  }

  // A group stays at its members' capacity-weighted position. Neither its
  // location nor its size is displaced to make room for a count badge.
  function layoutSites(points, zoom = 1) {
    return clusterSites(points).map(bin => {
      if (bin.count === 1) { const point=bin.members[0];return {...point,kind:'site',key:`site:${point.id}`,capacityMW:point.site?.capacityMW??null}; }
      const known=bin.members.filter(point=>finite(point.site?.capacityMW)&&point.site.capacityMW>=0);
      const total=known.reduce((n,point)=>n+point.site.capacityMW,0);
      const x=total>0?known.reduce((n,point)=>n+point.x*point.site.capacityMW,0)/total:bin.x;
      const y=total>0?known.reduce((n,point)=>n+point.y*point.site.capacityMW,0)/total:bin.y;
      const types=new Set(bin.members.map(point=>point.site?.type));
      return {...bin,x,y,kind:'cluster',key:`cluster:${bin.key}`,capacityMW:known.length===bin.count?total:null,knownCapacityMW:total,type:types.size===1?bin.members[0].site?.type:'mixed'};
    });
  }
  function colourFor(type) {
    const value = String(type || '').toLowerCase().replace(/[\s-]+/g, '_');
    if (TECH_COLOURS[value]) return TECH_COLOURS[value];
    if (/offshore/.test(value)) return TECH_COLOURS.wind_offshore;
    if (/wind/.test(value)) return TECH_COLOURS.wind_onshore;
    if (/solar|photovoltaic/.test(value)) return TECH_COLOURS.solar;
    if (/hydro|tidal|wave|marine/.test(value)) return TECH_COLOURS.hydro;
    if (/battery|storage|pumped/.test(value)) return TECH_COLOURS.storage;
    if (/waste|landfill|sewage/.test(value)) return TECH_COLOURS.waste;
    if (/biomass|biogas|anaerobic/.test(value)) return TECH_COLOURS.biomass;
    if (/gas|oil|coal|diesel/.test(value)) return TECH_COLOURS.gas;
    if (/nuclear/.test(value)) return TECH_COLOURS.nuclear;
    return TECH_COLOURS.other;
  }
  function svg(tag, attributes = {}, text) {
    const element = document.createElementNS(NS, tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function geographyPath(polygons) {
    return (polygons || []).filter(ring => ring.length >= 3).map(ring => ring.map(([lon, lat], i) => {
      const p = project(lon, lat); return `${i ? 'L' : 'M'}${p.x.toFixed(6)},${p.y.toFixed(6)}`;
    }).join('') + 'Z').join('');
  }

  class GenerationMap {
    constructor({ element, geography, onSelect = () => {}, onHover = () => {}, onViewChange = () => {}, onClusterSelect = () => {}, onClearSelect = () => {}, onRegionSelect = () => {}, onReset = () => {}, colourFor: customColour }) {
      if (!element) throw new TypeError('GenerationMap requires an SVG element.');
      this.element = element; this.onSelect = onSelect; this.onHover = onHover; this.onViewChange = onViewChange; this.onClusterSelect = onClusterSelect;
      this.onClearSelect = onClearSelect;
      this.onRegionSelect=onRegionSelect;this.onReset=onReset;this.mode='overview';this.overviewGroups=[];this.regionNodes=new Map();
      this.hoveredRegionId=null;this.focusedRegionId=null;this.previewedRegionId=null;
      this.colourFor = typeof customColour === 'function' ? customColour : colourFor;
      this.sites = []; this.points = []; this.byId = new Map(); this.nodes = new Map(); this.listeners = []; this.pointers = new Map();
      this.zoom = 1; this.selectedId = null; this.destroyed = false; this.frame = null;
      this.tap = null; this.start = null; this.last = null; this.pinch = null; this.moved = false; this.suppressDoubleClickUntil = 0;
      const sw = project(...BOUNDS[0]), ne = project(...BOUNDS[1]);
      this.initialCentre = { x: (sw.x + ne.x) / 2, y: (sw.y + ne.y) / 2 }; this.centre = { ...this.initialCentre };
      this.camera = new window.JMapMotion.Camera({ element,
        read: () => ({ zoom: this.zoom, x: this.centre.x, y: this.centre.y }),
        write: value => { this.zoom = value.zoom; this.centre = { x: value.x, y: value.y }; this.render(true); }
      });
      element.setAttribute('role', 'group'); element.setAttribute('tabindex', 0);
      element.setAttribute('aria-label', 'UK installed capacity by source region. Select a named region to explore its sites. Drag to pan, plus and minus to zoom, Home for the overview.');
      element.style.touchAction = 'none'; element.style.cursor = 'grab';
      this.land = svg('g', { class: 'generation-land', fill: 'var(--map-land, #141414)', stroke: 'var(--map-coast, #343434)', 'stroke-width': .7, 'stroke-linejoin': 'round', 'pointer-events': 'none' });
      for (const feature of geography?.features || []) this.land.append(svg('path', { d: geographyPath(feature.polygons), 'vector-effect': 'non-scaling-stroke' }));
      this.countryLabels = svg('g', { 'pointer-events': 'none', 'aria-hidden': 'true' });
      this.countryNodes = [['SCOTLAND', -4.4, 57.1], ['ENGLAND', -1.6, 52.8], ['WALES', -4.3, 52.1], ['N. IRELAND', -6.8, 54.7], ['IRELAND', -8.2, 53.0]].map(([name, lon, lat]) => {
        const node = svg('text', { fill: 'var(--map-label, #bdbdbd)', 'fill-opacity': .5, 'font-family': 'Arial, sans-serif', 'font-size': 9, 'letter-spacing': 1.2, 'text-anchor': 'middle' }, name);
        this.countryLabels.append(node); return { node, world: project(lon, lat) };
      });
      this.markers = svg('g', { class: 'generation-markers' });
      this.regions=svg('g',{class:'generation-regions'});
      this.regionReadout=svg('g',{class:'generation-region-readout','aria-hidden':'true','pointer-events':'none',display:'none'});
      this.regionReadoutBox=svg('rect',{fill:'var(--surface, #111)',stroke:'var(--line, #333)','stroke-width':1,rx:3});
      this.regionReadoutName=svg('text',{x:12,y:18,fill:'var(--ink, #eee)','font-family':'Arial, sans-serif','font-size':12,'font-weight':500,class:'generation-region-label'});
      this.regionReadoutCapacity=svg('text',{x:12,y:35,fill:'var(--muted, #aaa)','font-family':'Arial, sans-serif','font-size':11});
      this.regionReadout.append(this.regionReadoutBox,this.regionReadoutName,this.regionReadoutCapacity);
      element.replaceChildren(svg('rect', { width: '100%', height: '100%', fill: 'var(--map-sea, #080808)' }), this.land, this.countryLabels, this.regions, this.markers,this.regionReadout);
      this.bindEvents(); this.resizeObserver = new ResizeObserver(() => this.resize()); this.resizeObserver.observe(element); this.resize();
    }
    static markerRadius(capacity, zoom) { return markerRadius(capacity, zoom); }
    static radiusForCapacity(capacity, zoom) { return markerRadius(capacity, zoom); }
    static overviewRadius(capacity,zoom) {return overviewRadius(capacity,zoom);}
    static get TECH_COLOURS() { return TECH_COLOURS; }
    static get REFERENCE_MW() { return REFERENCE_MW; }
    static get OVERVIEW_REFERENCE_MW() {return OVERVIEW_REFERENCE_MW;}
    static colourFor(type) { return colourFor(type); }

    listen(target, type, callback, options) { target.addEventListener(type, callback, options); this.listeners.push(() => target.removeEventListener(type, callback, options)); }
    resize() {
      const box = this.element.getBoundingClientRect(); if (!box.width || !box.height) return;
      this.width = box.width; this.height = box.height; this.element.setAttribute('viewBox', `0 0 ${this.width} ${this.height}`);
      const sw = project(...BOUNDS[0]), ne = project(...BOUNDS[1]);
      this.baseScale = .9 * Math.min(this.width / (ne.x - sw.x), this.height / (sw.y - ne.y)); this.render(true);
    }
    setSites(sites) {
      this.sites = Array.isArray(sites) ? sites : []; this.points = []; this.byId.clear();
      this.sites.forEach(site => {
        if (site?.id === null || site?.id === undefined || !finite(site.lon) || !finite(site.lat) || Math.abs(site.lon) > 180 || Math.abs(site.lat) > 85) return;
        const id = String(site.id); if (this.byId.has(id)) return;
        const point = { id, site, world: project(site.lon, site.lat) }; this.points.push(point); this.byId.set(id, point);
      });
      this.render(true); return this;
    }
    setOverviewGroups(groups) {
      this.hoveredRegionId=null;this.focusedRegionId=null;this.previewedRegionId=null;
      this.overviewGroups=(Array.isArray(groups)?groups:[]).filter(group=>group?.id&&finite(group.lat)&&finite(group.lon));
      this.render(true);return this;
    }
    setMode(mode) {
      if(!['overview','sites'].includes(mode))throw new TypeError('Map mode must be overview or sites.');
      if(this.mode!==mode){this.mode=mode;this.hoveredRegionId=null;this.focusedRegionId=null;this.previewedRegionId=null;if(mode==='overview'){this.nodes.clear();this.markers.replaceChildren();}}
      this.element.dataset.mode=mode;
      this.element.setAttribute('aria-label',mode==='overview'?'Installed capacity by named UK source region. Select a region for its sites.':'UK registered generating sites. Every bubble shows installed capacity; nearby sites can share a combined-capacity bubble.');
      this.render(true);return this;
    }
    siteDescription(site) {
      const capacity = finite(site.capacityMW) ? `${site.capacityMW.toLocaleString('en-GB', { maximumFractionDigits: 2 })} MW installed capacity` : 'Capacity unavailable';
      return [site.name, site.type, capacity, site.operator, site.country, site.status].filter(Boolean).join(' · ');
    }
    createNode(kind, key) {
      const group = svg('g', { class: kind === 'site' ? 'generation-marker' : 'generation-cluster', role: 'button', tabindex: 0 });
      group.style.cursor = 'pointer';
      const title = svg('title'), ring = svg('circle', { fill: 'none', stroke: '#ffffff', 'stroke-width': 1.7, display: 'none', 'pointer-events': 'none', class: 'generation-selection-ring' });
      const circle = svg('circle', { 'stroke-width': 1.1, class: kind === 'site' ? 'generation-bubble' : 'generation-cluster-bubble' });
      const text = svg('text', { 'text-anchor': 'middle', y: 3.5, fill: '#ededed', 'font-family': 'Arial, sans-serif', 'font-size': 10.5, 'font-weight': 600, 'pointer-events': 'none' });
      const name = svg('text', { fill: '#eee', 'font-family': 'Arial, sans-serif', 'font-size': 10, 'paint-order': 'stroke', stroke: 'var(--map-land, #141414)', 'stroke-width': 2.5, 'stroke-linejoin': 'round', 'pointer-events': 'bounding-box', display: 'none', class: 'generation-site-label' });
      const hit = svg('circle', { fill: 'transparent', class: 'generation-marker-hit' });
      group.append(title, ring, circle, text, name, hit);
      const entry = { group, title, ring, circle, text, name, hit, kind, key, item: null };
      group.addEventListener('keydown', event => { if (!event.ctrlKey && !event.metaKey && !event.altKey && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); event.stopPropagation(); this.choose(entry); } });
      group.addEventListener('click', event => { if (event.detail === 0) { event.stopPropagation(); this.choose(entry); } });
      group.addEventListener('mouseenter', () => { circle.setAttribute('stroke-width', 1.8); this.onHover(entry.kind === 'site' ? entry.item.site : null); });
      group.addEventListener('mouseleave', () => { circle.setAttribute('stroke-width', 1.1); this.onHover(null); });
      group.addEventListener('focus', () => this.onHover(entry.kind === 'site' ? entry.item.site : null));
      group.addEventListener('blur', () => this.onHover(null));
      this.markers.append(group); this.nodes.set(key, entry); return entry;
    }
    renderOverview() {
      const keep=new Set();
      for(const item of this.overviewGroups){
        let entry=this.regionNodes.get(item.id);
        if(!entry){
          const group=svg('g',{class:'generation-region','data-region-id':item.id,role:'button',tabindex:0});group.style.cursor='pointer';
          const circle=svg('circle',{class:'generation-region-bubble',fill:'#ddd','fill-opacity':.07,stroke:'#888','stroke-width':1});
          const hit=svg('circle',{fill:'transparent'});
          group.append(circle,hit);
          entry={group,circle,hit,item:null,kind:'region'};
          group.addEventListener('keydown',event=>{if(!event.ctrlKey&&!event.metaKey&&!event.altKey&&(event.key==='Enter'||event.key===' ')){event.preventDefault();event.stopPropagation();this.choose(entry);}});
          group.addEventListener('click',event=>{if(event.detail===0){event.stopPropagation();this.choose(entry);}});
          group.addEventListener('mouseenter',()=>{this.hoveredRegionId=item.id;this.renderRegionReadout();});
          group.addEventListener('mouseleave',()=>{if(this.hoveredRegionId===item.id)this.hoveredRegionId=null;this.renderRegionReadout();});
          group.addEventListener('focus',()=>{this.focusedRegionId=item.id;this.renderRegionReadout();});
          group.addEventListener('blur',()=>{if(this.focusedRegionId===item.id)this.focusedRegionId=null;this.renderRegionReadout();});
          this.regions.append(group);this.regionNodes.set(item.id,entry);
        }
        keep.add(item.id);entry.item={kind:'region',group:item};
        const p=this.screen(project(item.lon,item.lat)),radius=overviewRadius(item.capacityMW,this.zoom);
        const visible=p.x>=-radius&&p.x<=this.width+radius&&p.y>=-radius&&p.y<=this.height+radius;
        entry.group.setAttribute('transform',`translate(${p.x.toFixed(2)} ${p.y.toFixed(2)})`);entry.group.setAttribute('display',visible?'inline':'none');entry.group.setAttribute('tabindex',visible?0:-1);
        entry.group.dataset.capacityMw=finite(item.capacityMW)?item.capacityMW:'';entry.group.dataset.count=item.siteCount??item.sites?.length??0;
        const amount=finite(item.capacityMW)?`${(item.capacityMW/1000).toLocaleString('en-GB',{maximumFractionDigits:2})} GW`:'Capacity unavailable';
        entry.group.setAttribute('aria-label',`${item.name}: ${amount} installed capacity. Select to explore the underlying sites.${item.isOffshore?' This is a UK-wide offshore summary, not a single site.':''}`);
        entry.circle.setAttribute('r',radius);entry.circle.setAttribute('stroke-dasharray',!finite(item.capacityMW)?'2 2':item.isOffshore?'4 3':'none');entry.hit.setAttribute('r',Math.max(radius,14));
      }
      this.regionNodes.forEach((entry,id)=>{if(!keep.has(id)){entry.group.remove();this.regionNodes.delete(id);}});
      this.renderRegionReadout();
    }
    previewRegion(id) {
      this.previewedRegionId=this.regionNodes.has(id)?id:null;
      this.renderRegionReadout();return this;
    }
    renderRegionReadout() {
      this.regionReadout.setAttribute('display','none');
      const id=this.hoveredRegionId||this.previewedRegionId||this.focusedRegionId;
      const active=this.mode==='overview'?this.regionNodes.get(id):null;
      this.regionNodes.forEach((entry,key)=>{
        const highlighted=active&&key===id;
        entry.group.dataset.highlighted=String(Boolean(highlighted));
        entry.group.setAttribute('opacity',active&&!highlighted ? .55 : 1);
        entry.circle.setAttribute('fill-opacity',highlighted ? .18 : .07);
        entry.circle.setAttribute('stroke',highlighted?'#eee':'#888');
        entry.circle.setAttribute('stroke-width',highlighted?1.5:1);
      });
      if(!active?.item||!this.width||!this.height)return;
      const item=active.item.group,p=this.screen(project(item.lon,item.lat));
      if(p.x<0||p.x>this.width||p.y<0||p.y>this.height)return;
      this.regionReadoutName.textContent=item.isOffshore?`${item.name} \u00b7 UK-wide`:item.name;
      this.regionReadoutCapacity.textContent=finite(item.capacityMW)?`${(item.capacityMW/1000).toLocaleString('en-GB',{maximumFractionDigits:2})} GW installed`:'Capacity unavailable';
      const width=Math.min(this.width-16,Math.max(this.regionReadoutName.textContent.length*6.7,this.regionReadoutCapacity.textContent.length*6)+24),height=46;
      const radius=overviewRadius(item.capacityMW,this.zoom);
      const x=clamp(p.x-width/2,8,this.width-width-8),y=clamp(p.y-radius-height-8>=8?p.y-radius-height-8:p.y+radius+8,8,this.height-height-8);
      this.regionReadoutBox.setAttribute('width',width);this.regionReadoutBox.setAttribute('height',height);
      this.regionReadout.setAttribute('transform',`translate(${x} ${y})`);this.regionReadout.setAttribute('display','inline');
    }
    screen(world) {
      const scale=this.baseScale*this.zoom;
      return {x:(world.x-this.centre.x)*scale+this.width/2,y:(world.y-this.centre.y)*scale+this.height/2};
    }
    render(emit = false) {
      if (!this.baseScale || this.destroyed) return;
      const scale = this.baseScale * this.zoom, tx = this.width / 2 - this.centre.x * scale, ty = this.height / 2 - this.centre.y * scale;
      this.land.setAttribute('transform', `matrix(${scale} 0 0 ${scale} ${tx} ${ty})`);
      this.element.dataset.mode=this.mode;
      this.regions.setAttribute('display',this.mode==='overview'?'inline':'none');
      this.markers.setAttribute('display',this.mode==='sites'?'inline':'none');
      if(this.mode!=='overview')this.regionReadout.setAttribute('display','none');
      this.countryLabels.setAttribute('display',this.mode==='sites'?'inline':'none');
      this.countryNodes.forEach(({ node, world }) => { node.setAttribute('x', world.x * scale + tx); node.setAttribute('y', world.y * scale + ty); node.setAttribute('display', this.zoom > 4 ? 'none' : 'inline'); });
      let visibleCount = 0;
      const positioned = [];
      for (const point of this.points) {
        const x = point.world.x * scale, y = point.world.y * scale, sx = x + tx, sy = y + ty;
        if (sx >= 0 && sx <= this.width && sy >= 0 && sy <= this.height) visibleCount++;
        if (sx > -50 && sx < this.width + 50 && sy > -50 && sy < this.height + 50) positioned.push({ ...point, x, y });
      }
      if(this.mode==='overview'){
        this.renderOverview();
        if(emit)this.onViewChange({zoom:this.zoom,mode:this.mode,overviewCount:this.overviewGroups.length,visibleCount,clusterCount:0,markerCount:0,totalCount:this.sites.length,mappedCount:this.points.length});
        return;
      }
      const items = layoutSites(positioned.filter(point=>point.id!==this.selectedId), this.zoom).map(item => ({ ...item, x: item.x + tx, y: item.y + ty }));
      const clusterCount = items.filter(item => item.kind === 'cluster' && item.x >= 0 && item.x <= this.width && item.y >= 0 && item.y <= this.height).length;
      // A selected member of a cluster stays inspectable as a bounded individual
      // marker, removed from its former group's capacity to avoid double counting.
      const selected = this.byId.get(this.selectedId);
      if (selected && !items.some(item => item.kind === 'site' && item.id === this.selectedId)) {
        const x = selected.world.x * scale + tx, y = selected.world.y * scale + ty;
        if (x > -30 && x < this.width + 30 && y > -30 && y < this.height + 30) items.push({ ...selected, kind: 'site', key: `site:${selected.id}`,capacityMW:selected.site.capacityMW, x, y });
      }
      const retained = new Set();
      items.forEach(item => {
        const entry = this.nodes.get(item.key) || this.createNode(item.kind, item.key); retained.add(item.key); entry.item = item;
        const selected = item.kind === 'site' && item.id === this.selectedId;
        const radius = markerRadius(item.capacityMW, this.zoom);
        const colour = item.kind === 'cluster' ? item.type==='mixed'?'#aaa':this.colourFor(item.type) : this.colourFor(item.site.type);
        entry.group.dataset.capacityMw=finite(item.capacityMW)?item.capacityMW:'';
        entry.group.dataset.count=item.kind==='cluster'?item.count:1;
        entry.group.setAttribute('transform', `translate(${item.x.toFixed(2)} ${item.y.toFixed(2)})`);
        entry.group.setAttribute('aria-pressed', String(selected)); entry.group.setAttribute('tabindex', item.x >= 0 && item.x <= this.width && item.y >= 0 && item.y <= this.height ? 0 : -1);
        entry.circle.setAttribute('r', radius.toFixed(2)); entry.circle.setAttribute('fill', colour); entry.circle.setAttribute('fill-opacity', item.kind === 'cluster' ? .25 : .55);
        entry.circle.setAttribute('stroke', colour);
        entry.circle.setAttribute('stroke-dasharray', !finite(item.capacityMW) ? '2 2' : 'none');
        entry.hit.setAttribute('r', Math.max(8, radius + 2)); entry.ring.setAttribute('r', Math.min(26, radius + 3.5)); entry.ring.setAttribute('display', selected ? 'inline' : 'none');
        entry.name.setAttribute('display', 'none');
        if (item.kind === 'cluster') {
          const amount=finite(item.capacityMW)?`${item.capacityMW.toLocaleString('en-GB',{maximumFractionDigits:1})} MW combined installed capacity`:'Combined capacity unavailable';
          const description = `${amount}, ${item.count.toLocaleString('en-GB')} registered sites. Select for a breakdown.`;
          entry.title.textContent = description; entry.group.setAttribute('aria-label', description); entry.group.setAttribute('data-count', item.count);
          entry.text.textContent = ''; entry.text.setAttribute('display', 'none');
        } else {
          const description = this.siteDescription(item.site); entry.title.textContent = description; entry.group.setAttribute('aria-label', description); entry.group.setAttribute('data-site-id', item.id); entry.group.setAttribute('data-type', item.site.type || 'other'); entry.text.setAttribute('display', 'none');
          if (selected && this.zoom >= 3.5) {
            const name = String(item.site.name || '').slice(0, 42), right = item.x + radius + 7 + name.length * 5.5 < this.width - 6;
            entry.name.textContent = name; entry.name.setAttribute('x', right ? radius + 7 : -radius - 7); entry.name.setAttribute('y', 3); entry.name.setAttribute('text-anchor', right ? 'start' : 'end'); entry.name.setAttribute('display', 'inline');
          }
        }
      });
      this.nodes.forEach((entry, key) => { if (!retained.has(key)) { entry.group.remove(); this.nodes.delete(key); } });
      const selectedNode = this.nodes.get(`site:${this.selectedId}`);
      if (selectedNode && this.markers.lastElementChild !== selectedNode.group) this.markers.append(selectedNode.group);
      if (emit) this.onViewChange({ zoom: this.zoom,mode:this.mode,overviewCount:this.overviewGroups.length, visibleCount, clusterCount, markerCount: items.filter(item => item.kind === 'site').length, totalCount: this.sites.length, mappedCount: this.points.length });
    }
    selectSite(id) { this.selectedId = id === null || id === undefined ? null : String(id); this.render(false); return this; }
    clearSelection({ silent = false } = {}) {
      const restoreFocus = this.element.contains(document.activeElement);
      this.selectSite(null); this.onHover(null);
      if (restoreFocus) this.element.focus({ preventScroll: true });
      if (!silent) this.onClearSelect();
      return this;
    }
    choose(entry) {
      const item = entry.item; if (!item) return;
      if(item.kind==='region'){this.onRegionSelect(item.group);this.element.focus({preventScroll:true});return;}
      if (item.kind === 'site') { this.selectSite(item.id); this.onSelect(item.id); return; }
      const members = item.members.map(point => point.site), selection = this.onClusterSelect({ count: item.count, sites: members });
      if (selection === false) return;
      this.fitSites(Array.isArray(selection?.sites) ? selection.sites : members, true);
      this.element.focus({preventScroll:true});
    }
    focusSite(id) {
      const point = this.byId.get(String(id)); if (!point) return this;
      this.camera.cancel();
      this.selectedId = point.id; this.centre = { ...point.world }; this.zoom = Math.max(this.zoom, 8); this.render(true); return this;
    }
    fitSites(sites = this.sites, expand = false) {
      this.camera.cancel();
      const points = (Array.isArray(sites) ? sites : []).filter(site => finite(site.lon) && finite(site.lat)).map(site => project(site.lon, site.lat));
      if (!points.length || !this.baseScale) return this;
      const xs = points.map(p => p.x), ys = points.map(p => p.y), left = Math.min(...xs), right = Math.max(...xs), top = Math.min(...ys), bottom = Math.max(...ys);
      this.centre = { x: (left + right) / 2, y: (top + bottom) / 2 };
      if (right - left < 1e-7 && bottom - top < 1e-7) this.zoom = expand ? Math.min(64, Math.max(8, this.zoom * 2)) : 8;
      else {
        const scale = Math.min(Math.max(50, this.width - 90) / Math.max(1e-6, right - left), Math.max(50, this.height - 90) / Math.max(1e-6, bottom - top));
        this.zoom = clamp(Math.max(expand ? this.zoom * 1.5 : .35, scale / this.baseScale), .35, 64);
      }
      this.render(true); return this;
    }
    reset() { this.onReset(); this.camera.to({ zoom: 1, ...this.initialCentre }); return this; }
    zoomBy(factor, anchor = { x: this.width / 2, y: this.height / 2 }) {
      if (!this.baseScale || !finite(factor) || factor <= 0) return this;
      const target = this.camera.target();
      const previous = this.baseScale * target.zoom, next = clamp(target.zoom * factor, .35, 64), scale = this.baseScale * next;
      target.x += (anchor.x - this.width / 2) * (1 / previous - 1 / scale); target.y += (anchor.y - this.height / 2) * (1 / previous - 1 / scale);
      target.zoom = next; this.camera.to(target, { immediate: this.pointers.size > 1 }); return this;
    }
    point(event) { const box = this.element.getBoundingClientRect(); return { x: (event.clientX - box.left) * this.width / box.width, y: (event.clientY - box.top) * this.height / box.height }; }
    scheduleRender() {
      if (this.frame !== null) return;
      this.frame = requestAnimationFrame(() => { this.frame = null; this.render(true); });
    }
    panBy(dx, dy) { if (this.baseScale) { const target = this.camera.target(), scale = this.baseScale * target.zoom; target.x -= dx / scale; target.y -= dy / scale; this.camera.to(target); } return this; }
    cancelGesture() {
      const captured = [...this.pointers.keys()]; this.pointers.clear();
      this.tap = null; this.start = null; this.last = null; this.pinch = null; this.moved = false;
      this.element.style.cursor = 'grab'; this.suppressDoubleClickUntil = performance.now() + 200;
      captured.forEach(id => { if (this.element.hasPointerCapture(id)) this.element.releasePointerCapture(id); });
      if (this.frame !== null) { cancelAnimationFrame(this.frame); this.frame = null; }
      if (captured.length) { this.onHover(null); this.render(true); }
    }
    bindEvents() {
      this.listen(this.element, 'wheel', event => { if (event.ctrlKey || event.metaKey) return; event.preventDefault(); const delta = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY; this.zoomBy(Math.exp(-clamp(delta, -120, 120) * .002), this.point(event)); }, { passive: false });
      this.listen(this.element, 'keydown', event => {
        if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || event.target.closest?.('input,textarea,select,[contenteditable="true"]')) return;
        const actions = { '+': () => this.zoomBy(1.35), '=': () => this.zoomBy(1.35), '-': () => this.zoomBy(1 / 1.35), Home: () => this.reset(), Escape: () => this.clearSelection(), ArrowLeft: () => this.panBy(40, 0), ArrowRight: () => this.panBy(-40, 0), ArrowUp: () => this.panBy(0, 40), ArrowDown: () => this.panBy(0, -40) };
        if (actions[event.key]) { event.preventDefault(); actions[event.key](); }
      });
      this.listen(this.element, 'dblclick', event => { if (performance.now() < this.suppressDoubleClickUntil || event.ctrlKey || event.metaKey) return; if (!event.target.closest('.generation-marker,.generation-cluster,.generation-region')) { event.preventDefault(); this.zoomBy(1.6, this.point(event)); } });
      this.listen(this.element, 'pointerdown', event => {
        if (event.button !== 0) return;
        const point = this.point(event); this.pointers.set(event.pointerId, point);
        if (this.pointers.size === 1) { this.start = point; this.last = point; this.moved = false; const target = event.target.closest('.generation-marker,.generation-cluster,.generation-region'); this.tap = target ? [...this.nodes.values(),...this.regionNodes.values()].find(entry => entry.group === target) : null; }
        else { this.moved = true; this.tap = null; const [a, b] = [...this.pointers.values()]; this.pinch = Math.hypot(a.x - b.x, a.y - b.y); }
        this.element.setPointerCapture(event.pointerId); this.element.style.cursor = 'grabbing';
      });
      this.listen(this.element, 'pointermove', event => {
        if (!this.pointers.has(event.pointerId)) return;
        if (event.pointerType === 'mouse' && event.buttons === 0) { this.cancelGesture(); return; }
        const point = this.point(event); this.pointers.set(event.pointerId, point);
        if (this.pointers.size > 1) { const [a, b] = [...this.pointers.values()], distance = Math.hypot(a.x - b.x, a.y - b.y); if (this.pinch > 0) this.zoomBy(distance / this.pinch, { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }); this.pinch = distance; return; }
        if (Math.hypot(point.x - this.start.x, point.y - this.start.y) > 4) this.moved = true;
        if (this.moved) { const scale = this.baseScale * this.zoom; this.centre.x -= (point.x - this.last.x) / scale; this.centre.y -= (point.y - this.last.y) / scale; this.scheduleRender(); }
        this.last = point;
      });
      const release = (event, cancelled = false) => {
        if (!this.pointers.has(event.pointerId)) return;
        const single = this.pointers.size === 1, end = this.point(event), tap = this.tap;
        const moved = this.moved || this.start && Math.hypot(end.x - this.start.x, end.y - this.start.y) > 4;
        const inside = end.x >= 0 && end.x <= this.width && end.y >= 0 && end.y <= this.height;
        this.pointers.delete(event.pointerId);
        if (this.element.hasPointerCapture(event.pointerId)) this.element.releasePointerCapture(event.pointerId);
        if (moved || cancelled) this.suppressDoubleClickUntil = performance.now() + 200;
        if (this.pointers.size === 1) { this.start = this.last = [...this.pointers.values()][0]; this.moved = true; this.tap = null; this.pinch = null; }
        if (!this.pointers.size) { this.element.style.cursor = 'grab'; this.start = null; this.last = null; this.tap = null; this.pinch = null; this.moved = false; }
        if (!cancelled && single && !moved && inside) { if (tap) this.choose(tap); else this.clearSelection(); }
      };
      this.listen(this.element, 'pointerup', event => release(event));
      this.listen(this.element, 'pointercancel', () => this.cancelGesture());
      this.listen(this.element, 'lostpointercapture', event => { if (this.pointers.has(event.pointerId)) this.cancelGesture(); });
      this.listen(window, 'pointerup', event => { if (this.pointers.has(event.pointerId)) this.cancelGesture(); });
      this.listen(window, 'blur', () => this.cancelGesture());
      this.listen(document, 'visibilitychange', () => { if (document.hidden) this.cancelGesture(); });
    }
    destroy() { this.destroyed = true; this.camera.destroy(); this.resizeObserver.disconnect(); this.listeners.forEach(remove => remove()); if (this.frame !== null) cancelAnimationFrame(this.frame); this.nodes.clear();this.regionNodes.clear(); this.element.replaceChildren(); }
  }

  return Object.freeze({ GenerationMap, markerRadius, overviewRadius, clusterSites, layoutSites, project, colourFor, TECH_COLOURS, REFERENCE_MW,OVERVIEW_REFERENCE_MW });
});

/* Real site register and an independently sourced GB-wide operational snapshot. */
(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const D = window.JMapGenerationData;
  const O = window.JMapGenerationOverview;
  const catalog = window.JMAP_GENERATION_SITES;
  const params = new URL(location.href).searchParams;
  const state = { query:params.get('q') || '',type:params.get('type') || 'all',country:params.get('country') || 'all',mode:params.get('map')==='sites'||params.has('area')?'sites':'overview',regionId:params.get('area')||null,groups:[],selected:null,clusterIds:null,filtered:[],tab:'sites',snapshot:null,error:null,fetching:false,zoom:1 };
  const labels = {wind_onshore:'Onshore wind',wind_offshore:'Offshore wind',solar:'Solar',hydro:'Hydro',biomass:'Biomass',waste:'Waste',gas:'Gas',nuclear:'Nuclear',storage:'Storage',coal:'Coal',oil:'Oil',other:'Other'};
  const colours = {wind_onshore:'#53bba5',wind_offshore:'#4fa7cf',solar:'#d5b85c',hydro:'#8c99d7',biomass:'#97b76d',waste:'#aaa779',gas:'#df927a',nuclear:'#bc92c7',storage:'#ce9fc3',other:'#9aafb4'};
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const number = (value,digits=0) => finite(value) ? value.toLocaleString('en-GB',{maximumFractionDigits:digits}) : '—';
  const power = value => finite(value) ? `${number(value,1)} MW` : '—';
  const capacity = value => finite(value) ? value >= 1000 ? `${number(value/1000,2)} GW` : power(value) : '—';
  const summaryCapacity = summary => summary.capacityKnownCount ? `${capacity(summary.capacityKnownSumMW)}${summary.capacityUnknownCount?' known':''}` : summary.count?'Unavailable':capacity(0);
  const time = value => new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/London',hour:'2-digit',minute:'2-digit'}).format(new Date(value));
  const date = value => !value || !Number.isFinite(Date.parse(value)) ? String(value || 'Source publication') : new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/London',day:'numeric',month:'short',year:'numeric'}).format(new Date(value));
  const node = (tag,className,text) => { const e=document.createElement(tag); if(className)e.className=className;if(text!==undefined)e.textContent=text;return e; };
  let map,queryTimer=null,refreshTimer,statusTimer,controller;
  const regionAnchors=new Map((O&&catalog?.sites?O.aggregateRegions(catalog.sites):[]).map(group=>[group.id,{lat:group.lat,lon:group.lon}]));

  function facts(target,rows) {
    target.replaceChildren(...rows.map(([label,value]) => {const row=node('div');row.append(node('dt','',label),node('dd','',value));return row;}));
  }
  function setTab(tab) {
    state.tab=tab;
    $('#sites-panel').hidden=tab!=='sites'; $('#snapshot-panel').hidden=tab!=='snapshot';
    $('#sites-tab').setAttribute('aria-pressed',String(tab==='sites')); $('#snapshot-tab').setAttribute('aria-pressed',String(tab==='snapshot'));
  }
  function syncUrl() {
    const url=new URL(location.href);
    [['q',state.query],['type',state.type==='all'?'':state.type],['country',state.country==='all'?'':state.country],['map',state.mode==='sites'?'sites':''],['area',state.regionId||'']].forEach(([key,value])=>value?url.searchParams.set(key,value):url.searchParams.delete(key));
    if(url.href!==location.href)history.replaceState(null,'',url.href);
  }
  function flushSearch() {
    if(queryTimer===null)return;
    clearTimeout(queryTimer);queryTimer=null;filter();
  }
  function filter({fit=false}={}) {
    clearTimeout(queryTimer);queryTimer=null;
    state.clusterIds=null;
    const candidates=D.filterSites(catalog.sites,{query:state.query,type:state.type,country:state.country});
    state.groups=O.aggregateRegions(candidates).map(group=>({...group,...regionAnchors.get(group.id)}));
    const region=state.groups.find(group=>group.id===state.regionId);
    if(state.regionId&&!region)state.regionId=null;
    state.filtered=region?region.sites:candidates;
    if(state.selected&&!state.filtered.some(site=>site.id===state.selected)) clearSite();
    const summary=D.summarizeSites(state.filtered);
    $('#site-count').textContent=number(summary.count);
    $('#capacity-total').textContent=summaryCapacity(summary);
    $('#capacity-total').title=`Sum of ${number(summary.capacityKnownCount)} known capacities; ${number(summary.capacityUnknownCount)} unavailable. Installed equipment, not current output.`;
    $('#empty-map').hidden=state.filtered.length>0;
    map.setOverviewGroups(state.groups);
    map.setMode(state.mode);
    map.setSites(state.filtered);
    if(fit&&state.filtered.length)map.fitSites(state.mode==='overview'?[...candidates,...state.groups]:state.filtered);
    updatePresentation(); renderRegions(); renderList(); renderLegend(); renderBubbleScale(); syncUrl();
    $('#export-sites').disabled=state.filtered.length===0;
  }
  function renderList() {
    const members=state.clusterIds?state.filtered.filter(site=>state.clusterIds.has(site.id)):state.filtered;
    const ranked=[...members].sort((a,b)=>(b.capacityMW??-1)-(a.capacityMW??-1)||a.name.localeCompare(b.name));
    $('#site-list-title').textContent=state.clusterIds?`Selected group · ${number(members.length)}`:'Filtered sites';
    $('#clear-cluster').hidden=!state.clusterIds;
    $('#site-list').replaceChildren(...ranked.slice(0,120).map(site=>{
      const button=node('button','site-row');button.type='button';button.dataset.siteId=site.id;button.setAttribute('aria-pressed',String(state.selected===site.id));
      const name=node('span');name.append(node('strong','',site.name),node('small','',`${labels[site.type]||site.type} · ${site.country||'Location not classified'}`));
      button.append(name,node('span','',number(site.capacityMW,1)));button.title=`${site.name}, ${power(site.capacityMW)} installed`;
      button.addEventListener('click',()=>selectSite(site.id,true));return button;
    }));
    $('#list-note').textContent=ranked.length>120?`120 of ${number(ranked.length)} sites · export includes all.`:ranked.length?'':'No matching sites.';
    $('#list-note').hidden=!$('#list-note').textContent;
  }
  function updatePresentation() {
    const overview=state.mode==='overview',region=state.groups.find(group=>group.id===state.regionId);
    $('#overview-view').setAttribute('aria-pressed',String(overview));$('#sites-view').setAttribute('aria-pressed',String(!overview));
    $('#overview-panel').hidden=!overview;$('#site-results').hidden=overview;$('#sites-tab').textContent=overview?'Regions':'Sites';
    $('#map-title').textContent=overview?'Capacity by region':'Installed capacity by site';
    $('#fit-results').textContent=overview?'Explore sites ↗':'Fit results ⤢';
    $('#bubble-scale-label').textContent=overview?'Installed capacity · GW':'Installed capacity · MW';
    $('#bubble-scale-note').textContent=overview?'Select a region to see its sites.':'Groups show combined capacity.';
    $('#overview-scope-chip').hidden=!region;$('#overview-scope-chip').textContent=region?`${region.name} · Overview ×`:'';
    $('#selected-region-detail').hidden=!region;
    if(region){
      $('#selected-region-name').textContent=region.name;
      $('#selected-region-summary').textContent=`${capacity(region.capacityMW)} installed · ${number(region.siteCount)} registered sites${region.isOffshore?' · UK offshore summary':''}`;
      const breakdown=node('details'),summary=node('summary','','Technology breakdown');breakdown.append(summary);
      D.aggregateByType(region.sites).forEach(row=>{const line=node('div','region-type-row'),dot=node('i');dot.style.background=colours[row.type]||colours.other;line.append(dot,node('span','',row.label||labels[row.type]||row.type),node('strong','',summaryCapacity(row)));breakdown.append(line);});
      $('#selected-region-mix').replaceChildren(breakdown);
    }
  }
  function renderRegions() {
    const sorted=[...state.groups].sort((a,b)=>(b.capacityMW??-1)-(a.capacityMW??-1)),max=Math.max(1,...sorted.map(group=>group.capacityMW||0));
    $('#overview-list').replaceChildren(...sorted.map(group=>{
      const button=node('button','overview-row');button.type='button';button.dataset.regionId=group.id;button.dataset.capacityMw=group.capacityMW??'';
      button.append(node('span','',group.name),node('strong','',capacity(group.capacityMW)));
      button.title=`${group.name}: ${capacity(group.capacityMW)} installed, ${number(group.siteCount)} sites. Select to explore.${group.isOffshore?' A UK-wide offshore summary, not one location.':''}`;
      if(finite(group.capacityMW)){const bar=node('i');bar.style.width=`${Math.min(100,group.capacityMW/max*100)}%`;button.append(bar);}
      button.addEventListener('mouseenter',()=>map.previewRegion(group.id));button.addEventListener('mouseleave',()=>map.previewRegion(null));
      button.addEventListener('focus',()=>map.previewRegion(group.id));button.addEventListener('blur',()=>map.previewRegion(null));
      button.addEventListener('click',()=>selectRegion(group));return button;
    }));
  }
  function selectRegion(group) {
    flushSearch();if(!state.groups.some(row=>row.id===group.id))return;
    state.mode='sites';state.regionId=group.id;clearSite();filter({fit:true});setTab('sites');$('#sites-panel').scrollTop=0;
    $('#generation-map').focus({preventScroll:true});
    $('#announcement').textContent=`${group.name}. Showing its registered sites and installed capacities.`;
  }
  function showOverview({reset=true}={}) {
    flushSearch();state.mode='overview';state.regionId=null;state.clusterIds=null;clearSite();filter();setTab('sites');
    if(reset)map.reset();
  }
  function handleMapReset() {
    if(state.mode==='overview'&&!state.regionId)return;
    showOverview({reset:false});
  }
  function showSites({fit=false}={}) {flushSearch();state.mode='sites';filter({fit});setTab('sites');}
  function renderLegend() {
    $('#technology-key').hidden=state.mode==='overview';
    if(state.mode==='overview')return;
    const present=new Set(state.filtered.map(site=>site.type));
    $('#technology-key').replaceChildren(...Object.entries(labels).filter(([type])=>present.has(type)).map(([type,label])=>{
      const item=node('span');const dot=node('i');dot.style.background=colours[type]||colours.other;item.append(dot,document.createTextNode(label));return item;
    }));
    const mixed=node('span'),dot=node('i');dot.style.background='#aaa';mixed.append(dot,document.createTextNode('Mixed technologies'));$('#technology-key').append(mixed);
  }
  function renderBubbleScale() {
    if(!map)return;
    const overview=state.mode==='overview';
    const radius=overview?window.GenerationMap.overviewRadius:window.GenerationMap.markerRadius || window.GenerationMap.radiusForCapacity;
    if(typeof radius!=='function')return;
    $('#bubble-scale').replaceChildren(...(overview?[1000,5000,20000]:[100,1000,10000]).map(value=>{
      const item=node('span','bubble-item');const dot=node('i');const r=radius(value,state.zoom);
      dot.style.width=`${Math.max(2,r*2)}px`;dot.style.height=`${Math.max(2,r*2)}px`;item.append(dot,document.createTextNode(number(overview?value/1000:value)));return item;
    }));
  }
  function onViewChange(view) {
    state.zoom=view.zoom || 1;
    const visible=view.visibleCount ?? view.visibleSiteCount;
    const clusters=view.clusterCount;
    $('#map-view-status').textContent=state.mode==='overview'?`${number(state.groups.length)} regions`:`${finite(visible)?`${number(visible)} sites in view`:`${number(state.filtered.length)} filtered sites`}${finite(clusters)&&clusters?` · ${number(clusters)} groups`:''}`;
    renderBubbleScale();
  }
  function selectSite(id,focus=false) {
    flushSearch();
    const site=state.filtered.find(item=>item.id===id);if(!site){map?.selectSite(state.selected);return;}
    state.mode='sites';map.setMode('sites');updatePresentation();renderLegend();state.selected=id;setTab('sites');map.selectSite(id);if(focus)map.focusSite(id);
    $('#site-detail').hidden=false;$('#detail-name').textContent=site.name;$('#detail-technology').textContent=labels[site.type]||site.type;
    $('#detail-place').textContent=site.country||'United Kingdom';$('#detail-capacity').textContent=power(site.capacityMW);
    facts($('#detail-facts'),[['Operator',site.operator||'Not reported'],['Status','Reported operating'],['Register date',date(site.sourceDate||catalog.asOf)],['Location',`${number(site.lat,4)}°, ${number(site.lon,4)}°`],['Current site output','Unavailable']]);
    $('#detail-source').href=site.sourceUrl || 'https://www.gov.uk/government/publications/renewable-energy-planning-database-quarterly-extract';
    $('#sites-panel').scrollTop=0;
    document.querySelectorAll('.site-row').forEach(row=>row.setAttribute('aria-pressed',String(row.dataset.siteId===id)));
    $('#announcement').textContent=`${site.name}, ${power(site.capacityMW)} installed capacity.`;
  }
  function clearSite({restoreFocus=false}={}) {
    const selected=state.selected,detailHadFocus=$('#site-detail').contains(document.activeElement);
    state.selected=null;map?.selectSite(null);$('#site-detail').hidden=true;
    document.querySelectorAll('.site-row').forEach(row=>row.setAttribute('aria-pressed','false'));
    if(restoreFocus||detailHadFocus){
      const row=[...document.querySelectorAll('.site-row')].find(item=>item.dataset.siteId===selected);
      (row||$('#generation-map')).focus({preventScroll:true});
    }
  }
  function selectCluster(cluster) {
    flushSearch();
    const matching=new Set(state.filtered.map(site=>site.id)),members=cluster.sites.filter(site=>matching.has(site.id));
    if(!members.length)return false;
    state.clusterIds=new Set(members.map(site=>site.id));clearSite();setTab('sites');renderList();$('#sites-panel').scrollTop=0;
    $('#announcement').textContent=`Group of ${members.length} sites. Group members are listed in the panel.`;
    return {sites:members};
  }
  function sources() {
    const entries=Array.isArray(catalog.sources)?catalog.sources:Object.values(catalog.sources||{});
    const paragraphs=entries.map(source=>{
      const p=node('p'); const url=source.url||source.sourceUrl||source.pageUrl;
      if(url){const a=node('a','',source.name||source.title||'Official register');a.href=url;a.target='_blank';a.rel='noreferrer';p.append(a);}else p.append(document.createTextNode(source.name||source.title||'Official register'));
      const stamp=source.asOf||source.date||source.sourceDate||source.published;
      if(source.period)p.append(document.createTextNode(` · ${source.period}`));
      if(stamp)p.append(document.createTextNode(` · published ${date(stamp)}`));
      if(source.description)p.append(document.createTextNode(`. ${source.description}`));return p;
    });
    if(catalog.coverage?.note)paragraphs.push(node('p','',catalog.coverage.note));
    for(const note of catalog.coverage?.notes||[])paragraphs.push(node('p','',note));
    $('#catalogue-sources').replaceChildren(...paragraphs);
    $('#catalogue-period').textContent=catalog.asOfLabel||`Published registers · ${date(catalog.asOf)}`;
  }
  function livePeriod(snapshot) {
    return `${date(snapshot.startTime)} · ${time(snapshot.startTime)}–${time(snapshot.endTime)} UK · five-minute average`;
  }
  function updateLiveStatus() {
    const badge=$('#open-snapshot');const freshness=D.freshness(state.snapshot);
    badge.className=`feed-status ${state.error?'unavailable':freshness.state}`;
    if(!state.snapshot){badge.textContent=state.error?'GB snapshot unavailable':state.fetching?'GB snapshot: connecting':'GB snapshot unavailable';return;}
    const partial=state.snapshot.complete?'':' · partial';
    const reading=finite(state.snapshot.generationMW)?`metered ${capacity(state.snapshot.generationMW)}`:'snapshot';
    badge.textContent=`GB ${state.error?'update failed':freshness.state==='stale'?'last reading':reading} · ${time(state.snapshot.endTime)} UK${partial}`;
    $('#live-period').textContent=livePeriod(state.snapshot);
    $('#live-status').textContent=state.error?`${state.error} Showing the previous observation at ${time(state.snapshot.endTime)} UK.`:freshness.state==='stale'?'This observation is more than 15 minutes old. Refreshing from Elexon every 60 seconds.':state.snapshot.complete?'One coherent observation from Elexon. Checked every 60 seconds.':'Some observations are missing. Incomplete totals remain unavailable; reported fuel readings are shown below.';
  }
  function renderLive() {
    const snapshot=state.snapshot;
    facts($('#live-totals'),snapshot?[['Metered output + storage',power(snapshot.generationMW)],['Imports to GB',power(snapshot.importsMW)],['Exports from GB',power(snapshot.exportsMW)],['Net imports',finite(snapshot.netImportsMW)?`${snapshot.netImportsMW<0?'−':''}${power(Math.abs(snapshot.netImportsMW))}`:'—']]:[['Metered output + storage','—'],['Imports to GB','—'],['Exports from GB','—']]);
    const max=snapshot?Math.max(1,...snapshot.mix.map(row=>finite(row.mw)?Math.abs(row.mw):0)):1;
    $('#generation-mix').replaceChildren(...(snapshot?.mix||[]).map(row=>{
      const item=node('div','fuel-row');item.dataset.code=row.code;item.append(node('span','',row.label),node('strong','',number(row.mw)));
      if(finite(row.mw)){const bar=node('i','fuel-bar');bar.style.width=`${Math.min(100,Math.abs(row.mw)/max*100)}%`;item.append(bar);}return item;
    }));
    updateLiveStatus();
  }
  async function refreshLive() {
    if(state.fetching)return;state.fetching=true;controller=new AbortController();$('#refresh-live').disabled=true;updateLiveStatus();
    const timeout=setTimeout(()=>controller?.abort(),15000);
    try{
      const snapshot=await D.fetchNationalSnapshot({signal:controller.signal});
      if(!state.snapshot||Date.parse(snapshot.startTime)>=Date.parse(state.snapshot.startTime))state.snapshot=snapshot;
      state.error=null;renderLive();
    }catch(error){
      state.error=error.name==='AbortError'?'The live request timed out.':error.message||'The live feed could not be reached.';
      $('#live-status').textContent=state.snapshot?`${state.error} Previous reading retained.`:`${state.error} The site register remains available. No live readings have been substituted.`;
    }finally{clearTimeout(timeout);state.fetching=false;controller=null;$('#refresh-live').disabled=false;updateLiveStatus();}
  }
  function download() {
    const rows=[['UK generation site register — installed capacity, not current output'],['Register date',catalog.asOf],['Search',state.query],['Technology',state.type],['Country',state.country],['Source region',state.groups.find(group=>group.id===state.regionId)?.name||'All matching regions'],[],['ID','Site','Technology','Country','Installed capacity MW','Latitude','Longitude','Operator','Source date','Source URL'],...state.filtered.map(site=>[site.id,site.name,site.type,site.country,site.capacityMW,site.lat,site.lon,site.operator,site.sourceDate,site.sourceUrl])];
    const csv=rows.map(row=>row.map(value=>`"${String(value??'').replaceAll('"','""')}"`).join(',')).join('\r\n');
    const url=URL.createObjectURL(new Blob(['\uFEFF'+csv],{type:'text/csv;charset=utf-8;'}));const link=node('a');link.href=url;link.download='jmap-generating-sites.csv';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function startTimers() {clearInterval(refreshTimer);clearInterval(statusTimer);refreshTimer=setInterval(()=>{if(!document.hidden)refreshLive();},60000);statusTimer=setInterval(updateLiveStatus,15000);}
  function init() {
    try{
      if(!catalog?.sites?.length)throw new Error('The official site register is unavailable.');
      if(!D||!O||!window.GenerationMap)throw new Error('The map could not be loaded.');
      const types=[...new Set(catalog.sites.map(site=>site.type))].sort((a,b)=>(labels[a]||a).localeCompare(labels[b]||b));
      types.forEach(type=>{const option=node('option','',labels[type]||type);option.value=type;$('#technology').append(option);});
      const countries=[...new Set(catalog.sites.map(site=>site.country).filter(Boolean))].sort();
      countries.forEach(country=>{const option=node('option','',country);option.value=country;$('#country').append(option);});
      if(!types.includes(state.type))state.type='all';if(!countries.includes(state.country))state.country='all';
      $('#site-search').value=state.query;$('#technology').value=state.type;$('#country').value=state.country;
      map=new window.GenerationMap({element:$('#generation-map'),geography:window.JMAP_GEOGRAPHY,onSelect:id=>selectSite(id),onClusterSelect:selectCluster,onRegionSelect:selectRegion,onReset:handleMapReset,onClearSelect:()=>clearSite(),onViewChange});
      filter({fit:Boolean(state.query||state.type!=='all'||state.country!=='all'||state.regionId)});sources();renderLive();refreshLive();startTimers();
    }catch(error){$('#catalogue-error').hidden=false;$('#catalogue-error').textContent=error.message;$('#catalogue-period').textContent='Register unavailable';}
  }
  $('#site-search').addEventListener('input',event=>{state.query=event.target.value.trim();state.regionId=null;clearTimeout(queryTimer);$('#export-sites').disabled=true;queryTimer=setTimeout(()=>{queryTimer=null;filter();},120);});
  $('#site-search').addEventListener('keydown',event=>{if(event.key!=='Enter'||event.isComposing||event.ctrlKey||event.metaKey||event.altKey)return;event.preventDefault();state.query=event.currentTarget.value.trim();state.regionId=null;showSites({fit:true});$('#announcement').textContent=`${state.filtered.length} matching ${state.filtered.length===1?'site':'sites'} framed on the map.`;});
  $('#technology').addEventListener('change',event=>{state.type=event.target.value;state.regionId=null;filter({fit:true});});
  $('#country').addEventListener('change',event=>{state.country=event.target.value;state.regionId=null;filter({fit:true});});
  $('#reset-filters').addEventListener('click',()=>{state.query='';state.type='all';state.country='all';state.mode='overview';state.regionId=null;$('#site-search').value='';$('#technology').value='all';$('#country').value='all';clearSite();filter();setTab('sites');map.reset();});
  $('#fit-results').addEventListener('click',()=>{showSites({fit:true});});
  $('#overview-view').addEventListener('click',()=>showOverview());$('#sites-view').addEventListener('click',()=>showSites());
  $('#overview-scope-chip').addEventListener('click',()=>showOverview());
  $('#zoom-in').addEventListener('click',()=>map?.zoomBy(1.35));$('#zoom-out').addEventListener('click',()=>map?.zoomBy(1/1.35));$('#reset-map').addEventListener('click',()=>map?.reset());
  $('#sites-tab').addEventListener('click',()=>setTab('sites'));$('#snapshot-tab').addEventListener('click',()=>setTab('snapshot'));$('#open-snapshot').addEventListener('click',()=>setTab('snapshot'));
  $('#clear-site').addEventListener('click',()=>clearSite({restoreFocus:true}));$('#export-sites').addEventListener('click',download);$('#refresh-live').addEventListener('click',refreshLive);
  $('#clear-cluster').addEventListener('click',()=>{state.clusterIds=null;renderList();});
  $('#open-sources').addEventListener('click',()=>$('#sources-dialog').showModal());$('#close-sources').addEventListener('click',()=>$('#sources-dialog').close());
  window.addEventListener('pagehide',()=>{clearInterval(refreshTimer);clearInterval(statusTimer);controller?.abort();});
  window.addEventListener('pageshow',event=>{if(event.persisted){startTimers();refreshLive();}});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){updateLiveStatus();refreshLive();}});
  document.addEventListener('keydown',event=>{
    if(event.defaultPrevented||event.ctrlKey||event.metaKey||event.altKey)return;
    const editing=document.activeElement.closest?.('input,textarea,select,[contenteditable="true"]');
    if(event.key==='/'&&!editing&&!$('#sources-dialog').open){event.preventDefault();$('#site-search').focus();}
    if(event.key==='Escape'&&!editing&&!$('#sources-dialog').open)clearSite();
  });
  init();
})();

//easter egg test

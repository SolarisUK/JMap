/* Pure summaries of the selected site portfolio. Values describe supplied power,
 * not transmission flows, regional demand, or transfers between UK nations.
 * All power/capacity values are MW; shares and utilisation are percentages.
 */
(function (root, factory) {
  'use strict';
  const api = Object.freeze(factory());
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.JMapAnalysis = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const DEFAULT_REGIONS = ['england', 'scotland', 'wales', 'northern-ireland'];
  const LOW_CARBON_TYPES = new Set(['wind', 'solar', 'nuclear', 'hydro']);

  function validate(sites) {
    if (!Array.isArray(sites)) throw new TypeError('Sites must be an array.');
    sites.forEach((site, index) => {
      if (!site || typeof site !== 'object') throw new TypeError(`Site ${index} must be a record.`);
      if (typeof site.type !== 'string' || !site.type.trim()) throw new TypeError(`Site ${index} must have a technology type.`);
      ['capacity', 'output'].forEach(key => {
        if (typeof site[key] !== 'number' || !Number.isFinite(site[key])) {
          throw new TypeError(`Site ${site.id || index} ${key} must be a finite number in MW.`);
        }
        if (site[key] < 0) throw new RangeError(`Site ${site.id || index} ${key} cannot be negative.`);
      });
    });
    return sites;
  }

  function add(total, value) {
    const result = total + value;
    if (!Number.isFinite(result)) throw new RangeError('The aggregated MW value exceeds the supported numeric range.');
    return result;
  }

  function percentage(value, total, empty = null) {
    // Divide before multiplying so finite MW inputs cannot overflow at *100.
    return total > 0 ? value / total * 100 : empty;
  }

  function summariseUnchecked(sites) {
    const result = {
      siteCount: sites.length,
      capacity: 0,
      output: 0,
      generation: 0,
      storage: 0,
      imports: 0,
      lowCarbon: 0,
      lowCarbonShare: null,
      utilisation: null
    };
    sites.forEach(site => {
      result.capacity = add(result.capacity, site.capacity);
      result.output = add(result.output, site.output);
      if (site.type === 'storage') result.storage = add(result.storage, site.output);
      else if (site.type === 'interconnector') result.imports = add(result.imports, site.output);
      else result.generation = add(result.generation, site.output);
      if (LOW_CARBON_TYPES.has(site.type)) result.lowCarbon = add(result.lowCarbon, site.output);
    });
    result.lowCarbonShare = percentage(result.lowCarbon, result.generation);
    result.utilisation = percentage(result.output, result.capacity);
    return result;
  }

  function summarise(sites = []) {
    return summariseUnchecked(validate(sites));
  }

  function byOutput(a, b) {
    return b.output - a.output || a.key.localeCompare(b.key, 'en-GB');
  }

  function aggregateByTechnology(sites = []) {
    validate(sites);
    const groups = new Map();
    sites.forEach(site => {
      if (!groups.has(site.type)) groups.set(site.type, []);
      groups.get(site.type).push(site);
    });
    const total = sites.reduce((value, site) => add(value, site.output), 0);
    return [...groups].map(([key, members]) => {
      const summary = summariseUnchecked(members);
      return {
        key,
        siteCount: summary.siteCount,
        capacity: summary.capacity,
        output: summary.output,
        share: percentage(summary.output, total, 0),
        utilisation: summary.utilisation
      };
    }).sort(byOutput);
  }

  function aggregateByRegion(sites = [], regions = DEFAULT_REGIONS) {
    validate(sites);
    if (!regions || typeof regions !== 'object') throw new TypeError('Regions must be an array of keys or a keyed region object.');
    const keys = Array.isArray(regions) ? regions : Object.keys(regions);
    if (keys.some(key => typeof key !== 'string' || !key.trim())) throw new TypeError('Region keys must be nonempty strings.');
    const groups = new Map(keys.map(key => [key, []]));
    sites.forEach(site => {
      // Retain unrecognised/unassigned regions rather than silently dropping MW.
      const key = typeof site.region === 'string' && site.region.trim() ? site.region : 'unknown';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(site);
    });
    const total = sites.reduce((value, site) => add(value, site.output), 0);
    return [...groups].map(([key, members]) => {
      const summary = summariseUnchecked(members);
      return { key, ...summary, share: percentage(summary.output, total, 0) };
    }).sort(byOutput);
  }

  return { summarise, aggregateByTechnology, aggregateByRegion };
});

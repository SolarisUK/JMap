/* Local electricity statistics: metered use and renewable capacity are separate measures. */
(function (root, factory) {
  'use strict';
  const api = Object.freeze(factory());
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.JMapLocalAnalysis = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  const known = value => typeof value === 'number' && Number.isFinite(value);
  const metrics = Object.freeze({
    demand: { label: 'Electricity use', field: 'consumptionGWh', unit: 'GWh', description: 'Annual metered domestic + non-domestic use.' },
    domestic: { label: 'Domestic use', field: 'domesticGWh', unit: 'GWh', description: 'Annual use at domestic meters.' },
    business: { label: 'Non-domestic use', field: 'nonDomesticGWh', unit: 'GWh', description: 'Commercial, industrial and public-sector use.' },
    perMeter: { label: 'Use per domestic meter', field: 'meanDomesticKWh', divisor: 1000, unit: 'MWh / meter', description: 'Mean annual use per domestic meter; comparable across area sizes.' },
    capacity: { label: 'Renewable capacity', field: 'renewableCapacityMW', unit: 'MW', description: 'Installed renewable capacity, not total generation or firm available power.' },
    renewable: { label: 'Renewable output', field: 'renewableGWh', unit: 'GWh', description: 'Complete published renewable generation only. Confidential or unmatched values are grey.' }
  });
  function value(row, metric) {
    const definition = metrics[metric];
    if (!definition) throw new RangeError('Unknown local metric.');
    const raw = row[definition.field];
    return known(raw) ? raw / (definition.divisor || 1) : null;
  }
  function quantile(sorted, fraction) {
    if (!sorted.length) return null;
    const position = (sorted.length - 1) * fraction;
    const lower = Math.floor(position);
    return sorted[lower] + (sorted[Math.ceil(position)] - sorted[lower]) * (position - lower);
  }
  function scale(rows, metric) {
    const numbers = rows.map(row => value(row, metric)).filter(known).sort((a, b) => a - b);
    // A fixed full-dataset 95th percentile keeps ordinary differences readable.
    // The legend explicitly marks its upper end as capped; numeric values stay exact.
    return { min: 0, max: Math.max(1, quantile(numbers, .95) || 1), observedMax: numbers.at(-1) ?? null, knownCount: numbers.length };
  }
  function summary(rows) {
    const sum = field => rows.reduce((total, row) => total + (known(row[field]) ? row[field] : 0), 0);
    const measured = rows.filter(row => known(row.consumptionGWh));
    const consumptionGWh = measured.length ? sum('consumptionGWh') : null;
    const domesticGWh = measured.length ? sum('domesticGWh') : null;
    const domesticMeters = measured.length ? sum('domesticMeters') : null;
    return {
      areaCount: rows.length, measuredCount: measured.length,
      consumptionGWh, domesticGWh,
      nonDomesticGWh: measured.length ? sum('nonDomesticGWh') : null,
      domesticShare: consumptionGWh > 0 ? domesticGWh / consumptionGWh * 100 : null,
      meanDomesticMWh: domesticMeters > 0 ? domesticGWh * 1000 / domesticMeters : null,
      renewableCapacityMW: rows.some(row => known(row.renewableCapacityMW)) ? sum('renewableCapacityMW') : null,
      capacityKnownCount: rows.filter(row => known(row.renewableCapacityMW)).length
    };
  }
  return { metrics, value, scale, summary };
});

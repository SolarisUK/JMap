/* Annual electricity generation compared with annual electricity use, in TWh.
 * This arithmetic describes a historical energy balance, not real-time power
 * adequacy, household access, transmission headroom, or a blackout forecast.
 * Scenario percentages scale annual totals only; they are illustrative.
 */
(function (root, factory) {
  'use strict';
  const api = Object.freeze(factory());
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.JMapBalance = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  function knownEnergy(value, field) {
    if (value === null || value === undefined) return null;
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      throw new TypeError(`${field} must be a finite number in TWh, or null when unavailable.`);
    }
    if (value < 0) throw new RangeError(`${field} cannot be negative.`);
    return value;
  }

  function checkedNumber(value) {
    if (!Number.isFinite(value)) throw new RangeError('The annual balance exceeds the supported numeric range.');
    return value;
  }

  function scenarioOptions(options = {}) {
    if (!options || typeof options !== 'object' || Array.isArray(options)) {
      throw new TypeError('Scenario options must be a record.');
    }
    const result = {};
    for (const field of ['demandChangePercent', 'generationChangePercent']) {
      const value = options[field] === undefined ? 0 : options[field];
      if (typeof value !== 'number' || !Number.isFinite(value)) {
        throw new TypeError(`${field} must be a finite percentage.`);
      }
      if (value < -100 || value > 100) throw new RangeError(`${field} must be between -100 and 100.`);
      result[field] = value;
    }
    return result;
  }

  function analyseUnchecked(row, scenario) {
    if (!row || typeof row !== 'object' || Array.isArray(row)) throw new TypeError('Each region must be a record.');
    if (typeof row.key !== 'string' || !row.key.trim()) throw new TypeError('Each region must have a nonempty key.');
    const baselineGenerationTWh = knownEnergy(row.generationTWh, 'generationTWh');
    const baselineConsumptionTWh = knownEnergy(row.consumptionTWh, 'consumptionTWh');
    const scale = (value, change) => value === null ? null : checkedNumber(value * (1 + change / 100));
    const generationTWh = scale(baselineGenerationTWh, scenario.generationChangePercent);
    const consumptionTWh = scale(baselineConsumptionTWh, scenario.demandChangePercent);
    const known = generationTWh !== null && consumptionTWh !== null;
    const balanceTWh = known ? generationTWh - consumptionTWh : null;
    const coveragePercent = known && consumptionTWh > 0
      ? checkedNumber(generationTWh / consumptionTWh * 100) : null;
    const shortfallPercent = known && consumptionTWh > 0
      ? checkedNumber(Math.max(0, -balanceTWh) / consumptionTWh * 100) : null;
    const status = !known ? 'unknown' : balanceTWh > 0 ? 'annual-surplus' : balanceTWh < 0 ? 'annual-deficit' : 'balanced';
    return {
      ...row,
      baselineGenerationTWh,
      baselineConsumptionTWh,
      generationTWh,
      consumptionTWh,
      balanceTWh,
      coveragePercent,
      shortfallPercent,
      status
    };
  }

  function analyseRegion(row, options) {
    return analyseUnchecked(row, scenarioOptions(options));
  }

  // Rank by local generation relative to use. An unavailable ratio ranks last,
  // even when a zero-demand region has a known positive annual balance.
  function analyseRegions(rows = [], options) {
    if (!Array.isArray(rows)) throw new TypeError('Regions must be an array.');
    const scenario = scenarioOptions(options);
    const analysed = rows.map(row => analyseUnchecked(row, scenario));
    if (new Set(analysed.map(row => row.key)).size !== analysed.length) {
      throw new RangeError('Region keys must be unique.');
    }
    return analysed.sort((a, b) => {
      if (a.coveragePercent === null && b.coveragePercent !== null) return 1;
      if (b.coveragePercent === null && a.coveragePercent !== null) return -1;
      if (a.coveragePercent !== b.coveragePercent) return b.coveragePercent - a.coveragePercent;
      if (a.balanceTWh === null && b.balanceTWh !== null) return 1;
      if (b.balanceTWh === null && a.balanceTWh !== null) return -1;
      if (a.balanceTWh !== b.balanceTWh) return b.balanceTWh - a.balanceTWh;
      return a.key.localeCompare(b.key, 'en-GB');
    });
  }

  return { analyseRegion, analyseRegions };
});

/* Simulator view models. Units and endpoint shapes follow LEONARD_SPEC.md.
 * Cumulative KPIs come only from snapshot.totals, never from instantaneous zones.
 * Unknown values stay null. Signed flows and overload ratios are never clipped.
 */
(function (root, factory) {
  'use strict';
  const api = Object.freeze(factory());
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.JMapOperations = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const TOTAL_FIELDS = ['unserved_mwh', 'cost_gbp', 'carbon_t', 'curtailed_mwh'];
  const HALF_HOUR_MS = 30 * 60 * 1000;
  const DISPLAY_TZ = 'Europe/London';

  function record(value, label) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new TypeError(`${label} must be an object.`);
    return value;
  }
  function knownNumber(value, label) {
    if (value === null || value === undefined) return null;
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new TypeError(`${label} must be a finite number or null.`);
    return value;
  }
  function utcMilliseconds(value, label = 'Timestamp') {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/.test(value)) {
      throw new TypeError(`${label} must be an ISO 8601 UTC timestamp.`);
    }
    const milliseconds = Date.parse(value);
    if (!Number.isFinite(milliseconds) || new Date(milliseconds).toISOString().slice(0, 19) !== value.slice(0, 19)) {
      throw new RangeError(`${label} is not a valid UTC date and time.`);
    }
    return milliseconds;
  }

  function formatTime(timestamp, { includeDate = false, includeZone = true } = {}) {
    const milliseconds = utcMilliseconds(timestamp);
    return new Intl.DateTimeFormat('en-GB', {
      timeZone: DISPLAY_TZ,
      ...(includeDate ? { day: '2-digit', month: 'short' } : {}),
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
      ...(includeZone ? { timeZoneName: 'short' } : {})
    }).format(new Date(milliseconds));
  }

  function totalKpis(snapshot) {
    const totals = snapshot?.totals;
    if (totals !== null && totals !== undefined) record(totals, 'Episode totals');
    return Object.fromEntries(TOTAL_FIELDS.map(key => [key, knownNumber(totals?.[key], `totals.${key}`)]));
  }

  function validateSnapshot(snapshot) {
    record(snapshot, 'Snapshot');
    utcMilliseconds(snapshot.timestamp_utc, 'snapshot.timestamp_utc');
    record(snapshot.zones, 'Snapshot zones');
    record(snapshot.edges, 'Snapshot edges');
    Object.entries(snapshot.zones).forEach(([key, zone]) => {
      record(zone, `zones.${key}`);
      ['demand_mw', 'generation_mw', 'unserved_mw', 'cost_gbp', 'carbon_t', 'curtailed_mw', 'storage_soc', 'dr_called_mw'].forEach(field => knownNumber(zone[field], `zones.${key}.${field}`));
    });
    Object.entries(snapshot.edges).forEach(([key, edge]) => {
      record(edge, `edges.${key}`);
      ['flow_mw', 'limit_mw', 'loading_frac'].forEach(field => knownNumber(edge[field], `edges.${key}.${field}`));
      if (edge.tripped !== undefined && edge.tripped !== null && typeof edge.tripped !== 'boolean') throw new TypeError(`edges.${key}.tripped must be boolean.`);
    });
    if (snapshot.incidents !== undefined && !Array.isArray(snapshot.incidents)) throw new TypeError('Snapshot incidents must be an array.');
    totalKpis(snapshot);
    return snapshot;
  }

  function validateForecast(payload) {
    record(payload, 'Forecast');
    if (typeof payload.zone_id !== 'string' || !payload.zone_id.trim()) throw new TypeError('Forecast zone_id is required.');
    const issued = utcMilliseconds(payload.issue_time_utc, 'Forecast issue_time_utc');
    if (payload.unit !== 'MW') throw new TypeError('Forecast unit must be MW.');
    if (!Array.isArray(payload.quantiles) || payload.quantiles.join(',') !== 'p10,p50,p90') throw new TypeError('Forecast quantiles must be ordered p10, p50, p90.');
    if (!Array.isArray(payload.timestamps_utc) || payload.timestamps_utc.length !== 48 || !Array.isArray(payload.forecast) || payload.forecast.length !== 48) {
      throw new RangeError('Forecast must contain 48 timestamps and 48 quantile rows.');
    }
    payload.forecast.forEach((row, index) => {
      if (utcMilliseconds(payload.timestamps_utc[index], `Forecast timestamp ${index}`) !== issued + index * HALF_HOUR_MS) {
        throw new RangeError(`Forecast timestamp ${index} must equal issue time plus ${index} half-hours.`);
      }
      if (!Array.isArray(row) || row.length !== 3) throw new RangeError(`Forecast row ${index} must contain p10, p50 and p90.`);
      row.forEach((value, quantile) => {
        if (knownNumber(value, `Forecast row ${index}, ${payload.quantiles[quantile]}`) === null) throw new TypeError(`Forecast row ${index} has an unavailable quantile.`);
        if (value < 0) throw new RangeError(`Forecast row ${index} cannot contain negative demand.`);
      });
      if (row[0] > row[1] || row[1] > row[2]) throw new RangeError(`Forecast row ${index} quantiles are out of order.`);
    });
    if (!Array.isArray(payload.explanation) || payload.explanation.length !== 3 || payload.explanation.some(text => typeof text !== 'string' || !text.trim())) {
      throw new TypeError('Forecast explanation must contain three English text strings.');
    }
    return payload;
  }

  // Reporting thresholds do not change simulator totals. By default, sub-1-MWh
  // baselines have no percentage headline and energy differences up to 0.1 MWh
  // are treated as a numerical tie before comparing the reported episode cost.
  function compareResults(payload, reference, options = {}) {
    record(payload, 'Comparison');
    record(payload.strategies, 'Comparison strategies');
    record(options, 'Comparison reporting thresholds');
    const minBaselineMWh = options.minBaselineMWh ?? 1;
    const energyToleranceMWh = options.energyToleranceMWh ?? .1;
    [minBaselineMWh, energyToleranceMWh].forEach(value => {
      if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) throw new RangeError('Comparison thresholds must be finite nonnegative MWh values.');
    });
    if (payload.agents_is_placeholder !== undefined && typeof payload.agents_is_placeholder !== 'boolean') throw new TypeError('agents_is_placeholder must be boolean.');
    const keys = reference?.strategies || Object.keys(payload.strategies);
    if (!Array.isArray(keys) || keys.some(key => typeof key !== 'string') || new Set(keys).size !== keys.length) throw new TypeError('Reference strategies must be unique string keys.');
    const labels = { none: 'No response', optimiser: 'Optimiser', agents: 'Agents' };
    const baseline = totalKpis({ totals: payload.strategies.none });
    const materialUnserved = baseline.unserved_mwh === null ? null : baseline.unserved_mwh > 0 && baseline.unserved_mwh >= minBaselineMWh;
    const rows = keys.map(key => {
      const isPlaceholder = key === 'agents' && payload.agents_is_placeholder === true;
      const totals = totalKpis({ totals: isPlaceholder ? null : payload.strategies[key] });
      const unservedAvoidedMWh = baseline.unserved_mwh === null || totals.unserved_mwh === null ? null : baseline.unserved_mwh - totals.unserved_mwh;
      const reductionPercent = materialUnserved && unservedAvoidedMWh !== null ? unservedAvoidedMWh / baseline.unserved_mwh * 100 : null;
      return {
        key, label: isPlaceholder ? `${labels[key] || key} · not yet trained` : labels[key] || key,
        isPlaceholder, totals, reductionPercent, unservedAvoidedMWh,
        costChangeGbp: baseline.cost_gbp === null || totals.cost_gbp === null ? null : totals.cost_gbp - baseline.cost_gbp
      };
    });
    const eligible = rows.filter(row => !row.isPlaceholder && row.totals.unserved_mwh !== null);
    const lowest = eligible.length ? Math.min(...eligible.map(row => row.totals.unserved_mwh)) : null;
    let winners = eligible.filter(row => row.totals.unserved_mwh - lowest <= energyToleranceMWh);
    const energyTie = winners.length > 1;
    const costComparable = energyTie && winners.every(row => row.totals.cost_gbp !== null);
    // Cost breaks an energy tie only when every tied strategy reports its cost.
    if (costComparable) {
      const cheapest = Math.min(...winners.map(row => row.totals.cost_gbp));
      winners = winners.filter(row => row.totals.cost_gbp === cheapest);
    }
    const best = winners.length === 1 ? winners[0] : null;
    let headline = 'Comparison results unavailable.';
    if (winners.length > 1) headline = `Unserved energy is within ${energyToleranceMWh} MWh: ${winners.map(row => row.label).join(', ')}. Reported costs do not resolve this tie.`;
    if (best) {
      if (materialUnserved === false) {
        headline = `${costComparable ? `${best.label} has the lowest reported cost among strategies within ${energyToleranceMWh} MWh of the least unserved energy. ` : ''}Baseline unserved energy is below ${minBaselineMWh} MWh; no substantive percentage reduction is reported.`;
      }
      else if (best.key === 'none') headline = costComparable
        ? `No response has the lowest reported cost among strategies within ${energyToleranceMWh} MWh of the least unserved energy.`
        : 'No response has the lowest reported unserved energy in this comparison.';
      else if (best.reductionPercent > 0) headline = `${best.label} reduced unserved energy by ${best.reductionPercent.toFixed(1)}% versus no response.`;
      else if (best.reductionPercent === 0) headline = `${best.label} matched baseline unserved energy with the lowest reported cost.`;
      else if (best.reductionPercent < 0) headline = `${best.label} has the lowest reported cost among strategies within ${energyToleranceMWh} MWh of the least unserved energy; its unserved energy is higher than baseline.`;
      else headline = `${best.label} has the lowest reported unserved energy; baseline reduction is unavailable.`;
    }
    return {
      scenario: payload.scenario || null, rows, bestStrategy: best?.key || null,
      winnerKeys: winners.map(row => row.key), reductionPercent: best?.reductionPercent ?? null,
      materialUnserved, minBaselineMWh, energyToleranceMWh,
      headline, rankingMetric: `Lowest unserved MWh within ${energyToleranceMWh} MWh tolerance, then lowest cost when known`
    };
  }

  function renderForecast(element, payload) {
    validateForecast(payload);
    if (!element || typeof element.replaceChildren !== 'function') throw new TypeError('Forecast chart requires an SVG element.');
    const document = element.ownerDocument;
    const NS = 'http://www.w3.org/2000/svg';
    const svg = (tag, attributes = {}, text) => {
      const item = document.createElementNS(NS, tag);
      Object.entries(attributes).forEach(([key, value]) => item.setAttribute(key, String(value)));
      if (text !== undefined) item.textContent = text;
      return item;
    };
    const width = 360, height = 240;
    const pad = { left: 48, right: 12, top: 26, bottom: 50 };
    const plotWidth = width - pad.left - pad.right, plotHeight = height - pad.top - pad.bottom;
    const minimum = Math.min(...payload.forecast.map(row => row[0]));
    const maximum = Math.max(...payload.forecast.map(row => row[2]));
    const span = Math.max(1, maximum - minimum, maximum * .01);
    const approximateStep = span / 4 * 1.2;
    const magnitude = 10 ** Math.floor(Math.log10(approximateStep));
    const fraction = approximateStep / magnitude;
    const step = (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * magnitude;
    const yMin = Math.floor(Math.max(0, minimum - span * .1) / step) * step;
    const yMax = Math.max(yMin + step, Math.ceil((maximum + span * .1) / step) * step);
    if (![yMin, yMax, step].every(Number.isFinite)) throw new RangeError('Forecast exceeds the supported chart range.');
    const x = index => pad.left + index / 47 * plotWidth;
    const y = value => pad.top + (yMax - value) / (yMax - yMin) * plotHeight;
    const xy = (index, value) => `${x(index).toFixed(2)},${y(value).toFixed(2)}`;
    const peak = payload.forecast.reduce((best, row, index) => row[1] > payload.forecast[best][1] ? index : best, 0);
    const title = svg('title', {}, `${payload.zone_id}: 24-hour demand forecast in MW`);
    const description = svg('desc', {}, `Issued ${formatTime(payload.issue_time_utc, { includeDate: true })}. Forty-eight half-hour starts from ${formatTime(payload.timestamps_utc[0], { includeDate: true })} to ${formatTime(payload.timestamps_utc[47], { includeDate: true })}. The line shows P50; shading shows P10 to P90, not observed demand. Peak median ${payload.forecast[peak][1].toLocaleString('en-GB')} MW at ${formatTime(payload.timestamps_utc[peak], { includeDate: true })}.`);
    const chart = svg('g', { 'aria-hidden': 'true' });
    chart.append(svg('text', { x: pad.left, y: 16, fill: '#647168', 'font-size': 11, 'font-family': 'Arial, sans-serif' }, 'Demand · MW'));
    const tickCount = Math.round((yMax - yMin) / step);
    for (let index = 0; index <= tickCount; index += 1) {
      const tick = yMin + index * step;
      chart.append(svg('line', { x1: pad.left, x2: width - pad.right, y1: y(tick), y2: y(tick), stroke: '#dfe5df', 'stroke-width': 1 }));
      chart.append(svg('text', { x: pad.left - 10, y: y(tick) + 4, fill: '#647168', 'font-size': 11, 'font-family': 'monospace', 'text-anchor': 'end' }, tick.toLocaleString('en-GB', { maximumFractionDigits: 2 })));
    }
    const bandPath = 'M' + payload.forecast.map((row, index) => xy(index, row[2])).join('L') + 'L' + payload.forecast.map((row, index) => xy(index, row[0])).reverse().join('L') + 'Z';
    const medianPath = 'M' + payload.forecast.map((row, index) => xy(index, row[1])).join('L');
    chart.append(svg('path', { d: bandPath, fill: '#3d8b73', 'fill-opacity': .17, class: 'forecast-band' }));
    chart.append(svg('path', { d: medianPath, fill: 'none', stroke: '#26705a', 'stroke-width': 2.5, 'stroke-linejoin': 'round', class: 'forecast-median' }));
    payload.forecast.forEach((row, index) => {
      const hit = svg('circle', { cx: x(index), cy: y(row[1]), r: 7, fill: 'transparent' });
      hit.append(svg('title', {}, `${formatTime(payload.timestamps_utc[index], { includeDate: true })}: P10 ${row[0]} MW; P50 ${row[1]} MW; P90 ${row[2]} MW`));
      chart.append(hit);
    });
    [0, 12, 24, 36, 47].forEach(index => {
      const attributes = { x: x(index), fill: '#647168', 'font-family': 'monospace', 'text-anchor': index === 0 ? 'start' : index === 47 ? 'end' : 'middle' };
      chart.append(svg('text', { ...attributes, y: height - 32, 'font-size': 10 }, formatTime(payload.timestamps_utc[index], { includeZone: false })));
      const zone = new Intl.DateTimeFormat('en-GB', { timeZone: DISPLAY_TZ, timeZoneName: 'short' }).formatToParts(new Date(utcMilliseconds(payload.timestamps_utc[index]))).find(part => part.type === 'timeZoneName').value;
      chart.append(svg('text', { ...attributes, y: height - 20, 'font-size': 8.5 }, zone));
    });
    chart.append(svg('text', { x: pad.left + plotWidth / 2, y: height - 5, fill: '#647168', 'font-size': 9, 'font-family': 'Arial, sans-serif', 'text-anchor': 'middle' }, 'Europe/London · half-hour starting'));
    element.setAttribute('viewBox', `0 0 ${width} ${height}`);
    element.setAttribute('role', 'img');
    element.setAttribute('aria-label', `${payload.zone_id} demand forecast. P50 median with P10 to P90 uncertainty band. Times shown in Europe/London.`);
    element.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    element.replaceChildren(title, description, chart);
    return payload;
  }

  return { totalKpis, validateSnapshot, validateForecast, compareResults, formatTime, renderForecast };
});

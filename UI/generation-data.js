/* Generating-site catalogue helpers and separately sourced national metering.
 * Capacity is not output. National fuel measurements are never allocated to sites.
 * FUELINST is GB operational metering, not UK demand or complete embedded output.
 */
(function (root, factory) {
  'use strict';
  const api = Object.freeze(factory());
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.JMapGenerationData = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const TYPE_LABELS = Object.freeze({ wind_onshore: 'Onshore wind', wind_offshore: 'Offshore wind', solar: 'Solar', hydro: 'Hydro', biomass: 'Biomass', waste: 'Waste', gas: 'Gas', nuclear: 'Nuclear', storage: 'Storage', other: 'Other' });
  const FUELS = Object.freeze([
    ['CCGT', 'Gas · CCGT'], ['OCGT', 'Gas · OCGT'], ['NUCLEAR', 'Nuclear'],
    ['WIND', 'Wind'], ['NPSHYD', 'Hydro'], ['PS', 'Pumped storage'],
    ['BIOMASS', 'Biomass'], ['OTHER', 'Other'], ['COAL', 'Coal'], ['OIL', 'Oil']
  ].map(([code, label]) => Object.freeze({ code, label })));
  const INTERCONNECTOR_CODES = Object.freeze(['INTFR', 'INTIFA2', 'INTELEC', 'INTNED', 'INTNEM', 'INTNSL', 'INTVKL', 'INTIRL', 'INTEW', 'INTGRNL']);
  const FUEL_CODES = new Set(FUELS.map(fuel => fuel.code));
  const KNOWN_CODES = new Set([...FUEL_CODES, ...INTERCONNECTOR_CODES]);
  const SOURCE = Object.freeze({
    name: 'Elexon Insights / NESO operational metering',
    endpoint: 'https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELINST',
    documentation: 'https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELINST',
    definitions: 'https://bmrs.elexon.co.uk/generation-by-fuel-type',
    license: 'https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/',
    intervalMinutes: 5,
    coverage: 'Great Britain operationally metered output by fuel type, including pumped-storage discharge. It does not cover all embedded wind or solar, is not UK demand and is not site-level telemetry.',
    generationDefinition: 'Sum of positive domestic fuel observations, including pumped-storage discharge. Negative domestic observations are preserved separately in the signed mix and netDomesticMW.'
  });

  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const normalise = value => String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('en-GB');
  const searchText = value => normalise(value).replace(/[_-]+/g, ' ');
  function siteArray(sites) {
    if (!Array.isArray(sites) || sites.some(site => !site || typeof site !== 'object' || Array.isArray(site))) throw new TypeError('Sites must be an array of catalogue records.');
    return sites;
  }
  function sum(values) {
    const result = values.reduce((total, value) => total + value, 0);
    if (!Number.isFinite(result)) throw new RangeError('The aggregate exceeds the supported numeric range.');
    return result;
  }
  function filterSites(sites, { query = '', type = 'all', country = 'all' } = {}) {
    siteArray(sites);
    const terms = searchText(query).split(/\s+/).filter(Boolean);
    const selectedType = normalise(type), selectedCountry = normalise(country);
    return sites.filter(site => {
      if (selectedType && selectedType !== 'all' && normalise(site.type) !== selectedType) return false;
      if (selectedCountry && selectedCountry !== 'all' && normalise(site.country) !== selectedCountry) return false;
      const text = searchText([site.id, site.name, site.type, TYPE_LABELS[site.type], site.country, site.operator, site.status, site.originalTechnology, site.region, site.county, site.localAuthority, site.postcode].filter(Boolean).join(' '));
      return terms.every(term => text.includes(term));
    });
  }
  function summarizeSites(sites) {
    siteArray(sites);
    const capacities = sites.map(site => site.capacityMW).filter(value => finite(value) && value >= 0);
    return { count: sites.length, capacityKnownSumMW: sum(capacities), capacityKnownCount: capacities.length, capacityUnknownCount: sites.length - capacities.length };
  }
  function aggregateByType(sites) {
    siteArray(sites);
    const groups = new Map();
    sites.forEach(site => {
      const type = typeof site.type === 'string' && site.type ? site.type : 'unknown';
      if (!groups.has(type)) groups.set(type, []);
      groups.get(type).push(site);
    });
    return [...groups].map(([type, members]) => ({ type, label: TYPE_LABELS[type] || type, ...summarizeSites(members) })).sort((a, b) => b.capacityKnownSumMW - a.capacityKnownSumMW || b.count - a.count || a.type.localeCompare(b.type, 'en-GB'));
  }

  function nowMilliseconds(value) {
    const milliseconds = value === null ? NaN : new Date(value).getTime();
    if (!Number.isFinite(milliseconds)) throw new TypeError('A valid current time is required.');
    return milliseconds;
  }
  function buildNationalUrl(now = Date.now()) {
    const milliseconds = nowMilliseconds(now);
    const params = new URLSearchParams({ publishDateTimeFrom: new Date(milliseconds - 3600000).toISOString(), publishDateTimeTo: new Date(milliseconds).toISOString(), format: 'json' });
    return `${SOURCE.endpoint}?${params}`;
  }

  function parseNationalSnapshot(payload, now = Date.now()) {
    const milliseconds = nowMilliseconds(now);
    if (!payload || !Array.isArray(payload.data)) throw new TypeError('Elexon returned an unexpected national-generation response.');
    const candidates = payload.data.filter(row => row && typeof row.fuelType === 'string' && typeof row.startTime === 'string' && Number.isFinite(Date.parse(row.startTime)) && (!row.dataset || row.dataset === 'FUELINST'));
    if (!candidates.some(row => FUEL_CODES.has(row.fuelType))) throw new Error('No national fuel observations were published in the requested window.');
    const sampleMs = Math.max(...candidates.map(row => Date.parse(row.startTime)));
    if (sampleMs > milliseconds + 60000) throw new Error('The feed returned a future observation; check the device clock.');
    const sameInterval = candidates.filter(row => Date.parse(row.startTime) === sampleMs);
    const revisions = new Map();
    sameInterval.forEach(row => {
      if (!revisions.has(row.fuelType)) revisions.set(row.fuelType, []);
      revisions.get(row.fuelType).push(row);
    });
    const selected = new Map(), conflictingCodes = [];
    for (const [code, rows] of revisions) {
      const publication = row => Number.isFinite(Date.parse(row.publishTime)) ? Date.parse(row.publishTime) : -Infinity;
      const latest = Math.max(...rows.map(publication));
      const latestRows = rows.filter(row => publication(row) === latest);
      const values = latestRows.map(row => finite(row.generation) ? row.generation : null);
      const conflict = new Set(values).size > 1;
      if (conflict) conflictingCodes.push(code);
      selected.set(code, { mw: conflict ? null : values[0], publishTime: Number.isFinite(latest) ? new Date(latest).toISOString() : null });
    }
    const mix = FUELS.map(fuel => ({ ...fuel, mw: selected.get(fuel.code)?.mw ?? null, publishTime: selected.get(fuel.code)?.publishTime ?? null }));
    const interconnectors = INTERCONNECTOR_CODES.map(code => ({ code, mw: selected.get(code)?.mw ?? null, publishTime: selected.get(code)?.publishTime ?? null }));
    const missingFuelCodes = mix.filter(row => row.mw === null).map(row => row.code);
    const missingInterconnectorCodes = interconnectors.filter(row => row.mw === null).map(row => row.code);
    const unknownCodes = [...selected.keys()].filter(code => !KNOWN_CODES.has(code)).sort();
    const unknownDomesticCodes = unknownCodes.filter(code => !code.startsWith('INT'));
    const unknownInterconnectorCodes = unknownCodes.filter(code => code.startsWith('INT'));
    const generationComplete = missingFuelCodes.length === 0 && unknownDomesticCodes.length === 0;
    const transfersComplete = missingInterconnectorCodes.length === 0 && unknownInterconnectorCodes.length === 0;
    const domesticValues = mix.filter(row => row.mw !== null).map(row => row.mw);
    const transferValues = interconnectors.filter(row => row.mw !== null).map(row => row.mw);
    const knownGenerationMW = domesticValues.length ? sum(domesticValues.map(value => Math.max(value, 0))) : null;
    const knownImportsMW = transferValues.length ? sum(transferValues.map(value => Math.max(value, 0))) : null;
    const knownExportsMW = transferValues.length ? sum(transferValues.map(value => Math.max(-value, 0))) : null;
    const pumped = selected.get('PS')?.mw ?? null;
    const publishTimes = [...selected.values()].map(row => Date.parse(row.publishTime)).filter(Number.isFinite);
    return {
      startTime: new Date(sampleMs).toISOString(), endTime: new Date(sampleMs + 300000).toISOString(),
      publishTime: publishTimes.length ? new Date(Math.max(...publishTimes)).toISOString() : null,
      fetchedAt: new Date(milliseconds).toISOString(), mix, interconnectors,
      generationMW: generationComplete ? knownGenerationMW : null,
      netDomesticMW: generationComplete ? sum(domesticValues) : null,
      importsMW: transfersComplete ? knownImportsMW : null,
      exportsMW: transfersComplete ? knownExportsMW : null,
      netImportsMW: transfersComplete ? knownImportsMW - knownExportsMW : null,
      storageDischargeMW: pumped === null ? null : Math.max(pumped, 0),
      storageChargingMW: pumped === null ? null : Math.max(-pumped, 0),
      knownGenerationMW, knownImportsMW, knownExportsMW,
      negativeDomesticCodes: mix.filter(row => row.mw !== null && row.mw < 0).map(row => row.code),
      measuredFuelCount: domesticValues.length, measuredInterconnectorCount: transferValues.length,
      missingFuelCodes, missingInterconnectorCodes, unknownCodes, conflictingCodes: conflictingCodes.sort(),
      generationComplete, transfersComplete, complete: generationComplete && transfersComplete,
      coverage: SOURCE.coverage
    };
  }
  function freshness(snapshot, now = Date.now()) {
    if (!snapshot || !Number.isFinite(Date.parse(snapshot.endTime))) return { state: 'unavailable', ageMinutes: null };
    const ageMinutes = Math.max(0, (nowMilliseconds(now) - Date.parse(snapshot.endTime)) / 60000);
    return { state: ageMinutes > 15 ? 'stale' : 'fresh', ageMinutes };
  }
  async function fetchNationalSnapshot({ now = Date.now(), signal, fetchImpl = globalThis.fetch } = {}) {
    if (typeof fetchImpl !== 'function') throw new Error('This browser cannot request national generation data.');
    const response = await fetchImpl(buildNationalUrl(now), { signal, mode: 'cors', credentials: 'omit', cache: 'no-store', headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`Elexon national-generation request failed (HTTP ${response.status}).`);
    return parseNationalSnapshot(await response.json(), now);
  }

  return { TYPE_LABELS, FUELS, INTERCONNECTOR_CODES, SOURCE, filterSites, summarizeSites, aggregateByType, buildNationalUrl, parseNationalSnapshot, fetchNationalSnapshot, freshness };
});

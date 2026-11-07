/* Public Elexon FUELINST adapter. Positive MW imports into GB; negative exports.
 * Use the signed dataset endpoint: the current-generation summary caps exports.
 * All terminal points below are approximate display coordinates, not cable routes.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.JMapLiveTransfers = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  const SOURCE = Object.freeze({
    name: 'Elexon Insights / NESO operational metering',
    endpoint: 'https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELINST',
    documentation: 'https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELINST',
    definitions: 'https://bscdocs.elexon.co.uk/bsc-module/interface-definition-documents/neta-interface-definition-and-design-document-part-1-interfaces-with-bsc-parties-and-their-agents',
    signConvention: 'https://www.neso.energy/document/304771/download',
    license: 'https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/',
    intervalMinutes: 5
  });
  const LINKS = [
    { id: 'INTFR', name: 'IFA', country: 'France', gbTerminal: 'Sellindge, Kent', otherTerminal: 'Les Mandarins, near Calais', gb: [1.00, 51.10], other: [1.78, 50.91], bend: -10, label: [-32, -25], sourceUrl: 'https://www.nationalgrid.com/document/135331/download' },
    { id: 'INTIFA2', name: 'IFA2', country: 'France', gbTerminal: 'Chilling / Lee-on-the-Solent', otherTerminal: 'Tourbe, Normandy', gb: [-1.19, 50.82], other: [-.23, 49.11], bend: 35, label: [-55, 6], sourceUrl: 'https://www.ofgem.gov.uk/press-release/ofgem-proposes-approving-three-new-electricity-interconnectors' },
    { id: 'INTELEC', name: 'ElecLink', country: 'France', gbTerminal: 'Folkestone, Kent', otherTerminal: 'Coquelles, near Calais', gb: [1.15, 51.10], other: [1.81, 50.93], bend: 12, label: [52, 15], sourceUrl: 'https://www.eleclink.co.uk/publications/eleclink-news' },
    { id: 'INTNED', name: 'BritNed', country: 'Netherlands', gbTerminal: 'Isle of Grain, Kent', otherTerminal: 'Maasvlakte, Rotterdam', gb: [.72, 51.44], other: [4.06, 51.96], bend: -24, label: [8, -14], sourceUrl: 'https://www.britned.com/general/' },
    { id: 'INTNEM', name: 'Nemo Link', country: 'Belgium', gbTerminal: 'Richborough, Kent', otherTerminal: 'Herdersbrug, near Bruges', gb: [1.33, 51.31], other: [3.22, 51.27], bend: 22, label: [20, 27], sourceUrl: 'https://www.neso.energy/publications/electricity-ten-year-statement-etys/electricity-transmission-network-requirements/south-wales-and-south-england-boundaries' },
    { id: 'INTNSL', name: 'North Sea Link', country: 'Norway', gbTerminal: 'Blyth, Northumberland', otherTerminal: 'Kvilldal, Rogaland', gb: [-1.54, 55.14], other: [6.70, 59.50], bend: -25, label: [1, -15], sourceUrl: 'https://www.nationalgrid.com/stories/energy-explained/what-are-electricity-interconnectors' },
    { id: 'INTVKL', name: 'Viking Link', country: 'Denmark', gbTerminal: 'Bicker Fen, Lincolnshire', otherTerminal: 'Revsing, southern Jutland', gb: [-.22, 52.93], other: [9.15, 55.48], bend: -38, label: [0, -15], sourceUrl: 'https://www.nationalgrid.com/national-grid-ventures/viking-link' },
    { id: 'INTIRL', name: 'Moyle', country: 'Northern Ireland', gbTerminal: 'Auchencrosh, Ayrshire', otherTerminal: 'Ballycronan More, Islandmagee', gb: [-5.02, 55.02], other: [-5.79, 54.86], bend: -12, label: [-27, -22], sourceUrl: 'https://www.mutual-energy.com/electricity/' },
    { id: 'INTEW', name: 'East–West', country: 'Ireland', gbTerminal: 'Deeside, north Wales', otherTerminal: 'Woodland, County Meath', gb: [-3.03, 53.22], other: [-6.63, 53.50], bend: -10, label: [-5, -13], sourceUrl: 'https://cms.eirgrid.ie/sites/default/files/publications/All-Island-Ten-Year-Transmission-Forecast-Statement-2024_1.pdf' },
    { id: 'INTGRNL', name: 'Greenlink', country: 'Ireland', gbTerminal: 'Pembroke, south Wales', otherTerminal: 'Great Island, County Wexford', gb: [-4.99, 51.68], other: [-6.99, 52.28], bend: 11, label: [-2, 26], sourceUrl: 'https://greenlink.ie/faqs/' }
  ].map(link => Object.freeze(link));
  Object.freeze(LINKS);
  const IDS = new Set(LINKS.map(link => link.id));

  function buildUrl(now = Date.now()) {
    const time = typeof now === 'number' ? now : new Date(now).getTime();
    if (!Number.isFinite(time)) throw new TypeError('A valid current time is required.');
    const params = new URLSearchParams({ publishDateTimeFrom: new Date(time - 60 * 60 * 1000).toISOString(), publishDateTimeTo: new Date(time).toISOString(), format: 'json' });
    return `${SOURCE.endpoint}?${params}`;
  }

  function parseSnapshot(payload, now = Date.now()) {
    if (!payload || !Array.isArray(payload.data)) throw new TypeError('Elexon returned an unexpected response.');
    const candidates = payload.data.filter(row => row && typeof row.fuelType === 'string' && row.fuelType.startsWith('INT') && typeof row.startTime === 'string' && Number.isFinite(Date.parse(row.startTime)));
    const known = candidates.filter(row => IDS.has(row.fuelType));
    if (!known.length) throw new Error('No interconnector observations were published in the last hour.');
    const sampleMs = Math.max(...known.map(row => Date.parse(row.startTime)));
    if (sampleMs > Number(now) + 60 * 1000) throw new Error('The feed returned a future observation; check the device clock.');
    const sameInterval = candidates.filter(row => Date.parse(row.startTime) === sampleMs);
    const links = LINKS.map(link => {
      const rows = sameInterval.filter(row => row.fuelType === link.id).sort((a, b) => (Date.parse(b.publishTime) || 0) - (Date.parse(a.publishTime) || 0));
      const row = rows[0];
      const value = row && typeof row.generation === 'number' && Number.isFinite(row.generation) ? row.generation : null;
      const direction = value === null ? 'unknown' : value > 0 ? 'import' : value < 0 ? 'export' : 'idle';
      return { ...link, mw: value, direction, absoluteMw: value === null ? null : Math.abs(value), startTime: new Date(sampleMs).toISOString(), publishTime: row && Number.isFinite(Date.parse(row.publishTime)) ? new Date(row.publishTime).toISOString() : null };
    });
    const measured = links.filter(link => link.mw !== null);
    const unmappedCodes = [...new Set(sameInterval.filter(row => !IDS.has(row.fuelType)).map(row => row.fuelType))];
    const importsMw = measured.reduce((sum, link) => sum + Math.max(link.mw, 0), 0);
    const exportsMw = measured.reduce((sum, link) => sum + Math.max(-link.mw, 0), 0);
    const publishMs = Math.max(...measured.map(link => Date.parse(link.publishTime)).filter(Number.isFinite));
    return { startTime: new Date(sampleMs).toISOString(), endTime: new Date(sampleMs + 5 * 60 * 1000).toISOString(), publishTime: Number.isFinite(publishMs) ? new Date(publishMs).toISOString() : null, fetchedAt: new Date(now).toISOString(), links, importsMw: measured.length ? importsMw : null, exportsMw: measured.length ? exportsMw : null, netImportsMw: measured.length ? importsMw - exportsMw : null, measuredCount: measured.length, totalCount: LINKS.length, complete: measured.length === LINKS.length && unmappedCodes.length === 0, unmappedCodes };
  }

  function freshness(snapshot, now = Date.now()) {
    if (!snapshot) return { state: 'unavailable', ageMinutes: null };
    const ageMinutes = Math.max(0, (Number(now) - Date.parse(snapshot.endTime)) / 60000);
    return { state: ageMinutes > 15 ? 'stale' : 'fresh', ageMinutes };
  }

  async function fetchSnapshot({ now = Date.now(), signal, fetchImpl = globalThis.fetch } = {}) {
    if (typeof fetchImpl !== 'function') throw new Error('This browser cannot request the live feed.');
    const response = await fetchImpl(buildUrl(now), { signal, mode: 'cors', credentials: 'omit', cache: 'no-store', headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`Elexon request failed (HTTP ${response.status}).`);
    return parseSnapshot(await response.json(), now);
  }

  return Object.freeze({ SOURCE, LINKS, buildUrl, parseSnapshot, freshness, fetchSnapshot });
});

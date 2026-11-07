/* Source-region summaries of registered installed capacity, including storage
 * power. Summary coordinates are capacity-weighted catalogue locations: they
 * are neither generating stations nor administrative/network boundaries.
 * Keep full-catalogue coordinates by stable ID when filtering a fixed overview.
 */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.JMapGenerationOverview = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const REFERENCE_CAPACITY_MW = 25000;
  const REGIONS = [
    ['east-midlands', 'East Midlands', 'England'],
    ['east-of-england', 'East of England', 'England'],
    ['london', 'London', 'England'],
    ['north-east', 'North East', 'England'],
    ['north-west', 'North West', 'England'],
    ['northern-ireland', 'Northern Ireland', 'Northern Ireland'],
    ['scotland', 'Scotland', 'Scotland'],
    ['south-east', 'South East', 'England'],
    ['south-west', 'South West', 'England'],
    ['wales', 'Wales', 'Wales'],
    ['west-midlands', 'West Midlands', 'England'],
    ['yorkshire-and-the-humber', 'Yorkshire and the Humber', 'England'],
    ['offshore', 'Offshore sites', 'United Kingdom']
  ].map(([id, name, country]) => Object.freeze({ id, name, country }));
  const key = value => typeof value === 'string'
    ? value.trim().toLowerCase().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ') : '';
  const definitions = new Map(REGIONS.flatMap(region => [[key(region.id), region], [key(region.name), region]]));
  definitions.set('eastern', definitions.get('east of england'));
  definitions.set('east england', definitions.get('east of england'));
  definitions.set('eastengland', definitions.get('east of england'));
  definitions.set('yorkshire and humber', definitions.get('yorkshire and the humber'));
  definitions.set('offshore', definitions.get('offshore sites'));
  const UNASSIGNED = Object.freeze({ id: 'unassigned', name: 'Region unavailable', country: null });
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const knownCapacity = value => finite(value) && value >= 0;
  const validLocation = site => finite(site.lat) && Math.abs(site.lat) <= 90
    && finite(site.lon) && Math.abs(site.lon) <= 180;

  /**
   * Group the supplied records without mutation or rounding. `sites` contains
   * original records and `siteCount` counts register records, including phases.
   * `capacityMW` is null if any capacity is missing/invalid; `knownCapacityMW`
   * sums only measured nonnegative values and is null if there are none.
   * Weighted coordinates use positive known capacity at valid locations; when
   * no such weights exist, the mean of valid locations is used. No locations
   * yields null coordinates. Unknown source regions remain explicitly grouped.
   */
  function aggregateRegions(sites) {
    if (!Array.isArray(sites)) throw new TypeError('Region aggregation requires an array of site records.');
    const groups = new Map();
    for (const site of sites) {
      if (!site || typeof site !== 'object' || Array.isArray(site)) throw new TypeError('Each site must be a record.');
      const definition = definitions.get(key(site.region)) || UNASSIGNED;
      if (!groups.has(definition.id)) groups.set(definition.id, {
        ...definition, sites: [], capacitySum: 0, knownCapacityCount: 0,
        locationCount: 0, latitudeSum: 0, longitudeSum: 0,
        locationWeight: 0, weightedLatitude: 0, weightedLongitude: 0
      });
      const group = groups.get(definition.id);
      group.sites.push(site);
      if (knownCapacity(site.capacityMW)) {
        group.capacitySum += site.capacityMW;
        group.knownCapacityCount++;
      }
      if (validLocation(site)) {
        group.locationCount++;
        group.latitudeSum += site.lat;
        group.longitudeSum += site.lon;
        if (knownCapacity(site.capacityMW) && site.capacityMW > 0) {
          group.locationWeight += site.capacityMW;
          group.weightedLatitude += site.lat * site.capacityMW;
          group.weightedLongitude += site.lon * site.capacityMW;
        }
      }
    }
    const order = [...REGIONS.map(region => region.id), UNASSIGNED.id];
    return order.filter(id => groups.has(id)).map(id => {
      const group = groups.get(id), siteCount = group.sites.length;
      const unknownCapacityCount = siteCount - group.knownCapacityCount;
      const knownCapacityMW = group.knownCapacityCount ? group.capacitySum : null;
      const isOffshore = id === 'offshore';
      return {
        id: group.id, name: group.name, country: group.country, isOffshore,
        capacityMW: unknownCapacityCount ? null : knownCapacityMW,
        knownCapacityMW, knownCapacityCount: group.knownCapacityCount, unknownCapacityCount,
        siteCount, sites: group.sites,
        lat: group.locationWeight > 0 ? group.weightedLatitude / group.locationWeight
          : group.locationCount ? group.latitudeSum / group.locationCount : null,
        lon: group.locationWeight > 0 ? group.weightedLongitude / group.locationWeight
          : group.locationCount ? group.longitudeSum / group.locationCount : null,
        note: isOffshore ? 'UK-wide offshore sites; the summary marker is not a single generating location.'
          : id === 'unassigned' ? 'Source region is unavailable or unrecognised.'
          : 'Source-region summary; the marker is not a single generating location.'
      };
    });
  }

  return Object.freeze({ aggregateRegions, REFERENCE_CAPACITY_MW, referenceCapacityMW: REFERENCE_CAPACITY_MW });
});

/*
 * Official annual electricity context; deliberately independent of JMAP_SITES.
 * DESNZ, Regional electricity generation and supply timeseries, 2004 to 2025.
 * Published 29 September 2026. Workbook downloaded and cells checked 7 Nov 2026.
 * Source workbook values are GWh. All values below are TWh (GWh / 1000).
 *
 * Table 1 / "Generation and supply": 2025 columns DD=Scotland, DE=Wales,
 * DF=Northern Ireland, DG=England. Row 7=gross generation; rows 12,13,14=
 * net outward transfers to England, Northern Ireland and Europe respectively;
 * row 20=final electricity consumed. Net imports reverse the transfer signs.
 * Gross demand is derived as generation + net imports. It includes network
 * losses, generation/storage own use and the source's balancing differences;
 * it must not be confused with Table 1 row 20 final consumption or public sales.
 * Table 2a / "Electricity generation by fuel": 2025 columns DE=Scotland,
 * DF=Wales, DG=Northern Ireland, DH=England; rows 33,35,36=renewables,wind,solar.
 * Gross generation includes pumped-storage and recorded grid-battery output.
 *
 * An annual deficit means net imports, NOT unmet demand or outage probability.
 * Nations are linked by electricity networks; annual surplus is not guaranteed
 * spare capacity at peak times. These records contain no local access, network
 * constraints, hourly adequacy or interruption measurements.
 */
(function (root, factory) {
  'use strict';
  const data = factory();
  if (typeof module === 'object' && module.exports) module.exports = data;
  else root.JMAP_REGIONS = data;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const publicationUrl = 'https://www.gov.uk/government/statistics/energy-trends-september-2026-special-feature-article-electricity-generation-and-supply-in-scotland-wales-northern-ireland-and-england-2021-to-2025';
  const workbookUrl = 'https://assets.publishing.service.gov.uk/media/6aba6c4afe72ed1e2b02f14b/Regional_Electricity_Generation_and_Supply_Timeseries_2026.xlsx';
  const records = [
    {
      key: 'england', name: 'England',
      generationTWh: 208.85100686544826,
      netImportsTWh: 57.04046984948886,
      finalConsumptionTWh: 231.59209280910069,
      windTWh: 47.7108702, solarTWh: 17.41379,
      renewableTWh: 101.6508002,
      sourceColumn: 'DG', fuelSourceColumn: 'DH'
    },
    {
      key: 'scotland', name: 'Scotland',
      generationTWh: 54.014912844021426,
      netImportsTWh: -20.751075,
      finalConsumptionTWh: 27.997217332488213,
      windTWh: 30.85002, solarTWh: 0.77409,
      renewableTWh: 39.02691,
      sourceColumn: 'DD', fuelSourceColumn: 'DE'
    },
    {
      key: 'wales', name: 'Wales',
      generationTWh: 22.470185617246178,
      netImportsTWh: -7.151063349488864,
      finalConsumptionTWh: 12.441434177318521,
      windTWh: 4.99617, solarTWh: 1.60845,
      renewableTWh: 8.25202,
      sourceColumn: 'DE', fuelSourceColumn: 'DF'
    },
    {
      key: 'northern-ireland', name: 'Northern Ireland',
      generationTWh: 8.225713073284123,
      netImportsTWh: 0.5914256,
      finalConsumptionTWh: 7.828955681092516,
      windTWh: 2.88262, solarTWh: 0.32867,
      renewableTWh: 4.06393,
      sourceColumn: 'DF', fuelSourceColumn: 'DG'
    }
  ];

  return Object.freeze({
    year: 2025,
    published: '2026-09-29',
    checked: '2026-11-07',
    unit: 'TWh',
    title: 'Electricity generation and supply by UK nation, 2025',
    publisher: 'Department for Energy Security and Net Zero',
    sourceUrl: publicationUrl,
    sources: Object.freeze([
      Object.freeze({ title: 'DESNZ regional electricity generation and supply, 2004 to 2025', url: publicationUrl }),
      Object.freeze({ title: 'Official data workbook (Table 1 and Table 2a)', url: workbookUrl }),
      Object.freeze({ title: 'Gross electricity demand definition (Department for the Economy)', url: 'https://www.economy-ni.gov.uk/articles/electricity-consumption-and-renewable-generation-statistics' })
    ]),
    definitions: Object.freeze({
      generationTWh: 'Annual gross electricity generation, including pumped storage and recorded grid-battery discharge (Table 1, row 7).',
      consumptionTWh: 'Gross annual electricity demand, derived as gross generation plus net imports. Includes network losses and generation/storage own use; different from final consumption.',
      demandTWh: 'Alias of consumptionTWh: gross annual electricity demand.',
      finalConsumptionTWh: 'Total electricity consumed by final users, including autogenerators (Table 1, row 20). Shown separately from gross demand.',
      netImportsTWh: 'Negative sum of net outward transfers (Table 1, rows 12 to 14). Positive means net imports from other UK nations and Europe; negative means net exports.',
      balanceTWh: 'Gross generation minus gross demand, equal to net exports. This annual energy balance does not measure spare power capacity or unmet demand.',
      coverage: 'Gross generation divided by gross annual demand. This measures local generation relative to use, not household connection/access or security of supply.',
      windTWh: 'Annual wind generation by all generating companies (Table 2a, row 35).',
      solarTWh: 'Annual solar generation by all generating companies (Table 2a, row 36).',
      renewableTWh: 'All renewables including hydro, wind, solar, wave/tidal and bioenergy (Table 2a, row 33).',
      scenario: 'Changes applied to annual generation and demand are illustrative sensitivity calculations, not dispatch, transmission or shortage forecasts.'
    }),
    limitations: Object.freeze([
      'Historical annual data, not current power or a forecast.',
      'Gross demand includes network losses and generation/storage own use; it is not final-user electricity consumption.',
      'A deficit is covered by net imports. Import reliance alone does not imply a power shortage.',
      'Surplus over a year does not guarantee availability at peak demand.',
      'No local network constraints, transfer limits, outage rates, storage duration or household electricity-access measurements are included.',
      'Northern Ireland operates within the all-island electricity market; a UK aggregate is an annual accounting sum, not one operational grid.',
      'Official tables include statistical and rounding differences; derived gross demand preserves the generation and net-transfer accounting identity.'
    ]),
    regions: Object.freeze(records.map(record => Object.freeze({
      ...record,
      year: 2025,
      consumptionTWh: record.generationTWh + record.netImportsTWh,
      demandTWh: record.generationTWh + record.netImportsTWh
    })))
  });
});

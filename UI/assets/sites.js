/*
 * JMap demonstration dataset: 45 representative UK sites, not a complete asset register.
 * All output values are synthetic examples in MW, NOT live or historical measurements.
 * Coordinates and installed capacities are approximate; capacity definitions vary by source.
 * Wind/hydro/biomass/nuclear mean generation; storage means discharge; interconnectors
 * mean import to GB. Neither storage nor interconnectors should count as generation.
 * Operator labels are descriptive and do not represent complete ownership structures.
 * UK totals are illustrative site aggregates, not a measured GB/all-island power balance.
 * The dataset contains no demand, network constraints, or transmission-flow measurements.
 * Primary reference pages checked when preparing this demonstration:
 * https://www.edfenergy.com/about/nuclear/power-stations
 * https://orsted.co.uk/energy-solutions/offshore-wind/our-wind-farms
 * https://www.sserenewables.com/our-sites/
 * https://www.drax.com/uk/what-we-do/cruachan-power-station/
 * https://www.nationalgrid.com/national-grid-ventures/interconnectors-connecting-cleaner-future
 * https://harmonyenergy.co.uk/projects/
 * https://www.gov.uk/government/collections/renewables-statistics
 * https://www.epuki.co.uk/about/our-power-stations/ballylumford/
 * https://www.epuki.co.uk/about/our-power-stations/kilroot/
 * https://www.sserenewables.com/onshore-wind/northern-ireland/slieve-kirk-wind-park/
 * https://esb.ie/what-we-do/generation-and-trading/crockdun---wind
 * https://www.res-group.com/resources/news/res-doubles-down-with-new-solar-om-contracts/
 */
window.JMAP_SITES = [
  { id: 'beatrice', name: 'Beatrice Offshore Wind Farm', type: 'wind', region: 'scotland', lat: 58.13, lon: -3.07, capacity: 588, output: 376, operator: 'Beatrice Offshore Windfarm', note: 'Offshore wind in the Moray Firth. Illustrative output; approximate location and capacity.' },
  { id: 'moray-east', name: 'Moray East Wind Farm', type: 'wind', region: 'scotland', lat: 58.16, lon: -2.70, capacity: 950, output: 638, operator: 'Ocean Winds', note: 'Offshore wind in the outer Moray Firth. Illustrative output; approximate location and capacity.' },
  { id: 'seagreen', name: 'Seagreen Offshore Wind Farm', type: 'wind', region: 'scotland', lat: 56.59, lon: -1.73, capacity: 1075, output: 742, operator: 'SSE Renewables', note: 'Offshore wind east of Angus. Illustrative output; approximate location and capacity.' },
  { id: 'whitelee', name: 'Whitelee Wind Farm', type: 'wind', region: 'scotland', lat: 55.68, lon: -4.28, capacity: 539, output: 287, operator: 'ScottishPower Renewables', note: 'Onshore wind south of Glasgow. Illustrative output; approximate location and capacity.' },
  { id: 'clyde', name: 'Clyde Wind Farm', type: 'wind', region: 'scotland', lat: 55.46, lon: -3.56, capacity: 548, output: 324, operator: 'SSE Renewables', note: 'Onshore wind in South Lanarkshire, including extension. Illustrative output; approximate location and capacity.' },
  { id: 'hornsea-one', name: 'Hornsea 1 Wind Farm', type: 'wind', region: 'england', lat: 53.89, lon: 1.83, capacity: 1218, output: 816, operator: 'Ørsted', note: 'Offshore wind east of Yorkshire. Illustrative output; approximate location and capacity.' },
  { id: 'hornsea-two', name: 'Hornsea 2 Wind Farm', type: 'wind', region: 'england', lat: 53.98, lon: 1.63, capacity: 1320, output: 924, operator: 'Ørsted', note: 'Offshore wind east of Yorkshire. Illustrative output; approximate location and capacity.' },
  { id: 'walney-extension', name: 'Walney Extension', type: 'wind', region: 'england', lat: 54.08, lon: -3.74, capacity: 659, output: 382, operator: 'Ørsted', note: 'Offshore wind west of Walney Island. Illustrative output; approximate location and capacity.' },
  { id: 'gwynt-y-mor', name: 'Gwynt y Môr Wind Farm', type: 'wind', region: 'wales', lat: 53.45, lon: -3.58, capacity: 576, output: 351, operator: 'RWE', note: 'Offshore wind north of the Welsh coast. Illustrative output; approximate location and capacity.' },
  { id: 'east-anglia-one', name: 'East Anglia ONE', type: 'wind', region: 'england', lat: 52.23, lon: 2.52, capacity: 714, output: 507, operator: 'ScottishPower Renewables', note: 'Offshore wind east of Suffolk. Illustrative output; approximate location and capacity.' },
  { id: 'london-array', name: 'London Array', type: 'wind', region: 'england', lat: 51.64, lon: 1.50, capacity: 630, output: 334, operator: 'London Array', note: 'Offshore wind in the Thames Estuary. Illustrative output; approximate location and capacity.' },
  { id: 'rampion', name: 'Rampion Offshore Wind Farm', type: 'wind', region: 'england', lat: 50.64, lon: -0.26, capacity: 400, output: 208, operator: 'RWE', note: 'Offshore wind south of Sussex. Illustrative output; approximate location and capacity.' },

  { id: 'torness', name: 'Torness Power Station', type: 'nuclear', region: 'scotland', lat: 55.97, lon: -2.41, capacity: 1200, output: 1080, operator: 'EDF', note: 'Advanced gas-cooled reactors in East Lothian. Illustrative output; approximate location and capacity.' },
  { id: 'heysham-one', name: 'Heysham 1 Power Station', type: 'nuclear', region: 'england', lat: 54.03, lon: -2.91, capacity: 1060, output: 841, operator: 'EDF', note: 'Advanced gas-cooled reactors in Lancashire. Illustrative output; approximate location and capacity.' },
  { id: 'heysham-two', name: 'Heysham 2 Power Station', type: 'nuclear', region: 'england', lat: 54.03, lon: -2.92, capacity: 1240, output: 1132, operator: 'EDF', note: 'Advanced gas-cooled reactors in Lancashire. Illustrative output; approximate location and capacity.' },
  { id: 'hartlepool', name: 'Hartlepool Power Station', type: 'nuclear', region: 'england', lat: 54.64, lon: -1.18, capacity: 1185, output: 962, operator: 'EDF', note: 'Advanced gas-cooled reactors on Teesside. Illustrative output; approximate location and capacity.' },
  { id: 'sizewell-b', name: 'Sizewell B', type: 'nuclear', region: 'england', lat: 52.22, lon: 1.62, capacity: 1198, output: 1114, operator: 'EDF', note: 'Pressurised water reactor on the Suffolk coast. Illustrative output; approximate location and capacity.' },

  { id: 'peterhead', name: 'Peterhead Power Station', type: 'gas', region: 'scotland', lat: 57.48, lon: -1.78, capacity: 1180, output: 781, operator: 'SSE Thermal', note: 'Combined-cycle gas generation in Aberdeenshire. Illustrative output; approximate location and capacity.' },
  { id: 'keadby-two', name: 'Keadby 2', type: 'gas', region: 'england', lat: 53.60, lon: -0.75, capacity: 893, output: 624, operator: 'SSE Thermal', note: 'Combined-cycle gas generation in North Lincolnshire. Illustrative output; approximate location and capacity.' },
  { id: 'pembroke', name: 'Pembroke Power Station', type: 'gas', region: 'wales', lat: 51.68, lon: -4.99, capacity: 2199, output: 1467, operator: 'RWE', note: 'Combined-cycle gas generation on the Milford Haven waterway. Illustrative output; approximate location and capacity.' },
  { id: 'carrington', name: 'Carrington Power Station', type: 'gas', region: 'england', lat: 53.43, lon: -2.40, capacity: 884, output: 591, operator: 'ESB', note: 'Combined-cycle gas generation in Greater Manchester. Illustrative output; approximate location and capacity.' },
  { id: 'grain', name: 'Grain Power Station', type: 'gas', region: 'england', lat: 51.44, lon: 0.71, capacity: 1326, output: 849, operator: 'Uniper', note: 'Combined-cycle gas generation on the Isle of Grain. Illustrative output; approximate location and capacity.' },
  { id: 'staythorpe', name: 'Staythorpe Power Station', type: 'gas', region: 'england', lat: 53.17, lon: -0.81, capacity: 1735, output: 1218, operator: 'RWE', note: 'Combined-cycle gas generation in Nottinghamshire. Illustrative output; approximate location and capacity.' },
  { id: 'marchwood', name: 'Marchwood Power Station', type: 'gas', region: 'england', lat: 50.90, lon: -1.45, capacity: 842, output: 514, operator: 'Marchwood Power', note: 'Combined-cycle gas generation on Southampton Water. Illustrative output; approximate location and capacity.' },

  { id: 'shotwick', name: 'Shotwick Solar Park', type: 'solar', region: 'wales', lat: 53.24, lon: -2.99, capacity: 72, output: 38, operator: 'Shotwick Solar Park', note: 'Solar photovoltaic generation in Flintshire. Illustrative output; approximate location and capacity.' },
  { id: 'llanwern', name: 'Llanwern Solar Farm', type: 'solar', region: 'wales', lat: 51.56, lon: -2.90, capacity: 75, output: 42, operator: 'NextEnergy', note: 'Solar photovoltaic generation near Newport. Illustrative output; approximate location and capacity.' },
  { id: 'west-raynham', name: 'West Raynham Solar Farm', type: 'solar', region: 'england', lat: 52.79, lon: 0.75, capacity: 50, output: 27, operator: 'West Raynham Solar', note: 'Solar photovoltaic generation on a former Norfolk airfield. Illustrative output; approximate location and capacity.' },
  { id: 'southwick', name: 'Southwick Estate Solar Farm', type: 'solar', region: 'england', lat: 50.89, lon: -1.08, capacity: 50, output: 29, operator: 'Southwick Estate Solar', note: 'Solar photovoltaic generation in Hampshire. Illustrative output; approximate location and capacity.' },

  { id: 'sloy', name: 'Sloy Power Station', type: 'hydro', region: 'scotland', lat: 56.25, lon: -4.71, capacity: 152, output: 94, operator: 'SSE Renewables', note: 'Conventional hydroelectric generation near Loch Lomond. Illustrative output; approximate location and capacity.' },
  { id: 'foyers', name: 'Foyers Power Station', type: 'storage', region: 'scotland', lat: 57.26, lon: -4.49, capacity: 300, output: 120, operator: 'SSE Renewables', note: 'Pumped hydro storage on Loch Ness; output represents discharge. Illustrative output; approximate location and capacity.' },
  { id: 'cruachan', name: 'Cruachan Power Station', type: 'storage', region: 'scotland', lat: 56.40, lon: -5.12, capacity: 440, output: 198, operator: 'Drax', note: 'Pumped hydro storage inside Ben Cruachan; output represents discharge. Illustrative output; approximate location and capacity.' },
  { id: 'dinorwig', name: 'Dinorwig Power Station', type: 'storage', region: 'wales', lat: 53.12, lon: -4.11, capacity: 1728, output: 672, operator: 'First Hydro', note: 'Pumped hydro storage in Eryri; output represents discharge. Illustrative output; approximate location and capacity.' },

  { id: 'drax', name: 'Drax Power Station', type: 'biomass', region: 'england', lat: 53.74, lon: -1.00, capacity: 2595, output: 2136, operator: 'Drax', note: 'Biomass generation near Selby. Illustrative output; approximate location and capacity.' },
  { id: 'markinch', name: 'Markinch Biomass CHP', type: 'biomass', region: 'scotland', lat: 56.19, lon: -3.13, capacity: 65, output: 49, operator: 'RWE', note: 'Biomass combined heat and power in Fife. Illustrative electrical output; approximate location and capacity.' },
  { id: 'lynemouth', name: 'Lynemouth Power Station', type: 'biomass', region: 'england', lat: 55.21, lon: -1.52, capacity: 420, output: 327, operator: 'Lynemouth Power', note: 'Biomass generation in Northumberland. Illustrative output; approximate location and capacity.' },

  { id: 'ifa', name: 'IFA Interconnector', type: 'interconnector', region: 'england', lat: 51.10, lon: 1.00, capacity: 2000, output: 1460, operator: 'National Grid / RTE', note: 'GB converter station at Sellindge; connects France. Output represents illustrative imports, not generation.' },
  { id: 'britned', name: 'BritNed Interconnector', type: 'interconnector', region: 'england', lat: 51.44, lon: 0.72, capacity: 1000, output: 680, operator: 'BritNed', note: 'GB converter station on the Isle of Grain; connects the Netherlands. Output represents illustrative imports, not generation.' },
  { id: 'north-sea-link', name: 'North Sea Link', type: 'interconnector', region: 'england', lat: 55.14, lon: -1.54, capacity: 1400, output: 1120, operator: 'National Grid / Statnett', note: 'GB converter station at Blyth; connects Norway. Output represents illustrative imports, not generation.' },

  { id: 'pillswood', name: 'Pillswood Battery', type: 'storage', region: 'england', lat: 53.77, lon: -0.44, capacity: 98, output: 44, operator: 'Harmony Energy', note: 'Battery energy storage near Cottingham; output represents discharge. Illustrative output; approximate location and capacity.' },
  { id: 'clay-tye', name: 'Clay Tye Battery', type: 'storage', region: 'england', lat: 51.56, lon: 0.32, capacity: 99, output: 41, operator: 'Harmony Energy / FRV', note: 'Battery energy storage near Upminster; output represents discharge. Illustrative output; approximate location and capacity.' },

  { id: 'ballylumford', name: 'Ballylumford Power Station', type: 'gas', region: 'northern-ireland', lat: 54.849, lon: -5.785, capacity: 688, output: 446, operator: 'EP Ballylumford', note: 'Gas generation at Islandmagee, County Antrim. Synthetic sample output; approximate location and capacity. Not live telemetry.' },
  { id: 'kilroot-gas', name: 'Kilroot Gas Turbines', type: 'gas', region: 'northern-ireland', lat: 54.730, lon: -5.753, capacity: 700, output: 420, operator: 'EP Kilroot', note: 'Two 350 MW natural-gas turbines near Carrickfergus. Excludes the separate oil-fired units. Synthetic sample output; approximate location and capacity. Not live telemetry.' },
  { id: 'slieve-kirk', name: 'Slieve Kirk Wind Park', type: 'wind', region: 'northern-ireland', lat: 54.945, lon: -7.116, capacity: 73.6, output: 48, operator: 'SSE Renewables', note: 'Onshore wind cluster between Ardmore and Limavady. Synthetic sample output; approximate cluster location and capacity. Not live telemetry.' },
  { id: 'crockdun', name: 'Crockdun Wind Farm', type: 'wind', region: 'northern-ireland', lat: 54.6305, lon: -7.0802, capacity: 12.5, output: 8, operator: 'ESB', note: 'Onshore wind near Loughmacrory, County Tyrone. Synthetic sample output; approximate location and capacity. Not live telemetry.' },
  { id: 'ballygarvey', name: 'Ballygarvey Solar Farm', type: 'solar', region: 'northern-ireland', lat: 54.916, lon: -6.233, capacity: 8.2, output: 4, operator: 'Ballygarvey Solar', note: 'Solar generation near Ballymena, County Antrim. Synthetic sample output; approximate location and capacity. Not live telemetry.' }
];

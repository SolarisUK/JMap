Stage 2: Elexon half-hourly generation by fuel, 2024-2025

Extract this ZIP into C:\Users\ranya\JMap. The pulls, data and results folders
must sit directly inside JMap, beside schemas.py and the existing Stage 1 files.

Run from a fresh PowerShell prompt in JMap:

    python .\pulls\pull_elexon.py --offline

The offline command rebuilds generation_by_fuel.parquet from the saved raw
responses and checks its timestamp join to your Stage 1 demand data.
It makes no network requests. Keep pulls/pull_neso.py from Stage 1: Stage 2
imports its timestamp converter and retry-enabled HTTP session.

To download again, run without --offline. Existing raw batches are reused,
so interrupted downloads resume. To refresh a particular saved batch, move
its dated .json and .source.json files out of data/raw/elexon first.

Contents
--------
pulls/pull_elexon.py
data/raw/elexon/generation_by_fuel.parquet
data/raw/elexon/YYYY-MM-DD_YYYY-MM-DD.json (untouched API response bytes)
data/raw/elexon/YYYY-MM-DD_YYYY-MM-DD.source.json (source URL, time and hash)
data/raw/elexon/YYYY-MM.json (monthly manifests listing the response files)
results/stage2_checks.txt

Differences from the runbook
--------------------------
The current FUELHH endpoint rejects requests spanning more than seven inclusive
settlement dates. Monthly calls return HTTP 400. The script downloads 119 small
batches, with a 0.5 second pause after each successful request. HTTP failures
retry up to three times with backoff. Monthly manifests group the responses;
they are labelled as manifests and are not presented as original API payloads.

The script imports the shared Stage 1 converter and checks every converted
timestamp against Elexon's own startTime field, including DST boundary days.
Multiple publications for a period/fuel resolve to the latest publishTime;
conflicting values with an identical publication time cause an error.

Source fuel names are preserved. Missing fuel values remain null; no unpublished
fuel category is invented as zero. The report lists each fuel's first/last
publication and missing cells inside its published time range.

wind_total_mw is the sum of the wind categories present in FUELHH. It does not
include NESO's embedded wind estimate. The script creates solar_mw only if the
source actually publishes a solar category.

FUELHH excludes embedded generation. Source interconnector/storage categories
also have their own reporting conventions. Do not treat a sum of these columns
as all GB generation or require it to equal NESO ND. Signed values, if present
in a source category, are retained.

This generation file is a separate supporting dataset. The final canonical
real.parquet still uses exactly the nine columns specified in the contract.

Checks and next task
--------------------
Completed checks: 35,088 generation rows; 35,088 demand rows; 35,088 joined
rows (100%). No duplicate timestamps or missing half-hours. Every converted
timestamp agrees with the published UTC startTime.

The 20 observed source fuel codes have complete coverage except INTGRNL
(Greenlink), which has 10,466 unpublished cells, including 6,704 between its
first and last publication. These remain null. There is no solar category.

Read results/stage2_checks.txt for the completed coverage and join results.
These are Stage 2 checks, not the missing project's canonical validator.
Next: Stage 3, zone weather, followed by regional allocation and the canonical
table in Stages 4 and 5.

Attribution
-----------
Source: Elexon Insights, FUELHH, operational data supplied by NESO.
https://bmrs.elexon.co.uk/generation-by-fuel-type
https://bmrs.elexon.co.uk/api-documentation/endpoint
https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH
Use and redistribution are subject to Elexon's BMRS data licence.

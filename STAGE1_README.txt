Stage 1 completed: NESO national demand, 2024-2025

Extract this ZIP into your JMap project root. Its pulls/, data/ and results/
folders belong beside the project's schemas.py, not inside the old CSV folder.

PowerShell verification (your existing Python already has these dependencies):

    cd "C:\Users\ranya\JMap"
    python .\pulls\pull_neso.py --offline

The offline command rebuilds the Parquet from the saved NESO JSON and validates
all timestamps and day lengths. It makes no network requests.

To refresh the raw data later:

    python .\pulls\pull_neso.py

If running on a new computer, install the dependencies first:

    python -m pip install requests pandas pyarrow tzdata

Files
-----
data/raw/neso/national_demand.parquet  Validated Stage 1 intermediate
data/raw/neso/2024.json               Untouched NESO API response
data/raw/neso/2025.json               Untouched NESO API response
data/raw/neso/*.source.json           Source URLs, retrieval times and hashes
pulls/pull_neso.py                    Download, convert and validate
results/stage1_checks.txt             Results of the completed checks

Verified results
----------------
35,088 records; 2024-01-01 00:00 UTC through 2025-12-31 23:30 UTC.
No duplicates, missing half-hours or null data values.
727 local days have 48 periods, 2 have 46, and 2 have 50.
Minimum/maximum national demand: 12,803 / 45,924 MW.

Important details
-----------------
This file has the five Stage 1 columns from the runbook. The final real.parquet
will have the nine columns in _fake.parquet after weather and zone demand are
added in later stages. Do not substitute this intermediate for _fake.parquet.

The annual NESO files are historic outturn and have no forecast/actual column.
The script filters to A when that column exists. No forecast values, synthetic
values or interpolated targets have been added.

The script parses the API's ISO dates explicitly. Settlement period timestamps
start at Europe/London midnight and advance in elapsed half-hours. This handles
spring's skipped hour and both occurrences of autumn's repeated hour. Adding
period offsets to naive local clock times before localisation, as one runbook
paragraph suggests, does not handle those days correctly.

The original local CSV files and old neso_demand_utc.parquet were not available
in the attachments. The future dates in that older file remain unexplained.
These fresh downloads avoid depending on that conversion.

The project's scripts/check_parquet.py was not supplied and has not been run.
The PASS result is from this script's Stage 1 checks. The canonical validator
will still be needed at Stage 5.

These are GB national-demand figures. Later regional demand will be estimated
from that total, as described in the contract.

Official sources
----------------
https://www.neso.energy/data-portal/historic-demand-data/historic_demand_data_2024
https://www.neso.energy/data-portal/historic-demand-data/historic_demand_data_2025
https://assets.elexon.co.uk/wp-content/uploads/sites/11/2012/02/04142749/el01921.pdf

Next runbook task: Stage 2, Elexon generation by fuel.

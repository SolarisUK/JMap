Stage 6: data-quality report and coverage heatmap

Extract this ZIP into C:\Users\ranya\JMap. Its pulls and results folders belong
directly inside JMap, beside schemas.py and the existing stage files.

The finished report and chart are included, so they can be viewed immediately.
To regenerate them against your local data, run these commands one at a time:

    python -m pip install matplotlib
    python .\pulls\quality_report.py

Expected:

    Stage 6 quality report: COMPLETE
    Rows: 350,880; zones: 10; target coverage: 100.00%
    Target gaps longer than two hours: 0

Outputs
-------
results/data_quality.md            Compact report with three caveats at the top
results/data_coverage.png          Daily target coverage for each zone, 2024-2025
results/data_quality_summary.json  Full figures and validated Parquet hash
pulls/quality_report.py            Reusable report generator

Checks covered
--------------
Rows, date window, target coverage per zone, total-demand share versus contract,
each quality flag, all target gaps longer than two hours, national-demand
min/mean/max and comparison with the runbook's rough 18,000-48,000 MW guide.

Coverage means non-null targets divided by the expected UTC half-hours. It
includes any interpolated target values; their flags and exclusion from scoring
are reported separately. A complete table may still consist of estimates.
All regional demand rows in this project are estimates, not measured loads.

The heatmap correctly looks uniform: every zone has 48 non-null targets on
every UTC day. Local 46/50-period clock-change days do not change UTC day lengths.
The chart displays a fixed 0-48 scale and does not invent variation.

The completed report records 1,583 national half-hours below the rough 18 GW
guide, none above 48 GW, and retains those original outturn values. It also
states the approximate weather issue times and the dependence of allocated
regional targets on the temperature feature used to construct them.

The script checks that the canonical file hash matches the output that passed
the supplied team checker and that its input file hashes still match. If a
source has changed, run build_canonical.py successfully before regenerating
the report. The script reads your current schemas.py via the existing contract
loader. It makes no network requests after the chart package is installed.

The preparatory run here uses the contract fields printed in your supplied
schemas.py history. Your local run uses your full, current schemas.py.

Next runbook task: Stage 7, zone polygons as GeoJSON.

Run the supplied team checker on Windows

Extract this small update into C:\Users\ranya\JMap, alongside schemas.py and
the files already created in Stages 1-5.

Then run from a fresh PowerShell prompt in JMap:

    python .\pulls\build_canonical.py

This rebuilds real.parquet, runs the independent checks, and runs the supplied
team checker through a portable launcher. Expected team-checker output:

    PASS — conforms to the canonical table contract

The build should also report "Original runbook checker exit code: 0".

What this update contains
-------------------------
scripts/check_parquet.py             Your uploaded checker, unchanged
scripts/run_team_checker.py          Portable launcher
pulls/build_canonical.py             Updated to invoke that launcher
results/stage5_checks.txt            Completed checks from this session
results/canonical_metadata.json      Updated check status and file hashes

Why the launcher is needed
--------------------------
The supplied checker inserts /home/claude into its import path. That directory
does not locate your JMap schemas.py on Windows, especially with Python -I.
The launcher loads schemas.py from your actual project root before running
the unmodified checker.

The supplied checker also prints FAIL without returning a failing process
status. The launcher checks its actual problems list and returns 1 if it
contains violations, otherwise 0. No validation rules are replaced or relaxed.

The original runbook's direct command still has its hardcoded-path issue.
Use the build command above, or run only the supplied checker with:

    python -I scripts/run_team_checker.py data/canonical/real.parquet

Verification completed here
--------------------------
The supplied checker returned PASS on the 350,880-row real.parquet, with no
warnings. It reported all nine types correct, all ten zones present, 100%
coverage, no duplicates and no nulls. The file contains 348,960 rows flagged
OK and 1,920 flagged DST_BOUNDARY.

The local run used only the schema fields and scoring function printed in
your supplied schemas.py history. Your Windows run uses your full, current
schemas.py. A deliberately wrong float64 demand column was also rejected
with exit status 1 through the launcher.

The uploaded checker and the generated real.parquet remain byte-for-byte
unchanged. The package does not overwrite your schemas.py or alter raw data.

Passing the schema checker does not change the documented interpretation:
regional demand is estimated, and the forecast issue timestamps are proxies.
The checker labels non-null issue times "forecast" without checking actual
model-run availability; that limitation remains in the data provenance.

After the local team check passes, Stage 5's gate is closed and the next
runbook task is Stage 6: the quality report and data-coverage heatmap.

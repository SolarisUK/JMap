"""Validate a canonical-table parquet file against the project contract.

Usage: python3 -I scripts/check_parquet.py <path-to-parquet>
"""

import sys
from pathlib import Path

sys.path.insert(0, "/home/claude")

import pyarrow.parquet as pq  # noqa: E402

import schemas as S  # noqa: E402

path = Path(sys.argv[1])

pf = pq.ParquetFile(path)
print(f"=== {path.name} ===")
print(f"rows      : {pf.metadata.num_rows:,}")
print(f"row groups: {pf.metadata.num_row_groups}")
print(f"size      : {path.stat().st_size:,} bytes")
print()

print("--- schema as written ---")
print(pf.schema_arrow)
print()

tbl = pf.read()
cols = list(tbl.column_names)

print("--- contract check ---")
problems: list[str] = []
warnings: list[str] = []

# 1. columns
missing = [c for c in S.CANONICAL_COLUMNS if c not in cols]
extra = [c for c in cols if c not in S.CANONICAL_COLUMNS]
if missing:
    problems.append(f"missing required columns: {missing}")
if extra:
    warnings.append(f"extra columns not in contract: {extra}")
print(f"columns   : {len(cols)} present, {len(missing)} missing, {len(extra)} extra")

# 2. dtypes
# pyarrow's str() uses C names for the floats: float32 prints as "float", float64 as "double".
TYPE_ALIAS = {"float": "float32", "double": "float64", "halffloat": "float16"}

print("\ncolumn types (actual vs contract):")
for c in S.CANONICAL_COLUMNS:
    want = S.CANONICAL_SCHEMA[c]
    if c not in cols:
        print(f"  {c:26} MISSING            want {want}")
        continue
    got = str(tbl.schema.field(c).type)
    norm_got = TYPE_ALIAS.get(got, got)
    mark = "ok " if norm_got == want else "!! "
    if norm_got != want:
        problems.append(f"{c}: type is {norm_got}, contract says {want}")
    print(f"  {mark}{c:26} {got:22} want {want}")

df = tbl.to_pandas()

# 3. zone ids
if "zone_id" in cols:
    found = set(df["zone_id"].dropna().unique())
    unknown = sorted(found - set(S.ZONE_ORDER))
    print(f"\nzones     : {len(found)} distinct")
    print(f"  found   : {sorted(found)}")
    if unknown:
        problems.append(f"unknown zone ids (not in contract): {unknown}")
    absent = sorted(set(S.ZONE_ORDER) - found)
    if absent:
        warnings.append(f"contract zones with no rows: {absent}")

# 4. timestamps
if "timestamp_utc" in cols:
    ts = df["timestamp_utc"]
    print(f"\ntimestamps: {ts.min()}  ->  {ts.max()}")
    tzinfo = getattr(ts.dtype, "tz", None)
    print(f"  tz      : {tzinfo}")
    if tzinfo is None:
        problems.append("timestamp_utc is tz-naive; contract requires tz=UTC")
    elif str(tzinfo) not in ("UTC", "tzutc()", "datetime.timezone.utc"):
        problems.append(f"timestamp_utc tz is {tzinfo}, contract requires UTC")

    # half-hour alignment
    secs = ts.dt.minute * 60 + ts.dt.second + ts.dt.microsecond / 1e6
    bad_align = int(((secs != 0) & (secs != 1800)).sum())
    print(f"  aligned : {len(ts) - bad_align}/{len(ts)} on :00 or :30")
    if bad_align:
        problems.append(f"{bad_align} timestamps not aligned to a half-hour boundary")

    # duplicates per zone
    if "zone_id" in cols:
        dups = int(df.duplicated(subset=["zone_id", "timestamp_utc"]).sum())
        print(f"  dupes   : {dups} duplicate (zone_id, timestamp_utc) pairs")
        if dups:
            problems.append(f"{dups} duplicate (zone_id, timestamp_utc) rows")

        # gaps
        print("\n  per zone:")
        for z, g in df.groupby("zone_id", observed=True):
            t = g["timestamp_utc"].sort_values()
            deltas = t.diff().dropna()
            steps = deltas.dt.total_seconds() / 1800.0
            gaps = int((steps > 1).sum())
            expected = (
                int((t.max() - t.min()).total_seconds() // 1800) + 1 if len(t) > 1 else len(t)
            )
            print(
                f"    {z:6} {len(g):6,} rows  expected {expected:6,}  "
                f"gaps {gaps}  coverage {100*len(g)/max(expected,1):5.1f}%"
            )

# 5. values
print("\nvalue ranges:")
for c in ("demand_mw", "temp_c", "wind_ms", "solar_wm2"):
    if c not in cols:
        continue
    s = df[c]
    nn = int(s.isna().sum())
    print(f"  {c:12} min {s.min():10.2f}  max {s.max():10.2f}  mean {s.mean():10.2f}  nulls {nn}")

if "demand_mw" in cols:
    neg = int((df["demand_mw"] < 0).sum())
    if neg:
        warnings.append(f"{neg} negative demand_mw values (valid only if modelling export)")
    nulls = df["demand_mw"].isna()
    if nulls.any():
        if "quality_flag" in cols:
            unflagged = int((nulls & ((df["quality_flag"].astype(int) & S.QF.MISSING) == 0)).sum())
            if unflagged:
                problems.append(
                    f"{unflagged} null demand_mw rows without quality_flag bit MISSING set"
                )
            else:
                print(f"\n  {int(nulls.sum())} null demand_mw rows, all flagged MISSING — ok")
        else:
            problems.append("demand_mw has nulls but there is no quality_flag column")

# 6. quality flags
if "quality_flag" in cols:
    vc = df["quality_flag"].value_counts().sort_index()
    print("\nquality_flag values:")
    names = {
        S.QF.OK: "OK",
        S.QF.MISSING: "MISSING",
        S.QF.INTERPOLATED: "INTERPOLATED",
        S.QF.ZERO_RUN: "ZERO_RUN",
        S.QF.JUMP: "JUMP",
        S.QF.DST_BOUNDARY: "DST_BOUNDARY",
    }
    for v, n in vc.items():
        label = names.get(int(v), f"combination of bits ({int(v):#06b})")
        print(f"  {int(v):3} {label:22} {n:,} rows")
    scorable = int(df["quality_flag"].apply(lambda f: S.is_scorable(int(f))).sum())
    print(f"  scorable rows: {scorable:,} / {len(df):,}")

# 7. weather provenance
if "weather_issue_time_utc" in cols:
    nn = int(df["weather_issue_time_utc"].isna().sum())
    print(f"\nweather_issue_time_utc: {nn:,} null (observed), {len(df)-nn:,} forecast")
    if nn == len(df):
        warnings.append(
            "every weather row is marked observed; training on this leaks future weather"
        )

# 8. demand shares
if {"zone_id", "demand_mw"} <= set(cols):
    tot = df.groupby("zone_id", observed=True)["demand_mw"].sum()
    share = tot / tot.sum()
    print("\nzone share of total demand (actual vs contract):")
    for z in S.ZONE_ORDER:
        if z in share.index:
            a, w = share[z], S.DEMAND_SHARE[z]
            flag = "  <-- off" if abs(a - w) > 0.03 else ""
            print(f"  {z:6} {a:6.1%}  contract {w:5.1%}{flag}")

print("\n" + "=" * 60)
if problems:
    print(f"FAIL — {len(problems)} contract violation(s):")
    for p in problems:
        print(f"  x {p}")
else:
    print("PASS — conforms to the canonical table contract")
if warnings:
    print(f"\n{len(warnings)} warning(s):")
    for w in warnings:
        print(f"  ! {w}")

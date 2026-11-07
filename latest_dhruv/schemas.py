"""Shared contract for the grid project. Pure standard library — importable with nothing installed.

Owner: Dhruv. Frozen at hour 2. This module is the authority: where CONTRACT.md and this file
disagree, this file wins.

    import schemas
    schemas.ZONE_ORDER          # the ten zone ids, in canonical order
    schemas.OBS_DIM             # 48
    schemas.ACT_DIM             # 11
    schemas.validate_obs(...)   # shape check for Eugene's trainer
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, Sequence

CONTRACT_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

HALF_HOURS_PER_DAY = 48
STEPS_PER_EPISODE = 48
FORECAST_HORIZON = 48
QUANTILES = (0.1, 0.5, 0.9)
QUANTILE_NAMES = ("p10", "p50", "p90")

DISPLAY_TZ = "Europe/London"  # display only; everything internal is UTC


# ---------------------------------------------------------------------------
# Fuels
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fuel:
    id: str
    cost_gbp_per_mwh: float
    carbon_t_per_mwh: float
    dispatchable: bool
    curtailable: bool = False


FUELS: tuple[Fuel, ...] = (
    Fuel("NUCLEAR", 10.0, 0.00, dispatchable=False),
    Fuel("CCGT", 75.0, 0.37, dispatchable=True),
    Fuel("OCGT", 180.0, 0.55, dispatchable=True),
    Fuel("WIND", 0.0, 0.00, dispatchable=False, curtailable=True),
    Fuel("SOLAR", 0.0, 0.00, dispatchable=False, curtailable=True),
    Fuel("HYDRO", 5.0, 0.00, dispatchable=True),
    Fuel("BIOMASS", 110.0, 0.12, dispatchable=True),
    Fuel("IMPORT", 90.0, 0.25, dispatchable=True),
)

FUEL_ORDER: tuple[str, ...] = tuple(f.id for f in FUELS)
FUEL_INDEX: dict[str, int] = {f.id: i for i, f in enumerate(FUELS)}
N_FUELS = len(FUELS)

FUEL_COST = {f.id: f.cost_gbp_per_mwh for f in FUELS}
FUEL_CARBON = {f.id: f.carbon_t_per_mwh for f in FUELS}
DISPATCHABLE = tuple(f.id for f in FUELS if f.dispatchable)
CURTAILABLE = tuple(f.id for f in FUELS if f.curtailable)


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    demand_share: float
    capacity_mw: dict[str, float]
    storage_mwh: float
    storage_power_mw: float
    dr_mw: float  # demand response available
    lat: float
    lon: float


def _cap(**kw: float) -> dict[str, float]:
    """Capacity dict with every fuel present, missing ones zeroed."""
    out = {f: 0.0 for f in FUEL_ORDER}
    for k, v in kw.items():
        if k not in out:
            raise KeyError(f"unknown fuel {k!r}; expected one of {FUEL_ORDER}")
        out[k] = float(v)
    return out


ZONES: tuple[Zone, ...] = (
    Zone(
        "NSCO", "North Scotland", 0.04,
        _cap(WIND=6000, HYDRO=1500, CCGT=200, SOLAR=50),
        storage_mwh=600, storage_power_mw=300, dr_mw=80,
        lat=57.5, lon=-4.2,
    ),
    Zone(
        "SSCO", "South Scotland", 0.07,
        _cap(WIND=4500, HYDRO=500, NUCLEAR=1200, CCGT=1200, SOLAR=200),
        storage_mwh=900, storage_power_mw=450, dr_mw=140,
        lat=55.9, lon=-3.8,
    ),
    Zone(
        "NORT", "North England", 0.13,
        _cap(WIND=2500, NUCLEAR=1200, CCGT=4000, OCGT=500, SOLAR=800, HYDRO=200),
        storage_mwh=1200, storage_power_mw=600, dr_mw=260,
        lat=54.5, lon=-2.3,
    ),
    Zone(
        "YORK", "Yorkshire", 0.08,
        _cap(WIND=1500, CCGT=3000, BIOMASS=2600, SOLAR=1000, OCGT=300),
        storage_mwh=800, storage_power_mw=400, dr_mw=160,
        lat=53.8, lon=-1.3,
    ),
    Zone(
        "WALE", "Wales", 0.06,
        _cap(WIND=1800, CCGT=3500, SOLAR=1200, HYDRO=400, OCGT=200),
        storage_mwh=500, storage_power_mw=250, dr_mw=120,
        lat=52.4, lon=-3.7,
    ),
    Zone(
        "MIDL", "Midlands", 0.17,
        _cap(WIND=1200, CCGT=6000, SOLAR=2500, BIOMASS=500, OCGT=600),
        storage_mwh=1600, storage_power_mw=800, dr_mw=340,
        lat=52.6, lon=-1.5,
    ),
    Zone(
        "EAST", "East England", 0.10,
        _cap(WIND=5000, NUCLEAR=1200, CCGT=4000, SOLAR=3000, OCGT=400, IMPORT=2000),
        storage_mwh=1400, storage_power_mw=700, dr_mw=200,
        lat=52.4, lon=0.8,
    ),
    Zone(
        "SWES", "South West England", 0.08,
        _cap(WIND=1200, NUCLEAR=1000, CCGT=1500, SOLAR=3500, HYDRO=100, OCGT=200),
        storage_mwh=700, storage_power_mw=350, dr_mw=160,
        lat=50.9, lon=-3.6,
    ),
    Zone(
        "LOND", "London", 0.13,
        _cap(CCGT=1500, SOLAR=500, OCGT=400, IMPORT=2000),
        storage_mwh=1000, storage_power_mw=500, dr_mw=380,
        lat=51.5, lon=-0.1,
    ),
    Zone(
        "SOUT", "South & South East England", 0.14,
        _cap(WIND=2000, NUCLEAR=1200, CCGT=2500, SOLAR=3000, IMPORT=3000, OCGT=300),
        storage_mwh=1500, storage_power_mw=750, dr_mw=300,
        lat=51.1, lon=0.5,
    ),
)

ZONE_ORDER: tuple[str, ...] = tuple(z.id for z in ZONES)
ZONE_INDEX: dict[str, int] = {z.id: i for i, z in enumerate(ZONES)}
ZONE_BY_ID: dict[str, Zone] = {z.id: z for z in ZONES}
N_ZONES = len(ZONES)

DEMAND_SHARE: dict[str, float] = {z.id: z.demand_share for z in ZONES}

SLACK_ZONE = "MIDL"


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Edge:
    id: str
    frm: str
    to: str
    limit_mw: float
    circuits: int
    x_pu: float  # series reactance, per unit


def _edge(frm: str, to: str, limit_mw: float, circuits: int, x_pu: float) -> Edge:
    return Edge(f"{frm}-{to}", frm, to, float(limit_mw), circuits, x_pu)


EDGES: tuple[Edge, ...] = (
    _edge("NSCO", "SSCO", 3200, 2, 0.040),
    _edge("SSCO", "NORT", 6000, 2, 0.030),  # B6, the Scotland-England boundary
    _edge("NORT", "YORK", 5000, 2, 0.020),
    _edge("NORT", "WALE", 2500, 1, 0.055),
    _edge("YORK", "MIDL", 6000, 2, 0.018),
    _edge("YORK", "EAST", 3000, 1, 0.045),
    _edge("WALE", "MIDL", 3000, 2, 0.030),
    _edge("WALE", "SWES", 2000, 1, 0.060),
    _edge("MIDL", "EAST", 4000, 2, 0.025),
    _edge("MIDL", "LOND", 5000, 2, 0.022),
    _edge("MIDL", "SWES", 3000, 1, 0.040),
    _edge("EAST", "LOND", 4500, 2, 0.020),
    _edge("LOND", "SOUT", 5000, 2, 0.018),
    _edge("SWES", "SOUT", 2500, 1, 0.045),
)

EDGE_ORDER: tuple[str, ...] = tuple(e.id for e in EDGES)
EDGE_INDEX: dict[str, int] = {e.id: i for i, e in enumerate(EDGES)}
EDGE_BY_ID: dict[str, Edge] = {e.id: e for e in EDGES}
N_EDGES = len(EDGES)

B6_EDGE = "SSCO-NORT"

# Adjacency: zone id -> edge ids touching it, in EDGE_ORDER order.
ADJACENT: dict[str, tuple[str, ...]] = {
    z.id: tuple(e.id for e in EDGES if e.frm == z.id or e.to == z.id) for z in ZONES
}

# MIDL is the transmission hub with five adjacent corridors; everything else has three or fewer.
MAX_DEGREE = 5
assert all(len(v) <= MAX_DEGREE for v in ADJACENT.values()), "MAX_DEGREE too small"


# ---------------------------------------------------------------------------
# Canonical table
# ---------------------------------------------------------------------------

CANONICAL_PATH = "data/canonical"
CANONICAL_PARTITION = ("year", "month")

# column -> pyarrow type string. Ranya builds the pa.schema() from this.
CANONICAL_SCHEMA: dict[str, str] = {
    "zone_id": "string",
    "timestamp_utc": "timestamp[us, tz=UTC]",
    "demand_mw": "float32",
    "temp_c": "float32",
    "wind_ms": "float32",
    "solar_wm2": "float32",
    "weather_issue_time_utc": "timestamp[us, tz=UTC]",
    "quality_flag": "uint8",
    "is_estimated": "bool",
}

CANONICAL_COLUMNS: tuple[str, ...] = tuple(CANONICAL_SCHEMA)


class QF:
    """Quality flag bits. Combine with OR."""

    OK = 0
    MISSING = 1
    INTERPOLATED = 2
    ZERO_RUN = 4
    JUMP = 8
    DST_BOUNDARY = 16


# Rows with any of these bits set are excluded from scoring.
QF_UNSCORABLE = QF.MISSING | QF.INTERPOLATED


def is_scorable(flag: int) -> bool:
    return not (flag & QF_UNSCORABLE)


# ---------------------------------------------------------------------------
# Observation layout (per zone)
# ---------------------------------------------------------------------------

OBS_SIN_TOD = 0
OBS_COS_TOD = 1
OBS_IS_WEEKEND = 2
OBS_DEMAND_NOW = 3

OBS_FC_P50 = 4  # 4 slots: +1, +2, +4, +8 half-hours
OBS_FC_P50_LEADS = (1, 2, 4, 8)

OBS_FC_P90 = 8  # 2 slots: +1, +4 half-hours
OBS_FC_P90_LEADS = (1, 4)

OBS_CAP = 10  # 8 slots, FUEL_ORDER
OBS_OUT = 18  # 8 slots, FUEL_ORDER

OBS_STORAGE_SOC = 26
OBS_STORAGE_POWER = 27
OBS_DR_AVAIL = 28
OBS_UNSERVED_LAST = 29
OBS_NET_POSITION = 30

OBS_EDGE_FLOW = 31  # MAX_DEGREE slots, zero-padded
OBS_EDGE_HEADROOM = 36  # MAX_DEGREE slots
OBS_EDGE_TRIPPED = 41  # MAX_DEGREE slots
OBS_NBR_NET = 46  # MAX_DEGREE slots

OBS_NATIONAL_MARGIN = 51

OBS_DIM = 52

# Normalisation divisors. Keep these stable: the trained policy bakes them in.
NORM_DEMAND_MW = 10_000.0
NORM_NATIONAL_MW = 60_000.0
NORM_POWER_MW = 5_000.0


# ---------------------------------------------------------------------------
# Action layout (per zone), every element in [-1, 1]
# ---------------------------------------------------------------------------

ACT_DISPATCH = 0  # 8 slots, FUEL_ORDER; non-dispatchable slots ignored
ACT_STORAGE = 8  # -1 full charge .. +1 full discharge
ACT_DR = 9  # mapped to 0..1
ACT_CURTAIL = 10  # mapped to 0..1

ACT_DIM = 11

ACTION_LOW = -1.0
ACTION_HIGH = 1.0


def unit_to_fraction(x: float) -> float:
    """Map an action element from [-1, 1] to [0, 1]."""
    return (max(ACTION_LOW, min(ACTION_HIGH, x)) + 1.0) / 2.0


# ---------------------------------------------------------------------------
# Reward
# ---------------------------------------------------------------------------

W_UNSERVED = 1000.0  # per MWh unserved
W_OVERLOAD = 100.0  # per MW over a line limit
W_COST = 1.0  # per £1000
W_CARBON = 5.0  # per tCO2
W_CURTAIL = 2.0  # per MWh curtailed


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

INCIDENT_TYPES = (
    "line_trip",
    "generator_outage",
    "wind_lull",
    "demand_spike",
    "interconnector_loss",
)


@dataclass
class Incident:
    type: str
    target: str  # edge_id for line_trip, else zone_id
    start_step: int
    duration_steps: int
    magnitude: float

    def __post_init__(self) -> None:
        if self.type not in INCIDENT_TYPES:
            raise ValueError(f"unknown incident type {self.type!r}")
        if self.type == "line_trip":
            if self.target not in EDGE_BY_ID:
                raise ValueError(f"unknown edge {self.target!r}")
        elif self.target not in ZONE_BY_ID:
            raise ValueError(f"unknown zone {self.target!r}")
        if not 0 <= self.start_step < STEPS_PER_EPISODE:
            raise ValueError(f"start_step out of range: {self.start_step}")
        if self.duration_steps < 1:
            raise ValueError("duration_steps must be >= 1")

    def active_at(self, step: int) -> bool:
        return self.start_step <= step < self.start_step + self.duration_steps

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "target": self.target,
            "start_step": self.start_step,
            "duration_steps": self.duration_steps,
            "magnitude": self.magnitude,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Incident":
        return cls(
            type=d["type"],
            target=d["target"],
            start_step=int(d["start_step"]),
            duration_steps=int(d["duration_steps"]),
            magnitude=float(d["magnitude"]),
        )


# ---------------------------------------------------------------------------
# Strategies and scenarios
# ---------------------------------------------------------------------------

STRATEGIES = ("none", "optimiser", "agents")

SCENARIOS = ("b6_trip_windy_peak", "cold_snap", "nuclear_outage_low_wind")

SCENARIO_DIR = "scenarios"
MODEL_DIR = "models"
POLICY_DIR = "policies"
GEO_PATH = "data/geo/zones.geojson"
RESULTS_PATH = "results/compare.json"


# ---------------------------------------------------------------------------
# The forecaster interface Eugene implements in forecast.py
# ---------------------------------------------------------------------------


class Forecaster(Protocol):
    def predict(self, zone_id: str, issue_time_utc: datetime) -> list[list[float]]:
        """48 rows of [p10, p50, p90] in MW, starting at issue_time_utc."""
        ...

    def predict_all(self, issue_time_utc: datetime) -> list[list[list[float]]]:
        """N_ZONES x 48 x 3, zones in ZONE_ORDER order."""
        ...


# ---------------------------------------------------------------------------
# Validators — cheap shape checks so mistakes surface at the boundary
# ---------------------------------------------------------------------------


def validate_obs(obs: Sequence[Sequence[float]]) -> None:
    if len(obs) != N_ZONES:
        raise ValueError(f"obs must have {N_ZONES} rows, got {len(obs)}")
    for i, row in enumerate(obs):
        if len(row) != OBS_DIM:
            raise ValueError(
                f"obs row {i} ({ZONE_ORDER[i]}) must have {OBS_DIM} values, got {len(row)}"
            )


def validate_action(action: Sequence[Sequence[float]]) -> None:
    if len(action) != N_ZONES:
        raise ValueError(f"action must have {N_ZONES} rows, got {len(action)}")
    for i, row in enumerate(action):
        if len(row) != ACT_DIM:
            raise ValueError(
                f"action row {i} ({ZONE_ORDER[i]}) must have {ACT_DIM} values, got {len(row)}"
            )
        for j, v in enumerate(row):
            if not (ACTION_LOW - 1e-6 <= v <= ACTION_HIGH + 1e-6):
                raise ValueError(
                    f"action[{ZONE_ORDER[i]}][{j}] = {v} outside [{ACTION_LOW}, {ACTION_HIGH}]"
                )


def validate_forecast(fc: Sequence[Sequence[float]]) -> None:
    if len(fc) != FORECAST_HORIZON:
        raise ValueError(f"forecast must have {FORECAST_HORIZON} rows, got {len(fc)}")
    for h, row in enumerate(fc):
        if len(row) != 3:
            raise ValueError(f"forecast row {h} must be [p10, p50, p90], got {len(row)} values")
        p10, p50, p90 = row
        if not (p10 <= p50 <= p90):
            raise ValueError(f"forecast row {h} quantiles out of order: {row}")


def validate_canonical_columns(columns: Sequence[str]) -> None:
    missing = [c for c in CANONICAL_COLUMNS if c not in columns]
    if missing:
        raise ValueError(f"canonical table missing columns: {missing}")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Self-check: run `python schemas.py` to confirm the contract is internally consistent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    total_share = sum(DEMAND_SHARE.values())
    assert abs(total_share - 1.0) < 1e-9, f"demand shares sum to {total_share}, not 1.0"

    assert len(set(ZONE_ORDER)) == N_ZONES, "duplicate zone id"
    assert len(set(EDGE_ORDER)) == N_EDGES, "duplicate edge id"
    assert SLACK_ZONE in ZONE_BY_ID, "slack zone not a real zone"
    assert B6_EDGE in EDGE_BY_ID, "B6 edge not a real edge"

    for e in EDGES:
        assert e.frm in ZONE_BY_ID and e.to in ZONE_BY_ID, f"edge {e.id} references unknown zone"
        assert e.circuits >= 1, f"edge {e.id} has no circuits"

    # Every zone reachable from the slack bus.
    seen = {SLACK_ZONE}
    frontier = [SLACK_ZONE]
    while frontier:
        z = frontier.pop()
        for eid in ADJACENT[z]:
            e = EDGE_BY_ID[eid]
            nxt = e.to if e.frm == z else e.frm
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    assert seen == set(ZONE_ORDER), f"graph not connected; unreachable: {set(ZONE_ORDER) - seen}"

    # Observation and action layouts tile exactly, no overlaps or gaps.
    slots = (
        [OBS_SIN_TOD, OBS_COS_TOD, OBS_IS_WEEKEND, OBS_DEMAND_NOW]
        + list(range(OBS_FC_P50, OBS_FC_P50 + len(OBS_FC_P50_LEADS)))
        + list(range(OBS_FC_P90, OBS_FC_P90 + len(OBS_FC_P90_LEADS)))
        + list(range(OBS_CAP, OBS_CAP + N_FUELS))
        + list(range(OBS_OUT, OBS_OUT + N_FUELS))
        + [OBS_STORAGE_SOC, OBS_STORAGE_POWER, OBS_DR_AVAIL, OBS_UNSERVED_LAST, OBS_NET_POSITION]
        + list(range(OBS_EDGE_FLOW, OBS_EDGE_FLOW + MAX_DEGREE))
        + list(range(OBS_EDGE_HEADROOM, OBS_EDGE_HEADROOM + MAX_DEGREE))
        + list(range(OBS_EDGE_TRIPPED, OBS_EDGE_TRIPPED + MAX_DEGREE))
        + list(range(OBS_NBR_NET, OBS_NBR_NET + MAX_DEGREE))
        + [OBS_NATIONAL_MARGIN]
    )
    assert sorted(slots) == list(range(OBS_DIM)), (
        f"observation layout does not tile [0, {OBS_DIM}): "
        f"{sorted(set(range(OBS_DIM)) - set(slots))} unused, "
        f"{len(slots) - len(set(slots))} overlapping"
    )

    act_slots = list(range(ACT_DISPATCH, ACT_DISPATCH + N_FUELS)) + [
        ACT_STORAGE,
        ACT_DR,
        ACT_CURTAIL,
    ]
    assert sorted(act_slots) == list(range(ACT_DIM)), "action layout does not tile"

    print(f"contract v{CONTRACT_VERSION} OK")
    print(f"  {N_ZONES} zones, {N_EDGES} edges, {N_FUELS} fuels")
    print(f"  obs {N_ZONES}x{OBS_DIM}, action {N_ZONES}x{ACT_DIM}")
    print(f"  slack bus {SLACK_ZONE}, B6 edge {B6_EDGE}")
    print(f"  max degree {max(len(v) for v in ADJACENT.values())} (limit {MAX_DEGREE})")

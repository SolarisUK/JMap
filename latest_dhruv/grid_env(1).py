"""GridEnv — the simulation environment.

Lossless DC power flow using the contract's corridor reactances and each corridor's remaining
circuit fraction. Each electrical island has its own reference angle and balances its own shortage
or surplus. Thermal violations are reported and penalised rather than clipped: protection relays,
AC voltage/reactive power and dynamic stability are outside this model. Equations follow the
MATPOWER DC model (https://matpower.app/manual/matpower/DCModeling.html).

Merged in from Eugene's review (2026-11-07): partial trips reduce susceptance, surplus spills at
supplying zones, storage efficiency on both power limits, no battery charging during a shortage,
opened lines report zero flow, reset clears stale step detail, cached flow factors per topology.

What is already real:
  - observation and action shapes, and the meaning of every slot
  - zone demand, read from the canonical table
  - wind and solar output driven by actual weather
  - fuel costs, carbon intensities, storage and demand-response limits
  - all five incident types, with the sampling weights that matter
  - the reward function and every weight
  - the info dict the dashboard renders from
  - forecast slots populated (naive forecast for now, Eugene's model later)

What is still crude:
  - flows come from a minimum-norm solve of the nodal balance, which is DC power flow with every
    reactance set equal. The real version weights by susceptance. Closer than a stub needs to be,
    which is deliberate: convergence here should transfer.

Usage:
    import grid_env
    env = grid_env.GridEnv()
    obs, info = env.reset(seed=0)
    obs, reward, terminated, truncated, info = env.step(action)
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import gymnasium as gym
import numpy as np
from gymnasium import spaces

import schemas as S

DEFAULT_DATA = Path("data/canonical/_fake.parquet")
PHYSICS_VERSION = "dc-power-flow-v2"
DC_BASE_MVA = 1000.0

# Incident sampling. Not uniform over edges: NSCO hangs off the grid by one corridor, so a uniform
# sampler would fill training with unsolvable islanding episodes. See MY_COMMITMENTS.md #7.
EDGE_TRIP_WEIGHTS: dict[str, float] = {
    "SSCO-NORT": 4.0,  # B6, the demo
    "YORK-MIDL": 2.0,
    "MIDL-LOND": 2.0,
    "MIDL-EAST": 1.5,
    "EAST-LOND": 1.5,
    "LOND-SOUT": 1.5,
    "NORT-YORK": 1.0,
    "WALE-MIDL": 1.0,
    "MIDL-SWES": 1.0,
    "SWES-SOUT": 0.8,
    "YORK-EAST": 0.8,
    "NORT-WALE": 0.8,
    "WALE-SWES": 0.5,
    "NSCO-SSCO": 0.3,  # islands North Scotland; kept low, not zero
}

INCIDENT_MIX = {
    "none": 0.20,
    "line_trip": 0.30,
    "generator_outage": 0.15,
    "wind_lull": 0.15,
    "demand_spike": 0.12,
    "interconnector_loss": 0.08,
}

STORAGE_EFFICIENCY = 0.90
UNSERVED_VALUE_GBP_PER_MWH = 6000.0  # value of lost load, for the cost line in info


def _turbine_output_frac(wind_ms: np.ndarray) -> np.ndarray:
    """Fraction of rated wind capacity at a given wind speed. Cut-in 3, rated 12, cut-out 25."""
    w = np.asarray(wind_ms, dtype=np.float64)
    out = np.clip((w - 3.0) / (12.0 - 3.0), 0.0, 1.0) ** 3
    return np.where(w > 25.0, 0.0, out)


class GridEnv(gym.Env):
    metadata = {"render_modes": [], "physics_version": PHYSICS_VERSION}

    def __init__(
        self,
        data_path: str | Path = DEFAULT_DATA,
        forecaster=None,
        scenario: list[S.Incident] | None = None,
        random_incidents: bool = True,
        start_utc: str | None = None,
    ):
        super().__init__()

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(S.N_ZONES, S.OBS_DIM), dtype=np.float32
        )
        self.action_space = spaces.Box(
            low=S.ACTION_LOW, high=S.ACTION_HIGH, shape=(S.N_ZONES, S.ACT_DIM), dtype=np.float32
        )

        self.forecaster = forecaster
        self.fixed_scenario = scenario
        self.start_utc = start_utc
        self.random_incidents = random_incidents

        self._load_data(Path(data_path))
        self._build_network()

        # Static per-zone arrays, in ZONE_ORDER.
        self.capacity = np.array(
            [[z.capacity_mw[f] for f in S.FUEL_ORDER] for z in S.ZONES], dtype=np.float64
        )
        self.fuel_cost = np.array([S.FUEL_COST[f] for f in S.FUEL_ORDER])
        self.fuel_carbon = np.array([S.FUEL_CARBON[f] for f in S.FUEL_ORDER])
        self.is_dispatchable = np.array([f in S.DISPATCHABLE for f in S.FUEL_ORDER])
        self.is_curtailable = np.array([f in S.CURTAILABLE for f in S.FUEL_ORDER])
        self.storage_mwh = np.array([z.storage_mwh for z in S.ZONES])
        self.storage_power = np.array([z.storage_power_mw for z in S.ZONES])
        self.dr_mw = np.array([z.dr_mw for z in S.ZONES])

        self.i_wind = S.FUEL_INDEX["WIND"]
        self.i_solar = S.FUEL_INDEX["SOLAR"]
        self.i_import = S.FUEL_INDEX["IMPORT"]

        self.step_idx = 0
        self._last_unserved = np.zeros(S.N_ZONES)

    # -- setup -------------------------------------------------------------

    def _load_data(self, path: Path) -> None:
        import pyarrow.parquet as pq

        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found. Run: python3 -I scripts/make_fake_canonical.py"
            )
        df = pq.read_table(path).to_pandas()
        df = df.sort_values(["zone_id", "timestamp_utc"])

        # Plain tz-aware datetimes, so this behaves the same across pandas versions.
        uniq = sorted(df["timestamp_utc"].unique())
        t_index = {t: i for i, t in enumerate(uniq)}
        self.times = [t.to_pydatetime() if hasattr(t, "to_pydatetime") else t for t in uniq]
        n_t = len(self.times)

        self.demand = np.full((n_t, S.N_ZONES), np.nan)
        self.temp = np.zeros((n_t, S.N_ZONES))
        self.wind = np.zeros((n_t, S.N_ZONES))
        self.solar = np.zeros((n_t, S.N_ZONES))

        for zid, g in df.groupby("zone_id", observed=True):
            if zid not in S.ZONE_INDEX:
                continue
            j = S.ZONE_INDEX[zid]
            rows = g["timestamp_utc"].map(t_index).to_numpy()
            self.demand[rows, j] = g["demand_mw"].to_numpy()
            self.temp[rows, j] = g["temp_c"].to_numpy()
            self.wind[rows, j] = g["wind_ms"].to_numpy()
            self.solar[rows, j] = g["solar_wm2"].to_numpy()

        # Flagged-missing demand is filled here only so the simulation can run; the forecaster
        # excludes those rows from scoring, which is a separate concern.
        for j in range(S.N_ZONES):
            col = self.demand[:, j]
            bad = np.isnan(col)
            if bad.any():
                col[bad] = np.interp(np.flatnonzero(bad), np.flatnonzero(~bad), col[~bad])

        self.n_t = n_t

    def _build_network(self) -> None:
        """Node-edge incidence matrix. Column e is +1 at its from-node, -1 at its to-node."""
        A = np.zeros((S.N_ZONES, S.N_EDGES))
        for e_i, e in enumerate(S.EDGES):
            A[S.ZONE_INDEX[e.frm], e_i] = 1.0
            A[S.ZONE_INDEX[e.to], e_i] = -1.0
        self.A = A
        self.base_limits = np.array([e.limit_mw for e in S.EDGES])
        self.circuits = np.array([e.circuits for e in S.EDGES])
        self.reactances = np.array([e.x_pu for e in S.EDGES])
        self._dc_cache: dict = {}

    # -- incidents ---------------------------------------------------------

    def _sample_incidents(self) -> list[S.Incident]:
        kinds = list(INCIDENT_MIX)
        probs = np.array([INCIDENT_MIX[k] for k in kinds])
        kind = self.np_random.choice(kinds, p=probs / probs.sum())
        if kind == "none":
            return []

        start = int(self.np_random.integers(8, 40))
        dur = int(self.np_random.integers(4, 20))

        if kind == "line_trip":
            eids = list(EDGE_TRIP_WEIGHTS)
            w = np.array([EDGE_TRIP_WEIGHTS[e] for e in eids])
            target = str(self.np_random.choice(eids, p=w / w.sum()))
            n_circ = S.EDGE_BY_ID[target].circuits
            mag = 1.0 / n_circ if n_circ > 1 else 1.0
            if n_circ > 1 and self.np_random.random() < 0.3:
                mag = 1.0  # occasionally lose the whole corridor
        elif kind == "wind_lull":
            target = str(self.np_random.choice(S.ZONE_ORDER))
            mag = float(self.np_random.uniform(0.1, 0.5))
        elif kind == "demand_spike":
            target = str(self.np_random.choice(S.ZONE_ORDER))
            mag = float(self.np_random.uniform(1.08, 1.25))
        elif kind == "generator_outage":
            target = str(self.np_random.choice(S.ZONE_ORDER))
            mag = float(self.np_random.uniform(0.4, 0.95))
        else:  # interconnector_loss
            with_import = [z.id for z in S.ZONES if z.capacity_mw["IMPORT"] > 0]
            target = str(self.np_random.choice(with_import))
            mag = float(self.np_random.uniform(0.5, 1.0))

        return [S.Incident(kind, target, start, dur, mag)]

    def _active(self, step: int) -> list[S.Incident]:
        return [i for i in self.incidents if i.active_at(step)]

    # -- observation -------------------------------------------------------

    def _forecast_block(self, t_i: int) -> tuple[np.ndarray, np.ndarray]:
        """P50 at +1/+2/+4/+8 and P90 at +1/+4, per zone.

        With a real forecaster attached this calls it. Without one it uses a naive forecast
        (same half-hour last week, falling back to persistence), which is deliberately weak but
        never zero -- a zeroed forecast slot trains a policy with no forward view and fails
        silently. See MY_COMMITMENTS.md #2.
        """
        p50 = np.zeros((S.N_ZONES, 4))
        p90 = np.zeros((S.N_ZONES, 2))

        if self.forecaster is not None:
            # The agent already observes demand at t_i, so the forecast is issued at t_i + 1:
            # history known through t_i, row 0 = the next half-hour = the "+1" slot. This keeps
            # the forecaster branch and the naive branch below on the same convention.
            issue = self.times[min(t_i + 1, self.n_t - 1)]
            fc = np.asarray(self.forecaster.predict_all(issue), dtype=np.float64)
            for k, lead in enumerate(S.OBS_FC_P50_LEADS):
                p50[:, k] = fc[:, min(lead - 1, S.FORECAST_HORIZON - 1), 1]
            for k, lead in enumerate(S.OBS_FC_P90_LEADS):
                p90[:, k] = fc[:, min(lead - 1, S.FORECAST_HORIZON - 1), 2]
            return p50, p90

        for k, lead in enumerate(S.OBS_FC_P50_LEADS):
            src = t_i + lead - 336
            p50[:, k] = self.demand[src] if src >= 0 else self.demand[t_i]
        for k, lead in enumerate(S.OBS_FC_P90_LEADS):
            src = t_i + lead - 336
            base = self.demand[src] if src >= 0 else self.demand[t_i]
            p90[:, k] = base * 1.08  # naive spread, replaced by the real P90
        return p50, p90

    def _observe(self) -> np.ndarray:
        t_i = self.t0 + self.step_idx
        ts = self.times[t_i]
        hh = ts.hour * 2 + (1 if ts.minute >= 30 else 0)

        obs = np.zeros((S.N_ZONES, S.OBS_DIM))
        obs[:, S.OBS_SIN_TOD] = np.sin(2 * np.pi * hh / 48.0)
        obs[:, S.OBS_COS_TOD] = np.cos(2 * np.pi * hh / 48.0)
        obs[:, S.OBS_IS_WEEKEND] = 1.0 if ts.weekday() >= 5 else 0.0

        demand = self._demand_now(t_i)
        obs[:, S.OBS_DEMAND_NOW] = demand / S.NORM_DEMAND_MW

        p50, p90 = self._forecast_block(t_i)
        obs[:, S.OBS_FC_P50 : S.OBS_FC_P50 + 4] = p50 / S.NORM_DEMAND_MW
        obs[:, S.OBS_FC_P90 : S.OBS_FC_P90 + 2] = p90 / S.NORM_DEMAND_MW

        avail = self._available(t_i)
        obs[:, S.OBS_CAP : S.OBS_CAP + S.N_FUELS] = avail / S.NORM_POWER_MW
        obs[:, S.OBS_OUT : S.OBS_OUT + S.N_FUELS] = self.output / S.NORM_POWER_MW

        obs[:, S.OBS_STORAGE_SOC] = self.soc
        obs[:, S.OBS_STORAGE_POWER] = self.storage_power / S.NORM_POWER_MW
        obs[:, S.OBS_DR_AVAIL] = self.dr_mw / S.NORM_POWER_MW
        obs[:, S.OBS_UNSERVED_LAST] = self._last_unserved / S.NORM_DEMAND_MW
        obs[:, S.OBS_NET_POSITION] = (self.output.sum(axis=1) - demand) / S.NORM_DEMAND_MW

        limits = self._limits(self.step_idx)
        net = self.output.sum(axis=1) - demand
        for j, zid in enumerate(S.ZONE_ORDER):
            for k, eid in enumerate(S.ADJACENT[zid]):
                e_i = S.EDGE_INDEX[eid]
                e = S.EDGES[e_i]
                # A live line reports the last interval's measured flow. An opened line carries
                # nothing, whatever it carried before it opened.
                opened = limits[e_i] <= 0
                signed = 0.0 if opened else self.flows[e_i] * (1.0 if e.frm == zid else -1.0)
                lim = max(limits[e_i], 1.0)
                obs[j, S.OBS_EDGE_FLOW + k] = signed / lim
                obs[j, S.OBS_EDGE_HEADROOM + k] = 0.0 if opened else 1.0 - min(abs(signed) / lim, 2.0)
                obs[j, S.OBS_EDGE_TRIPPED + k] = 1.0 if limits[e_i] < self.base_limits[e_i] else 0.0
                nbr = e.to if e.frm == zid else e.frm
                obs[j, S.OBS_NBR_NET + k] = net[S.ZONE_INDEX[nbr]] / S.NORM_DEMAND_MW

        national = (self.output.sum() - demand.sum()) / S.NORM_NATIONAL_MW
        obs[:, S.OBS_NATIONAL_MARGIN] = national

        return obs.astype(np.float32)

    # -- physics (stub) ----------------------------------------------------

    def _demand_now(self, t_i: int) -> np.ndarray:
        d = self.demand[t_i].copy()
        for inc in self._active(self.step_idx):
            if inc.type == "demand_spike":
                d[S.ZONE_INDEX[inc.target]] *= inc.magnitude
        return d

    def _available(self, t_i: int) -> np.ndarray:
        """Available capacity by zone and fuel, after weather and incidents."""
        avail = self.capacity.copy()
        avail[:, self.i_wind] *= _turbine_output_frac(self.wind[t_i])
        avail[:, self.i_solar] *= np.clip(self.solar[t_i] / 1000.0, 0.0, 1.0)

        for inc in self._active(self.step_idx):
            j = S.ZONE_INDEX.get(inc.target)
            if inc.type == "wind_lull" and j is not None:
                avail[j, self.i_wind] *= inc.magnitude
            elif inc.type == "generator_outage" and j is not None:
                avail[j, self.is_dispatchable] *= 1.0 - inc.magnitude
            elif inc.type == "interconnector_loss" and j is not None:
                avail[j, self.i_import] *= 1.0 - inc.magnitude
        return avail

    def _limits(self, step: int) -> np.ndarray:
        lim = self.base_limits.copy()
        for inc in self.incidents:
            if inc.type == "line_trip" and inc.active_at(step):
                e_i = S.EDGE_INDEX[inc.target]
                lim[e_i] *= max(0.0, 1.0 - inc.magnitude)
        return lim

    def _components(self, limits: np.ndarray) -> list[list[int]]:
        """Electrical islands. An edge whose limit has fallen to zero no longer connects."""
        live = [e_i for e_i in range(S.N_EDGES) if limits[e_i] > 0.0]
        nbrs: dict[int, list[int]] = {j: [] for j in range(S.N_ZONES)}
        for e_i in live:
            e = S.EDGES[e_i]
            a, b = S.ZONE_INDEX[e.frm], S.ZONE_INDEX[e.to]
            nbrs[a].append(b)
            nbrs[b].append(a)

        seen: set[int] = set()
        comps: list[list[int]] = []
        for j in range(S.N_ZONES):
            if j in seen:
                continue
            stack, comp = [j], []
            seen.add(j)
            while stack:
                n = stack.pop()
                comp.append(n)
                for m in nbrs[n]:
                    if m not in seen:
                        seen.add(m)
                        stack.append(m)
            comps.append(sorted(comp))
        return comps

    def _solve_flows(
        self, net: np.ndarray, limits: np.ndarray, demand: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """DC power flow per electrical island: B theta = P, then f = Bf theta.

        Susceptance scales with each corridor's surviving circuit fraction, so losing one of two
        circuits halves what the corridor attracts, not just its limit. Flow factors depend only
        on topology, so they are cached per set of limits.

        Each island balances itself before the solve. A shortage is shed across the island in
        proportion to demand; a surplus is spilled at the zones supplying it, in proportion to
        their output, so a zone that generates nothing never reports spill.

        Thermal limits are not enforced: physics does not respect them. Overloaded lines keep
        their flow and are penalised in the reward.

        Returns (flows, imbalance): negative imbalance is unserved demand, positive is spill.
        """
        key = tuple(np.asarray(limits, dtype=float))
        if key not in self._dc_cache:
            live_fraction = np.clip(limits / self.base_limits, 0.0, 1.0)
            susceptance = DC_BASE_MVA * live_fraction / self.reactances
            branch = (self.A * susceptance).T  # edges x zones
            bus = self.A @ branch  # zones x zones
            angle_map = np.zeros((S.N_ZONES, S.N_ZONES))
            components = [np.array(c) for c in self._components(limits)]
            for idx in components:
                ref = S.ZONE_INDEX[S.SLACK_ZONE]
                ref = ref if ref in idx else int(idx[0])
                rest = idx[idx != ref]
                if len(rest):
                    angle_map[np.ix_(rest, rest)] = np.linalg.inv(bus[np.ix_(rest, rest)])
            self._dc_cache[key] = (components, branch @ angle_map)
        components, transfer = self._dc_cache[key]

        imbalance = np.zeros(S.N_ZONES)
        for idx in components:
            surplus = float(net[idx].sum())
            if surplus > 0:
                w = np.maximum(net[idx] + demand[idx], 0.0)  # = generation in each zone
            else:
                w = np.maximum(demand[idx], 0.0)
            w = w / w.sum() if w.sum() > 0 else np.full(len(idx), 1.0 / len(idx))
            imbalance[idx] = surplus * w

        return transfer @ (net - imbalance), imbalance

    # -- gym API -----------------------------------------------------------

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.step_idx = 0
        self._step_detail = None

        max_start = max(1, self.n_t - S.STEPS_PER_EPISODE - 1)
        start = (options or {}).get("start_utc", self.start_utc)
        if start is not None:
            # A fixed episode start, for scripted demo scenarios. Must be a UTC midnight that
            # exists in the loaded table, with a full day of data after it.
            from datetime import datetime

            want = datetime.fromisoformat(str(start))
            matches = [i for i, t in enumerate(self.times) if t == want]
            if not matches:
                raise ValueError(f"start_utc {start} not found in the loaded data")
            if matches[0] > self.n_t - S.STEPS_PER_EPISODE:
                raise ValueError(f"start_utc {start} leaves less than one day of data")
            self.t0 = matches[0]
        else:
            self.t0 = int(self.np_random.integers(0, max_start))

        if self.fixed_scenario is not None:
            self.incidents = list(self.fixed_scenario)
        elif self.random_incidents:
            self.incidents = self._sample_incidents()
        else:
            self.incidents = []

        self.soc = np.full(S.N_ZONES, 0.5)
        self.output = np.zeros((S.N_ZONES, S.N_FUELS))
        self.flows = np.zeros(S.N_EDGES)
        self._last_unserved = np.zeros(S.N_ZONES)
        self.totals = {"unserved_mwh": 0.0, "cost_gbp": 0.0, "carbon_t": 0.0, "curtailed_mwh": 0.0}

        obs = self._observe()
        return obs, self._info()

    def step(self, action):
        a = np.clip(np.asarray(action, dtype=np.float64).reshape(S.N_ZONES, S.ACT_DIM), -1.0, 1.0)
        t_i = self.t0 + self.step_idx

        demand = self._demand_now(t_i)
        avail = self._available(t_i)

        # demand response reduces demand
        dr_called = np.array([S.unit_to_fraction(x) for x in a[:, S.ACT_DR]]) * self.dr_mw
        demand_net = np.maximum(demand - dr_called, 0.0)

        # dispatch: fraction of available capacity
        frac = np.array([[S.unit_to_fraction(x) for x in row] for row in a[:, :S.N_FUELS]])
        out = avail.copy()
        out[:, self.is_dispatchable] = (avail * frac)[:, self.is_dispatchable]

        # curtailment of renewables
        keep = 1.0 - np.array([S.unit_to_fraction(x) for x in a[:, S.ACT_CURTAIL]])
        pre = out[:, self.is_curtailable].sum(axis=1)
        out[:, self.is_curtailable] *= keep[:, None]
        curtailed_action = pre - out[:, self.is_curtailable].sum(axis=1)

        # storage, in MW over a half-hour
        s_cmd = a[:, S.ACT_STORAGE] * self.storage_power
        discharge_cap = self.soc * self.storage_mwh * 2.0 * STORAGE_EFFICIENCY
        charge_cap = (1.0 - self.soc) * self.storage_mwh * 2.0 / STORAGE_EFFICIENCY
        s_power = np.clip(s_cmd, -charge_cap, discharge_cap)

        # A battery cannot charge from power that does not exist. Where an island is short,
        # cancel commanded charging before any customer is shed.
        limits = self._limits(self.step_idx)
        for comp in self._components(limits):
            idx = np.array(comp)
            deficit = max(float((demand_net[idx] - out[idx].sum(axis=1) - s_power[idx]).sum()), 0.0)
            charging = np.maximum(-s_power[idx], 0.0)
            if deficit > 0 and charging.sum() > 0:
                s_power[idx] += charging * min(deficit / charging.sum(), 1.0)
        self.soc = np.clip(
            self.soc
            + np.where(s_power < 0, -s_power * STORAGE_EFFICIENCY, -s_power / STORAGE_EFFICIENCY)
            * 0.5
            / np.maximum(self.storage_mwh, 1.0),
            0.0,
            1.0,
        )

        self.output = out
        gen = out.sum(axis=1) + s_power
        net = gen - demand_net

        self.flows, imbalance = self._solve_flows(net, limits, demand_net)

        unserved_mw = np.maximum(-imbalance, 0.0)
        spill_mw = np.maximum(imbalance, 0.0)

        overload_mw = np.maximum(np.abs(self.flows) - limits, 0.0)

        energy = out * 0.5  # MWh in a half-hour
        cost = float((energy * self.fuel_cost).sum())
        carbon = float((energy * self.fuel_carbon).sum())
        curtailed_mwh = float((curtailed_action + spill_mw).sum() * 0.5)
        unserved_mwh = float(unserved_mw.sum() * 0.5)

        reward = -(
            S.W_UNSERVED * unserved_mwh
            + S.W_OVERLOAD * float(overload_mw.sum())
            + S.W_COST * cost / 1000.0
            + S.W_CARBON * carbon
            + S.W_CURTAIL * curtailed_mwh
        )

        self._last_unserved = unserved_mw
        self._step_detail = {
            "demand": demand,
            "demand_net": demand_net,
            "gen": gen,
            "unserved_mw": unserved_mw,
            "curtailed_mw": curtailed_action + spill_mw,
            "dr_called": dr_called,
            "cost_zone": (energy * self.fuel_cost).sum(axis=1),
            "carbon_zone": (energy * self.fuel_carbon).sum(axis=1),
            "limits": limits,
            "overload_mw": overload_mw,
        }

        self.totals["unserved_mwh"] += unserved_mwh
        self.totals["cost_gbp"] += cost + unserved_mwh * UNSERVED_VALUE_GBP_PER_MWH
        self.totals["carbon_t"] += carbon
        self.totals["curtailed_mwh"] += curtailed_mwh

        self.step_idx += 1
        terminated = self.step_idx >= S.STEPS_PER_EPISODE
        truncated = False

        obs = self._observe() if not terminated else self._observe()
        return obs, float(reward), terminated, truncated, self._info()

    # -- info --------------------------------------------------------------

    def _info(self) -> dict:
        t_i = self.t0 + min(self.step_idx, self.n_t - self.t0 - 1)
        d = getattr(self, "_step_detail", None)
        # Topology at decision time (what the agent acts on next); flow is the last interval's
        # measurement on a live line and zero on an opened one.
        limits = self._limits(self.step_idx)

        zones = {}
        for j, zid in enumerate(S.ZONE_ORDER):
            zones[zid] = {
                "demand_mw": float(d["demand"][j]) if d else float(self.demand[t_i, j]),
                "generation_mw": float(d["gen"][j]) if d else 0.0,
                "unserved_mw": float(d["unserved_mw"][j]) if d else 0.0,
                "cost_gbp": float(d["cost_zone"][j]) if d else 0.0,
                "carbon_t": float(d["carbon_zone"][j]) if d else 0.0,
                "curtailed_mw": float(d["curtailed_mw"][j]) if d else 0.0,
                "storage_soc": float(self.soc[j]),
                "dr_called_mw": float(d["dr_called"][j]) if d else 0.0,
            }

        edges = {}
        for e_i, e in enumerate(S.EDGES):
            lim = float(limits[e_i])
            flow = float(self.flows[e_i]) if lim > 0 else 0.0
            edges[e.id] = {
                "flow_mw": flow,
                "limit_mw": lim,
                "loading_frac": abs(flow) / lim if lim > 0 else 0.0,
                "tripped": bool(lim < self.base_limits[e_i]),
            }

        return {
            "timestamp_utc": self.times[t_i].isoformat(),
            "zones": zones,
            "edges": edges,
            "totals": dict(self.totals),
            "incidents": [i.to_dict() for i in self._active(max(0, self.step_idx - 1))],
        }


def load_scenario(name: str) -> list[S.Incident]:
    """Read scenarios/<name>.json into a list of Incidents."""
    import json

    path = Path(S.SCENARIO_DIR) / f"{name}.json"
    data = json.loads(path.read_text())
    return [S.Incident.from_dict(d) for d in data["incidents"]]


def make_scenario_env(name: str, **kwargs) -> "GridEnv":
    """A GridEnv set up to replay one scripted scenario exactly.

    Uses the scenario file's incidents, and its episode_start_utc and selected_from data file
    when present, so the demo starts from the selected real-world conditions every time.
    """
    import json

    data = json.loads((Path(S.SCENARIO_DIR) / f"{name}.json").read_text())
    kwargs.setdefault("data_path", data.get("selected_from", DEFAULT_DATA))
    kwargs.setdefault("start_utc", data.get("episode_start_utc"))
    return GridEnv(scenario=load_scenario(name), **kwargs)

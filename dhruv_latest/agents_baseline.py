"""Baseline agents: the "none" and "optimiser" strategies.

STATUS: NoOpAgent is final. OptimiserAgent is a merit-order heuristic for now; the LP version
lands at hour 14. Both expose the same interface, so one eval loop drives all three strategies.

    import agents_baseline
    noop = agents_baseline.NoOpAgent()
    opt  = agents_baseline.OptimiserAgent()
    action = opt.act(obs, info)          # (10, 52) + info -> (10, 11), every element in [-1, 1]
"""

from __future__ import annotations

import numpy as np

import schemas as S


def _blank_action() -> np.ndarray:
    """All dispatch off, no storage, no demand response, no curtailment."""
    a = np.zeros((S.N_ZONES, S.ACT_DIM), dtype=np.float32)
    a[:, : S.N_FUELS] = -1.0  # dispatch fraction 0
    a[:, S.ACT_STORAGE] = 0.0
    a[:, S.ACT_DR] = -1.0  # call no demand response
    a[:, S.ACT_CURTAIL] = -1.0  # curtail nothing
    return a


class Agent:
    name = "agent"

    def act(self, obs: np.ndarray, info: dict) -> np.ndarray:
        raise NotImplementedError

    def reset(self) -> None:
        pass


def _merit_order() -> list[tuple[int, int]]:
    """(zone, fuel) pairs sorted cheapest first, across the whole system."""
    pairs = [
        (j, f_i)
        for j in range(S.N_ZONES)
        for f_i, f in enumerate(S.FUEL_ORDER)
        if f in S.DISPATCHABLE
    ]
    return sorted(pairs, key=lambda p: S.FUEL_COST[S.FUEL_ORDER[p[1]]])


def _dispatch_national(
    a: np.ndarray,
    need: float,
    avail: np.ndarray,
    merit: list[tuple[int, int]],
    zones: set[int] | None = None,
) -> float:
    """Fill `need` MW from the cheapest available plant, optionally restricted to `zones`.

    Returns MW left unmet.
    """
    for j, f_i in merit:
        if need <= 0:
            break
        if zones is not None and j not in zones:
            continue
        cap = float(avail[j, f_i])
        if cap <= 0:
            continue
        take = min(need, cap)
        frac = take / cap
        a[j, S.ACT_DISPATCH + f_i] = frac * 2.0 - 1.0
        need -= take
    return max(need, 0.0)


def _islands(info: dict) -> list[list[int]]:
    """Electrical islands implied by info's edge limits. An edge at zero limit is dead."""
    edges = info.get("edges") or {}
    nbrs: dict[int, list[int]] = {j: [] for j in range(S.N_ZONES)}
    for e in S.EDGES:
        d = edges.get(e.id)
        if d is not None and d["limit_mw"] <= 0:
            continue
        x, y = S.ZONE_INDEX[e.frm], S.ZONE_INDEX[e.to]
        nbrs[x].append(y)
        nbrs[y].append(x)

    seen: set[int] = set()
    out: list[list[int]] = []
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
        out.append(sorted(comp))
    return out


class NoOpAgent(Agent):
    """The "none" strategy: economic dispatch that is blind to the network.

    This is not "do literally nothing" -- a grid with every generator off is a blackout, and the
    comparison would be meaningless. It does what a market does with no network awareness: meet
    national demand from the cheapest plant anywhere, then ignore everything that happens. No
    storage, no demand response, no curtailment, no reaction to a tripped line.

    Dispatching nationally rather than per zone matters. Several zones -- LOND especially -- have
    less dispatchable capacity than their own demand and must import. A per-zone balance would
    under-generate nationally and show phantom unserved energy before any incident occurred.
    """

    name = "none"

    def __init__(self) -> None:
        self.merit = _merit_order()
        self.dispatchable = np.array([f in S.DISPATCHABLE for f in S.FUEL_ORDER])

    def act(self, obs: np.ndarray, info: dict) -> np.ndarray:
        a = _blank_action()
        demand = obs[:, S.OBS_DEMAND_NOW] * S.NORM_DEMAND_MW
        avail = obs[:, S.OBS_CAP : S.OBS_CAP + S.N_FUELS] * S.NORM_POWER_MW

        must_run = float(avail[:, ~self.dispatchable].sum())
        need = max(float(demand.sum()) - must_run, 0.0)
        _dispatch_national(a, need, avail, self.merit)
        return a


class OptimiserAgent(Agent):
    """The "optimiser" strategy: least-cost dispatch that does respond to the network.

    Hour-2 version is a merit-order heuristic with three reactions the NoOp agent lacks:
      - it dispatches against the forecast, not just present demand, so it pre-positions
      - it discharges storage and calls demand response where a zone is short or its lines
        are loaded
      - it curtails renewables where the local export corridor is saturated

    The LP version (scipy.optimize.linprog, minimising cost subject to nodal balance and line
    limits) replaces the body of act() at hour 14. The interface does not change.
    """

    name = "optimiser"

    def __init__(self, congestion_trigger: float = 0.90, damping: float = 0.5) -> None:
        self.merit = _merit_order()
        self.dispatchable = np.array([f in S.DISPATCHABLE for f in S.FUEL_ORDER])
        self.curtailable = np.array([f in S.CURTAILABLE for f in S.FUEL_ORDER])
        self.congestion_trigger = congestion_trigger
        self.damping = damping

    def _pressures(self, info: dict) -> tuple[np.ndarray, np.ndarray]:
        """Per-zone export and import pressure in MW, from the real limits in info.

        Positive export pressure is MW this zone is pushing beyond an adjacent limit. Positive
        import pressure is MW it is drawing beyond one. Taken from info rather than decoded from
        the observation, because info carries the actual MW limits after any trip.
        """
        export = np.zeros(S.N_ZONES)
        imp = np.zeros(S.N_ZONES)
        edges = info.get("edges") or {}
        for j, zid in enumerate(S.ZONE_ORDER):
            for eid in S.ADJACENT[zid]:
                e = S.EDGE_BY_ID[eid]
                d = edges.get(eid)
                if not d:
                    continue
                lim = d["limit_mw"]
                signed = d["flow_mw"] * (1.0 if e.frm == zid else -1.0)
                if lim <= 0:
                    continue
                export[j] = max(export[j], signed - self.congestion_trigger * lim)
                imp[j] = max(imp[j], -signed - self.congestion_trigger * lim)
        return export, imp

    def act(self, obs: np.ndarray, info: dict) -> np.ndarray:
        a = _blank_action()

        demand = obs[:, S.OBS_DEMAND_NOW] * S.NORM_DEMAND_MW
        fc_ahead = obs[:, S.OBS_FC_P50 + 2] * S.NORM_DEMAND_MW  # +4 half-hours
        avail = obs[:, S.OBS_CAP : S.OBS_CAP + S.N_FUELS] * S.NORM_POWER_MW
        soc = obs[:, S.OBS_STORAGE_SOC]

        export_mw, import_mw = self._pressures(info)
        must_run_z = avail[:, ~self.dispatchable].sum(axis=1)
        curtailable_z = avail[:, self.curtailable].sum(axis=1)

        # 1. Curtail first, and only the MW actually stuck behind an over-limit corridor.
        #    Damped, because this reacts to last step's flows and an undamped response
        #    oscillates. Curtailment must be computed BEFORE the dispatch need, or the
        #    reduction in must-run output is never made up and shows as unserved energy.
        curtail_mw = np.zeros(S.N_ZONES)
        for j in np.flatnonzero(export_mw > 0):
            if curtailable_z[j] <= 0:
                continue
            curtail_mw[j] = min(self.damping * float(export_mw[j]), float(curtailable_z[j]))
            a[j, S.ACT_CURTAIL] = (curtail_mw[j] / curtailable_z[j]) * 2.0 - 1.0

        # 2. Local storage and demand response where power is drawn across a constrained
        #    corridor. These sit on the right side of the bottleneck, which remote plant does
        #    not. Relief is bounded by actual state of charge, never by nameplate.
        for j in np.flatnonzero(import_mw > 0):
            if fc_ahead[j] > demand[j] * 1.10 and soc[j] < 0.5:
                continue  # hold the battery for a bigger peak within two hours
            a[j, S.ACT_STORAGE] = 1.0
            a[j, S.ACT_DR] = 0.2

        # 3. Dispatch each electrical island to meet its own demand. This is the difference that
        #    matters: a network-blind merit order will happily dispatch Scottish plant to serve
        #    London, and when the boundary is out that power cannot get there, so the south goes
        #    short while the north spills. Balancing per island is what turns the response into
        #    an actual saving rather than just a smaller overload.
        #    No reserve: surplus has nowhere to go and simply spills.
        def rank(p: tuple[int, int]) -> tuple[int, float]:
            j, f_i = p
            tier = 1 if import_mw[j] > 0 else (3 if export_mw[j] > 0 else 2)
            return (tier, S.FUEL_COST[S.FUEL_ORDER[f_i]])

        merit = sorted(self.merit, key=rank)
        relief_z = np.zeros(S.N_ZONES)
        for j in np.flatnonzero(a[:, S.ACT_STORAGE] > 0.5):
            z = S.ZONES[j]
            relief_z[j] = min(z.storage_power_mw, float(soc[j]) * z.storage_mwh * 2.0) + 0.6 * z.dr_mw

        for comp in _islands(info):
            idx = np.array(comp)
            need = max(
                float(demand[idx].sum())
                - float(must_run_z[idx].sum() - curtail_mw[idx].sum())
                - float(relief_z[idx].sum()),
                0.0,
            )
            _dispatch_national(a, need, avail, merit, zones=set(comp))

        return np.clip(a, S.ACTION_LOW, S.ACTION_HIGH).astype(np.float32)


class PolicyAgent(Agent):
    """Wraps a trained SB3 policy so it has the same interface as the baselines."""

    name = "agents"

    def __init__(self, model, vec_normalize=None):
        self.model = model
        self.vec_normalize = vec_normalize

    def act(self, obs: np.ndarray, info: dict) -> np.ndarray:
        # SB3 handles the (10, 52) Box natively -- do NOT flatten, it raises.
        o = np.asarray(obs, dtype=np.float32)
        if self.vec_normalize is not None:
            o = self.vec_normalize.normalize_obs(o)
        action, _ = self.model.predict(o, deterministic=True)
        return np.asarray(action, dtype=np.float32).reshape(S.N_ZONES, S.ACT_DIM)


AGENTS = {"none": NoOpAgent, "optimiser": OptimiserAgent}

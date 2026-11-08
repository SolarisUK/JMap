"""Baseline agents: the "none" and "optimiser" strategies.

NoOpAgent is the network-blind market baseline. OptimiserAgent solves a receding-horizon
DC optimal-dispatch LP. Both expose the same interface for paired evaluation.

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
    """Receding-horizon least-cost DC dispatch with physical storage state.

    The next four hours interpolate the P50 observation leads; only the first action is
    executed, then the LP is rebuilt from the next observation. Future plant availability
    and topology persist at their currently observed values, not an invented weather feed.
    The objective uses the simulator's prices: fuel + carbon (£67/t), DR (£300/MWh), curtailment (£70/MWh), VoLL.

    Firm must-run spill is an expensive emergency variable, not a freely dispatchable fuel.
    If capacity is insufficient, planned nodal shedding is diagnostic: the simulator applies
    its documented proportional island shedding and may produce different congested flows.
    """

    name = S.STRATEGIES[1]
    version = "dc-lp-v2"

    def __init__(self, congestion_trigger: float = 0.90, damping: float = 0.5) -> None:
        # Keep the former optional constructor arguments compatible with existing callers.
        from grid_env import DC_BASE_MVA, STORAGE_EFFICIENCY
        self.base_mva = DC_BASE_MVA
        self.efficiency = STORAGE_EFFICIENCY
        self.value_of_lost_load = S.PRICE_VOLL_GBP_PER_MWH
        self.pairs = _merit_order()
        self.dispatchable = np.array([f in S.DISPATCHABLE for f in S.FUEL_ORDER])
        self.curtailable = np.array([f in S.CURTAILABLE for f in S.FUEL_ORDER])
        self.incidence = np.zeros((S.N_ZONES, S.N_EDGES))
        for e_i, edge in enumerate(S.EDGES):
            self.incidence[S.ZONE_INDEX[edge.frm], e_i] = 1
            self.incidence[S.ZONE_INDEX[edge.to], e_i] = -1
        self.last_plan = None

    def reset(self):
        self.last_plan = None

    def act(self, obs: np.ndarray, info: dict) -> np.ndarray:
        from scipy.optimize import linprog
        from scipy.sparse import lil_matrix

        S.validate_obs(obs)
        obs = np.asarray(obs, dtype=float)
        if not np.isfinite(obs).all():
            raise ValueError("LP dispatch requires finite observations")
        actual = np.maximum(obs[:, S.OBS_DEMAND_NOW] * S.NORM_DEMAND_MW, 0)
        available = np.maximum(obs[:, S.OBS_CAP:S.OBS_CAP + S.N_FUELS] * S.NORM_POWER_MW, 0)
        power = np.maximum(obs[:, S.OBS_STORAGE_POWER] * S.NORM_POWER_MW, 0)
        capacity = np.array([zone.storage_mwh for zone in S.ZONES])
        initial_energy = np.clip(obs[:, S.OBS_STORAGE_SOC], 0, 1) * capacity
        dr_capacity = np.minimum(np.maximum(obs[:, S.OBS_DR_AVAIL] * S.NORM_POWER_MW, 0),
                                 np.array([zone.dr_mw for zone in S.ZONES]))
        must_run = available[:, ~self.dispatchable].sum(axis=1)
        renewable = available[:, self.curtailable].sum(axis=1)
        firm = must_run - renewable
        limits = np.array([max(0, (info.get("edges") or {}).get(edge.id, {}).get("limit_mw", edge.limit_mw))
                           for edge in S.EDGES])
        fractions = np.clip(limits / np.array([edge.limit_mw for edge in S.EDGES]), 0, 1)
        susceptance = self.base_mva * fractions / np.array([edge.x_pu for edge in S.EDGES])
        branch = (self.incidence * susceptance).T
        bus = self.incidence @ branch

        leads = np.array(S.OBS_FC_P50_LEADS) - 1
        periods = int(leads.max() + 1)
        forecast = obs[:, S.OBS_FC_P50:S.OBS_FC_P50 + len(leads)] * S.NORM_DEMAND_MW
        demand = np.column_stack([np.maximum(np.interp(np.arange(periods), leads, row), 0) for row in forecast])
        demand[0] = actual
        dt = 24 / S.HALF_HOURS_PER_DAY
        n_gen = len(self.pairs)
        # Per period: plant output, renewable curtailment, discharge, charge, DR,
        # unserved load, firm spill, phase angles, and end-of-interval stored energy.
        curtail, discharge, charge, dr, shed, spill, theta, energy = [n_gen + k * S.N_ZONES for k in range(8)]
        width = n_gen + 8 * S.N_ZONES
        variables = periods * width
        equality = lil_matrix((periods * 2 * S.N_ZONES, variables))
        rhs = np.zeros(periods * 2 * S.N_ZONES)
        inequality = lil_matrix((periods * (2 * S.N_EDGES + S.N_ZONES), variables))
        upper = np.zeros(inequality.shape[0])
        objective = np.zeros(variables)
        bounds = []
        references = {component[0] for component in _islands(info)}
        for component in _islands(info):
            if S.ZONE_INDEX[S.SLACK_ZONE] in component:
                references.discard(component[0])
                references.add(S.ZONE_INDEX[S.SLACK_ZONE])
        for t in range(periods):
            offset = t * width
            nodal = t * 2 * S.N_ZONES
            storage = nodal + S.N_ZONES
            for k, (j, f_i) in enumerate(self.pairs):
                equality[nodal + j, offset + k] = 1
                fuel = S.FUEL_ORDER[f_i]
                objective[offset + k] = dt * (S.FUEL_COST[fuel] + S.PRICE_CARBON_GBP_PER_T * S.FUEL_CARBON[fuel])
                bounds.append((0, float(available[j, f_i])))
            for k, sign in ((curtail, -1), (discharge, 1), (charge, -1), (dr, 1), (shed, 1), (spill, -1)):
                equality[nodal:nodal + S.N_ZONES, offset + k:offset + k + S.N_ZONES] = np.eye(S.N_ZONES) * sign
            equality[nodal:nodal + S.N_ZONES, offset + theta:offset + theta + S.N_ZONES] = -bus
            rhs[nodal:nodal + S.N_ZONES] = demand[t] - must_run
            equality[storage:storage + S.N_ZONES, offset + energy:offset + energy + S.N_ZONES] = np.eye(S.N_ZONES)
            equality[storage:storage + S.N_ZONES, offset + discharge:offset + discharge + S.N_ZONES] = np.eye(S.N_ZONES) * dt / self.efficiency
            equality[storage:storage + S.N_ZONES, offset + charge:offset + charge + S.N_ZONES] = -np.eye(S.N_ZONES) * dt * self.efficiency
            if t:
                equality[storage:storage + S.N_ZONES, offset - width + energy:offset - width + energy + S.N_ZONES] = -np.eye(S.N_ZONES)
            else:
                rhs[storage:storage + S.N_ZONES] = initial_energy
            objective[offset + shed:offset + shed + S.N_ZONES] = dt * self.value_of_lost_load
            objective[offset + spill:offset + spill + S.N_ZONES] = dt * self.value_of_lost_load
            objective[offset + dr:offset + dr + S.N_ZONES] = dt * S.PRICE_DR_GBP_PER_MWH
            objective[offset + curtail:offset + curtail + S.N_ZONES] = dt * S.PRICE_CURTAIL_GBP_PER_MWH
            for caps in (renewable, power, power, np.minimum(dr_capacity, demand[t]), demand[t], firm):
                bounds.extend((0, float(cap)) for cap in caps)
            bounds.extend((0, 0) if j in references else (None, None) for j in range(S.N_ZONES))
            bounds.extend((0, float(cap)) for cap in capacity)
            row = t * (2 * S.N_EDGES + S.N_ZONES)
            inequality[row:row + S.N_EDGES, offset + theta:offset + theta + S.N_ZONES] = branch
            inequality[row + S.N_EDGES:row + 2 * S.N_EDGES, offset + theta:offset + theta + S.N_ZONES] = -branch
            upper[row:row + 2 * S.N_EDGES] = np.tile(limits, 2)
            inequality[row + 2 * S.N_EDGES:row + 2 * S.N_EDGES + S.N_ZONES, offset + discharge:offset + discharge + S.N_ZONES] = np.eye(S.N_ZONES)
            inequality[row + 2 * S.N_EDGES:row + 2 * S.N_EDGES + S.N_ZONES, offset + charge:offset + charge + S.N_ZONES] = np.eye(S.N_ZONES)
            upper[row + 2 * S.N_EDGES:row + 2 * S.N_EDGES + S.N_ZONES] = power

        # Retain energy at the forecast's marginal replacement value, rather than treating
        # the initial battery inventory as free fuel that should always be emptied now.
        need = max(float(demand[-1].sum() - must_run.sum() - dr_capacity.sum()), 0)
        marginal = 0.0
        for j, f_i in self.pairs:
            if need <= 0:
                break
            if available[j, f_i] > 0:
                marginal = S.FUEL_COST[S.FUEL_ORDER[f_i]]
                need -= float(available[j, f_i])
        final_energy = (periods - 1) * width + energy
        objective[final_energy:final_energy + S.N_ZONES] = -self.efficiency * marginal
        equality, inequality = equality.tocsr(), inequality.tocsr()
        solution = linprog(objective, A_ub=inequality, b_ub=upper, A_eq=equality, b_eq=rhs,
                           bounds=bounds, method="highs")
        if not solution.success:
            raise RuntimeError(f"DC dispatch LP failed: {solution.message}")
        plan = solution.x.reshape(periods, width)
        if np.any((plan[:, discharge:discharge + S.N_ZONES] > 1e-7) &
                  (plan[:, charge:charge + S.N_ZONES] > 1e-7)):
            # Fix each battery's direction and resolve: a physical converter cannot charge
            # and discharge simultaneously just to dissipate a must-run surplus.
            for t in range(periods):
                for j in range(S.N_ZONES):
                    fix = charge if plan[t, discharge + j] >= plan[t, charge + j] else discharge
                    bounds[t * width + fix + j] = (0, 0)
            solution = linprog(objective, A_ub=inequality, b_ub=upper, A_eq=equality, b_eq=rhs,
                               bounds=bounds, method="highs")
            if not solution.success:
                raise RuntimeError(f"Physical battery direction LP failed: {solution.message}")
            plan = solution.x.reshape(periods, width)
        current = plan[0]
        action = _blank_action()
        for k, (j, f_i) in enumerate(self.pairs):
            if available[j, f_i] > 0:
                action[j, S.ACT_DISPATCH + f_i] = 2 * current[k] / available[j, f_i] - 1
        action[:, S.ACT_STORAGE] = np.divide(current[discharge:discharge + S.N_ZONES] - current[charge:charge + S.N_ZONES],
                                             power, out=np.zeros(S.N_ZONES), where=power > 0)
        action[:, S.ACT_DR] = 2 * np.divide(current[dr:dr + S.N_ZONES], dr_capacity,
                                          out=np.zeros(S.N_ZONES), where=dr_capacity > 0) - 1
        action[:, S.ACT_CURTAIL] = 2 * np.divide(current[curtail:curtail + S.N_ZONES], renewable,
                                               out=np.zeros(S.N_ZONES), where=renewable > 0) - 1
        self.last_plan = {"success": True, "objective": float(solution.fun),
                          "unserved_mw": current[shed:shed + S.N_ZONES].copy(),
                          "spill_mw": current[spill:spill + S.N_ZONES].copy(),
                          "flows_mw": branch @ current[theta:theta + S.N_ZONES],
                          "energy_mwh": plan[:, energy:energy + S.N_ZONES].copy()}
        return np.clip(action, S.ACTION_LOW, S.ACTION_HIGH).astype(np.float32)


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

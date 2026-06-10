"""CP-SAT optimization model: joint berth allocation, tank assignment and
sequencing for incoming vessels.

Decision variables
    x[v, b]  vessel v moors at berth b              (Boolean)
    y[v, k]  vessel v is served from tank k         (Boolean)
    s[v]     pumping start time of vessel v         (integer, minutes)

Hard constraints
    - every vessel gets exactly one berth and one tank
    - a tank is committed to at most one vessel in the window
    - berth/vessel size compatibility, tank/product compatibility
    - no two vessels overlap on the same berth
    - no vessel starts before its ETA, nor before tank cleaning finishes

Objective
    minimize  demurrage (waiting cost) + tank cleaning cost
"""
from __future__ import annotations

from ortools.sat.python import cp_model

from .data import Scenario, service_minutes, tank_options


def _entry(vessel, berth, tank, needs_clean, start):
    end = start + service_minutes(vessel, berth)
    wait = start - vessel.eta_min
    return {
        "vessel": vessel.name,
        "size": vessel.size,
        "op": vessel.operation,
        "product": vessel.product.name,
        "color": vessel.product.color,
        "volume": vessel.volume,
        "berth": berth.name,
        "tank": tank.name,
        "clean": needs_clean,
        "clean_cost": tank.clean_cost if needs_clean else 0.0,
        "eta": vessel.eta_min,
        "start": start,
        "end": end,
        "service": end - start,
        "wait": wait,
        "demurrage": wait * vessel.demurrage_day / (24 * 60),
    }


def solve(scenario: Scenario, time_limit_s: float = 10.0) -> dict:
    m = cp_model.CpModel()
    horizon = scenario.horizon_min * 2  # soft horizon: plans may run past the window
    vessels, berths, tanks = scenario.vessels, scenario.berths, scenario.tanks

    feasible_tanks = {
        v.name: [(t, clean) for t in tanks for ok, clean in [tank_options(v, t)] if ok]
        for v in vessels
    }
    if any(not opts for opts in feasible_tanks.values()):
        return {"status": "NO_COMPATIBLE_TANK", "entries": []}

    start = {}        # master start time per vessel
    x = {}            # (vessel, berth) -> presence literal
    y = {}            # (vessel, tank) -> assignment literal
    berth_ivs = {b.name: [] for b in berths}
    obj_terms = []

    for v in vessels:
        s_v = m.NewIntVar(v.eta_min, horizon, f"start_{v.name}")
        start[v.name] = s_v

        lits = []
        for b in berths:
            if not b.fits(v):
                continue
            dur = service_minutes(v, b)
            pres = m.NewBoolVar(f"x_{v.name}_{b.name}")
            s_vb = m.NewIntVar(v.eta_min, horizon, f"s_{v.name}_{b.name}")
            e_vb = m.NewIntVar(0, horizon + dur, f"e_{v.name}_{b.name}")
            iv = m.NewOptionalIntervalVar(s_vb, dur, e_vb, pres, f"iv_{v.name}_{b.name}")
            m.Add(s_v == s_vb).OnlyEnforceIf(pres)
            berth_ivs[b.name].append(iv)
            x[v.name, b.name] = pres
            lits.append(pres)
        m.AddExactlyOne(lits)

        tank_lits = []
        for t, needs_clean in feasible_tanks[v.name]:
            lit = m.NewBoolVar(f"y_{v.name}_{t.name}")
            y[v.name, t.name] = lit
            tank_lits.append(lit)
            if needs_clean:
                # Cleaning starts at t=0; pumping cannot start before it is done.
                m.Add(s_v >= t.clean_hours * 60).OnlyEnforceIf(lit)
                obj_terms.append(lit * int(t.clean_cost * 100))
        m.AddExactlyOne(tank_lits)

        wait = m.NewIntVar(0, horizon, f"wait_{v.name}")
        m.Add(wait == s_v - v.eta_min)
        cents_per_min = int(round(v.demurrage_day * 100 / (24 * 60)))
        obj_terms.append(wait * cents_per_min)

    for t in tanks:
        lits = [y[v.name, t.name] for v in vessels if (v.name, t.name) in y]
        if len(lits) > 1:
            m.AddAtMostOne(lits)

    for b in berths:
        m.AddNoOverlap(berth_ivs[b.name])

    m.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = 8
    status = solver.Solve(m)
    status_name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"status": status_name, "entries": []}

    entries = []
    for v in vessels:
        berth = next(b for b in berths if (v.name, b.name) in x
                     and solver.Value(x[v.name, b.name]))
        tank, needs_clean = next(
            (t, clean) for t, clean in feasible_tanks[v.name]
            if solver.Value(y[v.name, t.name])
        )
        entries.append(_entry(v, berth, tank, needs_clean, solver.Value(start[v.name])))

    return {
        "status": status_name,
        "entries": entries,
        "objective_eur": solver.ObjectiveValue() / 100,
        "wall_time_s": solver.WallTime(),
        "branches": solver.NumBranches(),
        "conflicts": solver.NumConflicts(),
    }

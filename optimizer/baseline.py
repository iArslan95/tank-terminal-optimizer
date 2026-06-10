"""First-come-first-served baseline: what a sensible planner without an
optimizer would do. Vessels are handled strictly in ETA order; each takes the
berth where it can start earliest. Tank choice prefers no-cleaning options,
with backtracking only to guarantee everyone gets *a* tank.

This is the benchmark the CP-SAT plan is compared against.
"""
from __future__ import annotations

from .data import Scenario, service_minutes, tank_options
from .model import _entry


def _tank_matching(scenario: Scenario):
    """Feasible vessel->tank matching, greedily preferring cheap/no-clean tanks."""
    options = {}
    for v in scenario.vessels:
        opts = []
        for t in scenario.tanks:
            ok, clean = tank_options(v, t)
            if ok:
                opts.append((t, clean))
        opts.sort(key=lambda tc: (tc[1], tc[0].clean_cost if tc[1] else 0.0))
        options[v.name] = opts

    order = sorted(scenario.vessels, key=lambda v: len(options[v.name]))
    assignment = {}

    def assign(i, used):
        if i == len(order):
            return True
        v = order[i]
        for t, clean in options[v.name]:
            if t.name in used:
                continue
            assignment[v.name] = (t, clean)
            used.add(t.name)
            if assign(i + 1, used):
                return True
            used.remove(t.name)
            del assignment[v.name]
        return False

    if not assign(0, set()):
        return None
    return assignment


def fcfs(scenario: Scenario) -> dict:
    matching = _tank_matching(scenario)
    if matching is None:
        return {"status": "NO_FEASIBLE_MATCHING", "entries": []}

    berth_free = {b.name: 0 for b in scenario.berths}
    entries = []
    for v in sorted(scenario.vessels, key=lambda v: v.eta_min):
        tank, needs_clean = matching[v.name]
        ready = tank.clean_hours * 60 if needs_clean else 0
        best = None
        for b in scenario.berths:
            if not b.fits(v):
                continue
            s = max(v.eta_min, ready, berth_free[b.name])
            key = (s, service_minutes(v, b))
            if best is None or key < best[0]:
                best = (key, b, s)
        _, berth, s = best
        berth_free[berth.name] = s + service_minutes(v, berth)
        entries.append(_entry(v, berth, tank, needs_clean, s))

    return {"status": "FCFS", "entries": entries}

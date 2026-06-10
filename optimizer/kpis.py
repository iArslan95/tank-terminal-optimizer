"""Shared KPI computation so the optimized plan and the FCFS baseline are
scored with exactly the same yardstick."""
from __future__ import annotations

from .data import Scenario


def compute(entries, scenario: Scenario) -> dict:
    if not entries:
        return {
            "wait_h": 0.0, "demurrage": 0.0, "cleaning": 0.0, "total": 0.0,
            "makespan_h": 0.0, "utilization": 0.0, "n_clean": 0,
        }
    wait_min = sum(e["wait"] for e in entries)
    demurrage = sum(e["demurrage"] for e in entries)
    cleaning = sum(e["clean_cost"] for e in entries)
    makespan = max(e["end"] for e in entries)
    busy = sum(e["service"] for e in entries)
    return {
        "wait_h": wait_min / 60,
        "demurrage": demurrage,
        "cleaning": cleaning,
        "total": demurrage + cleaning,
        "makespan_h": makespan / 60,
        "utilization": busy / (len(scenario.berths) * makespan) if makespan else 0.0,
        "n_clean": sum(1 for e in entries if e["clean"]),
    }

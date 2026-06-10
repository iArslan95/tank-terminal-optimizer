"""Smoke test: generate scenarios across seeds, solve with CP-SAT and the
FCFS baseline, and report the savings gap. Run from the project root:

    python scripts/selftest.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from optimizer import baseline, data, kpis, model  # noqa: E402

HEADER = (
    f"{'seed':>4} {'status':<8} {'waitFCFS':>9} {'waitOPT':>8} "
    f"{'eurFCFS':>10} {'eurOPT':>10} {'saved':>9} {'clF/clO':>7} "
    f"{'replanSav':>10} {'sec':>5}"
)


def main():
    print(HEADER)
    failures = 0
    for seed in range(1, 13):
        scenario = data.generate(seed, n_vessels=10, n_berths=3, n_tanks=14,
                                 horizon_days=5, congestion=0.9)
        opt = model.solve(scenario, time_limit_s=10)
        base = baseline.fcfs(scenario)
        if opt["status"] not in ("OPTIMAL", "FEASIBLE") or base["status"] != "FCFS":
            print(f"{seed:>4} FAILED  opt={opt['status']} base={base['status']}")
            failures += 1
            continue
        ko = kpis.compute(opt["entries"], scenario)
        kb = kpis.compute(base["entries"], scenario)

        # Disruption pipeline: delay the first vessel 12h, re-optimize, and
        # compare against stubbornly executing the original plan ("frozen").
        disrupted = data.delay_vessel(scenario, scenario.vessels[0].name, 12 * 60)
        opt_d = model.solve(disrupted, time_limit_s=10)
        frozen = baseline.freeze_replan(disrupted, opt["entries"])
        kd = kpis.compute(opt_d["entries"], disrupted)
        kf = kpis.compute(frozen["entries"], disrupted)
        assert opt_d["status"] in ("OPTIMAL", "FEASIBLE")
        assert kd["total"] <= kf["total"] + 1e-6, \
            "re-optimized plan should never lose to the frozen plan"

        print(
            f"{seed:>4} {opt['status']:<8} {kb['wait_h']:>8.1f}h {ko['wait_h']:>7.1f}h "
            f"{kb['total']:>10,.0f} {ko['total']:>10,.0f} {kb['total'] - ko['total']:>9,.0f} "
            f"{kb['n_clean']:>3}/{ko['n_clean']:<3} "
            f"{kf['total'] - kd['total']:>10,.0f} {opt['wall_time_s']:>5.2f}"
        )
        assert ko["total"] <= kb["total"] + 1e-6, "optimizer should never lose to FCFS"
    if failures:
        sys.exit(f"{failures} seed(s) failed")
    print("ALL OK")


if __name__ == "__main__":
    main()

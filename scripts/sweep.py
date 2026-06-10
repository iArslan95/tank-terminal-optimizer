"""Parameter sweep to pick demo defaults where the optimizer visibly wins."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from optimizer import baseline, data, kpis, model  # noqa: E402

for cong in (0.7, 0.8, 0.9):
    for nv in (8, 9, 10):
        for nb in (2, 3):
            results = []
            for seed in range(1, 11):
                sc = data.generate(seed, nv, nb, 14, horizon_days=5, congestion=cong)
                opt = model.solve(sc, 10)
                base = baseline.fcfs(sc)
                if opt["status"] not in ("OPTIMAL", "FEASIBLE"):
                    continue
                ko = kpis.compute(opt["entries"], sc)
                kb = kpis.compute(base["entries"], sc)
                results.append((seed, kb["wait_h"], ko["wait_h"],
                                kb["total"], ko["total"], kb["total"] - ko["total"],
                                kb["n_clean"], ko["n_clean"]))
            saved = [r[5] for r in results]
            wait = [r[1] for r in results]
            print(f"cong={cong} nv={nv} nb={nb}  "
                  f"meanWaitFCFS={sum(wait)/len(wait):6.1f}h  "
                  f"meanSaved={sum(saved)/len(saved):9,.0f}  "
                  f"posSeeds={sum(1 for s in saved if s > 1000)}/10")
            best = sorted(results, key=lambda r: -r[5])[:3]
            for r in best:
                print(f"    seed {r[0]:>2}: waitF={r[1]:5.1f}h waitO={r[2]:5.1f}h "
                      f"totF={r[3]:9,.0f} totO={r[4]:9,.0f} saved={r[5]:9,.0f} "
                      f"clean {r[6]}/{r[7]}")

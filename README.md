# ⚓ PortOpt — Tank Terminal Scheduling Optimizer

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![OR-Tools](https://img.shields.io/badge/OR--Tools-CP--SAT-green)
![Streamlit](https://img.shields.io/badge/Streamlit-app-red)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

An interactive **Operations Research** demo: a CP-SAT optimization model that
assigns every vessel calling at a chemical tank terminal a **berth**, a
**storage tank** and a **start time** — minimising demurrage and tank-cleaning
cost under real operational constraints — wrapped in a Streamlit decision-support
UI and benchmarked against a first-come-first-served plan. The scenario is
modelled after chemical terminals in the Rotterdam **Botlek** area (such as
Vopak Botlek); all data is synthetic and the project is not affiliated with
any terminal operator.

## Why

Picture a Tuesday morning at a Rotterdam chemical terminal. Five tankers sit at
anchorage; one must discharge methanol, another loads styrene, a third carries
acrylonitrile that only goes into a cleaned stainless tank. There are a handful
of jetties and dozens of tanks, half of them full or reserved. Every hour a
vessel waits costs serious demurrage money. The number of feasible plans runs
into the billions — far beyond what any planner can weigh by hand.

That is an optimization problem. This repo turns it into mathematics and lets a
solver find the **provably best** plan in seconds, then shows the planner what
it decided and why — the essence of a decision support system.

## What the app does

- **Optimizes** berth allocation, tank assignment and sequencing jointly with
  [OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_solver).
- **Benchmarks** every plan against a first-come-first-served baseline and shows
  the € saved (demurrage + cleaning), waiting hours and berth utilization.
- **Visualizes** the plan: vessel timeline with waiting bars and ETA markers,
  berth occupation Gantt, and tank capacity/flow charts.
- **What-if analysis**: delay any vessel by X hours and compare three plans —
  the original optimum, stubbornly executing the old schedule, and the
  re-optimized plan. The gap between the last two is the euro value of
  re-planning: the core loop of operational decision support.
- **Explains itself**: a model tab with the MILP-style formulation, the CP-SAT
  code, solver telemetry and a production roadmap.

All data is **synthetic** (generated per random seed, guaranteed feasible) but
realistic in magnitude: vessel classes, pump rates, a Botlek-style product
slate (methanol, MEG, styrene, acrylonitrile, caustic, aromatics, biofuels),
tank linings, cleaning times and demurrage rates. Vessel names are real
chemical-tanker names from fleets that call at Rotterdam (Stolt, Odfjell,
Essberger) — flavour only, with no real schedules or cargoes attached.

## The optimization model

| Block | Content |
|---|---|
| **Variables** | `x[v,b]` vessel→berth (bool), `y[v,k]` vessel→tank (bool), `s[v]` start time (int, minutes) |
| **Constraints** | one berth & one tank per vessel · at most one vessel per tank · vessel-size/berth compatibility · product/tank-lining compatibility · no overlap per berth (interval variables) · `s[v] ≥ ETA` · `s[v] ≥` cleaning time if the chosen tank needs a product switch |
| **Objective** | minimise `Σ wait[v] · demurrage_rate[v] + Σ y[v,k] · cleaning_cost[k]` |

The baseline planner serves vessels strictly in ETA order at the earliest free
berth — a sensible human heuristic. The optimizer beats it by resequencing,
deliberately choosing slower berths, or trading a tank cleaning against waiting
cost, and it **proves** optimality rather than guessing.

## Quickstart

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Sanity-check the optimizer across 12 random scenarios:

```bash
python scripts/selftest.py
```

## Deploy (free, shareable link)

1. Push this repo to GitHub (public).
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
3. **New app** → pick the repo and branch, main file `app.py` → **Deploy**.
4. Share the `https://<app>.streamlit.app` URL.

## Project structure

```
app.py                  Streamlit UI (charts, KPIs, what-if controls)
optimizer/
  data.py               synthetic scenario generator (vessels, berths, tanks)
  model.py              CP-SAT model: berth + tank + sequencing, cost objective
  baseline.py           first-come-first-served benchmark planner
  kpis.py               shared KPI computation (one yardstick for both plans)
scripts/selftest.py     multi-seed smoke test (optimizer never loses to FCFS,
                        re-optimizing never loses to freezing the old plan)
scripts/ui_test.py      headless UI test via streamlit.testing (AppTest)
```

## From demo to production

- Rolling re-optimization as ETAs update, freezing operations already in progress
- Time-phased tank inventory (multiple vessels per tank, heels, blending rules)
- Contract logic: laytime before demurrage, per-customer rates and priorities
- ETA **forecasts** (p50/p90) as optimizer input instead of nominated times —
  where predictive modeling meets Operations Research
- Planner-in-the-loop: lock assignments, compare scenarios, explain decisions

## Disclaimer

Educational portfolio project, inspired by chemical terminals in the Rotterdam
Botlek area (such as Vopak Botlek). All scenario data is synthetic; vessel
names are real tanker names used as flavour only, with no real schedules,
cargoes, terminals or customer data involved. Not affiliated with or endorsed
by any terminal operator or shipping company.

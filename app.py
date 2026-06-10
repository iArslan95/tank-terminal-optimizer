"""PortOpt — interactive Operations Research demo.

A CP-SAT model assigns every incoming vessel a berth, a storage tank and a
start time, minimising demurrage and tank-cleaning cost under operational
constraints — and is benchmarked against a first-come-first-served plan.

Run:  streamlit run app.py
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from datetime import time as dtime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from optimizer import baseline, data, kpis, model

st.set_page_config(
    page_title="PortOpt — Tank Terminal Scheduling",
    page_icon="⚓",
    layout="wide",
)

DEFAULT_SEED = 8
WAIT_KIND = "Waiting at anchorage"
WAIT_COLOR = "#64748b"
PRODUCT_COLORS = {p.name: p.color for p in data.PRODUCTS}
GANTT_COLORS = dict(PRODUCT_COLORS, **{WAIT_KIND: WAIT_COLOR})
T0 = datetime.combine(date.today(), dtime(6, 0))

CSS = """
<style>
.block-container {padding-top: 1.4rem;}
.hero {
  background: linear-gradient(135deg, #0b3a5c 0%, #0e7490 60%, #155e75 100%);
  border: 1px solid #1e5f8a; border-radius: 18px;
  padding: 26px 30px; margin-bottom: 18px;
}
.hero h1 {margin: 0; font-size: 1.9rem; color: #f0f9ff;}
.hero p {margin: 8px 0 0; color: #bae6fd; font-size: 1.0rem; max-width: 90ch;}
[data-testid="stMetric"] {
  background: #11233b; border: 1px solid #1f3b5c;
  border-radius: 14px; padding: 14px 16px;
}
.savings {
  background: linear-gradient(90deg, #064e3b, #065f46);
  border: 1px solid #10b981; color: #d1fae5;
  padding: 14px 18px; border-radius: 14px;
  font-size: 1.05rem; margin: 6px 0 14px;
}
.orcard {
  background: #11233b; border: 1px solid #1f3b5c; border-radius: 14px;
  padding: 16px 18px; height: 100%;
}
.orcard h4 {margin: 0 0 8px; color: #7dd3fc;}
.orcard p {margin: 0; color: #cbd5e1; font-size: 0.92rem;}
.footer {color: #64748b; font-size: 0.85rem; margin-top: 28px;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def ts(minutes: float) -> datetime:
    return T0 + timedelta(minutes=int(minutes))


def fmt(minutes: float) -> str:
    return ts(minutes).strftime("%a %d %b %H:%M")


def eur(x: float) -> str:
    return f"€ {x:,.0f}"


@st.cache_data(show_spinner=False)
def build_scenario(seed, nv, nb, nt, hd, cong, dem_scale):
    return data.generate(seed, nv, nb, nt, horizon_days=hd, congestion=cong,
                         demurrage_scale=dem_scale)


@st.cache_data(show_spinner="Solving with CP-SAT…")
def solve_all(seed, nv, nb, nt, hd, cong, dem_scale, disrupted, delay_h, time_limit):
    scenario = data.generate(seed, nv, nb, nt, horizon_days=hd, congestion=cong,
                             demurrage_scale=dem_scale)
    if disrupted:
        scenario = data.delay_vessel(scenario, disrupted, int(delay_h * 60))
    return scenario, model.solve(scenario, time_limit), baseline.fcfs(scenario)


def style_fig(fig, height):
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#cbd5e1",
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=""),
    )
    fig.update_xaxes(gridcolor="#1e293b", zeroline=False)
    fig.update_yaxes(gridcolor="#1e293b", title="")
    return fig


def vessel_gantt(entries):
    """One row per vessel: grey waiting bar from ETA to start, then the
    coloured pumping operation at the assigned berth."""
    ordered = sorted(entries, key=lambda e: e["eta"])
    labels = [f"{e['vessel']} ({e['size']})" for e in ordered]
    rows = []
    for e, label in zip(ordered, labels):
        op = "Discharge" if e["op"] == "IMPORT" else "Load"
        info = f"{op} {e['volume']:,} m³ · {e['berth']} → {e['tank']}"
        if e["wait"] > 0:
            rows.append(dict(Task=label, Start=ts(e["eta"]), End=ts(e["start"]),
                             Kind=WAIT_KIND, Info=f"Waiting {e['wait'] / 60:.1f} h"))
        rows.append(dict(Task=label, Start=ts(e["start"]), End=ts(e["end"]),
                         Kind=e["product"], Info=info))
    fig = px.timeline(
        pd.DataFrame(rows), x_start="Start", x_end="End", y="Task", color="Kind",
        color_discrete_map=GANTT_COLORS, hover_data=["Info"],
        pattern_shape="Kind",
        pattern_shape_map=dict({p: "" for p in PRODUCT_COLORS}, **{WAIT_KIND: "/"}),
    )
    fig.update_yaxes(categoryorder="array", categoryarray=labels, autorange="reversed")
    fig.add_trace(go.Scatter(
        x=[ts(e["eta"]) for e in ordered], y=labels, mode="markers",
        marker=dict(symbol="diamond", size=10, color="#f8fafc",
                    line=dict(color="#475569", width=1)),
        name="ETA (nominated)",
        hovertemplate="%{y} — ETA %{x|%a %H:%M}<extra></extra>",
    ))
    return style_fig(fig, 120 + 42 * len(ordered))


def berth_gantt(entries, scenario):
    rate = {b.name: b.pump_rate for b in scenario.berths}
    labels = [f"{b.name} · {b.pump_rate:,} m³/h" for b in scenario.berths]
    rows = [
        dict(
            Berth=f"{e['berth']} · {rate[e['berth']]:,} m³/h",
            Start=ts(e["start"]), End=ts(e["end"]), Kind=e["product"],
            Vessel=e["vessel"].replace("MT ", ""),
            Info=f"{e['vessel']} · {e['volume']:,} m³ → {e['tank']}",
        )
        for e in entries
    ]
    fig = px.timeline(
        pd.DataFrame(rows), x_start="Start", x_end="End", y="Berth", color="Kind",
        color_discrete_map=PRODUCT_COLORS, text="Vessel", hover_data=["Info"],
    )
    fig.update_traces(textposition="inside", insidetextanchor="middle")
    fig.update_yaxes(categoryorder="array", categoryarray=labels, autorange="reversed")
    return style_fig(fig, 130 + 52 * len(labels))


def tank_chart(scenario, entries):
    """Horizontal capacity bars per tank: remaining stock, outgoing volume,
    incoming volume and free space after the plan executes."""
    flow = {e["tank"]: e for e in entries}
    tanks = sorted(scenario.tanks, key=lambda t: t.name, reverse=True)
    labels, rem_x, rem_c, rem_t = [], [], [], []
    out_x, out_c, out_t, inc_x, inc_c, inc_t = [], [], [], [], [], []
    free_x, free_t = [], []
    for t in tanks:
        e = flow.get(t.name)
        incoming = e["volume"] if e and e["op"] == "IMPORT" else 0
        outgoing = e["volume"] if e and e["op"] == "EXPORT" else 0
        remaining = t.level - outgoing
        label = f"{t.name} · {t.lining}" + (" 🧽" if e and e["clean"] else "")
        labels.append(label)
        rem_x.append(remaining)
        rem_c.append(t.product.color if t.product else "#1e293b")
        rem_t.append(f"{t.name}: {remaining:,} m³ {t.product.name if t.product else ''} remains")
        out_x.append(outgoing)
        out_c.append(t.product.color if t.product else "#1e293b")
        out_t.append(f"{e['vessel']} loads {outgoing:,} m³ {e['product']}" if outgoing else "")
        inc_x.append(incoming)
        inc_c.append(e["color"] if incoming else "#1e293b")
        inc_t.append(
            f"{e['vessel']} discharges {incoming:,} m³ {e['product']}"
            + (f" — cleaning first ({t.clean_hours} h, {eur(t.clean_cost)})" if e and e["clean"] else "")
            if incoming else ""
        )
        free_x.append(t.capacity - remaining - incoming)
        free_t.append(f"{t.name}: free space after plan")

    fig = go.Figure()
    fig.add_bar(y=labels, x=rem_x, orientation="h", name="Stock (stays)",
                marker=dict(color=rem_c), hovertext=rem_t, hoverinfo="text")
    fig.add_bar(y=labels, x=out_x, orientation="h", name="Outgoing (loaded to vessel)",
                marker=dict(color=out_c, pattern=dict(shape="x"), opacity=0.65),
                hovertext=out_t, hoverinfo="text")
    fig.add_bar(y=labels, x=inc_x, orientation="h", name="Incoming (discharged)",
                marker=dict(color=inc_c, pattern=dict(shape="/")),
                hovertext=inc_t, hoverinfo="text")
    fig.add_bar(y=labels, x=free_x, orientation="h", name="Free capacity",
                marker=dict(color="rgba(148,163,184,0.12)",
                            line=dict(color="#1f3b5c", width=1)),
                hovertext=free_t, hoverinfo="text")
    fig.update_layout(barmode="stack")
    fig.update_xaxes(title="m³")
    return style_fig(fig, 110 + 28 * len(labels))


def cost_bar(k_base, k_opt):
    df = pd.DataFrame([
        {"Plan": "First-come-first-served", "Component": "Demurrage", "EUR": k_base["demurrage"]},
        {"Plan": "First-come-first-served", "Component": "Tank cleaning", "EUR": k_base["cleaning"]},
        {"Plan": "Optimized (CP-SAT)", "Component": "Demurrage", "EUR": k_opt["demurrage"]},
        {"Plan": "Optimized (CP-SAT)", "Component": "Tank cleaning", "EUR": k_opt["cleaning"]},
    ])
    fig = px.bar(df, x="Plan", y="EUR", color="Component", barmode="stack", text_auto=".2s",
                 color_discrete_map={"Demurrage": "#f59e0b", "Tank cleaning": "#22d3ee"})
    return style_fig(fig, 340)


def schedule_table(entries):
    rows = [
        {
            "Vessel": e["vessel"],
            "Op": "⬇️ Discharge" if e["op"] == "IMPORT" else "⬆️ Load",
            "Product": e["product"],
            "Volume (m³)": f"{e['volume']:,}",
            "Berth": e["berth"],
            "Tank": e["tank"] + (" 🧽" if e["clean"] else ""),
            "ETA": fmt(e["eta"]),
            "Start": fmt(e["start"]),
            "Finish": fmt(e["end"]),
            "Wait (h)": round(e["wait"] / 60, 1),
            "Demurrage": eur(e["demurrage"]),
        }
        for e in sorted(entries, key=lambda e: e["start"])
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("### ⚓ PortOpt")
    st.caption("Operations Research demo — synthetic data, real mathematics.")

    st.markdown("#### Scenario")
    seed = st.number_input("Random seed", 1, 999, DEFAULT_SEED,
                           help="Same seed = same scenario. Change it for a fresh week.")
    n_vessels = st.slider("Vessels calling this week", 3, 12, 10)
    n_berths = st.slider("Berths (jetties)", 2, 4, 3)
    n_tanks = st.slider("Storage tanks", 8, 24, 14)
    horizon_days = st.slider("Planning horizon (days)", 3, 10, 5)
    congestion = st.slider("Arrival congestion", 0.0, 1.0, 0.9, 0.05,
                           help="Higher = ETAs bunch together → more queueing pressure.")

    st.markdown("#### Economics")
    dem_scale = st.slider("Demurrage level (×)", 0.5, 2.0, 1.0, 0.1,
                          help="Waiting cost per day at 1.0×: S € 9k · M € 18k · L € 30k.")

scenario_preview = build_scenario(seed, n_vessels, n_berths, n_tanks,
                                  horizon_days, congestion, dem_scale)
vessel_names = [v.name for v in scenario_preview.vessels]

with st.sidebar:
    st.markdown("#### What-if disruption")
    pick = st.selectbox("Delayed vessel", ["— none —"] + vessel_names,
                        help="Simulate a late arrival and watch the plan re-optimize.")
    delay_h = st.slider("Delay (hours)", 2, 36, 12) if pick != "— none —" else 0

    st.markdown("#### Solver")
    time_limit = st.slider("CP-SAT time limit (s)", 2, 30, 10)
    st.caption("Instances this size usually solve to proven optimality in well under a second.")

disrupted = None if pick == "— none —" else pick
scenario, opt, base = solve_all(seed, n_vessels, n_berths, n_tanks, horizon_days,
                                congestion, dem_scale, disrupted, delay_h, time_limit)

# ----------------------------------------------------------------------------- header
st.markdown(
    """
    <div class="hero">
      <h1>⚓ PortOpt — Terminal Scheduling Optimizer</h1>
      <p>Decision support for liquid-bulk tank terminals. A CP-SAT optimization model
      assigns every incoming vessel a <b>berth</b>, a <b>storage tank</b> and a
      <b>start time</b> — minimising demurrage and tank-cleaning cost under real
      operational constraints, and benchmarked against a first-come-first-served plan.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if opt["status"] not in ("OPTIMAL", "FEASIBLE"):
    st.error(f"Solver returned **{opt['status']}** — try another seed or more tanks.")
    st.stop()
if base["status"] != "FCFS":
    st.error("Baseline could not find a feasible plan — try another seed.")
    st.stop()

if disrupted:
    st.warning(f"⚠️ Disruption active: **{disrupted}** arrives **{delay_h} h late** — "
               "both plans below are computed on the disrupted ETAs.")

k_opt = kpis.compute(opt["entries"], scenario)
k_base = kpis.compute(base["entries"], scenario)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total plan cost", eur(k_opt["total"]),
          delta=f"{k_opt['total'] - k_base['total']:+,.0f} € vs FCFS", delta_color="inverse")
c2.metric("Waiting time", f"{k_opt['wait_h']:,.1f} h",
          delta=f"{k_opt['wait_h'] - k_base['wait_h']:+,.1f} h vs FCFS", delta_color="inverse")
c3.metric("Demurrage", eur(k_opt["demurrage"]),
          delta=f"{k_opt['demurrage'] - k_base['demurrage']:+,.0f} € vs FCFS",
          delta_color="inverse")
c4.metric("Tank cleanings", f"{k_opt['n_clean']}",
          delta=f"{k_opt['n_clean'] - k_base['n_clean']:+d} vs FCFS", delta_color="inverse")
c5.metric("Berth utilization", f"{k_opt['utilization'] * 100:.0f}%",
          delta=f"{(k_opt['utilization'] - k_base['utilization']) * 100:+.0f} pp vs FCFS",
          delta_color="off")

saved = k_base["total"] - k_opt["total"]
if saved > 0.5:
    pct = saved / k_base["total"] * 100 if k_base["total"] else 0
    st.markdown(
        f"""<div class="savings">💰 The optimized plan saves <b>{eur(saved)}</b>
        (−{pct:.0f}%) versus first-come-first-served — {k_base['wait_h'] - k_opt['wait_h']:,.1f}
        fewer hours of waiting across {len(scenario.vessels)} port calls.</div>""",
        unsafe_allow_html=True,
    )
else:
    st.info("FCFS happens to be optimal for this scenario — raise **arrival congestion** "
            "or add vessels to see the optimizer earn its keep.")

tab_plan, tab_vs, tab_data, tab_how = st.tabs(
    ["🗓️ Optimized plan", "⚖️ vs. First-come-first-served", "📦 Scenario data", "🧠 Under the hood"]
)

# ----------------------------------------------------------------------------- plan tab
with tab_plan:
    st.caption(
        f"Solver: CP-SAT · status **{opt['status']}** · {opt['wall_time_s']:.2f}s wall time · "
        f"objective {eur(opt['objective_eur'])} · plan start {T0:%a %d %b %H:%M}"
    )
    st.subheader("Vessel timeline")
    st.plotly_chart(vessel_gantt(opt["entries"]), use_container_width=True)
    st.subheader("Berth occupation")
    st.plotly_chart(berth_gantt(opt["entries"], scenario), use_container_width=True)
    st.subheader("Tank allocation")
    st.caption("Hatched = volume moving this week · 🧽 = cleaning required before use.")
    st.plotly_chart(tank_chart(scenario, opt["entries"]), use_container_width=True)
    st.subheader("Schedule")
    schedule_table(opt["entries"])

# ----------------------------------------------------------------------------- compare tab
with tab_vs:
    st.markdown(
        "The baseline handles vessels **strictly in ETA order** at the first free berth — "
        "a sensible human heuristic. The optimizer may resequence vessels, pick a slower "
        "berth on purpose, or accept a tank cleaning when that wins overall."
    )
    left, right = st.columns(2)
    with left:
        st.plotly_chart(cost_bar(k_base, k_opt), use_container_width=True)
    with right:
        b = {e["vessel"]: e for e in base["entries"]}
        o = {e["vessel"]: e for e in opt["entries"]}
        rows = [
            {
                "Vessel": name,
                "Wait FCFS (h)": round(b[name]["wait"] / 60, 1),
                "Wait optimized (h)": round(o[name]["wait"] / 60, 1),
                "€ saved": round(
                    b[name]["demurrage"] + b[name]["clean_cost"]
                    - o[name]["demurrage"] - o[name]["clean_cost"]
                ),
            }
            for name in sorted(b, key=lambda n: b[n]["eta"])
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                     height=330)
    st.subheader("The FCFS plan, for comparison")
    st.plotly_chart(vessel_gantt(base["entries"]), use_container_width=True)

# ----------------------------------------------------------------------------- data tab
with tab_data:
    st.caption(f"All synthetic, generated from seed {seed}. "
               "Regenerate via the sidebar — every scenario is guaranteed feasible.")
    st.subheader(f"Vessels ({len(scenario.vessels)})")
    vdf = pd.DataFrame([
        {
            "Vessel": v.name, "Class": v.size,
            "Operation": "⬇️ Discharge" if v.operation == "IMPORT" else "⬆️ Load",
            "Product": v.product.name, "Volume (m³)": v.volume,
            "ETA": fmt(v.eta_min), "Demurrage €/day": round(v.demurrage_day),
        }
        for v in scenario.vessels
    ])
    st.dataframe(vdf, use_container_width=True, hide_index=True)

    st.subheader(f"Storage tanks ({len(scenario.tanks)})")
    tdf = pd.DataFrame([
        {
            "Tank": t.name, "Lining": t.lining, "Capacity (m³)": t.capacity,
            "Current product": t.product.name if t.product else "— empty —",
            "Fill": round(t.level / t.capacity * 100),
            "Residue": t.last_product.name if (t.product is None and t.last_product) else "",
            "Cleaning": f"{t.clean_hours} h · {eur(t.clean_cost)}",
        }
        for t in scenario.tanks
    ])
    st.dataframe(
        tdf, use_container_width=True, hide_index=True,
        column_config={"Fill": st.column_config.ProgressColumn(
            "Fill", format="%d%%", min_value=0, max_value=100)},
    )

    st.subheader(f"Berths ({len(scenario.berths)})")
    bdf = pd.DataFrame([
        {"Berth": b.name, "Max vessel class": b.max_size, "Pump rate (m³/h)": b.pump_rate}
        for b in scenario.berths
    ])
    st.dataframe(bdf, use_container_width=True, hide_index=True)

# ----------------------------------------------------------------------------- how tab
with tab_how:
    st.markdown("#### Operations Research in three building blocks")
    cc1, cc2, cc3 = st.columns(3)
    cc1.markdown(
        """<div class="orcard"><h4>1 · Decision variables</h4>
        <p>For every vessel: <b>which berth</b> (x<sub>v,b</sub>), <b>which tank</b>
        (y<sub>v,k</sub>) and <b>when to start</b> (s<sub>v</sub>). Booleans and an
        integer — every possible plan is some setting of these knobs.</p></div>""",
        unsafe_allow_html=True)
    cc2.markdown(
        """<div class="orcard"><h4>2 · Hard constraints</h4>
        <p>One berth and one tank per vessel · one vessel per tank · vessel size vs
        berth · product vs tank lining · no berth overlaps · never start before ETA
        or before cleaning finishes. Infeasible plans simply don't exist.</p></div>""",
        unsafe_allow_html=True)
    cc3.markdown(
        """<div class="orcard"><h4>3 · Objective</h4>
        <p>Minimise money: waiting hours × the vessel's demurrage rate, plus cleaning
        cost for every tank switched to a new product. The solver proves optimality,
        it doesn't guess.</p></div>""",
        unsafe_allow_html=True)

    st.markdown("&nbsp;")
    st.latex(r"""
        \min \;\; \sum_{v} c^{\text{wait}}_{v}\,(s_v - a_v)
        \;+\; \sum_{v,k} c^{\text{clean}}_{k}\; y_{v,k}
    """)
    st.latex(r"""
        \text{s.t.}\quad
        \sum_{b} x_{v,b} = 1,\qquad
        \sum_{k} y_{v,k} = 1,\qquad
        \sum_{v} y_{v,k} \le 1,\qquad
        s_v \ge a_v
    """)
    st.latex(r"""
        s_v \ge T^{\text{clean}}_{k}\cdot y_{v,k},
        \qquad
        \big[\,s_v,\; s_v + d_{v,b}\,\big) \text{ pairwise disjoint per berth } b
    """)

    n, nb_, nt_ = len(scenario.vessels), len(scenario.berths), len(scenario.tanks)
    space = nb_ ** n * math.factorial(n) * nt_ ** n
    with st.expander("Why a solver, and not brute force?"):
        st.markdown(
            f"This small scenario already spans roughly **{space:,.0f}** candidate plans "
            f"({nb_} berths and {nt_} tanks over {n} vessels, times every service order). "
            "CP-SAT does not enumerate them — branch-and-bound with constraint propagation "
            "prunes whole subtrees of provably-worse plans, which is how it returns a "
            f"**proven optimum** in ~{opt['wall_time_s']:.2f}s "
            f"({opt['branches']:,} branches, {opt['conflicts']:,} conflicts explored)."
        )

    with st.expander("The model in code (OR-Tools CP-SAT)"):
        st.code(
            '''
# one boolean per vessel-berth pair, one optional interval on the berth timeline
pres = model.NewBoolVar(f"x_{vessel}_{berth}")
iv = model.NewOptionalIntervalVar(start, service_min, end, pres, name)
model.AddExactlyOne(berth_literals)          # every vessel moors somewhere
model.AddNoOverlap(intervals_per_berth)      # one vessel per berth at a time

model.AddExactlyOne(tank_literals)           # every vessel gets a tank
model.AddAtMostOne(vessels_per_tank)         # a tank serves one vessel
model.Add(start >= clean_hours * 60).OnlyEnforceIf(y)   # cleaning gate

wait = start - eta
model.Minimize(sum(wait * demurrage_rate) + sum(y * cleaning_cost))
''',
            language="python",
        )

    st.markdown("#### From demo to production")
    st.markdown(
        """
- **Rolling re-optimization** — re-solve every few hours as ETAs update, freezing moves already in progress.
- **Tank inventory over time** — multiple vessels per tank with time-phased level tracking, heel and blending rules.
- **Contract logic** — laytime before demurrage starts, per-customer rates and priorities.
- **ETA forecasts as input** — feed the optimizer predicted arrival times (with uncertainty) instead of nominated ones; planning against *p50/p90* ETAs is where forecasting meets OR.
- **Planner-in-the-loop UI** — lock assignments, compare scenarios, and always show *why* the plan is optimal.
        """
    )

st.markdown(
    """<div class="footer">PortOpt · OR-Tools CP-SAT + Streamlit · all data synthetic ·
    built by Ismail Arslan as an Operations Research portfolio demo — not affiliated
    with any terminal operator.</div>""",
    unsafe_allow_html=True,
)

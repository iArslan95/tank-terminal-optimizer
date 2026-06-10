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

import assistant
from optimizer import baseline, data, kpis, model

st.set_page_config(
    page_title="PortOpt — Tank Terminal Scheduling",
    page_icon="⚓",
    layout="wide",
)

DEFAULT_SEED = 5
WAIT_KIND = "Waiting at anchorage"
WAIT_COLOR = "#9ca3af"
PRODUCT_COLORS = {p.name: p.color for p in data.PRODUCTS}
GANTT_COLORS = dict(PRODUCT_COLORS, **{WAIT_KIND: WAIT_COLOR})
T0 = datetime.combine(date.today(), dtime(6, 0))

CSS = """
<style>
.block-container {padding-top: 1.4rem;}
.hero {
  background: #ffffff;
  border: 1px solid #e7e5e4; border-left: 4px solid #0f766e;
  border-radius: 14px; padding: 26px 30px; margin-bottom: 18px;
}
.hero h1 {margin: 0; font-size: 1.8rem; color: #1c1917; letter-spacing: -0.01em;}
.hero p {margin: 8px 0 0; color: #78716c; font-size: 0.98rem; max-width: 90ch;}
[data-testid="stMetric"] {
  background: #ffffff; border: 1px solid #e7e5e4;
  border-radius: 12px; padding: 14px 16px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}
.savings {
  background: #f0fdf4; border: 1px solid #bbf7d0; color: #166534;
  padding: 13px 18px; border-radius: 12px;
  font-size: 1.0rem; margin: 6px 0 14px;
}
.orcard {
  background: #ffffff; border: 1px solid #e7e5e4; border-radius: 12px;
  padding: 16px 18px; height: 100%;
}
.orcard h4 {margin: 0 0 8px; color: #0f766e;}
.orcard p {margin: 0; color: #57534e; font-size: 0.92rem;}
.footer {color: #a8a29e; font-size: 0.85rem; margin-top: 28px;}
/* Tabs styled as clearly clickable buttons */
.stTabs [data-baseweb="tab-list"] {gap: 8px; padding: 2px 0 10px;}
.stTabs [data-baseweb="tab"] {
  background: #ffffff; border: 1px solid #e7e5e4; border-radius: 10px;
  padding: 9px 18px; font-weight: 600; font-size: 0.97rem; color: #57534e;
}
.stTabs [data-baseweb="tab"]:hover {border-color: #0f766e; color: #0f766e;}
.stTabs [aria-selected="true"] {
  background: #0f766e; border-color: #0f766e; color: #ffffff;
}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {display: none;}
/* Plan Assistant panel */
.chat-head {font-weight: 700; font-size: 1.02rem; color: #0f766e; margin-top: 4px;}
.stButton button {
  font-size: 0.85rem; text-align: left; width: 100%;
  background: #ffffff; border: 1px solid #e7e5e4; border-radius: 10px;
  color: #44403c; padding: 6px 12px;
}
.stButton button:hover {border-color: #0f766e; color: #0f766e;}
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
    """Solve the scenario. With a disruption active, also return the original
    (undisrupted) optimum and the 'frozen' plan — the old schedule executed
    against the new ETAs — so the UI can show the value of re-planning."""
    scenario = data.generate(seed, nv, nb, nt, horizon_days=hd, congestion=cong,
                             demurrage_scale=dem_scale)
    opt0 = model.solve(scenario, time_limit)
    if not disrupted:
        return scenario, opt0, baseline.fcfs(scenario), None, None
    disturbed = data.delay_vessel(scenario, disrupted, int(delay_h * 60))
    opt = model.solve(disturbed, time_limit)
    frozen = baseline.freeze_replan(disturbed, opt0["entries"]) if opt0["entries"] else None
    return disturbed, opt, baseline.fcfs(disturbed), opt0, frozen


def style_fig(fig, height):
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#57534e",
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=""),
    )
    fig.update_xaxes(gridcolor="#e7e5e4", zeroline=False)
    fig.update_yaxes(gridcolor="#e7e5e4", title="")
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
        marker=dict(symbol="diamond", size=10, color="#ffffff",
                    line=dict(color="#44403c", width=1.5)),
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
        rem_c.append(t.product.color if t.product else "#d6d3d1")
        rem_t.append(f"{t.name}: {remaining:,} m³ {t.product.name if t.product else ''} remains")
        out_x.append(outgoing)
        out_c.append(t.product.color if t.product else "#d6d3d1")
        out_t.append(f"{e['vessel']} loads {outgoing:,} m³ {e['product']}" if outgoing else "")
        inc_x.append(incoming)
        inc_c.append(e["color"] if incoming else "#d6d3d1")
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
                marker=dict(color="rgba(120,113,108,0.06)",
                            line=dict(color="#e7e5e4", width=1)),
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
                 color_discrete_map={"Demurrage": "#e09f3e", "Tank cleaning": "#2a9d8f"})
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
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_chat(scenario, opt, base, k_opt, k_base, settings, disruption):
    """Always-visible assistant panel, grounded in the live plan data."""
    st.markdown('<div class="chat-head">💬 Plan Assistant</div>', unsafe_allow_html=True)
    st.caption("Grounded in the live schedule — ask why, what, and what-if.")
    history = st.session_state.setdefault("chat_history", [])

    box = st.container(height=460, border=True)
    with box:
        if not history:
            st.markdown(
                "<small style='color:#a8a29e'>I can explain every number on this "
                "page — the schedule, the savings, the constraints. Try a "
                "suggestion below or ask your own question.</small>",
                unsafe_allow_html=True,
            )
        for m in history:
            with st.chat_message(m["role"], avatar="⚓" if m["role"] == "assistant" else None):
                st.markdown(m["content"])

    api_key = assistant.get_api_key()
    if not api_key:
        st.info("Add `GROQ_API_KEY` to `.streamlit/secrets.toml` (locally) or to "
                "the app's Secrets on Streamlit Cloud to enable the assistant.")
        return

    n_user = sum(1 for m in history if m["role"] == "user")
    if n_user >= assistant.MAX_USER_MESSAGES:
        st.warning("Chat limit reached for this session — tweak the scenario or refresh.")
        return

    if not history:
        for i, q in enumerate(assistant.suggested_questions(opt["entries"], k_opt, k_base)):
            if st.button(q, key=f"suggestion_{i}"):
                st.session_state["pending_question"] = q

    user_msg = st.chat_input("Ask about this plan…")
    user_msg = user_msg or st.session_state.pop("pending_question", None)
    if not user_msg:
        return

    history.append({"role": "user", "content": user_msg})
    with box:
        with st.chat_message("user"):
            st.markdown(user_msg)
        with st.chat_message("assistant", avatar="⚓"):
            context = assistant.build_context(
                scenario, opt, base, k_opt, k_base, T0, settings, disruption)
            try:
                reply = st.write_stream(assistant.stream_reply(api_key, context, history))
            except Exception as exc:
                reply = f"⚠️ The assistant hit an error: {exc}"
                st.markdown(reply)
    history.append({"role": "assistant", "content": str(reply)})


# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("### ⚓ PortOpt")
    st.caption("Operations Research demo — synthetic data, real mathematics.")

    st.markdown("#### Scenario")
    n_vessels = st.slider("Vessels calling this week", 3, 20, 10,
                          help="How many tankers arrive this week. More vessels = more "
                               "competition for berths and tanks, so more to optimize.")
    n_berths = st.slider("Berths (jetties)", 2, 6, 3,
                         help="How many jetties the terminal has. One vessel at a time "
                              "per jetty; the large sea jetties pump fastest, the "
                              "coaster/barge berths only take small vessels.")
    congestion = st.slider("Arrival congestion", 0.0, 1.0, 0.9, 0.05,
                           help="How bunched-up the arrivals are. Higher = ETAs cluster "
                                "in the same days → queues at the berths → more for the "
                                "optimizer to win.")

    with st.expander("⚙️ Advanced"):
        seed = st.number_input("Random seed", 1, 999, DEFAULT_SEED,
                               help="Same seed = same scenario. Change it for a fresh week.")
        n_tanks = st.slider("Storage tanks", 8, 36, 14,
                            help="How many storage tanks the terminal has. More tanks = "
                                 "more compatible options per vessel, fewer forced "
                                 "cleanings.")
        horizon_days = st.slider("Planning horizon (days)", 3, 10, 5,
                                 help="Length of the planning window. Arrivals land in "
                                      "the early part of it (see Arrival congestion).")
        dem_scale = st.slider("Demurrage level (×)", 0.5, 2.0, 1.0, 0.1,
                              help="Multiplier on the waiting cost per day. At 1.0×: "
                                   "small vessels € 9k, medium € 18k, large € 30k per "
                                   "day at anchorage.")
        time_limit = st.slider("CP-SAT time limit (s)", 2, 30, 10,
                               help="Maximum seconds the solver may search. OPTIMAL = "
                                    "proven best plan; if time runs out you get the "
                                    "best plan found so far (FEASIBLE).")

scenario_preview = build_scenario(seed, n_vessels, n_berths, n_tanks,
                                  horizon_days, congestion, dem_scale)
vessel_names = [v.name for v in scenario_preview.vessels]

with st.sidebar:
    st.markdown("#### What-if disruption")
    pick = st.selectbox("Delayed vessel", ["— none —"] + vessel_names,
                        help="Pick a vessel that arrives late (weather, port congestion) "
                             "and see what re-planning is worth in euros.")
    delay_h = st.slider("Delay (hours)", 2, 36, 12,
                        help="How many hours later than nominated the vessel arrives "
                             "at the anchorage.") if pick != "— none —" else 0

disrupted = None if pick == "— none —" else pick
scenario, opt, base, opt0, frozen = solve_all(
    seed, n_vessels, n_berths, n_tanks, horizon_days,
    congestion, dem_scale, disrupted, delay_h, time_limit)

# ----------------------------------------------------------------------------- header
st.markdown(
    """
    <div class="hero">
      <h1>⚓ PortOpt — Terminal Scheduling Optimizer</h1>
      <p>Decision support for a Rotterdam-style chemical terminal: the optimizer gives
      every vessel a <b>berth</b>, a <b>tank</b> and a <b>start time</b> — at minimal
      cost — and shows what that saves versus planning by hand.</p>
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

k_opt = kpis.compute(opt["entries"], scenario)
k_base = kpis.compute(base["entries"], scenario)

if disrupted and opt0 and frozen:
    k0 = kpis.compute(opt0["entries"], scenario)
    k_frozen = kpis.compute(frozen["entries"], scenario)
    st.warning(f"⚠️ **{disrupted}** arrives **{delay_h} h late**. "
               "What does the disruption do to the plan?")
    d1, d2, d3 = st.columns(3)
    d1.metric("Original plan (no disruption)", eur(k0["total"]),
              help="The optimal plan computed on the original, undisrupted ETAs.")
    d2.metric("Stick to the old schedule", eur(k_frozen["total"]),
              delta=f"{k_frozen['total'] - k0['total']:+,.0f} € disruption impact",
              delta_color="inverse",
              help="The original schedule executed against the new ETA — same berths, "
                   "tanks and order, only the clock shifts. This is the cost of NOT "
                   "re-planning.")
    d3.metric("Re-optimized plan", eur(k_opt["total"]),
              delta=f"{k_opt['total'] - k_frozen['total']:+,.0f} € vs old schedule",
              delta_color="inverse",
              help="The best achievable plan given the disruption, re-solved from "
                   "scratch by CP-SAT.")
    replan_gain = k_frozen["total"] - k_opt["total"]
    if replan_gain > 0.5:
        st.success(f"♻️ Re-optimizing after the disruption saves **{eur(replan_gain)}** "
                   "compared to executing the original schedule anyway.")
    if k_opt["total"] < k0["total"] - 0.5:
        st.caption("ℹ️ Total cost can end up *below* the original plan: waiting is paid "
                   "from actual arrival, so a vessel that turns up after the congestion "
                   "peak simply queues less.")
    st.divider()

c1, c2, c3 = st.columns(3)
c1.metric("Total plan cost", eur(k_opt["total"]),
          delta=f"{k_opt['total'] - k_base['total']:+,.0f} € vs first-come-first-served",
          delta_color="inverse",
          help="Demurrage + tank-cleaning cost of the optimized plan. The delta "
               "compares against a first-come-first-served plan of the same scenario.")
c2.metric("Waiting time", f"{k_opt['wait_h']:,.1f} h",
          delta=f"{k_opt['wait_h'] - k_base['wait_h']:+,.1f} h vs first-come-first-served",
          delta_color="inverse",
          help="Total hours all vessels spend waiting at anchorage before a berth "
               "is ready for them.")
c3.metric("Tank cleanings", f"{k_opt['n_clean']}",
          delta=f"{k_opt['n_clean'] - k_base['n_clean']:+d} vs first-come-first-served",
          delta_color="inverse",
          help="Tanks that must be cleaned before use because the incoming product "
               "differs from the residue of the previous one.")

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

main_col, chat_col = st.columns([2.3, 1], gap="medium")

with main_col:
    tab_plan, tab_vs, tab_data, tab_how = st.tabs(
        ["🗓️ The plan", "⚖️ Optimizer vs. human", "📦 Scenario", "🧠 How it works"]
    )

# ----------------------------------------------------------------------------- plan tab
with tab_plan:
    st.caption(
        f"Solver: CP-SAT · status **{opt['status']}** · {opt['wall_time_s']:.2f}s wall time · "
        f"objective {eur(opt['objective_eur'])} · plan start {T0:%a %d %b %H:%M}"
    )
    st.subheader("Vessel timeline",
                 help="One row per vessel, in arrival order. ♦ = nominated ETA · grey "
                      "hatched = waiting at anchorage · coloured bar = pumping at the "
                      "berth (colour = product). Hover any bar for volume, berth and tank.")
    st.plotly_chart(vessel_gantt(opt["entries"]))
    with st.expander("⚓ Berth occupation — which vessel lies where"):
        st.caption("One row per jetty (label shows its pump rate). Bars never overlap: "
                   "one vessel per berth at a time is a hard constraint.")
        st.plotly_chart(berth_gantt(opt["entries"], scenario))
    with st.expander("🛢️ Tank allocation — stock, flows and cleanings"):
        st.caption("Per tank: solid = stock that stays · ✕-hatched = loaded onto a vessel "
                   "· ╱-hatched = discharged into the tank · faint = free space after the "
                   "plan. 🧽 = cleaning required before use.")
        st.plotly_chart(tank_chart(scenario, opt["entries"]))
    st.subheader("Schedule",
                 help="The executable plan: berth, tank and timing per vessel, plus "
                      "waiting hours and their demurrage cost. 🧽 = tank cleaned first.")
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
        st.subheader("Cost comparison",
                     help="Total plan cost stacked by component — demurrage (waiting) "
                          "and tank cleanings. The gap between the bars is what "
                          "optimization earns this week.")
        st.plotly_chart(cost_bar(k_base, k_opt))
    with right:
        st.subheader("Per-vessel impact",
                     help="Waiting hours under both plans and the € saved per vessel "
                          "(demurrage + cleaning differences).")
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
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True,
                     height=330)
    with st.expander("📅 The first-come-first-served plan as a timeline"):
        st.caption("Same scenario, planned strictly in arrival order — typically more "
                   "grey (waiting) than the optimized timeline on the first tab.")
        st.plotly_chart(vessel_gantt(base["entries"]))

# ----------------------------------------------------------------------------- data tab
with tab_data:
    st.caption(f"All synthetic, generated from seed {seed}. "
               "Regenerate via the sidebar — every scenario is guaranteed feasible.")
    st.subheader(f"Vessels ({len(scenario.vessels)})",
                 help="This week's nominations: arrival time (ETA), operation "
                      "(discharge or load), product, volume and each vessel's "
                      "demurrage rate per day of waiting.")
    vdf = pd.DataFrame([
        {
            "Vessel": v.name, "Class": v.size,
            "Operation": "⬇️ Discharge" if v.operation == "IMPORT" else "⬆️ Load",
            "Product": v.product.name, "Volume (m³)": v.volume,
            "ETA": fmt(v.eta_min), "Demurrage €/day": round(v.demurrage_day),
        }
        for v in scenario.vessels
    ])
    st.dataframe(vdf, width="stretch", hide_index=True)

    st.subheader(f"Storage tanks ({len(scenario.tanks)})",
                 help="Current tank state. The lining limits which product families "
                      "are allowed; Residue = last product in an empty tank (a "
                      "different incoming product means cleaning first); Fill = "
                      "current level vs capacity.")
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
        tdf, width="stretch", hide_index=True,
        column_config={"Fill": st.column_config.ProgressColumn(
            "Fill", format="%d%%", min_value=0, max_value=100)},
    )

    st.subheader(f"Berths ({len(scenario.berths)})",
                 help="The jetties: the largest vessel class each can take and its "
                      "pump rate — which drives how long a vessel occupies the berth.")
    bdf = pd.DataFrame([
        {"Berth": b.name, "Max vessel class": b.max_size, "Pump rate (m³/h)": b.pump_rate}
        for b in scenario.berths
    ])
    st.dataframe(bdf, width="stretch", hide_index=True)

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

with chat_col:
    chat_settings = {
        "seed": int(seed), "vessels": n_vessels, "berths": n_berths,
        "tanks": n_tanks, "horizon_days": horizon_days,
        "congestion": congestion, "demurrage_scale": dem_scale,
    }
    disruption_info = None
    if disrupted and opt0 and frozen:
        disruption_info = {
            "vessel": disrupted, "delay_h": delay_h,
            "original": k0["total"], "frozen": k_frozen["total"],
            "reoptimized": k_opt["total"],
        }
    render_chat(scenario, opt, base, k_opt, k_base, chat_settings, disruption_info)

st.markdown(
    """<div class="footer">PortOpt · OR-Tools CP-SAT + Streamlit · all data synthetic ·
    inspired by chemical terminals in the Rotterdam Botlek area (such as Vopak Botlek) ·
    built by Ismail Arslan as an Operations Research portfolio demo — not affiliated
    with or endorsed by any terminal operator.</div>""",
    unsafe_allow_html=True,
)

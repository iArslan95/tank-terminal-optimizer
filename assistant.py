"""PortOpt Plan Assistant — a grounded LLM chat over the live schedule.

Architecture: context injection. Every question is answered by an LLM (Groq,
Llama 3.3 70B) that receives a freshly serialized snapshot of the current
scenario, the optimized plan, the FCFS baseline and any active disruption in
its system prompt. No data leaves the session except that snapshot; nothing is
stored server-side. The API key lives in Streamlit secrets, never in the repo.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import timedelta

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"  # free tier, fast enough to feel instant
MAX_HISTORY_TURNS = 8     # messages (user+assistant) sent back to the model
MAX_USER_MESSAGES = 25    # per-session cap to keep a public demo affordable

SYSTEM_PROMPT = """\
You are the PortOpt Plan Assistant, embedded in PortOpt — an interactive
Operations Research demo that schedules vessels at a Rotterdam Botlek-style
chemical tank terminal. It was built by Ismail Arslan as a portfolio demo;
all data is synthetic.

WHAT THE APP SHOWS
- Sidebar: scenario sliders (vessels, berths/jetties, arrival congestion;
  under Advanced: random seed, tanks, horizon, demurrage level, CP-SAT time
  limit) and a what-if disruption picker (delay one vessel by N hours).
- KPI cards: total plan cost (demurrage + cleaning), waiting hours, tank
  cleanings — each with a delta versus the first-come-first-served baseline.
- Green banner: euros saved versus that baseline.
- Tabs: "The plan" (vessel timeline with ETA diamonds and grey waiting bars,
  berth occupation Gantt, tank allocation chart, schedule table) ·
  "Optimizer vs. human" (cost comparison, per-vessel impact, FCFS timeline) ·
  "Scenario" (vessel/tank/berth data) · "How it works" (the math).
- When a disruption is active, a panel compares: original plan, sticking to
  the old schedule anyway (the cost of NOT re-planning), and the re-optimized
  plan.

HOW THE OPTIMIZATION WORKS
- Solver: Google OR-Tools CP-SAT. Status OPTIMAL means mathematically proven
  best; FEASIBLE means best found within the time limit.
- Decision variables: which berth x[v,b], which tank y[v,k], start time s[v].
- Hard constraints: exactly one berth and one tank per vessel; a tank serves
  at most one vessel in the window; vessel size class must fit the berth
  (S/M/L, nested); product family must match the tank lining (mild steel:
  CPP/aromatics only; epoxy coated: CPP+biofuels; stainless: everything);
  no two vessels overlap on a berth; no vessel starts before its ETA, nor
  before tank cleaning finishes (cleaning starts at t=0).
- Objective: minimize waiting cost + cleaning cost. Waiting cost = waiting
  minutes x the vessel's demurrage day-rate / 1440. Default day-rates:
  S = EUR 9k, M = EUR 18k, L = EUR 30k (times the demurrage slider).
- Berth time = 2h setup (mooring, hoses, paperwork) + volume / pump rate.
- Cleaning is needed when a product goes into an empty tank whose residue is
  a different product (6-14 h, EUR 8-22k, tank-specific).
- Baseline (FCFS): vessels strictly in ETA order at the earliest free berth,
  preferring no-cleaning tanks. The optimizer wins by resequencing, choosing
  slower berths deliberately, or trading a cleaning against waiting.

RULES
- Ground every number in the CURRENT STATE block below. If something is not
  in the data, say so — never invent vessels, costs or times.
- Be concise: aim for under 150 words unless the user asks for depth. Use
  short paragraphs or compact bullets. Format money like "EUR 12,345".
- Small arithmetic on the provided numbers is encouraged; show it briefly.
- Mirror the language of the user's latest message: an English question gets
  an English answer, a Dutch question gets a Dutch answer.
- Stay on topic: this demo, its data, and Operations Research concepts. For
  anything unrelated, politely steer back to the schedule.
- The scenario can change between questions (sliders); the CURRENT STATE
  block is always the truth for *now*.
"""


def get_api_key():
    """Streamlit secrets first, then environment. Returns None if absent."""
    try:
        import streamlit as st
        key = st.secrets.get("GROQ_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("GROQ_API_KEY")


def _fmt_t(t0, minutes):
    return (t0 + timedelta(minutes=int(minutes))).strftime("%a %H:%M")


def build_context(scenario, opt, base, k_opt, k_base, t0, settings,
                  disruption=None):
    """Compact textual snapshot of everything currently on screen."""
    lines = ["CURRENT STATE", "", f"Plan start (t=0): {t0:%A %d %B %Y %H:%M}",
             "Settings: " + json.dumps(settings)]

    lines.append(
        f"KPIs optimized: total EUR {k_opt['total']:,.0f} (demurrage EUR "
        f"{k_opt['demurrage']:,.0f} + cleaning EUR {k_opt['cleaning']:,.0f}), "
        f"waiting {k_opt['wait_h']:.1f} h, cleanings {k_opt['n_clean']}, "
        f"berth utilization {k_opt['utilization'] * 100:.0f}%."
    )
    lines.append(
        f"KPIs FCFS baseline: total EUR {k_base['total']:,.0f} (demurrage EUR "
        f"{k_base['demurrage']:,.0f} + cleaning EUR {k_base['cleaning']:,.0f}), "
        f"waiting {k_base['wait_h']:.1f} h, cleanings {k_base['n_clean']}. "
        f"Optimizer saves EUR {k_base['total'] - k_opt['total']:,.0f}."
    )

    lines.append("")
    lines.append("OPTIMIZED PLAN (vessel | class | op | product | m3 | ETA | "
                 "berth | tank | start | end | wait h | demurrage EUR | cleaning):")
    for e in sorted(opt["entries"], key=lambda e: e["start"]):
        lines.append(
            f"- {e['vessel']} | {e['size']} | {e['op']} | {e['product']} | "
            f"{e['volume']:,} | {_fmt_t(t0, e['eta'])} | {e['berth']} | "
            f"{e['tank']} | {_fmt_t(t0, e['start'])} | {_fmt_t(t0, e['end'])} | "
            f"{e['wait'] / 60:.1f} | {e['demurrage']:,.0f} | "
            f"{'yes EUR ' + format(e['clean_cost'], ',.0f') if e['clean'] else 'no'}"
        )

    lines.append("")
    lines.append("FCFS BASELINE (vessel | berth | tank | start | wait h | "
                 "demurrage EUR | cleaning EUR):")
    for e in sorted(base["entries"], key=lambda e: e["start"]):
        lines.append(
            f"- {e['vessel']} | {e['berth']} | {e['tank']} | "
            f"{_fmt_t(t0, e['start'])} | {e['wait'] / 60:.1f} | "
            f"{e['demurrage']:,.0f} | {e['clean_cost']:,.0f}"
        )

    lines.append("")
    lines.append("BERTHS (name | max class | pump m3/h): " + "; ".join(
        f"{b.name} | {b.max_size} | {b.pump_rate:,}" for b in scenario.berths))

    lines.append("TANKS (name | lining | cap m3 | level m3 | product | residue "
                 "| clean h | clean EUR):")
    for t in scenario.tanks:
        lines.append(
            f"- {t.name} | {t.lining} | {t.capacity:,} | {t.level:,} | "
            f"{t.product.name if t.product else 'empty'} | "
            f"{t.last_product.name if (t.product is None and t.last_product) else '-'} | "
            f"{t.clean_hours} | {t.clean_cost:,.0f}"
        )

    if disruption:
        lines.append("")
        lines.append(
            f"ACTIVE DISRUPTION: {disruption['vessel']} arrives "
            f"{disruption['delay_h']} h late. Original optimum EUR "
            f"{disruption['original']:,.0f}; executing the old schedule anyway "
            f"EUR {disruption['frozen']:,.0f}; re-optimized plan EUR "
            f"{disruption['reoptimized']:,.0f}. Re-planning saves EUR "
            f"{disruption['frozen'] - disruption['reoptimized']:,.0f}."
        )

    return "\n".join(lines)


def suggested_questions(entries, k_opt, k_base):
    """Two or three grounded, demo-flattering starter questions."""
    qs = []
    waiting = [e for e in entries if e["wait"] > 0]
    if waiting:
        worst = max(waiting, key=lambda e: e["wait"])
        qs.append(
            f"Why does {worst['vessel']} wait {worst['wait'] / 60:.1f} h, "
            "and what would have to change to avoid it?"
        )
    saved = k_base["total"] - k_opt["total"]
    if saved > 0.5:
        qs.append(
            f"Where exactly does this plan save € {saved:,.0f} versus "
            "first-come-first-served?"
        )
    qs.append("Which single extra berth or tank would improve this week the most?")
    if len(qs) < 3:
        qs.append("Walk me through how the optimizer built this schedule.")
    return qs[:3]


def _post_with_retry(api_key, payload):
    """POST to Groq, retrying on free-tier 429s (the response says how long
    to wait) and transient 5xx errors before giving up with a clear message."""
    for attempt in range(3):
        resp = requests.post(GROQ_URL, json=payload, stream=True, timeout=60,
                             headers={"Authorization": f"Bearer {api_key}"})
        if resp.status_code == 200:
            return resp
        status, detail = resp.status_code, resp.text[:200]
        if attempt < 2 and status == 429:
            m = re.search(r"try again in ([0-9.]+)s", resp.text)
            try:
                wait = float(resp.headers.get("retry-after") or
                             (m.group(1) if m else 3.0))
            except ValueError:
                wait = 3.0
            resp.close()
            time.sleep(min(wait + 0.4, 9.0))
            continue
        if attempt < 2 and status >= 500:
            resp.close()
            time.sleep(1.5)
            continue
        resp.close()
        if status == 429:
            raise RuntimeError("the free Groq tier hit its tokens-per-minute "
                               "limit and stayed busy after retries — wait "
                               "~30 seconds and ask again.")
        raise RuntimeError(f"Groq API {status}: {detail}")
    raise RuntimeError("Groq API unavailable after retries.")


def stream_reply(api_key, context, history):
    """Stream a grounded answer from Groq. Yields text deltas."""
    messages = (
        [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + context}]
        + history[-MAX_HISTORY_TURNS:]
    )
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 700,
        "stream": True,
    }
    with _post_with_retry(api_key, payload) as resp:
        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8")
            if not line.startswith("data: "):
                continue
            data = line[len("data: "):]
            if data == "[DONE]":
                break
            delta = json.loads(data)["choices"][0].get("delta", {})
            chunk = delta.get("content")
            if chunk:
                yield chunk

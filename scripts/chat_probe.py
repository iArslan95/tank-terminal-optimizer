"""End-to-end probe of the Plan Assistant: solve a scenario, build the
grounded context, ask Groq one question, print the answer. Needs a key in
.streamlit/secrets.toml or the GROQ_API_KEY environment variable.

    python scripts/chat_probe.py
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import assistant  # noqa: E402
from optimizer import baseline, data, kpis, model  # noqa: E402


def main():
    key = assistant.get_api_key()
    if not key:
        sys.exit("No GROQ_API_KEY found in secrets or environment.")

    scenario = data.generate(5, n_vessels=10, n_berths=3, n_tanks=14,
                             horizon_days=5, congestion=0.9)
    opt = model.solve(scenario, time_limit_s=10)
    base = baseline.fcfs(scenario)
    k_opt = kpis.compute(opt["entries"], scenario)
    k_base = kpis.compute(base["entries"], scenario)

    context = assistant.build_context(
        scenario, opt, base, k_opt, k_base, datetime(2026, 6, 11, 6, 0),
        settings={"seed": 5, "vessels": 10, "berths": 3, "tanks": 14},
    )
    question = ("Which vessel waits longest in the optimized plan, and why "
                "does the optimizer still beat FCFS overall? Max 3 sentences.")
    reply = "".join(assistant.stream_reply(
        key, context, [{"role": "user", "content": question}]))

    print("Q:", question)
    print("A:", reply)
    assert len(reply) > 40, "suspiciously short reply"
    print("CHAT PROBE OK")


if __name__ == "__main__":
    main()

"""Headless UI test via streamlit.testing: load the app, activate a what-if
disruption through the sidebar selectbox, and assert the disruption panel
renders without exceptions. Run from the project root:

    python scripts/ui_test.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.run()
    assert not at.exception, f"app raised on default run: {at.exception}"
    assert len(at.metric) == 3, f"expected 3 KPI metrics, got {len(at.metric)}"
    assert len(at.chat_input) == 1, "Plan Assistant chat input should render"

    box = at.selectbox[0]
    vessel = next(o for o in box.options if o != "— none —")
    box.select(vessel)
    at.run()
    assert not at.exception, f"app raised with disruption active: {at.exception}"
    assert len(at.metric) == 6, (
        f"expected 3 disruption + 3 KPI metrics, got {len(at.metric)}"
    )
    labels = [m.label for m in at.metric]
    for expected in ("Original plan (no disruption)", "Stick to the old schedule",
                     "Re-optimized plan"):
        assert expected in labels, f"missing metric '{expected}' in {labels}"

    print(f"disrupted vessel: {vessel}")
    print("metrics:", " | ".join(f"{m.label}={m.value}" for m in at.metric[:3]))
    print("UI DISRUPTION TEST OK")


if __name__ == "__main__":
    main()

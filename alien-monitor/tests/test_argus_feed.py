"""Argus run feed — demo only in TEST mode."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from argus_feed import DEFAULT_ARGUS_RUN, argus_run_for_mode, clear_argus_run, set_argus_run  # noqa: E402


def test_demo_only_in_test_mode():
    clear_argus_run()
    assert argus_run_for_mode("test") == DEFAULT_ARGUS_RUN
    assert argus_run_for_mode("real") is None
    assert argus_run_for_mode("universe") is None


def test_fresh_run_wins_in_live_modes():
    clear_argus_run()
    payload = {"id": "run_live_1", "goal": "live goal", "beats": [], "spendUsd": 0.01}
    set_argus_run(payload)
    live = argus_run_for_mode("real")
    assert live is not None
    assert live["id"] == "run_live_1"
    assert argus_run_for_mode("test")["id"] == "run_live_1"
    clear_argus_run()

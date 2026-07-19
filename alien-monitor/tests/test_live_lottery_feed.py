"""A poisoned relayer feed must never reach the frontend as a non-number or junk.

Guards F2: an injected event with a non-numeric `amount` used to crash the Monitor
activity render (`amount.toFixed(...)`) for every viewer. set_live_lottery now coerces
amounts to finite floats, length-caps strings, and drops non-dict events.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from live_lottery_feed import (
    clear_live_lottery,
    live_metrics_if_fresh,
    lottery_events_if_fresh,
    set_live_lottery,
)


def test_poisoned_feed_is_sanitized():
    clear_live_lottery()
    set_live_lottery({
        "mode": "uni",
        "metrics": {"prize_pool_usd": "NaN", "round": 21, "players": "3", "opex_24h": float("inf")},
        "last_winner": "x" * 200,
        "events": [
            {"agent": "Echo", "amount": "not-a-number", "action": "ticket"},  # bad amount
            {"agent": "Aria", "amount": 1.5},
            "junk-not-a-dict",                                                # dropped
            {"agent": "Z" * 500, "amount": float("nan")},                    # capped + coerced
        ],
    })

    events = lottery_events_if_fresh()
    assert len(events) == 3  # the non-dict event is dropped
    for e in events:
        assert isinstance(e["amount"], float) and math.isfinite(e["amount"])  # never crashes toFixed
        assert len(e["agent"]) <= 64

    metrics = live_metrics_if_fresh()
    assert all(isinstance(v, float) and math.isfinite(v) for v in metrics.values())  # NaN/inf scrubbed
    assert metrics["players"] == 3.0  # numeric string coerced


def test_stale_feed_is_not_served():
    clear_live_lottery()
    assert live_metrics_if_fresh() is None
    assert lottery_events_if_fresh() == []

"""Connectivity: the relayer→monitor live-feed CONTRACT.

The relayer PUSHES {mode, metrics{...}, last_winner, events} to the monitor's
POST /api/lottery/update (economy.py). If the relayer's metric keys and the monitor's
consumed keys ever drift, the live lottery node silently shows zeros. This test pins
both ends so either-side drift fails CI.
"""
from __future__ import annotations

import sys
from pathlib import Path

from ailottery_relayer.monitor import MONITOR_METRIC_KEYS, build_monitor_metrics


def _alien_monitor_backend() -> Path:
    """Monorepo: …/lottery/relayer/tests → parents[3]. Satellite: parents[2] at repo root."""
    here = Path(__file__).resolve()
    for anchor in (here.parents[2], here.parents[3]):
        candidate = anchor / "alien-monitor" / "backend"
        if (candidate / "live_lottery_feed.py").is_file():
            return candidate
    raise RuntimeError(
        "alien-monitor backend not found — CI clones alexar76/alien-monitor beside lottery/"
    )


# import the CONSUMER (monitor backend) — lightweight module (stdlib only)
_MON = _alien_monitor_backend()
sys.path.insert(0, str(_MON))
from live_lottery_feed import (
    _LIVE_METRIC_KEYS,
    clear_live_lottery,
    live_metrics_if_fresh,
    lottery_events_if_fresh,
    set_live_lottery,
)


def test_economy_resolves_build_monitor_metrics():
    # Regression: snapshot() builds metrics via build_monitor_metrics — it MUST be imported
    # into economy, or /economy + the monitor push 500 at runtime (unit tests don't exercise
    # snapshot() since it needs a live chain, so guard the name resolution explicitly).
    import ailottery_relayer.economy as economy

    assert hasattr(economy, "build_monitor_metrics")


def test_economy_snapshot_module_builds_metrics():
    from ailottery_relayer import economy_snapshot

    assert economy_snapshot.build_snapshot is not None
    assert economy_snapshot.publish_snapshot is not None


def test_metric_key_contract_matches_both_ends():
    # producer (relayer) and consumer (monitor) must agree on the exact metric keys.
    assert tuple(MONITOR_METRIC_KEYS) == tuple(_LIVE_METRIC_KEYS)


def test_relayer_payload_round_trips_through_monitor():
    clear_live_lottery()
    payload = {
        "mode": "uni",
        "last_winner": "CodeNova",
        "metrics": build_monitor_metrics(
            prize_pool_usd=42.0, round=7, players=5, payouts_24h=10.0, opex_24h=2.0, funding_24h=8.0
        ),
        "events": [{"agent": "CodeNova", "action": "ticket", "target": "lottery", "amount": 1.0, "token": "USDC", "id": "x"}],
    }
    set_live_lottery(payload)
    served = live_metrics_if_fresh()
    assert served is not None
    for k in MONITOR_METRIC_KEYS:
        assert k in served, f"metric {k} silently dropped on the relayer→monitor feed"
    assert served["round"] == 7 and served["players"] == 5 and served["prize_pool_usd"] == 42.0
    assert len(lottery_events_if_fresh()) == 1  # financial-flow events propagate

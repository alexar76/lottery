"""In-memory live lottery snapshot pushed by the UNI/demo relayer.

Hardened against a poisoned/garbage feed: numeric fields are coerced to finite
numbers and string fields are length-capped, so a malformed push can never reach
the frontend as a non-number (which would crash `amount.toFixed(...)` for every
viewer) or as an unbounded string.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

LIVE_LOTTERY_TTL = 30.0
_LIVE_LOTTERY: dict = {"ts": 0.0, "mode": "", "metrics": {}, "events": [], "last_winner": ""}
_LIVE_METRIC_KEYS = ("prize_pool_usd", "round", "players", "payouts_24h", "opex_24h", "funding_24h")
_MAX_EVENTS = 40


def _finite(value, default: float = 0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _clean_event(e) -> dict:
    e = e if isinstance(e, dict) else {}
    return {
        "ts": str(e.get("ts", ""))[:32],
        "agent": str(e.get("agent", ""))[:64],
        "action": str(e.get("action", ""))[:32],
        "target": str(e.get("target", ""))[:48],
        "amount": _finite(e.get("amount", 0)),   # always a finite number → safe .toFixed
        "token": str(e.get("token", ""))[:16],
        "id": str(e.get("id", ""))[:64],
    }


def set_live_lottery(payload: dict) -> None:
    metrics = payload.get("metrics") or {}
    events = payload.get("events") or []
    _LIVE_LOTTERY["ts"] = datetime.now(UTC).timestamp()
    _LIVE_LOTTERY["mode"] = str(payload.get("mode", ""))[:16]
    _LIVE_LOTTERY["metrics"] = {k: _finite(metrics.get(k, 0)) for k in _LIVE_METRIC_KEYS}
    _LIVE_LOTTERY["last_winner"] = str(payload.get("last_winner", ""))[:64]
    _LIVE_LOTTERY["events"] = [_clean_event(e) for e in events[-_MAX_EVENTS:] if isinstance(e, dict)]


def live_lottery_fresh() -> bool:
    return bool(_LIVE_LOTTERY["metrics"]) and (
        datetime.now(UTC).timestamp() - _LIVE_LOTTERY["ts"] < LIVE_LOTTERY_TTL
    )


def live_metrics_if_fresh() -> dict | None:
    if not live_lottery_fresh():
        return None
    return dict(_LIVE_LOTTERY["metrics"])


def lottery_events_if_fresh() -> list[dict]:
    if not live_lottery_fresh():
        return []
    return list(_LIVE_LOTTERY["events"])


def clear_live_lottery() -> None:
    """Test helper — drop stale relayer snapshot."""
    _LIVE_LOTTERY.update(ts=0.0, mode="", metrics={}, events=[], last_winner="")

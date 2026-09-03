"""Best-effort live feed to the Alien Monitor.

The monitor has no inbound lottery endpoint by default; this build adds a minimal
`POST /api/lottery/update` to alien-monitor/backend/main.py. If MONITOR_URL is set,
the relayer pushes its real economy snapshot + recent financial-flow events each
cycle, and the monitor renders them on the live `lottery` node instead of the
simulation. If the monitor or endpoint is absent, this silently no-ops.
"""
from __future__ import annotations

import httpx

from .log import get_logger

log = get_logger("monitor")

# ── relayer→monitor feed CONTRACT ────────────────────────────────────────────
# The metric keys the relayer PUSHES and the monitor CONSUMES must agree exactly,
# or the live lottery node silently shows zeros. This tuple is the single source of
# truth on the relayer side; the monitor's `_LIVE_METRIC_KEYS` must equal it (asserted
# by the relayer↔monitor connectivity test). Change one → change both.
MONITOR_METRIC_KEYS = ("prize_pool_usd", "round", "players", "payouts_24h", "opex_24h", "funding_24h")


def build_monitor_metrics(
    *, prize_pool_usd: float, round: int, players: int,
    payouts_24h: float, opex_24h: float, funding_24h: float,
) -> dict:
    """Build the metrics block keyed by MONITOR_METRIC_KEYS (the feed contract)."""
    return {
        "prize_pool_usd": prize_pool_usd,
        "round": round,
        "players": players,
        "payouts_24h": payouts_24h,
        "opex_24h": opex_24h,
        "funding_24h": funding_24h,
    }


class MonitorFeed:
    def __init__(self, monitor_url: str, token: str = ""):
        self.url = monitor_url.rstrip("/") if monitor_url else ""
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx.Client(timeout=4.0) if self.url else None
        self._warned = False

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def push(self, payload: dict) -> None:
        if not self.enabled:
            return
        try:
            resp = self._http.post(
                f"{self.url}/api/lottery/update", json=payload, headers=self._headers
            )
            # A 401/403 means our MONITOR_TOKEN doesn't match the monitor's ALIEN_API_TOKEN —
            # the feed is silently rejected. Surface it once instead of looking "live".
            if resp.status_code >= 400 and not self._warned:
                hint = " (check MONITOR_TOKEN == monitor ALIEN_API_TOKEN)" if resp.status_code in (401, 403) else ""
                log.warning("monitor feed rejected: HTTP %s%s", resp.status_code, hint)
                self._warned = True
        except Exception as exc:
            if not self._warned:
                log.info("monitor feed unavailable (%s) — continuing", exc)
                self._warned = True

    def close(self) -> None:
        if self._http:
            self._http.close()

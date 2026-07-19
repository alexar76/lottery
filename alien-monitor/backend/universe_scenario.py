"""
Universe Scenario Engine — orchestrates self-evolving UNI economy.

Phases: BOOTSTRAP → EXPANSION → FEDERATION → MATURITY.
Each tick advances the scenario, checks phase transitions, and fires
phase-specific actions (buyer rounds, funding injections, hub spawns).

The ONLY synthetic element is external funding. Everything else —
purchases, channels, invocations, federation — uses real Hub API calls.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from universe_external_buyer import ExternalAIBuyer
from universe_funding import UniverseFundingStream
from universe_hub_spawner import HubSpawner

if TYPE_CHECKING:
    from universe import VirtualUniverse

DEFAULT_PHASE_CONFIG = {
    "BOOTSTRAP": {"min_ticks": 40, "min_products": 3},
    "EXPANSION": {"min_ticks": 150, "min_invocations": 20, "min_funding_usd": 200},
    "FEDERATION": {"min_ticks": 350, "min_fed_hubs": 3, "min_total_supply": 1000},
    "MATURITY": {},
}

PHASE_COLORS = {
    "BOOTSTRAP": "#4488ff",
    "EXPANSION": "#44ff88",
    "FEDERATION": "#ff44ff",
    "MATURITY": "#ffdd44",
}


class UniverseScenarioEngine:
    """Orchestrates the self-evolving UNI timeline."""

    def __init__(self, hub_url: str = "http://127.0.0.1:9083", config: dict | None = None):
        self.phase = "BOOTSTRAP"
        self.phase_started_at = time.time()
        self.tick_count = 0
        self.config = config or DEFAULT_PHASE_CONFIG

        self.external_buyer = ExternalAIBuyer(hub_url=hub_url)
        self.funding_stream = UniverseFundingStream()
        self.hub_spawner = HubSpawner(hub_url=hub_url)

        self.events: list[dict] = []
        self.total_invocations = 0

    def tick(self, vu: VirtualUniverse) -> dict:
        self.tick_count += 1

        new_phase = self._check_phase_transition(vu)
        if new_phase:
            self.phase = new_phase
            self.phase_started_at = time.time()
            self.events.append({
                "type": "phase_changed",
                "phase": new_phase,
                "tick": self.tick_count,
                "ts": time.time(),
            })
            if new_phase == "EXPANSION":
                self.funding_stream.ensure_hub_liquidity(vu)
                initial = self.funding_stream.inject_initial_external_funding(self.tick_count, vu)
                if initial:
                    self.events.append(initial)

        self._execute_phase_actions(vu)

        events = list(self.events)
        self.events.clear()
        return {
            "phase": self.phase,
            "phase_progress": self.get_phase_progress(vu),
            "phase_color": PHASE_COLORS.get(self.phase, "#00f0ff"),
            "tick_count": self.tick_count,
            "funding_total": self.funding_stream.total_funding,
            "hub_count": len(self.hub_spawner.spawned_hubs),
            "buyer_rounds": self.external_buyer.rounds_completed,
            "total_invocations": self.total_invocations,
            "events": events,
        }

    def _check_phase_transition(self, vu: VirtualUniverse) -> str | None:
        cfg = self.config.get(self.phase, {})
        if not cfg:
            return None

        products_count = len(vu.products)

        if self.phase == "BOOTSTRAP":
            if self.tick_count >= cfg["min_ticks"] and products_count >= cfg["min_products"]:
                print(f"[Scenario] BOOTSTRAP → EXPANSION (tick={self.tick_count}, products={products_count})")
                return "EXPANSION"

        elif self.phase == "EXPANSION":
            if (self.tick_count >= cfg["min_ticks"]
                    and self.total_invocations >= cfg["min_invocations"]
                    and self.funding_stream.total_funding >= cfg["min_funding_usd"]):
                print(f"[Scenario] EXPANSION → FEDERATION (tick={self.tick_count}, invocations={self.total_invocations}, funding={self.funding_stream.total_funding})")
                return "FEDERATION"

        elif self.phase == "FEDERATION":
            if (self.tick_count >= cfg["min_ticks"]
                    and len(self.hub_spawner.spawned_hubs) >= cfg["min_fed_hubs"]
                    and self.funding_stream.total_funding >= cfg["min_total_supply"]):
                print(f"[Scenario] FEDERATION → MATURITY (tick={self.tick_count}, hubs={len(self.hub_spawner.spawned_hubs)})")
                return "MATURITY"

        return None

    def _execute_phase_actions(self, vu: VirtualUniverse) -> None:
        if self.phase in ("BOOTSTRAP",):
            return

        buyer_interval = 8 if self.phase == "EXPANSION" else 5
        funding_interval = self.funding_stream.interval_ticks
        if self.phase != "EXPANSION":
            funding_interval = max(150, int(funding_interval * 0.75))
        spawn_interval = None if self.phase == "EXPANSION" else 300

        self.funding_stream.update_growth_multiplier(
            vu, fed_hub_count=len(self.hub_spawner.spawned_hubs)
        )

        if self.tick_count % buyer_interval == 0:
            try:
                result = self.external_buyer.execute_round(vu)
                self.total_invocations += result.get("purchases", 0)
                if result.get("events"):
                    self.events.extend(result["events"])
            except Exception as exc:
                print(f"[Scenario] Buyer round failed: {exc}")

        if self.tick_count > 0 and self.tick_count % funding_interval == 0:
            try:
                result = self.funding_stream.tick(self.tick_count, vu)
                if result:
                    self.events.append(result)
            except Exception as exc:
                print(f"[Scenario] Funding tick failed: {exc}")

        if spawn_interval and self.tick_count % spawn_interval == 0:
            try:
                result = self.hub_spawner.tick(self.tick_count, vu)
                if result:
                    self.events.append(result)
            except Exception as exc:
                print(f"[Scenario] Hub spawn failed: {exc}")

    def get_phase_progress(self, vu: VirtualUniverse) -> float:
        cfg = self.config.get(self.phase, {})
        if not cfg:
            return 1.0

        if self.phase == "BOOTSTRAP":
            tick_prog = min(self.tick_count / cfg["min_ticks"], 1.0)
            prod_prog = min(len(vu.products) / cfg["min_products"], 1.0)
            return (tick_prog + prod_prog) / 2

        if self.phase == "EXPANSION":
            tick_prog = min(self.tick_count / cfg["min_ticks"], 1.0)
            inv_prog = min(self.total_invocations / cfg["min_invocations"], 1.0)
            fund_prog = min(self.funding_stream.total_funding / cfg["min_funding_usd"], 1.0)
            return (tick_prog + inv_prog + fund_prog) / 3

        if self.phase == "FEDERATION":
            tick_prog = min(self.tick_count / cfg["min_ticks"], 1.0)
            hub_prog = min(len(self.hub_spawner.spawned_hubs) / cfg["min_fed_hubs"], 1.0)
            fund_prog = min(self.funding_stream.total_funding / cfg["min_total_supply"], 1.0)
            return (tick_prog + hub_prog + fund_prog) / 3

        return 1.0

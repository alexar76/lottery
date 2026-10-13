"""Sponsor policy — the runtime enforcement of "the Hub funds ONLY its own bound
lottery, and nothing at all if that lottery isn't deployed" («деньги не увести»).

This is the code behind the documented guarantee. Before the economy engine sends
a single tithe it must pass `resolve_bound()`:

  1. only_funds_bound_lottery: a NON-zero `lottery_address` in sponsor.yaml that
     does not equal the lottery the relayer is actually operating  →  REFUSE.
     The charitable flow can never be redirected to another address.
  2. requires_deployed_lottery: no contract code at the bound address  →  donate
     NOTHING. The mode is inert until a real bound lottery exists.
  3. zero/placeholder address: in demo/uni the relayer self-binds to the lottery
     it just deployed (for the showcase); in LIVE this means "no bound lottery"
     → donate nothing, so an unconfigured live setup can never move funds.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from web3 import Web3

from .config import Config
from .log import get_logger

log = get_logger("sponsor")
ZERO = "0x0000000000000000000000000000000000000000"


@dataclass
class Binding:
    ok: bool
    address: Optional[str]
    reason: str


class SponsorPolicy:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.s = (cfg.sponsor or {}).get("sponsor", {}) or {}

    @property
    def enabled(self) -> bool:
        # the DONOR (Hub) decides whether it is charitable; sponsor.yaml is the demo default
        if self.cfg.hub_charity_enabled is not None:
            return self.cfg.hub_charity_enabled
        return bool(self.s.get("enabled", False))

    def tithe_bps(self) -> int:
        # the tithe RATE is Hub-owned (the donor's generosity). HUB_TITHE_BPS overrides
        # the sponsor.yaml demo default / per-mode value.
        if self.cfg.hub_tithe_bps >= 0:
            return self.cfg.hub_tithe_bps
        modes = (self.cfg.sponsor or {}).get("modes", {}) or {}
        mode_cfg = modes.get(self.cfg.mode, {}) or {}
        return int(mode_cfg.get("tithe_bps", self.s.get("tithe_bps", 0)))

    def resolve_bound(self, deployed_address: str, w3: Web3) -> Binding:
        if not self.enabled:
            return Binding(False, None, "sponsor disabled in config")

        # the Hub (donor) picks which lottery it funds; HUB_LOTTERY_ADDRESS overrides
        cfg_addr = (self.cfg.hub_lottery_address or self.s.get("lottery_address") or ZERO)
        deployed = Web3.to_checksum_address(deployed_address)

        if int(cfg_addr, 16) == 0:
            if self.cfg.mode in ("demo", "uni"):
                bound = deployed  # self-bind to the just-deployed lottery (showcase)
                note = "self-bound to deployed lottery (demo/uni)"
            else:
                return Binding(False, None,
                               "no bound lottery configured (live) → donate nothing")
        else:
            bound = Web3.to_checksum_address(cfg_addr)
            if bound != deployed:
                # THE anti-redirect guarantee.
                return Binding(False, None,
                               f"configured bound address {bound} != operating lottery "
                               f"{deployed} → REFUSE (anti-redirect)")
            note = "bound to configured lottery_address"

        # requires_deployed_lottery: there must be code at the bound address.
        if self.s.get("requires_deployed_lottery", True):
            code = w3.eth.get_code(bound)
            if not code or len(code) == 0:
                return Binding(False, None, f"no contract code at {bound} → donate nothing")

        return Binding(True, bound, note)

    def tithe_usd(self, hub_routing_revenue_usd: float) -> float:
        """20% (default) of the Hub's routing-fee revenue for the period."""
        return round(hub_routing_revenue_usd * self.tithe_bps() / 10_000, 6)

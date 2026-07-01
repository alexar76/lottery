"""The economy engine — drives a full lottery round end to end and models the
circular AI economy.

See module docstring in the original design: open → agents buy tickets → Hub tithes →
UNI benefactor → close/commit → Platon + Chronos → draw → settle → repeat.
"""
from __future__ import annotations

import time

from eth_account import Account
from web3 import Web3

from .chain import Chain
from .config import Config
from .economy_draw import close_and_draw
from .economy_snapshot import LINE_TARGET, build_snapshot, name_for_addr, publish_snapshot, record_event
from .log import get_logger
from .mesh import MeshClient
from .monitor import MonitorFeed, build_monitor_metrics
from .oracles import PRICE, OpexLedger, OracleClient
from .roster import Participant, mesh_roster, synthetic_roster, uni_wallet_roster
from .sponsor import SponsorPolicy
from .treasurer import Treasurer

log = get_logger("economy")

# Re-export roster API (tests + integrators import from economy).
__all__ = [
    "EconomyEngine",
    "Participant",
    "derive_agent_key",
    "mesh_roster",
    "synthetic_roster",
    "uni_wallet_roster",
]

from .roster import derive_agent_key  # noqa: E402  (re-export)


class EconomyEngine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        addr = cfg.resolved_address()
        if not addr:
            raise SystemExit("No lottery address — set LOTTERY_ADDRESS or wait for the deploy step.")
        self.chain = Chain(cfg.rpc_url, cfg.chain_id, addr)
        self.ledger = OpexLedger()
        self.oracles = OracleClient(cfg, self.ledger)
        self.sponsor = SponsorPolicy(cfg)
        self.monitor = MonitorFeed(cfg.monitor_url, cfg.monitor_token)
        self.mesh = MeshClient(cfg)

        self.events: list[dict] = []
        self.last_winner = ""
        self.state: dict = {}
        self._uni_round_counter = 0
        self._hub_revenue_accum = 0.0
        self._last_tithe_ts = 0.0
        self._prev_players = 0
        self.last_opex_plan = None
        self.treasurer = Treasurer(cfg, self.oracles)
        self._running = True

        self.fn = self.chain.contract.functions
        self.operator_key = cfg.operator_key
        self.signer_key = cfg.oracle_signer_key
        self.treasury_key = cfg.treasury_key
        self.sponsor_key = cfg.sponsor_key
        self.benefactor_key = cfg.benefactor_key
        self.agent_keys = cfg.agent_keys
        self._agent_addr = [Account.from_key(k).address for k in self.agent_keys]
        self._key_by_addr = {Account.from_key(k).address: k for k in self.agent_keys}
        self._roster: list[Participant] = []
        self._name_by_addr: dict[str, str] = {}
        self._refresh_roster()

        self.binding = self.sponsor.resolve_bound(self.chain.address, self.chain.w3)
        log.info("sponsor binding: ok=%s addr=%s — %s",
                 self.binding.ok, self.binding.address, self.binding.reason)

    def _refresh_roster(self) -> None:
        if self.mesh.enabled:
            cap = self.cfg.mesh_max_agents if self.cfg.uni_auto_wallet \
                else min(len(self.agent_keys), self.cfg.mesh_max_agents)
            agents = self.mesh.fetch_agents(max(0, cap))
            if agents:
                if self.cfg.uni_auto_wallet:
                    self._roster = uni_wallet_roster(agents, self.cfg.uni_wallet_seed)
                    self._fund_and_bind_roster()
                else:
                    self._roster = mesh_roster(agents, self.agent_keys, self._agent_addr)
                self._name_by_addr = {p.addr: p.name for p in self._roster}
                return
            if any(p.source == "mesh" for p in self._roster):
                return
        if not self.agent_keys:
            self._roster, self._name_by_addr = [], {}
            return
        self._roster = synthetic_roster(self.agent_keys, self._agent_addr)
        self._name_by_addr = {p.addr: p.name for p in self._roster}

    def _fund_and_bind_roster(self) -> None:
        for p in self._roster:
            if p.source != "mesh":
                continue
            try:
                if self.chain.balance(p.addr) < self.cfg.agent_fund_wei:
                    self.chain.transfer(self.cfg.faucet_key, p.addr, self.cfg.agent_fund_wei)
            except Exception as exc:
                log.warning("funding agent %s (%s) failed: %s", p.name, p.addr, exc)
            if p.mesh_id and p.wallet:
                self.mesh.bind_wallet(p.mesh_id, p.wallet)

    @property
    def roster_source(self) -> str:
        return "mesh" if any(p.source == "mesh" for p in self._roster) else "synthetic"

    def _name(self, addr: str) -> str:
        return name_for_addr(self, addr)

    def _event(self, agent: str, action: str, target: str, amount_usd: float) -> None:
        record_event(self, agent, action, target, amount_usd)

    def open_round(self) -> int:
        self.chain.send(self.fn.openRound(), self.operator_key)
        rid = self.chain.current_round_id()
        log.info("round %s opened", rid)
        self._event("operator", "open", f"round {rid}", 0)
        return rid

    def sell_tickets(self, rid: int) -> None:
        if not self.cfg.sim_agents:
            return
        self._refresh_roster()
        if not self._roster:
            return
        price = self.chain.ticket_price()
        now = self.chain.block()["timestamp"]
        expiry = now + 86_400
        bonuses, _ = self.oracles.lumen_reputation([p.addr for p in self._roster])
        self._event("lottery", "invoke", "LUMEN", PRICE["lumen.reputation@v1"])
        for i, p in enumerate(self._roster):
            count = 1 + (i % 3)
            cost_usd = self.cfg.wei_to_usd(price * count)
            bonus = p.trust_bps if p.source == "mesh" else min(int(bonuses.get(p.addr, 0)), 5000)
            try:
                if bonus > 0:
                    sig = self.chain.sign_voucher(self.signer_key, p.addr, rid, bonus, expiry)
                    self.chain.send(
                        self.fn.buyTicketsWithVoucher(rid, count, bonus, expiry, sig),
                        p.key, value=price * count)
                    self._event(p.name, "ticket+rep", "lottery", cost_usd)
                else:
                    self.chain.send(self.fn.buyTickets(rid, count), p.key, value=price * count)
                    self._event(p.name, "ticket", "lottery", cost_usd)
            except Exception as exc:
                log.warning("agent %s buy failed: %s", p.name, exc)

    def apply_sponsor_tithe(self, rid: int) -> None:
        if not self.binding.ok:
            return
        self._hub_revenue_accum += self.cfg.hub_routing_revenue_usd
        interval = self.cfg.demo_tithe_interval_s if self.cfg.is_demo else self.cfg.hub_tithe_interval_hours * 3600
        now = time.time()
        if now - self._last_tithe_ts < interval:
            return
        tithe_usd = self.sponsor.tithe_usd(self._hub_revenue_accum)
        self._last_tithe_ts = now
        if tithe_usd <= 0:
            return
        assert Web3.to_checksum_address(self.binding.address) == self.chain.address
        amt = self.cfg.usd_to_wei(tithe_usd)
        try:
            self.chain.send(self.fn.fund(rid, amt), self.sponsor_key, value=amt)
            self._event("Hub", "scheduled-tithe", "lottery", tithe_usd)
            log.info("Hub scheduled tithe $%.4f → round %s (every %sh, from $%.2f accrued routing revenue)",
                     tithe_usd, rid, self.cfg.hub_tithe_interval_hours, self._hub_revenue_accum)
            self._hub_revenue_accum = 0.0
        except Exception as exc:
            log.warning("tithe failed: %s", exc)

    def apply_uni_benefactor(self, rid: int) -> None:
        if not self.cfg.is_uni:
            return
        self._uni_round_counter += 1
        if self._uni_round_counter < 7:
            return
        self._uni_round_counter = 0
        amt = self.cfg.usd_to_wei(self.cfg.uni_weekly_usd)
        try:
            self.chain.send(self.fn.fund(rid, amt), self.benefactor_key, value=amt)
            self._event("Unknown benefactor", "weekly-grant", "lottery", self.cfg.uni_weekly_usd)
            log.info("UNI external benefactor allocated $%.2f → round %s", self.cfg.uni_weekly_usd, rid)
        except Exception as exc:
            log.warning("benefactor funding failed: %s", exc)

    def close_and_draw(self, rid: int) -> bool:
        return close_and_draw(self, rid)

    def settle(self, rid: int) -> None:
        r = self.chain.get_round(rid)
        winner = r["winner"]
        key = self._key_by_addr.get(winner)
        if key and not r["prizeClaimed"]:
            try:
                self.chain.send(self.fn.claimPrize(rid), key)
                self._event(self._name(winner), "claim", "lottery", self.cfg.wei_to_usd(r["prizePool"]))
            except Exception as exc:
                log.warning("claim failed: %s", exc)

        round_opex_wei = (r["ticketRevenue"] + r["funding"]) * r["sOpexBps"] // 10_000
        round_opex_usd = self.cfg.wei_to_usd(round_opex_wei)
        econ = self.chain.economy()
        players = self.chain.participants_count(rid)
        if self.cfg.treasurer_enabled and round_opex_usd > 0:
            ctx = {"players": players, "prev_players": self._prev_players,
                   "prize_pool_usd": self.cfg.wei_to_usd(r["prizePool"]),
                   "reserve_usd": self.cfg.wei_to_usd(econ["opexAvailable"])}
            plan = self.treasurer.plan(round_opex_usd, ctx)
            self.last_opex_plan = plan
            spend_wei = min(econ["opexAvailable"], self.cfg.usd_to_wei(plan.spend_total))
            if spend_wei > 0:
                try:
                    to = Account.from_key(self.treasury_key).address
                    self.chain.send(self.fn.withdrawOpex(to, spend_wei), self.treasury_key)
                except Exception as exc:
                    log.warning("opex withdraw failed: %s", exc)
            for line, amt in plan.nonzero().items():
                self._event("treasurer", f"opex:{line}", LINE_TARGET.get(line, line), amt)
            log.info("treasurer round %s — %s", rid, plan.rationale)
        self._prev_players = players

    def snapshot(self) -> dict:
        return build_snapshot(self)

    def publish(self) -> None:
        publish_snapshot(self)

    def run_one_round(self) -> None:
        rid = self.open_round(); self.publish()
        self.sell_tickets(rid); self.publish()
        self.apply_sponsor_tithe(rid); self.apply_uni_benefactor(rid); self.publish()
        if self.cfg.sell_window > 0:
            time.sleep(self.cfg.sell_window)
        if self.close_and_draw(rid):
            self.settle(rid)
        self.publish()

    def run_forever(self) -> None:
        log.info("economy engine: mode=%s address=%s live_oracles=%s onchain_vdf=%s",
                 self.cfg.mode, self.chain.address, self.cfg.use_live_oracles, self.chain.onchain_vdf())
        while self._running:
            try:
                self.run_one_round()
            except Exception:
                log.exception("round failed")
            time.sleep(self.cfg.round_interval)

    def stop(self) -> None:
        self._running = False
        self.oracles.close()
        self.monitor.close()

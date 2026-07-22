"""The economy engine — drives a full lottery round end to end and models the
circular AI economy:

    open → agents buy tickets → Hub tithes (only its bound lottery) →
    UNI external benefactor ($100/week) → entries close (commit) →
    Platon randomness + (optional) Chronos VDF → draw/reveal → winner →
    treasury withdraws opex → pays the oracles the draw consumed → repeat.

Every oracle call's price is booked as opex (the lottery *paying* for services);
the Hub's routing-fee revenue funds the tithe (defense: only its bound lottery).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from eth_account import Account
from web3 import Web3

from .chain import Chain
from .config import Config
from .log import get_logger
from .mesh import MeshClient
from .monitor import MonitorFeed, build_monitor_metrics
from .oracles import PRICE, OpexLedger, OracleClient
from .sponsor import SponsorPolicy
from .treasurer import Treasurer
from .vdf import base_seed, empty_proof, proof_from_chronos, seed_string

log = get_logger("economy")

# Fallback names ONLY when the Mesh roster is unavailable (synthetic demo crowd).
_NAMES = ["Aria", "Boreas", "Ceres", "Draco", "Echo", "Flux", "Gaia", "Helix"]


@dataclass
class Participant:
    """A lottery seat. `source="mesh"` ⇒ a real verified Mesh agent (real name, id,
    reputation); `source="synthetic"` ⇒ the demo crowd. In UNI/Anvil the on-chain buy
    is always signed by a relayer-held funded `key` (Mesh agents expose no private key);
    `wallet` records the agent's own bound address for display + the future self-sign path."""
    name: str
    key: str            # relayer-held funded signing key (custodial in UNI/demo)
    addr: str           # on-chain msg.sender == Account.from_key(key).address
    trust_bps: int = 0  # real reputation → odds bonus (mesh); synthetic uses LUMEN
    mesh_id: str = ""
    wallet: str = ""    # agent's own bound EVM address (self-custodial, future path)
    source: str = "synthetic"


def mesh_roster(agents, keys: list[str], addrs: list[str]) -> list[Participant]:
    """Seat real Mesh agents onto funded signing keys (custodial in UNI/demo)."""
    return [
        Participant(name=a.name, key=keys[i], addr=addrs[i], trust_bps=a.trust_bps,
                    mesh_id=a.id, wallet=a.evm_address, source="mesh")
        for i, a in enumerate(agents)
    ]


def synthetic_roster(keys: list[str], addrs: list[str]) -> list[Participant]:
    """Demo crowd — used only when the Mesh roster is unavailable."""
    return [
        Participant(name=_NAMES[i % len(_NAMES)], key=k, addr=addrs[i])
        for i, k in enumerate(keys)
    ]


def derive_agent_key(seed: str, agent_id: str) -> str:
    """Deterministic per-agent private key for the UNI emulation (we own the chain).
    Same agent ⇒ same wallet across rounds; different agents ⇒ distinct wallets."""
    return Web3.keccak(text=f"ailottery-uni-wallet|{seed}|{agent_id}").hex()


def uni_wallet_roster(agents, seed: str) -> list[Participant]:
    """Each real Mesh agent gets its OWN deterministic wallet and signs its own buys —
    true self-custodial participation (UNI: we hold the derived keys + fund them)."""
    out = []
    for a in agents:
        key = derive_agent_key(seed, a.id)
        addr = Account.from_key(key).address
        out.append(Participant(name=a.name, key=key, addr=addr, trust_bps=a.trust_bps,
                               mesh_id=a.id, wallet=addr, source="mesh"))
    return out


# where each opex line item's money conceptually goes (for the activity feed)
LINE_TARGET = {"oracles": "oracles", "gas": "chain", "hub_fee": "Hub", "reserve": "reserve",
               "marketing": "announcer-agent", "audit": "audit-agent", "treasurer": "treasurer-agent"}


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        self._hub_revenue_accum = 0.0   # routing-fee revenue the Hub accrues between transfers
        self._last_tithe_ts = 0.0       # 0 → the first eligible round transfers immediately
        self._prev_players = 0
        self.last_opex_plan = None
        self.treasurer = Treasurer(cfg, self.oracles)
        self._running = True

        # identities
        self.fn = self.chain.contract.functions
        self.operator_key = cfg.operator_key
        self.signer_key = cfg.oracle_signer_key
        self.treasury_key = cfg.treasury_key
        self.sponsor_key = cfg.sponsor_key
        self.benefactor_key = cfg.benefactor_key
        self.agent_keys = cfg.agent_keys
        self._agent_addr = [Account.from_key(k).address for k in self.agent_keys]
        self._key_by_addr = {Account.from_key(k).address: k for k in self.agent_keys}
        # Participant roster: real verified Mesh agents when MESH_URL is reachable,
        # otherwise the synthetic demo crowd. Rebuilt each round so newly-registered
        # agents appear live. _name_by_addr is derived from it for the activity feed.
        self._roster: list[Participant] = []
        self._name_by_addr: dict[str, str] = {}
        self._refresh_roster()

        # resolve the sponsor binding ONCE — this is the «деньги не увести» gate
        self.binding = self.sponsor.resolve_bound(self.chain.address, self.chain.w3)
        log.info("sponsor binding: ok=%s addr=%s — %s",
                 self.binding.ok, self.binding.address, self.binding.reason)

    # ── roster (real Mesh agents, else synthetic) ───────────────────────────────
    def _refresh_roster(self) -> None:
        """Rebuild the participant roster from the Mesh; keep the last good Mesh roster
        on a transient outage; fall back to the synthetic crowd when Mesh is off/empty.

        UNI self-custody: each real Mesh agent gets its OWN deterministic wallet (funded
        from the faucet, bound back to the Mesh) and signs its own buys. Without
        auto-wallet the agents are seated on relayer-held funded keys (custodial demo)."""
        if self.mesh.enabled:
            # auto-wallet isn't bounded by the funded-key count — only by the cap
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
                return  # transient Mesh blip — keep the last real roster, don't flap
        if not self.agent_keys:
            self._roster, self._name_by_addr = [], {}
            return
        self._roster = synthetic_roster(self.agent_keys, self._agent_addr)
        self._name_by_addr = {p.addr: p.name for p in self._roster}

    def _fund_and_bind_roster(self) -> None:
        """Top up each self-custodial agent wallet from the faucet (idempotent — only
        when below target) and bind the address back to its Mesh agent. UNI only."""
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

    # ── naming / events ────────────────────────────────────────────────────────
    def _name(self, addr: str) -> str:
        if not addr or int(addr, 16) == 0:
            return "—"
        return self._name_by_addr.get(addr, f"Agent-{addr[2:6]}")

    def _event(self, agent: str, action: str, target: str, amount_usd: float) -> None:
        self.events.append({
            "ts": _iso(), "agent": agent, "action": action, "target": target,
            "amount": round(float(amount_usd), 4), "token": "USDC",
            "id": f"lot_{int(time.time())}_{len(self.events)}",
        })
        self.events = self.events[-200:]

    # ── round lifecycle ────────────────────────────────────────────────────────
    def open_round(self) -> int:
        self.chain.send(self.fn.openRound(), self.operator_key)
        rid = self.chain.current_round_id()
        log.info("round %s opened", rid)
        self._event("operator", "open", f"round {rid}", 0)
        return rid

    def sell_tickets(self, rid: int) -> None:
        if not self.cfg.sim_agents:
            return
        # Re-discover the real Mesh roster each round so newly-verified agents join live.
        self._refresh_roster()
        if not self._roster:  # no Mesh agents and no funded crowd → nothing to drive
            return
        price = self.chain.ticket_price()
        now = self.chain.block()["timestamp"]
        expiry = now + 86_400
        # one priced LUMEN call per round → the lottery PAYS for reputation scoring
        # (opex out). Real Mesh agents already carry a verified trust score; the
        # synthetic crowd's bonus is sourced from this LUMEN call.
        bonuses, _ = self.oracles.lumen_reputation([p.addr for p in self._roster])
        self._event("lottery", "invoke", "LUMEN", PRICE["lumen.reputation@v1"])
        for i, p in enumerate(self._roster):
            count = 1 + (i % 3)
            cost_usd = self.cfg.wei_to_usd(price * count)
            # real Mesh reputation when seated from the Mesh; LUMEN otherwise
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
        # The HUB pushes its accrued tithe on ITS OWN schedule (every N hours) — the
        # lottery never pulls. Between transfers the Hub keeps accruing routing fees.
        if not self.binding.ok:
            return
        self._hub_revenue_accum += self.cfg.hub_routing_revenue_usd
        interval = self.cfg.demo_tithe_interval_s if self.cfg.is_demo else self.cfg.hub_tithe_interval_hours * 3600
        now = time.time()
        if now - self._last_tithe_ts < interval:
            return  # not the Hub's scheduled transfer time yet
        tithe_usd = self.sponsor.tithe_usd(self._hub_revenue_accum)
        self._last_tithe_ts = now
        if tithe_usd <= 0:
            return
        # re-assert the destination is exactly the bound lottery (anti-redirect)
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
        if self._uni_round_counter < 7:  # 1 round ≈ 1 day → weekly allocation every 7 rounds
            return
        self._uni_round_counter = 0
        amt = self.cfg.usd_to_wei(self.cfg.uni_weekly_usd)
        try:
            self.chain.send(self.fn.fund(rid, amt), self.benefactor_key, value=amt)
            self._event("Unknown benefactor", "weekly-grant", "lottery", self.cfg.uni_weekly_usd)
            log.info("UNI external benefactor allocated $%.2f → round %s", self.cfg.uni_weekly_usd, rid)
        except Exception as exc:
            log.warning("benefactor funding failed: %s", exc)

    def _advance_to_close(self, rid: int) -> dict:
        r = self.chain.get_round(rid)
        target = r["entriesClose"] + 1
        if self.cfg.fast_forward:
            now = self.chain.block()["timestamp"]
            if now < target:
                self.chain.fast_forward(target - now)
        else:
            while self.chain.block()["timestamp"] < target:
                time.sleep(self.cfg.poll_interval)
        return self.chain.get_round(rid)

    def close_and_draw(self, rid: int) -> bool:
        # no players → cancel rather than revert on NoParticipants
        if self.chain.participants_count(rid) == 0:
            log.info("round %s had no participants → cancel", rid)
            self.chain.send(self.fn.cancelRound(rid), self.operator_key)
            self._event("operator", "cancel", f"round {rid}", 0)
            return False

        self._advance_to_close(rid)

        # 1) obtain the Platon entropy and COMMIT it (before the seed block exists)
        client_seed = f"{self.chain.address}|{rid}"
        platon_word, _ = self.oracles.platon_random(client_seed)
        self._event("lottery", "invoke", "Platon", PRICE["platon.random@v1"])
        commitment = Web3.solidity_keccak(["bytes32"], [platon_word])
        self.chain.send(self.fn.closeEntries(rid, commitment), self.operator_key)
        self._event("operator", "close", f"round {rid}", 0)

        # 2) make blockhash(seedBlock) available and pass minDrawDelay
        self.chain.mine()
        r = self.chain.get_round(rid)
        mdd = self.chain.min_draw_delay()
        if self.cfg.fast_forward:
            self.chain.fast_forward(mdd + 1)
        else:
            while self.chain.block()["timestamp"] < r["closedAt"] + mdd:
                time.sleep(self.cfg.poll_interval)

        # 3) build the (optional) VDF proof
        if self.chain.onchain_vdf():
            bh = self.chain.blockhash(r["seedBlock"])
            seed = seed_string(base_seed(rid, bh, platon_word))
            difficulty = 100_000
            out, _ = self.oracles.chronos_eval(seed, difficulty)
            self._event("lottery", "invoke", "Chronos", PRICE["chronos.eval@v1"])
            proof = None
            if out and all(out.get(k) for k in ("g", "y", "modulus")) and isinstance(out.get("proof"), dict):
                try:
                    proof = proof_from_chronos(
                        seed, out["modulus"], out["g"], out["y"],
                        out["proof"].get("pi"), out["proof"].get("l"),
                        difficulty, self.cfg.chronos_canonical_n)
                except Exception as exc:
                    log.error("onchain VDF proof parse failed: %s", exc)
            if proof is None:
                # fail SAFE: a missing/invalid Chronos proof must not brick the round
                # (the contract requires onchainVdf proofs). Cancel → funds refundable.
                log.error("round %s: onchain_vdf=true but no valid Chronos proof "
                          "(Chronos must use the contract's canonical modulus; set "
                          "CHRONOS_CANONICAL_N) — cancelling to keep funds refundable", rid)
                self.chain.send(self.fn.cancelRound(rid), self.operator_key)
                self._event("operator", "cancel", f"round {rid}", 0)
                return False
            vdf_t = difficulty
        else:
            self._event("lottery", "invoke", "Chronos", PRICE["chronos.eval@v1"])  # consumed conceptually
            proof, vdf_t = empty_proof(), 0

        # 4) sign the beacon (binds the exact proof) and reveal/draw
        proof_hash = proof.proof_hash()
        sig = self.chain.sign_beacon(self.signer_key, rid, platon_word, vdf_t, proof_hash)
        self.chain.send(self.fn.fulfillDraw(rid, platon_word, vdf_t, sig, proof.as_tuple()), self.operator_key)

        r = self.chain.get_round(rid)
        self.last_winner = self._name(r["winner"])
        prize_usd = self.cfg.wei_to_usd(r["prizePool"])
        self._event("lottery", "prize", self.last_winner, prize_usd)
        log.info("round %s drawn — winner %s, prize $%.4f", rid, self.last_winner, prize_usd)
        return True

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

        # ── AI Treasurer manages this round's opex bucket ────────────────────────
        # opex is a capped, segregated share of TOTAL income; the treasurer allocates
        # it across line items and can NEVER reach the prize pool (contract-enforced).
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
            # disburse only the SPENT portion from the on-chain opex bucket; the
            # unspent remainder stays on-chain as the solvency reserve.
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

    # ── publish ────────────────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        econ = self.chain.economy()
        rid = econ["round"]
        players = self.chain.participants_count(rid) if rid else 0
        r = self.chain.get_round(rid) if rid else None
        if r:
            if int(r["status"]) == 3:  # Settled
                pool = r["prizePool"]
            else:  # prospective prize = prize share of TOTAL income so far
                pool = ((r["ticketRevenue"] + r["funding"]) * (r["sPrizeBps"] or 7000)) // 10_000
        else:
            pool = 0
        return {
            "mode": self.cfg.mode,
            "address": self.chain.address,
            "round": rid,
            "players": players,
            "last_winner": self.last_winner,
            "prize_pool_usd": round(self.cfg.wei_to_usd(pool), 4),
            "metrics": build_monitor_metrics(
                prize_pool_usd=round(self.cfg.wei_to_usd(pool), 2),
                round=rid,
                players=players,
                payouts_24h=round(self.cfg.wei_to_usd(econ["prizesPaid"]), 2),
                opex_24h=round(self.cfg.wei_to_usd(econ["opexTotal"]), 2),
                funding_24h=round(self.cfg.wei_to_usd(econ["fundingTotal"]), 2),
            ),
            "oracle_ledger": {
                "spend_usd": self.ledger.oracle_spend_usd,
                "routing_fees_usd": self.ledger.routing_fees_usd,
                "calls": self.ledger.calls,
            },
            "reserve_usd": round(self.cfg.wei_to_usd(econ["opexAvailable"]), 4),
            "treasurer": ({
                "rationale": self.last_opex_plan.rationale,
                "spend_usd": self.last_opex_plan.spend_total,
                "reserve_hold_usd": self.last_opex_plan.reserve_hold,
                "items": self.last_opex_plan.nonzero(),
            } if self.last_opex_plan else None),
            "sponsor": {"bound": self.binding.ok, "address": self.binding.address,
                        "reason": self.binding.reason, "tithe_bps": self.sponsor.tithe_bps(),
                        "tithe_source": "hub" if self.cfg.hub_tithe_bps >= 0 else "config",
                        "interval_hours": self.cfg.hub_tithe_interval_hours,
                        "pushed_by": "hub"},
            # The real participant roster (verified Mesh agents when source=="mesh"),
            # so the showcase/monitor render actual ecosystem agents, not invented names.
            "roster_source": self.roster_source,
            "roster": [
                {"name": p.name, "address": p.addr, "trust_bps": p.trust_bps,
                 "source": p.source, "mesh_id": p.mesh_id, "wallet": p.wallet}
                for p in self._roster
            ],
            "events": self.events[-40:],
        }

    def publish(self) -> None:
        self.state = self.snapshot()
        self.monitor.push({k: self.state[k] for k in ("mode", "metrics", "last_winner", "events")})

    # ── main loop ────────────────────────────────────────────────────────────
    def run_one_round(self) -> None:
        rid = self.open_round(); self.publish()
        self.sell_tickets(rid); self.publish()
        self.apply_sponsor_tithe(rid); self.apply_uni_benefactor(rid); self.publish()
        # real-time window so EXTERNAL agents (the agent container) can also buy in
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

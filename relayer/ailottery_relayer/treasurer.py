"""AI Treasurer — the lottery's autonomous operational-expense manager.

The lottery is a full member of the AI economy, so it has real running costs. Each
round the contract accrues a capped `opex` share of TOTAL income (tickets + donations)
into a segregated bucket. The Treasurer decides how to allocate THAT bucket across the
lottery's real opex line items — autonomously, but inside a hard ceiling it can never
exceed: the contract caps opex and keeps it provably separate from the prize pool, so
the Treasurer can never touch the winner's money. It manages the opex bucket; it cannot
raid prizes.

Recursion that's on-theme: the Treasurer is itself an agent service the lottery pays
for out of opex — the lottery literally consumes an AI service to run itself.

Opex line items (an AI-economy lottery's genuine costs):
  oracles    Platon $0.004 + Chronos $0.01 + LUMEN $0.005 per draw   (mandatory)
  gas        on-chain settlement (open/close/draw/withdraw, reseed)  (mandatory)
  hub_fee    the Hub's 1% routing fee on each oracle invocation       (mandatory)
  reserve    buffer toward a target (gas spikes, reseed, solvency)
  marketing  an announcer agent to grow participation when it's low
  audit      a risk/monitoring agent
  treasurer  the Treasurer's own fee (the recursion above)

Modes:
  policy (default) — a deterministic, testable allocation heuristic.
  llm              — ask an agent/LLM (via the Hub) for the allocation; falls back
                     to `policy` on any failure, so it is always safe + deterministic
                     enough to run headless.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .log import get_logger

log = get_logger("treasurer")

# mandatory per-draw costs (USD) — must always be covered first
ORACLE_COST_USD = 0.019           # Platon 0.004 + Chronos 0.01 + LUMEN 0.005
HUB_FEE_USD = round(ORACLE_COST_USD * 0.01, 6)  # 1% routing fee on the oracle spend


@dataclass
class OpexPlan:
    items: dict = field(default_factory=dict)   # line -> usd
    spend_total: float = 0.0                    # what we actually disburse this round
    reserve_hold: float = 0.0                   # left in the on-chain opex bucket as buffer
    rationale: str = ""

    def nonzero(self):
        return {k: v for k, v in self.items.items() if v > 0}


class Treasurer:
    def __init__(self, cfg, oracles=None):
        self.cfg = cfg
        self.oracles = oracles
        econ = (cfg.economics or {}).get("opex", {}) if getattr(cfg, "economics", None) else {}
        self.gas_usd = float(econ.get("gas_usd", 0.01))
        self.treasurer_fee_usd = float(econ.get("treasurer_fee_usd", 0.002))
        self.audit_fee_usd = float(econ.get("audit_fee_usd", 0.003))
        self.marketing_max_usd = float(econ.get("marketing_max_usd", 1.0))
        self.reserve_target_usd = float(getattr(cfg, "reserve_target_usd", 5.0))

    # ── public ────────────────────────────────────────────────────────────────
    def plan(self, budget_usd: float, ctx: dict) -> OpexPlan:
        """Allocate the round's opex `budget_usd` across line items. `ctx` carries
        {players, prize_pool_usd, reserve_usd, prev_players}."""
        budget_usd = max(0.0, float(budget_usd))
        if self.cfg.treasurer_mode == "llm":
            p = self._llm_plan(budget_usd, ctx)
            if p is not None:
                return p
        return self._policy_plan(budget_usd, ctx)

    # ── deterministic policy ────────────────────────────────────────────────────
    def _policy_plan(self, budget: float, ctx: dict) -> OpexPlan:
        items = {"oracles": 0.0, "gas": 0.0, "hub_fee": 0.0, "treasurer": 0.0,
                 "reserve": 0.0, "marketing": 0.0, "audit": 0.0}
        left = budget

        # 1) mandatory: oracles + gas + hub routing fee + the treasurer's own fee
        for k, cost in (("oracles", ORACLE_COST_USD), ("gas", self.gas_usd),
                        ("hub_fee", HUB_FEE_USD), ("treasurer", self.treasurer_fee_usd)):
            spend = min(left, cost)
            items[k] = round(spend, 6)
            left -= spend

        # 2) top up the reserve toward its target (solvency buffer)
        reserve_now = float(ctx.get("reserve_usd", 0.0))
        gap = max(0.0, self.reserve_target_usd - reserve_now)
        if left > 0 and gap > 0:
            topup = min(left, gap * 0.5)  # ease toward target, don't starve growth
            items["reserve"] = round(topup, 6)
            left -= topup

        # 3) discretionary: grow participation when it's low/falling, else a little audit
        if left > 0:
            players = int(ctx.get("players", 0))
            prev = int(ctx.get("prev_players", players))
            low_or_falling = players <= 3 or players < prev
            if low_or_falling:
                mk = min(left, self.marketing_max_usd)
                items["marketing"] = round(mk, 6); left -= mk
            if left > 0:
                ad = min(left, self.audit_fee_usd)
                items["audit"] = round(ad, 6); left -= ad

        spend_total = round(sum(items.values()), 6)
        reserve_hold = round(max(0.0, budget - spend_total), 6)  # unspent stays in the bucket
        rationale = (f"budget ${budget:.4f}: mandatory ${items['oracles']+items['gas']+items['hub_fee']+items['treasurer']:.4f}, "
                     f"reserve +${items['reserve']:.4f} (target ${self.reserve_target_usd}), "
                     f"{'marketing' if items['marketing'] else 'no-marketing'} ${items['marketing']:.4f}, "
                     f"hold ${reserve_hold:.4f}")
        return OpexPlan(items=items, spend_total=spend_total, reserve_hold=reserve_hold, rationale=rationale)

    # ── optional LLM/agent-backed allocation ────────────────────────────────────
    def _llm_plan(self, budget: float, ctx: dict):
        """Ask an agent/LLM (via the oracle/Hub layer) for an allocation. The lottery
        PAYS for this decision (it's the treasurer line). Falls back to policy on any
        problem so the engine never blocks."""
        if not (self.oracles and self.cfg.use_live_oracles):
            return None
        try:
            prompt = ("You are the lottery treasurer. Allocate the opex budget across "
                      "[oracles,gas,hub_fee,reserve,marketing,audit,treasurer] as JSON "
                      f"of USD amounts summing <= {budget}. Context: {json.dumps(ctx)}. "
                      "Cover mandatory oracles/gas/hub_fee/treasurer first.")
            out, _ = self.oracles.platon_ask(prompt)  # cheap grounded guide capability
            data = out if isinstance(out, dict) else {}
            alloc = data.get("allocation") if isinstance(data.get("allocation"), dict) else None
            if not alloc:
                return None
            items = {k: max(0.0, float(alloc.get(k, 0))) for k in
                     ("oracles", "gas", "hub_fee", "reserve", "marketing", "audit", "treasurer")}
            tot = sum(items.values())
            if tot > budget and tot > 0:  # scale down to respect the hard cap
                items = {k: round(v * budget / tot, 6) for k, v in items.items()}
            spend = round(sum(items.values()), 6)
            return OpexPlan(items=items, spend_total=spend,
                            reserve_hold=round(max(0.0, budget - spend), 6),
                            rationale="llm-allocated (capped to budget)")
        except Exception as exc:
            log.info("treasurer llm plan failed (%s) → policy", exc)
            return None

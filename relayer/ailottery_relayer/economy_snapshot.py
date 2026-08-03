"""Monitor snapshot + activity feed for the economy engine."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .monitor import build_monitor_metrics

if TYPE_CHECKING:
    from .economy import EconomyEngine

# where each opex line item's money conceptually goes (for the activity feed)
LINE_TARGET = {"oracles": "oracles", "gas": "chain", "hub_fee": "Hub", "reserve": "reserve",
               "marketing": "announcer-agent", "audit": "audit-agent", "treasurer": "treasurer-agent"}


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_event(engine: EconomyEngine, agent: str, action: str, target: str, amount_usd: float) -> None:
    engine.events.append({
        "ts": iso_now(), "agent": agent, "action": action, "target": target,
        "amount": round(float(amount_usd), 4), "token": "USDC",
        "id": f"lot_{int(time.time())}_{len(engine.events)}",
    })
    engine.events = engine.events[-200:]


def name_for_addr(engine: EconomyEngine, addr: str) -> str:
    if not addr or int(addr, 16) == 0:
        return "—"
    return engine._name_by_addr.get(addr, f"Agent-{addr[2:6]}")


def build_snapshot(engine: EconomyEngine) -> dict:
    econ = engine.chain.economy()
    rid = econ["round"]
    players = engine.chain.participants_count(rid) if rid else 0
    r = engine.chain.get_round(rid) if rid else None
    if r:
        if int(r["status"]) == 3:  # Settled
            pool = r["prizePool"]
        else:
            pool = ((r["ticketRevenue"] + r["funding"]) * (r["sPrizeBps"] or 7000)) // 10_000
    else:
        pool = 0
    return {
        "mode": engine.cfg.mode,
        "address": engine.chain.address,
        "round": rid,
        "players": players,
        "last_winner": engine.last_winner,
        "prize_pool_usd": round(engine.cfg.wei_to_usd(pool), 4),
        "metrics": build_monitor_metrics(
            prize_pool_usd=round(engine.cfg.wei_to_usd(pool), 2),
            round=rid,
            players=players,
            payouts_24h=round(engine.cfg.wei_to_usd(econ["prizesPaid"]), 2),
            opex_24h=round(engine.cfg.wei_to_usd(econ["opexTotal"]), 2),
            funding_24h=round(engine.cfg.wei_to_usd(econ["fundingTotal"]), 2),
        ),
        "oracle_ledger": {
            "spend_usd": engine.ledger.oracle_spend_usd,
            "routing_fees_usd": engine.ledger.routing_fees_usd,
            "calls": engine.ledger.calls,
        },
        "reserve_usd": round(engine.cfg.wei_to_usd(econ["opexAvailable"]), 4),
        "treasurer": ({
            "rationale": engine.last_opex_plan.rationale,
            "spend_usd": engine.last_opex_plan.spend_total,
            "reserve_hold_usd": engine.last_opex_plan.reserve_hold,
            "items": engine.last_opex_plan.nonzero(),
        } if engine.last_opex_plan else None),
        "sponsor": {"bound": engine.binding.ok, "address": engine.binding.address,
                    "reason": engine.binding.reason, "tithe_bps": engine.sponsor.tithe_bps(),
                    "tithe_source": "hub" if engine.cfg.hub_tithe_bps >= 0 else "config",
                    "interval_hours": engine.cfg.hub_tithe_interval_hours,
                    "pushed_by": "hub"},
        "roster_source": engine.roster_source,
        "roster": [
            {"name": p.name, "address": p.addr, "trust_bps": p.trust_bps,
             "source": p.source, "mesh_id": p.mesh_id, "wallet": p.wallet}
            for p in engine._roster
        ],
        "events": engine.events[-40:],
    }


def publish_snapshot(engine: EconomyEngine) -> None:
    engine.state = build_snapshot(engine)
    engine.monitor.push({k: engine.state[k] for k in ("mode", "metrics", "last_winner", "events")})

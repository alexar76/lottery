"""Unit tests for economy_snapshot helpers split out of economy.py."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from ailottery_relayer.config import Config
from ailottery_relayer.economy_snapshot import (
    build_snapshot,
    name_for_addr,
    publish_snapshot,
    record_event,
)
from ailottery_relayer.monitor import MONITOR_METRIC_KEYS
from ailottery_relayer.roster import Participant
from ailottery_relayer.sponsor import Binding


def _fake_engine():
    cfg = Config()
    cfg.mode = "uni"
    cfg.hub_tithe_bps = 2000
    cfg.hub_tithe_interval_hours = 24
    cfg.wei_to_usd = lambda w: w / 1_000_000_000_000_000

    binding = Binding(ok=True, address="0x" + "ab" * 20, reason="bound")
    sponsor = SimpleNamespace(tithe_bps=lambda: 2000)

    chain = SimpleNamespace(
        address="0x" + "cd" * 20,
        economy=lambda: {
            "round": 2,
            "prizesPaid": 0,
            "opexTotal": 0,
            "fundingTotal": 0,
            "ticketRevenue": 0,
            "opexAvailable": 5_000_000_000_000_000,
            "operatorAvailable": 0,
        },
        participants_count=lambda rid: 3,
        get_round=lambda rid: {
            "status": 1,
            "ticketRevenue": 10_000_000_000_000_000,
            "funding": 0,
            "sPrizeBps": 7000,
            "prizePool": 0,
        },
    )

    engine = SimpleNamespace(
        cfg=cfg,
        chain=chain,
        ledger=SimpleNamespace(oracle_spend_usd=1.5, routing_fees_usd=0.2, calls=2),
        binding=binding,
        sponsor=sponsor,
        last_winner="Aria",
        last_opex_plan=None,
        roster_source="mesh",
        _roster=[
            Participant(name="Aria", key="0xk", addr="0xA1", trust_bps=100, mesh_id="m1", wallet="0xA1", source="mesh"),
        ],
        _name_by_addr={"0xA1": "Aria"},
        events=[],
        state={},
        monitor=SimpleNamespace(push=MagicMock()),
    )
    return engine


def test_record_event_appends_and_trims_feed():
    engine = _fake_engine()
    record_event(engine, "Aria", "ticket", "lottery", 1.23456)
    assert len(engine.events) == 1
    ev = engine.events[0]
    assert ev["agent"] == "Aria" and ev["action"] == "ticket"
    assert ev["amount"] == 1.2346
    assert ev["token"] == "USDC"
    assert ev["ts"].endswith("Z")


def test_name_for_addr_resolves_roster_and_zero_address():
    engine = _fake_engine()
    assert name_for_addr(engine, "0xA1") == "Aria"
    assert name_for_addr(engine, "0x0000000000000000000000000000000000000000") == "—"
    assert name_for_addr(engine, "0xdeadbeef000000000000000000000000000000").startswith("Agent-")


def test_build_snapshot_shapes_monitor_payload():
    engine = _fake_engine()
    snap = build_snapshot(engine)
    assert snap["mode"] == "uni"
    assert snap["round"] == 2
    assert snap["players"] == 3
    assert snap["last_winner"] == "Aria"
    assert snap["roster_source"] == "mesh"
    assert snap["roster"][0]["name"] == "Aria"
    for key in MONITOR_METRIC_KEYS:
        assert key in snap["metrics"]
    assert snap["sponsor"]["bound"] is True


def test_publish_snapshot_pushes_monitor_subset():
    engine = _fake_engine()
    publish_snapshot(engine)
    engine.monitor.push.assert_called_once()
    payload = engine.monitor.push.call_args[0][0]
    assert set(payload.keys()) == {"mode", "metrics", "last_winner", "events"}
    assert engine.state["round"] == 2

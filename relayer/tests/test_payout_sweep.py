"""Audit 2026-11-11, satellites-3/4: pull payments the relayer owed itself and never pulled.

A prize won by a derived (auto-wallet) roster wallet was never claimed — the claim looked only at
the funded-key list, ran once, and nothing retried it or forfeited it later. Refunds owed to the
sponsor, benefactor and agent keys after a cancel were never pulled at all.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from eth_account import Account

from ailottery_relayer.abi import STATUS_CANCELLED, STATUS_OPEN, STATUS_SETTLED, UNCLAIMED_PRIZE_TTL
from ailottery_relayer.economy import EconomyEngine, derive_agent_key, uni_wallet_roster
from ailottery_relayer.economy_draw import sweep_payouts

NOW = 1_800_000_000
DERIVED = derive_agent_key("seed", "mesh-agent-1")
DERIVED_ADDR = Account.from_key(DERIVED).address
SPONSOR = "0x" + "11" * 32
SPONSOR_ADDR = Account.from_key(SPONSOR).address
STRANGER = "0x" + "77" * 20


class _View:
    def __init__(self, value):
        self.value = value

    def call(self):
        return self.value


def _engine(rounds: dict[int, dict], *, owed=None, settled_at=None, clock=NOW):
    sent: list = []
    owed = owed or {}
    settled_at = settled_at or {}
    chain = SimpleNamespace(
        current_round_id=lambda: max(rounds),
        get_round=lambda rid: rounds[rid],
        block=lambda: {"number": 1, "timestamp": clock},
        send=lambda fn, key, **_: sent.append((fn, key)) or {"status": 1},
    )
    fn = SimpleNamespace(
        claimPrize=lambda rid: f"claim:{rid}",
        refund=lambda rid: f"refund:{rid}",
        forfeitUnclaimedPrize=lambda rid: f"forfeit:{rid}",
        settledAt=lambda rid: _View(settled_at.get(rid, 0)),
        paidBy=lambda rid, a: _View(owed.get((rid, a.lower()), 0)),
        fundedBy=lambda rid, a: _View(0),
    )
    engine = EconomyEngine.__new__(EconomyEngine)
    engine.chain, engine.fn = chain, fn
    engine.cfg = SimpleNamespace(wei_to_usd=lambda w: 0.0)
    engine.operator_key = "0x" + "99" * 32
    engine.sponsor_key, engine.benefactor_key = SPONSOR, ""
    engine.agent_keys = []
    engine._roster = uni_wallet_roster([SimpleNamespace(id="mesh-agent-1", name="Ada", trust_bps=0)], "seed")
    engine._name_by_addr = {}
    engine._event = MagicMock()
    return engine, sent


def _settled(winner, claimed=False):
    return {"status": STATUS_SETTLED, "winner": winner, "prizeClaimed": claimed, "prizePool": 10}


def test_a_prize_won_by_a_derived_roster_wallet_is_claimed_with_its_key():
    engine, sent = _engine({1: _settled(DERIVED_ADDR)})
    assert sweep_payouts(engine, force=True)["claimed"] == 1
    assert sent == [("claim:1", DERIVED)]


def test_the_relayer_s_own_refunds_are_pulled_after_a_cancel():
    engine, sent = _engine({1: {"status": STATUS_CANCELLED, "winner": "0x" + "0" * 40, "prizeClaimed": False}},
                           owed={(1, SPONSOR_ADDR.lower()): 5, (1, DERIVED_ADDR.lower()): 3})
    assert sweep_payouts(engine, force=True)["refunded"] == 2
    assert sorted(sent) == sorted([("refund:1", SPONSOR), ("refund:1", DERIVED)])


def test_someone_else_s_prize_is_forfeited_only_after_its_ttl_and_does_not_pin_the_scan():
    rounds = {1: _settled(STRANGER), 2: {"status": STATUS_OPEN, "winner": "0x" + "0" * 40, "prizeClaimed": False}}
    engine, sent = _engine(rounds, settled_at={1: NOW - 10})
    sweep_payouts(engine, force=True)
    assert sent == [] and engine._forfeit_due == {1: NOW - 10 + UNCLAIMED_PRIZE_TTL}
    assert engine._payout_cursor == 2, "the open round, not the 180-day wait, is where the scan resumes"
    engine.chain.block = lambda: {"number": 2, "timestamp": NOW + UNCLAIMED_PRIZE_TTL}
    assert sweep_payouts(engine, force=True)["forfeited"] == 1
    assert sent == [("forfeit:1", engine.operator_key)] and engine._forfeit_due == {}


def test_a_failed_claim_is_retried_by_the_next_pass():
    engine, sent = _engine({1: _settled(DERIVED_ADDR)})
    calls = {"n": 0}

    def flaky(fn, key, **_):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("nonce too low")
        sent.append((fn, key))

    engine.chain.send = flaky
    assert sweep_payouts(engine, force=True)["failed"] == 1
    assert engine._payout_cursor == 1
    assert sweep_payouts(engine, force=True)["claimed"] == 1 and sent == [("claim:1", DERIVED)]


def test_the_sweep_runs_at_most_hourly_unless_forced():
    engine, sent = _engine({1: _settled(DERIVED_ADDR)})
    sweep_payouts(engine)
    assert sweep_payouts(engine) == {}

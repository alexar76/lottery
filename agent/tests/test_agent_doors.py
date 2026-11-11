"""The agent enters a round through the door the deployed contract actually has.

The demo chain on my-vps runs a contract deployed from the 2026-06 source, which has no
`paidTicketsEnabled` or `workSeated` getter: both calls revert with no data. Until
2026-11-08 the agent treated that revert as a failure and retried it every poll, so it
never entered a round on that chain (its wallet nonce stayed 0).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from ailottery_agent.__main__ import (
    STATUS_CANCELLED,
    STATUS_OPEN,
    STATUS_SETTLED,
    TxReverted,
    enter_round,
    follow_up,
    paid_door_open,
)
from web3.exceptions import ContractLogicError

ME = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
OTHER = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"
PRICE = 10**15
_MISSING = object()


class _View:
    def __init__(self, fn):
        self._fn = fn

    def call(self):
        return self._fn()


def _round(status, winner=OTHER, claimed=False, prize=8 * 10**15):
    r = [0] * 16
    r[0], r[12], r[13], r[15] = status, prize, winner, claimed
    return tuple(r)


class FakeLottery:
    """`paid` = _MISSING models a contract without the switch (reverts, no data)."""

    def __init__(self, *, paid=_MISSING, seated=False, rounds=None, switch_error=None):
        self.rounds = rounds or {}

        def paid_getter():
            if switch_error is not None:
                raise switch_error
            if paid is _MISSING:
                raise ContractLogicError("execution reverted", data="0x")
            return paid

        def seated_getter():
            if paid is _MISSING:
                raise ContractLogicError("execution reverted", data="0x")
            return seated

        self.functions = SimpleNamespace(
            paidTicketsEnabled=lambda: _View(paid_getter),
            workSeated=lambda rid, agent: _View(seated_getter),
            ticketPrice=lambda: _View(lambda: PRICE),
            getRound=lambda rid: _View(lambda: self.rounds[rid]),
            buyTickets=lambda rid, n: ("buyTickets", rid, n),
            buyTicketsWithVoucher=lambda rid, n, bps, exp, sig: ("buyTicketsWithVoucher", rid, n, bps),
            enterFromWork=lambda rid, pid, bps, exp, sig: ("enterFromWork", rid),
            claimPrize=lambda rid: ("claimPrize", rid),
            refund=lambda rid: ("refund", rid),
        )


class Chain:
    """Records sent transactions; `revert` names the calls that get mined and revert."""

    def __init__(self, revert=()):
        self.sent = []
        self.revert = set(revert)

    def send(self, tx, value=0):
        self.sent.append((tx[0], value))
        if tx[0] in self.revert:
            raise TxReverted(f"transaction 0x{len(self.sent):064x} reverted")
        return {"status": 1}


def _enter(lottery, chain, *, voucher=None, seat=None, said=None):
    seats = []

    def fetch_work_seat(rid):
        seats.append(rid)
        return seat or {"participant_id": "0x" + "11" * 32, "weight_bps": 10000,
                        "expiry": 1, "signature": "0x" + "22" * 65}

    paid = enter_round(lottery, 7, address=ME, tickets=2, send=chain.send,
                       fetch_voucher=lambda rid: voucher, fetch_work_seat=fetch_work_seat,
                       say=(said.append if said is not None else lambda m: None))
    return paid, seats


class TestTheDoor:
    def test_a_contract_without_the_switch_is_entered_by_buying_tickets(self):
        chain = Chain()
        paid, seats = _enter(FakeLottery(), chain)
        assert paid is True
        assert chain.sent == [("buyTickets", 2 * PRICE)]
        assert seats == []

    def test_paid_tickets_off_takes_a_work_seat_and_pays_nothing(self):
        chain = Chain()
        paid, seats = _enter(FakeLottery(paid=False), chain)
        assert paid is False
        assert chain.sent == [("enterFromWork", 0)]
        assert seats == [7]

    def test_an_existing_work_seat_is_not_taken_twice(self):
        chain = Chain()
        paid, seats = _enter(FakeLottery(paid=False, seated=True), chain)
        assert (paid, chain.sent, seats) == (False, [], [])

    def test_paid_tickets_on_buys_tickets(self):
        chain = Chain()
        paid, _ = _enter(FakeLottery(paid=True), chain)
        assert paid is True
        assert chain.sent == [("buyTickets", 2 * PRICE)]

    def test_a_revert_with_data_is_not_read_as_an_old_contract(self):
        err = ContractLogicError("execution reverted: Paused", data="0x9e87fac8")
        with pytest.raises(ContractLogicError):
            paid_door_open(FakeLottery(switch_error=err))

    def test_a_transport_error_is_not_read_as_an_old_contract(self):
        with pytest.raises(ConnectionError):
            paid_door_open(FakeLottery(switch_error=ConnectionError("node down")))


class TestVouchers:
    VOUCHER = {"rep_bonus_bps": 500, "expiry": 9, "signature": "0x" + "33" * 65}

    def test_a_voucher_buys_once(self):
        chain = Chain()
        paid, _ = _enter(FakeLottery(), chain, voucher=self.VOUCHER)
        assert paid is True
        assert chain.sent == [("buyTicketsWithVoucher", 2 * PRICE)]

    def test_a_voucher_the_contract_refuses_falls_back_to_plain_tickets(self):
        chain = Chain(revert={"buyTicketsWithVoucher"})
        said = []
        paid, _ = _enter(FakeLottery(), chain, voucher=self.VOUCHER, said=said)
        assert paid is True
        assert chain.sent == [("buyTicketsWithVoucher", 2 * PRICE), ("buyTickets", 2 * PRICE)]
        assert any("voucher purchase reverted" in line for line in said)

    def test_a_reverted_purchase_is_an_error_not_a_purchase(self):
        chain = Chain(revert={"buyTickets"})
        said = []
        with pytest.raises(TxReverted):
            _enter(FakeLottery(), chain, said=said)
        assert not any("bought" in line for line in said)


class TestAfterTheDraw:
    def _follow(self, status, *, paid=True, winner=OTHER, claimed=False, revert=()):
        chain = Chain(revert=revert)
        said = []
        done = follow_up(FakeLottery(rounds={7: _round(status, winner, claimed)}), 7,
                         address=ME, paid=paid, send=chain.send, say=said.append)
        return done, chain.sent, said

    def test_an_open_round_is_followed_further(self):
        assert self._follow(STATUS_OPEN) == (False, [], [])

    def test_a_cancelled_round_gives_the_tickets_back(self):
        done, sent, said = self._follow(STATUS_CANCELLED)
        assert done is True
        assert sent == [("refund", 0)]
        assert any("refunded" in line for line in said)

    def test_a_cancelled_work_seat_has_nothing_to_refund(self):
        assert self._follow(STATUS_CANCELLED, paid=False) == (True, [], [])

    def test_a_refund_that_reverts_when_nothing_is_owed_any_more_is_dropped(self):
        done, sent, said = self._follow(STATUS_CANCELLED, revert={"refund"})
        assert done is True
        assert sent == [("refund", 0)]
        assert any("refund reverted" in line for line in said)

    def test_a_won_round_is_claimed(self):
        done, sent, _ = self._follow(STATUS_SETTLED, winner=ME)
        assert (done, sent) == (True, [("claimPrize", 0)])

    def test_a_lost_or_already_claimed_round_sends_nothing(self):
        assert self._follow(STATUS_SETTLED)[:2] == (True, [])
        assert self._follow(STATUS_SETTLED, winner=ME, claimed=True)[:2] == (True, [])


# ── audit 2026-11-11, satellites-5 ────────────────────────────────────────────
def _owing(lottery, owed: dict):
    lottery.functions.paidBy = lambda rid, a: _View(lambda: owed.get(rid, 0))
    return lottery


class TestNothingOwedIsDropped:
    def test_a_refund_that_reverts_while_still_owed_is_retried_after_backoff(self):
        from ailottery_agent.__main__ import FOLLOW_BACKOFF_S

        lottery = _owing(FakeLottery(rounds={7: _round(STATUS_CANCELLED)}), {7: 2 * PRICE})
        clock = [1000.0]
        state, said = {}, []
        failing = Chain(revert={"refund"})
        assert follow_up(lottery, 7, address=ME, paid=True, send=failing.send, say=said.append,
                         state=state, now=lambda: clock[0]) is False
        assert any("retrying" in line for line in said)
        assert follow_up(lottery, 7, address=ME, paid=True, send=failing.send, say=said.append,
                         state=state, now=lambda: clock[0]) is False
        assert failing.sent == [("refund", 0)], "nothing is resent inside the backoff"
        clock[0] += FOLLOW_BACKOFF_S
        ok = Chain()
        assert follow_up(lottery, 7, address=ME, paid=True, send=ok.send, say=said.append,
                         state=state, now=lambda: clock[0]) is True
        assert ok.sent == [("refund", 0)]

    def test_a_claim_that_keeps_reverting_is_given_up_after_the_limit(self):
        from ailottery_agent.__main__ import MAX_FOLLOW_TRIES

        lottery = FakeLottery(rounds={7: _round(STATUS_SETTLED, ME, False)})
        chain, state, said, clock = Chain(revert={"claimPrize"}), {}, [], [0.0]
        results = []
        for _ in range(MAX_FOLLOW_TRIES):
            results.append(follow_up(lottery, 7, address=ME, paid=True, send=chain.send,
                                     say=said.append, state=state, now=lambda: clock[0]))
            clock[0] += 10**6
        assert results == [False] * (MAX_FOLLOW_TRIES - 1) + [True]
        assert len(chain.sent) == MAX_FOLLOW_TRIES and "giving up" in said[-1]

    def test_tickets_already_bought_are_not_bought_again(self):
        lottery = _owing(FakeLottery(paid=True), {7: 2 * PRICE})
        chain, said = Chain(), []
        paid, _ = _enter(lottery, chain, said=said)
        assert paid is True and chain.sent == []
        assert any("already bought" in line for line in said)

    def test_a_restart_recovers_a_won_prize_and_a_refund(self):
        from ailottery_agent.__main__ import recover_rounds

        rounds = {5: _round(STATUS_SETTLED, ME, False), 6: _round(STATUS_CANCELLED),
                  7: _round(STATUS_SETTLED, OTHER, False), 8: _round(STATUS_OPEN)}
        lottery = _owing(FakeLottery(rounds=rounds), {6: PRICE})
        lottery.functions.currentRoundId = lambda: _View(lambda: 8)
        lottery.rounds.update({r: _round(STATUS_OPEN) for r in range(1, 5)})
        assert recover_rounds(lottery, ME) == ({5, 6}, {6})

    def test_a_restart_before_the_draw_recovers_the_rounds_the_agent_is_in(self):
        """Review of 2026-11-11: a round paid into (or work-seated) and still Open past its
        entries, or Drawing, was skipped by the recovery and never followed up."""
        from ailottery_agent.__main__ import STATUS_DRAWING, recover_rounds

        rounds = {r: _round(STATUS_OPEN) for r in range(1, 10)}   # entriesClose 0: closed
        rounds[9] = _round(STATUS_DRAWING)
        lottery = _owing(FakeLottery(rounds=rounds, paid=False, seated=False), {8: PRICE})
        lottery.functions.currentRoundId = lambda: _View(lambda: 9)
        seated = {9}
        lottery.functions.workSeated = lambda rid, a: _View(lambda: rid in seated)
        assert recover_rounds(lottery, ME, now=1_000) == ({8, 9}, {8})
        # an Open round still taking entries is left to the main loop
        assert recover_rounds(lottery, ME, now=None) == ({9}, set())


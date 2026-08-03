"""The draw path against the CURRENT contract rules.

Three of those rules changed under the relayer's feet in the fairness rework and
each one turns a relayer assumption into an on-chain revert:

  * `cancelRound` is refused while a Drawing round is still settleable, so the
    old "cancel so funds stay refundable" fail-safe now reverts and takes the
    round loop down with it.
  * an expired seed hash makes `fulfillDraw` revert no matter how good the
    beacon is; the only way forward is a rescue with FRESH entropy.
  * `maxDrawDelay()` is derived from a DECLARED block time the contract cannot
    verify, so a wrong declaration silently authorises a delay no seed survives.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from web3 import Web3

from ailottery_relayer.abi import (
    BLOCKHASH_WINDOW,
    MAX_RESEEDS,
    RESEED_COOLDOWN,
    STALL_CANCEL_DELAY,
)
from ailottery_relayer.chain import Chain
from ailottery_relayer.economy import EconomyEngine
from ailottery_relayer.economy_draw import (
    close_and_draw,
    ensure_settleable_seed,
    preflight_draw_window,
    safe_cancel,
    sweep_stalled_rounds,
)
from ailottery_relayer.oracles import OracleUnavailable

HEAD = 10_000


def _chain(**overrides) -> Chain:
    """A Chain bound to no RPC — only the pure/derived helpers are exercised."""
    c = Chain.__new__(Chain)
    c.block = lambda: {"number": HEAD, "timestamp": 1_700_000_000}
    c.blockhash = lambda n: b"\x11" * 32
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


# ── seed availability: the RPC hash outlives the EVM's ───────────────────────
def test_seed_status_tracks_the_evm_window_not_the_rpc():
    c = _chain()
    assert c.seed_status(HEAD + 1) == "pending"
    assert c.seed_status(HEAD) == "ready"
    # our tx executes at HEAD+1, whose oldest visible ancestor is HEAD+1-256
    assert c.seed_status(HEAD - (BLOCKHASH_WINDOW - 1)) == "ready"
    assert c.seed_status(HEAD - BLOCKHASH_WINDOW) == "expired"


def test_seed_blockhash_refuses_a_hash_the_contract_would_read_as_zero():
    c = _chain()
    # eth_getBlockByNumber happily answers for an ancient block; building a
    # beacon on it would produce a fulfillDraw that reverts BlockhashUnavailable.
    assert c.blockhash(HEAD - 5_000) == b"\x11" * 32
    assert c.seed_blockhash(HEAD - 5_000) is None
    assert c.seed_blockhash(HEAD - 10) == b"\x11" * 32


# ── cancelRound is refused mid-window ────────────────────────────────────────
def _round(status=2, seed_block=HEAD - 10, closed_at=1_700_000_000, commitment=b"\x99" * 32):
    return {"status": status, "seedBlock": seed_block, "closedAt": closed_at,
            "seedCommitment": commitment,
            "entriesClose": 1_699_999_000, "winner": "0x" + "0" * 40, "prizePool": 0}


def test_cancel_allowed_mirrors_the_contract_guard():
    settleable = _chain(get_round=lambda rid: _round(),
                        participants_count=lambda rid: 3)
    assert settleable.cancel_allowed(1) is False, \
        "a Drawing round whose outcome is already computable cannot be cancelled"

    expired = _chain(get_round=lambda rid: _round(seed_block=HEAD - 5_000),
                     participants_count=lambda rid: 3)
    assert expired.cancel_allowed(1) is True, "nobody can settle it — cancel is the exit"

    empty = _chain(get_round=lambda rid: _round(), participants_count=lambda rid: 0)
    assert empty.cancel_allowed(1) is True

    open_round = _chain(get_round=lambda rid: _round(status=1),
                        participants_count=lambda rid: 3)
    assert open_round.cancel_allowed(1) is True

    settled = _chain(get_round=lambda rid: _round(status=3),
                     participants_count=lambda rid: 3)
    assert settled.cancel_allowed(1) is False


def _engine(chain_kwargs=None, **kw):
    sent: list = []

    def _send(fn, key, **_):
        sent.append((fn, key))
        return {"status": 1}

    defaults = {
        "address": "0x000000000000000000000000000000000000dEaD",
        "send": _send,
        "mine": MagicMock(),
        "fast_forward": MagicMock(),
        "block": MagicMock(return_value={"number": HEAD, "timestamp": 1_700_000_000}),
        "min_draw_delay": MagicMock(return_value=60),
    }
    defaults.update(chain_kwargs or {})
    chain = SimpleNamespace(**defaults)
    engine = SimpleNamespace(
        chain=chain,
        cfg=SimpleNamespace(fast_forward=True, poll_interval=0.01,
                            chronos_canonical_n="", wei_to_usd=lambda w: 0.0),
        fn=SimpleNamespace(
            cancelRound=lambda rid: f"cancel:{rid}",
            cancelStalledRound=lambda rid: f"cancel-stalled:{rid}",
            closeEntries=lambda rid, c: f"close:{rid}:{c.hex()}",
            reseed=lambda rid, c: f"reseed:{rid}:{c.hex()}",
            fulfillDraw=lambda *a: "fulfill",
        ),
        operator_key="0xoperator",
        signer_key="0xsigner",
        _event=MagicMock(),
        _name=lambda a: "winner",
        last_winner="",
        stalled_rounds=[],
        **kw,
    )
    return engine, sent


def test_safe_cancel_does_not_fire_a_cancel_the_contract_would_reject():
    engine, sent = _engine({"cancel_allowed": lambda rid: False})
    assert safe_cancel(engine, 4, "no valid Chronos proof") is False
    assert sent == [], "a reverting cancelRound would abort the whole round loop"


def test_safe_cancel_still_cancels_when_the_round_is_unsettleable():
    engine, sent = _engine({"cancel_allowed": lambda rid: True})
    assert safe_cancel(engine, 4, "no participants") is True
    assert sent == [("cancel:4", "0xoperator")]


def test_safe_cancel_refuses_when_the_gate_cannot_be_evaluated():
    def _boom(rid):
        raise RuntimeError("rpc down")

    engine, sent = _engine({"cancel_allowed": _boom})
    assert safe_cancel(engine, 4, "no valid Chronos proof") is False
    assert sent == []


def test_chronos_failure_does_not_send_a_reverting_cancel():
    """The old fail-safe cancelled unconditionally; that path is now a revert."""
    r = _round()
    engine, sent = _engine({
        "participants_count": lambda rid: 2,
        "get_round": lambda rid: dict(r),
        "seed_status": lambda b, head=None: "ready",
        "seed_blockhash": lambda b: b"\x11" * 32,
        "cancel_allowed": lambda rid: False,      # still settleable
        "onchain_vdf": lambda: True,
        "reseed_count": lambda rid: 0,
    }, oracles=SimpleNamespace(
        sortes_draw=lambda seed: (b"\x02" * 32, None),
        chronos_eval=lambda seed, d: (None, None),   # oracle returns nothing usable
    ))
    assert close_and_draw(engine, 9) is False
    assert not any(str(fn).startswith("cancel:") for fn, _ in sent)
    assert any(str(fn).startswith("close:") for fn, _ in sent)


# ── the rescue path ──────────────────────────────────────────────────────────
def test_expired_seed_is_rescued_with_never_before_used_entropy():
    state = {"seed": "expired", "reseeds": 0}
    words = [b"\xaa" * 32, b"\xbb" * 32]

    def _get_round(rid):
        return _round(seed_block=HEAD - 5_000 if state["seed"] == "expired" else HEAD - 2)

    def _seed_status(block, head=None):
        return state["seed"]

    engine, sent = _engine({
        "get_round": _get_round,
        "seed_status": _seed_status,
        "reseed_count": lambda rid: state["reseeds"],
    })

    def _refresh(attempt):
        state["seed"] = "ready"
        state["reseeds"] = attempt
        return words[attempt]

    out = ensure_settleable_seed(engine, 3, words[0], _refresh)
    assert out is not None
    _r, word = out
    assert word == words[1], "the rescued round must settle with the FRESH word"

    reseeds = [fn for fn, _ in sent if str(fn).startswith("reseed:")]
    assert len(reseeds) == 1
    fresh_commitment = Web3.solidity_keccak(["bytes32"], [words[1]]).hex()
    stale_commitment = Web3.solidity_keccak(["bytes32"], [words[0]]).hex()
    assert fresh_commitment in reseeds[0]
    assert stale_commitment not in reseeds[0], \
        "re-committing the revealed word reverts StaleCommitment"


def test_rescue_budget_exhausted_gives_up_instead_of_reseeding():
    engine, sent = _engine({
        "get_round": lambda rid: _round(seed_block=HEAD - 5_000),
        "seed_status": lambda b, head=None: "expired",
        "reseed_count": lambda rid: MAX_RESEEDS,
    })
    assert ensure_settleable_seed(engine, 3, b"\xaa" * 32, lambda a: b"\xbb" * 32) is None
    assert sent == []


def test_rescue_is_deferred_rather_than_blocking_for_the_cooldown():
    """RESEED_COOLDOWN is an hour; a live relayer must not sit on it."""
    engine, sent = _engine({
        "get_round": lambda rid: _round(seed_block=HEAD - 5_000, closed_at=1_700_000_000),
        "seed_status": lambda b, head=None: "expired",
        "reseed_count": lambda rid: 0,
    })
    engine.cfg.fast_forward = False
    # closed one minute ago ⇒ the cooldown has not elapsed
    engine.chain.block = MagicMock(
        return_value={"number": HEAD, "timestamp": 1_700_000_000 + RESEED_COOLDOWN - 60})
    assert ensure_settleable_seed(engine, 3, b"\xaa" * 32, lambda a: b"\xbb" * 32) is None
    assert sent == []


def test_rescue_without_fresh_entropy_is_not_attempted():
    """A rescue the oracle cannot feed must leave the round rescuable, not reseed
    something the contract will reject."""
    def _refresh(attempt):
        raise OracleUnavailable("draw oracle down")

    engine, sent = _engine({
        "get_round": lambda rid: _round(seed_block=HEAD - 5_000),
        "seed_status": lambda b, head=None: "expired",
        "reseed_count": lambda rid: 0,
    })
    assert ensure_settleable_seed(engine, 3, b"\xaa" * 32, _refresh) is None
    assert sent == []


def test_settleable_seed_needs_no_rescue():
    engine, sent = _engine({
        "get_round": lambda rid: _round(seed_block=HEAD - 2),
        "seed_status": lambda b, head=None: "ready",
        "reseed_count": lambda rid: 0,
    })
    out = ensure_settleable_seed(engine, 3, b"\xaa" * 32, lambda a: b"\xbb" * 32)
    assert out is not None and out[1] == b"\xaa" * 32
    assert sent == []


# ── the declared-block-time footgun ──────────────────────────────────────────
def test_preflight_refuses_a_draw_delay_no_seed_can_survive():
    """GOVERNANCE declaring 60 s/block on a 2 s chain inflates maxDrawDelay 30×;
    the contract accepts a 1 h minDrawDelay that expires every single seed."""
    engine, _ = _engine({
        "min_draw_delay": MagicMock(return_value=3600),
        "seconds_per_block": MagicMock(return_value=60),
        "observed_seconds_per_block": MagicMock(return_value=2.0),
    })
    engine.cfg.fast_forward = False
    assert preflight_draw_window(engine) is False


def test_preflight_passes_on_an_honestly_declared_chain():
    engine, _ = _engine({
        "min_draw_delay": MagicMock(return_value=30),
        "seconds_per_block": MagicMock(return_value=2),
        "observed_seconds_per_block": MagicMock(return_value=2.0),
    })
    engine.cfg.fast_forward = False
    assert preflight_draw_window(engine) is True


def test_preflight_falls_back_to_the_declaration_when_it_cannot_measure():
    """A dev chain that mines on demand has no measurable block time; the
    on-chain bound still applies, so we do not block the demo."""
    engine, _ = _engine({
        "min_draw_delay": MagicMock(return_value=30),
        "seconds_per_block": MagicMock(return_value=2),
        "observed_seconds_per_block": MagicMock(return_value=None),
    })
    engine.cfg.fast_forward = False
    assert preflight_draw_window(engine) is True


def test_preflight_refuses_a_delay_that_only_fits_under_the_declaration():
    """The narrow overstatement, which a raw-window check waves through.

    Declaring 4 s on a 2 s chain doubles `maxDrawDelay()` to 520 s, so the
    contract accepts `minDrawDelay = 519`. The seed still dies at ~520 s
    (260 blocks × 2 s), so every round reaches its draw with well under a block
    of margin — undrawable in practice, and exactly the headroom the contract's
    own `DRAW_DELAY_HEADROOM` divisor reserves.
    """
    engine, _ = _engine({
        "min_draw_delay": MagicMock(return_value=519),
        "seconds_per_block": MagicMock(return_value=4),
        "observed_seconds_per_block": MagicMock(return_value=2.0),
    })
    engine.cfg.fast_forward = False
    assert preflight_draw_window(engine) is False


def test_preflight_allows_the_exact_ceiling_the_contract_allows():
    """No false refusal: `setMinDrawDelay` accepts `maxDrawDelay()` itself, so a
    correctly declared chain sitting on that ceiling must still open rounds."""
    engine, _ = _engine({
        "min_draw_delay": MagicMock(return_value=260),   # == maxDrawDelay() at 2 s
        "seconds_per_block": MagicMock(return_value=2),
        "observed_seconds_per_block": MagicMock(return_value=2.0),
    })
    engine.cfg.fast_forward = False
    assert preflight_draw_window(engine) is True


# ── the rescue must not fire a call the contract will reject ─────────────────
def test_rescue_refuses_to_recommit_the_currently_pinned_commitment():
    """A draw oracle stuck on one value would make `reseed` revert
    `StaleCommitment`, and that revert raises out of the draw — abandoning a
    round that a later attempt could still have rescued."""
    stale = b"\xaa" * 32
    engine, sent = _engine({
        "get_round": lambda rid: _round(
            seed_block=HEAD - 5_000,
            commitment=Web3.solidity_keccak(["bytes32"], [stale])),
        "seed_status": lambda b, head=None: "expired",
        "reseed_count": lambda rid: 0,
    })
    assert ensure_settleable_seed(engine, 3, stale, lambda attempt: stale) is None
    assert sent == [], "a guaranteed-revert reseed must never be broadcast"


# ── a round the draw gave up on must not stay locked ─────────────────────────
def test_sweep_cancels_a_round_the_contract_will_now_let_go():
    """Once the seed ages out nobody can settle the round, so `cancelRound` is
    accepted again — and that is what opens `refund` for tickets and funding."""
    # the REAL guard, over a chain whose seed has aged out of the EVM's window
    guard = _chain(get_round=lambda rid: _round(seed_block=HEAD - 5_000),
                   participants_count=lambda rid: 3)
    engine, sent = _engine({
        "get_round": lambda rid: _round(seed_block=HEAD - 5_000),
        "cancel_allowed": guard.cancel_allowed,
    })
    assert sweep_stalled_rounds(engine, [11]) == []
    assert sent == [("cancel:11", "0xoperator")]


def test_sweep_uses_the_permissionless_stall_exit_when_cancel_stays_refused():
    """A round that stayed settleable but that we could never prove a beacon for
    is released by `cancelStalledRound` after STALL_CANCEL_DELAY. Without this,
    the entries sit there until an outside party happens to notice."""
    closed = 1_700_000_000
    engine, sent = _engine({
        "get_round": lambda rid: _round(closed_at=closed),
        "cancel_allowed": lambda rid: False,   # still settleable ⇒ cancelRound reverts
    })
    engine.chain.block = MagicMock(
        return_value={"number": HEAD, "timestamp": closed + STALL_CANCEL_DELAY})
    assert sweep_stalled_rounds(engine, [12]) == []
    assert sent == [("cancel-stalled:12", "0xoperator")]


def test_sweep_leaves_a_round_alone_before_the_stall_delay():
    closed = 1_700_000_000
    engine, sent = _engine({
        "get_round": lambda rid: _round(closed_at=closed),
        "cancel_allowed": lambda rid: False,
    })
    engine.chain.block = MagicMock(
        return_value={"number": HEAD, "timestamp": closed + STALL_CANCEL_DELAY - 1})
    assert sweep_stalled_rounds(engine, [13]) == [13], "must be retried, not dropped"
    assert sent == []


def test_sweep_forgets_a_round_somebody_else_finished():
    engine, sent = _engine({"get_round": lambda rid: _round(status=3)})  # Settled
    assert sweep_stalled_rounds(engine, [14]) == []
    assert sent == []


def test_sweep_keeps_a_round_it_could_not_evaluate():
    def _boom(rid):
        raise RuntimeError("rpc down")

    engine, sent = _engine({"get_round": _boom})
    assert sweep_stalled_rounds(engine, [15]) == [15]
    assert sent == []


# ── the PRODUCTION draw path (EconomyEngine.close_and_draw) ──────────────────
def _production_engine(chain_kwargs, **kw):
    """The real `EconomyEngine.close_and_draw` bound to doubles.

    `economy_draw.close_and_draw` is a second copy of this logic that only the
    tests call; the relayer actually runs the method on EconomyEngine, so the
    fail-safes have to be pinned there too.
    """
    engine, sent = _engine(chain_kwargs, **kw)
    engine._advance_to_close = lambda rid: engine.chain.get_round(rid)
    return engine, sent


def test_production_draw_does_not_fire_a_reverting_cancel_and_queues_the_round():
    engine, sent = _production_engine({
        "participants_count": lambda rid: 2,
        "get_round": lambda rid: _round(),
        "seed_status": lambda b, head=None: "ready",
        "seed_blockhash": lambda b: b"\x11" * 32,
        "cancel_allowed": lambda rid: False,      # still settleable
        "onchain_vdf": lambda: True,
        "reseed_count": lambda rid: 0,
    }, oracles=SimpleNamespace(
        platon_random=lambda seed: (b"\x02" * 32, None),
        chronos_eval=lambda seed, d: (None, None),   # no usable proof
    ))
    assert EconomyEngine.close_and_draw(engine, 21) is False
    assert not any(str(fn).startswith("cancel") for fn, _ in sent)
    assert engine.stalled_rounds == [21], \
        "an abandoned Drawing round must be queued for the sweep, not forgotten"


def test_production_round_loop_sells_no_tickets_into_an_undrawable_round():
    engine, _ = _production_engine({
        "min_draw_delay": MagicMock(return_value=3600),
        "seconds_per_block": MagicMock(return_value=60),
        "observed_seconds_per_block": MagicMock(return_value=2.0),
    })
    engine.cfg.fast_forward = False
    engine.open_round = MagicMock()
    engine.sell_tickets = MagicMock()
    engine.publish = MagicMock()
    EconomyEngine.run_one_round(engine)
    engine.open_round.assert_not_called()
    engine.sell_tickets.assert_not_called()


def test_sweep_still_cancels_an_open_round_that_may_hold_sponsor_funding():
    """A round with zero tickets can still hold `fund()` money, and only a cancel
    makes that refundable — `cancelStalledRound` requires Drawing, so an Open
    round dropped here would strand it."""
    guard = _chain(get_round=lambda rid: _round(status=1),
                   participants_count=lambda rid: 0)
    engine, sent = _engine({
        "get_round": lambda rid: _round(status=1),
        "cancel_allowed": guard.cancel_allowed,
    })
    assert sweep_stalled_rounds(engine, [16]) == []
    assert sent == [("cancel:16", "0xoperator")]


def test_empty_round_whose_cancel_could_not_be_evaluated_is_queued():
    def _boom(rid):
        raise RuntimeError("rpc down")

    engine, sent = _engine({
        "participants_count": lambda rid: 0,
        "cancel_allowed": _boom,
    })
    assert close_and_draw(engine, 17) is False
    assert sent == []
    assert engine.stalled_rounds == [17], \
        "sponsor funding in an uncancelled round has no other exit"

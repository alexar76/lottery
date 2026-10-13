"""Draw phase — close entries, oracle randomness, optional VDF, fulfill.

The contract's fairness rules bound what this module may do, and several of them
changed the shape of the happy path:

  * `fulfillDraw` is PERMISSIONLESS and not Pausable-gated. The relayer still
    submits it (it holds the beacon), but it is no longer a privileged action and
    a paused contract must not stop us from settling a drawable round.
  * `cancelRound` is REFUSED while a Drawing round is still settleable. A
    fail-safe path that cancels blindly now reverts and takes the round loop down
    with it, so every cancel asks `Chain.cancel_allowed` first.
  * `reseed` is a rescue that demands FRESH, never-before-used entropy. Rescuing a
    round therefore means a new oracle draw, not a resubmission of the old word.
  * The wall-clock draw bound is derived from the chain's DECLARED block time. If
    that declaration is wrong, every seed expires before its draw is even valid —
    the contract cannot detect this, but the relayer can measure the real one.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable, Optional

from web3 import Web3

from .abi import (
    DRAW_DELAY_HEADROOM,
    MAX_RESEEDS,
    RESEED_COOLDOWN,
    SEED_LIFETIME_BLOCKS,
    STALL_CANCEL_DELAY,
    STATUS_DRAWING,
    STATUS_OPEN,
)
from .log import get_logger
from .oracles import PRICE, OracleUnavailable
from .vdf import base_seed, empty_proof, proof_from_chronos, seed_string

if TYPE_CHECKING:
    from .economy import EconomyEngine

log = get_logger("economy.draw")

# Absolute ceiling on any in-round wait, so a stuck chain (anvil paused, RPC
# down) cannot hang the relayer forever.
_WAIT_TIMEOUT_S = 300


def advance_to_close(engine: EconomyEngine, rid: int) -> dict:
    r = engine.chain.get_round(rid)
    target = r["entriesClose"] + 1
    if engine.cfg.fast_forward:
        now = engine.chain.block()["timestamp"]
        if now < target:
            engine.chain.fast_forward(target - now)
    else:
        while engine.chain.block()["timestamp"] < target:
            time.sleep(engine.cfg.poll_interval)
    return engine.chain.get_round(rid)


def safe_cancel(engine: EconomyEngine, rid: int, why: str) -> bool:
    """Cancel `rid` only if the contract would actually accept it.

    `cancelRound` reverts on a Drawing round whose pinned blockhash is still
    readable — deliberately, so the operator cannot look at the seed block,
    compute the winner and cancel an outcome it dislikes. Firing it anyway turns
    a recoverable round into a raised `tx reverted` that aborts the round loop,
    so the fail-safe would itself be the failure. When the cancel is refused the
    round simply stays Drawing: it is still settleable by anyone holding a valid
    beacon, still rescuable, and `cancelStalledRound` refunds everyone
    permissionlessly after STALL_CANCEL_DELAY.
    """
    try:
        allowed = engine.chain.cancel_allowed(rid)
    except Exception as exc:
        # Cannot evaluate the gate ⇒ do not fire a tx that probably reverts.
        log.error("round %s: cancel pre-check failed (%s) — leaving the round in place", rid, exc)
        return False
    if not allowed:
        log.error(
            "round %s: %s, but cancelRound is REFUSED while the round is still "
            "settleable — leaving it Drawing (any valid beacon still settles it; "
            "cancelStalledRound refunds everyone after the stall delay)", rid, why)
        return False
    engine.chain.send(engine.fn.cancelRound(rid), engine.operator_key)
    engine._event("operator", "cancel", f"round {rid}", 0)
    return True


def defer_stalled(engine: EconomyEngine, rid: int) -> None:
    """Remember a live round we could not close out, so the sweep revisits it.

    Every abandoned-draw exit below runs through here: a round still holding
    tickets or sponsor funding must never be dropped on the floor just because
    this cycle gave up on it.
    """
    if rid not in engine.stalled_rounds:
        engine.stalled_rounds.append(rid)
        log.warning("round %s left unresolved — queued for the stalled-round sweep", rid)


def sweep_stalled_rounds(engine: EconomyEngine, rounds: list[int]) -> list[int]:
    """Finish off rounds an earlier cycle had to leave sitting in `Drawing`.

    `safe_cancel` refusing a cancel the contract would reject is correct, but on
    its own it converts "the draw failed" into "the entries are locked in a round
    nothing revisits": the relayer opens a fresh round on the next cycle and never
    looks at the old one again. Both exits the contract offers are used here —
    `cancelRound` the moment the contract stops considering the round settleable
    (seed aged out, or never mined), and the permissionless `cancelStalledRound`
    after STALL_CANCEL_DELAY for a round that stayed settleable but that we could
    never produce a proof for. Either way agents get their tickets and sponsors
    their funding back via `refund`, instead of waiting for an outside party to
    notice.

    Cancelling forfeits the rescue that a still-expired round technically still
    has budget for. That is deliberate: this engine does not re-enter the draw for
    a round it has already given up on, so the honest choice is a refund now
    rather than an indefinite hold.

    Returns the rounds still outstanding, to be retried on the next cycle.
    """
    still: list[int] = []
    for rid in rounds:
        try:
            r = engine.chain.get_round(rid)
            status = int(r["status"])
            if status not in (STATUS_OPEN, STATUS_DRAWING):
                continue  # settled or cancelled in the meantime — nothing owed
            if safe_cancel(engine, rid, "draw abandoned on an earlier cycle"):
                continue
            now = engine.chain.block()["timestamp"]
            # Only a Drawing round has the stall exit; an Open one is always
            # cancellable, so reaching here means the cancel itself failed.
            if status == STATUS_DRAWING and now >= int(r["closedAt"]) + STALL_CANCEL_DELAY:
                # Permissionless, and the contract's delay is orders of magnitude
                # past any legitimate settle path, so this cannot kill a drawable
                # round. We submit it because we are the only party that knows
                # this round was abandoned.
                engine.chain.send(engine.fn.cancelStalledRound(rid), engine.operator_key)
                engine._event("operator", "cancel-stalled", f"round {rid}", 0)
                continue
        except Exception as exc:
            log.error("round %s: stalled-round sweep failed (%s) — retrying next cycle",
                      rid, exc)
        still.append(rid)
    return still


def preflight_draw_window(engine: EconomyEngine) -> bool:
    """Refuse to run a round whose seed cannot survive its own draw delay.

    `maxDrawDelay()` is derived from `secondsPerBlock`, which governance DECLARES
    — the contract has no way to measure the real one. Declaring 60 on a 2 s
    chain inflates the bound 30× and lets an admin set a `minDrawDelay` longer
    than the ~SEED_LIFETIME_BLOCKS-block settle window actually lasts; every seed
    then expires before its draw is valid and every round bricks into the rescue
    path (and, after MAX_RESEEDS, into a refund). We measure the block time the
    chain really has, re-run the contract's own bound on it, and fail closed
    rather than sell tickets into a round that cannot be drawn.
    """
    try:
        delay = engine.chain.min_draw_delay()
        declared = engine.chain.seconds_per_block()
    except Exception as exc:
        log.warning("draw-window preflight skipped (contract unreadable: %s)", exc)
        return True

    observed = None if engine.cfg.fast_forward else engine.chain.observed_seconds_per_block()
    # No measurement available (fresh chain, on-demand mining) ⇒ fall back to the
    # declaration, which the contract already enforces its own bound against.
    spb = observed if observed else declared
    # Re-run the CONTRACT'S OWN guard (`minDrawDelay <= maxDrawDelay(secondsPerBlock)`)
    # against the block time we measured rather than the one governance declared.
    # Checking against the raw SEED_LIFETIME_BLOCKS window instead would leave a
    # whole factor of DRAW_DELAY_HEADROOM open: declare 4 s on a 2 s chain and the
    # contract accepts a 519 s delay, while the seed still dies at ~520 s — every
    # round would reach its draw with under a block of margin, i.e. undrawable in
    # practice, yet a window-only check would wave it through.
    bound = (SEED_LIFETIME_BLOCKS * spb) / DRAW_DELAY_HEADROOM
    if delay > bound:
        log.error(
            "REFUSING to open a round: minDrawDelay=%ss exceeds the %.0fs the settle "
            "window can carry (%s blocks × %.2fs/block%s ÷ %s headroom) — seeds would "
            "expire before their draw is valid and every round would burn its rescue "
            "budget. Lower MIN_DRAW_DELAY or have GOVERNANCE correct "
            "setSecondsPerBlock (declared %ss).",
            delay, bound, SEED_LIFETIME_BLOCKS, spb,
            " measured" if observed else " declared", DRAW_DELAY_HEADROOM, declared)
        return False
    return True


def _wait_for_draw_delay(engine: EconomyEngine, rid: int) -> bool:
    """Block until `closedAt + minDrawDelay` has passed for the CURRENT seed."""
    mdd = engine.chain.min_draw_delay()
    r = engine.chain.get_round(rid)
    if engine.cfg.fast_forward:
        now = engine.chain.block()["timestamp"]
        target = r["closedAt"] + mdd + 1
        if now < target:
            engine.chain.fast_forward(target - now)
        engine.chain.mine()
        return True
    deadline = time.monotonic() + _WAIT_TIMEOUT_S
    while engine.chain.block()["timestamp"] < r["closedAt"] + mdd:
        if time.monotonic() > deadline:
            log.error("round %s: min_draw_delay wait timed out after %s s", rid, _WAIT_TIMEOUT_S)
            return False
        time.sleep(engine.cfg.poll_interval)
    return True


def ensure_settleable_seed(
    engine: EconomyEngine,
    rid: int,
    word: bytes,
    refresh_word: Callable[[int], bytes],
) -> Optional[tuple[dict, bytes]]:
    """Return `(round, randomness)` the contract can actually settle with.

    The pinned seed hash lives inside the EVM's BLOCKHASH_WINDOW. Once it ages
    out, `blockhash(seedBlock)` is permanently zero and `fulfillDraw` reverts
    `BlockhashUnavailable` no matter how good the beacon is — the round can only
    be rescued. A rescue is not a re-roll: the contract rejects a commitment the
    round has already used, so `refresh_word` must produce NEW entropy, which is
    then committed before the new seed block exists.

    Returns None when the round cannot be settled; the caller keeps the funds
    recoverable rather than submitting a doomed draw.
    """
    for _ in range(MAX_RESEEDS + 1):
        if not _wait_for_draw_delay(engine, rid):
            return None
        r = engine.chain.get_round(rid)
        if int(r["status"]) != STATUS_DRAWING:
            log.info("round %s left Drawing (status=%s) — nothing to settle", rid, r["status"])
            return None

        status = _await_seed_block(engine, r["seedBlock"])
        if status == "ready":
            return r, word
        if status == "pending":
            log.error("round %s: seed block %s never arrived", rid, r["seedBlock"])
            return None

        used = engine.chain.reseed_count(rid)
        if used >= MAX_RESEEDS:
            log.error("round %s: seed expired and the rescue budget (%s) is spent — "
                      "the round can only be cancelled and refunded", rid, MAX_RESEEDS)
            return None
        if not _await_reseed_cooldown(engine, rid, r):
            return None

        try:
            word = refresh_word(used + 1)
        except OracleUnavailable as exc:
            log.error("round %s: rescue needs FRESH entropy but the draw oracle is "
                      "unavailable (%s) — leaving the round rescuable", rid, exc)
            return None
        commitment = Web3.solidity_keccak(["bytes32"], [word])
        if commitment == bytes(r["seedCommitment"]):
            # The contract records every commitment a round has used and reverts
            # StaleCommitment on a repeat. Sending it anyway buys a guaranteed
            # revert that raises out of the draw and abandons a round we could
            # still rescue on a later attempt, so refuse instead.
            log.error("round %s: the rescue oracle re-derived the commitment already "
                      "pinned on this round — it is not producing fresh randomness; "
                      "leaving the round rescuable rather than reverting", rid)
            return None
        engine.chain.send(engine.fn.reseed(rid, commitment), engine.operator_key)
        engine._event("operator", "reseed", f"round {rid}", 0)
        log.warning("round %s: seed expired — rescued with fresh entropy (rescue %s/%s)",
                    rid, used + 1, MAX_RESEEDS)
    return None


def _await_seed_block(engine: EconomyEngine, seed_block: int) -> str:
    """Resolve the seed block's state, mining/waiting out a not-yet-mined pin."""
    status = engine.chain.seed_status(seed_block)
    if status != "pending":
        return status
    deadline = time.monotonic() + _WAIT_TIMEOUT_S
    while status == "pending":
        if time.monotonic() > deadline:
            return "pending"
        engine.chain.mine()  # no-op off anvil; real chains just produce blocks
        if not engine.cfg.fast_forward:
            time.sleep(engine.cfg.poll_interval)
        status = engine.chain.seed_status(seed_block)
    return status


def _await_reseed_cooldown(engine: EconomyEngine, rid: int, r: dict) -> bool:
    """RESEED_COOLDOWN must elapse from the CURRENT seed pin before a rescue."""
    ready_at = int(r["closedAt"]) + RESEED_COOLDOWN
    now = engine.chain.block()["timestamp"]
    if now >= ready_at:
        return True
    if engine.cfg.fast_forward:
        engine.chain.fast_forward(ready_at - now + 1)
        return True
    # Never block a live relayer for an hour: the round stays Drawing, so it is
    # still settleable/rescuable later and `cancelStalledRound` refunds everyone
    # permissionlessly after the stall delay.
    log.error("round %s: rescue available in %ss (RESEED_COOLDOWN) — deferring; the "
              "round remains rescuable and is permissionlessly refundable after the "
              "stall delay", rid, ready_at - now)
    return False


def close_and_draw(engine: EconomyEngine, rid: int) -> bool:
    if engine.chain.participants_count(rid) == 0:
        # No tickets, but `fund()` may still have put sponsor money in this round,
        # and only a cancel makes that refundable — so a failed cancel is queued.
        log.info("round %s had no participants → cancel", rid)
        if not safe_cancel(engine, rid, "no participants"):
            defer_stalled(engine, rid)
        return False

    advance_to_close(engine, rid)

    def _draw_word(attempt: int = 0) -> bytes:
        # A rescue MUST bring entropy the round has never committed, so the VRF
        # client seed carries the attempt number.
        client_seed = f"{engine.chain.address}|{rid}" if attempt == 0 \
            else f"{engine.chain.address}|{rid}|reseed{attempt}"
        w, _ = engine.oracles.sortes_draw(client_seed)
        engine._event("lottery", "invoke", "Sortes", PRICE["sortes.draw@v1"])
        return w

    try:
        draw_word = _draw_word()
    except OracleUnavailable as exc:
        # The VRF draw oracle is down. Do NOT close with a fallback word (it would
        # be publicly grindable) — cancel the round so tickets stay refundable and
        # retry on a later round once the oracle is reachable again.
        log.error("round %s: draw oracle unavailable (%s) — cancelling to keep "
                  "funds refundable rather than drawing a predictable winner", rid, exc)
        safe_cancel(engine, rid, "draw oracle unavailable")
        return False
    commitment = Web3.solidity_keccak(["bytes32"], [draw_word])
    engine.chain.send(engine.fn.closeEntries(rid, commitment), engine.operator_key)
    engine._event("operator", "close", f"round {rid}", 0)

    engine.chain.mine()
    settleable = ensure_settleable_seed(engine, rid, draw_word, _draw_word)
    if settleable is None:
        if not safe_cancel(engine, rid, "no settleable seed"):
            defer_stalled(engine, rid)
        return False
    r, draw_word = settleable

    if engine.chain.onchain_vdf():
        bh = engine.chain.seed_blockhash(r["seedBlock"])
        if bh is None:  # raced out of the window between the check and here
            log.error("round %s: seed hash expired mid-draw — not submitting a "
                      "beacon the contract cannot bind", rid)
            defer_stalled(engine, rid)
            return False
        seed = seed_string(base_seed(rid, bh, draw_word))
        difficulty = 100_000
        out, _ = engine.oracles.chronos_eval(seed, difficulty)
        engine._event("lottery", "invoke", "Chronos", PRICE["chronos.eval@v1"])
        proof = None
        if out and all(out.get(k) for k in ("g", "y", "modulus")) and isinstance(out.get("proof"), dict):
            try:
                proof = proof_from_chronos(
                    seed, out["modulus"], out["g"], out["y"],
                    out["proof"].get("pi"), out["proof"].get("l"),
                    difficulty, engine.cfg.chronos_canonical_n)
            except Exception as exc:
                log.error("onchain VDF proof parse failed: %s", exc)
        if proof is None:
            log.error("round %s: onchain_vdf=true but no valid Chronos proof "
                      "(Chronos must use the contract's canonical modulus; set "
                      "CHRONOS_CANONICAL_N) — trying to keep funds refundable", rid)
            if not safe_cancel(engine, rid, "no valid Chronos proof"):
                defer_stalled(engine, rid)
            return False
        vdf_t = difficulty
    else:
        engine._event("lottery", "invoke", "Chronos", PRICE["chronos.eval@v1"])
        proof, vdf_t = empty_proof(), 0

    proof_hash = proof.proof_hash()
    sig = engine.chain.sign_beacon(engine.signer_key, rid, draw_word, vdf_t, proof_hash)
    # Permissionless since the fairness rework — the beacon, not the caller's
    # role, is what opens this. We submit with the operator key because it is the
    # funded one, not because the contract requires it.
    engine.chain.send(engine.fn.fulfillDraw(rid, draw_word, vdf_t, sig, proof.as_tuple()), engine.operator_key)

    r = engine.chain.get_round(rid)
    engine.last_winner = engine._name(r["winner"])
    prize_usd = engine.cfg.wei_to_usd(r["prizePool"])
    engine._event("lottery", "prize", engine.last_winner, prize_usd)
    log.info("round %s drawn — winner %s, prize $%.4f", rid, engine.last_winner, prize_usd)
    return True

"""Draw phase — close entries, oracle randomness, optional VDF, fulfill."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from web3 import Web3

from .log import get_logger
from .oracles import PRICE, OracleUnavailable
from .vdf import base_seed, empty_proof, proof_from_chronos, seed_string

if TYPE_CHECKING:
    from .economy import EconomyEngine

log = get_logger("economy.draw")


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


def close_and_draw(engine: EconomyEngine, rid: int) -> bool:
    if engine.chain.participants_count(rid) == 0:
        log.info("round %s had no participants → cancel", rid)
        engine.chain.send(engine.fn.cancelRound(rid), engine.operator_key)
        engine._event("operator", "cancel", f"round {rid}", 0)
        return False

    advance_to_close(engine, rid)

    client_seed = f"{engine.chain.address}|{rid}"
    try:
        draw_word, _ = engine.oracles.sortes_draw(client_seed)
    except OracleUnavailable as exc:
        # The VRF draw oracle is down. Do NOT close with a fallback word (it would
        # be publicly grindable) — cancel the round so tickets stay refundable and
        # retry on a later round once the oracle is reachable again.
        log.error("round %s: draw oracle unavailable (%s) — cancelling to keep "
                  "funds refundable rather than drawing a predictable winner", rid, exc)
        engine.chain.send(engine.fn.cancelRound(rid), engine.operator_key)
        engine._event("operator", "cancel", f"round {rid}", 0)
        return False
    engine._event("lottery", "invoke", "Sortes", PRICE["sortes.draw@v1"])
    commitment = Web3.solidity_keccak(["bytes32"], [draw_word])
    engine.chain.send(engine.fn.closeEntries(rid, commitment), engine.operator_key)
    engine._event("operator", "close", f"round {rid}", 0)

    engine.chain.mine()
    r = engine.chain.get_round(rid)
    mdd = engine.chain.min_draw_delay()
    if engine.cfg.fast_forward:
        engine.chain.fast_forward(mdd + 1)
    else:
        # SECURITY: bounded wait with absolute timeout (max 5 min) so a stuck
        # chain (anvil paused, RPC down) does not hang the relayer forever.
        deadline = time.monotonic() + 300
        while engine.chain.block()["timestamp"] < r["closedAt"] + mdd:
            if time.monotonic() > deadline:
                log.error("round %s: min_draw_delay wait timed out after 300 s", rid)
                return False
            time.sleep(engine.cfg.poll_interval)

    if engine.chain.onchain_vdf():
        bh = engine.chain.blockhash(r["seedBlock"])
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
                      "CHRONOS_CANONICAL_N) — cancelling to keep funds refundable", rid)
            engine.chain.send(engine.fn.cancelRound(rid), engine.operator_key)
            engine._event("operator", "cancel", f"round {rid}", 0)
            return False
        vdf_t = difficulty
    else:
        engine._event("lottery", "invoke", "Chronos", PRICE["chronos.eval@v1"])
        proof, vdf_t = empty_proof(), 0

    proof_hash = proof.proof_hash()
    sig = engine.chain.sign_beacon(engine.signer_key, rid, draw_word, vdf_t, proof_hash)
    engine.chain.send(engine.fn.fulfillDraw(rid, draw_word, vdf_t, sig, proof.as_tuple()), engine.operator_key)

    r = engine.chain.get_round(rid)
    engine.last_winner = engine._name(r["winner"])
    prize_usd = engine.cfg.wei_to_usd(r["prizePool"])
    engine._event("lottery", "prize", engine.last_winner, prize_usd)
    log.info("round %s drawn — winner %s, prize $%.4f", rid, engine.last_winner, prize_usd)
    return True

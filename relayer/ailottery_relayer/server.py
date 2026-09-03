"""Read-only observability API + a reputation-voucher minting endpoint.

The voucher endpoint lets a participating agent obtain a signed LUMEN reputation
voucher (ORACLE_SIGNER-signed EIP-712) that the contract verifies in
`buyTicketsWithVoucher`. The bonus is obtained by **really invoking the LUMEN
reputation oracle** through the same `OracleClient` the round loop uses — priced and
booked as opex in live deployments (Hub or direct oracle-family), with a deterministic
per-agent fallback only when the oracle is unreachable. So the standalone agent's odds
boost is oracle-derived, identical to the synthetic crowd's path — not a bypass.
"""
from __future__ import annotations

import os
import threading
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from web3 import Web3

# Mirrors AIAgentLottery.MAX_REP_BONUS_BPS (reputation can add ≤ +50% odds). The
# contract rejects a voucher above this, so we cap defensively before signing.
MAX_REP_BONUS_BPS = 5_000


class VoucherRequest(BaseModel):
    agent: str
    round_id: int | None = None


#: /voucher rationing. Each request is one priced oracle invoke plus one signature.
_VOUCHER_WINDOW_S = 3600.0
_VOUCHER_MAX_PER_AGENT = 12
_VOUCHER_MAX_PER_IP = 60
_voucher_by_agent: dict[str, list[float]] = {}
_voucher_by_ip: dict[str, list[float]] = {}
_voucher_lock = threading.Lock()


def _allow(bucket: dict[str, list[float]], key: str, limit: int) -> bool:
    """Sliding-window limiter. Locked: uvicorn serves this from a daemon thread while the
    round loop runs in the main one."""
    now = time.time()
    window = now - _VOUCHER_WINDOW_S
    with _voucher_lock:
        hits = [t for t in bucket.get(key, []) if t > window]
        if len(hits) >= limit:
            bucket[key] = hits
            return False
        hits.append(now)
        bucket[key] = hits
        if len(bucket) > 4096:
            for k in [k for k, v in bucket.items() if not v or max(v) <= window][:2048]:
                bucket.pop(k, None)
        return True


def _allow_pseudo_voucher_bonus() -> bool:
    """Opt-in: let /voucher sign the deterministic stand-in bonus again.

    Off by default. A showcase that wants visibly varied odds without a real trust graph
    can set LOTTERY_ALLOW_PSEUDO_VOUCHER_BONUS=1 -- with the keyed stand-in and the rate
    limit above, that is a deliberate demo choice rather than a free maximum boost.
    """
    return (os.getenv("LOTTERY_ALLOW_PSEUDO_VOUCHER_BONUS") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def make_app(engine) -> FastAPI:
    app = FastAPI(title="AI-Agent Oracle Lottery — relayer", version="0.1.0")
    # Let the public showcase poll /economy from its own origin. The feed is read-only.
    # /voucher is mutating in the sense that matters: it makes the ORACLE_SIGNER key sign
    # an odds boost. "Harmless without that agent's key" was the wrong threat model — the
    # attacker generates the address, so it holds the key. See the rate limit and the
    # no-stand-in rule below. Defaults to "*"; override with LOTTERY_CORS_ORIGINS.
    origins = [o.strip() for o in os.getenv("LOTTERY_CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "mode": engine.cfg.mode, "address": engine.chain.address}

    @app.get("/economy")
    def economy():
        return engine.state or engine.snapshot()

    @app.get("/rounds/{rid}")
    def round_info(rid: int):
        r = engine.chain.get_round(rid)
        return {k: (v.hex() if isinstance(v, (bytes, bytearray)) else v) for k, v in r.items()}

    @app.post("/voucher")
    def voucher(req: VoucherRequest, request: Request):
        agent = Web3.to_checksum_address(req.agent)
        # Each call makes a PRICED oracle invoke and produces a signed odds boost, so it
        # is rationed per agent and per caller address. Unlimited, it was both a way to
        # burn the operator's oracle budget from anywhere and the online search the keyed
        # stand-in bonus is meant to force.
        client = (request.client.host if request.client else "") or "unknown"
        for bucket, key, limit in (
            (_voucher_by_agent, agent, _VOUCHER_MAX_PER_AGENT),
            (_voucher_by_ip, client, _VOUCHER_MAX_PER_IP),
        ):
            if not _allow(bucket, key, limit):
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"voucher requests limited to {limit} per "
                        f"{int(_VOUCHER_WINDOW_S)}s (each one costs a priced oracle call)"
                    ),
                )
        rid = req.round_id or engine.chain.current_round_id()
        # Really call LUMEN — same OracleClient the round loop uses, so the call is priced
        # and booked as opex in live mode. allow_pseudo_fallback=False is the load-bearing
        # part: a single-agent request can never produce a score spread, so this path used
        # to sign the deterministic stand-in EVERY time, in live mode too. No
        # differentiated reputation now means no boost.
        bonuses, _ = engine.oracles.lumen_reputation(
            [agent], allow_pseudo_fallback=_allow_pseudo_voucher_bonus()
        )
        bonus = min(int(bonuses.get(agent, 0)), MAX_REP_BONUS_BPS)
        expiry = engine.chain.block()["timestamp"] + 3600
        sig = engine.chain.sign_voucher(engine.signer_key, agent, rid, bonus, expiry)
        return {
            "round_id": rid,
            "agent": agent,
            "rep_bonus_bps": bonus,
            "expiry": expiry,
            "signature": Web3.to_hex(bytes(sig)),  # always a single clean 0x-prefix
        }

    return app

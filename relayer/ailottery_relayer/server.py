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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from web3 import Web3

# Mirrors AIAgentLottery.MAX_REP_BONUS_BPS (reputation can add ≤ +50% odds). The
# contract rejects a voucher above this, so we cap defensively before signing.
MAX_REP_BONUS_BPS = 5_000


class VoucherRequest(BaseModel):
    agent: str
    round_id: int | None = None


def make_app(engine) -> FastAPI:
    app = FastAPI(title="AI-Agent Oracle Lottery — relayer", version="0.1.0")
    # Let the public showcase poll /economy from its own origin. The feed is read-only
    # and the only mutating route (/voucher) just signs a reputation-capped odds bonus
    # for a given agent — harmless without that agent's key. Defaults to "*"; override
    # with LOTTERY_CORS_ORIGINS (comma-separated) to lock it down.
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
    def voucher(req: VoucherRequest):
        agent = Web3.to_checksum_address(req.agent)
        rid = req.round_id or engine.chain.current_round_id()
        # Really call LUMEN — same OracleClient the round loop uses, so the call is
        # priced + booked as opex in live mode and falls back to a deterministic
        # per-agent score only when the oracle is unreachable (never blocks the agent).
        bonuses, _ = engine.oracles.lumen_reputation([agent])
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

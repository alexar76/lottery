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

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from web3 import Web3

from .chain import _ABI_MISMATCH
from .eligibility import EligibilityError, FederationEligibilityVerifier, participant_id

# Mirrors AIAgentLottery.MAX_REP_BONUS_BPS (reputation can add ≤ +50% odds). The
# contract rejects a voucher above this, so we cap defensively before signing.
MAX_REP_BONUS_BPS = 5_000
# Unpaid work seat: 1.0× weight (LUMEN may raise this up to BPS+MAX on-chain).
WORK_WEIGHT_BPS = 10_000


class VoucherRequest(BaseModel):
    agent: str
    round_id: int | None = None


class HubEntitlement(BaseModel):
    purpose: str
    hub_url: str
    agent_id: str
    participant_id: str
    wallet: str
    issued_at: int
    expires_at: int
    nonce: str
    signature: dict


class WorkSeatRequest(BaseModel):
    agent: str
    round_id: int | None = None
    entitlement: HubEntitlement | None = None


#: /voucher rationing. Each request is one priced oracle invoke plus one signature.
_VOUCHER_WINDOW_S = 3600.0
_VOUCHER_MAX_PER_AGENT = 12
_VOUCHER_MAX_PER_IP = 60
#: Ceiling on priced LUMEN calls this endpoint may buy in a window, whoever asks.
#
# The two buckets above cannot bound spend on their own: an attacker mints agent
# addresses for free, so the per-agent cap only forces a new address every 12 requests,
# and the per-caller cap only forces a new source address. Until 2026-09-11 the caller
# bucket keyed on the reverse proxy (see _client_address) and was therefore ALSO a global
# cap — which is the only reason the budget was bounded, and the reason a single visitor
# could exhaust the endpoint for the whole federation. Making the caller bucket work
# per-caller removes that accident, so the ceiling has to be stated instead of inherited.
_VOUCHER_MAX_GLOBAL = int(os.getenv("LOTTERY_VOUCHER_MAX_PER_HOUR", "120") or "120")
_voucher_by_agent: dict[str, list[float]] = {}
_voucher_by_ip: dict[str, list[float]] = {}
_voucher_global: dict[str, list[float]] = {}
_voucher_lock = threading.Lock()

#: /work-seat is a signature only (no oracle spend). Still rationed: unlimited it
# would let anyone grind eligibility attestations for a round.
_WORK_SEAT_WINDOW_S = 3600.0
_WORK_SEAT_MAX_PER_AGENT = 8
_work_seat_by_agent: dict[str, list[float]] = {}


def _allow(
    bucket: dict[str, list[float]],
    key: str,
    limit: int,
    window_s: float = _VOUCHER_WINDOW_S,
) -> bool:
    """Sliding-window limiter. Locked: uvicorn serves this from a daemon thread while the
    round loop runs in the main one.

    The window is a parameter: /work-seat carries its own (`_WORK_SEAT_WINDOW_S`) and used
    to silently inherit the voucher one, so the 429 it raised quoted a window it was not
    actually applying. They happen to be equal today — tuning either apart would have made
    the limiter lie."""
    now = time.time()
    window = now - window_s
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


def _trusted_proxies() -> frozenset[str]:
    """Addresses whose ``X-Forwarded-For`` this relayer believes.

    Empty by default, and ``*`` is refused: blanket trust would let any caller name its own
    address and take a fresh rate-limit bucket per request — worse than the shared bucket
    this exists to fix.
    """
    out: set[str] = set()
    for part in (os.getenv("LOTTERY_TRUSTED_PROXIES") or "").split(","):
        entry = part.strip()
        if entry and entry != "*":
            out.add(entry)
    return frozenset(out)


def _client_address(request: Request) -> str:
    """The address /voucher's per-caller bucket keys on.

    ``request.client.host`` behind ``lottery/deploy/nginx-relayer-api.conf`` is always the
    proxy, so the 60/hour caller cap was one bucket for the internet: any visitor could
    lock the federation out of vouchers for an hour.

    The header is read only from a declared proxy, and RIGHT TO LEFT, because nginx
    APPENDS with ``$proxy_add_x_forwarded_for`` — the leftmost hop is whatever the caller
    invented. Same shape as the hub's ``_client_address`` and the mesh's ``client_ip``.
    """
    peer = ""
    client = getattr(request, "client", None)
    if client is not None:
        peer = str(getattr(client, "host", "") or "").strip()
    proxies = _trusted_proxies()
    if not peer or peer not in proxies:
        return peer or "unknown"
    raw = request.headers.get("x-forwarded-for") or ""
    for hop in reversed([h.strip() for h in raw.split(",")]):
        if hop and hop not in proxies:
            return hop
    return peer


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
    eligibility = getattr(engine, "eligibility_verifier", None) or FederationEligibilityVerifier(
        os.getenv("LOTTERY_FEDERATION_REGISTRY_URL", "").strip()
        or getattr(engine.cfg, "hub_url", "")
        or "https://modelmarket.dev"
    )

    @app.get("/healthz")
    def healthz(response: Response):
        # "ok" used to mean "the process is up", which stayed true while the lottery the
        # relayer drives had been redeployed out from under it. Report the contract and,
        # in LIVE, the participant-bound ABI that every federated work seat requires.
        live = bool(getattr(engine, "contract_live", True))
        compatible = True
        if getattr(engine.cfg, "mode", "") == "live":
            checker = getattr(engine.chain, "supports_federated_work_seats", None)
            try:
                compatible = bool(checker()) if callable(checker) else False
            except Exception:
                # The probe now only returns False for a real ABI mismatch and re-raises
                # transport errors. A flaky RPC must not flip the healthcheck to 503 and
                # get the container restarted — report the last known answer instead.
                compatible = bool(getattr(engine, "_last_federated_ok", True))
            else:
                engine._last_federated_ok = compatible
        healthy = live and compatible
        if not healthy:
            response.status_code = 503
        return {
            "ok": healthy,
            "mode": engine.cfg.mode,
            "address": engine.chain.address,
            "contract_live": live,
            "federated_work_seat_compatible": compatible,
        }

    @app.get("/economy")
    def economy():
        return engine.state or engine.snapshot()

    @app.get("/rounds/{rid}")
    def round_info(rid: int):
        r = engine.chain.get_round(rid)
        return {k: (v.hex() if isinstance(v, (bytes, bytearray)) else v) for k, v in r.items()}

    @app.post("/voucher")
    def voucher(req: VoucherRequest, request: Request):
        # /work-seat validates this and /voucher raised ValueError out of the handler —
        # a 500 for a typo'd address, on a public endpoint.
        try:
            agent = Web3.to_checksum_address(req.agent)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="agent must be a valid EVM address") from exc
        # Each call makes a PRICED oracle invoke and produces a signed odds boost, so it
        # is rationed per agent and per caller address. Unlimited, it was both a way to
        # burn the operator's oracle budget from anywhere and the online search the keyed
        # stand-in bonus is meant to force.
        client = _client_address(request)
        for bucket, key, limit in (
            (_voucher_by_agent, agent, _VOUCHER_MAX_PER_AGENT),
            (_voucher_by_ip, client, _VOUCHER_MAX_PER_IP),
            # Last, and deliberately: an attacker owns the agent addresses and can rent
            # source addresses, so this is the only bucket that actually bounds what the
            # operator pays LUMEN. Checked after the other two so a single abuser burns
            # its own quotas first.
            (_voucher_global, "*", _VOUCHER_MAX_GLOBAL),
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

    @app.post("/work-seat")
    def work_seat(req: WorkSeatRequest, request: Request):
        """EIP-712 WorkSeat for an agent authenticated by an active federated Hub."""
        try:
            agent = Web3.to_checksum_address(req.agent)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="agent must be a valid EVM address") from exc
        if req.entitlement is None:
            if getattr(engine.cfg, "mode", "") != "demo":
                raise HTTPException(
                    status_code=403,
                    detail="a signed entitlement from an active federated Hub is required",
                )
            # The self-contained local demo deliberately has no Hub. Keep that one
            # environment runnable without making the production endpoint anonymous.
            participant = participant_id("http://lottery.local", agent.lower())
        else:
            try:
                participant = eligibility.verify(req.entitlement.model_dump(), wallet=agent)
            except EligibilityError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
        # One reverse-proxy address can legitimately front the whole federation, so an
        # IP bucket turns "any Hub agent" into a global 30-seat/hour bottleneck. The
        # authenticated stable participant is the correct principal to ration.
        for bucket, key, limit, window_s in (
            (_work_seat_by_agent, participant, _WORK_SEAT_MAX_PER_AGENT, _WORK_SEAT_WINDOW_S),
        ):
            if not _allow(bucket, key, limit, window_s):
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"work-seat requests limited to {limit} per "
                        f"{int(_WORK_SEAT_WINDOW_S)}s"
                    ),
                )
        rid = req.round_id or engine.chain.current_round_id()
        if not rid:
            raise HTTPException(status_code=409, detail="no open round")
        try:
            wallet_seated = bool(engine.chain.work_seated(rid, agent))
            subject_seated = bool(engine.chain.participant_seated(rid, participant))
        except _ABI_MISMATCH as exc:
            # The Sep-10 contract has the wallet-only ABI. Never mint a signature it
            # cannot verify: expose the required redeploy instead of returning a receipt
            # that predictably reverts on-chain.
            raise HTTPException(
                status_code=503,
                detail="configured lottery contract does not support federated participant IDs",
            ) from exc
        except Exception as exc:
            # Anything else is the node, not the deployment. Saying "redeploy your
            # contract" for a timeout sent operators to replace a contract that was fine.
            raise HTTPException(
                status_code=503,
                detail=f"lottery RPC unavailable: {type(exc).__name__}",
            ) from exc
        if subject_seated and not wallet_seated:
            # Two DIFFERENT on-chain nullifiers. Reporting the participant's seat as this
            # wallet's made callers (argus: `if seat.already_seated -> ok`) announce a seat
            # the wallet does not hold — it cannot win and cannot claim. Say so.
            raise HTTPException(
                status_code=409,
                detail=(
                    "this agent identity already holds the work seat for this round from "
                    "a different wallet; one seat per agent per round"
                ),
            )
        if wallet_seated:
            return {
                "round_id": rid,
                "agent": agent,
                "participant_id": participant,
                "weight_bps": WORK_WEIGHT_BPS,
                "already_seated": True,
                "participant_already_seated": subject_seated,
                "lottery": engine.chain.address,
            }
        block_time = int(engine.chain.block()["timestamp"])
        # Do not turn a ten-minute Hub entitlement into a day-long bearer right: the
        # on-chain signature must expire no later than the proof that authorised it.
        # Carry the proof's REMAINING LIFETIME across, rather than comparing a Hub
        # wall-clock stamp with a chain timestamp — uni/demo mode warps the anvil clock
        # forward, so the two are minutes or hours apart and every federated seat was
        # rejected as "expires before chain admission".
        if req.entitlement:
            remaining = int(req.entitlement.expires_at) - int(time.time())
            if remaining <= 0:
                raise HTTPException(
                    status_code=409, detail="Hub entitlement expires before chain admission"
                )
            expiry = block_time + min(600, remaining)
        else:
            expiry = block_time + 600
        sig = engine.chain.sign_work_seat(
            engine.signer_key, agent, participant, rid, WORK_WEIGHT_BPS, expiry)
        return {
            "round_id": rid,
            "agent": agent,
            "participant_id": participant,
            "weight_bps": WORK_WEIGHT_BPS,
            "expiry": expiry,
            "already_seated": False,
            "lottery": engine.chain.address,
            "signature": Web3.to_hex(bytes(sig)),
        }

    return app

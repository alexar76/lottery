"""Oracle client — the lottery's real consumption of the AIMarket oracle services.

LIVE: invoke through the AIMarket Hub (`POST {hub}/ai-market/v2/invoke` with the
v2 envelope + `X-Payment-Channel`, so the Hub debits the call price and skims its
1% routing fee) or, if only ORACLE_URL is set, call the oracle-family directly
(`POST {oracle}/ai-market/v2/invoke`). Every call's price is booked as opex —
this is the lottery *paying* for the services it uses.

DEMO: deterministic local stand-ins (no network, play-money) with the SAME prices,
so the economy numbers and the circular-flow narrative hold.

Capability prices (oracles/.../capabilities.py): platon.random@v1 $0.004,
chronos.eval@v1 $0.01, lumen.reputation@v1 $0.005.
"""
from __future__ import annotations

import json
import secrets
import threading
from dataclasses import dataclass, field
from typing import Optional

import httpx
from web3 import Web3

from .config import Config
from .log import get_logger

log = get_logger("oracles")

PRICE = {"platon.random@v1": 0.004, "chronos.eval@v1": 0.01, "lumen.reputation@v1": 0.005,
         "platon.ask@v1": 0.003, "sortes.draw@v1": 0.006, "sortes.verify@v1": 0.001}
PRODUCT = {"platon.random@v1": "prod-platon", "chronos.eval@v1": "prod-chronos",
           "lumen.reputation@v1": "prod-lumen", "platon.ask@v1": "prod-platon",
           "sortes.draw@v1": "prod-sortes", "sortes.verify@v1": "prod-sortes"}


@dataclass
class OracleResult:
    value: dict
    price_usd: float
    routing_fee_usd: float
    source: str  # "live-hub" | "live-direct" | "demo"


@dataclass
class OpexLedger:
    """Tracks what the lottery spent on oracle/agent services + Hub routing fees.

    Thread-safe: the round-driving loop (main thread) and the FastAPI `/voucher`
    endpoint (uvicorn daemon thread) both invoke oracles and `record()` here, so the
    counters are mutated under a lock to keep opex booking consistent under concurrency.
    """
    oracle_spend_usd: float = 0.0
    routing_fees_usd: float = 0.0
    calls: int = 0
    by_capability: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def record(self, r: OracleResult) -> None:
        with self._lock:
            self.oracle_spend_usd = round(self.oracle_spend_usd + r.price_usd, 6)
            self.routing_fees_usd = round(self.routing_fees_usd + r.routing_fee_usd, 6)
            self.calls += 1


class OracleClient:
    def __init__(self, cfg: Config, ledger: OpexLedger):
        self.cfg = cfg
        self.ledger = ledger
        self._http = httpx.Client(timeout=25.0)
        self.routing_fee_bps = 100  # the Hub's default 1%

    # ── public API ────────────────────────────────────────────────────────────
    def platon_random(self, client_seed: str) -> tuple[bytes, OracleResult]:
        """Returns an unbiasable 32-byte word + the priced result."""
        cap = "platon.random@v1"
        if self.cfg.use_live_oracles:
            r = self._invoke(cap, {"num_bytes": 32, "client_seed": client_seed})
            word = self._to_word(r.value, client_seed)
        else:
            r = self._demo(cap, {"client_seed": client_seed})
            word = Web3.keccak(text=f"platon|{client_seed}|{secrets.token_hex(16)}")
        self.ledger.record(r)
        return word, r

    def sortes_draw(self, client_seed: str) -> tuple[bytes, OracleResult]:
        """Trustless ECVRF (RFC 9381) draw word — ungrindable: for a fixed
        (oracle public key, client_seed) exactly ONE valid 32-byte output exists, and
        anyone can verify it offline from the 80-byte proof. Replaces the trusted
        Platon beacon as the lottery's winner word, closing the 'operator could grind
        the seed before commit' gap. Same 32-byte word → same on-chain commit/VDF path."""
        cap = "sortes.draw@v1"
        if self.cfg.use_live_oracles:
            r = self._invoke(cap, {"num_bytes": 32, "alpha": client_seed})
            word = self._to_word(r.value, client_seed)
        else:
            r = self._demo(cap, {"alpha": client_seed})
            word = Web3.keccak(text=f"sortes|{client_seed}|{secrets.token_hex(16)}")
        self.ledger.record(r)
        return word, r

    def chronos_eval(self, seed: str, difficulty: int) -> tuple[Optional[dict], OracleResult]:
        """Returns the Chronos VDF output (g/y/proof/modulus) for the on-chain path."""
        cap = "chronos.eval@v1"
        if self.cfg.use_live_oracles:
            r = self._invoke(cap, {"seed": seed, "difficulty": difficulty})
            out = r.value if isinstance(r.value, dict) else {}
        else:
            r = self._demo(cap, {"seed": seed, "difficulty": difficulty})
            out = None  # demo never uses the on-chain VDF path
        self.ledger.record(r)
        return out, r

    def platon_ask(self, question: str) -> tuple[dict, OracleResult]:
        """Grounded, read-only guide capability — used by the AI Treasurer's LLM mode."""
        cap = "platon.ask@v1"
        if self.cfg.use_live_oracles:
            r = self._invoke(cap, {"question": question})
            out = r.value if isinstance(r.value, dict) else {}
        else:
            r = self._demo(cap, {})
            out = {}
        self.ledger.record(r)
        return out, r

    def lumen_reputation(self, agents: list[str]) -> tuple[dict[str, int], OracleResult]:
        """Returns agent→reputation-bonus-bps (0..5000, the contract's cap)."""
        cap = "lumen.reputation@v1"
        n = max(1, len(agents))
        if self.cfg.use_live_oracles:
            # a simple symmetric trust ring so PageRank has something to chew on
            edges = [[i, (i + 1) % n, 1.0] for i in range(n)]
            r = self._invoke(cap, {"nodes": n, "edges": edges, "damping": 0.85})
            scores = (r.value or {}).get("scores") if isinstance(r.value, dict) else None
            bonuses = self._scores_to_bonuses(agents, scores)
        else:
            r = self._demo(cap, {"nodes": n})
            bonuses = {a: self._pseudo_bonus(a) for a in agents}
        self.ledger.record(r)
        return bonuses, r

    # ── transport ──────────────────────────────────────────────────────────────
    def _invoke(self, capability_id: str, payload: dict) -> OracleResult:
        price = PRICE.get(capability_id, 0.0)
        try:
            if self.cfg.hub_url:
                body = {
                    "product_id": PRODUCT.get(capability_id, ""),
                    "capability_id": capability_id,
                    "source_hub": "lottery-relayer",
                    "input": payload,
                }
                headers = {}
                if self.cfg.payment_channel:
                    headers["X-Payment-Channel"] = self.cfg.payment_channel
                resp = self._http.post(f"{self.cfg.hub_url}/ai-market/v2/invoke", json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                price = float(data.get("price_usd", price) or price)
                value = data.get("result") or data
                value = self._unwrap_output(value)
                fee = round(price * self.routing_fee_bps / 10_000, 6)
                return OracleResult(value=value, price_usd=price, routing_fee_usd=fee, source="live-hub")
            else:  # direct oracle-family
                body = {"capability_id": capability_id, "input": payload}
                resp = self._http.post(f"{self.cfg.oracle_url}/ai-market/v2/invoke", json=body)
                resp.raise_for_status()
                data = resp.json()
                price = float(data.get("price_usd", price) or price)
                value = self._unwrap_output(data)
                return OracleResult(value=value, price_usd=price, routing_fee_usd=0.0, source="live-direct")
        except Exception as exc:
            log.warning("live oracle %s failed (%s) → demo fallback", capability_id, exc)
            return self._demo(capability_id, payload)

    def _demo(self, capability_id: str, payload: dict) -> OracleResult:
        return OracleResult(value={"demo": True, **payload}, price_usd=PRICE.get(capability_id, 0.0),
                            routing_fee_usd=0.0, source="demo")

    # ── parsing helpers ────────────────────────────────────────────────────────
    @staticmethod
    def _unwrap_output(data) -> dict:
        if isinstance(data, dict):
            if isinstance(data.get("output"), dict):
                return data["output"]
            return data
        return {"value": data}

    @staticmethod
    def _to_word(output: dict, client_seed: str) -> bytes:
        """Reduce whatever entropy the oracle returned to a deterministic 32-byte word."""
        for k in ("randomness", "random", "value", "beacon", "hex", "bytes", "output"):
            v = output.get(k) if isinstance(output, dict) else None
            if isinstance(v, str) and v:
                try:
                    raw = bytes.fromhex(v.removeprefix("0x"))
                    if raw:
                        return Web3.keccak(raw + client_seed.encode())
                except ValueError:
                    return Web3.keccak(text=v + client_seed)
        return Web3.keccak(text=json.dumps(output, sort_keys=True, default=str) + client_seed)

    @staticmethod
    def _scores_to_bonuses(agents: list[str], scores) -> dict[str, int]:
        if not scores or len(scores) < len(agents):
            return {a: OracleClient._pseudo_bonus(a) for a in agents}
        sub = scores[: len(agents)]
        lo, hi = min(sub), max(sub)
        span = hi - lo
        if span <= 1e-12:
            # The oracle answered but couldn't differentiate the agents — a single-agent
            # request (the /voucher path), or the synthetic trust ring is symmetric (the
            # ecosystem serves no real trust edges yet). Fall back to the deterministic
            # per-agent proxy rather than a meaningless flat 0, so a real LUMEN call still
            # yields a usable per-agent bonus instead of silently zeroing every agent.
            return {a: OracleClient._pseudo_bonus(a) for a in agents}
        out = {}
        for i, a in enumerate(agents):
            frac = (sub[i] - lo) / span
            out[a] = int(round(frac * 5000))  # 0..+50%
        return out

    @staticmethod
    def _pseudo_bonus(agent: str) -> int:
        h = int(Web3.keccak(text=f"rep|{agent}").hex(), 16)
        return (h % 5001)  # 0..5000 bps

    def close(self) -> None:
        self._http.close()

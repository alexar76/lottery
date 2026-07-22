"""
Universe Funding Stream — external capital injection into UNI economy.

The ONLY synthetic element in UNI mode. Simulates an external funding
source (grant program, testnet faucet, investor capital) sending USDT
into the ecosystem on a regular schedule.

Funding grows with the universe — more hubs, more products, more funding.
Visualized as cosmic energy streams flowing from outside toward the hub.

In UNI mode, the FakeUSDT contract on Anvil is used to mint tokens.
The source address appears as "external" — outside the known entity graph.
"""

from __future__ import annotations

import hashlib
import os
import random
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from universe import VirtualUniverse

# Factory UNI grants — ecosystem float for Hub-side liquidity (see POST /api/uni/grant).
HUB_LIQUIDITY_OWNER = "universe:hub-treasury"
BUYER_LIQUIDITY_OWNER = "universe:external-buyer"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class UniverseFundingStream:
    """Periodic external capital injection into the UNI economy."""

    def __init__(self, interval_ticks: int | None = None, amount_range: tuple[float, float] | None = None):
        lo = _env_float("ALIEN_UNIVERSE_FUNDING_MIN_USD", 100.0)
        hi = _env_float("ALIEN_UNIVERSE_FUNDING_MAX_USD", 200.0)
        self.total_funding = 0.0
        self.rounds: list[dict] = []
        self.interval_ticks = interval_ticks if interval_ticks is not None else _env_int(
            "ALIEN_UNIVERSE_FUNDING_INTERVAL_TICKS", 200
        )
        self.amount_range = amount_range if amount_range is not None else (lo, hi)
        self.last_funding_tick = 0
        self._funding_multiplier = 1.0
        self._hub_liquidity_seeded = False

    def tick(self, current_tick: int, vu: VirtualUniverse) -> dict | None:
        if current_tick - self.last_funding_tick < self.interval_ticks:
            return None

        self.last_funding_tick = current_tick

        base = random.uniform(*self.amount_range)
        amount = round(base * self._funding_multiplier, 2)
        self.total_funding += amount

        tx_hash = self._mint_or_record(amount, vu)
        recipient = self._funding_onchain_recipient(vu) or vu.evm_escrow_address or "0xEscrow"

        event = {
            "type": "funding_stream",
            "id": f"funding_{current_tick}",
            "amount": amount,
            "token": "USDT",
            "source": "external",
            "tx_hash": tx_hash,
            "ts": datetime.now(timezone.utc).isoformat(),
            "total_funding": self.total_funding,
            "round": len(self.rounds) + 1,
        }

        self.rounds.append(event)
        if len(self.rounds) > 100:
            self.rounds = self.rounds[-100:]

        vu.transactions.append({
            "id": tx_hash[:16],
            "hash": tx_hash,
            "from": "0xExternal",
            "to": recipient,
            "action": "funding",
            "target": "ecosystem",
            "amount": amount,
            "token": "USDT",
            "block": vu.chain_analytics.get("blocks", 0),
            "gas_used": 0,
            "status": "confirmed",
            "ts": event["ts"],
            "onchain": True,
            "funding": True,
        })

        if len(vu.transactions) > 200:
            vu.transactions = vu.transactions[-200:]

        vu.chain_analytics["tx_count"] = len(vu.transactions)

        print(f"[Funding] ${amount:.2f} USDT injected (total: ${self.total_funding:.2f})")

        return event

    def ensure_hub_liquidity(self, vu: VirtualUniverse) -> dict:
        """One-time UNI grants so Hub and external buyer have float before EXPANSION rounds."""
        if self._hub_liquidity_seeded:
            return {"ok": True, "skipped": True}
        hub_usd = _env_float("ALIEN_UNIVERSE_HUB_LIQUIDITY_GRANT_USD", 500.0)
        buyer_usd = _env_float("ALIEN_UNIVERSE_BUYER_LIQUIDITY_GRANT_USD", 300.0)
        grants: list[str] = []
        if hub_usd > 0:
            self._credit_factory_uni_for_owner(hub_usd, f"bootstrap_{HUB_LIQUIDITY_OWNER}", HUB_LIQUIDITY_OWNER)
            grants.append(f"hub:{hub_usd}")
        if buyer_usd > 0:
            self._credit_factory_uni_for_owner(buyer_usd, f"bootstrap_{BUYER_LIQUIDITY_OWNER}", BUYER_LIQUIDITY_OWNER)
            grants.append(f"buyer:{buyer_usd}")
        self._hub_liquidity_seeded = True
        print(f"[Funding] Hub liquidity bootstrap — {', '.join(grants) or 'skipped (no AIFACTORY_UNI_GRANT_SECRET)'}")
        return {"ok": True, "grants": grants}

    def inject_initial_external_funding(self, current_tick: int, vu: VirtualUniverse) -> dict | None:
        """First external injection when EXPANSION starts."""
        initial = _env_float("ALIEN_UNIVERSE_INITIAL_FUNDING_USD", 0.0)
        if initial <= 0 or self.rounds:
            return None
        self.last_funding_tick = current_tick - self.interval_ticks
        saved = self.amount_range
        self.amount_range = (initial, initial)
        try:
            return self.tick(current_tick, vu)
        finally:
            self.amount_range = saved

    def update_growth_multiplier(self, vu: VirtualUniverse, fed_hub_count: int = 0) -> None:
        product_factor = min(len(vu.products) / 20.0, 2.0)
        hub_factor = min(fed_hub_count / 3.0, 2.0)
        self.grow_funding(1.0 + 0.15 * product_factor + 0.25 * hub_factor)

    def _funding_onchain_recipient(self, vu: VirtualUniverse) -> str:
        target = (os.environ.get("ALIEN_UNIVERSE_FUNDING_TARGET") or "escrow").strip().lower()
        if target in ("hub", "payment", "recipient") and vu.payment_recipient:
            return vu.payment_recipient
        return vu.evm_escrow_address or ""

    def _mint_or_record(self, amount: float, vu: VirtualUniverse) -> str:
        if vu._w3 and vu._w3.is_connected() and vu.evm_usdt_address:
            try:
                return self._mint_onchain(amount, vu)
            except Exception as exc:
                print(f"[Funding] On-chain mint failed: {exc}")

        synthetic = f"0x{hashlib.sha256(f'funding_{amount}_{self.total_funding}_{random.random()}'.encode()).hexdigest()[:64]}"
        self._credit_factory_uni_for_owner(amount, synthetic, "universe:funding")
        return synthetic

    def _credit_factory_uni(self, amount_usd: float, ref: str) -> None:
        self._credit_factory_uni_for_owner(amount_usd, ref, "universe:funding")

    def _credit_factory_uni_for_owner(self, amount_usd: float, ref: str, owner_id: str) -> None:
        """Mirror external funding into Factory UNI ledger (Hub liquidity bus)."""
        import httpx

        app_url = os.environ.get("AICOM_API_URL", "http://127.0.0.1:9081").rstrip("/")
        secret = os.environ.get("AIFACTORY_UNI_GRANT_SECRET", "").strip()
        if not secret:
            return
        try:
            from core.uni.pricing import usd_to_uni
        except ImportError:
            usd_to_uni = lambda x, **kw: float(x) * 100.0  # noqa: E731 — ~100 UNI per $1 peg
        payload = {
            "owner_id": owner_id,
            "amount_uni": usd_to_uni(amount_usd, apply_spread=False),
            "ref": ref[:128],
            "reason": "universe_funding_stream",
        }
        try:
            r = httpx.post(
                f"{app_url}/api/uni/grant",
                json=payload,
                headers={"X-Uni-Grant-Secret": secret},
                timeout=8.0,
            )
            if r.status_code != 200:
                print(f"[Funding] UNI grant {owner_id} HTTP {r.status_code}: {r.text[:120]}")
        except Exception as exc:
            print(f"[Funding] UNI grant {owner_id} skipped: {exc}")

    def _mint_onchain(self, amount: float, vu: VirtualUniverse) -> str:
        deployer = vu._w3.eth.accounts[0]
        token_addr = vu._w3.to_checksum_address(vu.evm_usdt_address)
        recipient = vu._w3.to_checksum_address(
            self._funding_onchain_recipient(vu) or vu._w3.eth.accounts[1]
        )
        usdt = vu._w3.eth.contract(
            address=token_addr,
            abi=[
                {"constant": False, "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
            ],
        )
        amount_wei = vu._w3.to_wei(amount, "ether")
        tx_hash = usdt.functions.transfer(recipient, amount_wei).transact({"from": deployer})
        receipt = vu._w3.eth.wait_for_transaction_receipt(tx_hash)
        return tx_hash.hex()

    def get_stats(self) -> dict:
        return {
            "total_funding": self.total_funding,
            "rounds": len(self.rounds),
            "last_amount": self.rounds[-1]["amount"] if self.rounds else 0,
            "multiplier": self._funding_multiplier,
            "interval_ticks": self.interval_ticks,
        }

    def grow_funding(self, multiplier: float) -> None:
        self._funding_multiplier = max(1.0, multiplier)

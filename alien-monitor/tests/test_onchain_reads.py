"""On-chain read encode/decode + native-unit overlay — fully offline (fake caller)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import onchain_reads as oc  # noqa: E402


def _word(n: int) -> str:
    return oc.uint_arg(n)


def _round_struct(*, ticket_revenue: int, funding: int, prize_pool: int) -> str:
    """16 inline 32-byte words; only ticketRevenue(9)/funding(10)/prizePool(12) non-zero."""
    words = [0] * 16
    words[oc._R_TICKET_REVENUE] = ticket_revenue
    words[oc._R_FUNDING] = funding
    words[oc._R_PRIZE_POOL] = prize_pool
    return "0x" + "".join(_word(w) for w in words)


class _FakeCaller:
    """Dispatches eth_call by selector → canned hex result."""

    def __init__(self, by_selector: dict[str, str]):
        self.by_selector = by_selector
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, to: str, data: str) -> str:
        self.calls.append((to, data))
        return self.by_selector[data[2:10]]


# ── pure encode/decode ───────────────────────────────────────────────────────
def test_encode_helpers():
    assert oc.uint_arg(8453) == f"{8453:064x}"
    assert oc.addr_arg("0x" + "ab" * 20).endswith("ab" * 20)
    assert oc.call_data("9cbe5efd") == "0x9cbe5efd"
    assert oc.call_data("8f1327c0", oc.uint_arg(2)).startswith("0x8f1327c0")


def test_decode_uint_and_addr():
    assert oc.decode_uint("0x" + f"{42:064x}") == 42
    assert oc.decode_uint("0x") == 0
    two_words = "0x" + f"{1:064x}" + f"{99:064x}"
    assert oc.decode_uint(two_words, 1) == 99
    a = "0x" + "00" * 12 + "ab" * 20
    assert oc.decode_addr(a) == "0x" + "ab" * 20


# ── reads (fake caller) ──────────────────────────────────────────────────────
def test_read_lottery_native_eth_pot_and_tickets():
    eth = 10 ** 18
    caller = _FakeCaller({
        oc.SEL_CURRENT_ROUND: "0x" + _word(2),
        oc.SEL_TOKEN: "0x" + _word(0),  # address(0) → native ETH
        oc.SEL_GET_ROUND: _round_struct(ticket_revenue=3 * eth, funding=1 * eth, prize_pool=0),
        oc.SEL_TICKET_PRICE: "0x" + _word(eth),
    })
    out = asyncio.run(oc.read_lottery(caller, "0xLottery"))
    assert out["round"] == 2
    assert out["prize_token"] == "ETH"
    assert out["prize_pool"] == 4.0          # not drawn → ticketRevenue + funding
    assert out["tickets"] == 3               # 3 ETH revenue / 1 ETH price
    assert out["drawn"] is False


def test_read_lottery_uses_prizepool_once_drawn():
    eth = 10 ** 18
    caller = _FakeCaller({
        oc.SEL_CURRENT_ROUND: "0x" + _word(5),
        oc.SEL_TOKEN: "0x" + _word(0),
        oc.SEL_GET_ROUND: _round_struct(ticket_revenue=2 * eth, funding=0, prize_pool=7 * eth),
        oc.SEL_TICKET_PRICE: "0x" + _word(eth),
    })
    out = asyncio.run(oc.read_lottery(caller, "0xLottery"))
    assert out["drawn"] is True and out["prize_pool"] == 7.0  # drawn → use prizePool


def test_read_erc20_balance_usdc_6dp():
    caller = _FakeCaller({oc.SEL_BALANCE_OF: "0x" + _word(2_106_836)})  # 2.106836 USDC (6 dp)
    holder = "0x" + "11" * 20
    out = asyncio.run(oc.read_erc20_balance(caller, "0x" + "22" * 20, holder, decimals=6))
    assert out == 2.106836


def test_read_nft_minted():
    caller = _FakeCaller({oc.SEL_NEXT_TOKEN_ID: "0x" + _word(12)})
    assert asyncio.run(oc.read_nft_minted(caller, "0xNFT")) == 12


def test_read_acex_tvl_sums_holders_skips_none():
    caller = _FakeCaller({oc.SEL_BALANCE_OF: "0x" + _word(1_500_000)})  # 1.5 USDC per holder
    vault = "0x" + "11" * 20
    pool = "0x" + "22" * 20
    out = asyncio.run(oc.read_acex_tvl(caller, "0x" + "33" * 20, [vault, None, pool]))
    assert out == 3.0  # 2 real holders × 1.5, None skipped


def test_read_open_channels_net_count():
    O, S, R, E = oc.EV_CHANNEL_OPENED, oc.EV_CHANNEL_SETTLED, oc.EV_CHANNEL_REFUNDED, oc.EV_CHANNEL_EXPIRED
    logs = [{"topics": [O]}, {"topics": [O]}, {"topics": [O]}, {"topics": [S]}, {"topics": [R]}]

    async def logs_call(filt):
        # OR-topic filter is sent; we just return the canned lifecycle logs
        assert filt["topics"][0] == [O, S, R, E] and filt["address"] == "0xEsc"
        return logs

    out = asyncio.run(oc.read_open_channels(logs_call, "0xEsc", "0x2d4a8a1"))
    assert out == 1  # 3 opened − (1 settled + 1 refunded) = 1


def test_read_open_channels_never_negative():
    async def logs_call(filt):
        return [{"topics": [oc.EV_CHANNEL_SETTLED]}]  # a close with no open in range
    assert asyncio.run(oc.read_open_channels(logs_call, "0xEsc", "0x0")) == 0


# ── overlay onto nodes ───────────────────────────────────────────────────────
def test_apply_onchain_native_overrides_lottery_and_fills_escrow_nft():
    from chain_metrics import apply_onchain_native_to_nodes

    nodes = [
        {"id": "lottery", "metrics": {"prize_pool_usd": 0, "players": 0, "round": 2723,
                                      "payouts_24h": 0}, "status": "idle"},
        {"id": "evm_escrow", "metrics": {"channels": 0, "tvl": 0}, "status": "unknown"},
        {"id": "acex", "metrics": {"volume_24h": 0, "listings": 0}, "status": "unknown"},
        {"id": "nft_contract", "metrics": {"minted": 0, "holders": 0}, "status": "unknown"},
    ]
    native = {
        "lottery": {"round": 2, "prize_pool": 4.0, "prize_token": "ETH", "tickets": 3, "drawn": False},
        "escrow_tvl": 2.106836,
        "escrow_channels": 3,
        "acex_tvl": 12.5,
        "nft_minted": 5,
    }
    apply_onchain_native_to_nodes(nodes, native)
    lot = next(n for n in nodes if n["id"] == "lottery")["metrics"]
    assert "prize_pool_usd" not in lot and "players" not in lot  # USD estimates dropped
    assert lot["prize_pool_eth"] == 4.0 and lot["round"] == 2 and lot["tickets"] == 3
    assert lot["payouts_24h"] == 0  # off-chain 24h flow retained
    esc = next(n for n in nodes if n["id"] == "evm_escrow")["metrics"]
    assert esc["tvl"] == 2.106836 and esc["channels"] == 3
    assert next(n for n in nodes if n["id"] == "acex")["metrics"]["tvl"] == 12.5
    assert next(n for n in nodes if n["id"] == "nft_contract")["metrics"]["minted"] == 5

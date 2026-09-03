"""Real on-chain reads for LIVE mode — native ETH/USDC, no price oracle, no fabrication.

Reads the deployed Base contracts directly via ``eth_call`` (through the same async failover
RPC list as chain_metrics) and decodes the results by hand — the encode/decode core is pure
and unit-tested offline; only the thin async wrappers touch the network.

Selectors come from the Foundry artifacts' methodIdentifiers (stable, no keccak dependency).
Values are returned in the contract's native unit (wei→ETH, USDC base units→USDC), because
the ecosystem has no USD price oracle (same stance as web/backend payment verification).
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

# ── function selectors (Foundry methodIdentifiers) ──────────────────────────
SEL_CURRENT_ROUND = "9cbe5efd"  # currentRoundId()
SEL_GET_ROUND = "8f1327c0"      # getRound(uint256)
SEL_TICKET_PRICE = "1209b1f6"   # ticketPrice()
SEL_TOKEN = "fc0c546a"          # token()
SEL_NEXT_TOKEN_ID = "75794a3c"  # nextTokenId()
SEL_BALANCE_OF = "70a08231"     # balanceOf(address)  (ERC-20 standard)
SEL_DECIMALS = "313ce567"       # decimals()          (ERC-20 standard)

ZERO_ADDR = "0x" + "0" * 40

# Round struct word offsets (all fields static → 16 inline 32-byte words).
_R_STATUS, _R_TICKET_REVENUE, _R_FUNDING, _R_PRIZE_POOL = 0, 9, 10, 12


# ── pure encode / decode (unit-tested, no network) ──────────────────────────
def uint_arg(n: int) -> str:
    """32-byte (64-hex) big-endian encoding of a uint."""
    return f"{int(n):064x}"


def addr_arg(address: str) -> str:
    """Left-pad a 20-byte address to a 32-byte word."""
    return f"{int(address, 16):064x}"


def call_data(selector_hex: str, *args_hex: str) -> str:
    """0x + 4-byte selector + concatenated 32-byte arg words."""
    return "0x" + selector_hex + "".join(args_hex)


def _hexbody(result: str) -> str:
    return result[2:] if isinstance(result, str) and result.startswith("0x") else (result or "")


def decode_uint(result: str, word: int = 0) -> int:
    """Decode the uint at the given 32-byte word; 0 for empty/'0x'."""
    body = _hexbody(result)
    chunk = body[word * 64:(word + 1) * 64]
    return int(chunk, 16) if chunk else 0


def decode_addr(result: str, word: int = 0) -> str:
    body = _hexbody(result)
    chunk = body[word * 64:(word + 1) * 64]
    return "0x" + chunk[-40:] if chunk else ZERO_ADDR


# ── async callers ───────────────────────────────────────────────────────────
# Caller signature: async (to_address, data_hex) -> result_hex. Injected so the reads are
# testable with a fake; the real one wraps chain_metrics._json_rpc_failover (eth_call).
Caller = Callable[[str, str], Awaitable[str]]


def make_caller(client: Any, rpc_urls: list[str]) -> Caller:
    from chain_metrics import _json_rpc_failover

    async def _call(to: str, data: str) -> str:
        _url, result = await _json_rpc_failover(client, rpc_urls, "eth_call", [{"to": to, "data": data}, "latest"])
        return result

    return _call


def _native_unit(token_addr: str, usdc_addr: str | None) -> tuple[str, int]:
    """Symbol + decimals for the lottery's settlement token (no price oracle)."""
    if token_addr.lower() == ZERO_ADDR:
        return "ETH", 18
    if usdc_addr and token_addr.lower() == usdc_addr.lower():
        return "USDC", 6
    return "TOKEN", 18


async def read_lottery(call: Caller, address: str, *, usdc_addr: str | None = None) -> dict:
    """Live lottery state in native units: round, prize pool, tickets sold, settlement token.

    Prize pool = the round's ``prizePool`` once drawn, else the accumulating
    ``ticketRevenue + funding`` pot. Tickets ≈ ticketRevenue / ticketPrice.
    """
    round_id = decode_uint(await call(address, call_data(SEL_CURRENT_ROUND)))
    token_addr = decode_addr(await call(address, call_data(SEL_TOKEN)))
    symbol, decimals = _native_unit(token_addr, usdc_addr)
    scale = 10 ** decimals

    rnd = await call(address, call_data(SEL_GET_ROUND, uint_arg(round_id)))
    ticket_revenue = decode_uint(rnd, _R_TICKET_REVENUE)
    funding = decode_uint(rnd, _R_FUNDING)
    prize_pool_raw = decode_uint(rnd, _R_PRIZE_POOL)
    pot_raw = prize_pool_raw if prize_pool_raw > 0 else (ticket_revenue + funding)

    ticket_price = decode_uint(await call(address, call_data(SEL_TICKET_PRICE)))
    tickets = (ticket_revenue // ticket_price) if ticket_price else 0

    return {
        "round": round_id,
        "prize_pool": round(pot_raw / scale, 6),
        "prize_token": symbol,
        "tickets": int(tickets),
        "drawn": prize_pool_raw > 0,
    }


async def read_erc20_balance(call: Caller, token: str, holder: str, *, decimals: int = 6) -> float:
    """ERC-20 balance of ``holder`` in whole tokens (default 6 dp = USDC)."""
    raw = decode_uint(await call(token, call_data(SEL_BALANCE_OF, addr_arg(holder))))
    return round(raw / (10 ** decimals), 6)


async def read_nft_minted(call: Caller, address: str) -> int:
    """Minted entitlement count ≈ nextTokenId()."""
    return decode_uint(await call(address, call_data(SEL_NEXT_TOKEN_ID)))


async def read_acex_tvl(call: Caller, usdc_addr: str, holders: list[str | None]) -> float:
    """Native USDC TVL across the ACEX value contracts (vault / AMM / lending pool)."""
    total = 0.0
    for h in holders:
        if h:
            total += await read_erc20_balance(call, usdc_addr, h, decimals=6)
    return round(total, 6)


# ── escrow open-channel count via events ────────────────────────────────────
# topic0 = keccak of the exact event signatures in AIMarketEscrow.sol.
EV_CHANNEL_OPENED = "0x506f81b7a67b45bfbc6167fd087b3dd9b65b4531a2380ec406aab5b57ac62152"
EV_CHANNEL_SETTLED = "0xf9fd50bb93373f038588c8fe1cc4e882e60a9fd611751250ad26733b4d008151"
EV_CHANNEL_REFUNDED = "0x173cb959dc036336053ea80c0b241b6401a02e35970c2d0cc0b6e052d6a08cb0"
EV_CHANNEL_EXPIRED = "0x482746ef7d1095564f09015c1c1f04e69e52e442c38f45446a0414555cecdb67"

# Logs caller: async (getLogs filter dict) -> list of log dicts. Injected for testability.
LogsCall = Callable[[dict], Awaitable[list]]


def make_logs_call(client: Any, rpc_urls: list[str]) -> LogsCall:
    from chain_metrics import _json_rpc_failover

    async def _logs(filt: dict) -> list:
        _url, result = await _json_rpc_failover(client, rpc_urls, "eth_getLogs", [filt])
        return result or []

    return _logs


async def read_open_channels(
    logs_call: LogsCall, escrow_addr: str, from_block_hex: str, to_block: str = "latest"
) -> int:
    """Net open channels = opened − (settled + refunded + expired), from one OR-topic getLogs.
    Each channel id closes at most once, so the difference is the live open count.
    Raises on RPC failure (caller treats as 'unknown' — never fabricates a count)."""
    logs = await logs_call({
        "address": escrow_addr,
        "fromBlock": from_block_hex,
        "toBlock": to_block,
        "topics": [[EV_CHANNEL_OPENED, EV_CHANNEL_SETTLED, EV_CHANNEL_REFUNDED, EV_CHANNEL_EXPIRED]],
    })
    counts = {EV_CHANNEL_OPENED: 0, EV_CHANNEL_SETTLED: 0, EV_CHANNEL_REFUNDED: 0, EV_CHANNEL_EXPIRED: 0}
    for lg in logs:
        topics = lg.get("topics") or []
        t0 = topics[0].lower() if topics else ""
        if t0 in counts:
            counts[t0] += 1
    closed = counts[EV_CHANNEL_SETTLED] + counts[EV_CHANNEL_REFUNDED] + counts[EV_CHANNEL_EXPIRED]
    return max(0, counts[EV_CHANNEL_OPENED] - closed)

"""
On-chain metrics for Alien Monitor LIVE (real) mode.

Reads RPC URLs and contract addresses from the same env vars as AI-Factory /
aimarket-hub (.env in repo root). Uses JSON-RPC via httpx — no hard dependency
on web3.py for LIVE polling.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

import httpx

# Unified multi-chain registry + RPC failover. Vendored verbatim from
# aimarket-hub/aimarket_hub/chain_net.py (kept in sync by tests/test_chain_net_parity.py),
# because alien-monitor is a standalone service with no hard dep on aimarket_hub.
# Per-chain RPC env keys (BASE_RPC_URL, ETHEREUM_RPC_URL, …) are resolved inside chain_net.
import chain_net


def _strip_addr(val: str) -> str:
    return (val or "").strip().strip('"').strip("'")


def _dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        k = (u or "").rstrip("/")
        if k and k not in seen:
            seen.add(k)
            out.append(u)
    return out


def primary_evm_chain() -> str:
    for key in (
        "ALIEN_EVM_CHAIN",
        "AIMARKET_PAYMENT_CHAIN",
        "AIFACTORY_AI_MARKET_CHAIN",
        "AIMARKET_NFT_CHAIN",
    ):
        raw = (os.environ.get(key) or "").strip().lower()
        if raw and raw != "solana":
            return raw
    # Default to the ecosystem-wide active EVM network (chain_net; default Base).
    active = chain_net.active_network()
    return active.id if active.is_evm else "base"


def _monitor_evm_overrides(chain: str) -> list[str]:
    """alien-monitor-specific RPC overrides, used as the preferred default ahead of chain_net."""
    urls: list[str] = []
    for key in ("ALIEN_EVM_RPC", "EVM_RPC", "EVM_RPC_URL"):
        v = (os.environ.get(key) or "").strip()
        if v:
            urls.append(v)
    nft_chain = (os.environ.get("AIMARKET_NFT_CHAIN") or "").strip().lower()
    nft_rpc = (os.environ.get("AIMARKET_NFT_CHAIN_RPC") or "").strip()
    if nft_rpc and chain == nft_chain:
        urls.append(nft_rpc)
    return urls


def evm_rpc_urls_for_chain(chain: str) -> list[str]:
    """Priority-ordered EVM RPC URLs: monitor overrides → chain_net (operator env + presets)."""
    chain = chain.strip().lower()
    urls = _monitor_evm_overrides(chain)
    try:
        urls += list(chain_net.network(chain).rpc_urls)
    except chain_net.ChainNetError:
        pass
    return _dedupe_urls(urls)


def evm_rpc_for_chain(chain: str) -> str | None:
    """Back-compat single-URL accessor — the highest-priority endpoint, or None."""
    urls = evm_rpc_urls_for_chain(chain)
    return urls[0] if urls else None


def solana_rpc_urls() -> list[str]:
    """Priority-ordered Solana RPC URLs: monitor override → chain_net (operator env + presets)."""
    urls: list[str] = []
    v = (os.environ.get("ALIEN_SOLANA_RPC") or "").strip()
    if v:
        urls.append(v)
    try:
        urls += list(chain_net.network("solana").rpc_urls)
    except chain_net.ChainNetError:
        pass
    return _dedupe_urls(urls)


def solana_rpc_url() -> str:
    """Back-compat single-URL accessor — the highest-priority Solana endpoint."""
    urls = solana_rpc_urls()
    return urls[0] if urls else "https://api.mainnet-beta.solana.com"


def configured_contracts() -> dict[str, str | None]:
    # Demo defaults for the active EVM chain (chain_net; Base ships our live demo contracts),
    # so the monitor shows the real deployment out of the box. Env always wins.
    try:
        demo = chain_net.network(primary_evm_chain()).addresses
    except chain_net.ChainNetError:
        demo = {}
    escrow = _strip_addr(
        os.environ.get("AIMARKET_ESCROW_EVM_ADDRESS")
        or os.environ.get("AIFACTORY_AI_MARKET_CONTRACT")
        or ""
    ) or demo.get("AIMarketEscrow") or ""
    nft = _strip_addr(
        os.environ.get("AIMARKET_NFT_CONTRACT")
        or os.environ.get("AIMARKET_NFT_CONTRACT_ADDRESS")
        or ""
    ) or demo.get("AIMarketCapabilityNFT") or ""
    # Solana escrow program exists in source but is not part of the live demo → no default.
    sol_program = _strip_addr(os.environ.get("AIMARKET_ESCROW_SOLANA_PROGRAM_ID") or "")
    recipient = _strip_addr(os.environ.get("AIMARKET_PAYMENT_RECIPIENT") or "")
    return {
        "escrow_evm": escrow or None,
        "nft_evm": nft or None,
        "escrow_solana": sol_program or None,
        "payment_recipient": recipient or None,
    }


def _hex_to_int(val: Any) -> int:
    if val is None:
        return 0
    if isinstance(val, int):
        return val
    s = str(val).strip()
    if s.startswith("0x"):
        return int(s, 16)
    return int(s)


async def _json_rpc(
    client: httpx.AsyncClient,
    url: str,
    method: str,
    params: list[Any],
) -> Any:
    resp = await client.post(
        url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers={"User-Agent": chain_net.user_agent(), "Accept": "application/json"},
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    return payload.get("result")


async def _json_rpc_failover(
    client: httpx.AsyncClient,
    urls: list[str],
    method: str,
    params: list[Any],
) -> tuple[str, Any]:
    """Try each url in priority order (preferred default first) until one answers; return
    (winning_url, result). Raises the last error if all fail. The winning url is then pinned
    for the remaining calls in a snapshot — so we don't split a read across nodes."""
    last_err: Exception | None = None
    for url in urls:
        try:
            return url, await _json_rpc(client, url, method, params)
        except Exception as exc:  # transport/RPC error → fail over to the next endpoint
            last_err = exc
            continue
    raise last_err or RuntimeError("no RPC endpoints configured")


async def fetch_evm_metrics(
    client: httpx.AsyncClient,
    *,
    chain: str,
    rpc_urls: list[str],
    contracts: dict[str, str | None],
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "chain": chain,
        "rpc": rpc_urls[0] if rpc_urls else "",
        "connected": False,
        "errors": [],
        "contracts": {},
    }
    if not rpc_urls:
        out["errors"].append(f"evm rpc ({chain}): no endpoints configured")
        return out
    try:
        # Find the highest-priority endpoint that answers, then pin it for the rest.
        rpc_url, chain_id_hex = await _json_rpc_failover(client, rpc_urls, "eth_chainId", [])
        block_hex = await _json_rpc(client, rpc_url, "eth_blockNumber", [])
        gas_hex = await _json_rpc(client, rpc_url, "eth_gasPrice", [])
        out["rpc"] = rpc_url
        out.update(
            {
                "connected": True,
                "block": _hex_to_int(block_hex),
                "gas_gwei": round(_hex_to_int(gas_hex) / 1e9, 4),
                "chain_id": _hex_to_int(chain_id_hex),
            }
        )
    except Exception as exc:
        out["errors"].append(f"evm rpc ({chain}): {exc}")
        return out

    for label, addr in (
        ("escrow", contracts.get("escrow_evm")),
        ("nft", contracts.get("nft_evm")),
        ("recipient", contracts.get("payment_recipient")),
    ):
        if not addr or not addr.startswith("0x") or len(addr) < 42:
            continue
        info: dict[str, Any] = {"address": addr, "deployed": False, "balance_eth": 0.0}
        try:
            code = await _json_rpc(client, rpc_url, "eth_getCode", [addr, "latest"])
            info["deployed"] = bool(code and code not in ("0x", "0x0"))
            bal_hex = await _json_rpc(client, rpc_url, "eth_getBalance", [addr, "latest"])
            info["balance_eth"] = round(_hex_to_int(bal_hex) / 1e18, 6)
        except Exception as exc:
            info["error"] = str(exc)
        out["contracts"][label] = info

    return out


async def fetch_solana_metrics(
    client: httpx.AsyncClient,
    *,
    rpc_urls: list[str],
    program_id: str | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "rpc": rpc_urls[0] if rpc_urls else "",
        "connected": False,
        "errors": [],
        "program": None,
    }
    if not rpc_urls:
        out["errors"].append("solana rpc: no endpoints configured")
        return out
    try:
        rpc_url, slot = await _json_rpc_failover(client, rpc_urls, "getSlot", [])
        height = await _json_rpc(client, rpc_url, "getBlockHeight", [])
        out["rpc"] = rpc_url
        out.update(
            {
                "connected": True,
                "slot": int(slot),
                "block_height": int(height),
            }
        )
    except Exception as exc:
        out["errors"].append(f"solana rpc: {exc}")
        return out

    if program_id:
        prog: dict[str, Any] = {"address": program_id, "deployed": False}
        try:
            result = await _json_rpc(
                client,
                rpc_url,
                "getAccountInfo",
                [program_id, {"encoding": "base64"}],
            )
            value = (result or {}).get("value")
            prog["deployed"] = bool(value and value.get("executable"))
            prog["lamports"] = (value or {}).get("lamports", 0)
        except Exception as exc:
            prog["error"] = str(exc)
        out["program"] = prog

    return out


def active_network_info() -> dict[str, Any]:
    """The selected EVM network as surfaced to the UI (id, name, chainId, kind, testnet)."""
    chain = primary_evm_chain()
    try:
        net = chain_net.network(chain)
        return {"id": net.id, "name": net.display_name, "chain_id": net.chain_id,
                "kind": net.kind, "testnet": net.testnet}
    except chain_net.ChainNetError:
        return {"id": chain, "name": chain.title(), "chain_id": None, "kind": "evm", "testnet": False}


async def fetch_onchain_snapshot(timeout: float = 8.0) -> dict[str, Any]:
    """Poll the configured EVM + Solana RPCs (with failover) and contract deployment status.

    ``timeout`` is a HARD TOTAL budget: per-call timeouts bound each request, and an outer
    wait_for bounds the whole snapshot, so even with every endpoint of every chain offline the
    call returns a degraded snapshot promptly instead of scaling with endpoint count.
    """
    try:
        return await asyncio.wait_for(_fetch_onchain_snapshot(timeout), timeout=timeout)
    except (asyncio.TimeoutError, TimeoutError):
        return {
            "primary_chain": primary_evm_chain(),
            "network": active_network_info(),
            "contracts": configured_contracts(),
            "evm": None,
            "solana": None,
            "errors": [f"on-chain snapshot exceeded total timeout ({timeout}s) — RPCs unreachable"],
        }


async def _fetch_onchain_snapshot(timeout: float = 8.0) -> dict[str, Any]:
    chain = primary_evm_chain()
    evm_urls = evm_rpc_urls_for_chain(chain)
    contracts = configured_contracts()
    sol_urls = solana_rpc_urls()

    snapshot: dict[str, Any] = {
        "primary_chain": chain,
        "network": active_network_info(),
        "contracts": contracts,
        "evm": None,
        "solana": None,
        "errors": [],
    }

    # Short per-call timeout so failing over across several dead endpoints stays bounded
    # (never hangs the snapshot when offline).
    per_call = min(timeout, 5.0)
    async with httpx.AsyncClient(timeout=per_call) as client:
        if evm_urls:
            snapshot["evm"] = await fetch_evm_metrics(
                client, chain=chain, rpc_urls=evm_urls, contracts=contracts
            )
            snapshot["errors"].extend(snapshot["evm"].get("errors") or [])
        else:
            snapshot["errors"].append(
                f"No EVM RPC configured for chain {chain!r} "
                f"(set AIMARKET_RPC_{chain.upper()} or {chain.upper()}_RPC_URL or ALIEN_EVM_RPC)"
            )

        snapshot["solana"] = await fetch_solana_metrics(
            client,
            rpc_urls=sol_urls,
            program_id=contracts.get("escrow_solana"),
        )
        snapshot["errors"].extend(snapshot["solana"].get("errors") or [])

    return snapshot


# Human chain names by chainId — so the EVM node shows the chain it's ACTUALLY on
# (e.g. Base 8453), not a hardcoded "Ethereum".
_CHAIN_NAMES: dict[int, str] = {
    1: "Ethereum",
    8453: "Base",
    84532: "Base Sepolia",
    42161: "Arbitrum",
    10: "Optimism",
    137: "Polygon",
    11155111: "Sepolia",
}


def apply_chain_metrics_to_nodes(nodes: list[dict], chain: dict[str, Any]) -> None:
    """Merge on-chain snapshot into topology nodes (ethereum, escrows, nft)."""
    evm = chain.get("evm") or {}
    sol = chain.get("solana") or {}
    contracts_cfg = chain.get("contracts") or {}

    by_id = {n["id"]: n for n in nodes}

    if "ethereum" in by_id:
        if evm.get("connected"):
            by_id["ethereum"]["status"] = "active"
            cid = int(evm.get("chain_id", 0) or 0)
            # Relabel the node to the chain it is actually connected to (Base, not "Ethereum").
            by_id["ethereum"]["label"] = _CHAIN_NAMES.get(cid) or (evm.get("chain") or "EVM").title()
            by_id["ethereum"]["metrics"] = {
                "chain": evm.get("chain", ""),
                "chain_id": cid,
                "block": evm.get("block", 0),
                "gas": evm.get("gas_gwei", 0),
                "rpc": evm.get("rpc", ""),
            }
        else:
            # LIVE/UNI but this network isn't connected → show it explicitly offline
            # (greyed), not as a live participant.
            by_id["ethereum"]["status"] = "offline"
            by_id["ethereum"]["metrics"] = {"connected": 0}

    evm_contracts = evm.get("contracts") or {}

    if "evm_escrow" in by_id:
        esc = evm_contracts.get("escrow") or {}
        addr = esc.get("address") or contracts_cfg.get("escrow_evm")
        if addr:
            by_id["evm_escrow"]["metrics"] = {
                "address": addr,
                "chain": evm.get("chain", chain.get("primary_chain", "")),
                "deployed": 1 if esc.get("deployed") else 0,
                "balance_eth": esc.get("balance_eth", 0),
                "channels": 0,
                "tvl": 0,
            }
            # active = contract code is on-chain; else fall back to chain reachability
            # (idle = chain up but escrow not deployed at that address; unknown = chain unreachable)
            by_id["evm_escrow"]["status"] = "active" if esc.get("deployed") else (
                "idle" if evm.get("connected") else "unknown"
            )
        elif evm.get("connected"):
            by_id["evm_escrow"]["status"] = "idle"
            by_id["evm_escrow"]["metrics"]["chain"] = evm.get("chain", "")
        else:
            # no escrow configured AND chain not connected → explicitly offline (greyed)
            by_id["evm_escrow"]["status"] = "offline"

    if "nft_contract" in by_id:
        nft = evm_contracts.get("nft") or {}
        addr = nft.get("address") or contracts_cfg.get("nft_evm")
        if addr:
            by_id["nft_contract"]["metrics"] = {
                "address": addr,
                "chain": evm.get("chain", ""),
                "deployed": 1 if nft.get("deployed") else 0,
                "balance_eth": nft.get("balance_eth", 0),
                "minted": 0,
                "holders": 0,
            }
            by_id["nft_contract"]["status"] = "active" if nft.get("deployed") else (
                "idle" if evm.get("connected") else "unknown"
            )

    if "solana" in by_id:
        if sol.get("connected"):
            by_id["solana"]["status"] = "active"
            by_id["solana"]["metrics"] = {
                "slot": sol.get("slot", 0),
                "block_height": sol.get("block_height", 0),
                "tps": 0,
                "rpc": sol.get("rpc", ""),
            }
        else:
            # Solana not wired in this deployment (e.g. EVM-only UNI) → explicitly offline.
            by_id["solana"]["status"] = "offline"
            by_id["solana"]["metrics"] = {"connected": 0}

    if "solana_escrow" in by_id:
        prog = sol.get("program") or {}
        addr = prog.get("address") or contracts_cfg.get("escrow_solana")
        if addr:
            by_id["solana_escrow"]["metrics"] = {
                "program_id": addr,
                "deployed": 1 if prog.get("deployed") else 0,
                "lamports": prog.get("lamports", 0),
                "channels": 0,
                "tvl": 0,
            }
            by_id["solana_escrow"]["status"] = "active" if prog.get("deployed") else (
                "idle" if sol.get("connected") else "unknown"
            )
        elif sol.get("connected"):
            by_id["solana_escrow"]["status"] = "idle"
        else:
            # no Solana escrow program configured AND Solana not connected → explicitly offline
            by_id["solana_escrow"]["status"] = "offline"


def apply_onchain_native_to_nodes(nodes: list[dict], native: dict[str, Any]) -> None:
    """Overlay native-unit on-chain reads onto topology nodes (lottery, escrow, acex, nft)."""
    by_id = {n["id"]: n for n in nodes}
    lot = native.get("lottery")
    if isinstance(lot, dict) and "lottery" in by_id:
        m = by_id["lottery"].setdefault("metrics", {})
        m.pop("prize_pool_usd", None)
        m.pop("players", None)
        m["prize_pool_eth"] = float(lot.get("prize_pool") or 0)
        m["round"] = int(lot.get("round") or 0)
        m["tickets"] = int(lot.get("tickets") or 0)
        if "payouts_24h" not in m:
            m["payouts_24h"] = 0
    if "evm_escrow" in by_id:
        esc = by_id["evm_escrow"].setdefault("metrics", {})
        if "escrow_tvl" in native:
            esc["tvl"] = float(native["escrow_tvl"])
        if "escrow_channels" in native:
            esc["channels"] = int(native["escrow_channels"])
    if "acex" in by_id and "acex_tvl" in native:
        by_id["acex"].setdefault("metrics", {})["tvl"] = float(native["acex_tvl"])
    if "nft_contract" in by_id and "nft_minted" in native:
        by_id["nft_contract"].setdefault("metrics", {})["minted"] = int(native["nft_minted"])


def hub_events_to_activity(hub_payload: dict[str, Any]) -> tuple[list[dict], dict[str, Any]]:
    """Map hub /stats/live JSON to monitor events + metric hints."""
    events_out: list[dict] = []
    hints: dict[str, Any] = {
        "invocations_24h": 0,
        "channels_open": 0,
        "volume_24h": 0,
    }
    summary = hub_payload.get("summary") if isinstance(hub_payload, dict) else {}
    if isinstance(summary, dict):
        hints["invocations_24h"] = int(summary.get("total_invocations") or summary.get("invocations_24h") or 0)
        hints["channels_open"] = int(summary.get("open_channels") or summary.get("channels_open") or 0)
        hints["volume_24h"] = float(summary.get("volume_usd") or summary.get("volume_24h") or 0)

    raw_events = hub_payload.get("events") if isinstance(hub_payload, dict) else []
    if not isinstance(raw_events, list):
        return events_out, hints

    for i, ev in enumerate(raw_events[:20]):
        if not isinstance(ev, dict):
            continue
        events_out.append(
            {
                "id": str(ev.get("id") or f"hub_{i}"),
                "ts": ev.get("ts") or datetime.now(timezone.utc).isoformat(),
                "agent": str(ev.get("consumer_hub") or ev.get("agent") or "hub-client"),
                "action": str(ev.get("action") or "invoke"),
                "target": str(ev.get("capability_id") or ev.get("target") or "hub"),
                "amount": float(
                    ev.get("amount_usd")
                    or ev.get("price_usd")
                    or ev.get("amount")
                    or 0
                ),
                "token": str(ev.get("token") or "USDT"),
                "onchain": False,
            }
        )
    return events_out, hints


def build_real_summary(
    *,
    tick: int,
    hub_hints: dict[str, Any],
    mesh_stats: dict[str, Any] | None,
    chain: dict[str, Any],
) -> dict[str, Any]:
    evm = chain.get("evm") or {}
    sol = chain.get("solana") or {}
    agents = 0
    if isinstance(mesh_stats, dict):
        agents = int(mesh_stats.get("agents") or mesh_stats.get("agents_online") or 0)

    return {
        "total_invocations_24h": hub_hints.get("invocations_24h", 0),
        "total_volume_usd": hub_hints.get("volume_24h", 0),
        "active_channels": hub_hints.get("channels_open", 0),
        "tvl_usd": 0,
        "agents_online": agents,
        "apps_online": 0,
        "tps_solana": 0,
        "gas_gwei": evm.get("gas_gwei", 0),
        "block_number": evm.get("block", 0),
        "onchain_tx_count": 0,
        "mode": "real",
        "tick": tick,
        "blockchain_ready": bool(evm.get("connected") or sol.get("connected")),
        "evm_chain": evm.get("chain") or chain.get("primary_chain"),
        "evm_rpc": evm.get("rpc"),
        "solana_rpc": sol.get("rpc"),
        "evm_chain_id": evm.get("chain_id"),
        "solana_slot": sol.get("slot"),
        # Selected network surfaced for the UI (so it shows e.g. "Base", not a guess).
        "network": chain.get("network") or {},
        "network_name": (chain.get("network") or {}).get("name")
        or (evm.get("chain") or chain.get("primary_chain") or "").title(),
    }

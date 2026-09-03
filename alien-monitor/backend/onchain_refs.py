"""Per-node on-chain identity (contract address / wallet + network) for the
NodeDetail card.

Each mode fills `node["onchain"]` with the values that are actually true there:
  - LIVE  → real Base-mainnet addresses + chain id 8453 + basescan explorer
  - UNI   → the local Universe Anvil deployment (chain id 31337, no explorer)
  - TEST  → clearly-labelled MOCK addresses (mock=True, no explorer)

Honest by construction: no address ⇒ no ref (the card omits the section), and a
TEST ref always carries ``mock: true`` so the UI can badge it as fake.
"""

from __future__ import annotations

import hashlib
from typing import Any

# Universe Anvil chain id (standard Foundry/Anvil default).
UNI_CHAIN_ID = 31337
UNI_NETWORK = "AICOM Universe · Anvil"

# node id -> address key in chain_net._BASE_ADDRESSES (the live Base demo set).
LIVE_CONTRACTS = {
    "evm_escrow": "AIMarketEscrow",
    "nft_contract": "AIMarketCapabilityNFT",
    "lottery": "AIAgentLottery",
    "acex": "AgentListingRegistry",
}


def _explorer_addr(explorer_tx: str, address: str) -> str:
    """Turn a "…/tx/{}" template into an address URL ("…/address/<addr>")."""
    if not explorer_tx or not address:
        return ""
    base = explorer_tx.split("/tx/")[0] if "/tx/" in explorer_tx else explorer_tx.rstrip("/")
    return f"{base}/address/{address}"


def make_ref(
    address: str | None,
    network: str,
    chain_id: int | None,
    *,
    explorer_tx: str = "",
    kind: str = "contract",
    mock: bool = False,
) -> dict[str, Any] | None:
    """Build an on-chain ref, or None when there is no address (so the caller can
    simply skip nodes that have no on-chain identity in this mode)."""
    if not address:
        return None
    ref: dict[str, Any] = {"address": address, "network": network, "kind": kind}
    if chain_id is not None:
        ref["chain_id"] = chain_id
    explorer = _explorer_addr(explorer_tx, address)
    if explorer:
        ref["explorer"] = explorer
    if mock:
        ref["mock"] = True
    return ref


def attach_refs(nodes: list[dict], mapping: dict[str, dict | None]) -> None:
    by_id = {n.get("id"): n for n in nodes}
    for nid, ref in mapping.items():
        if ref and nid in by_id:
            by_id[nid]["onchain"] = ref


def _mock_address(node_id: str) -> str:
    """Deterministic, obviously-fake address for TEST (flagged mock=True)."""
    return "0x" + hashlib.sha1(f"aicom-mock:{node_id}".encode()).hexdigest()[:40]


def attach_test_refs(nodes: list[dict]) -> None:
    """TEST/simulator — mock contract addresses (network labelled, no explorer)."""
    by_id = {n.get("id"): n for n in nodes}
    mapping: dict[str, dict | None] = {}
    for nid in LIVE_CONTRACTS:
        if nid in by_id:
            mapping[nid] = make_ref(_mock_address(nid), "Base · mock", 8453, kind="contract", mock=True)
    if "ethereum" in by_id:
        by_id["ethereum"]["onchain"] = {"network": "Base · mock", "chain_id": 8453, "kind": "network", "mock": True}
    attach_refs(nodes, mapping)


def attach_uni_refs(nodes: list[dict], addresses: dict[str, str | None]) -> None:
    """UNI/universe — the local Anvil deployment. `addresses` keys: evm_escrow,
    evm_nft, evm_lottery, evm_usdt (as published by the VirtualUniverse)."""
    mapping = {
        "evm_escrow": make_ref(addresses.get("evm_escrow"), UNI_NETWORK, UNI_CHAIN_ID),
        "nft_contract": make_ref(addresses.get("evm_nft"), UNI_NETWORK, UNI_CHAIN_ID),
        "lottery": make_ref(addresses.get("evm_lottery"), UNI_NETWORK, UNI_CHAIN_ID),
    }
    attach_refs(nodes, mapping)
    by_id = {n.get("id"): n for n in nodes}
    if any(addresses.values()):
        for cid in ("ethereum",):
            if cid in by_id:
                by_id[cid]["onchain"] = {"network": UNI_NETWORK, "chain_id": UNI_CHAIN_ID, "kind": "network"}


def attach_live_refs(nodes: list[dict]) -> None:
    """LIVE/real — real addresses for the ACTIVE EVM network from chain_net."""
    try:
        import chain_net
        from chain_metrics import primary_evm_chain

        spec = chain_net.network(primary_evm_chain())
    except Exception:
        return
    addrs = spec.addresses or {}
    net, cid, ex = spec.display_name, spec.chain_id, spec.explorer_tx
    mapping = {
        nid: make_ref(addrs.get(key), net, cid, explorer_tx=ex)
        for nid, key in LIVE_CONTRACTS.items()
    }
    attach_refs(nodes, mapping)
    by_id = {n.get("id"): n for n in nodes}
    if "ethereum" in by_id:
        explorer = ex.split("/tx/")[0] if "/tx/" in ex else ""
        by_id["ethereum"]["onchain"] = {
            "network": net, "kind": "network",
            **({"chain_id": cid} if cid is not None else {}),
            **({"explorer": explorer} if explorer else {}),
        }

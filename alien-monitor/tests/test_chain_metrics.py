"""Tests for LIVE mode on-chain polling."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from chain_metrics import (
    _hex_to_int,
    _json_rpc_failover,
    active_network_info,
    apply_chain_metrics_to_nodes,
    configured_contracts,
    evm_rpc_for_chain,
    evm_rpc_urls_for_chain,
    hub_events_to_activity,
    primary_evm_chain,
    build_real_summary,
)


def test_hex_to_int():
    assert _hex_to_int("0x10") == 16
    assert _hex_to_int(42) == 42


def test_primary_evm_chain_from_env(monkeypatch):
    monkeypatch.setenv("AIMARKET_PAYMENT_CHAIN", "arbitrum")
    assert primary_evm_chain() == "arbitrum"


def test_evm_rpc_for_chain(monkeypatch):
    monkeypatch.delenv("ALIEN_EVM_RPC", raising=False)
    monkeypatch.setenv("BASE_RPC_URL", "https://mainnet.base.org")
    assert evm_rpc_for_chain("base") == "https://mainnet.base.org"


def test_evm_rpc_override(monkeypatch):
    monkeypatch.setenv("ALIEN_EVM_RPC", "http://127.0.0.1:8545")
    assert evm_rpc_for_chain("base") == "http://127.0.0.1:8545"


def test_configured_contracts(monkeypatch):
    monkeypatch.setenv("AIMARKET_ESCROW_EVM_ADDRESS", "0x1234567890123456789012345678901234567890")
    monkeypatch.setenv("AIMARKET_NFT_CONTRACT", "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd")
    cfg = configured_contracts()
    assert cfg["escrow_evm"].startswith("0x1234")
    assert cfg["nft_evm"].startswith("0xabcd")


def test_hub_events_to_activity():
    payload = {
        "summary": {"total_invocations": 100, "open_channels": 5},
        "events": [
            {
                "id": "e1",
                "consumer_hub": "peer-a",
                "capability_id": "cap-x",
                "price_usd": 1.5,
                "action": "invoke",
            }
        ],
    }
    events, hints = hub_events_to_activity(payload)
    assert hints["invocations_24h"] == 100
    assert hints["channels_open"] == 5
    assert len(events) == 1
    assert events[0]["agent"] == "peer-a"


def test_apply_chain_metrics_to_nodes():
    nodes = [
        {"id": "ethereum", "status": "unknown", "metrics": {}},
        {"id": "evm_escrow", "status": "unknown", "metrics": {"channels": 0, "tvl": 0}},
        {"id": "nft_contract", "status": "unknown", "metrics": {}},
        {"id": "solana", "status": "unknown", "metrics": {}},
        {"id": "solana_escrow", "status": "unknown", "metrics": {}},
    ]
    chain = {
        "primary_chain": "base",
        "contracts": {
            "escrow_evm": "0x1234567890123456789012345678901234567890",
            "nft_evm": None,
            "escrow_solana": "EscrowProg1111111111111111111111111111111111",
        },
        "evm": {
            "connected": True,
            "chain": "base",
            "chain_id": 8453,
            "block": 12345,
            "gas_gwei": 0.05,
            "rpc": "https://mainnet.base.org",
            "contracts": {
                "escrow": {
                    "address": "0x1234567890123456789012345678901234567890",
                    "deployed": True,
                    "balance_eth": 0.1,
                }
            },
        },
        "solana": {
            "connected": True,
            "slot": 999,
            "block_height": 888,
            "rpc": "https://api.mainnet-beta.solana.com",
            "program": {"address": "EscrowProg1111111111111111111111111111111111", "deployed": True},
        },
    }
    apply_chain_metrics_to_nodes(nodes, chain)
    eth = next(n for n in nodes if n["id"] == "ethereum")
    assert eth["status"] == "active"
    assert eth["label"] == "Base"  # relabeled from chain_id 8453, not the hardcoded "Ethereum"
    assert eth["metrics"]["block"] == 12345
    esc = next(n for n in nodes if n["id"] == "evm_escrow")
    assert esc["status"] == "active"
    assert esc["metrics"]["deployed"] == 1


def test_disconnected_networks_are_marked_offline():
    # EVM-only deployment (e.g. UNI on anvil): Solana isn't connected → its node must
    # render explicitly offline (greyed), not as a live participant.
    nodes = [
        {"id": "ethereum", "status": "active", "metrics": {}},
        {"id": "solana", "status": "active", "metrics": {}},
        {"id": "solana_escrow", "status": "unknown", "metrics": {}},
    ]
    chain = {"evm": {"connected": True, "chain": "anvil", "chain_id": 31337, "block": 1},
             "solana": {"connected": False}}
    apply_chain_metrics_to_nodes(nodes, chain)
    eth = next(n for n in nodes if n["id"] == "ethereum")
    assert eth["status"] == "active"
    assert eth["label"] == "Anvil"  # unknown chain_id 31337 → title-cased chain name
    sol = next(n for n in nodes if n["id"] == "solana")
    assert sol["status"] == "offline"  # not shown as a connected network
    assert sol["metrics"] == {"connected": 0}
    # the Solana escrow with no program id + Solana not connected → explicitly offline (greyed)
    assert next(n for n in nodes if n["id"] == "solana_escrow")["status"] == "offline"

    # …and the reverse: EVM down, Solana up → EVM offline.
    nodes2 = [{"id": "ethereum", "status": "active", "metrics": {}}]
    apply_chain_metrics_to_nodes(nodes2, {"evm": {"connected": False}, "solana": {}})
    assert nodes2[0]["status"] == "offline"


class TestRpcFailoverAndNetwork:
    """The monitor's chain_net-backed network selection + RPC failover."""

    def _clear(self, monkeypatch):
        for k in (
            "ALIEN_EVM_RPC", "EVM_RPC", "EVM_RPC_URL", "AIMARKET_NFT_CHAIN_RPC", "AIMARKET_NFT_CHAIN",
            "ALIEN_EVM_CHAIN", "AIMARKET_PAYMENT_CHAIN", "AIFACTORY_AI_MARKET_CHAIN", "AIMARKET_CHAIN",
            "AIMARKET_NETWORK", "AIMARKET_TESTNET", "AIMARKET_RPC_BASE", "BASE_RPC_URL",
            "AIMARKET_ESCROW_EVM_ADDRESS", "AIFACTORY_AI_MARKET_CONTRACT",
            "AIMARKET_NFT_CONTRACT", "AIMARKET_NFT_CONTRACT_ADDRESS",
        ):
            monkeypatch.delenv(k, raising=False)

    def test_evm_rpc_urls_priority_monitor_override_first(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("ALIEN_EVM_RPC", "https://mon.node")
        urls = evm_rpc_urls_for_chain("base")
        assert urls[0] == "https://mon.node"              # monitor override = preferred default
        assert "https://mainnet.base.org" in urls         # chain_net presets retained as backups
        assert evm_rpc_for_chain("base") == "https://mon.node"

    def test_configured_contracts_default_to_base_demo(self, monkeypatch):
        self._clear(monkeypatch)
        cfg = configured_contracts()
        assert cfg["escrow_evm"].lower().startswith("0x3df85a")    # demo escrow on Base
        assert cfg["nft_evm"].lower().startswith("0xa9af")         # demo capability NFT

    def test_active_network_info_default_base(self, monkeypatch):
        self._clear(monkeypatch)
        info = active_network_info()
        assert info["id"] == "base" and info["chain_id"] == 8453 and info["name"] == "Base"

    def test_json_rpc_failover_skips_dead_endpoint(self):
        import asyncio

        class _Resp:
            def raise_for_status(self): ...
            def json(self): return {"jsonrpc": "2.0", "id": 1, "result": "0x2105"}

        class _Client:
            def __init__(self, down): self.down = set(down); self.calls = []
            async def post(self, url, json=None, headers=None):
                self.calls.append(url)
                if url in self.down:
                    raise ConnectionError("down")
                return _Resp()

        c = _Client(down={"https://a"})
        url, result = asyncio.run(_json_rpc_failover(c, ["https://a", "https://b"], "eth_chainId", []))
        assert url == "https://b" and result == "0x2105"   # failed over off the dead default
        assert c.calls == ["https://a", "https://b"]


def test_build_real_summary():
    summary = build_real_summary(
        tick=3,
        hub_hints={"invocations_24h": 50, "channels_open": 2, "volume_24h": 1000},
        mesh_stats={"agents": 7},
        chain={
            "primary_chain": "base",
            "evm": {"connected": True, "gas_gwei": 0.1, "block": 100, "chain": "base", "rpc": "https://x"},
            "solana": {"connected": True, "slot": 1, "rpc": "https://s"},
        },
    )
    assert summary["mode"] == "real"
    assert summary["tick"] == 3
    assert summary["agents_online"] == 7
    assert summary["blockchain_ready"] is True
    assert summary["block_number"] == 100

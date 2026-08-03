"""Tests for live ARGUS /health polling → graph node onchain + metrics."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from argus_status import apply_argus_to_nodes, _onchain_ref_from_health, merge_argus_runtime


def _argus_node() -> dict:
    return {
        "id": "argus",
        "label": "Argus",
        "metrics": {"runs_24h": 0},
        "status": "unknown",
    }


class TestArgusOnchainRef:
    def test_wallet_ref_when_economy_on(self):
        health = {
            "status": "ok",
            "economy": "on",
            "wallet": "0x3520b679c998EE01B0d5EB0458CB9abf4e7Bb9e7",
            "chainNetwork": "Base",
            "chainId": 8453,
            "walletExplorer": "https://basescan.org/address/0x3520b679c998EE01B0d5EB0458CB9abf4e7Bb9e7",
        }
        ref = _onchain_ref_from_health(health)
        assert ref is not None
        assert ref["address"] == health["wallet"]
        assert ref["kind"] == "wallet"
        assert ref["chain_id"] == 8453
        assert ref["network"] == "Base"
        assert "basescan" in ref["explorer"]

    def test_no_ref_when_economy_off(self):
        health = {
            "status": "ok",
            "economy": "off",
            "wallet": "0x3520b679c998EE01B0d5EB0458CB9abf4e7Bb9e7",
        }
        assert _onchain_ref_from_health(health) is None


class TestMergeArgusRuntime:
    def test_overlays_wallet_from_status_onto_health(self):
        health = {"status": "ok", "economy": "on", "model": "deepseek-chat", "uptimeSec": 5}
        status = {
            "status": "ok",
            "wallet": "0x3520b679c998EE01B0d5EB0458CB9abf4e7Bb9e7",
            "chainNetwork": "Base",
            "chainId": 8453,
        }
        merged = merge_argus_runtime(health, status)
        assert merged is not None
        assert "wallet" not in health
        assert merged["wallet"] == status["wallet"]
        assert merged["model"] == "deepseek-chat"


class TestApplyArgusToNodes:
    def test_merges_live_health(self):
        nodes = [_argus_node(), {"id": "hub", "status": "active"}]
        health = {
            "status": "ok",
            "economy": "on",
            "mode": "live",
            "model": "deepseek-chat",
            "version": "0.2.0",
            "uptimeSec": 120,
            "wallet": "0x3520b679c998EE01B0d5EB0458CB9abf4e7Bb9e7",
            "chainNetwork": "Base",
            "chainId": 8453,
            "walletExplorer": "https://basescan.org/address/0x3520b679c998EE01B0d5EB0458CB9abf4e7Bb9e7",
        }
        apply_argus_to_nodes(nodes, health)
        argus = nodes[0]
        assert argus["status"] == "active"
        assert argus["argus_live"]["economy"] == "on"
        assert argus["metrics"]["uptime_sec"] == 120
        assert argus["onchain"]["address"] == health["wallet"]
        assert "url" in argus

    def test_offline_when_no_health(self):
        nodes = [_argus_node()]
        apply_argus_to_nodes(nodes, None)
        assert nodes[0]["status"] == "offline"
        assert "onchain" not in nodes[0]

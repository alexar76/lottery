"""UNI bootstrap includes EVM + optional Solana lottery contract addresses."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from universe import VirtualUniverse, resolve_lottery_contracts_dir
from lottery_layers import _metrics_from_layers


def test_resolve_lottery_contracts_dir():
    p = resolve_lottery_contracts_dir()
    if p is None:
        pytest.skip("lottery/contracts not present (standalone alien-monitor mirror)")
    assert (p / "src" / "AIAgentLottery.sol").is_file()


def test_hub_snippet_includes_lottery_addresses(tmp_path):
    u = VirtualUniverse(data_dir=tmp_path)
    u.evm_escrow_address = "0x" + "e" * 40
    u.evm_nft_address = "0x" + "9" * 40
    u.evm_usdt_address = "0x" + "5" * 40
    u.evm_lottery_address = "0x" + "d" * 40
    u.solana_lottery_program_id = "DT6QVF7HhCQTFRCcP7V6AJpQF6ZQzEc9LQSrq85MHpFD"
    u.payment_recipient = "0x" + "f" * 40
    u._write_hub_env_snippet()
    text = (tmp_path / "hub.env.snippet").read_text(encoding="utf-8")
    assert "HUB_LOTTERY_ADDRESS=0x" + "d" * 40 in text
    assert "AIMARKET_LOTTERY_SOLANA_PROGRAM_ID=DT6QVF7HhCQTFRCcP7V6AJpQF6ZQzEc9LQSrq85MHpFD" in text


def test_lottery_contract_verified_checks_code():
    u = VirtualUniverse(data_dir=Path("/tmp/unused"))
    u._w3 = MagicMock()
    u._w3.is_connected.return_value = True
    u._w3.to_checksum_address.side_effect = lambda a: a
    u._w3.eth.get_code.return_value = b"\x01"
    u.evm_lottery_address = "0xabc"
    assert u._lottery_contract_verified() is True


def test_live_lottery_feed_overrides_layer_metrics():
    from live_lottery_feed import set_live_lottery

    set_live_lottery({
        "mode": "uni",
        "metrics": {"prize_pool_usd": 9.5, "round": 3, "players": 4,
                    "payouts_24h": 1.0, "opex_24h": 0.5, "funding_24h": 2.0},
        "events": [{"id": "lot_1", "agent": "Hub", "action": "tithe", "target": "lottery", "amount": 1}],
    })
    m = _metrics_from_layers({"invocations_24h": 999}, {"agents": 99})
    assert m["round"] == 3
    assert m["players"] == 4
    assert m["prize_pool_usd"] == 9.5

"""onchainVdf() must fail-soft when the deployed ABI/address is stale."""

from __future__ import annotations

from unittest.mock import MagicMock

from ailottery_relayer.chain import Chain


def test_onchain_vdf_returns_false_when_contract_reverts(monkeypatch):
    chain = Chain.__new__(Chain)
    fn = MagicMock()
    fn.call.side_effect = Exception("execution reverted")
    chain.contract = MagicMock()
    chain.contract.functions.onchainVdf.return_value = fn
    assert chain.onchain_vdf() is False


def test_onchain_vdf_returns_true_when_contract_answers(monkeypatch):
    chain = Chain.__new__(Chain)
    fn = MagicMock()
    fn.call.return_value = True
    chain.contract = MagicMock()
    chain.contract.functions.onchainVdf.return_value = fn
    assert chain.onchain_vdf() is True

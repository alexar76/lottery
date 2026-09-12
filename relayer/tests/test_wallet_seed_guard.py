"""Fail-closed guard: production must not derive agent wallets from a public/default seed.

Motivated by a real demo finding — with UNI_WALLET_SEED unset the relayer silently falls back
to the public Anvil operator key, making every derived agent wallet trivially sweepable. In
production that must hard-fail; in demo/uni (play-money, local chain) it stays permissive.
Run: `pip install -e relayer[dev] && pytest relayer/tests/test_wallet_seed_guard.py`.
"""
from __future__ import annotations

import pytest

from ailottery_relayer.config import _PUBLIC_DEV_SEEDS, Config

ANVIL0 = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"


def _base_env(monkeypatch):
    # Enable auto-wallet without UNI mode; clear anything we assert on.
    monkeypatch.setenv("UNI_AUTO_WALLET", "1")
    monkeypatch.delenv("UNI_WALLET_SEED", raising=False)
    monkeypatch.delenv("OPERATOR_KEY", raising=False)
    monkeypatch.delenv("AIFACTORY_PROD", raising=False)


def test_prod_autowallet_without_seed_fails_closed(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("AIFACTORY_PROD", "1")
    with pytest.raises(RuntimeError, match="UNI_WALLET_SEED is not"):
        Config.from_env()


def test_prod_autowallet_with_public_seed_fails_closed(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("AIFACTORY_PROD", "1")
    monkeypatch.setenv("UNI_WALLET_SEED", ANVIL0)
    with pytest.raises(RuntimeError, match="PUBLIC dev key"):
        Config.from_env()


def test_prod_autowallet_with_secret_seed_ok(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("AIFACTORY_PROD", "1")
    monkeypatch.setenv("UNI_WALLET_SEED", "0x" + "ab" * 32)  # a non-public secret
    c = Config.from_env()
    assert c.uni_wallet_seed == "0x" + "ab" * 32


def test_non_prod_is_permissive(monkeypatch):
    # demo/uni: public seed is acceptable (play-money, local chain) — must NOT raise.
    _base_env(monkeypatch)  # AIFACTORY_PROD unset
    c = Config.from_env()
    assert c.uni_auto_wallet is True


def test_autowallet_off_is_exempt_even_in_prod(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("AIFACTORY_PROD", "1")
    monkeypatch.setenv("UNI_AUTO_WALLET", "0")
    c = Config.from_env()  # no wallets are bound, so the seed is irrelevant
    assert c.uni_auto_wallet is False


def test_known_anvil_key_is_listed():
    assert ANVIL0 in _PUBLIC_DEV_SEEDS

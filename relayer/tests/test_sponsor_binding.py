"""Connectivity: the lottery↔Hub tithe binding (the «деньги не увести» gate).

The Hub funds ONLY its own bound lottery, donates nothing if that lottery isn't
deployed, and can never be redirected to another address. These tests pin that
anti-redirect contract — the core of the lottery↔Hub link.
"""
from __future__ import annotations

from ailottery_relayer.config import Config
from ailottery_relayer.sponsor import SponsorPolicy

A1 = "0x" + "1" * 40
A2 = "0x" + "2" * 40


class _Eth:
    def __init__(self, code: bytes):
        self._code = code

    def get_code(self, _addr):
        return self._code


class _W3:
    """Minimal web3 stand-in: only get_code is used by resolve_bound."""
    def __init__(self, code: bytes = b"\x60\x60"):
        self.eth = _Eth(code)


def _cfg(**kw) -> Config:
    c = Config()
    c.sponsor = {"sponsor": {"enabled": True, "requires_deployed_lottery": True}}
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def test_anti_redirect_refuses_a_different_lottery():
    # Hub configured to fund A1, but the relayer operates A2 → REFUSE (can't be redirected).
    b = SponsorPolicy(_cfg(mode="live", hub_lottery_address=A1)).resolve_bound(A2, _W3())
    assert b.ok is False
    assert "anti-redirect" in b.reason.lower()


def test_requires_deployed_lottery_donates_nothing_without_code():
    # uni self-binds to the deployed address, but there's no contract code there → donate nothing.
    b = SponsorPolicy(_cfg(mode="uni")).resolve_bound(A1, _W3(code=b""))
    assert b.ok is False


def test_demo_uni_self_binds_when_code_present():
    b = SponsorPolicy(_cfg(mode="uni")).resolve_bound(A1, _W3(code=b"\x60\x60"))
    assert b.ok is True
    assert b.address.lower() == A1.lower()


def test_live_without_bound_lottery_donates_nothing():
    # LIVE + no configured bound lottery → never moves funds.
    b = SponsorPolicy(_cfg(mode="live")).resolve_bound(A1, _W3())
    assert b.ok is False


def test_disabled_sponsor_donates_nothing():
    c = _cfg(mode="uni")
    c.sponsor = {"sponsor": {"enabled": False}}
    assert SponsorPolicy(c).resolve_bound(A1, _W3()).ok is False


def test_tithe_is_a_share_of_hub_revenue():
    # 20% of the Hub's routing-fee revenue (Hub-owned rate).
    assert SponsorPolicy(_cfg(mode="uni", hub_tithe_bps=2000)).tithe_usd(5.0) == 1.0

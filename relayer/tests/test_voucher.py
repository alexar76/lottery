"""Regression guard: the /voucher endpoint must REALLY invoke the LUMEN oracle.

History: the standalone agent's reputation voucher used to bypass the oracle with a
raw `_pseudo_bonus`, while the round loop's synthetic crowd went through
`OracleClient.lumen_reputation`. In live mode that was a desync — the real agent's
odds boost was not oracle-derived. These tests pin the fixed behavior:

  * /voucher calls `lumen_reputation` (priced + booked as opex in live mode),
  * the oracle-derived bonus flows into the signed voucher,
  * it is clamped to the contract cap before signing,
  * the shared opex ledger is thread-safe (the endpoint runs in a daemon thread
    concurrently with the round loop),
  * a single-agent / symmetric-graph response degrades to a per-agent score
    instead of a meaningless flat 0.

Run: `pip install -e relayer[dev] && pytest relayer/tests`.
"""
from __future__ import annotations

import threading

from ailottery_relayer.oracles import OpexLedger, OracleClient, OracleResult
from ailottery_relayer.server import MAX_REP_BONUS_BPS, make_app
from fastapi.testclient import TestClient


def _result(price: float = 0.005) -> OracleResult:
    return OracleResult(value={}, price_usd=price, routing_fee_usd=0.0, source="live-hub")


class _FakeChain:
    address = "0xLottery"

    def __init__(self) -> None:
        self.signed: list[int] = []

    def current_round_id(self) -> int:
        return 7

    def block(self) -> dict:
        return {"timestamp": 1_000_000}

    def sign_voucher(self, key, agent, rid, bonus, expiry):
        self.signed.append(bonus)
        return b"\x11" * 65


class _FakeOracles:
    def __init__(self, bonus: int) -> None:
        self.bonus = bonus
        self.calls = 0

    def lumen_reputation(self, agents):
        self.calls += 1
        return (dict.fromkeys(agents, self.bonus), _result())


class _FakeEngine:
    def __init__(self, bonus: int) -> None:
        self.cfg = type("C", (), {"mode": "demo"})()
        self.oracles = _FakeOracles(bonus)
        self.chain = _FakeChain()
        self.signer_key = "0xkey"
        self.state = {}

    def snapshot(self) -> dict:
        return {}


_AGENT = "0x000000000000000000000000000000000000dEaD"


def test_voucher_really_invokes_lumen() -> None:
    engine = _FakeEngine(bonus=1234)
    client = TestClient(make_app(engine))

    resp = client.post("/voucher", json={"agent": _AGENT})

    assert resp.status_code == 200, resp.text
    assert engine.oracles.calls == 1, "voucher did not call lumen_reputation"
    body = resp.json()
    assert body["rep_bonus_bps"] == 1234  # oracle-derived bonus, not a bypass
    assert body["round_id"] == 7
    assert body["signature"].startswith("0x")
    assert engine.chain.signed == [1234]  # the same bonus was signed


def test_voucher_clamps_to_contract_cap() -> None:
    engine = _FakeEngine(bonus=99_999)  # oracle over-reports
    client = TestClient(make_app(engine))

    resp = client.post("/voucher", json={"agent": _AGENT})

    assert resp.status_code == 200, resp.text
    assert resp.json()["rep_bonus_bps"] == MAX_REP_BONUS_BPS == 5_000
    assert engine.chain.signed == [5_000]  # clamped before signing → contract won't reject


def test_scores_to_bonuses_degenerate_falls_back_to_per_agent() -> None:
    # single agent → no spread → deterministic per-agent proxy, not a flat 0
    one = OracleClient._scores_to_bonuses(["0xA"], [0.7])
    assert one == {"0xA": OracleClient._pseudo_bonus("0xA")}

    # symmetric trust ring → identical scores → per-agent proxy (each distinct), not all 0
    sym = OracleClient._scores_to_bonuses(["a", "b", "c"], [0.5, 0.5, 0.5])
    assert sym == {x: OracleClient._pseudo_bonus(x) for x in ("a", "b", "c")}
    assert not all(v == 0 for v in sym.values()) or all(
        OracleClient._pseudo_bonus(x) == 0 for x in ("a", "b", "c")
    )


def test_scores_to_bonuses_real_spread_maps_to_0_5000() -> None:
    out = OracleClient._scores_to_bonuses(["a", "b"], [0.0, 1.0])
    assert out == {"a": 0, "b": 5_000}


def test_opex_ledger_is_thread_safe() -> None:
    ledger = OpexLedger()

    def hammer() -> None:
        for _ in range(500):
            ledger.record(_result(price=0.005))

    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert ledger.calls == 2_000  # no lost updates under concurrency
    assert round(ledger.oracle_spend_usd, 3) == 10.0

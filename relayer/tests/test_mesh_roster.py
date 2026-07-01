"""The lottery roster is built from REAL verified Mesh agents, not invented names.

These tests pin: trust_score → odds-bonus mapping (clamped to the contract cap), the
Mesh client's parse/sort/skip + fault-tolerance, and the mesh/synthetic roster builders.
Run: `pip install -e relayer[dev] && pytest relayer/tests`.
"""
from __future__ import annotations

from ailottery_relayer.config import Config
from ailottery_relayer.economy import (
    derive_agent_key,
    mesh_roster,
    synthetic_roster,
    uni_wallet_roster,
)
from ailottery_relayer.roster import Participant as RosterParticipant
from ailottery_relayer.mesh import MeshAgent, MeshClient
from eth_account import Account


class _FakeResp:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


def _client(data):
    cfg = Config()
    cfg.mesh_url = "http://mesh:8000"
    mc = MeshClient(cfg)
    mc._http = type("H", (), {"get": lambda self, url, params=None: _FakeResp(data)})()
    return mc


def test_trust_bps_clamped_to_contract_cap():
    assert MeshAgent("i", "n", 0.5).trust_bps == 2500
    assert MeshAgent("i", "n", 1.0).trust_bps == 5000
    assert MeshAgent("i", "n", 9.9).trust_bps == 5000   # never exceeds MAX_REP_BONUS_BPS
    assert MeshAgent("i", "n", -1.0).trust_bps == 0     # never negative


def test_fetch_agents_parses_sorts_and_skips():
    mc = _client([
        {"id": "a1", "name": "CodeNova", "trust_score": 0.9, "evm_address": "0x" + "1" * 40},
        {"id": "a2", "name": "AuditHawk", "trust_score": 0.3},
        {"id": "bad", "trust_score": 0.5},  # no name → skipped
    ])
    got = mc.fetch_agents(limit=5)
    assert [a.name for a in got] == ["CodeNova", "AuditHawk"]  # highest-trust first, junk dropped
    assert got[0].evm_address == "0x" + "1" * 40


def test_fetch_agents_caps_to_limit():
    rows = [{"id": f"a{i}", "name": f"N{i}", "trust_score": i / 10} for i in range(10)]
    assert len(_client(rows).fetch_agents(limit=3)) == 3


def test_fetch_agents_is_fault_tolerant():
    cfg = Config()
    cfg.mesh_url = "http://mesh:8000"
    mc = MeshClient(cfg)

    def _boom(*a, **k):
        raise RuntimeError("mesh down")

    mc._http = type("H", (), {"get": _boom})()
    assert mc.fetch_agents(5) == []  # falls back to synthetic crowd, never raises


def test_fetch_agents_disabled_when_no_mesh_url():
    assert MeshClient(Config()).fetch_agents(5) == []  # mesh_url unset ⇒ disabled


def test_mesh_roster_seats_real_agents_on_funded_keys():
    from ailottery_relayer.economy import Participant

    assert RosterParticipant is Participant
    agents = [MeshAgent("a1", "CodeNova", 0.9, evm_address="0x" + "1" * 40),
              MeshAgent("a2", "AuditHawk", 0.3)]
    keys = ["0xk1", "0xk2", "0xk3"]
    addrs = ["0xA1", "0xA2", "0xA3"]
    roster = mesh_roster(agents, keys, addrs)
    assert [p.name for p in roster] == ["CodeNova", "AuditHawk"]
    assert all(p.source == "mesh" for p in roster)
    assert roster[0].trust_bps == 4500 and roster[0].addr == "0xA1" and roster[0].wallet == "0x" + "1" * 40
    assert roster[0].mesh_id == "a1"


def test_synthetic_roster_is_the_fallback_crowd():
    roster = synthetic_roster(["0xk1", "0xk2"], ["0xA1", "0xA2"])
    assert [p.name for p in roster] == ["Aria", "Boreas"]
    assert all(p.source == "synthetic" and p.trust_bps == 0 for p in roster)


def test_derive_agent_key_deterministic_and_distinct():
    k1 = derive_agent_key("seed", "agt_1")
    assert k1 == derive_agent_key("seed", "agt_1")        # same agent ⇒ same wallet every round
    assert k1 != derive_agent_key("seed", "agt_2")        # distinct per agent
    assert k1 != derive_agent_key("other-seed", "agt_1")  # seed-bound
    assert len(k1.removeprefix("0x")) == 64               # a 32-byte private key
    assert Account.from_key(k1).address.startswith("0x")  # usable to sign on-chain


def test_uni_wallet_roster_is_self_custodial():
    agents = [MeshAgent("agt_1", "CodeNova", 0.9), MeshAgent("agt_2", "AuditHawk", 0.2)]
    roster = uni_wallet_roster(agents, "uni-seed")
    assert [p.name for p in roster] == ["CodeNova", "AuditHawk"]
    # each agent signs with its OWN derived wallet (key→addr), not a shared relayer key
    assert roster[0].addr == Account.from_key(roster[0].key).address
    assert roster[0].addr != roster[1].addr
    assert roster[0].wallet == roster[0].addr and roster[0].source == "mesh"
    assert roster[0].mesh_id == "agt_1" and roster[0].trust_bps == 4500

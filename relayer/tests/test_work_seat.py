"""Work-seat door: unpaid enterFromWork is the default; paid tickets stay off."""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from eth_account import Account

from ailottery_relayer.economy import (
    WORK_WEIGHT_BPS,
    live_work_roster,
    Participant,
)


def test_live_work_roster_is_distinct_named_wallets():
    a = live_work_roster("secret-seed-one", 4)
    b = live_work_roster("secret-seed-one", 4)
    assert [p.name for p in a] == ["AuditHawk", "NetPulse", "CodeNova", "DeepScout"]
    assert [p.addr for p in a] == [p.addr for p in b]
    assert len({p.addr for p in a}) == 4
    other = live_work_roster("other-seed", 4)
    assert {p.addr for p in a}.isdisjoint({p.addr for p in other})
    assert all(p.source == "work" and len(p.key.replace("0x", "")) == 64 for p in a)
    assert live_work_roster("secret-seed-one", 0) == []


def test_roster_source_never_labels_live_work_or_empty_as_synthetic():
    from ailottery_relayer.economy import EconomyEngine

    work = SimpleNamespace(
        _roster=[Participant(name="A", key="k", addr="0x1", source="work")]
    )
    empty = SimpleNamespace(_roster=[])
    assert EconomyEngine.roster_source.__get__(work) == "work"
    assert EconomyEngine.roster_source.__get__(empty) == "none"


def test_enter_from_work_signs_and_sends_unpaid_seat():
    from ailottery_relayer.economy import EconomyEngine

    p = Participant(name="AuditHawk", key="0x" + "11" * 32, addr="0x" + "aa" * 20, source="work")
    engine = SimpleNamespace(
        cfg=SimpleNamespace(sim_agents=True, mode="live", hub_url="https://hub.example"),
        _roster=[p],
        signer_key="0xsigner",
        chain=SimpleNamespace(
            paid_tickets_enabled=lambda: False,
            block=lambda: {"timestamp": 1_700_000_000},
            work_seated=lambda rid, addr: False,
            participant_seated=lambda rid, participant: False,
            sign_work_seat=MagicMock(return_value=b"\x22" * 65),
            send=MagicMock(),
        ),
        fn=SimpleNamespace(enterFromWork=MagicMock(return_value="fn")),
        _event=MagicMock(),
        _refresh_roster=lambda: None,
    )
    EconomyEngine._enter_from_work(engine, 3)
    engine.chain.sign_work_seat.assert_called_once()
    args = engine.chain.sign_work_seat.call_args[0]
    assert args[1] == p.addr and args[3] == 3 and args[4] == WORK_WEIGHT_BPS
    engine.chain.send.assert_called_once()
    call = engine.fn.enterFromWork.call_args[0]
    assert call[0] == 3 and call[2:] == (WORK_WEIGHT_BPS, 1_700_000_000 + 86_400, b"\x22" * 65)


def test_sell_tickets_uses_work_seat_when_paid_off():
    from ailottery_relayer.economy import EconomyEngine

    engine = SimpleNamespace(
        cfg=SimpleNamespace(sim_agents=True),
        _roster=[Participant(name="A", key="k", addr="0x1")],
        chain=SimpleNamespace(paid_tickets_enabled=lambda: False),
        _refresh_roster=MagicMock(),
        _enter_from_work=MagicMock(),
        _buy_tickets=MagicMock(),
    )
    EconomyEngine.sell_tickets(engine, 9)
    engine._enter_from_work.assert_called_once_with(9)
    engine._buy_tickets.assert_not_called()


def test_already_work_seated_is_skipped():
    from ailottery_relayer.economy import EconomyEngine

    p = Participant(name="AuditHawk", key="0x" + "11" * 32, addr="0x" + "aa" * 20, source="work")
    engine = SimpleNamespace(
        cfg=SimpleNamespace(sim_agents=True, mode="live", hub_url="https://hub.example"),
        _roster=[p],
        signer_key="0xsigner",
        chain=SimpleNamespace(
            paid_tickets_enabled=lambda: False,
            block=lambda: {"timestamp": 1_700_000_000},
            work_seated=lambda rid, addr: True,
            participant_seated=lambda rid, participant: False,
            sign_work_seat=MagicMock(),
            send=MagicMock(),
        ),
        fn=SimpleNamespace(enterFromWork=MagicMock()),
        _event=MagicMock(),
        _refresh_roster=lambda: None,
    )
    EconomyEngine._enter_from_work(engine, 1)
    engine.chain.send.assert_not_called()
    engine._event.assert_not_called()


def test_live_tithe_is_not_invented_from_operator_eth():
    from ailottery_relayer.economy import EconomyEngine

    engine = SimpleNamespace(
        cfg=SimpleNamespace(mode="live"),
        binding=SimpleNamespace(ok=True),
        chain=SimpleNamespace(send=MagicMock()),
    )
    EconomyEngine.apply_sponsor_tithe(engine, 1)
    engine.chain.send.assert_not_called()


def test_wait_for_fund_does_not_open_a_second_round():
    from ailottery_relayer.economy import EconomyEngine

    calls = {"open": 0}

    def open_round():
        calls["open"] += 1
        return 1

    engine = SimpleNamespace(
        cfg=SimpleNamespace(wait_for_fund=True, sell_window=0, sim_agents=True),
        chain=SimpleNamespace(
            current_round_id=lambda: 1,
            get_round=lambda rid: {"status": 1, "funding": 0},
        ),
        _ensure_contract_live=lambda: True,
        stalled_rounds=[],
        open_round=open_round,
        sell_tickets=MagicMock(),
        apply_sponsor_tithe=MagicMock(),
        apply_uni_benefactor=MagicMock(),
        publish=MagicMock(),
        close_and_draw=MagicMock(),
    )
    # preflight + sweep are imported names on the method; patch via module-level is heavy.
    # Drive the body after those guards by calling the wait branch with an Open round.
    EconomyEngine.run_one_round = EconomyEngine.run_one_round
    # Manually: existing Open round + zero funding must not call open_round.
    from ailottery_relayer import economy as eco

    orig_pre = eco.preflight_draw_window
    orig_sweep = eco.sweep_stalled_rounds
    eco.preflight_draw_window = lambda _e: True
    eco.sweep_stalled_rounds = lambda e, s: s
    try:
        EconomyEngine.run_one_round(engine)
    finally:
        eco.preflight_draw_window = orig_pre
        eco.sweep_stalled_rounds = orig_sweep
    assert calls["open"] == 0
    engine.close_and_draw.assert_not_called()
    engine.sell_tickets.assert_called_once_with(1)


def test_derived_key_is_a_real_private_key():
    roster = live_work_roster("seed", 1)
    Account.from_key(roster[0].key)  # must not raise


def test_rpc_url_list_and_live_fallbacks():
    from ailottery_relayer.rpc import LIVE_FALLBACKS, parse_rpc_urls, with_live_fallbacks

    assert parse_rpc_urls(" https://a.example ,https://b.example") == [
        "https://a.example", "https://b.example",
    ]
    demo = with_live_fallbacks(["http://chain:8545"], False)
    assert demo == ["http://chain:8545"]
    live = with_live_fallbacks(["https://mainnet.base.org"], True)
    assert live[0] == "https://mainnet.base.org"
    assert "https://base-rpc.publicnode.com" in live
    assert all(fb in live for fb in LIVE_FALLBACKS)


def test_publish_keeps_last_snapshot_on_rpc_blip():
    from ailottery_relayer.economy import EconomyEngine

    engine = SimpleNamespace(
        snapshot=MagicMock(side_effect=RuntimeError("429")),
        monitor=SimpleNamespace(push=MagicMock()),
        state={"mode": "live", "round": 1, "players": 4},
        _seed_state=MagicMock(),
    )
    EconomyEngine.publish(engine)
    engine.monitor.push.assert_not_called()
    assert engine.state["players"] == 4


def test_live_health_fails_closed_without_participant_bound_contract_abi():
    from fastapi.testclient import TestClient
    from ailottery_relayer.server import make_app

    engine = SimpleNamespace(
        cfg=SimpleNamespace(mode="live"),
        chain=SimpleNamespace(
            address="0xOldLottery",
            supports_federated_work_seats=lambda: False,
        ),
        contract_live=True,
        state={},
        snapshot=lambda: {},
    )
    response = TestClient(make_app(engine)).get("/healthz")
    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "mode": "live",
        "address": "0xOldLottery",
        "contract_live": True,
        "federated_work_seat_compatible": False,
    }


def test_live_health_requires_code_and_participant_bound_abi():
    from fastapi.testclient import TestClient
    from ailottery_relayer.server import make_app

    engine = SimpleNamespace(
        cfg=SimpleNamespace(mode="live"),
        chain=SimpleNamespace(
            address="0xNewLottery",
            supports_federated_work_seats=lambda: True,
        ),
        contract_live=True,
        state={},
        snapshot=lambda: {},
    )
    response = TestClient(make_app(engine)).get("/healthz")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["federated_work_seat_compatible"] is True


def test_work_seat_endpoint_signs_for_a_federated_participant():
    from fastapi.testclient import TestClient
    from ailottery_relayer.server import WORK_WEIGHT_BPS, make_app
    import ailottery_relayer.server as server_mod

    server_mod._work_seat_by_agent.clear()

    class Chain:
        address = "0xFederatedLottery"

        def current_round_id(self):
            return 1

        def block(self):
            return {"timestamp": 1_700_000_000}

        def work_seated(self, rid, agent):
            return False

        def participant_seated(self, rid, participant):
            return False

        def sign_work_seat(self, key, agent, participant, rid, weight, expiry):
            assert weight == WORK_WEIGHT_BPS
            return b"\x33" * 65

    engine = SimpleNamespace(
        cfg=SimpleNamespace(mode="live"),
        chain=Chain(),
        signer_key="0xkey",
        state={},
        snapshot=lambda: {},
        eligibility_verifier=SimpleNamespace(
            verify=lambda entitlement, wallet: "0x" + "44" * 32
        ),
    )
    client = TestClient(make_app(engine))
    agent = "0x000000000000000000000000000000000000dEaD"
    # The Hub stamps expires_at on ITS wall clock; the chain runs on its own (uni mode
    # warps anvil forward by hours). The endpoint carries the proof's remaining LIFETIME
    # across instead of comparing the two clocks, so the proof must be live-relative here.
    _now = int(time.time())
    resp = client.post("/work-seat", json={
        "agent": agent,
        "entitlement": {
            "purpose": "ai-agent-lottery-work-seat-v1",
            "hub_url": "https://peer.example",
            "agent_id": "agent-7",
            "participant_id": "0x" + "44" * 32,
            "wallet": agent,
            "issued_at": _now,
            "expires_at": _now + 300,
            "nonce": "n",
            "signature": {},
        },
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["round_id"] == 1
    assert body["weight_bps"] == 10_000
    assert body["already_seated"] is False
    assert body["participant_id"] == "0x" + "44" * 32
    # chain block time + the proof's remaining lifetime (capped at 600s), not the Hub stamp.
    assert body["expiry"] == 1_700_000_000 + 300
    assert body["signature"].startswith("0x")
    assert body["lottery"] == "0xFederatedLottery"


def test_work_seat_endpoint_skips_if_already_seated():
    from fastapi.testclient import TestClient
    from ailottery_relayer.server import make_app
    import ailottery_relayer.server as server_mod

    server_mod._work_seat_by_agent.clear()

    class Chain:
        address = "0xLottery"
        signed = False

        def current_round_id(self):
            return 2

        def block(self):
            return {"timestamp": 1}

        def work_seated(self, rid, agent):
            return True

        def participant_seated(self, rid, participant):
            return False

        def sign_work_seat(self, *a, **k):
            self.signed = True
            return b"\x00" * 65

    engine = SimpleNamespace(
        cfg=SimpleNamespace(mode="live"), chain=Chain(),
        signer_key="0x", state={}, snapshot=lambda: {},
        eligibility_verifier=SimpleNamespace(
            verify=lambda entitlement, wallet: "0x" + "55" * 32
        ),
    )
    body = TestClient(make_app(engine)).post(
        "/work-seat", json={
            "agent": "0x000000000000000000000000000000000000dEaD",
            "entitlement": {
                "purpose": "ai-agent-lottery-work-seat-v1",
                "hub_url": "https://peer.example",
                "agent_id": "agent-7",
                "participant_id": "0x" + "55" * 32,
                "wallet": "0x000000000000000000000000000000000000dEaD",
                "issued_at": 1,
                "expires_at": 2,
                "nonce": "n",
                "signature": {},
            },
        }
    ).json()
    assert body["already_seated"] is True
    assert "signature" not in body
    assert engine.chain.signed is False


def test_work_seat_endpoint_requires_entitlement_and_valid_agent():
    from fastapi.testclient import TestClient
    from ailottery_relayer.server import make_app

    engine = SimpleNamespace(
        cfg=SimpleNamespace(mode="live"),
        chain=SimpleNamespace(address="0xLottery"),
        signer_key="0x",
        state={},
        snapshot=lambda: {},
        eligibility_verifier=SimpleNamespace(verify=lambda *_a, **_k: "0x" + "66" * 32),
    )
    client = TestClient(make_app(engine))
    missing = client.post("/work-seat", json={"agent": "0x" + "11" * 20})
    assert missing.status_code == 403
    invalid = client.post(
        "/work-seat",
        json={
            "agent": "not-an-address",
            "entitlement": {
                "purpose": "ai-agent-lottery-work-seat-v1",
                "hub_url": "https://peer.example",
                "agent_id": "agent-7",
                "participant_id": "0x" + "66" * 32,
                "wallet": "not-an-address",
                "issued_at": 1,
                "expires_at": 2,
                "nonce": "n",
                "signature": {},
            },
        },
    )
    assert invalid.status_code == 422


def test_demo_work_seat_remains_self_contained_without_a_hub():
    from fastapi.testclient import TestClient
    from ailottery_relayer.server import make_app

    class Chain:
        address = "0xLottery"

        def current_round_id(self):
            return 4

        def block(self):
            return {"timestamp": 1_700_000_000}

        def work_seated(self, _rid, _agent):
            return False

        def participant_seated(self, _rid, _participant):
            return False

        def sign_work_seat(self, *_args):
            return b"\x77" * 65

    engine = SimpleNamespace(
        cfg=SimpleNamespace(mode="demo"), chain=Chain(), signer_key="0x",
        state={}, snapshot=lambda: {},
    )
    response = TestClient(make_app(engine)).post(
        "/work-seat", json={"agent": "0x" + "11" * 20}
    )
    assert response.status_code == 200, response.text
    assert response.json()["participant_id"].startswith("0x")


def test_participant_seat_from_another_wallet_is_not_reported_as_this_wallet_s_seat():
    """`workSeated[rid][wallet]` and `participantSeated[rid][pid]` are different nullifiers.

    Collapsing them into one `already_seated: true` told a caller whose wallet holds no
    seat that it was in the round — argus turns that into `ok: true`. The wallet then
    cannot win and cannot claim, and nothing surfaces the rotation that caused it.
    """
    from fastapi.testclient import TestClient

    from ailottery_relayer.server import make_app
    import ailottery_relayer.server as server_mod

    server_mod._work_seat_by_agent.clear()

    class Chain:
        address = "0xLottery"

        def current_round_id(self):
            return 7

        def block(self):
            return {"timestamp": 1_700_000_000}

        def work_seated(self, _rid, _agent):
            return False  # this WALLET is not seated

        def participant_seated(self, _rid, _participant):
            return True  # but the agent identity is, from another wallet

        def sign_work_seat(self, *_a, **_k):  # pragma: no cover - must not be reached
            raise AssertionError("must not sign when the wallet is not seated")

    now = int(time.time())
    engine = SimpleNamespace(
        cfg=SimpleNamespace(mode="live"), chain=Chain(), signer_key="0x",
        state={}, snapshot=lambda: {},
        eligibility_verifier=SimpleNamespace(verify=lambda *_a, **_k: "0x" + "77" * 32),
    )
    resp = TestClient(make_app(engine)).post(
        "/work-seat",
        json={
            "agent": "0x000000000000000000000000000000000000dEaD",
            "entitlement": {
                "purpose": "ai-agent-lottery-work-seat-v1",
                "hub_url": "https://peer.example",
                "agent_id": "agent-7",
                "participant_id": "0x" + "77" * 32,
                "wallet": "0x000000000000000000000000000000000000dEaD",
                "issued_at": now,
                "expires_at": now + 300,
                "nonce": "n",
                "signature": {},
            },
        },
    )
    assert resp.status_code == 409, resp.text
    assert "different wallet" in resp.json()["detail"]

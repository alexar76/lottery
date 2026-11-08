"""Finite actual-main controls; all signing uses public synthetic Anvil keys, no RPC."""

from __future__ import annotations
from types import SimpleNamespace
import pytest
from eth_account import Account
from web3 import Web3 as RealWeb3
import ailottery_agent.__main__ as current


class StopFinite(BaseException):
    pass


def _run_main(monkeypatch, module, case):
    Account.enable_unaudited_hdwallet_features()
    account = Account.from_mnemonic(
        " ".join(["test"] * 11 + ["junk"]), account_path="m/44'/60'/0'/0/1"
    )
    address = RealWeb3.to_checksum_address("0x" + "12" * 20)
    state = SimpleNamespace(tick=0, sent=[], built=None)

    def rid():
        return 7 if case != "retry" or state.tick < 7 else 8

    def round_value(round_id):
        row = [0] * 16
        row[0] = 1
        row[2] = 10000
        row[12] = 8 * 10**15
        row[13] = account.address
        row[15] = False
        if case in ("refund", "refund_reverted", "work_seat") and state.tick >= 1:
            row[0] = 4
        if case == "claim" and state.tick >= 1:
            row[0] = 3
        return tuple(row)

    class View:
        def __init__(self, fn):
            self.fn = fn

        def call(self):
            return self.fn()

    class Tx:
        def __init__(self, name, round_id):
            self.name = name
            self.rid = round_id

        def build_transaction(self, values):
            state.built = {"name": self.name, "rid": self.rid}
            return dict(values, to=address, data="0x")

    lottery = SimpleNamespace(address=address)
    lottery.functions = SimpleNamespace(
        currentRoundId=lambda: View(rid),
        getRound=lambda r: View(lambda: round_value(r)),
        paidTicketsEnabled=lambda: View(lambda: case != "work_seat"),
        workSeated=lambda r, a: View(lambda: True),
        ticketPrice=lambda: View(lambda: 10**15),
        buyTickets=lambda r, n: Tx("buyTickets", r),
        buyTicketsWithVoucher=lambda r, *a: Tx("buyTicketsWithVoucher", r),
        enterFromWork=lambda r, *a: Tx("enterFromWork", r),
        refund=lambda r: Tx("refund", r),
        claimPrize=lambda r: Tx("claimPrize", r),
    )

    class Eth:
        chain_id = 31337
        gas_price = 1
        accounts = []

        def contract(self, **kwargs):
            return lottery

        def get_block(self, *args):
            return {"timestamp": 100}

        def get_transaction_count(self, *args):
            return len(state.sent)

        def send_raw_transaction(self, raw):
            assert Account.recover_transaction(raw) == account.address
            state.sent.append(dict(state.built))
            return RealWeb3.keccak(raw)

        def wait_for_transaction_receipt(self, *args, **kwargs):
            last = state.sent[-1]
            failed = (case == "retry" and last["rid"] == 7) or (
                case == "refund_reverted" and last["name"] == "refund"
            )
            return {"status": 0 if failed else 1}

    class Factory:
        HTTPProvider = staticmethod(lambda rpc, **kw: SimpleNamespace(endpoint_uri=rpc))
        to_checksum_address = staticmethod(RealWeb3.to_checksum_address)
        to_hex = staticmethod(RealWeb3.to_hex)

        def __new__(cls, provider):
            return SimpleNamespace(
                eth=Eth(), provider=provider, is_connected=lambda: True
            )

    monkeypatch.setattr(module, "Web3", Factory)

    def sleep(_):
        state.tick += 1
        if state.tick >= 14:
            raise StopFinite()

    monkeypatch.setattr(module, "time", SimpleNamespace(sleep=sleep))
    for key, value in {
        "AGENT_KEY": account.key.hex(),
        "RPC_URL": "http://127.0.0.1:18545",
        "CHAIN_ID": "31337",
        "LOTTERY_ADDRESS": address,
        "RELAYER_URL": "",
        "USE_VOUCHER": "0",
        "POLL": "0",
        "TICKETS": "2",
        "HOME_HUB_URL": "",
        "HUB_AGENT_ID": "",
        "HUB_AGENT_TOKEN": "",
    }.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(StopFinite):
        module.main()
    return state


def test_actual_main_status_zero_is_not_entry_three_attempts_then_new_round(
    monkeypatch, capsys
):
    state = _run_main(monkeypatch, current, "retry")
    output = capsys.readouterr().out
    assert state.sent == [{"name": "buyTickets", "rid": 7}] * 3 + [
        {"name": "buyTickets", "rid": 8}
    ]
    assert "round 7 — bought" not in output
    assert output.count("round 8 — bought") == 1
    assert output.count("could not enter") == 3
    assert "waiting for the next round" in output


@pytest.mark.parametrize(
    "case,word",
    [
        ("refund", "tickets refunded"),
        ("refund_reverted", "refund reverted"),
        ("claim", "claimed"),
    ],
)
def test_actual_main_follow_up_is_done_once_across_later_polls(
    monkeypatch, capsys, case, word
):
    state = _run_main(monkeypatch, current, case)
    output = capsys.readouterr().out
    action = "claimPrize" if case == "claim" else "refund"
    assert state.sent == [{"name": "buyTickets", "rid": 7}, {"name": action, "rid": 7}]
    assert output.count(word) == 1


def test_actual_main_does_not_refund_a_work_seat(monkeypatch, capsys):
    state = _run_main(monkeypatch, current, "work_seat")
    output = capsys.readouterr().out
    assert state.sent == []
    assert "refunded" not in output

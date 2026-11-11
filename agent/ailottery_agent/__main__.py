"""An autonomous lottery agent loop.

Env:
  RPC_URL, CHAIN_ID, AGENT_KEY          — chain + identity
  LOTTERY_ADDRESS or LOTTERY_ADDRESS_FILE
  RELAYER_URL                           — work-seat signatures / reputation vouchers
  HOME_HUB_URL, HUB_AGENT_ID, HUB_AGENT_TOKEN — federated LIVE eligibility
  TICKETS (default 2), POLL (default 3s), USE_VOUCHER (default 1)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx
from eth_account import Account
from web3 import Web3
from web3.exceptions import ContractLogicError

from .dev_key_safety import require_signing_chain

ABI = [
    {"type": "function", "name": "currentRoundId", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "ticketPrice", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "participantsCount", "stateMutability": "view",
     "inputs": [{"type": "uint256"}], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "paidTicketsEnabled", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "bool"}]},
    {"type": "function", "name": "workSeated", "stateMutability": "view",
     "inputs": [{"name": "roundId", "type": "uint256"}, {"name": "agent", "type": "address"}],
     "outputs": [{"type": "bool"}]},
    {"type": "function", "name": "enterFromWork", "stateMutability": "nonpayable",
     "inputs": [{"name": "roundId", "type": "uint256"},
                {"name": "participantId", "type": "bytes32"},
                {"name": "weightBps", "type": "uint16"}, {"name": "expiry", "type": "uint64"},
                {"name": "sig", "type": "bytes"}], "outputs": []},
    {"type": "function", "name": "buyTickets", "stateMutability": "payable",
     "inputs": [{"name": "roundId", "type": "uint256"}, {"name": "count", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "buyTicketsWithVoucher", "stateMutability": "payable",
     "inputs": [{"name": "roundId", "type": "uint256"}, {"name": "count", "type": "uint256"},
                {"name": "repBonusBps", "type": "uint16"}, {"name": "expiry", "type": "uint64"},
                {"name": "sig", "type": "bytes"}], "outputs": []},
    {"type": "function", "name": "claimPrize", "stateMutability": "nonpayable",
     "inputs": [{"name": "roundId", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "refund", "stateMutability": "nonpayable",
     "inputs": [{"name": "roundId", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "paidBy", "stateMutability": "view",
     "inputs": [{"type": "uint256"}, {"type": "address"}], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "getRound", "stateMutability": "view", "inputs": [{"type": "uint256"}],
     "outputs": [{"type": "tuple", "components": [
         {"name": "status", "type": "uint8"}, {"name": "openedAt", "type": "uint64"},
         {"name": "entriesClose", "type": "uint64"}, {"name": "closedAt", "type": "uint64"},
         {"name": "sPrizeBps", "type": "uint16"}, {"name": "sOpexBps", "type": "uint16"},
         {"name": "sOperatorBps", "type": "uint16"}, {"name": "seedBlock", "type": "uint256"},
         {"name": "seedCommitment", "type": "bytes32"}, {"name": "ticketRevenue", "type": "uint256"},
         {"name": "funding", "type": "uint256"}, {"name": "totalWeight", "type": "uint256"},
         {"name": "prizePool", "type": "uint256"}, {"name": "winner", "type": "address"},
         {"name": "randomWord", "type": "uint256"}, {"name": "prizeClaimed", "type": "bool"}]}]},
]

STATUS_OPEN, STATUS_DRAWING, STATUS_SETTLED, STATUS_CANCELLED = 1, 2, 3, 4

#: Attempts at entering one round before the agent waits for the next one. Each failed
#: attempt can be a mined, reverted transaction; retrying it every POLL seconds for the
#: whole entry window only fills the chain with failures.
MAX_ENTRY_TRIES = 3

#: A claim or refund that reverts is retried, with backoff, while the contract still owes it.
#: Giving up after one revert abandoned the prize or the refund for good (audit 2026-11-11,
#: satellites-5); a revert can be transient (gas, nonce, a node behind).
MAX_FOLLOW_TRIES = 5
FOLLOW_BACKOFF_S = 60

#: Rounds re-read at start: the agent's sets live in memory, and a restart between buying
#: and the draw used to forget a round it then won (or that was cancelled).
RECOVER_LOOKBACK = 200


class TxReverted(RuntimeError):
    """The transaction was mined and reverted (receipt status 0)."""


def _say(message: str) -> None:
    print(message, flush=True)


def _reverted_without_data(exc: ContractLogicError) -> bool:
    return getattr(exc, "data", None) in (None, "", "0x", b"")


def paid_door_open(lottery) -> bool:
    """Whether `buyTickets` is the way into a round on this contract.

    `paidTicketsEnabled` came with the 2026-09-10 contract, where an unpaid work seat
    is the default door. A contract deployed before that has no such getter: the call
    reverts with no data, and `buyTickets` is its only door. The relayer reads it the
    same way (`ChainClient.paid_tickets_enabled`). A revert that carries data, or a
    transport error, is something else and is raised.
    """
    try:
        return bool(lottery.functions.paidTicketsEnabled().call())
    except ContractLogicError as exc:
        if _reverted_without_data(exc):
            return True
        raise


def paid_into(lottery, rid, address) -> int:
    """What the contract records this agent paid into round `rid` (0 when nothing).

    A contract fake or build without the getter answers 0; a transport error is raised, so
    a purchase is never repeated on a guess.
    """
    getter = getattr(lottery.functions, "paidBy", None)
    if getter is None:
        return 0
    try:
        return int(getter(rid, address).call() or 0)
    except ContractLogicError as exc:
        if _reverted_without_data(exc):
            return 0
        raise


def enter_round(lottery, rid, *, address, tickets, send, fetch_voucher, fetch_work_seat,
                say=_say) -> bool:
    """Enter open round `rid` through the door the contract has. True when the agent paid."""
    if not paid_door_open(lottery):
        if lottery.functions.workSeated(rid, address).call():
            return False
        seat = fetch_work_seat(rid)
        if not seat.get("already_seated"):
            send(lottery.functions.enterFromWork(
                rid,
                bytes.fromhex(seat["participant_id"].removeprefix("0x")),
                int(seat["weight_bps"]),
                int(seat["expiry"]),
                bytes.fromhex(seat["signature"].removeprefix("0x")),
            ))
        say(f"agent: round {rid} — entered with a Hub work seat")
        return False
    # A purchase whose receipt timed out after the broadcast was mined anyway: the next poll
    # bought a second batch (satellites-5). The contract's own record decides.
    if paid_into(lottery, rid, address) > 0:
        say(f"agent: round {rid} — tickets already bought")
        return True
    price = lottery.functions.ticketPrice().call()
    v = fetch_voucher(rid)
    if v:
        try:
            send(lottery.functions.buyTicketsWithVoucher(
                rid, tickets, int(v["rep_bonus_bps"]), int(v["expiry"]),
                bytes.fromhex(v["signature"].removeprefix("0x"))), value=price * tickets)
            say(f"agent: round {rid} — bought {tickets} tickets (+{v['rep_bonus_bps']}bps rep)")
            return True
        except TxReverted as exc:
            say(f"agent: round {rid} — the voucher purchase reverted ({exc}); buying without it")
    send(lottery.functions.buyTickets(rid, tickets), value=price * tickets)
    say(f"agent: round {rid} — bought {tickets} tickets")
    return True


def follow_up(lottery, rid, *, address, paid, send, say=_say, state=None, now=time.time) -> bool:
    """Claim a won prize or take back a cancelled round's tickets.

    True once the round needs nothing more from the agent. A claim or refund that reverts
    is re-read: if the contract no longer owes it, the round is done; if it still does, it
    is retried with backoff up to MAX_FOLLOW_TRIES (``state`` carries the count between
    polls). One revert used to drop the prize or the refund for good.
    """
    st = state if state is not None else {}
    if st.get("next", 0.0) > now():
        return False
    r = lottery.functions.getRound(rid).call()
    status, prize, winner, claimed = r[0], r[12], r[13], r[15]
    if status == STATUS_SETTLED:
        if str(winner).lower() == str(address).lower() and not claimed:
            try:
                send(lottery.functions.claimPrize(rid))
                say(f"agent: 🏆 WON round {rid} — claimed {prize} wei")
            except TxReverted as exc:
                return _after_revert(st, rid, "claimPrize", exc, say, now,
                                     owed=lambda: not lottery.functions.getRound(rid).call()[15])
        return True
    if status == STATUS_CANCELLED:
        if paid:
            try:
                send(lottery.functions.refund(rid))
                say(f"agent: round {rid} was cancelled — tickets refunded")
            except TxReverted as exc:
                return _after_revert(st, rid, "refund", exc, say, now,
                                     owed=lambda: paid_into(lottery, rid, address) > 0)
        return True
    return False


def _after_revert(st: dict, rid, what: str, exc, say, now, *, owed) -> bool:
    st["tries"] = st.get("tries", 0) + 1
    try:
        still = owed()
    except Exception:  # noqa: BLE001 — unknown: keep it
        still = True
    if not still:
        say(f"agent: round {rid} — {what} reverted ({exc}); nothing is owed any more")
        return True
    if st["tries"] >= MAX_FOLLOW_TRIES:
        say(f"agent: round {rid} — {what} reverted {st['tries']} times ({exc}); giving up")
        return True
    wait = FOLLOW_BACKOFF_S * 2 ** (st["tries"] - 1)
    st["next"] = now() + wait
    label = "refund reverted" if what == "refund" else f"{what} reverted"
    say(f"agent: round {rid} — {label} ({exc}); retrying in {wait} s")
    return False


def recover_rounds(lottery, address, *, lookback=RECOVER_LOOKBACK,
                   now: int | None = None) -> tuple[set[int], set[int]]:
    """Rounds the chain says this agent is still owed something in, or may be: (to follow, paid).

    A round not yet drawn counts when the agent is in it (it paid, or holds a work seat) and
    the main loop can no longer reach it: Drawing, or Open past its entries (``now`` is the
    chain's time). A restart between buying and the draw is exactly the case to recover
    (review of 2026-11-11). An Open round still taking entries is the main loop's: its
    paid/work-seat checks find the agent's entry there.
    """
    follow: set[int] = set()
    paid: set[int] = set()
    current = int(lottery.functions.currentRoundId().call() or 0)
    for rid in range(max(1, current - lookback), current + 1):
        r = lottery.functions.getRound(rid).call()
        status, winner, claimed = r[0], r[13], r[15]
        if status == STATUS_SETTLED and str(winner).lower() == str(address).lower() and not claimed:
            follow.add(rid)
        elif status == STATUS_CANCELLED and paid_into(lottery, rid, address) > 0:
            follow.add(rid)
            paid.add(rid)
        elif status == STATUS_DRAWING or (status == STATUS_OPEN and now is not None and now > int(r[2])):
            if paid_into(lottery, rid, address) > 0:
                follow.add(rid)
                paid.add(rid)
            elif _work_seated(lottery, rid, address):
                follow.add(rid)
    return follow, paid


def _work_seated(lottery, rid, address) -> bool:
    getter = getattr(lottery.functions, "workSeated", None)
    if getter is None:
        return False
    try:
        return bool(getter(rid, address).call())
    except ContractLogicError:
        return False


def _addr() -> str:
    a = os.getenv("LOTTERY_ADDRESS", "")
    if a:
        return a
    p = Path(os.getenv("LOTTERY_ADDRESS_FILE", "/shared/lottery.address"))
    for _ in range(90):
        if p.exists() and p.read_text().strip():
            return p.read_text().strip()
        print("agent: waiting for lottery address…", flush=True)
        time.sleep(2)
    sys.exit("agent: no lottery address")


def main() -> None:
    rpc = os.getenv("RPC_URL", "http://chain:8545")
    chain_id = int(os.getenv("CHAIN_ID", "31337"))
    key = os.getenv("AGENT_KEY") or sys.exit("agent: set AGENT_KEY")
    relayer = os.getenv("RELAYER_URL", "").rstrip("/")
    tickets = int(os.getenv("TICKETS", "2"))
    poll = float(os.getenv("POLL", "3"))
    use_voucher = os.getenv("USE_VOUCHER", "1").lower() in ("1", "true", "yes")
    home_hub = os.getenv("HOME_HUB_URL", "").rstrip("/")
    hub_agent_id = os.getenv("HUB_AGENT_ID", "").strip()
    hub_agent_token = os.getenv("HUB_AGENT_TOKEN", "").strip()

    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 30, "allow_redirects": False}))
    require_signing_chain(w3, chain_id, [rpc], key)
    acct = Account.from_key(key)
    lottery = w3.eth.contract(address=Web3.to_checksum_address(_addr()), abi=ABI)
    print(f"agent {acct.address} on {lottery.address} (relayer={relayer or 'none'})", flush=True)

    def send(fn, value=0):
        require_signing_chain(w3, chain_id, [rpc], key)
        tx = fn.build_transaction({
            "from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
            "value": value, "chainId": chain_id, "gas": 1_500_000, "gasPrice": w3.eth.gas_price})
        if int(tx.get("chainId", -1)) != chain_id:
            raise RuntimeError("Transaction builder changed the configured signing chain ID")
        require_signing_chain(w3, chain_id, [rpc], key)
        signed = acct.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        require_signing_chain(w3, chain_id, [rpc], key)
        h = w3.eth.send_raw_transaction(raw)
        receipt = w3.eth.wait_for_transaction_receipt(h, timeout=120)
        if receipt["status"] != 1:
            raise TxReverted(f"transaction {Web3.to_hex(h)} reverted")
        return receipt

    def fetch_voucher(rid):
        if not (relayer and use_voucher):
            return None
        try:
            r = httpx.post(f"{relayer}/voucher", json={"agent": acct.address, "round_id": rid}, timeout=8)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            print(f"agent: voucher unavailable ({exc})", flush=True)
            return None

    def fetch_work_seat(rid):
        if not relayer:
            raise RuntimeError("RELAYER_URL is required while paid tickets are off")
        entitlement = None
        configured = (bool(home_hub), bool(hub_agent_id), bool(hub_agent_token))
        if any(configured) and not all(configured):
            raise RuntimeError(
                "set HOME_HUB_URL, HUB_AGENT_ID, and HUB_AGENT_TOKEN together"
            )
        if all(configured):
            proof = httpx.post(
                f"{home_hub}/ai-market/v2/lottery/work-seat-entitlement",
                json={"agent_id": hub_agent_id, "wallet": acct.address},
                headers={"Authorization": f"Bearer {hub_agent_token}"},
                timeout=8,
            )
            proof.raise_for_status()
            entitlement = proof.json().get("entitlement")
            if not entitlement:
                raise RuntimeError("home Hub returned no lottery entitlement")
        payload = {"agent": acct.address, "round_id": rid}
        if entitlement is not None:
            payload["entitlement"] = entitlement
        seat = httpx.post(f"{relayer}/work-seat", json=payload, timeout=8)
        seat.raise_for_status()
        return seat.json()

    entered: set[int] = set()
    paid: set[int] = set()
    done: set[int] = set()
    tries: dict[int, int] = {}
    follow_state: dict[int, dict] = {}
    try:
        owed, owed_paid = recover_rounds(lottery, acct.address,
                                         now=int(w3.eth.get_block("latest")["timestamp"]))
        entered |= owed
        paid |= owed_paid
        if owed:
            _say(f"agent: still owed something in rounds {sorted(owed)} — following them up")
    except Exception as exc:  # noqa: BLE001
        _say(f"agent: could not re-read earlier rounds ({exc})")
    while True:
        try:
            rid = lottery.functions.currentRoundId().call()
            if rid and rid not in entered and tries.get(rid, 0) < MAX_ENTRY_TRIES:
                r = lottery.functions.getRound(rid).call()
                status, entries_close = r[0], r[2]
                if status == STATUS_OPEN and w3.eth.get_block("latest")["timestamp"] <= entries_close:
                    try:
                        if enter_round(lottery, rid, address=acct.address, tickets=tickets, send=send,
                                       fetch_voucher=fetch_voucher, fetch_work_seat=fetch_work_seat):
                            paid.add(rid)
                        entered.add(rid)
                    except Exception as exc:
                        tries[rid] = tries.get(rid, 0) + 1
                        left = MAX_ENTRY_TRIES - tries[rid]
                        _say(f"agent: round {rid} — could not enter ({exc}); "
                             + (f"{left} more tries" if left else "waiting for the next round"))
            # claim any won prize, take back cancelled rounds' tickets
            for r_id in sorted(entered - done):
                if follow_up(lottery, r_id, address=acct.address, paid=r_id in paid, send=send,
                             state=follow_state.setdefault(r_id, {})):
                    done.add(r_id)
        except Exception as exc:
            _say(f"agent: {exc}")
        time.sleep(poll)


if __name__ == "__main__":
    main()

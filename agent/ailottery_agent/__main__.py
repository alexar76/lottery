"""An autonomous lottery agent loop.

Env:
  RPC_URL, CHAIN_ID, AGENT_KEY          — chain + identity
  LOTTERY_ADDRESS or LOTTERY_ADDRESS_FILE
  RELAYER_URL                           — for signed reputation vouchers (optional)
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

ABI = [
    {"type": "function", "name": "currentRoundId", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "ticketPrice", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "participantsCount", "stateMutability": "view",
     "inputs": [{"type": "uint256"}], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "buyTickets", "stateMutability": "payable",
     "inputs": [{"name": "roundId", "type": "uint256"}, {"name": "count", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "buyTicketsWithVoucher", "stateMutability": "payable",
     "inputs": [{"name": "roundId", "type": "uint256"}, {"name": "count", "type": "uint256"},
                {"name": "repBonusBps", "type": "uint16"}, {"name": "expiry", "type": "uint64"},
                {"name": "sig", "type": "bytes"}], "outputs": []},
    {"type": "function", "name": "claimPrize", "stateMutability": "nonpayable",
     "inputs": [{"name": "roundId", "type": "uint256"}], "outputs": []},
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

STATUS_OPEN, STATUS_SETTLED = 1, 3


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

    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 30}))
    acct = Account.from_key(key)
    lottery = w3.eth.contract(address=Web3.to_checksum_address(_addr()), abi=ABI)
    print(f"agent {acct.address} on {lottery.address} (relayer={relayer or 'none'})", flush=True)

    def send(fn, value=0):
        tx = fn.build_transaction({
            "from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
            "value": value, "chainId": chain_id, "gas": 1_500_000, "gasPrice": w3.eth.gas_price})
        signed = acct.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        h = w3.eth.send_raw_transaction(raw)
        return w3.eth.wait_for_transaction_receipt(h, timeout=120)

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

    entered: set[int] = set()
    claimed: set[int] = set()
    while True:
        try:
            rid = lottery.functions.currentRoundId().call()
            if rid and rid not in entered:
                r = lottery.functions.getRound(rid).call()
                status, entries_close = r[0], r[2]
                if status == STATUS_OPEN and w3.eth.get_block("latest")["timestamp"] <= entries_close:
                    price = lottery.functions.ticketPrice().call()
                    v = fetch_voucher(rid)
                    if v:
                        send(lottery.functions.buyTicketsWithVoucher(
                            rid, tickets, int(v["rep_bonus_bps"]), int(v["expiry"]),
                            bytes.fromhex(v["signature"].removeprefix("0x"))), value=price * tickets)
                        print(f"agent: round {rid} — bought {tickets} tickets (+{v['rep_bonus_bps']}bps rep)", flush=True)
                    else:
                        send(lottery.functions.buyTickets(rid, tickets), value=price * tickets)
                        print(f"agent: round {rid} — bought {tickets} tickets", flush=True)
                    entered.add(rid)
            # claim any settled win
            for r_id in list(entered):
                if r_id in claimed:
                    continue
                rr = lottery.functions.getRound(r_id).call()
                if rr[0] == STATUS_SETTLED and rr[13] == acct.address and not rr[15]:
                    send(lottery.functions.claimPrize(r_id))
                    print(f"agent: 🏆 WON round {r_id} — claimed {rr[12]} wei", flush=True)
                    claimed.add(r_id)
                elif rr[0] in (STATUS_SETTLED, 4):  # settled/cancelled → stop tracking
                    claimed.add(r_id)
        except Exception as exc:
            print(f"agent: {exc}", flush=True)
        time.sleep(poll)


if __name__ == "__main__":
    main()

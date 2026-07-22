"""Thin web3 wrapper: contract calls/txs, EIP-712 signing, and demo time-warp."""
from __future__ import annotations

from typing import Any, Optional

from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3

from .abi import (
    DRAW_BEACON_TYPE,
    EIP712_DOMAIN_NAME,
    EIP712_DOMAIN_VERSION,
    LOTTERY_ABI,
    REP_VOUCHER_TYPE,
    ROUND_FIELDS,
)
from .log import get_logger

log = get_logger("chain")


class Chain:
    def __init__(self, rpc_url: str, chain_id: int, lottery_address: str):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        self.chain_id = chain_id
        self.address = Web3.to_checksum_address(lottery_address)
        self.contract = self.w3.eth.contract(address=self.address, abi=LOTTERY_ABI)

    # ── identities ────────────────────────────────────────────────────────────
    def acct(self, private_key: str):
        return Account.from_key(private_key)

    # ── reads ───────────────────────────────────────────────────────────────
    def current_round_id(self) -> int:
        return self.contract.functions.currentRoundId().call()

    def ticket_price(self) -> int:
        return self.contract.functions.ticketPrice().call()

    def onchain_vdf(self) -> bool:
        try:
            return bool(self.contract.functions.onchainVdf().call())
        except Exception:
            return False

    def min_draw_delay(self) -> int:
        return self.contract.functions.minDrawDelay().call()

    def participants_count(self, rid: int) -> int:
        return self.contract.functions.participantsCount(rid).call()

    def get_round(self, rid: int) -> dict:
        raw = self.contract.functions.getRound(rid).call()
        return dict(zip(ROUND_FIELDS, raw))

    def economy(self) -> dict:
        raw = self.contract.functions.economy().call()
        keys = ["round", "prizesPaid", "opexTotal", "fundingTotal",
                "ticketRevenue", "opexAvailable", "operatorAvailable"]
        return dict(zip(keys, raw))

    def block(self) -> dict:
        b = self.w3.eth.get_block("latest")
        return {"number": b["number"], "timestamp": b["timestamp"]}

    def blockhash(self, number: int) -> bytes:
        return bytes(self.w3.eth.get_block(number)["hash"])

    def balance(self, addr: str) -> int:
        return self.w3.eth.get_balance(Web3.to_checksum_address(addr))

    # ── writes ────────────────────────────────────────────────────────────────
    def transfer(self, from_key: str, to: str, amount_wei: int) -> dict:
        """Plain ETH transfer — used in UNI to fund each agent's self-custodial wallet."""
        acct = Account.from_key(from_key)
        tx = {
            "from": acct.address,
            "to": Web3.to_checksum_address(to),
            "value": int(amount_wei),
            "nonce": self.w3.eth.get_transaction_count(acct.address, "pending"),
            "chainId": self.chain_id,
            "gas": 21_000,
            "gasPrice": self.w3.eth.gas_price,
        }
        signed = acct.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        tx_hash = self.w3.eth.send_raw_transaction(raw)
        rcpt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if rcpt["status"] != 1:
            raise RuntimeError(f"funding tx reverted: {tx_hash.hex()}")
        return dict(rcpt)

    def send(self, fn, private_key: str, value: int = 0, gas: Optional[int] = None) -> dict:
        acct = Account.from_key(private_key)
        tx = fn.build_transaction({
            "from": acct.address,
            "nonce": self.w3.eth.get_transaction_count(acct.address, "pending"),
            "value": value,
            "chainId": self.chain_id,
            "gas": gas or 3_000_000,
            # legacy gas price keeps anvil + most testnets happy without EIP-1559 estimation
            "gasPrice": self.w3.eth.gas_price,
        })
        signed = acct.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        tx_hash = self.w3.eth.send_raw_transaction(raw)
        rcpt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if rcpt["status"] != 1:
            raise RuntimeError(f"tx reverted: {tx_hash.hex()}")
        return dict(rcpt)

    # ── EIP-712 signing ─────────────────────────────────────────────────────
    def _domain(self) -> dict:
        return {
            "name": EIP712_DOMAIN_NAME,
            "version": EIP712_DOMAIN_VERSION,
            "chainId": self.chain_id,
            "verifyingContract": self.address,
        }

    def sign_beacon(self, private_key: str, round_id: int, platon_random: bytes,
                    vdf_t: int, proof_hash: bytes) -> bytes:
        typed = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "DrawBeacon": DRAW_BEACON_TYPE,
            },
            "primaryType": "DrawBeacon",
            "domain": self._domain(),
            "message": {
                "roundId": round_id,
                "platonRandom": platon_random,
                "vdfT": vdf_t,
                "proofHash": proof_hash,
            },
        }
        signable = encode_typed_data(full_message=typed)
        return Account.sign_message(signable, private_key=private_key).signature

    def sign_voucher(self, private_key: str, agent: str, round_id: int,
                     rep_bonus_bps: int, expiry: int) -> bytes:
        typed = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "ReputationVoucher": REP_VOUCHER_TYPE,
            },
            "primaryType": "ReputationVoucher",
            "domain": self._domain(),
            "message": {
                "agent": Web3.to_checksum_address(agent),
                "roundId": round_id,
                "repBonusBps": rep_bonus_bps,
                "expiry": expiry,
            },
        }
        signable = encode_typed_data(full_message=typed)
        return Account.sign_message(signable, private_key=private_key).signature

    # ── demo helpers (anvil) ──────────────────────────────────────────────────
    def fast_forward(self, seconds: int) -> None:
        """Warp anvil time and mine, so short windows pass without real waiting."""
        try:
            self.w3.provider.make_request("evm_increaseTime", [int(seconds)])
            self.w3.provider.make_request("evm_mine", [])
        except Exception as exc:  # not anvil → ignore, real time will elapse
            log.debug("fast_forward unsupported: %s", exc)

    def mine(self) -> None:
        try:
            self.w3.provider.make_request("evm_mine", [])
        except Exception:
            pass

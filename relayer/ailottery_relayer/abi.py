"""Hand-written minimal ABI for AIAgentLottery (only the parts the relayer calls)
plus the EIP-712 type definitions, kept byte-for-byte in sync with
lottery/contracts/src/AIAgentLottery.sol.

If the contract's external surface changes, update this file (and the relayer's
verification workflow will catch a drift).
"""
from __future__ import annotations

# Round struct field order — must match the Solidity `struct Round`.
ROUND_FIELDS = [
    "status", "openedAt", "entriesClose", "closedAt",
    "sPrizeBps", "sOpexBps", "sOperatorBps",
    "seedBlock", "seedCommitment", "ticketRevenue", "funding",
    "totalWeight", "prizePool", "winner", "randomWord", "prizeClaimed",
]

# economy() return tuple order.
ECONOMY_FIELDS = [
    "round", "prizesPaid", "opexTotal", "fundingTotal",
    "ticketRevenue", "opexAvailable", "operatorAvailable",
]

_ROUND_COMPONENTS = [
    {"name": "status", "type": "uint8"},
    {"name": "openedAt", "type": "uint64"},
    {"name": "entriesClose", "type": "uint64"},
    {"name": "closedAt", "type": "uint64"},
    {"name": "sPrizeBps", "type": "uint16"},
    {"name": "sOpexBps", "type": "uint16"},
    {"name": "sOperatorBps", "type": "uint16"},
    {"name": "seedBlock", "type": "uint256"},
    {"name": "seedCommitment", "type": "bytes32"},
    {"name": "ticketRevenue", "type": "uint256"},
    {"name": "funding", "type": "uint256"},
    {"name": "totalWeight", "type": "uint256"},
    {"name": "prizePool", "type": "uint256"},
    {"name": "winner", "type": "address"},
    {"name": "randomWord", "type": "uint256"},
    {"name": "prizeClaimed", "type": "bool"},
]

_VDF_COMPONENTS = [
    {"name": "seed", "type": "string"},
    {"name": "g", "type": "bytes"},
    {"name": "y", "type": "bytes"},
    {"name": "pi", "type": "bytes"},
    {"name": "l", "type": "bytes"},
    {"name": "N", "type": "bytes"},
    {"name": "T", "type": "uint256"},
]


def _fn(name, inputs, outputs=None, mutability="nonpayable"):
    return {
        "type": "function",
        "name": name,
        "stateMutability": mutability,
        "inputs": inputs,
        "outputs": outputs or [],
    }


def _ev(name, inputs):
    return {"type": "event", "name": name, "anonymous": False, "inputs": inputs}


LOTTERY_ABI = [
    _fn("openRound", [], [{"name": "roundId", "type": "uint256"}]),
    _fn("buyTickets",
        [{"name": "roundId", "type": "uint256"}, {"name": "count", "type": "uint256"}],
        mutability="payable"),
    _fn("buyTicketsWithVoucher",
        [{"name": "roundId", "type": "uint256"}, {"name": "count", "type": "uint256"},
         {"name": "repBonusBps", "type": "uint16"}, {"name": "expiry", "type": "uint64"},
         {"name": "sig", "type": "bytes"}],
        mutability="payable"),
    _fn("fund",
        [{"name": "roundId", "type": "uint256"}, {"name": "amount", "type": "uint256"}],
        mutability="payable"),
    _fn("closeEntries",
        [{"name": "roundId", "type": "uint256"}, {"name": "seedCommitment", "type": "bytes32"}]),
    _fn("reseed", [{"name": "roundId", "type": "uint256"}]),
    _fn("fulfillDraw",
        [{"name": "roundId", "type": "uint256"}, {"name": "platonRandom", "type": "bytes32"},
         {"name": "vdfT", "type": "uint256"}, {"name": "signerSig", "type": "bytes"},
         {"name": "vdf", "type": "tuple", "components": _VDF_COMPONENTS}]),
    _fn("claimPrize", [{"name": "roundId", "type": "uint256"}]),
    _fn("withdrawOpex",
        [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}]),
    _fn("withdrawOperatorFee",
        [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}]),
    _fn("cancelRound", [{"name": "roundId", "type": "uint256"}]),
    _fn("getRound", [{"name": "roundId", "type": "uint256"}],
        [{"name": "", "type": "tuple", "components": _ROUND_COMPONENTS}], "view"),
    _fn("participantsCount", [{"name": "roundId", "type": "uint256"}],
        [{"name": "", "type": "uint256"}], "view"),
    _fn("economy", [], [{"name": n, "type": "uint256"} for n in ECONOMY_FIELDS], "view"),
    _fn("currentRoundId", [], [{"name": "", "type": "uint256"}], "view"),
    _fn("ticketPrice", [], [{"name": "", "type": "uint256"}], "view"),
    _fn("opexAccrued", [], [{"name": "", "type": "uint256"}], "view"),
    _fn("operatorAccrued", [], [{"name": "", "type": "uint256"}], "view"),
    _fn("onchainVdf", [], [{"name": "", "type": "bool"}], "view"),
    _fn("minDrawDelay", [], [{"name": "", "type": "uint64"}], "view"),
    _fn("entryWindow", [], [{"name": "", "type": "uint64"}], "view"),
    _fn("paused", [], [{"name": "", "type": "bool"}], "view"),
    _ev("RoundOpened",
        [{"name": "roundId", "type": "uint256", "indexed": True},
         {"name": "entriesClose", "type": "uint64", "indexed": False}]),
    _ev("TicketsBought",
        [{"name": "roundId", "type": "uint256", "indexed": True},
         {"name": "agent", "type": "address", "indexed": True},
         {"name": "count", "type": "uint256", "indexed": False},
         {"name": "weight", "type": "uint256", "indexed": False},
         {"name": "paid", "type": "uint256", "indexed": False}]),
    _ev("Funded",
        [{"name": "roundId", "type": "uint256", "indexed": True},
         {"name": "benefactor", "type": "address", "indexed": True},
         {"name": "amount", "type": "uint256", "indexed": False}]),
    _ev("EntriesClosed",
        [{"name": "roundId", "type": "uint256", "indexed": True},
         {"name": "seedBlock", "type": "uint256", "indexed": False}]),
    _ev("Drawn",
        [{"name": "roundId", "type": "uint256", "indexed": True},
         {"name": "winner", "type": "address", "indexed": True},
         {"name": "prize", "type": "uint256", "indexed": False},
         {"name": "opex", "type": "uint256", "indexed": False},
         {"name": "operatorFee", "type": "uint256", "indexed": False},
         {"name": "randomWord", "type": "uint256", "indexed": False}]),
    _ev("PrizeClaimed",
        [{"name": "roundId", "type": "uint256", "indexed": True},
         {"name": "winner", "type": "address", "indexed": True},
         {"name": "amount", "type": "uint256", "indexed": False}]),
]

# ── EIP-712 ──────────────────────────────────────────────────────────────────
EIP712_DOMAIN_NAME = "AIAgentLottery"
EIP712_DOMAIN_VERSION = "1"

DRAW_BEACON_TYPE = [
    {"name": "roundId", "type": "uint256"},
    {"name": "platonRandom", "type": "bytes32"},
    {"name": "vdfT", "type": "uint256"},
    {"name": "proofHash", "type": "bytes32"},
]

REP_VOUCHER_TYPE = [
    {"name": "agent", "type": "address"},
    {"name": "roundId", "type": "uint256"},
    {"name": "repBonusBps", "type": "uint16"},
    {"name": "expiry", "type": "uint64"},
]

# abi.encode types for the beacon's proofHash = keccak256(abi.encode(g,y,pi,l,N,T,keccak(seed))).
PROOF_HASH_ABI_TYPES = ["bytes", "bytes", "bytes", "bytes", "bytes", "uint256", "bytes32"]

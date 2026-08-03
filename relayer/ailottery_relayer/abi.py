"""Hand-written minimal ABI for AIAgentLottery (the parts the relayer calls, plus
every event the contract declares) and the EIP-712 type definitions, kept
byte-for-byte in sync with lottery/contracts/src/AIAgentLottery.sol.

A hand-written mirror silently rots: a changed parameter list re-encodes to a
different selector, so the call does not fail loudly at the relayer — it reverts
on-chain, and a changed event re-hashes to a different topic0, so a log filter
matches nothing while looking healthy. `tests/test_abi_contract_agreement.py`
therefore derives every selector, topic0 and tuple layout from the compiled
Foundry artifact (and the event set straight from the .sol source) and asserts
this file agrees, so that drift can never come back unnoticed.
"""
from __future__ import annotations

from web3 import Web3

# ── contract constants mirrored from AIAgentLottery.sol ──────────────────────
# The relayer needs these to reason about the settle window BEFORE it spends an
# oracle call: whether a pinned seed hash is still readable on-chain, whether a
# rescue is permitted yet, and how much rescue budget a round has left. Pinned
# against the source by the ABI-agreement test.
SEED_BLOCK_OFFSET = 4
BLOCKHASH_WINDOW = 256
SEED_LIFETIME_BLOCKS = SEED_BLOCK_OFFSET + BLOCKHASH_WINDOW
DRAW_DELAY_HEADROOM = 2
MAX_RESEEDS = 2
RESEED_COOLDOWN = 60 * 60           # 1 hours
STALL_CANCEL_DELAY = 7 * 24 * 3600  # 7 days
UNCLAIMED_PRIZE_TTL = 180 * 24 * 3600  # 180 days
DEFAULT_SECONDS_PER_BLOCK = 2
MAX_SECONDS_PER_BLOCK = 60

# Round.status enum (Solidity `enum Status`), used to decide what a round still
# allows instead of hard-coding integers at each call site.
STATUS_NONE = 0
STATUS_OPEN = 1
STATUS_DRAWING = 2
STATUS_SETTLED = 3
STATUS_CANCELLED = 4


def max_draw_delay(seconds_per_block: int) -> int:
    """Mirror of AIAgentLottery._maxDrawDelay — the largest draw delay the
    block-denominated settle window can satisfy at a given block time."""
    return (SEED_LIFETIME_BLOCKS * int(seconds_per_block)) // DRAW_DELAY_HEADROOM

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
    # RESCUE, not a re-roll: the contract now demands a NEVER-BEFORE-USED
    # randomness commitment for the rescued round, so this takes the fresh
    # beacon's keccak256(platonRandom) as a second argument. Declaring the old
    # one-argument form here produced a different selector — every rescue call
    # would have reverted on-chain.
    _fn("reseed",
        [{"name": "roundId", "type": "uint256"},
         {"name": "newSeedCommitment", "type": "bytes32"}]),
    _fn("fulfillDraw",
        [{"name": "roundId", "type": "uint256"}, {"name": "platonRandom", "type": "bytes32"},
         {"name": "vdfT", "type": "uint256"}, {"name": "signerSig", "type": "bytes"},
         {"name": "vdf", "type": "tuple", "components": _VDF_COMPONENTS}]),
    _fn("claimPrize", [{"name": "roundId", "type": "uint256"}]),
    # Permissionless recycling of a prize the winner never claimed
    # (UNCLAIMED_PRIZE_TTL): the funds re-enter a later round's pool instead of
    # being stranded. Nobody can withdraw them.
    _fn("forfeitUnclaimedPrize", [{"name": "roundId", "type": "uint256"}]),
    _fn("refund", [{"name": "roundId", "type": "uint256"}]),
    _fn("withdrawOpex",
        [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}]),
    _fn("withdrawOperatorFee",
        [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}]),
    _fn("cancelRound", [{"name": "roundId", "type": "uint256"}]),
    # Permissionless escape hatch after STALL_CANCEL_DELAY — the only cancel a
    # non-operator can drive, and the recovery path when cancelRound is refused
    # because the round is still settleable.
    _fn("cancelStalledRound", [{"name": "roundId", "type": "uint256"}]),
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
    # The wall-clock draw bound is DERIVED from the chain's declared block time,
    # not a literal — the relayer reads both so it can compare the declaration
    # against the block time it actually observes (see economy_draw.preflight).
    _fn("secondsPerBlock", [], [{"name": "", "type": "uint64"}], "view"),
    _fn("maxDrawDelay", [], [{"name": "", "type": "uint64"}], "view"),
    _fn("reseedCount", [{"name": "", "type": "uint256"}],
        [{"name": "", "type": "uint16"}], "view"),
    _fn("settledAt", [{"name": "", "type": "uint256"}],
        [{"name": "", "type": "uint64"}], "view"),
    _fn("prizeRolledIn", [{"name": "", "type": "uint256"}],
        [{"name": "", "type": "uint256"}], "view"),
    _fn("unclaimedPool", [], [{"name": "", "type": "uint256"}], "view"),
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
    _ev("RoundCancelled",
        [{"name": "roundId", "type": "uint256", "indexed": True}]),
    _ev("Refunded",
        [{"name": "roundId", "type": "uint256", "indexed": True},
         {"name": "agent", "type": "address", "indexed": True},
         {"name": "amount", "type": "uint256", "indexed": False}]),
    _ev("OpexWithdrawn",
        [{"name": "to", "type": "address", "indexed": True},
         {"name": "amount", "type": "uint256", "indexed": False}]),
    _ev("OperatorFeeWithdrawn",
        [{"name": "to", "type": "address", "indexed": True},
         {"name": "amount", "type": "uint256", "indexed": False}]),
    _ev("SplitsUpdated",
        [{"name": "prizeBps", "type": "uint16", "indexed": False},
         {"name": "opexBps", "type": "uint16", "indexed": False},
         {"name": "operatorBps", "type": "uint16", "indexed": False}]),
    # A rescue does NOT re-emit EntriesClosed (entries do not re-close): a
    # consumer that only knew EntriesClosed kept the stale seedBlock and would
    # read blockhash() of a block the round no longer uses.
    _ev("RoundReseeded",
        [{"name": "roundId", "type": "uint256", "indexed": True},
         {"name": "seedBlock", "type": "uint256", "indexed": False},
         {"name": "seedCommitment", "type": "bytes32", "indexed": False},
         {"name": "reseedCount", "type": "uint16", "indexed": False}]),
    _ev("PrizeForfeited",
        [{"name": "roundId", "type": "uint256", "indexed": True},
         {"name": "winner", "type": "address", "indexed": True},
         {"name": "amount", "type": "uint256", "indexed": False}]),
    _ev("UnclaimedPrizeRolledIn",
        [{"name": "roundId", "type": "uint256", "indexed": True},
         {"name": "amount", "type": "uint256", "indexed": False}]),
    _ev("BlockTimeUpdated",
        [{"name": "secondsPerBlock", "type": "uint64", "indexed": False},
         {"name": "maxDrawDelay", "type": "uint64", "indexed": False}]),
]


# ── log-decoding helpers ─────────────────────────────────────────────────────
def event_signature(name: str) -> str:
    """Canonical Solidity event signature, e.g. `EntriesClosed(uint256,uint256)`."""
    for entry in LOTTERY_ABI:
        if entry["type"] == "event" and entry["name"] == name:
            return f"{name}({','.join(i['type'] for i in entry['inputs'])})"
    raise KeyError(f"{name} is not declared in LOTTERY_ABI")


def event_topic0(name: str) -> bytes:
    """topic0 of an event as it appears in a receipt log."""
    return Web3.keccak(text=event_signature(name))

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

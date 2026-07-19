"""VDF proof + draw-beacon helpers.

Two paths, both faithful to AIAgentLottery._randomWord / _verifyBeacon:

  onchain_vdf = False (default, tested):
    the proof is EMPTY; the contract derives the random word from
    keccak256(baseSeed, block.prevrandao). The beacon still commits the
    (empty) proof hash so the signature binds the whole payload.

  onchain_vdf = True (trustless upgrade):
    the relayer feeds Chronos the seed string `_toHex(baseSeed)`, gets back a
    Wesolowski proof over the pinned modulus, and the contract verifies
    π^l·g^r ≡ y (mod N) on-chain. Requires Chronos to use the canonical modulus.
"""
from __future__ import annotations

from dataclasses import dataclass

from eth_abi import encode as abi_encode
from web3 import Web3

from .abi import PROOF_HASH_ABI_TYPES


@dataclass
class VdfProof:
    seed: str = ""
    g: bytes = b""
    y: bytes = b""
    pi: bytes = b""
    l: bytes = b""
    N: bytes = b""
    T: int = 0

    def as_tuple(self):
        # order must match abi._VDF_COMPONENTS / Solidity struct VdfProof
        return (self.seed, self.g, self.y, self.pi, self.l, self.N, self.T)

    def proof_hash(self) -> bytes:
        seed_hash = Web3.keccak(text=self.seed)
        return Web3.keccak(
            abi_encode(PROOF_HASH_ABI_TYPES, [self.g, self.y, self.pi, self.l, self.N, self.T, seed_hash])
        )


def empty_proof() -> VdfProof:
    return VdfProof()


def base_seed(round_id: int, blockhash: bytes, platon_random: bytes) -> bytes:
    """keccak256(abi.encodePacked(uint256 roundId, bytes32 bh, bytes32 platonRandom))."""
    return Web3.solidity_keccak(
        ["uint256", "bytes32", "bytes32"], [round_id, blockhash, platon_random]
    )


def seed_string(base: bytes) -> str:
    """Contract's _toHex(bytes32): '0x' + 64 lowercase hex chars."""
    return "0x" + base.hex()


_RSA_LABELS = {"rsa-2048", "rsa_2048", "rsa2048"}


def _bigint_to_bytes(s) -> bytes:
    """Chronos returns group elements as DECIMAL big-int strings (str(int)); also
    tolerate 0x-hex. Returns minimal big-endian bytes (matching Solidity bignum input)."""
    s = str(s).strip()
    if not s:
        return b""
    n = int(s, 16) if s.lower().startswith("0x") else int(s)
    if n == 0:
        return b"\x00"
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


def proof_from_chronos(seed: str, modulus, g, y, pi, l, T: int, canonical_n_hex: str = "") -> VdfProof:
    """Build a VdfProof from a Chronos `chronos.eval@v1` output.

    Chronos returns g/y/proof.pi/proof.l as DECIMAL strings and `modulus` as a label
    ("RSA-2048"), NOT hex. We convert the decimals to big-endian bytes and resolve the
    modulus label to the contract's canonical modulus (CHRONOS_CANONICAL_N, which must
    equal ChronosVDF.CANONICAL_N for on-chain verification). Raises ValueError if the
    modulus cannot be resolved, so the caller can fail the round cleanly rather than
    submit an invalid proof (or crash on a non-hex label)."""
    m = str(modulus).strip()
    if (not m) or m.lower().replace("-", "_") in _RSA_LABELS:
        cn = (canonical_n_hex or "").removeprefix("0x")
        if not cn:
            raise ValueError(
                f"Chronos returned modulus label {modulus!r}; set CHRONOS_CANONICAL_N "
                "to the contract's canonical modulus to use the on-chain VDF path")
        N = bytes.fromhex(cn if len(cn) % 2 == 0 else "0" + cn)
    elif m.lower().startswith("0x"):
        h = m[2:]
        N = bytes.fromhex(h if len(h) % 2 == 0 else "0" + h)
    else:
        N = _bigint_to_bytes(m)
    return VdfProof(seed=seed, g=_bigint_to_bytes(g), y=_bigint_to_bytes(y),
                    pi=_bigint_to_bytes(pi), l=_bigint_to_bytes(l), N=N, T=T)

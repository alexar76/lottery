"""The relayer's hand-written ABI must AGREE with AIAgentLottery.sol, byte for byte.

This is the drift class that took the relayer out of service once already: pass-1
of the fairness rework changed `reseed(uint256)` into `reseed(uint256,bytes32)`
and added five events, and nothing failed — the mirror in `abi.py` kept declaring
the old shapes. A wrong parameter list encodes a DIFFERENT 4-byte selector, so
the call does not raise locally, it reverts on-chain; a wrong or missing event
hashes to a different topic0, so a log filter matches nothing while looking
perfectly healthy.

So this file does not hand-check anything. It derives every selector, topic0 and
tuple layout from the COMPILED Foundry artifact, derives the event set and the
EIP-712 type strings straight from the .sol SOURCE (no toolchain needed), and
asserts `abi.py` equals both. A future change to the contract's external surface
cannot pass silently.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from web3 import Web3

from ailottery_relayer import abi as relayer_abi
from ailottery_relayer.abi import (
    _VDF_COMPONENTS,
    ECONOMY_FIELDS,
    EIP712_DOMAIN_NAME,
    EIP712_DOMAIN_VERSION,
    LOTTERY_ABI,
    PROOF_HASH_ABI_TYPES,
    REP_VOUCHER_TYPE,
    ROUND_FIELDS,
    DRAW_BEACON_TYPE,
)

_CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
_SOURCE = _CONTRACTS / "src" / "AIAgentLottery.sol"
_ARTIFACT = _CONTRACTS / "out" / "AIAgentLottery.sol" / "AIAgentLottery.json"


# ── source helpers (no Foundry required) ─────────────────────────────────────
def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


@pytest.fixture(scope="module")
def source() -> str:
    assert _SOURCE.is_file(), f"contract source missing: {_SOURCE}"
    return _strip_comments(_SOURCE.read_text())


@pytest.fixture(scope="module")
def artifact() -> list:
    """The compiled ABI. Build it if needed; refuse to 'pass' without it."""
    if not _ARTIFACT.is_file():
        forge = shutil.which("forge")
        if not forge:
            pytest.fail(
                f"no compiled artifact at {_ARTIFACT} and `forge` is not on PATH — "
                "cannot verify the relayer ABI against the contract. Run "
                "`forge build` in lottery/contracts.")
        subprocess.run([forge, "build"], cwd=_CONTRACTS, check=True,
                       capture_output=True, timeout=600)
    return json.loads(_ARTIFACT.read_text())["abi"]


def _canonical(entry: dict) -> str:
    """`name(type,type,...)` with tuples expanded, exactly as Solidity hashes it."""
    def _type(item: dict) -> str:
        if item["type"].startswith("tuple"):
            inner = ",".join(_type(c) for c in item["components"])
            return f"({inner}){item['type'][len('tuple'):]}"
        return item["type"]
    return f"{entry['name']}({','.join(_type(i) for i in entry['inputs'])})"


def _by_name(entries: list, kind: str) -> dict:
    return {e["name"]: e for e in entries if e.get("type") == kind}


# ── functions: selectors ─────────────────────────────────────────────────────
def test_every_relayer_function_matches_the_compiled_selector(artifact):
    compiled = _by_name(artifact, "function")
    mismatches = []
    for entry in LOTTERY_ABI:
        if entry["type"] != "function":
            continue
        name = entry["name"]
        assert name in compiled, f"{name} is not on the contract any more"
        ours, theirs = _canonical(entry), _canonical(compiled[name])
        if ours != theirs:
            mismatches.append(
                f"{ours} (selector {Web3.keccak(text=ours)[:4].hex()}) != "
                f"{theirs} (selector {Web3.keccak(text=theirs)[:4].hex()})")
    assert not mismatches, "relayer would mis-encode these calls:\n  " + "\n  ".join(mismatches)


def test_reseed_takes_the_fresh_commitment_the_contract_demands(source, artifact):
    """The rescue is not a re-roll: it must carry NEW committed entropy."""
    compiled = _by_name(artifact, "function")["reseed"]
    assert _canonical(compiled) == "reseed(uint256,bytes32)"
    ours = next(e for e in LOTTERY_ABI if e["type"] == "function" and e["name"] == "reseed")
    assert _canonical(ours) == "reseed(uint256,bytes32)"
    # …and the source really rejects a re-used commitment, which is WHY the
    # second argument exists.
    assert "StaleCommitment" in source


# ── events: topic0 ───────────────────────────────────────────────────────────
def _source_events(src: str) -> dict[str, list[tuple[str, bool]]]:
    """{name: [(solidity_type, indexed), …]} for every event the contract declares."""
    out: dict[str, list[tuple[str, bool]]] = {}
    for name, params in re.findall(r"\bevent\s+(\w+)\s*\((.*?)\)\s*;", src, flags=re.S):
        fields = []
        for raw in (p.strip() for p in params.split(",") if p.strip()):
            words = raw.split()
            fields.append((words[0], "indexed" in words))
        out[name] = fields
    return out


def test_relayer_declares_every_event_the_contract_emits(source):
    declared = _source_events(source)
    assert declared, "no events parsed from the contract source — parser broke"
    ours = _by_name(LOTTERY_ABI, "event")
    missing = sorted(set(declared) - set(ours))
    assert not missing, (
        "the contract emits events the relayer cannot decode (a log filter on them "
        f"silently matches nothing): {missing}")


def test_event_topic0s_match_the_source_signatures(source):
    declared = _source_events(source)
    for name, entry in _by_name(LOTTERY_ABI, "event").items():
        expected_sig = f"{name}({','.join(t for t, _ in declared[name])})"
        assert relayer_abi.event_signature(name) == expected_sig
        assert relayer_abi.event_topic0(name) == Web3.keccak(text=expected_sig), (
            f"{name} topic0 drifted — subscribers would index nothing")
        assert [ix for _, ix in declared[name]] == [i["indexed"] for i in entry["inputs"]], (
            f"{name}: indexed flags differ, so the log decodes into the wrong fields")


def test_event_topic0s_match_the_compiled_artifact(artifact):
    compiled = _by_name(artifact, "event")
    for name, entry in _by_name(LOTTERY_ABI, "event").items():
        assert name in compiled, f"{name} is not emitted by the compiled contract"
        assert _canonical(entry) == _canonical(compiled[name])
        assert relayer_abi.event_topic0(name) == Web3.keccak(text=_canonical(compiled[name]))


# ── decoded tuples ───────────────────────────────────────────────────────────
def test_round_and_economy_field_order_match_the_contract(artifact):
    compiled = _by_name(artifact, "function")
    round_out = compiled["getRound"]["outputs"][0]["components"]
    assert ROUND_FIELDS == [c["name"] for c in round_out], (
        "getRound() decodes positionally — a reordered struct silently relabels "
        "every field the relayer reads")
    assert ECONOMY_FIELDS == [o["name"] for o in compiled["economy"]["outputs"]]


def test_vdf_proof_struct_matches_the_contract(artifact):
    compiled = _by_name(artifact, "function")["fulfillDraw"]
    vdf = next(i for i in compiled["inputs"] if i["type"].startswith("tuple"))
    assert [(c["name"], c["type"]) for c in vdf["components"]] == \
           [(c["name"], c["type"]) for c in _VDF_COMPONENTS]


# ── EIP-712 ──────────────────────────────────────────────────────────────────
def test_eip712_domain_matches_the_contract(source):
    name, version = re.search(r'EIP712\("([^"]+)",\s*"([^"]+)"\)', source).groups()
    assert (EIP712_DOMAIN_NAME, EIP712_DOMAIN_VERSION) == (name, version), (
        "a different domain separator ⇒ every beacon/voucher signature is rejected")


@pytest.mark.parametrize("struct,fields", [
    ("DrawBeacon", DRAW_BEACON_TYPE),
    ("ReputationVoucher", REP_VOUCHER_TYPE),
])
def test_eip712_typehash_strings_match_the_contract(source, struct, fields):
    ours = f"{struct}({','.join(f['type'] + ' ' + f['name'] for f in fields)})"
    assert f'keccak256("{ours}")' in re.sub(r"\s+", " ", source), (
        f"{struct} typehash drifted from the contract — signatures would not recover")


def test_proof_hash_encoding_matches_the_contract(source):
    """proofHash = keccak256(abi.encode(g,y,pi,l,N,T,keccak256(seed)))."""
    flat = re.sub(r"\s+", " ", source)
    call = re.search(r"keccak256\(abi\.encode\((vdf\..*?)\)\);", flat).group(1)
    order = re.findall(r"vdf\.(\w+)", call)
    types = {c["name"]: c["type"] for c in _VDF_COMPONENTS}
    # the trailing keccak256(bytes(vdf.seed)) contributes a bytes32, not a string
    expected = [types[f] for f in order[:-1]] + ["bytes32"]
    assert order[-1] == "seed"
    assert PROOF_HASH_ABI_TYPES == expected, (
        "the beacon would commit to a different proof hash than the contract checks")


# ── mirrored constants ───────────────────────────────────────────────────────
_UNITS = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400, "weeks": 604800}


def _eval_solidity_const(expr: str, known: dict[str, int]) -> int:
    """Evaluate a Solidity constant expression (`4`, `1 hours`, `A + B`)."""
    expr = re.sub(r"\b(\d[\d_]*)\b", lambda m: m.group(1).replace("_", ""), expr)
    for unit, mul in _UNITS.items():
        expr = re.sub(rf"(\d+)\s+{unit}\b", lambda m, m2=mul: str(int(m.group(1)) * m2), expr)

    def _node(n):
        if isinstance(n, ast.Constant):
            return int(n.value)
        if isinstance(n, ast.Name):
            return known[n.id]
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            return _node(n.left) + _node(n.right)
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mult):
            return _node(n.left) * _node(n.right)
        raise AssertionError(f"unsupported constant expression: {ast.dump(n)}")

    return _node(ast.parse(expr.strip(), mode="eval").body)


def test_mirrored_contract_constants_match_the_source(source):
    """The relayer reasons about the settle window with these — a stale copy makes
    it wait past an expiry, or rescue a round the contract still considers live."""
    declared: dict[str, int] = {}
    for m in re.finditer(r"uint\d+\s+public\s+constant\s+(\w+)\s*=\s*([^;]+);", source):
        declared[m.group(1)] = _eval_solidity_const(m.group(2), declared)

    mirrored = ["SEED_BLOCK_OFFSET", "BLOCKHASH_WINDOW", "SEED_LIFETIME_BLOCKS",
                "DRAW_DELAY_HEADROOM", "MAX_RESEEDS", "RESEED_COOLDOWN",
                "STALL_CANCEL_DELAY", "UNCLAIMED_PRIZE_TTL",
                "DEFAULT_SECONDS_PER_BLOCK", "MAX_SECONDS_PER_BLOCK"]
    for name in mirrored:
        assert name in declared, f"{name} is no longer a constant on the contract"
        assert getattr(relayer_abi, name) == declared[name], (
            f"{name}: relayer says {getattr(relayer_abi, name)}, "
            f"contract says {declared[name]}")


def test_max_draw_delay_mirror_matches_the_contract(artifact, source):
    """`_maxDrawDelay(s) = SEED_LIFETIME_BLOCKS * s / DRAW_DELAY_HEADROOM`."""
    assert "(SEED_LIFETIME_BLOCKS * uint256(s)) / DRAW_DELAY_HEADROOM" in \
        re.sub(r"\s+", " ", source)
    # Base's declared default: 260 blocks × 2 s / 2 = 260 s, NOT the 1 h an
    # earlier build allowed.
    assert relayer_abi.max_draw_delay(relayer_abi.DEFAULT_SECONDS_PER_BLOCK) == 260
    assert "maxDrawDelay" in _by_name(artifact, "function")

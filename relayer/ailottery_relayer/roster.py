"""Participant roster — real Mesh agents or synthetic demo crowd."""
from __future__ import annotations

from dataclasses import dataclass

from eth_account import Account
from web3 import Web3

# Fallback names ONLY when the Mesh roster is unavailable (synthetic demo crowd).
_NAMES = ["Aria", "Boreas", "Ceres", "Draco", "Echo", "Flux", "Gaia", "Helix"]


@dataclass
class Participant:
    """A lottery seat. `source="mesh"` ⇒ a real verified Mesh agent (real name, id,
    reputation); `source="synthetic"` ⇒ the demo crowd. In UNI/Anvil the on-chain buy
    is always signed by a relayer-held funded `key` (Mesh agents expose no private key);
    `wallet` records the agent's own bound address for display + the future self-sign path."""
    name: str
    key: str            # relayer-held funded signing key (custodial in UNI/demo)
    addr: str           # on-chain msg.sender == Account.from_key(key).address
    trust_bps: int = 0  # real reputation → odds bonus (mesh); synthetic uses LUMEN
    mesh_id: str = ""
    wallet: str = ""    # agent's own bound EVM address (self-custodial, future path)
    source: str = "synthetic"


def mesh_roster(agents, keys: list[str], addrs: list[str]) -> list[Participant]:
    """Seat real Mesh agents onto funded signing keys (custodial in UNI/demo)."""
    return [
        Participant(name=a.name, key=keys[i], addr=addrs[i], trust_bps=a.trust_bps,
                    mesh_id=a.id, wallet=a.evm_address, source="mesh")
        for i, a in enumerate(agents)
    ]


def synthetic_roster(keys: list[str], addrs: list[str]) -> list[Participant]:
    """Demo crowd — used only when the Mesh roster is unavailable."""
    return [
        Participant(name=_NAMES[i % len(_NAMES)], key=k, addr=addrs[i])
        for i, k in enumerate(keys)
    ]


def derive_agent_key(seed: str, agent_id: str) -> str:
    """Deterministic per-agent private key for the UNI emulation (we own the chain).
    Same agent ⇒ same wallet across rounds; different agents ⇒ distinct wallets."""
    return Web3.keccak(text=f"ailottery-uni-wallet|{seed}|{agent_id}").hex()


def uni_wallet_roster(agents, seed: str) -> list[Participant]:
    """Each real Mesh agent gets its OWN deterministic wallet and signs its own buys —
    true self-custodial participation (UNI: we hold the derived keys + fund them)."""
    out = []
    for a in agents:
        key = derive_agent_key(seed, a.id)
        addr = Account.from_key(key).address
        out.append(Participant(name=a.name, key=key, addr=addr, trust_bps=a.trust_bps,
                               mesh_id=a.id, wallet=addr, source="mesh"))
    return out

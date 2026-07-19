"""Hub discovery must not emit nodes for family-oracle federation peers."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from oracle_family import family_node_id_for_peer, oracle_node_id  # noqa: E402


def test_shadow_oracle_peer_maps_to_platon_not_new_node():
    peer = {
        "id": "platon-shadow-oracle",
        "label": "Platon Shadow Oracle",
        "url": "https://oracles.modelmarket.dev",
        "description": "32D dynamical shadow oracle",
    }
    assert family_node_id_for_peer(peer) == oracle_node_id("platon")


def test_oracle_family_seed_peer_is_suppressed():
    peer = {
        "id": "fed-oracle-family-aimarket-v2",
        "label": "Oracle Family (AIMarket v2)",
        "url": "https://oracles.modelmarket.dev/family",
        "description": "17 oracles",
    }
    assert family_node_id_for_peer(peer) == oracle_node_id("platon")

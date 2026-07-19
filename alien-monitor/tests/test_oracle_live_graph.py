"""LIVE graph must show 17 family oracles — not duplicate Platon Shadow peers."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from oracle_family import (  # noqa: E402
    CAVE,
    ORACLE_FAMILY,
    append_oracle_family_graph,
    build_oracle_family_nodes,
    family_node_id_for_peer,
    merge_discovered_peers,
    oracle_node_id,
)


def test_build_oracle_family_has_seventeen_plus_cave():
    nodes = build_oracle_family_nodes()
    ids = {n["id"] for n in nodes}
    assert len(ORACLE_FAMILY) == 17
    assert len(nodes) == 18
    assert CAVE["id"] in ids
    assert oracle_node_id("platon") in ids
    assert oracle_node_id("fermat") in ids
    assert oracle_node_id("sortes") in ids


def test_platon_shadow_peer_maps_to_oracle_platon():
    peer = {
        "id": "platon-shadow-oracle",
        "label": "Platon Shadow Oracle",
        "url": "https://oracles.modelmarket.dev",
        "description": "32D dynamical shadow oracle",
    }
    assert family_node_id_for_peer(peer) == oracle_node_id("platon")


def test_live_graph_dedupes_shadow_peer():
    nodes = [{"id": "hub", "label": "Hub", "group": "core", "metrics": {}, "position": {"x": 0, "y": 0, "z": 0}}]
    links: list[dict] = []
    append_oracle_family_graph(nodes, links)
    before = len(nodes)
    disc = {
        "nodes": [
            {
                "id": "platon-shadow-oracle",
                "label": "Platon Shadow Oracle",
                "url": "https://oracles.modelmarket.dev",
                "group": "oracle",
                "metrics": {"kappa": 0.42},
                "status": "active",
                "position": {"x": -2, "y": 5, "z": 1},
            },
            {
                "id": "platon-shadow-oracle-2",
                "label": "Platon Shadow Oracle",
                "url": "http://78.17.126.214",
                "group": "oracle",
                "metrics": {"order_parameter": 0.9},
                "status": "active",
                "position": {"x": -2, "y": 5, "z": 1},
            },
        ],
        "links": [
            {"source": "federation", "target": "platon-shadow-oracle", "label": "Federation peer"},
        ],
        "peer_count": 2,
    }
    nodes.append({"id": "federation", "label": "Federation", "group": "network", "metrics": {}, "position": {"x": 0, "y": 0, "z": 0}})
    merge_discovered_peers(nodes, links, disc)
    assert len(nodes) == before + 1  # federation only — no shadow duplicates
    platon = next(n for n in nodes if n["id"] == oracle_node_id("platon"))
    assert platon["metrics"].get("kappa") == 0.42
    assert platon["metrics"].get("order_parameter") == 0.9
    assert not any("shadow" in n["id"] for n in nodes)

"""ARGUS reference agent — topology anchor + graph links for Alien Monitor."""

from __future__ import annotations

from typing import Any

from argus_status import argus_public_url, argus_public_url_for_mode
from ecosystem_layout import node_position


def argus_node_spec(*, mode: str = "real") -> dict[str, Any]:
    """Static ARGUS node fields shared by TEST / LIVE / UNI topologies."""
    return {
        "id": "argus",
        "label": "ARGUS-3",
        "group": "argus",
        "icon": "client",
        "description": (
            "Wallet-native reference agent — WARDEN security, native oracle reads, "
            "Hub invokes, verifiable runs. Gray when the node is not reachable."
        ),
        "metrics": {"uptime_sec": 0, "runs_24h": 0},
        "status": "offline",
        "position": node_position("argus"),
        "url": argus_public_url_for_mode(mode),
    }


def argus_topology_links(*, oracle_target: str = "federation") -> list[dict[str, str]]:
    """Directed edges: ecosystem ↔ ARGUS demand-side client."""
    return [
        {"source": "hub", "target": "argus", "label": "Capability invoke"},
        {"source": "mesh", "target": "argus", "label": "Reference agent"},
        {"source": "argus", "target": oracle_target, "label": "Oracle reads"},
    ]

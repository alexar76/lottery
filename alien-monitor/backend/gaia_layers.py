"""GAIA physical-oracle node — topology anchor + graph links for Alien Monitor."""

from __future__ import annotations

from typing import Any

from ecosystem_layout import node_position
from gaia_status import gaia_links, gaia_public_url


def gaia_node_spec(*, mode: str = "real") -> dict[str, Any]:
    """Static GAIA node fields shared by TEST / LIVE / UNI topologies."""
    _ = mode
    return {
        "id": "gaia",
        "label": "GAIA",
        "group": "physical",
        "icon": "globe",
        "description": (
            "Physical-world oracle gateway — the ecosystem's third oracle class "
            "(math oracles → cognitive METIS → physical GAIA). Virtual IoT devices "
            "(weather, air-quality, energy) sign every reading with a per-device "
            "Ed25519 key; a plausibility verifier gates payment under Pay-on-Verified "
            "escrow, so a lying sensor automatically refunds the buyer. Loosely-coupled "
            "peer: the ecosystem runs without it, and it runs alone."
        ),
        "metrics": {"devices": 0, "online": 0, "live_relays": 0},
        "status": "offline",
        "position": node_position("gaia"),
        "url": gaia_public_url(),
        "links": gaia_links(),
    }


def gaia_topology_links() -> list[dict[str, str]]:
    """Directed edges: physical-oracle gateway ↔ ecosystem (optional at runtime)."""
    return [
        {"source": "gaia", "target": "hub", "label": "Sensor capabilities"},
        {"source": "gaia", "target": "metis", "label": "Pay-on-Verified"},
    ]

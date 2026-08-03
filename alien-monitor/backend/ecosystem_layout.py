"""Shared 3D anchors for the Alien Monitor ecosystem graph.

Keeps static nodes and the oracle ring in separate sectors so pulsing
coronas do not overlap (e.g. Colony vs Desktop Apps).
"""

from __future__ import annotations

import math

# Federation + discovered peer mini-ring
FEDERATION_ANCHOR = (0.0, 8.0, 2.0)
FEDERATION_PEER_RADIUS = 4.0

# Oracle family — far east sector (+X), away from client shelf (-X)
ORACLE_RING_CENTER = (17.0, 0.0, 1.0)
ORACLE_RING_RADIUS = 7.5
ORACLE_RING_Y_AMPLITUDE = 1.5

# ~1.3× baseline spacing — hub stays at origin
NODE_POSITIONS: dict[str, dict[str, float]] = {
    "hub": {"x": 0.0, "y": 0.0, "z": 0.0},
    "factory": {"x": 5.0, "y": 2.5, "z": -2.5},
    "mesh": {"x": -5.0, "y": -1.5, "z": 2.5},
    "acex": {"x": 2.5, "y": -4.0, "z": 5.0},
    "evm_escrow": {"x": 5.5, "y": 4.5, "z": -2.5},
    "solana_escrow": {"x": 4.5, "y": -3.5, "z": -5.5},
    "nft_contract": {"x": 6.5, "y": 0.5, "z": -5.0},
    "desktop_apps": {"x": -7.5, "y": 5.5, "z": -7.0},
    "plugins": {"x": 0.0, "y": -6.5, "z": -4.0},
    "sdk_dart": {"x": -6.5, "y": 1.5, "z": 6.5},
    "sdk_typescript": {"x": -7.5, "y": -1.5, "z": 5.0},
    "sdk_rust": {"x": -6.5, "y": 2.5, "z": -6.5},
    "federation": {"x": FEDERATION_ANCHOR[0], "y": FEDERATION_ANCHOR[1], "z": FEDERATION_ANCHOR[2]},
    "widget": {"x": -5.0, "y": 7.0, "z": -4.5},
    "ethereum": {"x": 3.5, "y": 6.5, "z": 5.5},
    "solana": {"x": 3.5, "y": -5.5, "z": 6.0},
    "cli": {"x": -6.5, "y": -5.5, "z": 6.5},
    "argus": {"x": -8.0, "y": 2.5, "z": 2.0},
    "dioscuri": {"x": -9.5, "y": 5.5, "z": -2.0},
    "helios": {"x": -8.5, "y": 7.5, "z": -5.0},
    "metis": {"x": -10.5, "y": 0.0, "z": 4.5},
    "skopos": {"x": -11.5, "y": -3.5, "z": 1.5},
    "gaia": {"x": -6.5, "y": 8.5, "z": -6.5},
}


def node_position(node_id: str, *, fallback: dict[str, float] | None = None) -> dict[str, float]:
    pos = NODE_POSITIONS.get(node_id)
    if pos is not None:
        return dict(pos)
    if fallback is not None:
        return dict(fallback)
    return {"x": 0.0, "y": 0.0, "z": 0.0}


def ring_position(index: int, total: int) -> dict[str, float]:
    """Place oracle nodes on a ring in the east sector."""
    ang = (2.0 * math.pi * index) / max(1, total)
    cx, cy, cz = ORACLE_RING_CENTER
    return {
        "x": round(cx + ORACLE_RING_RADIUS * math.cos(ang), 3),
        "y": round(cy + ORACLE_RING_Y_AMPLITUDE * math.sin(ang), 3),
        "z": round(cz + ORACLE_RING_RADIUS * 0.65 * math.sin(ang), 3),
    }


def federation_peer_position(node_id: str) -> dict[str, float]:
    h = sum(ord(ch) for ch in node_id) or 1
    ang = (h % 360) * math.pi / 180.0
    ax, ay, az = FEDERATION_ANCHOR
    return {
        "x": round(ax + FEDERATION_PEER_RADIUS * math.cos(ang), 3),
        "y": round(ay + ((h % 5) - 2) * 0.7, 3),
        "z": round(az + FEDERATION_PEER_RADIUS * math.sin(ang), 3),
    }

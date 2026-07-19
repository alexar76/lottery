"""3D layout spacing — oracle ring must not crowd static nodes."""

from __future__ import annotations

import math
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from ecosystem_layout import (  # noqa: E402
    NODE_POSITIONS,
    ORACLE_RING_CENTER,
    ORACLE_RING_RADIUS,
    ring_position,
)
from oracle_family import ORACLE_FAMILY  # noqa: E402


def _dist(a: dict[str, float], b: dict[str, float]) -> float:
    return math.sqrt(
        (a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2 + (a["z"] - b["z"]) ** 2
    )


def test_colony_far_from_desktop_apps():
    desktop = NODE_POSITIONS["desktop_apps"]
    colony = ring_position(5, len(ORACLE_FAMILY))
    assert _dist(desktop, colony) >= 12.0


def test_oracle_ring_nodes_separated_from_static_nodes():
    total = len(ORACLE_FAMILY)
    static = list(NODE_POSITIONS.values())
    min_gap = 4.5
    for i in range(total):
        oracle = ring_position(i, total)
        for pos in static:
            assert _dist(oracle, pos) >= min_gap, f"oracle[{i}] too close to static node"


def test_oracle_ring_center_in_east_sector():
    cx, _, _ = ORACLE_RING_CENTER
    assert cx >= ORACLE_RING_RADIUS

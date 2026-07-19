"""Argus node is always seeded in UNI universe topology."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def test_universe_seeds_argus_entity():
    from universe import VirtualUniverse

    u = VirtualUniverse()
    u.seed_entities()
    assert "argus" in u.entities
    ent = u.entities["argus"]
    assert ent.group == "argus"
    assert ent.name == "ARGUS-3"

"""Tests for satellite-map.yaml registry loader."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from ecosystem_registry import build_ecosystem_registry_context, load_satellites  # noqa: E402


def test_load_satellites_includes_skopos_and_metis():
    load_satellites.cache_clear()
    ids = {s["id"] for s in load_satellites()}
    assert "skopos" in ids
    assert "metis" in ids
    assert "gaia" in ids
    assert "theoros" in ids
    assert "alien-monitor" in ids


def test_build_ecosystem_registry_context_mentions_skopos():
    load_satellites.cache_clear()
    ctx = build_ecosystem_registry_context()
    assert "skopos" in ctx.lower()
    assert "gaia" in ctx.lower()
    assert "alexar76" in ctx.lower()

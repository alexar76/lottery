"""Tests for AI map navigation action detection."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from ai_nav_actions import resolve_nav_actions  # noqa: E402


def test_show_skopos_ru():
    q = "теме появился skopos?покажи мне его"
    actions = resolve_nav_actions(q)
    assert actions[0]["type"] == "focus_node"
    assert actions[0]["node_id"] == "skopos"


def test_show_skopos_en():
    actions = resolve_nav_actions("Show me SKOPOS on the map")
    assert actions[0]["node_id"] == "skopos"


def test_what_is_skopos_no_nav():
    assert resolve_nav_actions("What is SKOPOS?") == []


def test_where_is_metis():
    actions = resolve_nav_actions("Где METIS на карте?")
    assert actions[0]["node_id"] == "metis"


def test_show_gaia_ru_accusative():
    """«покажи гею» must focus — accusative «гею» used to miss alias «гея»."""
    actions = resolve_nav_actions("покажи гею")
    assert actions and actions[0]["node_id"] == "gaia"


def test_open_gaia_ru_accusative():
    assert resolve_nav_actions("открой гайю")[0]["node_id"] == "gaia"


def test_show_gaia_fr():
    assert resolve_nav_actions("montre gaia")[0]["node_id"] == "gaia"
    assert resolve_nav_actions("où est gaïa")[0]["node_id"] == "gaia"


def test_show_skopos_zh():
    assert resolve_nav_actions("显示 SKOPOS")[0]["node_id"] == "skopos"
    assert resolve_nav_actions("盖亚在哪里")[0]["node_id"] == "gaia"
    assert resolve_nav_actions("打开赫利俄斯")[0]["node_id"] == "helios"


def test_what_is_gaia_fr_zh_no_nav():
    assert resolve_nav_actions("Qu'est-ce que Gaia ?") == []
    assert resolve_nav_actions("什么是盖亚") == []


def test_core_satellite_without_state_entry():
    state = {"nodes": [{"id": "hub", "label": "Hub"}]}
    assert resolve_nav_actions("show skopos", state)[0]["node_id"] == "skopos"


def test_focus_when_node_present_in_state():
    state = {"nodes": [{"id": "hub", "label": "Hub"}]}
    assert resolve_nav_actions("show hub", state)[0]["node_id"] == "hub"

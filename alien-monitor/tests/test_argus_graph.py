"""ARGUS graph integration — node always present; offline when /health unreachable."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from argus_layers import argus_node_spec, argus_topology_links  # noqa: E402
from argus_status import apply_argus_graph, apply_argus_to_nodes  # noqa: E402
from main import build_topology  # noqa: E402


def test_topology_includes_argus_node():
    nodes, links = build_topology()
    ids = {n["id"] for n in nodes}
    assert "argus" in ids
    assert any(l["source"] == "hub" and l["target"] == "argus" for l in links)
    assert any(l["source"] == "argus" for l in links)


def test_argus_node_spec_defaults_offline():
    spec = argus_node_spec()
    assert spec["id"] == "argus"
    assert spec["group"] == "argus"
    assert spec["status"] == "offline"


def test_apply_argus_graph_marks_offline_when_unreachable(monkeypatch):
    nodes = [argus_node_spec()]
    monkeypatch.setattr("argus_status.fetch_argus_health_sync", lambda **_: None)
    apply_argus_graph(nodes, mode="real")
    assert nodes[0]["status"] == "offline"
    assert "argus_run" not in nodes[0]


def test_apply_argus_graph_marks_active_on_health(monkeypatch):
    nodes = [argus_node_spec()]
    health = {
        "status": "ok",
        "economy": "on",
        "mode": "live",
        "model": "deepseek/deepseek-chat",
        "version": "0.1.0",
        "uptimeSec": 42,
        "wallet": "0x3520b679c998EE01B0d5EB0458CB9abf4e7Bb9e7",
        "chainNetwork": "Base",
        "chainId": 8453,
    }
    monkeypatch.setattr("argus_status.fetch_argus_health_sync", lambda **_: health)
    apply_argus_graph(nodes, mode="real")
    assert nodes[0]["status"] == "active"
    assert nodes[0]["argus_live"]["model"] == "deepseek/deepseek-chat"


def test_apply_argus_to_nodes_clears_live_when_offline():
    nodes = [argus_node_spec()]
    nodes[0]["status"] = "active"
    nodes[0]["argus_live"] = {"economy": "on"}
    apply_argus_to_nodes(nodes, None)
    assert nodes[0]["status"] == "offline"
    assert "argus_live" not in nodes[0]

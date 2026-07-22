"""Tests for SKOPOS graph node in Alien Monitor."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(ROOT))

from skopos_layers import skopos_node_spec, skopos_topology_links  # noqa: E402
from skopos_status import apply_skopos_graph, apply_skopos_to_nodes  # noqa: E402


def test_skopos_node_spec_defaults_offline():
    spec = skopos_node_spec()
    assert spec["id"] == "skopos"
    assert spec["group"] == "observability"
    assert spec["url"].startswith("https://")
    assert spec["links"]["dashboard"] == spec["url"]


def test_skopos_topology_links_include_metis():
    ids = {(l["source"], l["target"]) for l in skopos_topology_links()}
    assert ("skopos", "metis") in ids


def test_apply_skopos_graph_marks_offline_when_unreachable(monkeypatch):
    nodes = [skopos_node_spec()]
    monkeypatch.setattr("skopos_status.fetch_skopos_status_sync", lambda **_: None)
    apply_skopos_graph(nodes, mode="real")
    assert nodes[0]["status"] == "offline"


def test_apply_skopos_graph_marks_active_on_health(monkeypatch):
    nodes = [skopos_node_spec()]
    monkeypatch.setattr(
        "skopos_status.fetch_skopos_status_sync",
        lambda **_: {"ok": True, "servers_monitored": 1, "requests_total": 42, "database": "postgresql"},
    )
    apply_skopos_graph(nodes, mode="real")
    assert nodes[0]["status"] == "active"
    assert nodes[0]["metrics"]["requests_total"] == 42


def test_apply_skopos_to_nodes_clears_live_when_offline():
    nodes = [skopos_node_spec()]
    nodes[0]["skopos_live"] = {"database": "postgresql"}
    apply_skopos_to_nodes(nodes, None)
    assert nodes[0]["status"] == "offline"
    assert "skopos_live" not in nodes[0]

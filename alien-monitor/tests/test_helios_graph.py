"""HELIOS graph node — topology + health polling."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from helios_layers import helios_node_spec, helios_topology_links  # noqa: E402
from helios_status import apply_helios_graph, apply_helios_to_nodes  # noqa: E402
from main import build_topology  # noqa: E402


def test_topology_includes_helios_node():
    nodes, links = build_topology()
    ids = {n["id"] for n in nodes}
    assert "helios" in ids
    assert any(l["source"] == "factory" and l["target"] == "helios" for l in links)
    assert any(l["source"] == "dioscuri" and l["target"] == "helios" for l in links)


def test_helios_node_spec_defaults_offline():
    spec = helios_node_spec()
    assert spec["id"] == "helios"
    assert spec["group"] == "media"
    assert spec["status"] == "offline"


def test_apply_helios_graph_marks_offline_when_unreachable(monkeypatch):
    nodes = [helios_node_spec()]
    monkeypatch.setattr("helios_status.fetch_helios_health_sync", lambda **_: None)
    apply_helios_graph(nodes, mode="real")
    assert nodes[0]["status"] == "offline"


def test_apply_helios_graph_marks_active_on_health(monkeypatch):
    nodes = [helios_node_spec()]
    health = {
        "ok": True,
        "version": "0.1.0",
        "uptimeSec": 120,
        "dryRun": False,
        "queue_pending": 3,
        "uploaded_today": 4,
        "youtube": {"subscribers": 500, "views": 12000, "videos": 15, "cached_at": "2026-07-07T10:00:00Z"},
    }
    monkeypatch.setattr("helios_status.fetch_helios_health_sync", lambda **_: health)
    apply_helios_graph(nodes, mode="real")
    assert nodes[0]["status"] == "active"
    assert nodes[0]["helios_live"]["subscribers"] == 500
    assert nodes[0]["metrics"]["views"] == 12000
    assert nodes[0]["metrics"]["uploaded_today"] == 4

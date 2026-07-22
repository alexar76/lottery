"""DIOSCURI graph node — topology + health polling."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dioscuri_layers import dioscuri_node_spec, dioscuri_topology_links  # noqa: E402
from dioscuri_status import apply_dioscuri_graph, apply_dioscuri_to_nodes  # noqa: E402
from main import build_topology  # noqa: E402


def test_topology_includes_dioscuri_node():
    nodes, links = build_topology()
    ids = {n["id"] for n in nodes}
    assert "dioscuri" in ids
    assert any(l["source"] == "factory" and l["target"] == "dioscuri" for l in links)
    assert any(l["source"] == "dioscuri" and l["target"] == "hub" for l in links)


def test_dioscuri_node_spec_defaults_offline():
    spec = dioscuri_node_spec()
    assert spec["id"] == "dioscuri"
    assert spec["group"] == "community"
    assert spec["status"] == "offline"
    assert "community_links" in spec
    theoros = spec["community_links"].get("theoros", "")
    assert theoros.rstrip("/").endswith("/theoros")
    children = spec.get("children") or []
    assert len(children) == 2
    assert {c["id"] for c in children} == {"castor", "pollux"}
    collab = spec.get("collaboration") or {}
    assert collab.get("id") == "theoros"
    assert collab.get("url", "").rstrip("/").endswith("/theoros")


def test_apply_dioscuri_graph_marks_offline_when_unreachable(monkeypatch):
    nodes = [dioscuri_node_spec()]
    monkeypatch.setattr("dioscuri_status.fetch_dioscuri_health_sync", lambda **_: None)
    apply_dioscuri_graph(nodes, mode="real")
    assert nodes[0]["status"] == "offline"


def test_apply_dioscuri_graph_marks_active_on_health(monkeypatch):
    nodes = [dioscuri_node_spec()]
    health = {
        "ok": True,
        "version": "0.1.0",
        "uptimeSec": 90,
        "dryRun": False,
        "adapters": {"telegram": True, "discord": False},
        "kb": {"chunks": 120, "repos": 18, "lastSyncAt": "2026-07-05T10:00:00Z", "lastSyncOk": True},
        "theoros": {"active": True, "discord": True, "canonChannel": True, "slot": True, "kb": True},
    }
    monkeypatch.setattr("dioscuri_status.fetch_dioscuri_health_sync", lambda **_: health)
    apply_dioscuri_graph(nodes, mode="real")
    assert nodes[0]["status"] == "active"
    assert nodes[0]["dioscuri_live"]["telegram"] is True
    assert nodes[0]["dioscuri_live"]["theoros_active"] is True
    assert nodes[0]["collaboration"]["active"] is True
    assert nodes[0]["metrics"]["kb_chunks"] == 120


def test_apply_dioscuri_graph_theoros_inactive_when_not_wired(monkeypatch):
    nodes = [dioscuri_node_spec()]
    health = {
        "ok": True,
        "version": "0.1.0",
        "uptimeSec": 90,
        "dryRun": False,
        "adapters": {"telegram": True, "discord": True},
        "kb": {"chunks": 120, "repos": 18, "lastSyncAt": "2026-07-05T10:00:00Z", "lastSyncOk": True},
        "theoros": {"active": False, "discord": True, "canonChannel": False, "slot": True, "kb": False},
    }
    monkeypatch.setattr("dioscuri_status.fetch_dioscuri_health_sync", lambda **_: health)
    apply_dioscuri_graph(nodes, mode="real")
    assert nodes[0]["collaboration"]["active"] is False
    assert nodes[0]["dioscuri_live"]["theoros_active"] is False


def test_apply_dioscuri_graph_marks_theoros_active(monkeypatch):
    nodes = [dioscuri_node_spec()]
    health = {
        "ok": True,
        "version": "0.1.0",
        "uptimeSec": 90,
        "dryRun": False,
        "adapters": {"telegram": True, "discord": True},
        "kb": {"chunks": 120, "repos": 18, "lastSyncAt": "2026-07-05T10:00:00Z", "lastSyncOk": True},
        "theoros": {"active": True, "discord": True, "canonChannel": True, "slot": True, "kb": True},
    }
    monkeypatch.setattr("dioscuri_status.fetch_dioscuri_health_sync", lambda **_: health)
    apply_dioscuri_graph(nodes, mode="real")
    assert nodes[0]["collaboration"]["active"] is True
    assert nodes[0]["dioscuri_live"]["theoros_active"] is True


def test_apply_dioscuri_graph_marks_theoros_inactive_when_offline(monkeypatch):
    nodes = [dioscuri_node_spec()]
    monkeypatch.setattr("dioscuri_status.fetch_dioscuri_health_sync", lambda **_: None)
    apply_dioscuri_graph(nodes, mode="real")
    assert nodes[0]["collaboration"]["active"] is False


def test_apply_dioscuri_to_nodes_clears_live_when_offline():
    nodes = [dioscuri_node_spec()]
    nodes[0]["status"] = "active"
    nodes[0]["dioscuri_live"] = {"telegram": True}
    apply_dioscuri_to_nodes(nodes, None)
    assert nodes[0]["status"] == "offline"
    assert nodes[0]["collaboration"]["active"] is False
    assert "dioscuri_live" not in nodes[0]


def test_dioscuri_topology_links_non_empty():
    links = dioscuri_topology_links()
    assert len(links) >= 2

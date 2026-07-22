"""METIS graph node — topology, health polling, and offline-safe chat proxy."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from main import build_topology  # noqa: E402
from metis_layers import metis_node_spec, metis_topology_links  # noqa: E402
from metis_status import apply_metis_graph, apply_metis_to_nodes, metis_chat  # noqa: E402


def test_topology_includes_metis_node():
    nodes, links = build_topology()
    ids = {n["id"] for n in nodes}
    assert "metis" in ids
    assert any(l["source"] == "factory" and l["target"] == "metis" for l in links)
    assert any(l["source"] == "metis" and l["target"] == "hub" for l in links)


def test_metis_node_spec_defaults_offline():
    spec = metis_node_spec()
    assert spec["id"] == "metis"
    assert spec["group"] == "cognition"
    assert spec["status"] == "offline"
    assert spec["chat"] is True
    assert "links" in spec


def test_apply_metis_graph_marks_offline_when_unreachable(monkeypatch):
    nodes = [metis_node_spec()]
    monkeypatch.setattr("metis_status.fetch_metis_health_sync", lambda **_: None)
    apply_metis_graph(nodes, mode="real")
    assert nodes[0]["status"] == "offline"


def test_apply_metis_graph_marks_active_on_health(monkeypatch):
    nodes = [metis_node_spec()]
    health = {
        "status": "ok",
        "service": "metis",
        "version": "0.2.0",
        "nodes": [{"id": "node-a", "healthy": True}],
        "circuit_breakers": {"llm": {"state": "closed"}, "web": {"state": "open"}},
        "knowledge_entries": 42,
    }
    monkeypatch.setattr("metis_status.fetch_metis_health_sync", lambda **_: health)
    apply_metis_graph(nodes, mode="real")
    assert nodes[0]["status"] == "active"
    assert nodes[0]["metis_live"]["knowledge_entries"] == 42
    assert nodes[0]["metis_live"]["cluster_nodes"] == 1
    assert nodes[0]["metis_live"]["open_circuit_breakers"] == 1
    assert nodes[0]["metrics"]["knowledge_entries"] == 42


def test_apply_metis_graph_marks_active_on_health_list_breakers(monkeypatch):
    nodes = [metis_node_spec()]
    health = {
        "status": "ok",
        "service": "metis",
        "version": "0.2.0",
        "nodes": [],
        "circuit_breakers": [{"endpoint": "api.deepseek.com", "state": "closed"}],
        "knowledge_entries": 1,
    }
    monkeypatch.setattr("metis_status.fetch_metis_health_sync", lambda **_: health)
    apply_metis_graph(nodes, mode="real")
    assert nodes[0]["status"] == "active"
    assert nodes[0]["metis_live"]["open_circuit_breakers"] == 0


def test_apply_metis_to_nodes_clears_live_when_offline():
    nodes = [metis_node_spec()]
    nodes[0]["status"] = "active"
    nodes[0]["metis_live"] = {"version": "0.2.0"}
    apply_metis_to_nodes(nodes, None)
    assert nodes[0]["status"] == "offline"
    assert "metis_live" not in nodes[0]


def test_metis_topology_links_non_empty():
    assert len(metis_topology_links()) >= 2


def test_metis_chat_empty_no_network():
    out = asyncio.run(metis_chat([]))
    assert "answer" in out and out.get("error") == "empty"


def test_metis_chat_offline_is_failsafe(monkeypatch):
    # Point at a closed port: the proxy must return a readable message, not raise.
    monkeypatch.setenv("ALIEN_METIS_URL", "http://127.0.0.1:9")
    out = asyncio.run(metis_chat([{"role": "user", "content": "hi"}], timeout=1.0))
    assert "answer" in out
    assert out.get("error")  # some error key set, but no exception propagated

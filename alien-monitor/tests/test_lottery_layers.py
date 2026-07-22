"""Tests for Agent Lottery monitor integration."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from factory_products import merge_factory_products
from lottery_layers import apply_lottery_metrics, lottery_financial_links, lottery_node_spec
from main import build_topology


def test_lottery_node_is_economy_group():
    nodes, links = build_topology()
    lot = next(n for n in nodes if n["id"] == "lottery")
    assert lot["group"] == "economy"
    assert lot["url"].startswith("https://")
    assert any(l["target"] == "lottery" and l["source"] == "hub" for l in links)


def test_merge_factory_products_keeps_lottery():
    nodes, links = build_topology()
    merge_factory_products(nodes, links, [{"id": "prod-a", "name": "Demo", "category": "saas"}])
    assert any(n["id"] == "lottery" for n in nodes)
    assert any(l["target"] == "lottery" for l in links)


def test_apply_lottery_metrics_from_hub_mesh():
    from live_lottery_feed import clear_live_lottery

    clear_live_lottery()
    nodes, _ = build_topology()
    apply_lottery_metrics(
        nodes,
        hub_hints={"invocations_24h": 120, "volume_24h": 100.0},
        mesh_stats={"agents": 7},
    )
    lot = next(n for n in nodes if n["id"] == "lottery")
    assert lot["status"] == "active"
    assert lot["metrics"]["players"] == 7
    assert lot["metrics"]["funding_24h"] == 20.0


def test_lottery_financial_links_to_oracles():
    links = lottery_financial_links(oracle_ids=["oracle-platon", "oracle-chronos"])
    assert {"source": "hub", "target": "lottery"} == {"source": links[0]["source"], "target": links[0]["target"]}
    targets = {l["target"] for l in links if l["source"] == "lottery"}
    assert "oracle-platon" in targets
    assert "oracle-chronos" in targets

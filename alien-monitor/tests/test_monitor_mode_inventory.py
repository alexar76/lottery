"""Monitor graph inventory — required nodes per mode."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from factory_products import (  # noqa: E402
    clear_factory_catalog_cache,
    resolve_factory_catalog,
)
from oracle_family import CAVE, ORACLE_FAMILY, oracle_node_id  # noqa: E402

CORE_IDS = {
    "hub", "factory", "mesh", "acex", "evm_escrow", "solana_escrow", "nft_contract",
    "desktop_apps", "plugins", "sdk_dart", "sdk_typescript", "sdk_rust", "federation",
    "widget", "ethereum", "solana", "cli", "lottery", "argus", "dioscuri", "helios",
    "metis", "skopos", "gaia",
}
ORACLE_IDS = {oracle_node_id(o["slug"]) for o in ORACLE_FAMILY} | {CAVE["id"]}


def test_resolve_factory_catalog_uses_monitor_catalog(monkeypatch):
    import factory_products as fp

    monkeypatch.setattr(
        fp,
        "fetch_factory_monitor_catalog_sync",
        lambda *a, **k: [{"id": "prod-a", "name": "Alpha", "category": "saas"}],
    )
    monkeypatch.setattr(fp, "fetch_factory_products_sync", lambda *a, **k: None)
    fp.clear_factory_catalog_cache()
    catalog, auth = resolve_factory_catalog("http://factory.test")
    assert auth is True
    assert catalog == [{"id": "prod-a", "name": "Alpha", "category": "saas"}]


def test_resolve_factory_catalog_never_synthesizes_fake_ids(monkeypatch):
    import factory_products as fp

    monkeypatch.setattr(fp, "fetch_factory_monitor_catalog_sync", lambda *a, **k: None)
    monkeypatch.setattr(fp, "fetch_factory_products_sync", lambda *a, **k: None)
    fp.clear_factory_catalog_cache()
    catalog, auth = resolve_factory_catalog("http://factory.test")
    assert catalog is None
    assert auth is False


def test_resolve_factory_catalog_keeps_last_good_cache(monkeypatch):
    import factory_products as fp

    monkeypatch.setattr(
        fp,
        "fetch_factory_monitor_catalog_sync",
        lambda *a, **k: [{"id": "prod-keep", "name": "Keep", "category": "saas"}],
    )
    monkeypatch.setattr(fp, "fetch_factory_products_sync", lambda *a, **k: None)
    fp.clear_factory_catalog_cache()
    first, _ = resolve_factory_catalog("http://factory.test")
    assert first and first[0]["id"] == "prod-keep"

    monkeypatch.setattr(fp, "fetch_factory_monitor_catalog_sync", lambda *a, **k: None)
    second, auth2 = resolve_factory_catalog("http://factory.test")
    assert auth2 is False
    assert second == first


def test_live_fetch_has_oracles_and_clusters(monkeypatch):
    import asyncio

    import factory_products as fp
    from main import fetch_real_metrics

    monkeypatch.setattr(
        fp,
        "fetch_factory_monitor_catalog_sync",
        lambda *a, **k: [
            {"id": "prod-a", "name": "Alpha", "category": "saas"},
            {"id": "prod-b", "name": "Beta", "category": "landings"},
        ],
    )
    monkeypatch.setattr(fp, "fetch_factory_products_sync", lambda *a, **k: None)
    fp.clear_factory_catalog_cache()

    state = asyncio.run(fetch_real_metrics())
    ids = {n["id"] for n in state["nodes"]}
    groups = {n.get("group") for n in state["nodes"]}
    assert CORE_IDS.issubset(ids)
    assert ORACLE_IDS.issubset(ids)
    assert "cluster" in groups
    cluster = next(n for n in state["nodes"] if n.get("group") == "cluster")
    assert all(not c["id"].startswith("cat-") for c in cluster.get("children") or [])

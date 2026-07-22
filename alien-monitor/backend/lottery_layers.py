"""Agent Lottery node — topology anchor + live financial metrics for the monitor."""

from __future__ import annotations

import os
from typing import Any

DEFAULT_LOTTERY_URL = "https://lottery.modelmarket.dev"
TITHE_RATE = 0.20  # Hub sponsor.yaml default routing-fee tithe


def lottery_url() -> str:
    return (os.environ.get("ALIEN_LOTTERY_URL") or DEFAULT_LOTTERY_URL).rstrip("/")


def lottery_node_spec() -> dict[str, Any]:
    """Static lottery node fields shared by TEST / LIVE / UNI topologies."""
    return {
        "id": "lottery",
        "label": "Agent Lottery",
        "group": "economy",
        "icon": "lottery",
        "description": (
            "AI-agent oracle lottery — unbiasable draws (Platon + Chronos VDF), "
            "LUMEN-weighted, Hub-sponsored. Economic actor: Hub tithe in, opex to oracles, prizes to agents."
        ),
        "metrics": {
            "prize_pool_usd": 0,
            "round": 0,
            "players": 0,
            "payouts_24h": 0,
            "opex_24h": 0,
            "funding_24h": 0,
        },
        "status": "unknown",
        "position": {"x": 5, "y": 3, "z": 3},
        "url": lottery_url(),
    }


def lottery_financial_links(*, oracle_ids: list[str] | None = None) -> list[dict[str, str]]:
    """Directed financial edges: Hub sponsor → lottery → oracles; mesh → lottery tickets."""
    links = [
        {"source": "hub", "target": "lottery", "label": "Sponsor tithe"},
        {"source": "mesh", "target": "lottery", "label": "Agent tickets"},
    ]
    targets = oracle_ids or ["federation"]
    for oid in targets:
        links.append({"source": "lottery", "target": oid, "label": "Oracle draw"})
    return links


def _metrics_from_layers(
    hub_hints: dict[str, Any] | None,
    mesh_stats: dict[str, Any] | None,
) -> dict[str, float | int]:
    from live_lottery_feed import live_metrics_if_fresh

    live = live_metrics_if_fresh()
    if live:
        return live
    hints = hub_hints or {}
    mesh = mesh_stats if isinstance(mesh_stats, dict) else {}
    volume = float(hints.get("volume_24h") or 0)
    invocations = int(hints.get("invocations_24h") or 0)
    agents = int(mesh.get("agents") or mesh.get("agents_online") or 0)
    funding = round(volume * TITHE_RATE, 2)
    return {
        "prize_pool_usd": round(max(0.0, volume * 0.05), 2),
        "round": max(1, invocations // 50) if invocations else 0,
        "players": agents,
        "payouts_24h": round(volume * 0.03, 2),
        "opex_24h": round(volume * 0.02, 2),
        "funding_24h": funding,
    }


def _lottery_is_live(
    hub_hints: dict[str, Any] | None,
    mesh_stats: dict[str, Any] | None,
) -> bool:
    from live_lottery_feed import live_lottery_fresh

    if live_lottery_fresh():
        return True
    invocations = int((hub_hints or {}).get("invocations_24h") or 0)
    agents = int((mesh_stats or {}).get("agents") or (mesh_stats or {}).get("agents_online") or 0)
    return invocations > 0 or agents > 0


def apply_lottery_metrics(
    nodes: list[dict],
    *,
    hub_hints: dict[str, Any] | None = None,
    mesh_stats: dict[str, Any] | None = None,
) -> None:
    """Fill lottery node metrics from live Hub/Mesh layers (LIVE + UNI)."""
    lot = next((n for n in nodes if n.get("id") == "lottery"), None)
    if lot is None:
        return
    lot.setdefault("url", lottery_url())
    metrics = _metrics_from_layers(hub_hints, mesh_stats)
    lot["metrics"] = {**lot.get("metrics", {}), **metrics}
    lot["status"] = "active" if _lottery_is_live(hub_hints, mesh_stats) else "idle"


def apply_lottery_entity(
    entities: dict[str, Any],
    *,
    hub_hints: dict[str, Any] | None = None,
    mesh_stats: dict[str, Any] | None = None,
) -> None:
    """Update lottery EcosystemEntity in UNI runtime."""
    ent = entities.get("lottery")
    if ent is None:
        return
    ent.url = lottery_url()
    ent.metrics = _metrics_from_layers(hub_hints, mesh_stats)
    ent.status = "active" if _lottery_is_live(hub_hints, mesh_stats) else "idle"

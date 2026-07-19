"""METIS cognitive layer — topology anchor + graph links for Alien Monitor."""

from __future__ import annotations

from typing import Any

from ecosystem_layout import node_position
from metis_status import metis_links, metis_public_url


def metis_node_spec(*, mode: str = "real") -> dict[str, Any]:
    """Static METIS node fields shared by TEST / LIVE / UNI topologies."""
    _ = mode
    return {
        "id": "metis",
        "label": "METIS",
        "group": "cognition",
        "icon": "brain",
        "description": (
            "Distributed cognitive layer over any LLM. Understanding Council → "
            "confidence gate (fail-closed) → layered MoA → verifier. Returns a "
            "verify score and asks for clarification instead of guessing. "
            "Loosely-coupled peer: the factory runs without it, and it runs alone."
        ),
        "metrics": {
            "knowledge_entries": 0,
            "cluster_nodes": 0,
            "open_breakers": 0,
        },
        "status": "offline",
        "position": node_position("metis"),
        "url": metis_public_url(),
        "links": metis_links(),
        "chat": True,
    }


def metis_topology_links() -> list[dict[str, str]]:
    """Directed edges: cognition layer ↔ ecosystem (all optional at runtime)."""
    return [
        {"source": "factory", "target": "metis", "label": "Confidence gate"},
        {"source": "metis", "target": "hub", "label": "Verified capability"},
        {"source": "metis", "target": "plugins", "label": "MCP tools"},
    ]

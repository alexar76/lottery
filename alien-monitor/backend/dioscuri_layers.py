"""DIOSCURI community twins — topology anchor + graph links for Alien Monitor."""

from __future__ import annotations

import os
from typing import Any

from dioscuri_status import (
    dioscuri_community_links,
    dioscuri_public_url,
    dioscuri_theoros_collaboration,
    dioscuri_twin_children,
)
from ecosystem_layout import node_position


def dioscuri_node_spec(*, mode: str = "real") -> dict[str, Any]:
    """Static DIOSCURI node fields shared by TEST / LIVE / UNI topologies."""
    _ = mode
    links = dioscuri_community_links()
    return {
        "id": "dioscuri",
        "label": "DIOSCURI",
        "group": "community",
        "icon": "community",
        "description": (
            "Twin community agents — CASTOR (Telegram) and POLLUX (Discord). "
            "THEOROS collaborates on the weekly canon column (#the-canon) — separate persona, same process. "
            "Shared MNEMOSYNE knowledge base; AEGIS shield."
        ),
        "metrics": {
            "kb_chunks": 0,
            "kb_repos": 0,
            "uptime_sec": 0,
            "telegram": 0,
            "discord": 0,
        },
        "status": "offline",
        "position": node_position("dioscuri"),
        "url": dioscuri_public_url(),
        "community_links": links,
        "children": dioscuri_twin_children(),
        "collaboration": dioscuri_theoros_collaboration(),
    }


def dioscuri_topology_links() -> list[dict[str, str]]:
    """Directed edges: ecosystem ↔ community layer."""
    return [
        {"source": "factory", "target": "dioscuri", "label": "Community twins"},
        {"source": "dioscuri", "target": "hub", "label": "Ecosystem Q&A"},
        {"source": "dioscuri", "target": "argus", "label": "Twin promo"},
    ]

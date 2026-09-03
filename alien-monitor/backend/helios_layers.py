"""HELIOS broadcast node — topology anchor + graph links for Alien Monitor."""

from __future__ import annotations

from typing import Any

from ecosystem_layout import node_position
from helios_status import helios_public_url, helios_youtube_url


def helios_node_spec(*, mode: str = "real") -> dict[str, Any]:
    _ = mode
    return {
        "id": "helios",
        "label": "HELIOS",
        "group": "media",
        "icon": "broadcast",
        "description": (
            "Broadcast pipeline — template in, voiced video out, queued to YouTube. "
            "Private until operator approve. POST-only, no engagement bots."
        ),
        "metrics": {
            "subscribers": 0,
            "views": 0,
            "videos": 0,
            "queue_pending": 0,
            "uploaded_today": 0,
        },
        "status": "offline",
        "position": node_position("helios"),
        "url": helios_public_url(),
        "youtube_url": helios_youtube_url(),
    }


def helios_topology_links() -> list[dict[str, str]]:
    return [
        {"source": "factory", "target": "helios", "label": "DevRel delivery"},
        {"source": "dioscuri", "target": "helios", "label": "Release queue"},
    ]

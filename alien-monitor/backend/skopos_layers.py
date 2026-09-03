"""SKOPOS observability node — topology anchor + graph links for Alien Monitor."""

from __future__ import annotations

from typing import Any

from ecosystem_layout import node_position
from skopos_status import skopos_links, skopos_public_url


def skopos_node_spec(*, mode: str = "real") -> dict[str, Any]:
    _ = mode
    return {
        "id": "skopos",
        "label": "SKOPOS",
        "group": "observability",
        "icon": "radar",
        "description": (
            "Fleet observability satellite — nginx & Apache analytics over SSH, "
            "Security Center with 3D threat map, scan history, and an AI analyst. "
            "Self-hosted data; PostgreSQL recommended for production."
        ),
        "metrics": {
            "servers": 0,
            "requests_total": 0,
            "security_score": 0,
        },
        "status": "offline",
        "position": node_position("skopos"),
        "url": skopos_public_url(),
        "links": skopos_links(),
    }


def skopos_topology_links() -> list[dict[str, str]]:
    return [
        {"source": "factory", "target": "skopos", "label": "Traffic telemetry"},
        {"source": "skopos", "target": "metis", "label": "Host fleet"},
        {"source": "skopos", "target": "hub", "label": "Ecosystem posture"},
    ]

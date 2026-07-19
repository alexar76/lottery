"""Poll HELIOS GET /health and attach YouTube channel stats to the graph node."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)

DEFAULT_HELIOS_URL = "http://127.0.0.1:8791"
DEFAULT_PUBLIC_HELIOS_URL = "https://github.com/alexar76/helios"
DEFAULT_YOUTUBE_CHANNEL = "https://www.youtube.com/@My-AI-Factory"


def helios_poll_url(*, mode: str | None = None) -> str:
    _ = mode
    return (os.environ.get("ALIEN_HELIOS_URL") or os.environ.get("HELIOS_URL") or DEFAULT_HELIOS_URL).rstrip("/")


def helios_public_url(*, mode: str | None = None) -> str:
    _ = mode
    return (
        os.environ.get("ALIEN_PUBLIC_HELIOS_URL")
        or os.environ.get("HELIOS_PUBLIC_URL")
        or DEFAULT_PUBLIC_HELIOS_URL
    ).rstrip("/")


def helios_youtube_url() -> str:
    return (
        os.environ.get("ALIEN_HELIOS_YOUTUBE_URL")
        or os.environ.get("HELIOS_YOUTUBE_URL")
        or DEFAULT_YOUTUBE_CHANNEL
    ).rstrip("/")


def fetch_helios_health_sync(*, base_url: str | None = None, timeout: float = 4.0) -> dict[str, Any] | None:
    root = (base_url or helios_poll_url()).rstrip("/")
    url = f"{root}/health"
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(url)
            if r.status_code != 200:
                return None
            data = r.json()
            return data if isinstance(data, dict) else None
    except Exception as exc:
        log.warning("HELIOS health poll failed: %s %s", url, exc)
        return None


def apply_helios_to_nodes(
    nodes: list[dict],
    health: dict[str, Any] | None,
    *,
    public_url: str | None = None,
) -> None:
    node = next((n for n in nodes if n.get("id") == "helios"), None)
    if not node:
        return

    node["url"] = public_url or helios_public_url()
    node["youtube_url"] = helios_youtube_url()

    if not health or not health.get("ok"):
        node["status"] = "offline" if health is None else "error"
        node.pop("helios_live", None)
        return

    yt = health.get("youtube") if isinstance(health.get("youtube"), dict) else {}
    queue_pending = int(health.get("queue_pending") or 0)
    dry_run = bool(health.get("dryRun"))

    node["status"] = "active" if queue_pending > 0 or int(yt.get("videos") or 0) > 0 else "idle"
    node["helios_live"] = {
        "version": health.get("version"),
        "uptime_sec": health.get("uptimeSec"),
        "dry_run": dry_run,
        "queue_pending": queue_pending,
        "subscribers": yt.get("subscribers"),
        "views": yt.get("views"),
        "videos": yt.get("videos"),
        "cached_at": yt.get("cached_at"),
        "stale": yt.get("stale", False),
        "channel_title": yt.get("title"),
    }
    metrics = dict(node.get("metrics") or {})
    metrics.update({
        "subscribers": int(yt.get("subscribers") or 0),
        "views": int(yt.get("views") or 0),
        "videos": int(yt.get("videos") or 0),
        "queue_pending": queue_pending,
        "uploaded_today": int(health.get("uploaded_today") or 0),
    })
    node["metrics"] = metrics


def apply_helios_graph(nodes: list[dict], *, mode: str = "real") -> None:
    _ = mode
    health = fetch_helios_health_sync()
    apply_helios_to_nodes(nodes, health, public_url=helios_public_url())

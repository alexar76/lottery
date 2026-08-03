"""Poll SKOPOS public status (GET /healthz) for Alien Monitor."""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_SKOPOS_URL = "https://skopos.modelmarket.dev"
DEFAULT_PUBLIC_SKOPOS_URL = "https://skopos.modelmarket.dev"
DEFAULT_SKOPOS_GITHUB_URL = "https://github.com/alexar76/skopos"


def skopos_poll_url() -> str:
    return (
        os.environ.get("ALIEN_SKOPOS_URL")
        or os.environ.get("SKOPOS_URL")
        or DEFAULT_SKOPOS_URL
    ).rstrip("/")


def skopos_public_url() -> str:
    return (
        os.environ.get("ALIEN_PUBLIC_SKOPOS_URL")
        or os.environ.get("SKOPOS_PUBLIC_URL")
        or DEFAULT_PUBLIC_SKOPOS_URL
    ).rstrip("/")


def skopos_links() -> dict[str, str]:
    github = (
        os.environ.get("ALIEN_SKOPOS_GITHUB_URL")
        or os.environ.get("SKOPOS_GITHUB_URL")
        or DEFAULT_SKOPOS_GITHUB_URL
    ).rstrip("/")
    public = skopos_public_url()
    return {
        "dashboard": public,
        "github": github,
        "docs": f"{github}#documentation",
        "integration": "https://github.com/alexar76/aicom/blob/main/docs/ecosystem/skopos-integration.md",
    }


def fetch_skopos_status_sync(*, base_url: str | None = None, timeout: float = 5.0) -> dict[str, Any] | None:
    root = (base_url or skopos_poll_url()).rstrip("/")
    for path in ("/healthz", "/_stcore/health"):
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.get(f"{root}{path}")
                if r.status_code != 200:
                    continue
                if path.endswith("healthz"):
                    data = r.json()
                    return data if isinstance(data, dict) else None
                body = (r.text or "").strip().lower()
                if body == "ok":
                    return {"ok": True, "service": "skopos"}
        except Exception:
            continue
    return None


def apply_skopos_to_nodes(
    nodes: list[dict],
    status: dict[str, Any] | None,
    *,
    public_url: str | None = None,
) -> None:
    node = next((n for n in nodes if n.get("id") == "skopos"), None)
    if not node:
        return

    node["url"] = public_url or skopos_public_url()
    node["links"] = skopos_links()

    if not status or not status.get("ok"):
        node["status"] = "offline" if status is None else "error"
        node.pop("skopos_live", None)
        return

    servers = int(status.get("servers_monitored") or 0)
    requests_total = int(status.get("requests_total") or 0)
    security_score = status.get("security_score")
    db_backend = str(status.get("database") or "sqlite")

    node["status"] = "active" if servers > 0 or requests_total > 0 else "idle"
    node["skopos_live"] = {
        "database": db_backend,
        "log_parsers": status.get("log_parsers") or [],
        "servers_monitored": servers,
        "requests_total": requests_total,
        "security_score": security_score,
        "version": status.get("version"),
    }
    metrics = dict(node.get("metrics") or {})
    metrics.update(
        {
            "servers": servers,
            "requests_total": requests_total,
            "security_score": int(security_score) if isinstance(security_score, (int, float)) else 0,
        }
    )
    node["metrics"] = metrics


def apply_skopos_graph(nodes: list[dict], *, mode: str = "real") -> None:
    _ = mode
    status = fetch_skopos_status_sync()
    apply_skopos_to_nodes(nodes, status, public_url=skopos_public_url())

"""Poll DIOSCURI GET /health and attach MNEMOSYNE + adapter stats to the graph node."""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_DIOSCURI_URL = "http://127.0.0.1:8790"
DEFAULT_PUBLIC_DIOSCURI_URL = "https://alexar76.github.io/dioscuri/"
DEFAULT_THEOROS_URL = "https://alexar76.github.io/theoros/"
DEFAULT_TELEGRAM_BOT_URL = "https://t.me/next_agent_market_bot"
DEFAULT_TELEGRAM_CHANNEL_URL = "https://t.me/just_for_agents"
DEFAULT_DISCORD_URL = ""


def dioscuri_poll_url(*, mode: str | None = None) -> str:
    _ = mode
    return (os.environ.get("ALIEN_DIOSCURI_URL") or os.environ.get("DIOSCURI_URL") or DEFAULT_DIOSCURI_URL).rstrip("/")


def dioscuri_public_url(*, mode: str | None = None) -> str:
    _ = mode
    return (
        os.environ.get("ALIEN_PUBLIC_DIOSCURI_URL")
        or os.environ.get("DIOSCURI_PUBLIC_URL")
        or DEFAULT_PUBLIC_DIOSCURI_URL
    ).rstrip("/")


def dioscuri_theoros_url(*, mode: str | None = None) -> str:
    _ = mode
    return (
        os.environ.get("ALIEN_PUBLIC_THEOROS_URL")
        or os.environ.get("ALIEN_THEOROS_URL")
        or os.environ.get("THEOROS_URL")
        or DEFAULT_THEOROS_URL
    ).rstrip("/")


def dioscuri_community_links() -> dict[str, str]:
    """Optional Telegram / Discord invite URLs for the node detail panel."""
    links: dict[str, str] = {
        "github": (
            os.environ.get("ALIEN_DIOSCURI_GITHUB_URL")
            or os.environ.get("DIOSCURI_GITHUB_URL")
            or "https://github.com/alexar76/dioscuri"
        ).rstrip("/"),
    }
    telegram_bot = (
        os.environ.get("ALIEN_DIOSCURI_TELEGRAM_BOT_URL")
        or os.environ.get("DIOSCURI_TELEGRAM_BOT_URL")
        or DEFAULT_TELEGRAM_BOT_URL
    ).strip()
    telegram_channel = (
        os.environ.get("ALIEN_DIOSCURI_TELEGRAM_CHANNEL_URL")
        or os.environ.get("DIOSCURI_TELEGRAM_CHANNEL_URL")
        or os.environ.get("ALIEN_DIOSCURI_TELEGRAM_URL")
        or os.environ.get("DIOSCURI_TELEGRAM_URL")
        or DEFAULT_TELEGRAM_CHANNEL_URL
    ).strip()
    discord = (
        os.environ.get("ALIEN_DIOSCURI_DISCORD_URL")
        or os.environ.get("DIOSCURI_DISCORD_URL")
        or DEFAULT_DISCORD_URL
    ).strip()
    if telegram_bot:
        links["telegram"] = telegram_bot
    if telegram_channel:
        links["telegram_channel"] = telegram_channel
    if discord:
        links["discord"] = discord
    links["theoros"] = dioscuri_theoros_url()
    return links


def dioscuri_twin_children() -> list[dict[str, str]]:
    """CASTOR + POLLUX — the Dioscuri twins only (not THEOROS)."""
    links = dioscuri_community_links()
    children: list[dict[str, str]] = [
        {"id": "castor", "label": "CASTOR", "category": "telegram"},
        {"id": "pollux", "label": "POLLUX", "category": "discord"},
    ]
    if links.get("telegram"):
        children[0]["url"] = links["telegram"]
    if links.get("discord"):
        children[1]["url"] = links["discord"]
    return children


def dioscuri_theoros_collaboration(*, active: bool | None = None) -> dict[str, Any]:
    """THEOROS — separate persona, same DIOSCURI process; not a third twin."""
    links = dioscuri_community_links()
    collab: dict[str, Any] = {
        "id": "theoros",
        "label": "THEOROS · θ",
        "role": "canon theorist",
        "url": links["theoros"],
        "repo": "https://github.com/alexar76/theoros",
    }
    if active is not None:
        collab["active"] = active
    return collab


def fetch_dioscuri_health_sync(*, base_url: str | None = None, timeout: float = 4.0) -> dict[str, Any] | None:
    root = (base_url or dioscuri_poll_url()).rstrip("/")
    url = f"{root}/health"
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(url)
            if r.status_code != 200:
                return None
            data = r.json()
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def apply_dioscuri_to_nodes(
    nodes: list[dict],
    health: dict[str, Any] | None,
    *,
    public_url: str | None = None,
) -> None:
    """Merge live DIOSCURI /health into the singleton ``dioscuri`` graph node."""
    node = next((n for n in nodes if n.get("id") == "dioscuri"), None)
    if not node:
        return

    node["url"] = public_url or dioscuri_public_url()
    node["community_links"] = dioscuri_community_links()
    node["children"] = dioscuri_twin_children()

    if not health or not health.get("ok"):
        node["status"] = "offline" if health is None else "error"
        node["collaboration"] = dioscuri_theoros_collaboration(active=False)
        node.pop("dioscuri_live", None)
        return

    theoros_block = health.get("theoros") if isinstance(health.get("theoros"), dict) else {}
    theoros_active = bool(theoros_block.get("active"))
    node["collaboration"] = dioscuri_theoros_collaboration(active=theoros_active)

    adapters = health.get("adapters") if isinstance(health.get("adapters"), dict) else {}
    kb = health.get("kb") if isinstance(health.get("kb"), dict) else {}
    telegram_on = bool(adapters.get("telegram"))
    discord_on = bool(adapters.get("discord"))
    any_adapter = telegram_on or discord_on

    node["status"] = "active" if any_adapter or int(kb.get("chunks") or 0) > 0 else "idle"
    node["dioscuri_live"] = {
        "version": health.get("version"),
        "uptime_sec": health.get("uptimeSec"),
        "dry_run": bool(health.get("dryRun")),
        "telegram": telegram_on,
        "discord": discord_on,
        "kb_chunks": kb.get("chunks"),
        "kb_repos": kb.get("repos"),
        "kb_last_sync": kb.get("lastSyncAt"),
        "kb_sync_ok": kb.get("lastSyncOk"),
    }
    social = health.get("social") if isinstance(health.get("social"), dict) else {}
    if social:
        node["dioscuri_live"]["social"] = social
    node["dioscuri_live"]["theoros_active"] = theoros_active
    metrics = dict(node.get("metrics") or {})
    metrics.update({
        "kb_chunks": int(kb.get("chunks") or 0),
        "kb_repos": int(kb.get("repos") or 0),
        "uptime_sec": int(health.get("uptimeSec") or 0),
        "telegram": 1 if telegram_on else 0,
        "discord": 1 if discord_on else 0,
        "discord_members": int(social.get("discord_members") or 0),
        "telegram_members": int(social.get("telegram_members") or 0),
        "twitter_followers": int(social.get("twitter_followers") or 0),
    })
    node["metrics"] = metrics


def apply_dioscuri_graph(nodes: list[dict], *, mode: str = "real") -> None:
    """Poll DIOSCURI /health for the active monitor mode."""
    _ = mode
    health = fetch_dioscuri_health_sync()
    apply_dioscuri_to_nodes(nodes, health, public_url=dioscuri_public_url())

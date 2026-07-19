"""Poll METIS ``GET /health`` and proxy chat to its OpenAI-compatible API.

Everything here is best-effort and offline-safe: if Metis is not running the
node simply shows ``offline`` and the chat proxy returns a friendly error — the
rest of the monitor is unaffected (Metis and the monitor are independent).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_METIS_URL = "https://metis.modelmarket.dev"
# The live interactive landing (cosmic star + live cognition panel), served over
# HTTPS by the deployed node. Override with ALIEN_PUBLIC_METIS_URL / METIS_PUBLIC_URL.
DEFAULT_PUBLIC_METIS_URL = "https://metis.modelmarket.dev"
DEFAULT_METIS_GITHUB_URL = "https://github.com/alexar76/metis"


def metis_poll_url() -> str:
    return (
        os.environ.get("ALIEN_METIS_URL")
        or os.environ.get("METIS_URL")
        or DEFAULT_METIS_URL
    ).rstrip("/")


def metis_public_url() -> str:
    return (
        os.environ.get("ALIEN_PUBLIC_METIS_URL")
        or os.environ.get("METIS_PUBLIC_URL")
        or DEFAULT_PUBLIC_METIS_URL
    ).rstrip("/")


def metis_api_key() -> str:
    return (
        os.environ.get("ALIEN_METIS_API_KEY")
        or os.environ.get("METIS_API_KEY")
        or ""
    ).strip()


def metis_links() -> dict[str, str]:
    github = (
        os.environ.get("ALIEN_METIS_GITHUB_URL")
        or os.environ.get("METIS_GITHUB_URL")
        or DEFAULT_METIS_GITHUB_URL
    ).rstrip("/")
    return {
        # The interactive landing: cosmic star + live cognition panel (docs/landing).
        "landing": metis_public_url(),
        "github": github,
        "docs": f"{github}#readme",
    }


def _auth_headers() -> dict[str, str]:
    key = metis_api_key()
    return {"Authorization": f"Bearer {key}"} if key else {}


def fetch_metis_health_sync(*, base_url: str | None = None, timeout: float = 4.0) -> dict[str, Any] | None:
    root = (base_url or metis_poll_url()).rstrip("/")
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(f"{root}/health", headers=_auth_headers())
            if r.status_code != 200:
                return None
            data = r.json()
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def apply_metis_to_nodes(
    nodes: list[dict],
    health: dict[str, Any] | None,
    *,
    public_url: str | None = None,
) -> None:
    """Merge live METIS ``/health`` into the singleton ``metis`` graph node."""
    node = next((n for n in nodes if n.get("id") == "metis"), None)
    if not node:
        return

    node["url"] = public_url or metis_public_url()
    node["links"] = metis_links()

    if not health or health.get("status") not in ("ok", "healthy"):
        node["status"] = "offline" if health is None else "error"
        node.pop("metis_live", None)
        return

    raw_cluster = health.get("nodes") if isinstance(health.get("nodes"), list) else []
    # Don't surface internal node URLs in the public monitor graph — id/status only.
    cluster = [
        {"id": n.get("id"), "status": n.get("status"), "healthy": n.get("healthy")}
        for n in raw_cluster if isinstance(n, dict)
    ]
    breakers_raw = health.get("circuit_breakers")
    open_breakers = 0
    if isinstance(breakers_raw, dict):
        open_breakers = sum(
            1 for b in breakers_raw.values() if isinstance(b, dict) and b.get("state") == "open"
        )
    elif isinstance(breakers_raw, list):
        open_breakers = sum(
            1 for b in breakers_raw if isinstance(b, dict) and b.get("state") == "open"
        )
    knowledge = int(health.get("knowledge_entries") or 0)

    node["status"] = "active" if (cluster or knowledge or health.get("version")) else "idle"
    node["metis_live"] = {
        "version": health.get("version"),
        "service": health.get("service"),
        "cluster_nodes": len(cluster),
        "cluster": cluster[:8],
        "knowledge_entries": knowledge,
        "open_circuit_breakers": open_breakers,
    }
    metrics = dict(node.get("metrics") or {})
    metrics.update(
        {
            "knowledge_entries": knowledge,
            "cluster_nodes": len(cluster),
            "open_breakers": open_breakers,
        }
    )
    node["metrics"] = metrics


def apply_metis_graph(nodes: list[dict], *, mode: str = "real") -> None:
    """Poll METIS ``/health`` for the active monitor mode."""
    _ = mode
    health = fetch_metis_health_sync()
    apply_metis_to_nodes(nodes, health, public_url=metis_public_url())


async def metis_chat(
    messages: list[dict[str, Any]],
    *,
    model: str = "metis",
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Proxy a chat turn to Metis ``POST /v1/chat/completions`` (server-side key).

    Returns ``{"answer": str, "model": str}`` on success or ``{"error": str,
    "answer": str}`` on any failure — never raises, so a dead Metis degrades to a
    readable message in the panel instead of breaking the monitor.
    """
    root = metis_poll_url()
    # Defensive cap: keep the last N turns and bound each message size.
    trimmed: list[dict[str, Any]] = []
    for m in messages[-20:]:
        role = str(m.get("role") or "user")
        if role not in ("system", "user", "assistant"):
            role = "user"
        content = str(m.get("content") or "")[:8000]
        if content:
            trimmed.append({"role": role, "content": content})
    if not trimmed:
        return {"error": "empty", "answer": "Ask Metis something to begin."}

    payload = {"model": model or "metis", "messages": trimmed, "stream": False}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                f"{root}/v1/chat/completions",
                json=payload,
                headers={"Content-Type": "application/json", **_auth_headers()},
            )
        if r.status_code != 200:
            return {
                "error": f"metis returned {r.status_code}",
                "answer": f"Metis is unavailable (HTTP {r.status_code}).",
            }
        data = r.json()
        answer = ""
        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            answer = ""
        return {"answer": answer or "(empty response)", "model": data.get("model", model)}
    except Exception as exc:  # offline-safe
        return {
            "error": type(exc).__name__,
            "answer": "Metis is not reachable right now. Start it with `metis-serve` "
            "(or set METIS_URL) to chat here.",
        }

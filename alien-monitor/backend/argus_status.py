"""Poll the live ARGUS HTTP /health and attach wallet + economy to the argus node."""

from __future__ import annotations

import os
from typing import Any

import httpx

from onchain_refs import make_ref

DEFAULT_ARGUS_URL = "http://127.0.0.1:8787"
DEFAULT_ARGUS_UNI_URL = "http://127.0.0.1:8788"
DEFAULT_PUBLIC_ARGUS_URL = "https://magic-ai-factory.com/argus/arena"
DEFAULT_PUBLIC_ARGUS_UNI_URL = "https://magic-ai-factory.com/argus-uni/arena"


def argus_poll_url(*, mode: str | None = None) -> str:
    if mode == "universe":
        return (
            os.environ.get("ALIEN_ARGUS_UNI_URL")
            or os.environ.get("ARGUS_UNI_URL")
            or DEFAULT_ARGUS_UNI_URL
        ).rstrip("/")
    return (os.environ.get("ALIEN_ARGUS_URL") or os.environ.get("ARGUS_URL") or DEFAULT_ARGUS_URL).rstrip("/")


def argus_public_url() -> str:
    return (
        os.environ.get("ALIEN_PUBLIC_ARGUS_URL")
        or os.environ.get("ARGUS_PUBLIC_URL")
        or DEFAULT_PUBLIC_ARGUS_URL
    ).rstrip("/")


def argus_public_url_for_mode(mode: str | None = None) -> str:
    if mode == "universe":
        return (
            os.environ.get("ALIEN_PUBLIC_ARGUS_UNI_URL")
            or os.environ.get("ARGUS_PUBLIC_UNI_URL")
            or DEFAULT_PUBLIC_ARGUS_UNI_URL
        ).rstrip("/")
    return argus_public_url()


def _argus_http_token() -> str | None:
    tok = (os.environ.get("ALIEN_ARGUS_HTTP_TOKEN") or os.environ.get("ARGUS_HTTP_TOKEN") or "").strip()
    return tok or None


def fetch_argus_health_sync(*, base_url: str | None = None, timeout: float = 4.0) -> dict[str, Any] | None:
    root = (base_url or argus_poll_url()).rstrip("/")
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


def fetch_argus_status_sync(*, base_url: str | None = None, timeout: float = 4.0) -> dict[str, Any] | None:
    """Authenticated /status — wallet + chain details (not exposed on public /health)."""
    token = _argus_http_token()
    if not token:
        return None
    root = (base_url or argus_poll_url()).rstrip("/")
    url = f"{root}/status"
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(url, headers={"Authorization": f"Bearer {token}"})
            if r.status_code != 200:
                return None
            data = r.json()
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def merge_argus_runtime(
    health: dict[str, Any] | None,
    status: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Overlay wallet/chain from authenticated /status onto public /health fields."""
    if not health:
        return None
    merged = dict(health)
    if status and status.get("status") == "ok":
        for key in ("wallet", "chain", "chainNetwork", "chainId", "walletExplorer"):
            if key in status:
                merged[key] = status[key]
    return merged


async def fetch_argus_health_async(
    *,
    base_url: str | None = None,
    mode: str | None = None,
    timeout: float = 4.0,
) -> dict[str, Any] | None:
    root = (base_url or argus_poll_url(mode=mode)).rstrip("/")
    url = f"{root}/health"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return None
            data = r.json()
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def _onchain_ref_from_health(health: dict[str, Any]) -> dict[str, Any] | None:
    wallet = (health.get("wallet") or "").strip()
    if not wallet or health.get("economy") != "on":
        return None
    network = str(health.get("chainNetwork") or health.get("chain") or "Base")
    chain_id = health.get("chainId")
    explorer = (health.get("walletExplorer") or "").strip()
    try:
        import chain_net

        spec = chain_net.network("base")
        ref = make_ref(
            wallet,
            health.get("chainNetwork") or spec.display_name,
            int(chain_id) if chain_id is not None else spec.chain_id,
            explorer_tx=spec.explorer_tx,
            kind="wallet",
        )
    except Exception:
        ref = make_ref(
            wallet,
            network,
            int(chain_id) if chain_id is not None else 8453,
            kind="wallet",
        )
    if ref and explorer:
        ref["explorer"] = explorer
    return ref


def apply_argus_to_nodes(
    nodes: list[dict],
    health: dict[str, Any] | None,
    *,
    public_url: str | None = None,
) -> None:
    """Merge live ARGUS /health into the singleton ``argus`` graph node."""
    argus = next((n for n in nodes if n.get("id") == "argus"), None)
    if not argus:
        return

    argus["url"] = public_url or argus_public_url()

    if not health or health.get("status") != "ok":
        argus["status"] = "offline" if health is None else "error"
        argus.pop("argus_live", None)
        argus.pop("onchain", None)
        return

    argus["status"] = "active"
    economy = str(health.get("economy") or "off")
    argus["argus_live"] = {
        "economy": economy,
        "mode": health.get("mode"),
        "model": health.get("model"),
        "version": health.get("version"),
        "uptime_sec": health.get("uptimeSec"),
        "wallet": health.get("wallet"),
    }
    metrics = dict(argus.get("metrics") or {})
    metrics.update({
        "economy": economy,
        "uptime_sec": int(health.get("uptimeSec") or 0),
        "model": health.get("model") or "",
    })
    argus["metrics"] = metrics

    ref = _onchain_ref_from_health(health)
    if ref:
        argus["onchain"] = ref
    else:
        argus.pop("onchain", None)


def apply_argus_graph(nodes: list[dict], *, mode: str = "real") -> None:
    """Poll ARGUS /health for the active monitor mode and attach run panel data."""
    from argus_feed import argus_run_for_mode

    poll_mode = "universe" if mode == "universe" else "real"
    base = argus_poll_url(mode=poll_mode)
    health = fetch_argus_health_sync(base_url=base)
    status = fetch_argus_status_sync(base_url=base)
    apply_argus_to_nodes(nodes, merge_argus_runtime(health, status), public_url=argus_public_url_for_mode(poll_mode))

    argus = next((n for n in nodes if n.get("id") == "argus"), None)
    if argus is not None:
        run = argus_run_for_mode(mode)
        if run:
            argus["argus_run"] = run
        else:
            argus.pop("argus_run", None)

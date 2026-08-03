"""Sync AI-Factory catalog into star-cluster nodes (no overlapping product planets)."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_APP_URL = "http://127.0.0.1:9081"
DEFAULT_PUBLIC_FACTORY_URL = "https://magic-ai-factory.com"
DEFAULT_FETCH_TIMEOUT = 25.0
DEFAULT_MONITOR_CATALOG_TIMEOUT = 10.0
CATALOG_CLUSTER_ID = "cluster-catalog"

# Last good Factory catalog + consecutive fetch/empty failures (shared by UNI + LIVE).
_catalog_cache: list[dict[str, Any]] | None = None
_catalog_fail_streak: int = 0


def _catalog_fail_threshold() -> int:
    raw = (os.environ.get("ALIEN_FACTORY_CATALOG_FAIL_THRESHOLD") or "3").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 3


def factory_public_url() -> str:
    """Canonical storefront URL for links in the monitor UI (not the internal poll URL)."""
    return (
        os.environ.get("ALIEN_PUBLIC_FACTORY_URL")
        or os.environ.get("AIFACTORY_PUBLIC_URL")
        or os.environ.get("PUBLIC_SITE_URL")
        or DEFAULT_PUBLIC_FACTORY_URL
    ).rstrip("/")


def product_storefront_url(product_id: str, *, public_base: str | None = None) -> str:
    pid = str(product_id or "").strip()
    base = (public_base or factory_public_url()).rstrip("/")
    return f"{base}/product/{pid}"


def clear_factory_catalog_cache() -> None:
    """Test helper — reset cached catalog and failure streak."""
    global _catalog_cache, _catalog_fail_streak
    _catalog_cache = None
    _catalog_fail_streak = 0


def _fetch_timeout() -> float:
    raw = (os.environ.get("ALIEN_FACTORY_API_TIMEOUT") or "").strip()
    if raw:
        try:
            return max(3.0, float(raw))
        except ValueError:
            pass
    return DEFAULT_FETCH_TIMEOUT


def _monitor_catalog_timeout() -> float:
    raw = (os.environ.get("ALIEN_FACTORY_MONITOR_CATALOG_TIMEOUT") or "").strip()
    if raw:
        try:
            return max(2.0, float(raw))
        except ValueError:
            pass
    return DEFAULT_MONITOR_CATALOG_TIMEOUT


def fetch_factory_monitor_catalog_sync(
    app_url: str,
    *,
    timeout: float | None = None,
) -> list[dict[str, Any]] | None:
    """Return cached slim storefront rows with real product ids from Factory.

    ``None`` on transport/error or when Factory cache is still warming with no rows.
    ``[]`` when Factory reports an authoritative empty catalog.
    """
    effective_timeout = timeout if timeout is not None else _monitor_catalog_timeout()
    url = f"{app_url.rstrip('/')}/api/products/monitor-catalog"
    try:
        with httpx.Client(timeout=effective_timeout) as client:
            r = client.get(url)
            if r.status_code != 200:
                logger.warning(
                    "factory monitor-catalog fetch failed: %s status=%s",
                    url,
                    r.status_code,
                )
                return None
            data = r.json()
            if not isinstance(data, dict):
                return None
            products = list(data.get("products") or [])
            pending = bool(data.get("pending"))
            if pending and not products:
                logger.info("factory monitor-catalog still warming — no rows yet")
                return None
            return products
    except Exception as exc:
        logger.warning("factory monitor-catalog fetch failed: %s (%s)", url, exc)
        return None


def fetch_factory_products_sync(
    app_url: str,
    *,
    timeout: float | None = None,
) -> list[dict[str, Any]] | None:
    """Return storefront products, ``[]`` when API responds with none, ``None`` on transport/error."""
    effective_timeout = timeout if timeout is not None else _fetch_timeout()
    url = f"{app_url.rstrip('/')}/api/products"
    try:
        with httpx.Client(timeout=effective_timeout) as client:
            r = client.get(url)
            if r.status_code != 200:
                logger.warning(
                    "factory catalog fetch failed: %s status=%s",
                    url,
                    r.status_code,
                )
                return None
            data = r.json()
            return list(data.get("products") or [])
    except Exception as exc:
        logger.warning("factory catalog fetch failed: %s (%s)", url, exc)
        return None


def resolve_factory_catalog(
    app_url: str,
    *,
    timeout: float | None = None,
) -> tuple[list[dict[str, Any]] | None, bool]:
    """Return (products, authoritative).

    Prefer Factory's cached ``/api/products/monitor-catalog`` (real ids only), then the
    full storefront list. On transient errors, reuse the last good in-process cache.
    Never synthesizes placeholder product ids.
    """
    global _catalog_cache, _catalog_fail_streak

    fresh = fetch_factory_monitor_catalog_sync(app_url)
    source = "monitor-catalog"
    if fresh is None:
        fresh = fetch_factory_products_sync(app_url, timeout=timeout)
        source = "products"

    threshold = _catalog_fail_threshold()

    if fresh is None:
        _catalog_fail_streak += 1
        if _catalog_cache is not None:
            logger.warning(
                "factory catalog unreachable (streak %s/%s) — keeping %s cached products",
                _catalog_fail_streak,
                threshold,
                len(_catalog_cache),
            )
            return list(_catalog_cache), False
        return None, False

    if not fresh and _catalog_cache:
        _catalog_fail_streak += 1
        if _catalog_fail_streak < threshold:
            logger.warning(
                "factory catalog empty but cache has %s products (streak %s/%s) — keeping cache",
                len(_catalog_cache),
                _catalog_fail_streak,
                threshold,
            )
            return list(_catalog_cache), False
        logger.warning(
            "factory catalog empty after %s consecutive issues — accepting empty catalog",
            _catalog_fail_streak,
        )
        _catalog_cache = []
        _catalog_fail_streak = 0
        return [], True

    _catalog_fail_streak = 0
    _catalog_cache = list(fresh)
    if source == "monitor-catalog":
        logger.debug("factory catalog synced from monitor-catalog (%s products)", len(fresh))
    return list(fresh), True


def ensure_factory_clusters(
    nodes: list[dict],
    links: list[dict],
    app_url: str,
    *,
    catalog_timeout: float | None = None,
) -> int:
    """Attach factory star-clusters from the real storefront catalog (cached on Factory)."""
    catalog, authoritative = resolve_factory_catalog(app_url, timeout=catalog_timeout)
    if catalog is not None:
        return merge_factory_products(
            nodes,
            links,
            catalog,
            app_url=app_url,
            authoritative=authoritative,
        )
    return 0


def _cluster_key(product: dict[str, Any]) -> str:
    if product.get("is_template"):
        return "templates"
    cat = str(product.get("category") or "other").strip().lower()
    cat = re.sub(r"[^a-z0-9_-]+", "-", cat)[:32] or "other"
    return cat


def build_product_clusters(
    products: list[dict[str, Any]],
    *,
    existing_ids: set[str],
    factory_position: dict[str, float] | None = None,
    app_url: str = DEFAULT_APP_URL,
    id_prefix: str = "cluster",
) -> tuple[list[dict], list[dict]]:
    """One catalog nebula for all storefront products — categories live in children/metrics only."""
    if not products:
        return [], []

    fp = factory_position or {"x": 4, "y": 2, "z": -2}
    public_base = factory_public_url()
    cid = CATALOG_CLUSTER_ID if id_prefix == "cluster" else f"{id_prefix}-catalog"
    if cid in existing_ids:
        return [], []

    items = list(products)
    categories = {_cluster_key(p) for p in items}
    nodes: list[dict] = [
        {
            "id": cid,
            "label": f"Products · {len(items)}",
            "group": "cluster",
            "icon": "cluster",
            "description": f"Star cluster — {len(items)} factory products",
            "metrics": {
                "count": len(items),
                "categories": len(categories),
                "templates": sum(1 for x in items if x.get("is_template")),
            },
            "status": "active",
            "position": {
                "x": fp["x"] + 5.0,
                "y": fp["y"] + 0.4,
                "z": fp["z"] + 1.2,
            },
            "url": public_base,
            "children": [
                {
                    "id": str(p.get("id") or f"p{i}"),
                    "label": str(p.get("name") or p.get("id"))[:64],
                    "url": product_storefront_url(str(p.get("id") or f"p{i}"), public_base=public_base),
                    "category": _cluster_key(p),
                }
                for i, p in enumerate(items[:80])
            ],
        }
    ]
    links: list[dict] = [{"source": "factory", "target": cid, "label": "catalog"}]
    existing_ids.add(cid)
    return nodes, links


def merge_factory_products(
    nodes: list[dict],
    links: list[dict],
    products: list[dict[str, Any]] | None,
    *,
    app_url: str = DEFAULT_APP_URL,
    authoritative: bool = True,
) -> int:
    """Replace per-product nodes with spaced clusters; return cluster count."""
    if products is None:
        cached = _catalog_cache
        if cached:
            products = list(cached)
            authoritative = False
        else:
            return 0
    if not authoritative and not products:
        return 0
    nodes[:] = [n for n in nodes if n.get("group") not in ("product", "cluster")]
    links[:] = [
        lnk
        for lnk in links
        if not (
            lnk.get("target", "").startswith("cluster-")
            or lnk.get("target", "").startswith("prod-")
            or (lnk.get("source") == "factory" and lnk.get("label") == "published")
        )
    ]
    existing = {n["id"] for n in nodes}
    factory = next((n for n in nodes if n.get("id") == "factory"), None)
    fp = (factory or {}).get("position")
    extra_nodes, extra_links = build_product_clusters(
        products,
        existing_ids=existing,
        factory_position=fp,
        app_url=app_url,
    )
    nodes.extend(extra_nodes)
    links.extend(extra_links)
    if factory is not None:
        factory.setdefault("metrics", {})["products"] = sum(
            int((n.get("metrics") or {}).get("count") or 0) for n in extra_nodes
        )
        factory["status"] = "active"
    return len(extra_nodes)


def collapse_graph_products(
    nodes: list[dict],
    links: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Merge individual product nodes into clusters (UNI materialized planets, etc.)."""
    products: list[dict[str, Any]] = []
    for n in nodes:
        if n.get("group") != "product":
            continue
        m = n.get("metrics") or {}
        products.append({
            "id": n.get("id"),
            "name": n.get("label"),
            "category": m.get("category", "other"),
            "description": n.get("description"),
            "is_template": m.get("category") == "templates" or "template" in str(n.get("id", "")).lower(),
        })
    if not products:
        return nodes, links
    product_ids = {n["id"] for n in nodes if n.get("group") == "product"}
    core_nodes = [n for n in nodes if n.get("group") != "product"]
    core_links = [
        lnk
        for lnk in links
        if lnk.get("target") not in product_ids and lnk.get("source") not in product_ids
    ]
    merge_factory_products(core_nodes, core_links, products)
    return core_nodes, core_links

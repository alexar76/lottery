"""Hub-driven federation discovery for the Alien Monitor.

The monitor used to render a hand-written node list and only polled the hub's
``/ai-market/v2/stats/live``. New ecosystem nodes (e.g. Platon) never appeared
unless someone edited the topology by hand. This module closes that gap: it asks
the AIMarket Hub for its federation peers, reads each peer's self-declared
``/.well-known/ai-market.json`` categories, and — for nodes that advertise a
relevant capability (oracle / simulation / math-viz / randomness-beacon) — emits
a graph node hydrated with live metrics from the peer's ``/api/health`` (κ,
order_parameter, …). Nothing is hardcoded; a node appears the moment the hub
knows about it.

Security (the monitor fetches URLs the hub hands it, so they are untrusted):
  * SSRF guard — private/loopback/link-local/metadata ranges are blocked by
    default (opt in with allow_private for local universe sims). DNS is resolved,
    every returned IP is checked, and IPv6-embedded IPv4 forms (mapped, 6to4,
    NAT64, v4-compatible) are decoded and re-checked. For plain-HTTP peers the
    connection is **pinned to the vetted IP** (Host header preserved) so a
    rebind between the check and httpx's own resolution cannot reach an internal
    address (closes the classic getaddrinfo/connect TOCTOU for the http path).
  * Hard per-request and per-peer wall-clock deadlines (asyncio.wait_for) on top
    of httpx's per-read timeout, so a slowloris peer dribbling bytes can never
    hang the monitor tick or hold the state lock.
  * Response-size caps, JSON content-type required, redirects disabled, bounded
    fan-out + concurrency, a (url, allow_private)-keyed TTL cache, and strict
    numeric coercion (only finite, magnitude-bounded scalars reach node.metrics,
    which the frontend types as Record<string, number>).
  * Fault isolation — one bad/slow/malicious peer can never break the graph.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import socket
import threading
import time
from ipaddress import ip_address, ip_network
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "AlienMonitor-Discovery/1.0"

# Categories that make a federation peer worth rendering as a node.
_DEFAULT_CATEGORIES = {"oracle", "simulation", "math-viz", "randomness-beacon", "beacon"}

# Core graph node ids the discovery layer must never clobber.
_RESERVED_IDS = {
    "hub", "factory", "mesh", "acex", "evm_escrow", "solana_escrow", "nft_contract",
    "desktop_apps", "plugins", "sdk_dart", "sdk_typescript", "sdk_rust", "federation",
    "widget", "ethereum", "solana", "cli", "lottery", "argus", "dioscuri", "helios", "gaia", "oracle-cave-platon",
    *(f"oracle-{slug}" for slug in (
        "platon", "chronos", "lattice", "murmuration", "lumen", "colony", "turing",
        "ablation", "fermat", "landauer", "percola",
    )),
}

# The 3D anchor of the "federation" node in build_topology()/seed_entities().
_FED_ANCHOR = (-2.0, 5.0, 1.0)

_MAX_RESPONSE_BYTES = 512_000  # 0.5 MB cap for well-known / health
_METRIC_MAGNITUDE_CAP = 1_000_000_000_000  # clamp peer-supplied numbers

# Blocked IP ranges (RFC1918, loopback, link-local, cloud metadata, multicast).
_BLOCKED_NETS = [
    ip_network("10.0.0.0/8"), ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"), ip_network("127.0.0.0/8"),
    ip_network("169.254.0.0/16"), ip_network("0.0.0.0/8"),
    ip_network("100.64.0.0/10"), ip_network("224.0.0.0/4"),
    ip_network("fc00::/7"), ip_network("fe80::/10"), ip_network("::1/128"),
]
_NAT64 = ip_network("64:ff9b::/96")


# ── SSRF guard ──────────────────────────────────────────────────────


def _embedded_ipv4(addr):
    """Decode an embedded IPv4 from IPv4-mapped / 6to4 / NAT64 / v4-compatible IPv6."""
    for attr in ("ipv4_mapped", "sixtofour"):
        v = getattr(addr, attr, None)
        if v is not None:
            return v
    if getattr(addr, "version", 4) == 6:
        try:
            if addr in _NAT64:
                return ip_address(int(addr) & 0xFFFFFFFF)
            packed = int(addr)
            if packed >> 32 == 0 and (packed & 0xFFFFFFFF) > 1:  # ::a.b.c.d (not ::/::1)
                return ip_address(packed & 0xFFFFFFFF)
        except ValueError:
            return None
    return None


def _blocked_ip(addr) -> bool:
    """True if an IP (or its embedded IPv4) falls in a blocked network."""
    if any(addr in net for net in _BLOCKED_NETS):
        return True
    emb = _embedded_ipv4(addr)
    if emb is not None and any(emb in net for net in _BLOCKED_NETS):
        return True
    return False


def _resolved_ips(hostname: str) -> list:
    """Return parsed IPs for a hostname (literal or DNS), or [] if unresolvable."""
    try:
        return [ip_address(hostname)]
    except ValueError:
        pass
    try:
        out = []
        for info in socket.getaddrinfo(hostname, None):
            try:
                out.append(ip_address(info[4][0]))
            except ValueError:
                continue
        return out
    except (socket.gaierror, UnicodeError, ValueError):
        return []


def _is_private_host(hostname: str) -> bool:
    """True if a hostname is (or resolves to) a blocked network. Fail-closed."""
    if not hostname:
        return True
    ips = _resolved_ips(hostname)
    if not ips:
        return True  # unresolvable → unsafe
    return any(_blocked_ip(a) for a in ips)


def url_is_safe(url: str, *, allow_private: bool = False) -> bool:
    """Reject non-http(s) schemes, header-injection chars, and internal hosts."""
    if not url or not isinstance(url, str):
        return False
    if not url.startswith(("https://", "http://")):
        return False
    if any(c in url for c in "\r\n\t"):
        return False
    if allow_private:
        return True
    try:
        return not _is_private_host(urlparse(url).hostname or "")
    except Exception:
        return False


def _pin_http_target(url: str, *, allow_private: bool) -> tuple[str, dict[str, str]] | None:
    """For plain-HTTP, pin the connection to a freshly re-vetted IP (Host header
    preserved) to defeat DNS rebinding between the guard check and httpx's own
    resolution. Returns (request_url, extra_headers) or None if unsafe.

    HTTPS keeps the hostname (IP-pinning would break TLS SNI/cert validation);
    the pre-flight guard + the operator-trusted hub relay bound that residual.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if allow_private or parsed.scheme != "http" or not host:
        return url, {}
    ips = _resolved_ips(host)
    if not ips or any(_blocked_ip(a) for a in ips):
        return None
    chosen = ips[0]
    if str(chosen) == host:
        return url, {}
    netloc = f"[{chosen}]" if chosen.version == 6 else str(chosen)
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return parsed._replace(netloc=netloc).geturl(), {"Host": parsed.netloc}


# ── numeric coercion ────────────────────────────────────────────────


def _num(value: Any) -> float | int | None:
    """Return a finite, magnitude-bounded number, or None. Bools are not numbers.

    Ints are short-circuited before float() so huge JSON integers cannot raise
    OverflowError (which would otherwise drop the whole peer node)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, int):
        return max(-_METRIC_MAGNITUDE_CAP, min(value, _METRIC_MAGNITUDE_CAP))
    if math.isnan(value) or math.isinf(value):
        return None
    return round(max(-1e18, min(value, 1e18)), 6)


def _scalar_metrics(health: dict[str, Any], *, limit: int = 16) -> dict[str, float | int]:
    """Pull finite top-level numeric fields (κ, order_parameter, tick, …)."""
    out: dict[str, float | int] = {}
    if not isinstance(health, dict):
        return out
    for key, val in health.items():
        if len(out) >= limit:
            break
        if not isinstance(key, str) or len(key) > 48:
            continue
        n = _num(val)
        if n is not None:
            out[key] = n
    return out


# ── id / position helpers ───────────────────────────────────────────


def _slugify(value: str) -> str:
    s = "".join(c if (c.isalnum() or c in "-_") else "-" for c in value.lower()).strip("-")
    return s[:48] or "peer"


def _node_id(well_known: dict[str, Any], base_url: str) -> str:
    eco = well_known.get("ecosystem") if isinstance(well_known.get("ecosystem"), dict) else {}
    candidate = ""
    if isinstance(eco, dict) and isinstance(eco.get("project"), str):
        candidate = eco["project"]
    if not candidate and isinstance(well_known.get("name"), str):
        candidate = well_known["name"]
    if not candidate:
        candidate = urlparse(base_url).hostname or base_url
    slug = _slugify(candidate)
    return f"fed-{slug}" if slug in _RESERVED_IDS else slug


def _position_for(node_id: str) -> dict[str, float]:
    h = sum(ord(ch) for ch in node_id) or 1
    ang = (h % 360) * math.pi / 180.0
    radius = 3.2
    ax, ay, az = _FED_ANCHOR
    return {
        "x": round(ax + radius * math.cos(ang), 3),
        "y": round(ay + ((h % 5) - 2) * 0.55, 3),
        "z": round(az + radius * math.sin(ang), 3),
    }


# ── HTTP ────────────────────────────────────────────────────────────


async def _get_json(
    client: httpx.AsyncClient, url: str, *, allow_private: bool, timeout: float,
) -> Any | None:
    """Fetch JSON with SSRF guard, IP-pinning, hard deadline, size cap, JSON-only."""
    if not url_is_safe(url, allow_private=allow_private):
        return None
    pinned = _pin_http_target(url, allow_private=allow_private)
    if pinned is None:
        return None
    req_url, extra_headers = pinned
    headers = {"User-Agent": USER_AGENT, **extra_headers}

    async def _do() -> Any | None:
        async with client.stream("GET", req_url, follow_redirects=False, headers=headers) as resp:
            if resp.status_code != 200:
                return None
            # JSON-only — default-closed: a peer that omits Content-Type is rejected.
            ctype = resp.headers.get("content-type", "").lower()
            if "json" not in ctype:
                return None
            clen = resp.headers.get("content-length")
            if clen and clen.isdigit() and int(clen) > _MAX_RESPONSE_BYTES:
                return None
            body = b""
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                body += chunk
                if len(body) > _MAX_RESPONSE_BYTES:
                    return None
        import json
        return json.loads(body)

    try:
        # Hard wall-clock deadline on top of httpx's per-read timeout — a slowloris
        # drip cannot exceed this even if every single read stays under read-timeout.
        return await asyncio.wait_for(_do(), timeout=max(0.5, timeout))
    except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001 - degrade, never raise
        logger.debug("discovery fetch failed for %s: %s", url[:80], exc)
        return None


def _matches(categories: Any, wanted: set[str]) -> bool:
    if not isinstance(categories, list):
        return False
    return any(isinstance(c, str) and c.strip().lower() in wanted for c in categories)


# ── config ──────────────────────────────────────────────────────────


class DiscoveryConfig:
    """Resolved at call time so env changes / tests take effect immediately."""

    def __init__(self, *, allow_private: bool = False):
        self.enabled = os.getenv("ALIEN_DISCOVERY_ENABLED", "1").strip().lower() not in ("0", "false", "no")
        self.allow_private = allow_private or os.getenv("ALIEN_DISCOVERY_ALLOW_PRIVATE", "0").strip().lower() in ("1", "true", "yes")
        self.timeout = float(os.getenv("ALIEN_DISCOVERY_TIMEOUT_S", "4"))
        self.max_peers = max(1, int(os.getenv("ALIEN_DISCOVERY_MAX_PEERS", "25")))
        self.concurrency = max(1, int(os.getenv("ALIEN_DISCOVERY_CONCURRENCY", "8")))
        self.refresh_s = max(2.0, float(os.getenv("ALIEN_DISCOVERY_REFRESH_S", "20")))
        cats = os.getenv("ALIEN_DISCOVERY_CATEGORIES", "").strip()
        self.categories = (
            {c.strip().lower() for c in cats.split(",") if c.strip()} if cats else set(_DEFAULT_CATEGORIES)
        )

    @property
    def peer_deadline(self) -> float:
        """Wall-clock budget for one peer (well-known + health, sequential)."""
        return self.timeout * 2 + 1.0


# ── core ────────────────────────────────────────────────────────────


async def _build_peer_node(
    client: httpx.AsyncClient, peer: dict[str, Any], cfg: DiscoveryConfig,
) -> dict[str, Any] | None:
    """Resolve one peer into a graph node (or None if not a match / unsafe)."""
    base_url = (peer.get("url") or "").rstrip("/")
    if not base_url or not url_is_safe(base_url, allow_private=cfg.allow_private):
        return None

    categories = peer.get("categories")
    well_known: dict[str, Any] = {}

    # If the hub didn't carry categories (older hub), fetch the peer's well-known.
    if not isinstance(categories, list) or not categories:
        wk_url = peer.get("well_known_url") or f"{base_url}/.well-known/ai-market.json"
        wk = await _get_json(client, wk_url, allow_private=cfg.allow_private, timeout=cfg.timeout)
        if isinstance(wk, dict):
            well_known = wk
            categories = wk.get("categories")

    if not _matches(categories, cfg.categories):
        return None

    # Enrich with the peer's well-known (name / description / ecosystem) if not yet fetched.
    if not well_known:
        wk_url = peer.get("well_known_url") or f"{base_url}/.well-known/ai-market.json"
        wk = await _get_json(client, wk_url, allow_private=cfg.allow_private, timeout=cfg.timeout)
        if isinstance(wk, dict):
            well_known = wk

    node_id = _node_id(well_known, base_url)
    label = str(well_known.get("name") or peer.get("name") or node_id)[:80]
    cat_list = [str(c) for c in categories if isinstance(c, str)][:8]

    metrics: dict[str, float | int] = {}
    caps = _num(peer.get("capabilities_count"))
    if caps is not None:
        metrics["capabilities"] = caps
    trust = _num(peer.get("trust_score"))
    if trust is not None:
        metrics["trust_score"] = trust

    # Live health → κ / order_parameter / tick / viewers …
    status = "idle"
    health = await _get_json(client, f"{base_url}/api/health", allow_private=cfg.allow_private, timeout=cfg.timeout)
    if isinstance(health, dict):
        status = "active"
        for k, v in _scalar_metrics(health).items():
            metrics.setdefault(k, v)

    description = str(
        well_known.get("description")
        or f"Federation peer — {', '.join(cat_list) or 'discovered node'}"
    )[:240]

    from oracle_family import family_node_id_for_peer

    probe = {
        "id": node_id,
        "label": label,
        "url": base_url,
        "description": description,
    }
    if family_node_id_for_peer(probe):
        return None

    return {
        "id": node_id,
        "label": label,
        "group": "oracle",
        "icon": "oracle",
        "url": base_url,
        "description": description,
        "metrics": metrics,
        "status": status,
        "position": _position_for(node_id),
        "categories": cat_list,
        "discovered": True,
    }


async def discover_async(hub_url: str, *, allow_private: bool = False) -> dict[str, Any]:
    """Query the hub's federation peers and return discovered nodes + links.

    hub_url is the operator-configured (trusted) hub address — it is NOT
    SSRF-checked. Every peer/well-known/health URL the hub hands back IS checked.
    """
    cfg = DiscoveryConfig(allow_private=allow_private)
    result: dict[str, Any] = {"nodes": [], "links": [], "events": [], "peer_count": 0, "errors": []}
    if not cfg.enabled or not hub_url:
        return result

    base = hub_url.rstrip("/")
    timeout = httpx.Timeout(cfg.timeout, connect=cfg.timeout)
    limits = httpx.Limits(max_connections=cfg.concurrency, max_keepalive_connections=cfg.concurrency)
    try:
        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
            payload = await _get_json(
                client, f"{base}/ai-market/v2/federation/peers",
                allow_private=True,  # the hub itself is trusted/operator-configured
                timeout=cfg.timeout,
            )
            if not isinstance(payload, dict):
                result["errors"].append("federation/peers: no JSON")
                return result
            peers = payload.get("peers")
            if not isinstance(peers, list):
                return result
            peers = peers[: cfg.max_peers]
            result["peer_count"] = len(peers)

            sem = asyncio.Semaphore(cfg.concurrency)

            async def _one(p: dict[str, Any]) -> dict[str, Any] | None:
                if not isinstance(p, dict):
                    return None
                async with sem:
                    try:
                        # Per-peer wall-clock budget: a slow peer is dropped, the
                        # rest still render (and the tick is never held hostage).
                        return await asyncio.wait_for(
                            _build_peer_node(client, p, cfg), timeout=cfg.peer_deadline,
                        )
                    except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
                        logger.debug("peer node build failed: %s", exc)
                        return None

            nodes = [n for n in await asyncio.gather(*(_one(p) for p in peers)) if n]
    except Exception as exc:
        logger.warning("federation discovery failed: %s", exc)
        result["errors"].append(str(exc))
        return result

    # Dedupe by id; link each discovered node to the federation hub-node.
    seen: set[str] = set()
    for node in nodes:
        if node["id"] in seen:
            continue
        seen.add(node["id"])
        result["nodes"].append(node)
        result["links"].append({
            "source": "federation", "target": node["id"], "label": "Federation peer",
        })
    return result


# ── TTL cache + sync wrapper ────────────────────────────────────────

_cache_lock = threading.Lock()
# Keyed by (hub_url, allow_private) so a private-allowed UNI result is never
# served to the SSRF-guarded REAL path, and vice-versa.
_cache: dict[tuple[str, bool], tuple[float, dict[str, Any]]] = {}
_seen_peers: set[str] = set()


def _empty() -> dict[str, Any]:
    return {"nodes": [], "links": [], "events": [], "peer_count": 0, "errors": []}


def _with_events(data: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the graph data with a specific events list (shares nodes/links)."""
    return {**data, "events": events}


async def discover_cached_async(hub_url: str, *, allow_private: bool = False) -> dict[str, Any]:
    """Cached variant for the async (real-mode) path. Events are delivered ONLY on
    the refresh that discovers a peer — cache hits carry no events (no replay)."""
    cfg = DiscoveryConfig(allow_private=allow_private)
    key = (hub_url.rstrip("/"), bool(cfg.allow_private))
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < cfg.refresh_s:
            return _with_events(hit[1], [])
    fresh = await discover_async(hub_url, allow_private=allow_private)
    events = _new_peer_events(fresh)
    with _cache_lock:
        _cache[key] = (now, fresh)  # stored without delivered events
    return _with_events(fresh, events)


def discover_cached_sync(hub_url: str, *, allow_private: bool = False) -> dict[str, Any]:
    """Cached variant for the sync (universe-mode worker-thread) path.

    Safe to call from a worker thread (no running event loop); mirrors the
    asyncio.run usage already in universe_layers.fetch_layers_sync.
    """
    cfg = DiscoveryConfig(allow_private=allow_private)
    key = (hub_url.rstrip("/"), bool(cfg.allow_private))
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < cfg.refresh_s:
            return _with_events(hit[1], [])
    try:
        fresh = asyncio.run(discover_async(hub_url, allow_private=allow_private))
    except Exception as exc:
        logger.warning("sync discovery failed: %s", exc)
        return _empty()
    events = _new_peer_events(fresh)
    with _cache_lock:
        _cache[key] = (now, fresh)
    return _with_events(fresh, events)


def _new_peer_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Emit a one-off activity event the first time each peer is discovered."""
    events: list[dict[str, Any]] = []
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _cache_lock:
        for node in result.get("nodes", []):
            nid = node.get("id")
            if nid and nid not in _seen_peers:
                _seen_peers.add(nid)
                events.append({
                    "id": f"disco_{nid}_{int(time.time())}",
                    "ts": ts,
                    "agent": str(node.get("label") or nid)[:32],
                    "action": "federation_join",
                    "target": "federation",
                    "amount": 0,
                    "token": "",
                    "onchain": False,
                })
    return events

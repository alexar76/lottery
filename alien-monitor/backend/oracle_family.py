"""The 17-oracle family (+ Platon's UMBRAL cave) for Alien Monitor.

Seven math-as-a-service oracles (Platon, Chronos, Lattice, Murmuration, Lumen,
Colony, Turing), four physics oracles (Ablation, Fermat, Landauer, Percola), and
six advanced oracles (Sortes, Gauss, Aestus, Betti, Kantor, Fourier).
These nodes ALWAYS render. A node flips to status 'live' only when its endpoint
answers — see VirtualUniverse._poll_oracle_family.

Live stack runs on the **oracle host** (oracles.modelmarket.dev / 78.17.126.214).
Nginx paths mirror ``oracles/nginx/oracles.conf``:

  /api/          → Platon backend
  /platon/       → UMBRAL cave (same engine, human UI)
  /chronos/      → Chronos VDF (:9300)
  /family/       → oracle-family app — Lattice, Murmuration, Lumen, Colony, Turing
  /ablation/     → Ablation SOC cascade-risk (:9308)
  /fermat/       → Fermat least-time routing (:9307)
  /landauer/     → Landauer thermodynamic floor (:9309)
  /percola/      → Percola percolation threshold (:9306)

Override any base with ``ALIEN_ORACLE_<SLUG>_URL`` or ``ALIEN_ORACLE_PORTAL``.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

PORTAL = (os.environ.get("ALIEN_ORACLE_PORTAL") or "https://oracles.modelmarket.dev").rstrip("/")


def oracle_live_url(slug: str) -> str:
    """Health poll base for one family member (Monitor appends ``/api/health``)."""
    env_slug = slug.upper().replace("-", "_")
    override = os.environ.get(f"ALIEN_ORACLE_{env_slug}_URL", "").strip()
    if override:
        return override.rstrip("/")
    if slug == "platon":
        return (os.environ.get("ALIEN_ORACLE_PLATON_URL") or PORTAL).rstrip("/")
    if slug == "chronos":
        return (os.environ.get("ALIEN_ORACLE_CHRONOS_URL") or f"{PORTAL}/chronos").rstrip("/")
    if slug in _PHYSICS_SLUGS:
        return f"{PORTAL}/{slug}"
    family = (os.environ.get("ALIEN_ORACLE_FAMILY_URL") or f"{PORTAL}/family").rstrip("/")
    return family


_PHYSICS_SLUGS = frozenset({"ablation", "fermat", "landauer", "percola"})


# slug, name, accent, skill, capability ids, test count
ORACLE_FAMILY: list[dict] = [
    {"slug": "platon", "name": "Platon", "accent": "#6ee7ff", "tests": 65,
     "skill": "Verifiable randomness + dynamical oracle",
     "caps": ["platon.random@v1", "platon.beacon@v1", "platon.commit@v1", "platon.oracle@v1", "platon.ask@v1"]},
    {"slug": "chronos", "name": "Chronos", "accent": "#c084fc", "tests": 8,
     "skill": "Verifiable delay — proof of elapsed sequential time",
     "caps": ["chronos.eval@v1", "chronos.verify@v1"]},
    {"slug": "lattice", "name": "Lattice", "accent": "#7dd3fc", "tests": 13,
     "skill": "Low-discrepancy (quasi-random) sequences",
     "caps": ["lattice.sequence@v1"]},
    {"slug": "murmuration", "name": "Murmuration", "accent": "#f472b6", "tests": 15,
     "skill": "Robust consensus aggregation",
     "caps": ["murmuration.aggregate@v1"]},
    {"slug": "lumen", "name": "Lumen", "accent": "#fbbf24", "tests": 18,
     "skill": "Reputation & trust scores",
     "caps": ["lumen.reputation@v1"]},
    {"slug": "colony", "name": "Colony", "accent": "#34d399", "tests": 12,
     "skill": "Optimization with a quality certificate",
     "caps": ["colony.optimize@v1"]},
    {"slug": "turing", "name": "Turing", "accent": "#a78bfa", "tests": 13,
     "skill": "Blue-noise structured sampling",
     "caps": ["turing.bluenoise@v1"]},
    # Physics oracles (ARGUS-3 / WARDEN gates — systemic risk, routing, thermodynamics, resilience)
    {"slug": "ablation", "name": "Ablation", "accent": "#fb7185", "tests": 34,
     "skill": "Systemic cascade risk — abelian sandpile / SOC tail distribution",
     "caps": ["ablation.cascade@v1", "ablation.verify@v1"]},
    {"slug": "fermat", "name": "Fermat", "accent": "#38bdf8", "tests": 24,
     "skill": "Least-time routing with dual optimality certificate",
     "caps": ["fermat.route@v1", "fermat.verify@v1"]},
    {"slug": "landauer", "name": "Landauer", "accent": "#f97316", "tests": 35,
     "skill": "Thermodynamic compute-cost floor (Landauer limit)",
     "caps": ["landauer.audit@v1", "landauer.verify@v1"]},
    {"slug": "percola", "name": "Percola", "accent": "#4ade80", "tests": 15,
     "skill": "Network percolation threshold — tipping-point resilience",
     "caps": ["percola.threshold@v1", "percola.verify@v1"]},
    # Advanced oracles (Jun 2026, ports 9310-9315) — served via the family app
    {"slug": "sortes", "name": "Sortes", "accent": "#fde047", "tests": 30,
     "skill": "Trustless verifiable randomness — ECVRF (RFC 9381)",
     "caps": ["sortes.draw@v1", "sortes.verify@v1"]},
    {"slug": "gauss", "name": "Gauss", "accent": "#2dd4bf", "tests": 18,
     "skill": "Gaussian-process uncertainty field + active sampling (Expected Improvement)",
     "caps": ["gauss.field@v1", "gauss.suggest@v1", "gauss.verify@v1"]},
    {"slug": "aestus", "name": "Aestus", "accent": "#f59e0b", "tests": 16,
     "skill": "Verifiable timed-release — RSW time-lock puzzle (seal-then-auto-open)",
     "caps": ["aestus.seal@v1", "aestus.open@v1", "aestus.verify@v1"]},
    {"slug": "betti", "name": "Betti", "accent": "#e879f9", "tests": 14,
     "skill": "Topological data analysis — persistent homology (Betti numbers)",
     "caps": ["betti.homology@v1", "betti.distance@v1"]},
    {"slug": "kantor", "name": "Kantor", "accent": "#60a5fa", "tests": 23,
     "skill": "Optimal transport / Wasserstein with a dual optimality certificate",
     "caps": ["kantor.transport@v1", "kantor.verify@v1"]},
    {"slug": "fourier", "name": "Fourier", "accent": "#a3e635", "tests": 17,
     "skill": "Spectral / graph-Laplacian — Fiedler value (λ₂), spectral cut",
     "caps": ["fourier.spectrum@v1", "fourier.verify@v1"]},
]

# Inject live_url after definition (keeps table readable).
for _o in ORACLE_FAMILY:
    _o["live_url"] = oracle_live_url(_o["slug"])

# Platon's interactive educational product — a distinct node from the platon.* oracle.
CAVE: dict = {
    "id": "oracle-cave-platon",
    "name": "Platon · UMBRAL cave",
    "accent": "#6ee7ff",
    "skill": "32D shadow-oracle cave — live, steerable, educational",
    "url": f"{PORTAL}/platon/umbral",
    "parent_slug": "platon",
    "live_url": (os.environ.get("ALIEN_CAVE_PLATON_URL") or f"{PORTAL}/platon").rstrip("/"),
}


def oracle_node_id(slug: str) -> str:
    return f"oracle-{slug}"


def scene_url(slug: str) -> str:
    """Full-screen 3D scene for this oracle on the family portal."""
    return f"{PORTAL}/?o={slug}"


def ring_position(index: int, total: int) -> dict:
    """Delegate to shared ecosystem layout (east-sector oracle ring)."""
    from ecosystem_layout import ring_position as layout_ring

    return layout_ring(index, total)


def family_node_id_for_peer(n: dict[str, Any]) -> str | None:
    """Map a hub-discovered peer onto a family oracle node id (never duplicate Platon)."""
    hay = " ".join(
        str(n.get(k) or "") for k in ("id", "label", "url", "description")
    ).lower()
    url = str(n.get("url") or "").lower()

    if ("cave" in hay or "umbral" in hay) and "platon" in hay:
        return CAVE["id"]
    if "/platon/" in url and ("umbral" in url or "cave" in hay):
        return CAVE["id"]

    for slug in _PHYSICS_SLUGS:
        if f"/{slug}" in url or f"/{slug}/" in url:
            return oracle_node_id(slug)
    if "/chronos" in url:
        return oracle_node_id("chronos")

    if "oracle family" in hay or ("/family" in url and "oracles.modelmarket" in url):
        return oracle_node_id("platon")

    for o in ORACLE_FAMILY:
        slug = o["slug"]
        if slug in hay or f"/{slug}" in url or f"oracle-{slug}" in hay:
            return oracle_node_id(slug)

    if "shadow" in hay and ("platon" in hay or "oracles.modelmarket" in url or ":9200" in url):
        return oracle_node_id("platon")
    return None


def build_oracle_family_nodes() -> list[dict[str, Any]]:
    """Always-present 17 oracles + Platon cave — same ring layout as UNI mode."""
    nodes: list[dict[str, Any]] = []
    total = len(ORACLE_FAMILY)
    for i, o in enumerate(ORACLE_FAMILY):
        eid = oracle_node_id(o["slug"])
        nodes.append({
            "id": eid,
            "label": o["name"],
            "group": "oracle",
            "icon": "oracle",
            "description": f"{o['skill']} · caps: {', '.join(o['caps'])}",
            "metrics": {
                "capability_count": len(o["caps"]),
                "tests": o["tests"],
                "deployed": 1 if o.get("live_url") else 0,
                "live": 0,
            },
            "status": "idle",
            "position": ring_position(i, total),
            "url": scene_url(o["slug"]),
            "color": o["accent"],
            "parent_id": "federation",
        })

    plat = next((n for n in nodes if n["id"] == oracle_node_id(CAVE["parent_slug"])), None)
    cave_pos = {"x": 0.0, "y": 0.0, "z": 0.0}
    if plat:
        pp = plat["position"]
        cave_pos = {
            "x": round(pp["x"] + 1.6, 3),
            "y": round(pp["y"] - 1.1, 3),
            "z": round(pp["z"] + 1.2, 3),
        }
    nodes.append({
        "id": CAVE["id"],
        "label": CAVE["name"],
        "group": "oracle",
        "icon": "cave",
        "description": CAVE["skill"],
        "metrics": {"live": 0},
        "status": "idle",
        "position": cave_pos,
        "url": CAVE["url"],
        "color": CAVE["accent"],
        "parent_id": oracle_node_id(CAVE["parent_slug"]),
    })
    return nodes


def oracle_family_links(existing_ids: set[str]) -> list[dict[str, str]]:
    """Federation → family oracles, lottery draw targets, cave off Platon."""
    links: list[dict[str, str]] = []
    draw_ids = [
        oracle_node_id(o["slug"])
        for o in ORACLE_FAMILY
        if o["slug"] in ("platon", "chronos", "lumen") and oracle_node_id(o["slug"]) in existing_ids
    ]
    if not draw_ids and "federation" in existing_ids:
        draw_ids = ["federation"]
    from lottery_layers import lottery_financial_links

    links.extend(lottery_financial_links(oracle_ids=draw_ids))
    for o in ORACLE_FAMILY:
        oid = oracle_node_id(o["slug"])
        if oid in existing_ids and "federation" in existing_ids:
            links.append({"source": "federation", "target": oid, "label": "oracle family"})
    plat_id = oracle_node_id(CAVE["parent_slug"])
    if CAVE["id"] in existing_ids and plat_id in existing_ids:
        links.append({"source": plat_id, "target": CAVE["id"], "label": "UMBRAL cave"})
    return links


def append_oracle_family_graph(nodes: list[dict], links: list[dict]) -> None:
    """Ensure the 17-oracle ring + cave exist in any mode graph (TEST/LIVE/UNI REST)."""
    existing = {n.get("id") for n in nodes}
    for node in build_oracle_family_nodes():
        if node["id"] not in existing:
            nodes.append(node)
            existing.add(node["id"])
    link_keys = {(l.get("source"), l.get("target")) for l in links}
    for link in oracle_family_links(existing):
        key = (link.get("source"), link.get("target"))
        if key not in link_keys:
            links.append(link)
            link_keys.add(key)


def _apply_health_to_node(node: dict[str, Any], health: dict[str, Any]) -> None:
    node["status"] = "active"
    metrics = node.setdefault("metrics", {})
    metrics["live"] = 1
    for k in ("tick", "viewers", "capabilities", "kappa", "order_parameter"):
        v = health.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            metrics[k] = v
    caps = health.get("capabilities")
    if isinstance(caps, int) and "capabilities" not in metrics:
        metrics["capabilities"] = caps


def poll_oracle_family_nodes(nodes: list[dict[str, Any]], *, timeout: float = 1.5) -> None:
    """Poll remote oracle health endpoints and hydrate family node metrics."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    by_id = {n["id"]: n for n in nodes if n.get("id")}
    targets: list[tuple[str, str]] = [
        (oracle_node_id(o["slug"]), o.get("live_url", "")) for o in ORACLE_FAMILY
    ]
    targets.append((CAVE["id"], CAVE.get("live_url", "")))

    def _poll_one(eid: str, base: str) -> tuple[str, dict[str, Any] | None]:
        if not base:
            return eid, None
        try:
            req = urllib.request.Request(
                f"{base.rstrip('/')}/api/health",
                headers={"User-Agent": "alien-monitor", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                if getattr(resp, "status", 200) == 200:
                    body = json.loads(resp.read(65536).decode("utf-8", "replace"))
                    if isinstance(body, dict) and body.get("status") == "ok":
                        return eid, body
        except Exception:
            pass
        return eid, None

    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
        futures = [pool.submit(_poll_one, eid, base) for eid, base in targets if eid in by_id]
        for fut in as_completed(futures):
            eid, health = fut.result()
            node = by_id.get(eid)
            if node is None:
                continue
            if isinstance(health, dict):
                _apply_health_to_node(node, health)
            else:
                node.setdefault("metrics", {})["live"] = 0


def merge_discovered_peers(
    nodes: list[dict[str, Any]],
    links: list[dict[str, Any]],
    disc: dict[str, Any],
) -> None:
    """Fold hub discovery into the graph — family peers enrich ring nodes, never duplicate."""
    by_id = {n["id"]: n for n in nodes if n.get("id")}
    existing = set(by_id)
    link_keys = {(l.get("source"), l.get("target")) for l in links}

    for dn in disc.get("nodes", []):
        if not isinstance(dn, dict):
            continue
        fam_id = family_node_id_for_peer(dn)
        if fam_id and fam_id in by_id:
            target = by_id[fam_id]
            if dn.get("status") == "active":
                target["status"] = "active"
                target.setdefault("metrics", {})["live"] = 1
            for k, v in (dn.get("metrics") or {}).items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    target.setdefault("metrics", {})[k] = v
            if dn.get("url"):
                target["discovered_url"] = dn["url"]
            continue
        if fam_id:
            continue
        nid = dn.get("id")
        if not nid or nid in existing:
            continue
        nodes.append(dn)
        by_id[nid] = dn
        existing.add(nid)

    for link in disc.get("links", []):
        target = link.get("target")
        if target and family_node_id_for_peer({"id": target, "label": target}):
            continue
        key = (link.get("source"), link.get("target"))
        if key not in link_keys:
            links.append(link)
            link_keys.add(key)

    fed = by_id.get("federation")
    if fed is not None and disc.get("peer_count"):
        fed.setdefault("metrics", {})["peers"] = disc["peer_count"]
        fed["status"] = "active"

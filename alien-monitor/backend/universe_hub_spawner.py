"""
Hub Spawner — creates new federated hubs in the UNI ecosystem.

New hubs register with the main Hub via the federation announce endpoint.
Each spawned hub gets capabilities with a distinct theme, an entity node
in the 3D graph, and a federation link to the main hub.

Spawns are deliberately infrequent — the user asked for "не часто" (not often).
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from universe import VirtualUniverse, EcosystemEntity

HUB_NAMES = [
    "Hydra Node", "Nexus Prime", "Quantum Bridge", "Stellar Gate",
    "Void Forge", "Apex Mesh", "Cipher Vault", "Nova Link",
    "Echo Grid", "Prism Hub", "Flux Relay", "Atlas Core",
]

HUB_CAPABILITY_THEMES = {
    "Hydra Node": [
        ("compute.render@v1", "GPU rendering pipeline", 3.50, "infra"),
        ("ml.inference@v1", "ML model inference endpoint", 2.00, "data"),
        ("data.process@v1", "ETL orchestration", 1.50, "data"),
    ],
    "Nexus Prime": [
        ("market.analyze@v1", "Real-time market analysis", 4.00, "finance"),
        ("sentiment.scan@v1", "Social sentiment scanner", 1.50, "data"),
        ("trend.predict@v1", "Trend forecasting engine", 3.00, "data"),
    ],
    "Quantum Bridge": [
        ("quantum.simulate@v1", "Quantum circuit simulator", 5.00, "infra"),
        ("crypto.verify@v1", "Zero-knowledge proof verifier", 2.50, "security"),
        ("entropy.generate@v1", "High-entropy random generator", 0.50, "infra"),
    ],
    "Stellar Gate": [
        ("nft.mint@v1", "NFT collection minter", 2.00, "content"),
        ("dao.propose@v1", "DAO proposal generator", 1.50, "legal"),
        ("token.swap@v1", "Cross-chain token swap", 3.00, "finance"),
    ],
    "Void Forge": [
        ("contract.audit@v1", "Smart contract auditor", 5.00, "security"),
        ("exploit.scan@v1", "Vulnerability scanner", 4.00, "security"),
        ("gas.optimize@v1", "Gas optimization engine", 2.00, "code"),
    ],
    "Apex Mesh": [
        ("api.gateway@v1", "API gateway configurator", 1.50, "infra"),
        ("load.balance@v1", "Auto-scaling load balancer", 2.00, "infra"),
        ("health.monitor@v1", "Service health monitor", 1.00, "infra"),
    ],
}


class HubSpawner:
    """Creates new federated hubs in the UNI ecosystem."""

    def __init__(self, hub_url: str = "http://127.0.0.1:9083", interval_ticks: int = 300):
        self.hub_url = hub_url.rstrip("/")
        self.interval_ticks = interval_ticks
        self.spawned_hubs: list[dict] = []
        self.last_spawn_tick = 0
        self._used_names: set[str] = set()

    def tick(self, current_tick: int, vu: VirtualUniverse) -> dict | None:
        if current_tick - self.last_spawn_tick < self.interval_ticks:
            return None

        self.last_spawn_tick = current_tick

        available = [n for n in HUB_NAMES if n not in self._used_names]
        if not available:
            return None

        name = random.choice(available)
        self._used_names.add(name)

        hub_port = 9083 + len(self.spawned_hubs) + 1
        hub_url = f"http://127.0.0.1:{hub_port}"

        capabilities = self._generate_capabilities(name)
        self._spawned_hubs.append({
            "name": name,
            "url": hub_url,
            "capabilities": len(capabilities),
            "tick": current_tick,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

        self._materialize_entity(name, hub_url, capabilities, vu)

        self._announce_to_federation(name, hub_url, capabilities)

        event = {
            "type": "hub_spawned",
            "id": f"hub_spawn_{len(self.spawned_hubs)}",
            "name": name,
            "url": hub_url,
            "capabilities": len(capabilities),
            "tick": current_tick,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        print(f"[HubSpawner] New hub: {name} @ {hub_url} ({len(capabilities)} capabilities)")
        return event

    def _generate_capabilities(self, hub_name: str) -> list[dict]:
        theme = HUB_CAPABILITY_THEMES.get(hub_name, [
            (f"{hub_name.lower().replace(' ', '-')}.generic@v1", f"Generic capability from {hub_name}", 1.00, "general"),
        ])

        caps = []
        for cap_id, desc, price, cat in theme:
            caps.append({
                "capability_id": cap_id,
                "name": cap_id.split("@")[0],
                "description": desc,
                "price_per_call_usd": price,
                "category": cat,
                "source_hub": hub_name.lower().replace(" ", "-"),
                "trust_score": round(random.uniform(0.75, 0.98), 4),
            })
        return caps

    def _materialize_entity(self, name: str, hub_url: str, capabilities: list[dict], vu: VirtualUniverse) -> None:
        from universe import EcosystemEntity

        eid = f"federated_{name.lower().replace(' ', '_')}"
        entity = EcosystemEntity(eid, name, "federated_hub", "network", icon="globe")
        entity.description = f"Federated hub: {len(capabilities)} capabilities"
        entity.status = "active"
        entity.url = hub_url
        entity.metrics = {
            "capabilities": len(capabilities),
            "peers": 1,
            "invocations_24h": 0,
        }

        main_hub = vu.entities.get("hub")
        if main_hub:
            entity.position = {
                "x": main_hub.position["x"] + random.uniform(-4, 4),
                "y": main_hub.position["y"] + random.uniform(-4, 4),
                "z": main_hub.position["z"] + random.uniform(-4, 4),
            }

        vu.entities[eid] = entity
        print(f"[HubSpawner] Entity materialized: {eid}")

    def _announce_to_federation(self, name: str, hub_url: str, capabilities: list[dict]) -> None:
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.post(
                    f"{self.hub_url}/ai-market/v2/federation/announce",
                    json={
                        "hub_url": hub_url,
                        "well_known_url": f"{hub_url}/.well-known/ai-market.json",
                        "hub_name": name,
                        "signer_public_key": "uni-simulated-key",
                    },
                )
                if r.status_code == 200:
                    print(f"[HubSpawner] Federation announce OK: {name}")
                else:
                    print(f"[HubSpawner] Federation announce HTTP {r.status_code}: {r.text[:200]}")
        except httpx.ConnectError:
            print(f"[HubSpawner] Federation announce skipped — Hub not reachable (will retry on crawl)")
        except Exception as exc:
            print(f"[HubSpawner] Federation announce error: {exc}")

"""
Poll live ecosystem layers for UNI mode — Hub, Mesh, Factory, Prometheus, local chain.

No simulated metrics: if a service is down, nodes stay idle/unknown with zero values.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

from chain_metrics import (
    apply_chain_metrics_to_nodes,
    build_real_summary,
    fetch_onchain_snapshot,
    hub_events_to_activity,
)

# Default URLs for the locally deployed aicom stack (docker-compose).
DEFAULT_HUB_URL = "http://127.0.0.1:9083"
DEFAULT_MESH_URL = "http://127.0.0.1:8090"
DEFAULT_APP_URL = "http://127.0.0.1:9081"
DEFAULT_PROM_URL = "http://127.0.0.1:9090/prometheus"


def layer_urls() -> dict[str, str]:
    return {
        "hub": (os.environ.get("ALIEN_UNIVERSE_HUB_URL") or os.environ.get("HUB_URL") or DEFAULT_HUB_URL).rstrip("/"),
        "mesh": (os.environ.get("ALIEN_UNIVERSE_MESH_URL") or os.environ.get("MESH_URL") or DEFAULT_MESH_URL).rstrip("/"),
        "app": (os.environ.get("ALIEN_UNIVERSE_APP_URL") or os.environ.get("AICOM_API_URL") or DEFAULT_APP_URL).rstrip("/"),
        "prom": (os.environ.get("ALIEN_UNIVERSE_PROM_URL") or os.environ.get("PROMETHEUS_URL") or DEFAULT_PROM_URL).rstrip("/"),
    }


def _get(client: httpx.Client, url: str) -> tuple[Any | None, str | None]:
    try:
        r = client.get(url)
        if r.status_code == 200:
            return r.json(), None
        return None, f"{url} -> HTTP {r.status_code}"
    except Exception as exc:
        return None, f"{url} unreachable: {exc}"


def fetch_layers_sync(
    *,
    evm_rpc: str,
    contracts: dict[str, str | None],
    chain_label: str = "EVM",
    timeout: float = 6.0,
) -> dict[str, Any]:
    """Synchronous poll of all UNI ecosystem layers + local chain RPC."""
    urls = layer_urls()
    out: dict[str, Any] = {
        "urls": urls,
        "errors": [],
        "hub": None,
        "mesh": None,
        "factory": None,
        "prometheus": None,
        "plugins": None,
        "agents": [],
        "events": [],
        "hub_hints": {},
        "chain": None,
    }

    with httpx.Client(timeout=timeout) as client:
        hub_data, err = _get(client, f"{urls['hub']}/ai-market/v2/stats/live")
        if err:
            out["errors"].append(err)
        else:
            out["hub"] = hub_data
            events, hints = hub_events_to_activity(hub_data if isinstance(hub_data, dict) else {})
            out["events"] = events
            out["hub_hints"] = hints

        mesh_data, err = _get(client, f"{urls['mesh']}/v1/stats")
        if err:
            out["errors"].append(err)
        else:
            out["mesh"] = mesh_data

        agents_data, err = _get(client, f"{urls['mesh']}/v1/agents")
        if err:
            out["errors"].append(err)
        elif isinstance(agents_data, list):
            out["agents"] = agents_data

        factory_data, err = _get(client, f"{urls['app']}/api/health")
        if err:
            out["errors"].append(err)
        else:
            out["factory"] = factory_data

        try:
            r = client.get(f"{urls['prom']}/api/v1/query", params={"query": "pipeline_tasks_total"})
            if r.status_code == 200:
                out["prometheus"] = r.json()
            else:
                out["errors"].append(f"prometheus -> HTTP {r.status_code}")
        except Exception as exc:
            out["errors"].append(f"prometheus unreachable: {exc}")

        plugins_data, err = _get(client, f"{urls['hub']}/ai-market/v2/plugins")
        if err:
            out["errors"].append(err)
        else:
            out["plugins"] = plugins_data

    # Local chain — force universe RPC + deployed contract addresses
    prev_rpc = os.environ.get("ALIEN_EVM_RPC")
    prev_chain = os.environ.get("ALIEN_EVM_CHAIN")
    os.environ["ALIEN_EVM_RPC"] = evm_rpc
    os.environ["ALIEN_EVM_CHAIN"] = chain_label
    if contracts.get("escrow_evm"):
        os.environ["AIMARKET_ESCROW_EVM_ADDRESS"] = contracts["escrow_evm"]
    if contracts.get("nft_evm"):
        os.environ["AIMARKET_NFT_CONTRACT"] = contracts["nft_evm"]
    if contracts.get("payment_recipient"):
        os.environ["AIMARKET_PAYMENT_RECIPIENT"] = contracts["payment_recipient"]

    import asyncio

    try:
        out["chain"] = asyncio.run(fetch_onchain_snapshot(timeout=timeout))
        out["errors"].extend(out["chain"].get("errors") or [])
    except Exception as exc:
        out["errors"].append(f"chain poll: {exc}")
        out["chain"] = {"errors": [str(exc)], "evm": None, "solana": None}
    finally:
        if prev_rpc is None:
            os.environ.pop("ALIEN_EVM_RPC", None)
        else:
            os.environ["ALIEN_EVM_RPC"] = prev_rpc
        if prev_chain is None:
            os.environ.pop("ALIEN_EVM_CHAIN", None)
        else:
            os.environ["ALIEN_EVM_CHAIN"] = prev_chain

    return out


def _pipeline_task_counts(prom: dict | None) -> tuple[int, int]:
    """Return (pending-ish, done-ish) from prometheus pipeline_tasks_total if present."""
    if not isinstance(prom, dict):
        return 0, 0
    try:
        results = prom.get("data", {}).get("result", [])
        done = 0
        for row in results:
            val = row.get("value", [None, "0"])
            done += int(float(val[1]))
        return 0, done
    except (TypeError, ValueError, IndexError):
        return 0, 0


def apply_layers_to_entities(entities: dict, layers: dict[str, Any]) -> None:
    """Update ecosystem entity metrics/status from polled layer data."""
    hub = entities.get("hub")
    if hub and (layers.get("hub") or layers.get("hub_hints")):
        hub.status = "active"
        hints = layers.get("hub_hints") or {}
        hub.metrics["invocations_24h"] = int(hints.get("invocations_24h") or 0)
        hub.metrics["channels_open"] = int(hints.get("channels_open") or 0)
        hub.metrics["capabilities"] = int(hints.get("capabilities") or hub.metrics.get("capabilities") or 0)
        hub.metrics["peers"] = int(hints.get("peers") or hub.metrics.get("peers") or 0)
    elif hub:
        hub.status = "idle"

    mesh_ent = entities.get("mesh")
    mesh = layers.get("mesh")
    if mesh_ent and isinstance(mesh, dict):
        mesh_ent.status = "active"
        mesh_ent.metrics["agents"] = int(mesh.get("agents") or mesh.get("agents_online") or len(layers.get("agents") or []))
        mesh_ent.metrics["tasks"] = int(mesh.get("tasks") or mesh.get("tasks_total") or 0)
        mesh_ent.metrics["activity"] = int(mesh.get("activity") or mesh.get("events_total") or 0)
    elif mesh_ent:
        mesh_ent.status = "idle"

    factory = entities.get("factory")
    if factory and layers.get("factory"):
        factory.status = "active"
        _, tasks_done = _pipeline_task_counts(layers.get("prometheus"))
        factory.metrics["tasks_done"] = tasks_done
        factory.metrics["tasks_pending"] = int(factory.metrics.get("tasks_pending") or 0)
        factory.metrics["products"] = len([e for e in entities.values() if e.group == "product"])
    elif factory:
        factory.status = "idle"

    plugins = entities.get("plugins")
    pdata = layers.get("plugins")
    if plugins and isinstance(pdata, dict):
        plist = pdata.get("plugins") or []
        if isinstance(plist, list):
            plugins.status = "active"
            plugins.metrics["loaded"] = len(plist)
            plugins.metrics["total"] = len(plist)

    acex = entities.get("acex")
    if acex:
        vol = float((layers.get("hub_hints") or {}).get("volume_24h") or 0)
        acex.metrics["volume_24h"] = vol
        acex.status = "active" if vol > 0 else "idle"

    chain = layers.get("chain") or {}
    evm = chain.get("evm") or {}
    if entities.get("ethereum") and evm.get("connected"):
        entities["ethereum"].status = "active"
        entities["ethereum"].metrics = {
            "chain_id": evm.get("chain_id", 0),
            "block": evm.get("block", 0),
            "gas": evm.get("gas_gwei", 0),
            "tx_count": evm.get("tx_count", 0) if "tx_count" in evm else 0,
            "rpc": evm.get("rpc", ""),
        }

    sol = chain.get("solana") or {}
    if entities.get("solana") and sol.get("connected"):
        entities["solana"].status = "active"
        entities["solana"].metrics = {
            "slot": sol.get("slot", 0),
            "block_height": sol.get("block_height", 0),
            "tps": 0,
            "rpc": sol.get("rpc", ""),
        }

    # Contract nodes via chain_metrics helper on node list
    node_list = [e.to_node() for e in entities.values()]
    apply_chain_metrics_to_nodes(node_list, chain)
    by_id = {n["id"]: n for n in node_list}
    for eid, ent in entities.items():
        if eid in by_id:
            ent.metrics.update(by_id[eid].get("metrics") or {})
            ent.status = by_id[eid].get("status", ent.status)


def sync_agent_entities(entities: dict, agents: list[dict], agents_registry: list[dict]) -> None:
    """Replace placeholder agents with agents registered in AI Service Mesh."""
    from universe import EcosystemEntity

    for key in list(entities.keys()):
        if key.startswith("agent_"):
            del entities[key]
    agents_registry.clear()
    for i, ag in enumerate(agents[:24]):
        if not isinstance(ag, dict):
            continue
        aid = str(ag.get("id") or ag.get("agent_id") or f"agent_{i}")
        name = str(ag.get("name") or ag.get("display_name") or aid)
        ent = EcosystemEntity(f"agent_{aid}", name, "agent", "agent", icon="planet")
        ent.metrics = {
            "invocations": int(ag.get("invocations") or ag.get("tasks_completed") or 0),
            "channels_open": int(ag.get("channels_open") or 0),
            "balance_eth": 0,
            "verified": 1 if ag.get("verified") else 0,
        }
        ent.status = "active" if ag.get("verified", True) else "idle"
        entities[ent.id] = ent
        agents_registry.append({"id": ent.id, "name": name, "balance": 0})


def build_universe_summary(
    *,
    tick: int,
    layers: dict[str, Any],
    agents_count: int,
    products_count: int,
    onchain_tx_count: int,
) -> dict[str, Any]:
    chain = layers.get("chain") or {}
    summary = build_real_summary(
        tick=tick,
        hub_hints=layers.get("hub_hints") or {},
        mesh_stats=layers.get("mesh") if isinstance(layers.get("mesh"), dict) else None,
        chain=chain,
    )
    summary["mode"] = "universe"
    summary["agents_online"] = agents_count
    summary["products_created"] = products_count
    summary["onchain_tx_count"] = onchain_tx_count
    summary["blockchain_ready"] = bool((chain.get("evm") or {}).get("connected"))
    summary["tvl_usd"] = 0
    _, tasks_done = _pipeline_task_counts(layers.get("prometheus"))
    if tasks_done:
        summary["apps_online"] = min(9, max(0, tasks_done // 10))
    return summary

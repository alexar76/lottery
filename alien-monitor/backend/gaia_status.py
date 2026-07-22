"""Poll the GAIA physical-oracle gateway for the Alien Monitor ``gaia`` node.

GAIA is the ecosystem's **third oracle class** (math oracles → cognitive METIS →
physical GAIA): virtual IoT devices whose every reading is Ed25519-attested by a
per-device key and plausibility-verified before a buyer is billed. This module is
best-effort and offline-safe — if GAIA is unreachable the node simply shows
``offline`` and the rest of the monitor is unaffected (GAIA and the monitor are
independent).

Two FREE reads build the node (no channel, no debit):

    GET  /health                  → service / version / device count
    POST /ai-market/v2/invoke     → gaia.fleet.status@v1 (free device registry:
                                    model, site, fields+units, online, fault, source)

The ``source`` field is the honesty marker: ``null`` → a deterministic simulator;
a hostname → a live relay wrapping a real public sensor API (NWS, openSenseMap,
OGC SensorThings).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

# The deployed gateway (also reachable at gaia.modelmarket.dev). Override with
# ALIEN_GAIA_URL / GAIA_URL for the poll target, ALIEN_PUBLIC_GAIA_URL /
# GAIA_PUBLIC_URL for the link shown in the panel.
DEFAULT_GAIA_URL = "https://iot.modelmarket.dev"
DEFAULT_PUBLIC_GAIA_URL = "https://iot.modelmarket.dev"
DEFAULT_GAIA_GITHUB_URL = "https://github.com/alexar76/gaia"


def gaia_poll_url() -> str:
    return (
        os.environ.get("ALIEN_GAIA_URL")
        or os.environ.get("GAIA_URL")
        or DEFAULT_GAIA_URL
    ).rstrip("/")


def gaia_public_url() -> str:
    return (
        os.environ.get("ALIEN_PUBLIC_GAIA_URL")
        or os.environ.get("GAIA_PUBLIC_URL")
        or DEFAULT_PUBLIC_GAIA_URL
    ).rstrip("/")


def gaia_links() -> dict[str, str]:
    github = (
        os.environ.get("ALIEN_GAIA_GITHUB_URL")
        or os.environ.get("GAIA_GITHUB_URL")
        or DEFAULT_GAIA_GITHUB_URL
    ).rstrip("/")
    return {
        # The interactive R3F landing (cosmic canvas + live sensor dashboard).
        "landing": gaia_public_url(),
        "github": github,
        "docs": f"{github}#readme",
    }


def _sanitize_devices(raw: Any) -> list[dict[str, Any]]:
    """Trim the fleet-status device registry to what the panel needs.

    Drops internal-only fields (e.g. device pubkeys) and normalises ``fields``
    from a {name: unit} map to an ordered [{name, unit}] list the UI renders.
    """
    devices: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return devices
    for d in raw:
        if not isinstance(d, dict):
            continue
        fields_raw = d.get("fields") if isinstance(d.get("fields"), dict) else {}
        fields = [{"name": str(k), "unit": str(v)} for k, v in fields_raw.items()]
        source = d.get("source")
        devices.append(
            {
                "id": str(d.get("device_id") or "?"),
                "model": str(d.get("model") or ""),
                "site": str(d.get("site") or ""),
                "firmware": str(d.get("firmware") or ""),
                "fields": fields,
                "online": bool(d.get("online", True)),
                "fault": str(d.get("fault") or "none"),
                "readings_recorded": int(d.get("readings_recorded") or 0),
                # A non-null source host means this device relays a real public
                # API; null means it is a deterministic simulator.
                "source": (str(source) if source else None),
                "live": bool(source),
            }
        )
    return devices


def fetch_gaia_status_sync(
    *, base_url: str | None = None, timeout: float = 4.0
) -> dict[str, Any] | None:
    """Return ``{"health": {...}, "devices": [...]}`` or ``None`` if GAIA is down."""
    root = (base_url or gaia_poll_url()).rstrip("/")
    try:
        with httpx.Client(timeout=timeout) as client:
            h = client.get(f"{root}/health")
            if h.status_code != 200:
                return None
            health = h.json()
            if not isinstance(health, dict):
                return None
            devices: list[dict[str, Any]] = []
            try:
                r = client.post(
                    f"{root}/ai-market/v2/invoke",
                    json={
                        "product_id": "gaia.gateway",
                        "capability_id": "gaia.fleet.status@v1",
                        "source_hub": "local",
                        "input": {},
                    },
                )
                if r.status_code == 200:
                    body = r.json()
                    out = body.get("output") if isinstance(body, dict) else None
                    if isinstance(out, dict):
                        devices = _sanitize_devices(out.get("devices"))
            except Exception:
                devices = []  # health alone still marks the node active
            return {"health": health, "devices": devices}
    except Exception:
        return None


def _live_payload(health: dict[str, Any], devices: list[dict[str, Any]]) -> dict[str, Any]:
    online = sum(1 for d in devices if d.get("online"))
    live_relays = sum(1 for d in devices if d.get("live"))
    device_count = int(health.get("devices") or len(devices))
    return {
        "version": health.get("version"),
        "service": health.get("service"),
        "device_count": device_count,
        "online": online,
        "live_relays": live_relays,
        # True when NO device relays a real upstream API (whole fleet simulated).
        "simulated": live_relays == 0,
        "devices": devices[:12],
    }


def apply_gaia_to_nodes(
    nodes: list[dict],
    status: dict[str, Any] | None,
    *,
    public_url: str | None = None,
) -> None:
    """Merge a live GAIA status into the singleton ``gaia`` graph node."""
    node = next((n for n in nodes if n.get("id") == "gaia"), None)
    if not node:
        return

    node["url"] = public_url or gaia_public_url()
    node["links"] = gaia_links()

    if not status:
        node["status"] = "offline"
        node.pop("gaia_live", None)
        node["metrics"] = {"devices": 0, "online": 0, "live_relays": 0}
        return

    health = status.get("health") or {}
    devices = status.get("devices") or []
    payload = _live_payload(health, devices)
    node["status"] = "active" if (payload["device_count"] or health.get("status") == "ok") else "idle"
    node["gaia_live"] = payload
    node["metrics"] = {
        "devices": payload["device_count"],
        "online": payload["online"],
        "live_relays": payload["live_relays"],
    }


def apply_gaia_graph(nodes: list[dict], *, mode: str = "real") -> None:
    """Poll GAIA ``/health`` + free fleet status for the active monitor mode."""
    _ = mode
    status = fetch_gaia_status_sync()
    apply_gaia_to_nodes(nodes, status, public_url=gaia_public_url())


# ── TEST mode: a static representative fleet (never touches the network) ───────

def gaia_demo_devices() -> list[dict[str, Any]]:
    """The deployed demo fleet, mirrored statically for TEST/offline snapshots."""

    def dev(did: str, model: str, fields: list[tuple[str, str]]) -> dict[str, Any]:
        return {
            "id": did,
            "model": model,
            "site": "demo-site-1",
            "firmware": "1.0.0",
            "fields": [{"name": n, "unit": u} for n, u in fields],
            "online": True,
            "fault": "none",
            "readings_recorded": 0,
            "source": None,
            "live": False,
        }

    return [
        dev("ws-01", "GAIA-WS1 (BME280-class + anemometer)",
            [("temperature_c", "cel"), ("humidity_pct", "percent"),
             ("pressure_hpa", "hPa"), ("wind_mps", "m/s")]),
        dev("ws-02", "GAIA-WS1 (BME280-class + anemometer)",
            [("temperature_c", "cel"), ("humidity_pct", "percent"),
             ("pressure_hpa", "hPa"), ("wind_mps", "m/s")]),
        dev("aq-01", "GAIA-AQ1 (SDS011-class PM + SCD30-class CO2)",
            [("pm2_5_ugm3", "ug/m3"), ("pm10_ugm3", "ug/m3"),
             ("co2_ppm", "ppm"), ("voc_index", "index")]),
        dev("em-01", "GAIA-EM1 (Shelly-EM-class)",
            [("voltage_v", "V"), ("current_a", "A"),
             ("power_w", "W"), ("energy_wh", "Wh")]),
    ]


def fill_gaia_sim_node(node: dict) -> None:
    """Populate the ``gaia`` node with the static demo fleet (TEST mode)."""
    devices = gaia_demo_devices()
    node["url"] = gaia_public_url()
    node["links"] = gaia_links()
    node["status"] = "active"
    node["gaia_live"] = {
        "version": "0.1.0",
        "service": "gaia",
        "device_count": len(devices),
        "online": len(devices),
        "live_relays": 0,
        "simulated": True,
        "devices": devices,
    }
    node["metrics"] = {"devices": len(devices), "online": len(devices), "live_relays": 0}

"""Load alexar76 satellite catalog from scripts/satellite-map.yaml for AI prompts."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_BACKEND_ROOT = Path(__file__).resolve().parent
_MONITOR_ROOT = _BACKEND_ROOT.parent


def _aicom_root() -> Path:
    for key in ("AICOM_ROOT", "AICOM_MONOREPO_ROOT"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return Path(raw)
    return _MONITOR_ROOT.parent


def _map_paths() -> list[Path]:
    root = _aicom_root()
    return [
        root / "scripts" / "satellite-map.yaml",
        _MONITOR_ROOT / "scripts" / "satellite-map.yaml",
        _BACKEND_ROOT / "data" / "satellite-map.yaml",
    ]


@lru_cache(maxsize=1)
def load_satellites() -> list[dict[str, Any]]:
    for path in _map_paths():
        if not path.is_file():
            continue
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        sats = data.get("satellites")
        if isinstance(sats, list):
            return [s for s in sats if isinstance(s, dict) and s.get("id")]
    return []


def build_ecosystem_registry_context(*, max_items: int = 48) -> str:
    """Compact satellite list for LLM system prompts."""
    org = "alexar76"
    lines: list[str] = [
        f"GitHub org **{org}** — loosely-coupled AIMarket / AICOM satellites (monorepo source of truth: aicom):",
        "",
    ]
    count = 0
    for sat in load_satellites():
        if count >= max_items:
            lines.append(f"… and {len(load_satellites()) - max_items} more satellites in satellite-map.yaml.")
            break
        sid = str(sat.get("id", ""))
        repo = str(sat.get("repo") or sid)
        desc = str(sat.get("description") or "").strip()
        home = str(sat.get("homepage") or "").strip()
        optional = sat.get("optional") is True
        tag = " (profile README)" if optional else ""
        line = f"- **{sid}** → github.com/{org}/{repo}{tag}: {desc}"
        if home:
            line += f" · {home}"
        lines.append(line)
        count += 1
    if count == 0:
        return ""
    lines.append("")
    lines.append(
        "When users ask about a satellite by name, explain its role and point to its homepage/repo. "
        "On the 3D map, core runtime peers appear as glowing nodes (hub, factory, mesh, argus, "
        "dioscuri, helios, metis, skopos, gaia, oracles, …)."
    )
    return "\n".join(lines)

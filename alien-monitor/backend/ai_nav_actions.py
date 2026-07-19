"""Detect map-navigation intents from AI chat questions."""

from __future__ import annotations

import re
from typing import Any

# Core nodes the monitor can focus — aliases cover EN / RU / transliterations.
NODE_ALIASES: dict[str, tuple[str, ...]] = {
    "skopos": ("skopos", "σκοπός", "скопос", "скopos"),
    "metis": ("metis", "μῆτις", "метис", "μητις"),
    "dioscuri": ("dioscuri", "диоскур", "castor", "pollux", "mnemosyne"),
    "helios": ("helios", "гелиос", "helios agent"),
    "gaia": ("gaia", "гайя", "гея", "iot", "айот", "датчик", "сенсор", "sensor"),
    "theoros": ("theoros", "теорос", "the canon", "the-canon"),
    "argus": ("argus", "аргус", "argus-3", "argus3"),
    "hub": ("hub", "хаб", "aimarket hub", "aimarket"),
    "factory": ("factory", "фабрик", "ai-factory", "ai factory"),
    "mesh": ("mesh", "service mesh", "меш", "ai service mesh"),
    "acex": ("acex",),
    "federation": ("federation", "федерац"),
    "lottery": ("lottery", "лотере"),
    "plugins": ("plugins", "плагин"),
    "desktop_apps": ("desktop", "десктоп", "flutter apps"),
    "platon": ("platon", "платон", "umbral"),
    "lumen": ("lumen", "люmen", "репутац"),
}

NAV_VERBS = (
    "show", "open", "find", "zoom", "focus", "fly", "navigate", "go to", "take me",
    "center", "highlight", "select", "display", "bring",
    "покаж", "найди", "открой", "перейди", "сфокус", "центр", "выведи", "открой",
    "muéstr", "muestr", "encuentr", "abre", "naveg", "enfoc", "centr",
)

CORE_GRAPH_NODES = frozenset(NODE_ALIASES.keys()) | {
    "ethereum", "solana", "evm_escrow", "solana_escrow", "nft_contract",
    "sdk_dart", "sdk_typescript", "sdk_rust", "cli", "widget",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _match_node(question: str) -> str | None:
    q = _normalize(question)
    best: tuple[int, str] | None = None
    for node_id, aliases in NODE_ALIASES.items():
        for alias in aliases:
            if alias in q:
                score = len(alias)
                if best is None or score > best[0]:
                    best = (score, node_id)
    return best[1] if best else None


def _has_nav_intent(question: str) -> bool:
    q = _normalize(question)
    if any(v in q for v in NAV_VERBS):
        return True
    # "where is skopos" / "где skopos"
    if ("where" in q or "где" in q or "dónde" in q or "donde" in q) and _match_node(q):
        return True
    return False


def resolve_nav_actions(question: str, state: dict | None = None) -> list[dict[str, Any]]:
    """Return client actions (e.g. focus_node) when the user asks to show a map node."""
    node_id = _match_node(question)
    if not node_id or not _has_nav_intent(question):
        return []

    if state:
        ids = {n.get("id") for n in (state.get("nodes") or []) if isinstance(n, dict)}
        if ids and node_id not in ids and node_id not in CORE_GRAPH_NODES:
            return []

    focus_id = node_id
    if node_id == "theoros":
        focus_id = "dioscuri"

    return [{"type": "focus_node", "node_id": focus_id, "requested_id": node_id}]


def nav_focus_label(node_id: str, locale: str = "en") -> str:
    labels = {
        "skopos": ("SKOPOS", "SKOPOS", "SKOPOS"),
        "metis": ("METIS", "METIS", "METIS"),
        "dioscuri": ("DIOSCURI", "DIOSCURI", "DIOSCURI"),
        "helios": ("HELIOS", "HELIOS", "HELIOS"),
        "gaia": ("GAIA", "GAIA", "GAIA"),
        "theoros": ("THEOROS", "THEOROS", "THEOROS"),
        "argus": ("ARGUS", "ARGUS", "ARGUS"),
        "hub": ("AIMarket Hub", "AIMarket Hub", "AIMarket Hub"),
        "factory": ("AI-Factory", "AI-Factory", "AI-Factory"),
    }
    idx = {"en": 0, "ru": 1, "es": 2}.get(locale, 0)
    default = (node_id.upper(), node_id.upper(), node_id.upper())
    return labels.get(node_id, default)[idx]


def append_nav_hint(answer: str, actions: list[dict[str, Any]], locale: str) -> str:
    if not actions or not answer:
        return answer
    focus = next((a for a in actions if a.get("type") == "focus_node"), None)
    if not focus:
        return answer
    node_id = str(focus.get("node_id") or "")
    if not node_id:
        return answer
    label = nav_focus_label(node_id, locale)
    lower = answer.lower()
    if node_id in lower or label.lower() in lower:
        return answer
    hints = {
        "ru": f"\n\nОткрываю **{label}** на 3D-карте — камера переместится к узлу, панель с деталями развернётся.",
        "es": f"\n\nAbriendo **{label}** en el mapa 3D — la cámara se centra y el panel de detalles se despliega.",
        "en": f"\n\nOpening **{label}** on the 3D map — flying the camera there and expanding the detail panel.",
    }
    return answer + hints.get(locale, hints["en"])

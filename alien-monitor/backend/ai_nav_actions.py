"""Detect map-navigation intents from AI chat questions."""

from __future__ import annotations

import re
from typing import Any

# Core nodes the monitor can focus — aliases cover the five base locales
# (en / ru / es / fr / zh) plus common transliterations.
NODE_ALIASES: dict[str, tuple[str, ...]] = {
    "skopos": (
        "skopos", "σκοπός", "скопос", "скopos", "skopós", "斯科波斯",
    ),
    "metis": (
        "metis", "μῆτις", "метис", "μητις", "métis", "墨提斯", "梅蒂斯",
    ),
    "dioscuri": (
        "dioscuri", "диоскур", "castor", "pollux", "mnemosyne",
        "dioscures", "dioskouroi", "狄奥斯库里", "狄奧斯庫里",
    ),
    "helios": (
        "helios", "гелиос", "helios agent", "hélios", "helíos",
        "赫利俄斯", "赫利奥斯",
    ),
    # RU short names ending in -я need accusative -ю too ("покажи гею").
    "gaia": (
        "gaia", "gaïa",
        "гайя", "гайю", "гея", "гею", "геи",
        "iot", "айот", "датчик", "сенсор", "sensor", "capteur", "传感器", "感測器",
        "盖亚", "蓋亞", "盖娅", "蓋婭",
    ),
    "theoros": (
        "theoros", "теорос", "the canon", "the-canon", "théoros", "特奥罗斯", "特奧羅斯",
    ),
    "argus": (
        "argus", "аргус", "argus-3", "argus3", "阿格斯",
    ),
    "hub": (
        "hub", "хаб", "aimarket hub", "aimarket", "concentrateur", "中枢", "中樞", "枢纽",
    ),
    "factory": (
        "factory", "фабрик", "ai-factory", "ai factory", "usine", "fabrique",
        "工厂", "工廠", "人工智能工厂",
    ),
    "mesh": (
        "mesh", "service mesh", "меш", "ai service mesh", "maillage", "服务网格", "服務網格",
    ),
    "acex": ("acex",),
    "federation": (
        "federation", "федерац", "fédération", "federación", "联邦", "聯盟",
    ),
    "lottery": (
        "lottery", "лотере", "loterie", "lotería", "彩票", "抽奖",
    ),
    "plugins": (
        "plugins", "плагин", "greffons", "插件",
    ),
    "desktop_apps": (
        "desktop", "десктоп", "flutter apps", "bureau", "桌面",
    ),
    "platon": (
        "platon", "платон", "umbral", "platon", "柏拉图", "柏拉圖",
    ),
    "lumen": (
        "lumen", "люmen", "репутац", "réputation", "声誉", "聲譽",
    ),
}

# Five base locales: en / ru / es / fr / zh (stems — substring match).
NAV_VERBS = (
    # en
    "show", "open", "find", "zoom", "focus", "fly", "navigate", "go to", "take me",
    "center", "highlight", "select", "display", "bring",
    # ru
    "покаж", "найди", "открой", "перейди", "сфокус", "центр", "выведи",
    # es
    "muéstr", "muestr", "encuentr", "abre", "naveg", "enfoc", "centr",
    # fr
    "montre", "montr", "ouvre", "trouv", "navigu", "affich", "amène", "amene",
    "sélectionn", "selectionn", "survole", "vole vers", "emmène", "emmene",
    # zh (simplified + common traditional)
    "显示", "顯示", "打开", "打開", "找到", "飞到", "飛到", "聚焦", "导航", "導航",
    "带我", "帶我", "看看", "定位",
)

# "where is X" markers — paired with a node match (no verb required).
WHERE_MARKERS = (
    "where", "где",
    "dónde", "donde",
    "où",
    "哪里", "哪兒", "哪儿", "在哪", "何处", "何處",
)

CORE_GRAPH_NODES = frozenset(NODE_ALIASES.keys()) | {
    "ethereum", "solana", "evm_escrow", "solana_escrow", "nft_contract",
    "sdk_dart", "sdk_typescript", "sdk_rust", "cli", "widget",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _alias_forms(alias: str) -> tuple[str, ...]:
    """Expand short RU aliases with common case endings.

    Substring match works for stems ("метис" ⊂ "метиса"), but names ending in
    -я/-а change the final letter in accusative ("гея" → "гею"), so nominative
    is not a prefix. Keep this tiny — no full morphology.
    """
    forms = [alias]
    if len(alias) < 3:
        return tuple(forms)
    last = alias[-1]
    stem = alias[:-1]
    if last == "я":
        forms.extend((stem + "ю", stem + "и", stem + "ей", stem + "ею"))
    elif last == "а" and not alias.isascii():
        forms.extend((stem + "у", stem + "ы", stem + "е"))
    return tuple(dict.fromkeys(forms))


def _match_node(question: str) -> str | None:
    q = _normalize(question)
    best: tuple[int, str] | None = None
    for node_id, aliases in NODE_ALIASES.items():
        for alias in aliases:
            for form in _alias_forms(alias):
                if form in q:
                    score = len(form)
                    if best is None or score > best[0]:
                        best = (score, node_id)
                    break
    return best[1] if best else None


def _has_nav_intent(question: str) -> bool:
    q = _normalize(question)
    if any(v in q for v in NAV_VERBS):
        return True
    # "where is skopos" / "где skopos" / "où est gaia" / "盖亚在哪里"
    if any(m in q for m in WHERE_MARKERS) and _match_node(q):
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
    # Product names stay Latin across the five base locales.
    labels = {
        "skopos": "SKOPOS",
        "metis": "METIS",
        "dioscuri": "DIOSCURI",
        "helios": "HELIOS",
        "gaia": "GAIA",
        "theoros": "THEOROS",
        "argus": "ARGUS",
        "hub": "AIMarket Hub",
        "factory": "AI-Factory",
    }
    return labels.get(node_id, node_id.upper())


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
        "fr": f"\n\nJ’ouvre **{label}** sur la carte 3D — la caméra se centre et le panneau de détails s’ouvre.",
        "zh": f"\n\n正在 3D 地图上打开 **{label}** — 镜头将飞向该节点并展开详情面板。",
        "en": f"\n\nOpening **{label}** on the 3D map — flying the camera there and expanding the detail panel.",
    }
    return answer + hints.get(locale, hints["en"])

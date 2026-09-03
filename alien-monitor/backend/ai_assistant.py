"""
Alien Monitor AI — multi-provider LLM + live ecosystem state in the prompt.
Uses the same provider ids / YAML shape as aicom (data/config/model_providers.yaml).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import yaml

_MONITOR_ROOT = Path(__file__).resolve().parent.parent
_AICOM_ROOT = _MONITOR_ROOT.parent

DEFAULT_PROVIDER = "deepseek_api"
DEFAULT_MODEL_HEAVY = "deepseek-v4-pro"
DEFAULT_MODEL_LIGHT = "deepseek-v4-flash"

LOCALE_INSTRUCTIONS: dict[str, str] = {
    "en": "Reply in English.",
    "ru": "Отвечай на русском языке.",
    "es": "Responde en español.",
}

LOCALE_NAMES: dict[str, str] = {
    "en": "English",
    "ru": "Russian",
    "es": "Spanish",
}

EMPTY_QUESTION: dict[str, str] = {
    "en": "Please ask a question about the AIMarket ecosystem.",
    "ru": "Задайте вопрос об экосистеме AIMarket.",
    "es": "Haz una pregunta sobre el ecosistema AIMarket.",
}

_config_cache: dict[str, Any] | None = None


def normalize_locale(raw: str) -> str:
    code = (raw or "en").strip().lower()[:2]
    return code if code in LOCALE_INSTRUCTIONS else "en"


def detect_question_locale(question: str) -> str | None:
    """Guess language from user text (Latin / Cyrillic / Spanish markers)."""
    text = (question or "").strip()
    if not text:
        return None
    cyrillic = sum(1 for c in text if "\u0400" <= c <= "\u04ff")
    latin = sum(1 for c in text if c.isalpha() and ord(c) < 128)
    lower = text.lower()
    spanish_markers = sum(1 for c in lower if c in "áéíóúñü¿¡")
    spanish_words = ("qué", "cómo", "cuál", "dónde", "por qué", "cuánto", "cuáles")
    if cyrillic >= 2 and cyrillic >= latin:
        return "ru"
    if spanish_markers >= 1 or any(w in lower for w in spanish_words):
        return "es"
    if latin >= 2:
        return "en"
    return None


def resolve_response_locale(question: str, ui_locale: str) -> str:
    """Prefer the question language; fall back to the UI locale."""
    ui = normalize_locale(ui_locale)
    detected = detect_question_locale(question)
    return detected or ui


def _config_paths() -> list[Path]:
    custom = os.getenv("ALIEN_LLM_CONFIG", "").strip()
    if custom:
        return [Path(custom)]
    return [
        _AICOM_ROOT / "data" / "config" / "model_providers.yaml",
        _MONITOR_ROOT / "config" / "model_providers.yaml",
        _MONITOR_ROOT / "config" / "model_providers.example.yaml",
    ]


def load_providers_config() -> dict[str, Any]:
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    for path in _config_paths():
        if path.is_file():
            with open(path, encoding="utf-8") as f:
                _config_cache = yaml.safe_load(f) or {}
            return _config_cache

    _config_cache = {
        "default_provider": DEFAULT_PROVIDER,
        "providers": {
            DEFAULT_PROVIDER: {
                "api_key_env": "DEEPSEEK_API_KEY",
                "base_url": "https://api.deepseek.com/v1",
                "enabled": True,
                "models": {"heavy": DEFAULT_MODEL_HEAVY, "light": DEFAULT_MODEL_LIGHT},
                "provider_type": "openai_compatible",
            },
        },
    }
    return _config_cache


def _resolve_api_key(pconf: dict) -> str:
    if pconf.get("api_key"):
        return str(pconf["api_key"])
    env_name = pconf.get("api_key_env")
    if env_name:
        return os.environ.get(str(env_name), "")
    return ""


def list_providers() -> dict[str, Any]:
    """Providers available for the monitor AI (enabled + has API key or local)."""
    cfg = load_providers_config()
    default = cfg.get("default_provider") or DEFAULT_PROVIDER
    out: list[dict[str, Any]] = []

    for name, pconf in (cfg.get("providers") or {}).items():
        if not isinstance(pconf, dict):
            continue
        if pconf.get("enabled") is False:
            continue
        ptype = pconf.get("provider_type", "openai_compatible")
        if ptype == "local_ollama":
            # Ollama uses native API — skip for monitor chat unless wired later
            continue
        api_key = _resolve_api_key(pconf)
        if ptype != "openai_compatible" and ptype != "anthropic" and not api_key:
            continue
        if ptype == "openai_compatible" and pconf.get("api_key_env") and not api_key:
            # key missing in env — still list but mark unavailable
            available = False
        else:
            available = bool(api_key) or pconf.get("api_key_env") is None

        models = pconf.get("models") or {}
        out.append({
            "id": name,
            "provider_type": ptype,
            "base_url": pconf.get("base_url", ""),
            "models": {
                "heavy": models.get("heavy", DEFAULT_MODEL_HEAVY),
                "light": models.get("light", DEFAULT_MODEL_LIGHT),
            },
            "available": available,
            "is_default": name == default,
        })

    out.sort(key=lambda x: (not x["is_default"], x["id"]))
    return {
        "default_provider": default,
        "default_model": DEFAULT_MODEL_HEAVY,
        "providers": out,
    }


def build_live_context(state: dict | None, mode: str, selected_node_id: str | None = None) -> str:
    """Compact JSON snapshot for the system prompt — tick, summary, nodes, recent activity."""
    if not state:
        return json.dumps(
            {"monitor_mode": mode, "note": "No live state snapshot yet — answers use static ecosystem knowledge only."},
            ensure_ascii=False,
        )

    summary = state.get("summary") or {}
    nodes_in = state.get("nodes") or []
    priority_ids = (
        "hub", "factory", "mesh", "skopos", "metis", "dioscuri", "helios", "argus",
        "acex", "federation", "lottery", "plugins", "desktop_apps",
    )
    seen: set[str] = set()
    ordered: list[dict] = []
    by_id = {n.get("id"): n for n in nodes_in if isinstance(n, dict) and n.get("id")}
    for pid in priority_ids:
        if pid in by_id:
            ordered.append(by_id[pid])
            seen.add(pid)
    for n in nodes_in:
        if not isinstance(n, dict):
            continue
        nid = n.get("id")
        if nid and nid not in seen:
            ordered.append(n)
            seen.add(nid)
    nodes_out = []
    for n in ordered[:48]:
        if not isinstance(n, dict):
            continue
        entry: dict[str, Any] = {
            "id": n.get("id"),
            "label": n.get("label"),
            "group": n.get("group"),
            "status": n.get("status"),
            "metrics": n.get("metrics") or {},
        }
        if selected_node_id and n.get("id") == selected_node_id:
            entry["selected"] = True
            entry["description"] = n.get("description")
            if n.get("children"):
                entry["children"] = n.get("children")
        nodes_out.append(entry)

    events = (state.get("events") or [])[-8:]
    transactions = (state.get("transactions") or [])[-8:]
    channels = (state.get("channels") or [])[-5:]

    payload: dict[str, Any] = {
        "monitor_mode": mode,
        "tick": state.get("tick", summary.get("tick")),
        "ts": state.get("ts"),
        "summary": summary,
        "scenario": state.get("scenario"),
        "nodes": nodes_out,
        "recent_events": events,
        "recent_transactions": transactions,
        "open_channels_sample": channels,
        "funding_events_recent": (state.get("funding_events") or [])[-3:],
    }
    if selected_node_id:
        payload["selected_node_id"] = selected_node_id

    return json.dumps(payload, ensure_ascii=False, default=str)


def build_system_prompt(
    ecosystem_context: str,
    locale: str,
    live_context: str,
) -> str:
    lang = LOCALE_NAMES.get(locale, "English")
    locale_rule = LOCALE_INSTRUCTIONS.get(locale, LOCALE_INSTRUCTIONS["en"])
    return (
        ecosystem_context
        + "\n\n## LIVE MONITOR SNAPSHOT (authoritative for current tick/metrics)\n"
        + "Use these values when the user asks about «now», current mode, metrics, nodes, or activity.\n"
        + live_context
        + "\n\n## RESPONSE LANGUAGE (mandatory)\n"
        + f"Write your entire answer in {lang} only. {locale_rule} "
        + "Do not switch languages mid-answer.\n"
        + "When citing numbers, prefer the LIVE MONITOR SNAPSHOT. "
        + "If monitor_mode is test, note that metrics are simulated."
    )


async def generate_answer(
    *,
    question: str,
    locale: str,
    system_prompt: str,
    provider_id: str | None = None,
    model_role: str = "heavy",
) -> tuple[str, dict[str, Any]]:
    """
    Call configured LLM provider. Returns (answer_text, meta).
    """
    cfg = load_providers_config()
    pid = provider_id or cfg.get("default_provider") or DEFAULT_PROVIDER
    providers = cfg.get("providers") or {}
    pconf = providers.get(pid)
    if not isinstance(pconf, dict):
        pid = cfg.get("default_provider") or DEFAULT_PROVIDER
        pconf = providers.get(pid) or {}

    role = model_role if model_role in ("heavy", "light") else "heavy"
    models = pconf.get("models") or {}
    model = models.get(role) or models.get("heavy") or DEFAULT_MODEL_HEAVY
    api_key = _resolve_api_key(pconf)
    ptype = pconf.get("provider_type", "openai_compatible")
    base_url = (pconf.get("base_url") or "https://api.deepseek.com/v1").rstrip("/")
    max_tokens = int((pconf.get("capabilities") or {}).get("max_tokens") or 1024)
    max_tokens = min(max_tokens, 4096)

    meta = {"provider": pid, "model": model, "model_role": role}

    if ptype == "anthropic":
        if not api_key:
            raise RuntimeError(f"Provider {pid}: missing API key")
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{base_url}/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": question}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            blocks = data.get("content") or []
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            return text.strip(), meta

    # openai_compatible (DeepSeek, Groq, Together, LM Studio, …)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": 0.3,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        return text.strip(), meta


def any_provider_configured() -> bool:
    listed = list_providers()["providers"]
    return any(p.get("available") for p in listed)

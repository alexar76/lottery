"""Tests for live-state AI context and provider registry."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from ai_assistant import (  # noqa: E402
    build_live_context,
    build_system_prompt,
    detect_question_locale,
    list_providers,
    normalize_locale,
    resolve_response_locale,
)


def test_normalize_locale():
    assert normalize_locale("ru-RU") == "ru"
    assert normalize_locale("xx") == "en"


def test_detect_question_locale():
    assert detect_question_locale("How do payment channels work?") == "en"
    assert detect_question_locale("Как работают платёжные каналы?") == "ru"
    assert detect_question_locale("¿Cómo funcionan los canales de pago?") == "es"


def test_resolve_response_locale_prefers_question():
    assert resolve_response_locale("How do payment channels work?", "ru") == "en"
    assert resolve_response_locale("Как работает хаб?", "en") == "ru"
    assert resolve_response_locale("???", "ru") == "ru"


def test_build_live_context_includes_tick_and_nodes():
    state = {
        "tick": 42,
        "ts": "2026-05-24T12:00:00Z",
        "summary": {"mode": "test", "tick": 42, "agents_online": 3},
        "nodes": [
            {"id": "hub", "label": "Hub", "group": "core", "status": "active", "metrics": {"peers": 2}},
        ],
        "events": [{"id": "e1", "action": "invoke"}],
        "transactions": [],
    }
    ctx = json.loads(build_live_context(state, "test", "hub"))
    assert ctx["tick"] == 42
    assert ctx["nodes"][0]["id"] == "hub"
    assert ctx["nodes"][0]["selected"] is True
    assert len(ctx["recent_events"]) == 1


def test_build_live_context_empty():
    ctx = json.loads(build_live_context(None, "real"))
    assert ctx["monitor_mode"] == "real"
    assert "note" in ctx


def test_list_providers_has_default():
    data = list_providers()
    assert data["default_provider"]
    assert isinstance(data["providers"], list)


def test_system_prompt_embeds_live_json():
    prompt = build_system_prompt("STATIC", "ru", '{"tick":1}')
    assert "LIVE MONITOR SNAPSHOT" in prompt
    assert '{"tick":1}' in prompt
    assert "русском" in prompt
    assert "RESPONSE LANGUAGE" in prompt

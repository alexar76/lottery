"""Oracle family URL wiring for remote liveness polls."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def test_oracle_live_url_defaults_to_portal_paths(monkeypatch):
    monkeypatch.delenv("ALIEN_ORACLE_PORTAL", raising=False)
    monkeypatch.delenv("ALIEN_ORACLE_PLATON_URL", raising=False)
    monkeypatch.delenv("ALIEN_ORACLE_CHRONOS_URL", raising=False)
    monkeypatch.delenv("ALIEN_ORACLE_FAMILY_URL", raising=False)

    import oracle_family

    importlib.reload(oracle_family)

    assert oracle_family.oracle_live_url("platon") == "https://oracles.modelmarket.dev"
    assert oracle_family.oracle_live_url("chronos") == "https://oracles.modelmarket.dev/chronos"
    assert oracle_family.oracle_live_url("lattice") == "https://oracles.modelmarket.dev/family"
    assert oracle_family.CAVE["live_url"] == "https://oracles.modelmarket.dev/platon"


def test_oracle_live_url_env_override(monkeypatch):
    monkeypatch.setenv("ALIEN_ORACLE_CHRONOS_URL", "http://127.0.0.1:9300")
    import oracle_family

    importlib.reload(oracle_family)
    assert oracle_family.oracle_live_url("chronos") == "http://127.0.0.1:9300"

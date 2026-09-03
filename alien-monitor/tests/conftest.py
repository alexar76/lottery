"""Shared pytest hooks — env must be set before backend.main is imported."""

from __future__ import annotations

import os

os.environ.setdefault("ALIEN_API_TOKEN", "test-monitor-token")
os.environ.setdefault("ALIEN_UNIVERSE_AUTO_START", "0")
os.environ.setdefault("ALIEN_MODE", "test")
os.environ.setdefault("ALIEN_DISABLE_BROADCASTER", "1")

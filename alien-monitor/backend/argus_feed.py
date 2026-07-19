"""In-memory Argus verifiable-run feed for the monitor.

A live Argus instance POSTs its latest run to ``/api/argus/run``; the monitor
attaches it to the ``argus`` node so clicking the node shows the real oracle
calls, WARDEN blocks, hires and the sealed receipt. Until a live run is pushed,
a representative DEFAULT run is shown so the panel is never empty.

Hardened like ``live_lottery_feed``: strings are length-capped and numbers
coerced finite, so a malformed push can never reach the frontend as a bad value.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

ARGUS_RUN_TTL = 120.0
_BEAT_KIND = ("oracle", "warden", "hire", "receipt")
_BEAT_STATUS = ("ok", "blocked", "paid", "sealed")
_MAX_BEATS = 12

# Shown until a live Argus run is pushed. Mirrors the frontend ArgusRunData shape.
DEFAULT_ARGUS_RUN: dict = {
    "id": "run_demo_7f3a",
    "goal": "Draw a fair winner from a verified random seed — and don't get owned doing it.",
    "beats": [
        {"kind": "oracle", "title": "Called a verifiable oracle",
         "detail": "platon.random@v1 → Ed25519-signed, unbiasable randomness + proof",
         "meta": "0x9f3c…a1 · proof ✓ · $0.004", "status": "ok"},
        {"kind": "warden", "title": "WARDEN refused a malicious tool",
         "detail": "fs-helper exposed an \"exfiltrate_env\" tool with a hidden-unicode injection",
         "meta": "gate: static-scan · TOOL_DEF_INJECTION · severity high", "status": "blocked"},
        {"kind": "hire", "title": "Hired another agent",
         "detail": "discover → open USDC channel → invoke translate@v2 → settle (reputation-checked)",
         "meta": "TranslatorPro · LUMEN 0.81 · $0.012 · receipt ✓", "status": "paid"},
        {"kind": "receipt", "title": "Sealed a verifiable receipt",
         "detail": "Every step is signed. Verify the proofs — don't trust the agent.",
         "meta": "sha256 0x4b…e9 · signer 0x12…35", "status": "sealed"},
    ],
    "spendUsd": 0.016,
    "receiptHash": "0x4b9e…e9",
    "signer": "0x12…35",
}

_LIVE: dict = {"ts": 0.0, "run": None}


def _finite(value, default: float = 0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _clean_beat(b) -> dict:
    b = b if isinstance(b, dict) else {}
    kind = str(b.get("kind", "oracle"))
    if kind not in _BEAT_KIND:
        kind = "oracle"
    status = str(b.get("status", "ok"))
    if status not in _BEAT_STATUS:
        status = "ok"
    return {
        "kind": kind,
        "title": str(b.get("title", ""))[:80],
        "detail": str(b.get("detail", ""))[:240],
        "meta": str(b.get("meta", ""))[:160],
        "status": status,
    }


def _clean_run(p) -> dict:
    p = p if isinstance(p, dict) else {}
    beats = [_clean_beat(b) for b in (p.get("beats") or [])[:_MAX_BEATS] if isinstance(b, dict)]
    run = {
        "id": str(p.get("id", "run"))[:64],
        "goal": str(p.get("goal", ""))[:240],
        "beats": beats or list(DEFAULT_ARGUS_RUN["beats"]),
        "spendUsd": _finite(p.get("spendUsd", 0)),
        "receiptHash": str(p.get("receiptHash", ""))[:80],
        "signer": str(p.get("signer", ""))[:80],
    }
    vu = p.get("verifyUrl")
    if isinstance(vu, str) and vu.startswith("http"):
        run["verifyUrl"] = vu[:300]
    return run


def set_argus_run(payload: dict) -> None:
    _LIVE["ts"] = datetime.now(UTC).timestamp()
    _LIVE["run"] = _clean_run(payload)


def argus_run_if_fresh() -> dict | None:
    if not _LIVE["run"]:
        return None
    if datetime.now(UTC).timestamp() - _LIVE["ts"] > ARGUS_RUN_TTL:
        return None
    return dict(_LIVE["run"])


def argus_run_for_mode(mode: str = "real") -> dict | None:
    """Fresh pushed run, or scripted demo in TEST only."""
    fresh = argus_run_if_fresh()
    if fresh:
        return fresh
    if mode == "test":
        return dict(DEFAULT_ARGUS_RUN)
    return None


def argus_run_or_default() -> dict:
    """Backward-compat: demo fallback (prefer ``argus_run_for_mode`` in graph code)."""
    return argus_run_if_fresh() or dict(DEFAULT_ARGUS_RUN)


def clear_argus_run() -> None:
    """Test helper — drop any pushed run."""
    _LIVE.update(ts=0.0, run=None)

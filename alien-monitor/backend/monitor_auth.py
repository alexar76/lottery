"""Bearer-token guard for sensitive Alien Monitor API routes.

Behaviour:
- Configured token (``ALIEN_API_TOKEN`` / ``ALIEN_MONITOR_API_TOKEN``): always required.
- No token AND not production: allowed (local dev / smoke tests).
- No token AND production: **refused** with 503 — refuse to fail open in prod.

Production is detected via ``ALIEN_ENV`` / ``AIFACTORY_ENV`` ∈ {production|prod|live}
or any of ``AIFACTORY_PROD=1`` / ``AIFACTORY_PRODUCTION=1``. This mirrors the same
production-mode detection used by ``services/ai_market_protocol/config.py`` and
``security/prod_startup_guard.py`` — keeping a single source of truth prevents the
classic "looks safe in staging, wide-open in prod" failure mode.
"""

from __future__ import annotations

import logging
import os
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

_PRODUCTION_ENV_TAGS = frozenset({"production", "prod", "live"})


def monitor_api_token() -> str:
    return (os.environ.get("ALIEN_API_TOKEN") or os.environ.get("ALIEN_MONITOR_API_TOKEN") or "").strip()


def _is_production_env() -> bool:
    for key in ("ALIEN_ENV", "AIFACTORY_ENV"):
        if os.environ.get(key, "").strip().lower() in _PRODUCTION_ENV_TAGS:
            return True
    for key in ("AIFACTORY_PROD", "AIFACTORY_PRODUCTION"):
        if os.environ.get(key, "").strip().lower() in ("1", "true", "yes", "on"):
            return True
    return False


_PROD_NO_TOKEN_WARNED = False


def require_monitor_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    expected = monitor_api_token()
    if not expected:
        if _is_production_env():
            global _PROD_NO_TOKEN_WARNED
            if not _PROD_NO_TOKEN_WARNED:
                logger.error(
                    "ALIEN_API_TOKEN is not set in production — refusing all auth-gated requests. "
                    "Set ALIEN_API_TOKEN (or ALIEN_MONITOR_API_TOKEN) to a unique secret."
                )
                _PROD_NO_TOKEN_WARNED = True
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="ALIEN_API_TOKEN not configured; refusing in production",
            )
        # Non-production: allow unauthenticated access for local dev convenience.
        return
    token = (credentials.credentials if credentials else "").strip()
    # Constant-time compare to avoid leaking the token via timing side-channels.
    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def monitor_public_read_allowed() -> bool:
    """Public demo UI (summary/topology/ws stream) without Bearer token."""
    if not _is_production_env():
        return True
    return os.environ.get("ALIEN_PUBLIC_READ", "").strip().lower() in ("1", "true", "yes", "on")


def require_monitor_read_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Read APIs (summary, topology, Pulse /api/pulse/state): open in dev; in production require token unless ALIEN_PUBLIC_READ=1."""
    if monitor_public_read_allowed():
        return
    require_monitor_auth(credentials)


def require_monitor_state_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Heavy /api/state dump — always token-gated in production (even public demo)."""
    if not _is_production_env():
        return
    require_monitor_auth(credentials)


def monitor_control_token_valid(token: str | None) -> bool:
    """Validate Bearer token for WebSocket control commands (set_mode, bootstrap)."""
    expected = monitor_api_token()
    if not expected:
        return not _is_production_env()
    got = (token or "").strip()
    return bool(got) and secrets.compare_digest(got, expected)


def monitor_ws_token_valid(token: str | None) -> bool:
    """Validate ?token= on WebSocket connect for full state stream."""
    return monitor_control_token_valid(token)


def cors_allow_origins() -> list[str]:
    raw = (os.environ.get("ALIEN_CORS_ORIGINS") or "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [
        "http://127.0.0.1:9100",
        "http://localhost:9100",
        "http://127.0.0.1:9080",
        "http://localhost:9080",
        "https://magic-ai-factory.com",
        "https://www.magic-ai-factory.com",
        "https://modeldev.modelmarket.dev",
    ]

"""Notify Alien Monitor when AI-Factory ships a new product."""

from __future__ import annotations

import os

import httpx

MONITOR_URL = os.environ.get(
    "ALIEN_MONITOR_URL",
    "http://127.0.0.1:9100/api/universe/materialize",
).rstrip("/")
if not MONITOR_URL.endswith("/materialize"):
    if MONITOR_URL.endswith("/api"):
        MONITOR_URL = f"{MONITOR_URL}/universe/materialize"
    elif "/api/" not in MONITOR_URL:
        MONITOR_URL = f"{MONITOR_URL}/api/universe/materialize"


def notify_product_materialized(product: dict, *, timeout: float = 5.0) -> bool:
    """POST product payload to monitor; returns True on success."""
    body = {
        "id": product.get("id") or product.get("product_id"),
        "name": product.get("name") or product.get("product_name"),
        "category": product.get("category") or product.get("type"),
        "description": product.get("description") or product.get("idea") or product.get("tagline"),
        "version": product.get("version"),
    }
    if not body.get("id"):
        return False
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(MONITOR_URL, json=body)
            return r.status_code == 200
    except Exception:
        return False

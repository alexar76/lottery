"""Verification of short-lived work-seat entitlements from federated AIMarket Hubs."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import time
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_MAX_TTL_S = 600
_MAX_CLOCK_SKEW = 60


class EligibilityError(ValueError):
    pass


def normalize_hub_url(value: str) -> str:
    raw = (value or "").strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise EligibilityError("hub URL must be absolute HTTP(S)")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise EligibilityError("hub URL must not contain credentials, query, or fragment")
    host = parsed.hostname.lower()
    port = parsed.port
    netloc = f"{host}:{port}" if port else host
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path.rstrip("/"), "", ""))


def participant_id(hub_url: str, agent_id: str) -> str:
    subject = (agent_id or "").strip()
    if not subject or len(subject) > 160 or any(c in subject for c in "\r\n\t"):
        raise EligibilityError("invalid agent_id")
    return "0x" + hashlib.sha256(
        f"{normalize_hub_url(hub_url)}\n{subject}".encode("utf-8")
    ).hexdigest()


def entitlement_canonical(entitlement: dict[str, Any]) -> str:
    claims = {
        "agent_id": str(entitlement.get("agent_id") or ""),
        "expires_at": int(entitlement.get("expires_at") or 0),
        "hub_url": normalize_hub_url(str(entitlement.get("hub_url") or "")),
        "issued_at": int(entitlement.get("issued_at") or 0),
        "nonce": str(entitlement.get("nonce") or ""),
        "participant_id": str(entitlement.get("participant_id") or "").lower(),
        "purpose": "ai-agent-lottery-work-seat-v1",
        "wallet": str(entitlement.get("wallet") or "").lower(),
    }
    return json.dumps(claims, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class FederationEligibilityVerifier:
    """Resolve Hub keys only through one configured federation registry."""

    def __init__(
        self,
        registry_url: str,
        *,
        timeout: float = 8.0,
        key_resolver: Callable[[str], str] | None = None,
    ) -> None:
        self.registry_url = normalize_hub_url(registry_url)
        self.timeout = timeout
        self.key_resolver = key_resolver
        self._key_cache: tuple[float, dict[str, str]] = (0.0, {})

    def _registry_keys(self) -> dict[str, str]:
        now = time.time()
        stamp, cached = self._key_cache
        if cached and now - stamp < 300:
            return cached
        keys: dict[str, str] = {}
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                own = client.get(f"{self.registry_url}/.well-known/ai-market.json")
                own.raise_for_status()
                own_body = own.json()
                own_key = str(own_body.get("signer_public_key") or "").strip()
                if own_key:
                    keys[self.registry_url] = own_key
                peers = client.get(f"{self.registry_url}/ai-market/v2/federation/peers")
                peers.raise_for_status()
                for peer in peers.json().get("peers") or []:
                    if not isinstance(peer, dict):
                        continue
                    if peer.get("trusted") is not True or str(peer.get("status") or "active") != "active":
                        continue
                    key = str(peer.get("public_key") or "").strip()
                    if not key:
                        continue
                    try:
                        keys[normalize_hub_url(str(peer.get("url") or ""))] = key
                    except EligibilityError:
                        continue
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise EligibilityError(f"federation registry unavailable: {type(exc).__name__}") from exc
        if not keys:
            raise EligibilityError("federation registry returned no pinned Hub keys")
        self._key_cache = (now, keys)
        return keys

    def _pinned_key(self, hub_url: str) -> str:
        if self.key_resolver is not None:
            return str(self.key_resolver(hub_url) or "")
        return self._registry_keys().get(normalize_hub_url(hub_url), "")

    def verify(self, entitlement: dict[str, Any], *, wallet: str, now: int | None = None) -> str:
        if entitlement.get("purpose") != "ai-agent-lottery-work-seat-v1":
            raise EligibilityError("wrong entitlement purpose")
        hub_url = normalize_hub_url(str(entitlement.get("hub_url") or ""))
        agent_id = str(entitlement.get("agent_id") or "").strip()
        expected_participant = participant_id(hub_url, agent_id)
        claimed_participant = str(entitlement.get("participant_id") or "").lower()
        if claimed_participant != expected_participant:
            raise EligibilityError("participant_id does not match Hub and agent identity")
        if str(entitlement.get("wallet") or "").lower() != wallet.lower():
            raise EligibilityError("entitlement is bound to another wallet")
        issued_at = int(entitlement.get("issued_at") or 0)
        expires_at = int(entitlement.get("expires_at") or 0)
        current = int(time.time()) if now is None else int(now)
        if not issued_at or expires_at <= issued_at or expires_at - issued_at > _MAX_TTL_S:
            raise EligibilityError("invalid entitlement lifetime")
        if issued_at > current + _MAX_CLOCK_SKEW or expires_at < current:
            raise EligibilityError("entitlement is not currently valid")
        nonce = str(entitlement.get("nonce") or "")
        if not nonce or len(nonce) > 160:
            raise EligibilityError("invalid entitlement nonce")
        signature = entitlement.get("signature")
        if not isinstance(signature, dict) or signature.get("algorithm") != "ed25519":
            raise EligibilityError("missing Ed25519 Hub signature")
        pinned = self._pinned_key(hub_url)
        if not pinned:
            raise EligibilityError("issuing Hub is not an active pinned federation member")
        carried = str(signature.get("public_key") or "")
        if carried and carried != pinned:
            raise EligibilityError("entitlement key does not match federation pin")
        try:
            public = Ed25519PublicKey.from_public_bytes(base64.b64decode(pinned, validate=True))
            sig = base64.b64decode(str(signature.get("value") or ""), validate=True)
            public.verify(sig, entitlement_canonical(entitlement).encode("utf-8"))
        except (ValueError, binascii.Error, InvalidSignature) as exc:
            raise EligibilityError("invalid Hub entitlement signature") from exc
        return expected_participant

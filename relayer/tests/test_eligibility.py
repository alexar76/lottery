from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ailottery_relayer.eligibility import (
    EligibilityError,
    FederationEligibilityVerifier,
    entitlement_canonical,
    participant_id,
)


def _signed_entitlement(*, now: int = 1_700_000_000):
    private = Ed25519PrivateKey.generate()
    public_b64 = base64.b64encode(private.public_key().public_bytes_raw()).decode("ascii")
    hub = "https://peer.example"
    entitlement = {
        "purpose": "ai-agent-lottery-work-seat-v1",
        "hub_url": hub,
        "agent_id": "agent-7",
        "participant_id": participant_id(hub, "agent-7"),
        "wallet": "0x" + "ab" * 20,
        "issued_at": now,
        "expires_at": now + 600,
        "nonce": "once-only-proof",
    }
    entitlement["signature"] = {
        "algorithm": "ed25519",
        "public_key": public_b64,
        "value": base64.b64encode(
            private.sign(entitlement_canonical(entitlement).encode("utf-8"))
        ).decode("ascii"),
    }
    return entitlement, public_b64


def test_accepts_only_a_valid_entitlement_from_the_pinned_hub():
    entitlement, public_b64 = _signed_entitlement()
    verifier = FederationEligibilityVerifier(
        "https://registry.example",
        key_resolver=lambda hub: public_b64 if hub == "https://peer.example" else "",
    )
    assert verifier.verify(
        entitlement, wallet="0x" + "AB" * 20, now=1_700_000_100
    ) == entitlement["participant_id"]


@pytest.mark.parametrize("mutation, message", [
    (lambda e: e.update(wallet="0x" + "cd" * 20), "another wallet"),
    (lambda e: e.update(participant_id="0x" + "00" * 32), "participant_id"),
    (lambda e: e.update(expires_at=e["issued_at"] + 601), "lifetime"),
])
def test_rejects_tampered_or_overlong_entitlements(mutation, message):
    entitlement, public_b64 = _signed_entitlement()
    mutation(entitlement)
    verifier = FederationEligibilityVerifier(
        "https://registry.example", key_resolver=lambda _hub: public_b64
    )
    with pytest.raises(EligibilityError, match=message):
        verifier.verify(entitlement, wallet="0x" + "ab" * 20, now=1_700_000_100)


def test_rejects_a_self_carried_key_when_hub_is_not_pinned():
    entitlement, _public_b64 = _signed_entitlement()
    verifier = FederationEligibilityVerifier(
        "https://registry.example", key_resolver=lambda _hub: ""
    )
    with pytest.raises(EligibilityError, match="not an active pinned"):
        verifier.verify(entitlement, wallet=entitlement["wallet"], now=1_700_000_100)


def test_rejects_expired_entitlement():
    entitlement, public_b64 = _signed_entitlement()
    verifier = FederationEligibilityVerifier(
        "https://registry.example", key_resolver=lambda _hub: public_b64
    )
    with pytest.raises(EligibilityError, match="not currently valid"):
        verifier.verify(entitlement, wallet=entitlement["wallet"], now=1_700_000_601)

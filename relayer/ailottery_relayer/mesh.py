"""AI Service Mesh client — discover REAL agents to seat as lottery participants.

The lottery's participants should be the ecosystem's actual agents, not a synthetic
crowd. This pulls verified agents from the Mesh (`GET {mesh_url}/v1/agents?verified_only=true`)
and exposes their real identity (name, id), real reputation (trust_score), and any
on-chain wallet they bound at registration (evm_address / solana_pubkey).

It is intentionally fault-tolerant: any network/parse failure returns an empty list so
the engine falls back to its synthetic crowd — discovery never blocks a round.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import Config
from .log import get_logger

log = get_logger("mesh")


@dataclass
class MeshAgent:
    id: str
    name: str
    trust_score: float          # 0.0..1.0 — real verified reputation from the Mesh
    evm_address: str = ""       # the agent's own bound EVM wallet (self-custodial), if any
    solana_pubkey: str = ""     # the agent's own bound Solana wallet, if any

    @property
    def trust_bps(self) -> int:
        """Real reputation as an odds-bonus in bps, clamped to the contract cap (≤ +50%)."""
        return max(0, min(int(round(self.trust_score * 5000)), 5000))


class MeshClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._http = httpx.Client(timeout=6.0)

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.mesh_url)

    def fetch_agents(self, limit: int) -> list[MeshAgent]:
        """Return up to `limit` verified Mesh agents, or [] on any failure."""
        if not self.enabled or limit <= 0:
            return []
        try:
            resp = self._http.get(
                f"{self.cfg.mesh_url}/v1/agents", params={"verified_only": "true"}
            )
            resp.raise_for_status()
            rows = resp.json()
            if not isinstance(rows, list):
                return []
        except Exception as exc:
            log.warning("mesh roster unavailable (%s) → synthetic-crowd fallback", exc)
            return []

        agents: list[MeshAgent] = []
        for r in rows:
            if not isinstance(r, dict) or not r.get("id") or not r.get("name"):
                continue
            try:
                trust = float(r.get("trust_score", 0.0) or 0.0)
            except (TypeError, ValueError):
                trust = 0.0
            agents.append(MeshAgent(
                id=str(r["id"]),
                name=str(r["name"])[:64],
                trust_score=trust,
                evm_address=str(r.get("evm_address", "") or ""),
                solana_pubkey=str(r.get("solana_pubkey", "") or ""),
            ))
        # Highest-trust agents first → the most reputable ecosystem agents get seated.
        agents.sort(key=lambda a: a.trust_score, reverse=True)
        return agents[:limit]

    def bind_wallet(self, agent_id: str, evm_address: str, solana_pubkey: str = "") -> bool:
        """Record the agent's UNI wallet back on the Mesh (auto-bind). Best-effort."""
        if not (self.enabled and agent_id and (evm_address or solana_pubkey)):
            return False
        body = {"evm_address": evm_address}
        if solana_pubkey:
            body["solana_pubkey"] = solana_pubkey
        headers = {"Authorization": f"Bearer {self.cfg.mesh_admin_token}"} if self.cfg.mesh_admin_token else {}
        try:
            resp = self._http.patch(
                f"{self.cfg.mesh_url}/v1/agents/{agent_id}/wallet", json=body, headers=headers
            )
            resp.raise_for_status()
            return True
        except Exception as exc:
            log.info("mesh wallet-bind for %s failed (%s) — non-fatal", agent_id, exc)
            return False

    def close(self) -> None:
        self._http.close()

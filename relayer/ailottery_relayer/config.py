"""Relayer configuration — env + sponsor.yaml. One source of truth for the three
run modes (demo / live / uni).

DEMO  — fully self-contained: local anvil chain, LOCAL oracle stand-ins, play-money.
        This is what `docker compose up` runs by default; needs no external service.
LIVE  — real chain (RPC_URL) + REAL oracle invocations paid through the AIMarket Hub.
UNI   — the self-evolving universe: like demo/live plus an unknown external
        benefactor that allocates $100/week to the prize pool.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

REPO_SPONSOR_YAML = Path(__file__).resolve().parents[2] / "config" / "sponsor.yaml"
REPO_ECONOMICS_YAML = Path(__file__).resolve().parents[2] / "config" / "economics.yaml"

# Well-known PUBLIC dev keys (the standard "test test ... junk" Anvil/Hardhat mnemonic) and the
# literal default seed. Deriving per-agent wallets from any of these makes the wallets trivially
# sweepable by anyone, so they are forbidden as a production wallet seed (see _guard_wallet_seed).
_PUBLIC_DEV_SEEDS = {
    "ailottery-uni",
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
    "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
    "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
    "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a",
    "0x8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba",
}


def _b(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _guard_wallet_seed(c: "Config") -> None:
    """Fail closed: never bind real per-agent wallets from a public/default seed in production.

    In demo/uni the public Anvil seed is fine (play-money on a local chain). But in production
    (``AIFACTORY_PROD=1``) with auto-wallet enabled, deriving wallets from the default operator
    key or any well-known dev key would make every agent wallet trivially sweepable. Require an
    explicit, non-public ``UNI_WALLET_SEED`` instead of silently falling back.
    """
    if not c.uni_auto_wallet:
        return
    if os.environ.get("AIFACTORY_PROD", "").strip() != "1":
        return
    explicit = os.getenv("UNI_WALLET_SEED", "").strip()
    if not explicit:
        raise RuntimeError(
            "UNI_AUTO_WALLET is on in production (AIFACTORY_PROD=1) but UNI_WALLET_SEED is not "
            "set: agent wallets would be derived from the public operator/dev key and be "
            "trivially sweepable by anyone. Set a secret UNI_WALLET_SEED before binding wallets."
        )
    if c.uni_wallet_seed.strip().lower() in _PUBLIC_DEV_SEEDS:
        raise RuntimeError(
            "UNI_WALLET_SEED resolves to a well-known PUBLIC dev key; agent wallets would be "
            "trivially sweepable. Use a secret seed for production."
        )


@dataclass
class Config:
    mode: str = "demo"                       # demo | live | uni

    # chain
    rpc_url: str = "http://chain:8545"
    chain_id: int = 31337
    lottery_address: str = ""                # set, or read from address_file
    address_file: str = "/shared/lottery.address"

    # keys (demo = well-known anvil keys via compose env)
    operator_key: str = ""
    oracle_signer_key: str = ""              # defaults to operator_key
    treasury_key: str = ""                   # defaults to operator_key
    sponsor_key: str = ""                    # the Hub's funding account (tithe)
    benefactor_key: str = ""                 # the UNI external benefactor
    agent_keys: list[str] = field(default_factory=list)  # synthetic crowd

    # real participants — discover verified agents from the AI Service Mesh and use
    # them as the lottery roster (real name + id + trust), instead of the synthetic crowd.
    mesh_url: str = ""                       # if set, GET {mesh_url}/v1/agents?verified_only=true
    mesh_admin_token: str = ""               # Bearer token to bind wallets back to the Mesh
    mesh_max_agents: int = 8                 # cap the on-chain roster (bounded by funded keys too)

    # UNI self-custody: in the UNI emulation each verified Mesh agent gets its OWN
    # deterministic on-chain wallet (we control the chain), is funded from the faucet,
    # and signs its OWN ticket purchases — true self-custodial participation, not a
    # relayer-held custodial key. The derived address is bound back to the Mesh agent.
    uni_auto_wallet: bool = False            # default: enabled in UNI mode
    uni_wallet_seed: str = ""                # master seed for deterministic per-agent keys
    faucet_key: str = ""                     # funds agent wallets (defaults to sponsor/operator)
    agent_fund_wei: int = 5 * 10**16         # top-up target per agent wallet (covers rounds + gas)

    # oracle routing
    hub_url: str = ""                        # if set (live), invoke oracles through the Hub
    oracle_url: str = ""                     # else call the oracle-family directly
    payment_channel: str = ""                # X-Payment-Channel for paid Hub invokes
    onchain_vdf: bool = False                # build & submit a real Chronos VDF proof
    chronos_canonical_n: str = ""            # hex modulus == ChronosVDF.CANONICAL_N (required for ONCHAIN_VDF)

    # economy
    wei_per_usd: int = 10**15                # play-money scale: $1 = 0.001 ETH (display + USD→wei)
    sim_agents: bool = True                  # relayer drives a synthetic ticket-buying crowd
    sim_tickets_per_round: int = 4
    hub_routing_revenue_usd: float = 5.0     # simulated Hub routing-fee revenue per round (tithe source)
    uni_weekly_usd: float = 100.0            # UNI external benefactor allocation

    # cadence (seconds) — short in demo so rounds visibly cycle
    round_interval: float = 6.0              # pause between finishing one round and the next
    sell_window: float = 4.0                 # real seconds to let EXTERNAL agents buy before closing
    poll_interval: float = 1.0
    fast_forward: bool = True                # demo/uni: warp anvil time so windows pass quickly

    # observability
    serve_host: str = "0.0.0.0"
    serve_port: int = 8090
    monitor_url: str = ""                    # POST live economy to the Alien Monitor (optional)
    monitor_token: str = ""                  # Bearer token if the monitor is auth-gated

    # Hub-OWNED charity (the donor decides generosity + which lottery) — mirrored from
    # the Hub's config via env; overrides sponsor.yaml when set. See aimarket-hub config.
    hub_tithe_bps: int = -1                  # -1 = unset → fall back to sponsor.yaml
    hub_charity_enabled: Optional[bool] = None
    hub_lottery_address: str = ""            # the Hub's bound lottery (anti-redirect target)
    hub_tithe_interval_hours: int = 24       # the HUB pushes its accrued tithe every N hours (Hub-owned)
    demo_tithe_interval_s: float = 15.0      # accelerated cadence so the schedule is visible in the demo

    # LOTTERY-owned opex / treasurer policy (see config/economics.yaml)
    treasurer_enabled: bool = True
    treasurer_mode: str = "policy"           # policy | llm
    reserve_target_usd: float = 5.0
    economics: dict = field(default_factory=dict)

    # loaded sponsor.yaml (the binding + safety gate)
    sponsor: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Config":
        c = cls()
        c.mode = os.getenv("LOTTERY_MODE", c.mode).strip().lower()
        c.rpc_url = os.getenv("RPC_URL", c.rpc_url)
        c.chain_id = _i("CHAIN_ID", c.chain_id)
        c.lottery_address = os.getenv("LOTTERY_ADDRESS", c.lottery_address)
        c.address_file = os.getenv("LOTTERY_ADDRESS_FILE", c.address_file)

        c.operator_key = os.getenv("OPERATOR_KEY", c.operator_key)
        c.oracle_signer_key = os.getenv("ORACLE_SIGNER_KEY", "") or c.operator_key
        c.treasury_key = os.getenv("TREASURY_KEY", "") or c.operator_key
        c.sponsor_key = os.getenv("SPONSOR_KEY", "") or c.operator_key
        c.benefactor_key = os.getenv("BENEFACTOR_KEY", "") or c.sponsor_key
        keys = os.getenv("AGENT_KEYS", "").strip()
        c.agent_keys = [k.strip() for k in keys.split(",") if k.strip()]

        c.mesh_url = os.getenv("MESH_URL", c.mesh_url).rstrip("/")
        c.mesh_admin_token = os.getenv("MESH_ADMIN_TOKEN", c.mesh_admin_token)
        c.mesh_max_agents = _i("MESH_MAX_AGENTS", c.mesh_max_agents)
        c.uni_auto_wallet = _b("UNI_AUTO_WALLET", c.mode == "uni")
        # deterministic per-agent keys: seed defaults to the operator key (UNI-local secret)
        c.uni_wallet_seed = os.getenv("UNI_WALLET_SEED", "") or c.operator_key or "ailottery-uni"
        c.faucet_key = os.getenv("FAUCET_KEY", "") or c.sponsor_key or c.operator_key
        c.agent_fund_wei = _i("AGENT_FUND_WEI", c.agent_fund_wei)
        c.hub_url = os.getenv("HUB_URL", c.hub_url).rstrip("/")
        c.oracle_url = os.getenv("ORACLE_URL", c.oracle_url).rstrip("/")
        c.payment_channel = os.getenv("PAYMENT_CHANNEL", c.payment_channel)
        c.onchain_vdf = _b("ONCHAIN_VDF", c.onchain_vdf)
        c.chronos_canonical_n = os.getenv("CHRONOS_CANONICAL_N", c.chronos_canonical_n)

        c.wei_per_usd = _i("WEI_PER_USD", c.wei_per_usd)
        c.sim_agents = _b("SIM_AGENTS", c.sim_agents)
        c.sim_tickets_per_round = _i("SIM_TICKETS_PER_ROUND", c.sim_tickets_per_round)
        c.hub_routing_revenue_usd = _f("HUB_ROUTING_REVENUE_USD", c.hub_routing_revenue_usd)
        c.uni_weekly_usd = _f("UNI_WEEKLY_USD", c.uni_weekly_usd)

        c.round_interval = _f("ROUND_INTERVAL", c.round_interval)
        c.sell_window = _f("SELL_WINDOW", c.sell_window)
        c.poll_interval = _f("POLL_INTERVAL", c.poll_interval)
        c.fast_forward = _b("FAST_FORWARD", c.mode in ("demo", "uni"))

        c.serve_host = os.getenv("SERVE_HOST", c.serve_host)
        c.serve_port = _i("SERVE_PORT", c.serve_port)
        c.monitor_url = os.getenv("MONITOR_URL", c.monitor_url).rstrip("/")
        c.monitor_token = os.getenv("MONITOR_TOKEN", c.monitor_token)

        # Hub-owned charity, read from HUB_* or (when co-located with the Hub) the
        # Hub's own AIMARKET_CHARITY_* env — single source of truth, no double config.
        c.hub_tithe_bps = _i("HUB_TITHE_BPS", _i("AIMARKET_CHARITY_TITHE_BPS", -1))
        _hce = os.getenv("HUB_CHARITY_ENABLED", os.getenv("AIMARKET_CHARITY_ENABLED"))
        c.hub_charity_enabled = (_hce.strip().lower() in ("1", "true", "yes", "on")) if _hce is not None else None
        c.hub_lottery_address = os.getenv("HUB_LOTTERY_ADDRESS", os.getenv("AIMARKET_CHARITY_LOTTERY_ADDRESS", ""))
        c.hub_tithe_interval_hours = _i("HUB_TITHE_INTERVAL_HOURS", _i("AIMARKET_CHARITY_INTERVAL_HOURS", 24))
        c.demo_tithe_interval_s = _f("DEMO_TITHE_INTERVAL_S", c.demo_tithe_interval_s)

        c.treasurer_enabled = _b("TREASURER_ENABLED", c.treasurer_enabled)
        c.treasurer_mode = os.getenv("TREASURER_MODE", c.treasurer_mode)
        c.reserve_target_usd = _f("RESERVE_TARGET_USD", c.reserve_target_usd)
        c.economics = _load_yaml(os.getenv("ECONOMICS_YAML", str(REPO_ECONOMICS_YAML)))

        c.sponsor = _load_yaml(os.getenv("SPONSOR_YAML", str(REPO_SPONSOR_YAML)))
        _guard_wallet_seed(c)
        return c

    # ── derived ──────────────────────────────────────────────────────────────
    @property
    def is_demo(self) -> bool:
        return self.mode == "demo"

    @property
    def is_uni(self) -> bool:
        return self.mode == "uni"

    @property
    def use_live_oracles(self) -> bool:
        """Call real oracle services (Hub or direct) rather than local stand-ins."""
        return bool(self.hub_url or self.oracle_url)

    def usd_to_wei(self, usd: float) -> int:
        return int(round(usd * self.wei_per_usd))

    def wei_to_usd(self, wei: int) -> float:
        return wei / self.wei_per_usd

    def resolved_address(self) -> str:
        if self.lottery_address:
            return self.lottery_address
        p = Path(self.address_file)
        if p.exists():
            return p.read_text().strip()
        return ""


def _load_yaml(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}
